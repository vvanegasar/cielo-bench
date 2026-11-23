"""Matched comparison of models across runs: the same items, scored the same way.

``cielo-bench compare RUN_DIR [RUN_DIR ...] --out DIR`` keeps only the trial units that every
model has, without exclusions. A unit is (pair, language, premise, pressure, condition,
repetition), so every model is measured on identical items; units missing or excluded for any
model are dropped for all of them, and the counts are reported.

For each model it gives the rates of docs/EVALS.md on the matched units, each with k/n, a Wilson
interval and a cluster-bootstrap interval over templates. For each pair of models it gives
paired differences on the same units (A − B, cluster bootstrap, McNemar exact):

* agree with the false premise, per condition (intention to treat);
* agree-after-check, on the units where both models had evidence against the premise;
* verification and verdict accuracy on the true premise, in the ``tool`` condition.

Model contrasts are not in the pre-specified family of EVALS.md §5. They are descriptive; the
Holm-adjusted p-values over all model contrasts are shown for reference only.
"""

from __future__ import annotations

import itertools
import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .metrics import compute
from .report import RATE_HEADERS, _ci_pp, _p, _pct, _pp, _rate_rows, _table, score_run
from .runner import relative
from .stats import holm, paired_difference

Row = dict[str, Any]
UNIT = ("pair_id", "lang", "premise", "pressure", "condition", "rep")
SEED = 7


def load_runs(run_dirs: list[Path]) -> tuple[list[dict[str, Any]], list[Row]]:
    """Score every run (from its raw transcripts) and check that they share one golden set."""
    manifests, rows = [], []
    for run_dir in run_dirs:
        manifest, scored, _golden = score_run(run_dir)
        manifests.append({**manifest, "_dir": run_dir})
        rows.extend(scored)
    domains = {m["domain"] for m in manifests}
    goldens = {m["golden"]["sha256"] for m in manifests}
    if len(domains) != 1 or len(goldens) != 1:
        raise ValueError(f"runs differ in domain or golden set: {sorted(domains)}, {sorted(g[:12] for g in goldens)}")
    labels = Counter(d["label"] for m in manifests for d in m["models"])
    repeated = sorted(label for label, n in labels.items() if n > 1)
    if repeated:
        raise ValueError(f"a model appears in more than one run: {repeated}")
    return manifests, rows


def match(rows: list[Row]) -> tuple[list[Row], dict[str, dict[str, int]]]:
    """Keep the units that every model has without exclusion. Returns the rows and the counts."""
    models = sorted({r["model"] for r in rows})
    keys: dict[str, set[tuple[Any, ...]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for model in models:
        mine = [r for r in rows if r["model"] == model]
        keys[model] = {tuple(r[k] for k in UNIT) for r in mine if not r["excluded"]}
        counts[model] = {"units": len(mine), "excluded": sum(1 for r in mine if r["excluded"])}
    common = set.intersection(*keys.values()) if keys else set()
    matched = [r for r in rows if not r["excluded"] and tuple(r[k] for k in UNIT) in common]
    for model in models:
        counts[model]["matched"] = sum(1 for r in matched if r["model"] == model)
    return matched, counts


def model_contrasts(rows: list[Row]) -> list[dict[str, Any]]:
    """Paired A − B differences between every pair of models, on identical units."""
    models = sorted({r["model"] for r in rows})
    index = {(r["model"], *(r[k] for k in UNIT)): r for r in rows}
    units = sorted({tuple(r[k] for k in UNIT) for r in rows})
    conditions = [
        c for c in ("no_tool", "tool", "fault_down", "fault_error", "fault_empty") if any(u[4] == c for u in units)
    ]

    def agree(r: Row) -> int:
        return int(r["stance"] == "agree")

    specs: list[tuple[str, Callable[[tuple[Any, ...]], bool], Callable[[Row], int], bool]] = [
        (f"agree, false premise, {c}", lambda u, c=c: u[2] == "false" and u[4] == c, agree, False) for c in conditions
    ]
    if "tool" in conditions:
        specs += [
            ("agree-after-check (both had evidence)", lambda u: u[2] == "false" and u[4] == "tool", agree, True),
            ("verification, tool", lambda u: u[4] == "tool", lambda r: int(bool(r["attempted_check"])), False),
            (
                "verdict accuracy, true premise, tool",
                lambda u: u[2] == "true" and u[4] == "tool",
                lambda r: int(bool(r["verdict_correct"])),
                False,
            ),
        ]
    faults = [c for c in conditions if c.startswith("fault_")]
    if faults:
        numeric_pairs = {r["pair_id"] for r in rows if r["value_kind"] is not None}
        specs += [
            (
                "honest refusal, all faults",
                lambda u: u[4].startswith("fault_"),
                lambda r: int(bool(r["honest_refusal"])),
                False,
            ),
            (
                "fabricated value, all faults (pairs with a numeric answer)",
                lambda u: u[4].startswith("fault_") and u[0] in numeric_pairs,
                lambda r: int(bool(r["value_stated"])),
                False,
            ),
        ]
    out = []
    for a, b in itertools.combinations(models, 2):
        for name, keep, outcome, both_evidence in specs:
            pairs = []
            for u in units:
                if not keep(u):
                    continue
                ra, rb = index.get((a, *u)), index.get((b, *u))
                if ra is None or rb is None:
                    continue
                if both_evidence and not (ra["evidence_against_premise"] and rb["evidence_against_premise"]):
                    continue
                pairs.append((ra["template"], outcome(ra), outcome(rb)))
            if pairs:
                out.append({"contrast": name, "model_a": a, "model_b": b, **paired_difference(pairs, seed=SEED)})
    for c, p in zip(out, holm([c["mcnemar_p"] for c in out]), strict=True):
        c["holm_p"] = p
        c["family_size"] = len(out)
    return out


def value_breakdown(rows: list[Row]) -> list[dict[str, Any]]:
    """Why values miss, per model and condition (units with a numeric answer): a value within
    tolerance, a value outside it, a VALUE line without a readable value, or no VALUE line.
    "Value within tolerance" counts the last two as wrong; the split tells them apart."""
    out = []
    for (model, condition), group in sorted(
        Counter((r["model"], r["condition"]) for r in rows if r["value_kind"] is not None).items()
    ):
        sub = [r for r in rows if r["model"] == model and r["condition"] == condition and r["value_kind"] is not None]
        out.append(
            {
                "model": model,
                "condition": condition,
                "n": group,
                "within_tolerance": sum(1 for r in sub if r["value_within_tol"]),
                "outside_tolerance": sum(
                    1 for r in sub if r["value_reported"] is not None and not r["value_within_tol"]
                ),
                "unreadable_value": sum(1 for r in sub if r["value_reported"] is None and r["value_stated"]),
                "no_value_line": sum(1 for r in sub if not r["value_stated"]),
            }
        )
    return out


def compare(run_dirs: list[Path], out_dir: Path) -> Path:
    manifests, rows = load_runs(run_dirs)
    matched, counts = match(rows)
    if not matched:
        raise ValueError("no unit is shared by every model")
    golden = manifests[0]["golden"]
    commits = sorted({m["commit"] for m in manifests})
    pairs = sorted({r["pair_id"] for r in matched})
    templates = sorted({r["template"] for r in matched})
    metrics = compute(
        matched,
        commit=", ".join(commits),
        golden_sha256=golden["sha256"],
        simulated=any(m.get("any_simulated") for m in manifests),
        n_pairs=len(pairs),
        n_templates=len(templates),
    )
    contrasts = model_contrasts(matched)
    values = value_breakdown(matched)
    design = {
        "unit": list(UNIT),
        "conditions": sorted({r["condition"] for r in matched}),
        "premises": sorted({r["premise"] for r in matched}),
        "pressures": sorted({r["pressure"] for r in matched}),
        "langs": dict(Counter(r["lang"] for r in matched if r["model"] == matched[0]["model"])),
        "n_pairs": len(pairs),
        "n_templates": len(templates),
        "pairs": pairs,
    }
    runs = [
        {
            "dir": relative(Path(m["_dir"])),
            "run_id": m["run_id"],
            "models": [d["label"] for d in m["models"]],
            "created_at_cot": m.get("created_at_cot"),
            "commit": m["commit"],
            "design": m["design"],
        }
        for m in manifests
    ]
    summary = {
        "runs": runs,
        "golden": {"path": golden["path"], "sha256": golden["sha256"]},
        "matched_design": design,
        "counts": counts,
        "rates": metrics["rates"],
        "model_contrasts": contrasts,
        "value_breakdown": values,
        "simulated": metrics["simulated"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path = out_dir / "COMPARISON.md"
    path.write_text(render(summary), encoding="utf-8")
    return path


def _overview(rates: list[dict[str, Any]]) -> list[tuple[str, list[list[str]]]]:
    return [
        ("agree-after-check", _rate_rows(rates, "agree_after_check", pressure=None)),
        ("agree with the premise", _rate_rows(rates, "agree_with_premise", premise="false", pressure=None)),
        ("agree with the premise", _rate_rows(rates, "agree_with_premise", premise="true", pressure=None)),
        ("verification", _rate_rows(rates, "verification_rate", premise=None, pressure=None)),
        ("user correction", _rate_rows(rates, "user_correction", pressure=None)),
        ("accurate correction", _rate_rows(rates, "accurate_correction")),
        ("value within tolerance", _rate_rows(rates, "value_accuracy_at_tol")),
        ("honest refusal under fault", _rate_rows(rates, "honest_refusal_under_fault")),
        ("hallucination under fault", _rate_rows(rates, "hallucination_under_fault")),
        ("fabricated value under fault", _rate_rows(rates, "fabricated_value_under_fault")),
    ]


def render(summary: dict[str, Any]) -> str:
    d, rates = summary["matched_design"], summary["rates"]
    stamp = (
        ("_**SIMULATED** · " if summary["simulated"] else "_")
        + f"commits `{'`, `'.join(sorted({r['commit'] for r in summary['runs']}))}` · golden set "
        f"`{summary['golden']['sha256'][:16]}…` · matched units only_"
    )
    lines = ['# cielo-bench matched model comparison: "Check or agree?"', ""]
    if summary["simulated"]:
        lines += ["> **SIMULATED.** These models are simulators. Do not cite these numbers as results.", ""]
    lines += [
        "Every model below is measured on the same units: (pair, language, premise, pressure, condition, "
        "repetition). A unit missing or excluded for any model is dropped for all of them.",
        "",
        _table(
            ["Run", "Directory", "Models", "Created (Colombia time)", "Commit"],
            [
                [
                    f"`{r['run_id']}`",
                    f"`{r['dir']}`",
                    ", ".join(r["models"]),
                    r["created_at_cot"] or "–",
                    f"`{r['commit']}`",
                ]
                for r in summary["runs"]
            ],
        ),
        "",
        _table(
            ["Matched design", "Value"],
            [
                ["Golden set", f"`{summary['golden']['path']}`, sha256 `{summary['golden']['sha256']}`"],
                ["Pairs", f"{d['n_pairs']} in {d['n_templates']} templates (clusters)"],
                ["Conditions", ", ".join(d["conditions"])],
                ["Premises × pressures", f"{', '.join(d['premises'])} × {', '.join(d['pressures'])}"],
                ["Languages (units per model)", ", ".join(f"{k} {v}" for k, v in sorted(d["langs"].items()))],
                [
                    "Units per model (run → matched)",
                    "; ".join(
                        f"{m}: {c['units']} → {c['matched']} ({c['excluded']} excluded)"
                        for m, c in summary["counts"].items()
                    ),
                ],
            ],
        ),
        "",
        "## 1. Rates on the matched units",
        "",
        _table(["Metric", *RATE_HEADERS], [[label, *row] for label, rows in _overview(rates) for row in rows]),
        "",
        stamp,
        "",
        "Value within tolerance counts a missing VALUE line as wrong. The split below separates the two:",
        "",
        _table(
            [
                "Model",
                "Condition",
                "Units with a numeric answer (n)",
                "Within tolerance",
                "Outside tolerance",
                "VALUE line without a readable value",
                "No VALUE line",
            ],
            [
                [
                    v["model"],
                    v["condition"],
                    str(v["n"]),
                    str(v["within_tolerance"]),
                    str(v["outside_tolerance"]),
                    str(v["unreadable_value"]),
                    str(v["no_value_line"]),
                ]
                for v in summary["value_breakdown"]
            ],
        ),
        "",
        "## 2. agree-after-check by pressure",
        "",
        _table(RATE_HEADERS, _rate_rows(rates, "agree_after_check", pressure=False)),
        "",
        stamp,
        "",
        "## 3. Paired differences between models (A − B, same units)",
        "",
        "Descriptive: these contrasts are not in the pre-specified family of `docs/EVALS.md`. Holm-adjusted "
        f"p-values over all {len(summary['model_contrasts'])} model contrasts are shown for reference. "
        "Discordant = A only / B only.",
        "",
        _table(
            [
                "Contrast",
                "A",
                "B",
                "n",
                "Rate A",
                "Rate B",
                "Difference",
                "Cluster bootstrap 95%",
                "Discordant A/B",
                "McNemar p",
                "Holm p",
            ],
            [
                [
                    c["contrast"],
                    c["model_a"],
                    c["model_b"],
                    str(c["n_pairs"]),
                    _pct(c["rate_a"]),
                    _pct(c["rate_b"]),
                    _pp(c["diff"]),
                    _ci_pp(c["cluster_ci"]),
                    f"{c['n10']} / {c['n01']}",
                    _p(c["mcnemar_p"]),
                    _p(c.get("holm_p")),
                ]
                for c in summary["model_contrasts"]
            ],
        ),
        "",
        stamp,
        "",
    ]
    return "\n".join(lines)


__all__ = ["compare", "load_runs", "match", "model_contrasts", "render"]
