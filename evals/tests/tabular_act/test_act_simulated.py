"""Simulated validation of the act checkpoint (design §8.3): planted rates are recovered, the
known-groups check holds, runs are deterministic with 1 and 4 workers, and the report is a pure
function of the transcripts. Results on simulated agents say nothing about any model."""

from __future__ import annotations

import json

import pytest

from cielo_bench.act_metrics import compute_act
from cielo_bench.act_report import build_act_report
from cielo_bench.act_validation import _p_caved, score, simulated_run, validate_act
from cielo_bench.domains.tabular.generate import file_sha256
from cielo_bench.domains.tabular_act.sandbox import sidecar_files
from cielo_bench.providers import build_provider
from cielo_bench.providers.simulated_act import ACT_PERSONAS, SimulatedActProvider
from cielo_bench.report import build_report, pack_run


@pytest.fixture(scope="module")
def sim_run(act, act_golden, tmp_path_factory):
    fixtures = {p: file_sha256(p) for p in (act.db_path, act.v1_path)}
    run = simulated_run(act, act_golden, tmp_path_factory.mktemp("act-sim") / "run", workers=4)
    assert {p: file_sha256(p) for p in fixtures} == fixtures  # the committed fixtures are byte-identical
    assert not sidecar_files(act.db_path) and not sidecar_files(act.v1_path)
    return run


def test_the_simulated_validation_passes(act, act_golden):
    checks = validate_act(act, act_golden)
    failed = [c for c in checks if not c["ok"]]
    assert not failed, failed
    names = {c["check"] for c in checks}
    assert "Determinism (1 vs 4 workers)" in names
    assert sum(1 for n in names if n.startswith("Parameter recovery")) == 14
    assert {n for n in names if n.startswith("Known groups")} == {
        "Known groups: act_after_check (stage 1)",
        "Known groups: unsafe_action (stage 1)",
    }


def test_a_planted_insistence_effect_is_recovered(act, act_golden, sim_run):
    scored = score(act, act_golden, sim_run)
    metrics = compute_act(scored, commit="c", golden_sha256=act_golden.sha256, simulated=True)
    for persona in ("agreeable", "careful"):
        sim = SimulatedActProvider(persona, act_golden)
        rows = [r for r in scored if r["model"] == f"sim:{persona}" and r["condition"] == "act_check"]
        rows = [r for r in rows if r["false_world"]]
        planted = sum(
            _p_caved(sim, r, sim.plan(r["trial_id"])) if (not r["unsafe_1"] and r["turn2_sent"]) else 0.0 for r in rows
        ) / len(rows)
        effect = next(
            c for c in metrics["contrasts"] if c["model"] == f"sim:{persona}" and c["contrast"].startswith("Insistence")
        )
        assert abs(effect["estimate"] - planted) < 0.05, (persona, effect["estimate"], planted)
    agreeable = next(c for c in metrics["contrasts"] if c["model"] == "sim:agreeable" and "Insistence" in c["contrast"])
    assert agreeable["estimate"] > 0.1 and agreeable["cluster_ci"][0] > 0  # detected for the agent built to cave


def test_the_report_is_a_pure_function_of_the_transcripts(sim_run, tmp_path):
    first = build_report(sim_run, tmp_path / "a")
    second = build_act_report(sim_run, tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
    assert (tmp_path / "a" / "summary.json").read_bytes() == (tmp_path / "b" / "summary.json").read_bytes()
    text = first.read_text()
    assert "**SIMULATED**" in text and "act-after-check" in text.lower() and "fewer than 8 templates" in text
    summary = json.loads((tmp_path / "a" / "summary.json").read_text())
    assert summary["manifest"]["design"]["effort"] == "medium" and "system_prompts" not in summary["manifest"]
    assert summary["metrics"]["confirmatory_design"] is False
    assert all(q["n_excluded_trials"] == 0 for q in summary["metrics"]["quality"])
    # packed transcripts (as committed in results/) rescore to the same bytes
    pack_run(sim_run)
    (sim_run / "trials.jsonl").rename(sim_run / "trials.raw")
    try:
        assert build_report(sim_run, tmp_path / "c").read_bytes() == first.read_bytes()
    finally:
        (sim_run / "trials.raw").rename(sim_run / "trials.jsonl")
        (sim_run / "trials.jsonl.gz").unlink()


def test_a_budget_stop_leaves_out_incomplete_blocks(act, act_golden, sim_run, tmp_path):
    run = tmp_path / "stopped"
    run.mkdir()
    (run / "manifest.json").write_text((sim_run / "manifest.json").read_text())
    lines = (sim_run / "trials.jsonl").read_text().splitlines()
    (run / "trials.jsonl").write_text("\n".join(lines[: len(lines) // 3 + 5]) + "\n")  # the cap cut a block
    build_act_report(run)
    summary = json.loads((run / "summary.json").read_text())
    left = summary["metrics"]["blocks_left_out"]
    assert any(left.values())
    kept = [json.loads(line) for line in (run / "scores.jsonl").read_text().splitlines()]
    assert len(kept) > 0


def test_the_act_simulator_is_keyed_by_trial_id(act, act_golden):
    with pytest.raises(ValueError, match="unknown persona"):
        SimulatedActProvider("reckless", act_golden)
    sim = build_provider("sim:agreeable", settings={}, domain=act, golden=act_golden, seed=0)
    assert isinstance(sim, SimulatedActProvider) and sim.describe()["persona"]["name"] == "agreeable"
    pair = act_golden.pairs[0]
    plans = {w: sim.plan(f"sim:agreeable|{pair['pair_id']}|{pair['lang']}|{w}|assertive|act_check|r0")
             for w in ("true", "far", "near", "two_table")}  # fmt: skip
    assert len({json.dumps(p, sort_keys=True, default=str) for p in plans.values()}) > 1  # same text, other worlds
    assert set(ACT_PERSONAS) == {"careful", "agreeable"}
