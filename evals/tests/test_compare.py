"""Matched model comparison across runs (simulated models, no network)."""

import json

import pytest

from cielo_bench.cli import main
from cielo_bench.compare import UNIT, compare, load_runs, match
from cielo_bench.domains import get_domain
from cielo_bench.golden import load_golden
from cielo_bench.providers.simulated import SimulatedProvider
from cielo_bench.runner import RunSpec, execute_run


def run(domain, golden, out, persona, **kw):
    spec = RunSpec(
        domain=domain,
        golden=golden,
        providers=[SimulatedProvider(persona, domain, golden)],
        out_dir=out,
        run_id=f"run-{persona}",
        simulated=True,
        progress=False,
        **kw,
    )
    return execute_run(spec)


@pytest.fixture
def two_runs(domain, golden, tmp_path):
    # a wider design for one model and a narrower one (tool only, fewer pairs) for the other
    wide = run(domain, golden, tmp_path / "careful", "careful", limit_pairs=4, conditions=("no_tool", "tool"))
    narrow = run(domain, golden, tmp_path / "agreeable", "agreeable", limit_pairs=2, conditions=("tool",))
    return wide, narrow


def test_only_units_shared_by_every_model_are_compared(two_runs, tmp_path):
    path = compare(list(two_runs), tmp_path / "cmp")
    summary = json.loads((tmp_path / "cmp" / "comparison.json").read_text())
    design = summary["matched_design"]
    assert design["conditions"] == ["tool"] and design["n_pairs"] == 2
    per_model = 2 * 2 * 3  # pairs x premises x pressures, tool only
    assert summary["counts"]["sim:careful"] == {"units": 4 * 2 * 2 * 3, "excluded": 0, "matched": per_model}
    assert summary["counts"]["sim:agreeable"]["matched"] == per_model
    models = {r["model"] for r in summary["rates"]}
    assert models == {"sim:careful", "sim:agreeable"}
    names = {c["contrast"] for c in summary["model_contrasts"]}
    assert {"agree, false premise, tool", "agree-after-check (both had evidence)", "verification, tool"} <= names
    assert all(c["model_a"] == "sim:agreeable" and c["model_b"] == "sim:careful" for c in summary["model_contrasts"])
    assert all(c["family_size"] == len(summary["model_contrasts"]) for c in summary["model_contrasts"])
    text = path.read_text()
    assert "SIMULATED" in text and "Paired differences between models" in text and "not in the pre-specified" in text
    assert "| Metric | Model (version) |" in text and "| agree-after-check | sim:agreeable (" in text


def test_a_unit_excluded_for_one_model_is_dropped_for_all(two_runs):
    wide, narrow = two_runs
    trials = narrow / "trials.jsonl"
    records = [json.loads(line) for line in trials.read_text().splitlines()]
    records[0]["error"] = "ProviderError: HTTP 529 (test)"
    trials.write_text("".join(json.dumps(r) + "\n" for r in records))
    _, rows = load_runs([wide, narrow])
    matched, counts = match(rows)
    dropped = tuple(records[0][k] for k in UNIT)
    assert all(tuple(r[k] for k in UNIT) != dropped for r in matched)
    assert counts["sim:agreeable"]["excluded"] == 1
    assert counts["sim:careful"]["matched"] == counts["sim:agreeable"]["matched"] == 2 * 2 * 3 - 1


def test_runs_must_share_the_golden_set_and_not_repeat_a_model(domain, golden, two_runs, tmp_path):
    wide, _ = two_runs
    again = run(domain, golden, tmp_path / "careful-again", "careful", limit_pairs=2, conditions=("tool",))
    with pytest.raises(ValueError, match="more than one run"):
        load_runs([wide, again])
    tabular = get_domain("tabular")
    other = run(tabular, load_golden(tabular.golden_path), tmp_path / "tab", "agreeable", limit_pairs=1)
    with pytest.raises(ValueError, match="domain or golden set"):
        load_runs([wide, other])
    assert main(["compare", str(wide), str(other), "--out", str(tmp_path / "x")]) == 2
    assert main(["compare", *map(str, two_runs), "--out", str(tmp_path / "ok")]) == 0
    assert (tmp_path / "ok" / "COMPARISON.md").exists()
