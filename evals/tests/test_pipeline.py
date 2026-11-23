"""End to end: run -> raw JSONL -> scores -> REPORT.md + figures, with simulated models and
with a mocked real provider (no network)."""

import json

import httpx
import pytest

from cielo_bench import cli
from cielo_bench.cli import main
from cielo_bench.golden import PRESSURES
from cielo_bench.prompts import answer_format, system_prompt
from cielo_bench.providers.anthropic import AnthropicProvider
from cielo_bench.providers.simulated import SimulatedProvider
from cielo_bench.report import build_report, describe_tolerances
from cielo_bench.runner import CONDITIONS, RunSpec, execute_run, plan_trials, round_robin


def spec(domain, golden, out, **kw):
    providers = [SimulatedProvider(p, domain, golden) for p in ("careful", "agreeable")]
    kw.setdefault("limit_pairs", 8)
    kw.setdefault("workers", 2)
    return RunSpec(
        domain=domain,
        golden=golden,
        providers=providers,
        out_dir=out,
        run_id="test-run",
        simulated=True,
        progress=False,
        **kw,
    )


def test_design_counts(domain, golden, tmp_path):
    plans = plan_trials(spec(domain, golden, tmp_path))
    # per pair: core 2 conditions x 2 premises x 3 pressures + faults 3 x 2 x 1, for 2 models
    assert len(plans) == 8 * (2 * 2 * 3 + 3 * 2) * 2
    assert {p.pressure for p in plans if p.condition == "tool"} == set(PRESSURES)
    assert {p.pressure for p in plans if p.condition.startswith("fault_")} == {"assertive"}
    small = plan_trials(spec(domain, golden, tmp_path, fault_limit=2, langs="both", reps=2))
    assert len({p.pair_id for p in small if p.condition == "fault_down"}) == 2
    assert {p.lang for p in small} == {"es", "en"}
    with pytest.raises(ValueError):
        plan_trials(spec(domain, golden, tmp_path, conditions=("tool", "sunny")))
    with pytest.raises(ValueError):
        plan_trials(spec(domain, golden, tmp_path, pressures=("shouting",)))
    picked = round_robin(golden.pairs, 18)
    assert len({p["template"] for p in picked}) == 18 and len(picked) == 18


def test_run_report_and_resume(domain, golden, tmp_path):
    run_dir = execute_run(spec(domain, golden, tmp_path / "run"))
    lines = (run_dir / "trials.jsonl").read_text().splitlines()
    assert len(lines) == 8 * 18 * 2
    first = json.loads(lines[0])
    assert {"pressure", "condition", "fault_kind", "rounds", "usage_total", "cost_usd"} <= set(first)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "complete" and manifest["simulated"] is True
    assert manifest["golden"]["sha256"] == golden.sha256 and manifest["design"]["pressures"] == list(PRESSURES)

    report = build_report(run_dir)
    text = report.read_text()
    assert "SIMULATED RUN" in text and "agree-after-check" in text and "Holm" in text
    assert text.count("_**SIMULATED** · commit") >= 12  # every table carries the marker
    assert golden.sha256 in text and "sim-careful-v1" in text
    for name in ("agreement_by_pressure.png", "verification_and_failure.png"):
        assert (run_dir / "figures" / name).stat().st_size > 10_000
    summary = json.loads((run_dir / "summary.json").read_text())
    assert all(r["golden_sha256"] == golden.sha256 and "n" in r and r["simulated"] for r in summary["metrics"]["rates"])
    assert (run_dir / "scores.jsonl").exists()

    with pytest.raises(FileExistsError):
        execute_run(spec(domain, golden, tmp_path / "run"))
    execute_run(spec(domain, golden, tmp_path / "run", resume=True))
    assert len((run_dir / "trials.jsonl").read_text().splitlines()) == len(lines)


def test_report_states_the_design_that_ran(domain, golden, tmp_path):
    """A tool-only run without a fault block must not be described as no_tool + tool with faults."""
    run_dir = execute_run(spec(domain, golden, tmp_path / "toolonly", conditions=("tool",), limit_pairs=2))
    text = build_report(run_dir).read_text()
    assert "| Core design | conditions tool × premise" in text and "no_tool, tool ×" not in text
    assert "2 pairs, round-robin across templates" in text
    assert "| Fault block | – |" in text and "| Fault block design | – |" in text
    assert "raw transcripts: " in text and "/trials.jsonl`)" in text  # simulated runs are not packed
    full = build_report(execute_run(spec(domain, golden, tmp_path / "full", limit_pairs=2))).read_text()
    assert "conditions no_tool, tool ×" in full and "fault_down (down)" in full


def test_interpretation_points_to_the_results_note(tmp_path):
    from cielo_bench.report import interpretation_pointer

    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "2026-11-x.md").write_text("Runs: `results/2026-11-23-astronomy-m`.\n", encoding="utf-8")
    (notes / "other.md").write_text("nothing here\n", encoding="utf-8")
    cited = interpretation_pointer(tmp_path / "results" / "2026-11-23-astronomy-m", notes)
    assert "docs/results/2026-11-x.md" in cited and "other.md" not in cited
    assert "results note in `docs/results/`" in interpretation_pointer(tmp_path / "results" / "uncited", notes)


def test_budget_guard_stops_before_spending(domain, golden, tmp_path):
    run_dir = execute_run(spec(domain, golden, tmp_path / "run", max_usd=0.0))
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "stopped" and manifest["n_trials_completed_this_session"] == 0


def test_simulated_runs_are_reproducible(domain, golden, tmp_path):
    a = execute_run(spec(domain, golden, tmp_path / "a", limit_pairs=4, workers=1))
    b = execute_run(spec(domain, golden, tmp_path / "b", limit_pairs=4, workers=3))

    def finals(path):
        return sorted(
            (json.loads(x)["trial_id"], json.loads(x)["final_text"])
            for x in (path / "trials.jsonl").read_text().splitlines()
        )

    assert finals(a) == finals(b)


def test_prompt_and_tolerance_descriptions_are_domain_driven(domain, golden):
    assert "`VALUE: 35°` or `VALUE: 19:40`" in answer_format(domain, "en")
    assert "`VALUE: 35°` o `VALUE: 19:40`" in system_prompt(domain, "es")
    text = describe_tolerances(golden)
    assert "angles ±1 deg" in text and "clock times ±3 min" in text
    fake = type(golden)(
        doc={
            **golden.doc,
            "pairs": [
                {
                    "answer": {
                        "kind": "number",
                        "target": 10.0,
                        "tolerance": 0.005,
                        "tolerance_mode": "rel",
                        "unit": "USD",
                    }
                }
            ],
        },
        path=golden.path,
    )
    assert describe_tolerances(fake) == "numbers ±0.5% of the target (1 pairs)"


def test_cli_reproduce_quick_and_commands(tmp_path, capsys):
    assert main(["reproduce", "--simulated", "--quick", "--quiet", "--out", str(tmp_path / "r")]) == 0
    out = capsys.readouterr().out
    assert "[SIMULATED] agree-after-check" in out and (tmp_path / "r" / "REPORT.md").exists()
    assert main(["reproduce", "--from", str(tmp_path / "r")]) == 0
    assert main(["report", str(tmp_path / "r"), "--out", str(tmp_path / "rep")]) == 0
    assert (tmp_path / "rep" / "REPORT.md").exists()
    assert main(["reproduce"]) == 2
    assert main(["run", "--simulated", "--models", "anthropic", "--out", str(tmp_path / "x")]) == 2
    assert main(["run", "--simulated", "--resume"]) == 2
    assert (
        main(
            [
                "run",
                "--simulated",
                "--limit",
                "2",
                "--conditions",
                "no_tool,tool",
                "--no-report",
                "--out",
                str(tmp_path / "y"),
            ]
        )
        == 0
    )
    assert main(["verify"]) == 0 and main(["power"]) == 0 and main(["domains"]) == 0
    assert main(["estimate", "--limit", "4"]) == 0
    assert "claude-opus-5-5" in capsys.readouterr().out


class _Final(httpx.BaseTransport):
    def __init__(self):
        self.calls = 0

    def handle_request(self, request):
        self.calls += 1
        body = {
            "model": "claude-opus-5-5",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "content": [{"type": "text", "text": "I cannot check that.\nVERDICT: UNKNOWN"}],
        }
        return httpx.Response(200, json=body)


def test_cli_real_path_with_a_mocked_provider(tmp_path, monkeypatch, capsys):
    transport = _Final()
    settings = {"CIELO_MODELS": "anthropic:claude-opus-5-5", "CIELO_ANTHROPIC_API_KEY": "sk-test", "CIELO_MAX_USD": "1"}
    monkeypatch.setattr(cli, "load_settings", lambda: dict(settings))
    monkeypatch.setattr(
        cli,
        "build_provider",
        lambda s, **kw: AnthropicProvider(
            api_key="sk-test",
            model="claude-opus-5-5",
            transport=transport,
            sleep=lambda x: None,
            requests_per_minute=None,
        ),
    )
    # without --yes and without a terminal, nothing is spent
    assert main(["run", "--limit", "2", "--conditions", "no_tool", "--out", str(tmp_path / "no")]) == 2
    assert transport.calls == 0
    assert main(["run", "--limit", "2", "--conditions", "no_tool", "--yes", "--out", str(tmp_path / "real")]) == 0
    out = capsys.readouterr().out
    assert "Cost estimate" in out and transport.calls == 2 * 2 * 3
    text = (tmp_path / "real" / "REPORT.md").read_text()
    assert "SIMULATED" not in text and "claude-opus-5-5" in text
    manifest = json.loads((tmp_path / "real" / "manifest.json").read_text())
    assert manifest["prices_usd_per_mtok"]["anthropic:claude-opus-5-5"] == [4.0, 20.0]
    assert "sk-test" not in (tmp_path / "real" / "trials.jsonl").read_text()
    # a model without a known price is refused before any spending
    monkeypatch.setattr(cli, "build_provider", lambda s, **kw: _priceless())
    assert main(["run", "--limit", "1", "--yes", "--out", str(tmp_path / "p")]) == 2


def _priceless():
    from cielo_bench.providers.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(api_key="k", model="m", requests_per_minute=None)


def test_conditions_constant_is_complete():
    assert CONDITIONS == ("no_tool", "tool", "fault_down", "fault_error", "fault_empty")


def test_cli_cache_dir_flag_sets_the_live_cache(tmp_path, monkeypatch):
    import os

    monkeypatch.setenv("CIELO_CACHE_DIR", "unset-by-test")
    assert main(["--cache-dir", str(tmp_path / "c"), "domains"]) == 0
    assert os.environ["CIELO_CACHE_DIR"] == str(tmp_path / "c")
