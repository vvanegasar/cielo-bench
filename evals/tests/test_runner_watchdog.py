"""A stalled run must surface: the watchdog reports stalls and machine sleep, and real runs on
macOS hold an idle-sleep assertion.

Regression for the first real smoke run (2026-11-22): the machine idled into sleep two seconds
after a request was sent; the request's 600 s read timeout counted only awake time, so the run
made no visible progress for hours, and progress was printed only every 200 trials.
"""

import json
import os
import threading
import time

from cielo_bench import runner
from cielo_bench.providers.simulated import SimulatedProvider
from cielo_bench.runner import RunSpec, Watchdog, execute_run


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


def test_keep_awake_uses_caffeinate_on_macos_only(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls.append(args)

    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/caffeinate")
    monkeypatch.setattr(runner.sys, "platform", "darwin")
    assert isinstance(runner.keep_awake(True), FakePopen)
    assert calls == [["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]]
    assert runner.keep_awake(False) is None
    monkeypatch.setattr(runner.sys, "platform", "linux")
    assert runner.keep_awake(True) is None
    monkeypatch.setattr(runner.sys, "platform", "darwin")
    monkeypatch.setattr(runner.shutil, "which", lambda name: None)
    assert runner.keep_awake(True) is None
    assert len(calls) == 1
