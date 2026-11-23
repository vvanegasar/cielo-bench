"""A stalled run must surface: the watchdog reports stalls and machine sleep, and real runs on
macOS hold an idle-sleep assertion.

Regression for the first real smoke run (2026-11-22): the machine idled into sleep two seconds
after a request was sent; the request's 600 s read timeout counted only awake time, so the run
made no visible progress for hours, and progress was printed only every 200 trials.
"""

import json
import os
import subprocess
import threading
import time

import httpx
import pytest

from cielo_bench import cli, runner
from cielo_bench.providers.anthropic import AnthropicProvider
from cielo_bench.providers.simulated import SimulatedProvider
from cielo_bench.runner import RunSpec, Watchdog, execute_run
from cielo_bench.runner import caffeinate_argv as real_caffeinate_argv  # bound before the autouse patch


class _Clock:
    def __init__(self):
        self.wall, self.mono = 1_000.0, 50.0

    def tick(self, seconds, *, asleep=False):
        self.wall += seconds
        if not asleep:
            self.mono += seconds


def test_watchdog_reports_a_stall_once_per_period_and_names_the_oldest_trial():
    clock, out = _Clock(), []
    wd = Watchdog(interval_s=60, stall_s=300, emit=out.append, wall=lambda: clock.wall, mono=lambda: clock.mono)
    wd.started("trial-A")
    clock.tick(30)
    wd.started("trial-B")
    clock.tick(30)
    assert wd.check() == []
    clock.tick(240)  # 300 s without a finished trial
    (message,) = wd.check()
    assert "no trial finished in 5.0 min" in message and "2 in flight" in message and message.endswith("trial-A")
    clock.tick(60)
    assert wd.check() == []  # reported at most once per stall period
    clock.tick(300)
    assert len(wd.check()) == 1
    wd.finished("trial-A")
    wd.finished("trial-B")
    clock.tick(900)
    assert wd.check() == []  # nothing in flight: an idle run is not a stalled run
    assert len(out) == 2


def test_watchdog_detects_that_the_machine_slept():
    clock, out = _Clock(), []
    wd = Watchdog(interval_s=60, stall_s=300, emit=out.append, wall=lambda: clock.wall, mono=lambda: clock.mono)
    clock.tick(60)
    assert wd.check() == []
    clock.tick(4.5 * 3600, asleep=True)  # wall clock advances, the monotonic clock does not
    (message,) = wd.check()
    assert "asleep for about 270 min" in message
    clock.tick(60)
    assert wd.check() == []


class _StuckFirstRequest(SimulatedProvider):
    """The first request hangs for a while, like a request lost while the machine slept."""

    def __init__(self, *args, hang_s, **kwargs):
        super().__init__(*args, **kwargs)
        self._hang_s, self._first, self._lock = hang_s, True, threading.Lock()

    def complete(self, conv):
        with self._lock:
            first, self._first = self._first, False
        if first:
            time.sleep(self._hang_s)
        return super().complete(conv)


def test_a_stuck_request_is_reported_while_the_run_waits(domain, golden, tmp_path, capsys):
    provider = _StuckFirstRequest("careful", domain, golden, hang_s=0.8)
    spec = RunSpec(
        domain=domain,
        golden=golden,
        providers=[provider],
        out_dir=tmp_path / "run",
        run_id="stuck",
        simulated=True,
        conditions=("no_tool",),
        premises=("true",),
        pressures=("neutral",),
        limit_pairs=1,
        workers=1,
        heartbeat_s=0.05,
        stall_warn_s=0.2,
    )
    run_dir = execute_run(spec)
    err = capsys.readouterr().err
    trial_id = json.loads((run_dir / "trials.jsonl").read_text().splitlines()[0])["trial_id"]
    assert "[watchdog] no trial finished in" in err and trial_id in err
    assert "[1/1] trials done" in err
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "complete" and manifest["keep_awake"] is None  # simulated: never held


def test_caffeinate_command_on_macos_only(monkeypatch):
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/caffeinate")
    monkeypatch.setattr(runner.sys, "platform", "darwin")
    assert real_caffeinate_argv() == ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]
    monkeypatch.setattr(runner.sys, "platform", "linux")
    assert real_caffeinate_argv() is None
    monkeypatch.setattr(runner.sys, "platform", "darwin")
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    assert real_caffeinate_argv() is None


class FakeHelper:
    def __init__(self, argv=None, *, stubborn=False, **kwargs):
        self.argv, self.stubborn = argv, stubborn
        self.terminated = self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        if self.stubborn and not self.killed:
            raise subprocess.TimeoutExpired("caffeinate", timeout)
        return 0


def test_keep_awake_starts_the_helper_only_when_wanted(monkeypatch):
    started = []
    monkeypatch.setattr(runner, "caffeinate_argv", lambda: ["caffeinate", "-i"])
    monkeypatch.setattr(runner, "_spawn", lambda argv: started.append(argv) or FakeHelper(argv))
    assert isinstance(runner.keep_awake(True), FakeHelper) and started == [["caffeinate", "-i"]]
    assert runner.keep_awake(False) is None and len(started) == 1

    def broken(argv):
        raise OSError("no such file")

    monkeypatch.setattr(runner, "_spawn", broken)
    assert runner.keep_awake(True) is None


def test_release_kills_a_helper_that_does_not_exit():
    polite, stubborn = FakeHelper(), FakeHelper(stubborn=True)
    runner.release(polite)
    runner.release(stubborn, timeout_s=0.01)
    runner.release(None)
    assert polite.terminated and not polite.killed
    assert stubborn.terminated and stubborn.killed


class _Answer(httpx.BaseTransport):
    def __init__(self, fail=False):
        self.fail = fail

    def handle_request(self, request):
        if self.fail:
            raise RuntimeError("unexpected failure inside a trial")
        body = {
            "model": "claude-opus-5-5",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "content": [{"type": "text", "text": "VERDICT: UNKNOWN"}],
        }
        return httpx.Response(200, json=body)


def real_spec(domain, golden, out, fail=False):
    provider = AnthropicProvider(
        api_key="sk-test",
        model="claude-opus-5-5",
        transport=_Answer(fail),
        sleep=lambda s: None,
        requests_per_minute=None,
    )
    return RunSpec(
        domain=domain,
        golden=golden,
        providers=[provider],
        out_dir=out,
        run_id="real-test",
        simulated=False,
        conditions=("no_tool",),
        premises=("true",),
        pressures=("neutral",),
        limit_pairs=1,
        progress=False,
    )


def test_a_real_run_always_releases_the_keep_awake_helper(domain, golden, tmp_path, monkeypatch):
    helpers = []
    monkeypatch.setattr(runner, "caffeinate_argv", lambda: ["caffeinate", "-i"])
    monkeypatch.setattr(runner, "_spawn", lambda argv: helpers.append(FakeHelper(argv)) or helpers[-1])
    run_dir = execute_run(real_spec(domain, golden, tmp_path / "ok"))
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["keep_awake"] == "caffeinate -i" and manifest["sessions"][0]["keep_awake"] == "caffeinate -i"
    assert len(helpers) == 1 and helpers[0].terminated
    with pytest.raises(RuntimeError):
        execute_run(real_spec(domain, golden, tmp_path / "boom", fail=True))
    assert len(helpers) == 2 and helpers[1].terminated  # released even when the run fails


def test_resume_keeps_the_run_identity_and_records_each_session(domain, golden, tmp_path):
    def spec(run_id, **kw):
        return RunSpec(
            domain=domain,
            golden=golden,
            providers=[SimulatedProvider("careful", domain, golden)],
            out_dir=tmp_path / "run",
            run_id=run_id,
            simulated=True,
            conditions=("tool",),
            limit_pairs=1,
            progress=False,
            **kw,
        )

    first = execute_run(spec("first-id", max_usd=0.0))  # the budget guard stops it before any trial
    before = json.loads((first / "manifest.json").read_text())
    assert before["status"] == "stopped" and len(before["sessions"]) == 1
    execute_run(spec("second-id", resume=True))
    after = json.loads((first / "manifest.json").read_text())
    assert after["run_id"] == "first-id" and after["created_at_utc"] == before["created_at_utc"]
    assert after["commit"] == before["commit"] and after["status"] == "complete"
    assert [s["status"] for s in after["sessions"]] == ["stopped", "complete"]
    assert after["sessions"][1]["n_trials_completed_this_session"] == 6
    records = [json.loads(x) for x in (first / "trials.jsonl").read_text().splitlines()]
    assert {r["run_id"] for r in records} == {"first-id"}


def test_resume_of_a_manifest_without_sessions_keeps_its_first_session(domain, golden, tmp_path):
    out = tmp_path / "legacy"
    out.mkdir()
    legacy = {
        "run_id": "old-id",
        "created_at_utc": "2026-11-23T12:03:59Z",
        "created_at_cot": "2026-11-23T07:03:59-05:00",
        "commit": "abc123",
        "status": "stopped",
        "max_usd": 14.0,
        "cost_usd_this_session": 14.3,
        "n_trials_completed_this_session": 0,
    }
    (out / "manifest.json").write_text(json.dumps(legacy))
    (out / "trials.jsonl").write_text("")
    spec = RunSpec(
        domain=domain,
        golden=golden,
        providers=[SimulatedProvider("careful", domain, golden)],
        out_dir=out,
        run_id="new-id",
        simulated=True,
        conditions=("tool",),
        limit_pairs=1,
        progress=False,
        resume=True,
    )
    manifest = json.loads((execute_run(spec) / "manifest.json").read_text())
    assert manifest["run_id"] == "old-id" and manifest["commit"] == "abc123"
    assert manifest["sessions"][0]["cost_usd_this_session"] == 14.3 and manifest["sessions"][0]["commit"] == "abc123"
    assert manifest["sessions"][1]["status"] == "complete"


def test_run_ids_differ_for_runs_started_in_the_same_second(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_stamp", lambda: "20261123T120000Z")
    for name in ("a", "b"):
        assert (
            cli.main(
                [
                    "run",
                    "--simulated",
                    "--limit",
                    "1",
                    "--conditions",
                    "tool",
                    "--no-report",
                    "--out",
                    str(tmp_path / name),
                ]
            )
            == 0
        )
    ids = {json.loads((tmp_path / n / "manifest.json").read_text())["run_id"] for n in ("a", "b")}
    assert len(ids) == 2 and all(i.startswith("20261123T120000Z-simulated-") for i in ids)
