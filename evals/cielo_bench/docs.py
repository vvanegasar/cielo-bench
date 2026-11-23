"""Generated README tables: test suite, harness validation, golden sets, power, real results.

Each table lives between markers in a Markdown file::

    <!-- cielo-bench:begin validation -->
    ...generated...
    <!-- cielo-bench:end validation -->

``cielo-bench docs --update-readme-tables`` rewrites the blocks it finds; ``--check`` exits 1
when a block is out of date, so CI can verify that the README matches the code. The test-suite
block is only rewritten when JUnit and coverage reports are given (they depend on the machine).

The validation block runs the full design with the two simulated agents. It checks the
*instrument* (that the harness measures what it should), never a language model.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, RESULTS_DIR, git_commit
from .domain import Domain
from .domains import AVAILABLE, get_domain
from .golden import GoldenSet, load_golden
from .metrics import compute
from .providers.simulated import PERSONAS, SimulatedProvider
from .runner import FAULT_CONDITIONS, RunSpec, execute_run, plan_trials
from .scoring import score_trial
from .stats import design_effect, paired_mde, wilson

BLOCKS = ("tests", "validation", "golden", "power", "results")
_BLOCK_RE = r"(<!-- cielo-bench:begin {name} -->)(.*?)(<!-- cielo-bench:end {name} -->)"
DEFAULT_PLANNED = "before 2026-12-06"

L = {
    "en": {
        "check": "Check",
        "shows": "What it shows",
        "result": "Result",
        "status": "Status",
        "domain": "Domain",
        "pairs": "Pairs",
        "templates": "Templates",
        "cities": "Cities",
        "langs": "Languages",
        "fixtures": "Upstream fixtures",
        "hash": "Golden-set SHA-256",
        "template": "Template",
        "comparison": "Comparison",
        "units": "Units (n)",
        "clusters": "Clusters",
        "per": "Per cluster",
        "mde20": "MDE, ψ = 20% (ICC 0.05 / 0.20)",
        "mde40": "MDE, ψ = 40% (ICC 0.05 / 0.20)",
        "suite": "Suite",
        "tests": "Tests",
        "passed": "Passed",
        "failed": "Failed",
        "skipped": "Skipped",
        "module": "Module",
        "statements": "Statements",
        "coverage": "Coverage",
        "nd": "not detectable",
        "pending": "Pending first real-model runs (planned {planned}). No numbers are shown until then.",
        "results_head": [
            "Run",
            "Domain",
            "Model (version)",
            "k/n",
            "agree-after-check",
            "Wilson 95%",
            "Cluster bootstrap 95%",
            "Commit",
            "Golden set",
        ],
        "validation_caption": (
            "**Instrument validation with simulated agents — these are not results for any language model.** "
            "Two deterministic simulated agents with planted behaviour (`sim:agreeable`, `sim:careful`) run "
            "the full design; the checks confirm that the harness recovers what was planted."
        ),
    },
    "es": {
        "check": "Prueba",
        "shows": "Qué muestra",
        "result": "Resultado",
        "status": "Estado",
        "domain": "Dominio",
        "pairs": "Pares",
        "templates": "Plantillas",
        "cities": "Ciudades",
        "langs": "Idiomas",
        "fixtures": "Fixtures de la fuente",
        "hash": "SHA-256 del golden set",
        "template": "Plantilla",
        "comparison": "Comparación",
        "units": "Unidades (n)",
        "clusters": "Clusters",
        "per": "Por cluster",
        "mde20": "EMD, ψ = 20 % (ICC 0,05 / 0,20)",
        "mde40": "EMD, ψ = 40 % (ICC 0,05 / 0,20)",
        "suite": "Suite",
        "tests": "Pruebas",
        "passed": "Pasan",
        "failed": "Fallan",
        "skipped": "Omitidas",
        "module": "Módulo",
        "statements": "Sentencias",
        "coverage": "Cobertura",
        "nd": "no detectable",
        "pending": (
            "Primeras corridas con modelos reales pendientes (previstas {planned}). "
            "No se muestran números hasta entonces."
        ),
        "results_head": [
            "Corrida",
            "Dominio",
            "Modelo (versión)",
            "k/n",
            "agree-after-check",
            "Wilson 95 %",
            "Bootstrap por clusters 95 %",
            "Commit",
            "Golden set",
        ],
        "validation_caption": (
            "**Validación del instrumento con agentes simulados: no son resultados de ningún modelo de lenguaje.** "
            "Dos agentes simulados deterministas con conducta sembrada (`sim:agreeable`, `sim:careful`) corren "
            "el diseño completo; las pruebas confirman que el arnés recupera lo sembrado."
        ),
    },
}


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(out)


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def _ci(ci: Any) -> str:
    return "–" if not ci else f"[{100 * ci[0]:.1f}, {100 * ci[1]:.1f}]"


def _domains() -> list[tuple[Domain, GoldenSet | None]]:
    out = []
    for name in AVAILABLE:
        domain = get_domain(name)
        try:
            golden = load_golden(domain.golden_path)
        except Exception:  # a domain without a valid golden set is listed as such
            golden = None
        out.append((domain, golden))
    return out


# ----------------------------------------------------------------------------- golden
def golden_block(lang: str = "en") -> str:
    t = L[lang]
    summary, details = [], []
    for domain, golden in _domains():
        if golden is None:
            summary.append([domain.name, "–", "–", "–", "–", "–", "golden set missing"])
            continue
        pairs = golden.pairs
        cities = Counter(str((p.get("context") or {}).get("city", "–")) for p in pairs)
        langs = Counter(p["lang"] for p in pairs)
        fixtures = len(golden.doc.get("fixtures", []))
        summary.append(
            [
                f"`{domain.name}` ({golden.doc.get('version', '')})",
                str(len(pairs)),
                str(len(golden.templates)),
                ", ".join(f"{c} {n}" for c, n in cities.most_common()) if cities != Counter({"–": len(pairs)}) else "–",
                ", ".join(f"{k.upper()} {n}" for k, n in sorted(langs.items())),
                str(fixtures),
                f"`{golden.sha256[:16]}…`",
            ]
        )
        by_template = Counter(p["template"] for p in pairs)
        details.append(f"**{domain.name}**: " + ", ".join(f"`{name}` {n}" for name, n in sorted(by_template.items())))
    head = [t["domain"], t["pairs"], t["templates"], t["cities"], t["langs"], t["fixtures"], t["hash"]]
    return _table(head, summary) + "\n\n" + "\n\n".join(details)


# ----------------------------------------------------------------------------- power
def power_block(lang: str = "en") -> str:
    t = L[lang]
    rows = []
    for domain, golden in _domains():
        if golden is None:
            continue
        n, g = len(golden.pairs), len(golden.templates)
        comparisons = [
            ("tool − no_tool, false premise (3 pressures pooled)", n * 3),
            ("assertive − neutral; authority − neutral (one condition)", n),
            ("verification: false − true premise (3 pressures pooled)", n * 3),
            ("fault − tool, false premise (assertive)", n),
        ]
        for label, units in comparisons:
            m = units / g
            cells = []
            for psi in (0.2, 0.4):
                vals = [paired_mde(units, psi, deff=design_effect(m, icc)) for icc in (0.05, 0.2)]
                cells.append(" / ".join(t["nd"] if v is None else f"{100 * v:.1f} pp" for v in vals))
            rows.append([f"`{domain.name}`: {label}", str(units), str(g), f"{m:.0f}", *cells])
    return _table([t["comparison"], t["units"], t["clusters"], t["per"], t["mde20"], t["mde40"]], rows) + (
        "\n\nMDE: minimum detectable paired difference (McNemar, α = 0.05, power 0.8, Connor 1987), inflated by the "
        "design effect 1 + (m − 1)·ICC. ψ: share of discordant pairs."
        if lang == "en"
        else "\n\nEMD: efecto mínimo detectable de una diferencia pareada (McNemar, α = 0,05, potencia 0,8, "
        "Connor 1987), inflado por el efecto de diseño 1 + (m − 1)·ICC. ψ: proporción de pares discordantes."
    )


# ----------------------------------------------------------------------------- validation
def _simulated_run(domain: Domain, golden: GoldenSet, out: Path, workers: int, limit_pairs: int | None = None) -> Path:
    providers = [SimulatedProvider(p, domain, golden) for p in ("agreeable", "careful")]
    spec = RunSpec(
        domain=domain,
        golden=golden,
        providers=providers,
        out_dir=out,
        run_id=f"validation-w{workers}",
        simulated=True,
        limit_pairs=limit_pairs,
        workers=workers,
        progress=False,
    )
    return execute_run(spec)


def _fingerprint(run_dir: Path) -> str:
    rows = sorted((r["trial_id"], r["final_text"]) for r in map(json.loads, (run_dir / "trials.jsonl").open()))
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


_VALIDATION_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}


def validate_domain(domain: Domain, golden: GoldenSet, limit_pairs: int | None = None) -> list[dict[str, Any]]:
    """Run the full simulated design twice and check the instrument. Returns check records
    (memoized per domain and golden-set hash, so several README files share one validation)."""
    key = (domain.name, golden.sha256, str(limit_pairs))
    if key not in _VALIDATION_CACHE:
        _VALIDATION_CACHE[key] = _validate_domain(domain, golden, limit_pairs)
    return _VALIDATION_CACHE[key]


def _validate_domain(domain: Domain, golden: GoldenSet, limit_pairs: int | None = None) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    problems = domain.verify_golden(golden)
    checks.append(
        {
            "check": "Golden-set integrity",
            "shows": "fixtures intact; facts re-derivable; premise rules hold",
            "result": f"sha256 {golden.sha256[:12]}…; {len(problems)} problems",
            "ok": not problems,
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        a = _simulated_run(domain, golden, Path(tmp) / "a", workers=1, limit_pairs=limit_pairs)
        b = _simulated_run(domain, golden, Path(tmp) / "b", workers=4, limit_pairs=limit_pairs)
        fa, fb = _fingerprint(a), _fingerprint(b)
        checks.append(
            {
                "check": "Determinism",
                "shows": "two runs (1 vs 4 workers) give identical transcripts",
                "result": f"{fa[:12]}… = {fb[:12]}…" if fa == fb else f"{fa[:12]}… ≠ {fb[:12]}…",
                "ok": fa == fb,
            }
        )
        records = [json.loads(line) for line in (a / "trials.jsonl").open()]
        spec = RunSpec(
            domain=domain,
            golden=golden,
            providers=[SimulatedProvider("careful", domain, golden)],
            out_dir=Path(tmp),
            run_id="plan",
            simulated=True,
            limit_pairs=limit_pairs,
        )
        planned = Counter((p.condition, p.premise, p.pressure) for p in plan_trials(spec))
        seen = Counter(
            (r["condition"], r["premise"], r["pressure"]) for r in records if r["model_label"] == "sim:careful"
        )
        errors = sum(1 for r in records if r.get("error"))
        checks.append(
            {
                "check": "Design coverage",
                "shows": "every condition × premise × pressure cell, no errors",
                "result": f"{len(planned)} cells, {len(records)} trials, {errors} errors",
                "ok": seen == planned and errors == 0,
            }
        )
        fault_results = [
            tr["result"]
            for r in records
            if r["condition"] in FAULT_CONDITIONS
            for rnd in r["rounds"]
            for tr in rnd["tool_results"]
        ]
        leaked = [
            res
            for res in fault_results
            if res.get("status") != "source_unavailable"
            or any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in res.values())
        ]
        kinds = sorted({k for k in FAULT_CONDITIONS.values()})
        checks.append(
            {
                "check": "Fault injection",
                "shows": f"{'/'.join(kinds)}: every tool result is source_unavailable with no values",
                "result": f"{len(fault_results)} tool results, {len(leaked)} with values",
                "ok": bool(fault_results) and not leaked,
            }
        )
        pairs = {p["pair_id"]: p for p in golden.pairs}
        scored = [score_trial(r, pairs[r["pair_id"]], domain) for r in records]
        metrics = compute(
            scored,
            commit=git_commit(),
            golden_sha256=golden.sha256,
            simulated=True,
            n_pairs=limit_pairs or len(golden.pairs),
            n_templates=len(golden.templates),
        )
    aac = {r["model"]: r for r in metrics["rates"] if r["metric"] == "agree_after_check" and r["pressure"] is None}
    agreeable, careful = aac.get("sim:agreeable"), aac.get("sim:careful")
    if agreeable and careful and agreeable["wilson"] and careful["wilson"]:
        separated = careful["wilson"][1] < agreeable["wilson"][0]
        checks.append(
            {
                "check": "Known groups",
                "shows": "agree-after-check separates a sycophantic from a careful agent",
                "result": (
                    f"agreeable {agreeable['k']}/{agreeable['n']} = {_pct(agreeable['rate'])} "
                    f"(Wilson {_ci(agreeable['wilson'])}, cluster {_ci(agreeable['cluster_ci'])}) vs careful "
                    f"{careful['k']}/{careful['n']} = {_pct(careful['rate'])} (Wilson {_ci(careful['wilson'])}, "
                    f"cluster {_ci(careful['cluster_ci'])})"
                ),
                "ok": separated,
            }
        )
        for name, rec in (("agreeable", agreeable), ("careful", careful)):
            persona = PERSONAS[name]
            eligible = [
                s
                for s in scored
                if s["model"] == f"sim:{name}"
                and s["premise"] == "false"
                and s["evidence_against_premise"]
                and not s["excluded"]
            ]
            planted = sum(
                min(0.95, persona.p_agree_after_check * persona.agree_factor(s["pressure"])) for s in eligible
            )
            expected = planted / len(eligible) if eligible else None
            lo, hi = wilson(rec["k"], rec["n"]) or (0.0, 1.0)
            checks.append(
                {
                    "check": f"Parameter recovery ({name})",
                    "shows": "planted agree-after-check lies inside the measured Wilson 95% CI",
                    "result": f"planted {_pct(expected)}, measured {_pct(rec['rate'])} {_ci((lo, hi))}",
                    "ok": expected is not None and lo <= expected <= hi,
                }
            )
    effect = next(
        (
            c
            for c in metrics["contrasts"]
            if c["model"] == "sim:agreeable" and c["contrast"] == "agree, false premise, tool: authority - neutral"
        ),
        None,
    )
    if effect:
        checks.append(
            {
                "check": "Planted pressure effect",
                "shows": "authority − neutral is detected for the agent built to cave to authority",
                "result": f"{effect['diff'] * 100:+.1f} pp (cluster {_ci(effect['cluster_ci'])}), Holm p = "
                f"{effect['holm_p']:.2g}",
                "ok": effect["holm_p"] is not None and effect["holm_p"] < 0.05,
            }
        )
    return checks


def validation_block(lang: str = "en") -> str:
    t = L[lang]
    parts = [t["validation_caption"]]
    for domain, golden in _domains():
        if golden is None:
            continue
        rows = [
            [c["check"], c["shows"], c["result"], "PASS" if c["ok"] else "FAIL"]
            for c in validate_domain(domain, golden)
        ]
        parts.append(
            f"**{domain.name}** (golden `{golden.sha256[:12]}…`)\n\n"
            + _table([t["check"], t["shows"], t["result"], t["status"]], rows)
        )
    return "\n\n".join(parts)


# ----------------------------------------------------------------------------- tests
def tests_block(junit: Path, coverage: Path, lang: str = "en") -> str:
    t = L[lang]
    root = ET.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    data = json.loads(coverage.read_text(encoding="utf-8"))
    groups: dict[str, list[int]] = {}
    for path, info in data.get("files", {}).items():
        rel = path.split("cielo_bench/", 1)[-1]
        group = (
            "domains/" + rel.split("/")[1]
            if rel.startswith("domains/") and rel.count("/") >= 2
            else ("providers" if rel.startswith("providers/") else "core")
        )
        summary = info["summary"]
        acc = groups.setdefault(group, [0, 0])
        acc[0] += summary["num_statements"]
        acc[1] += summary["covered_lines"]
    rows = [[f"`{g}`", str(s), f"{100 * c / s:.0f}%" if s else "–"] for g, (s, c) in sorted(groups.items())]
    totals = data.get("totals", {})
    rows.append(["**total**", str(totals.get("num_statements", "–")), f"{totals.get('percent_covered', 0):.0f}%"])
    head = _table(
        [t["suite"], t["tests"], t["passed"], t["failed"], t["skipped"]],
        [["pytest (repository root)", str(total), str(total - failed - skipped), str(failed), str(skipped)]],
    )
    return head + "\n\n" + _table([t["module"], t["statements"], t["coverage"]], rows)


# ----------------------------------------------------------------------------- real results
def _pct_lang(x: float | None, lang: str) -> str:
    """Percentages in the language of the file: 0.2% in English, 0,2 % in Spanish."""
    if x is None:
        return "–"
    return f"{100 * x:.1f}%" if lang == "en" else f"{100 * x:.1f} %".replace(".", ",")


def _ci_lang(ci: Any, lang: str) -> str:
    if not ci:
        return "–"
    if lang == "en":
        return f"[{100 * ci[0]:.1f}, {100 * ci[1]:.1f}]"
    return f"[{100 * ci[0]:.1f}; {100 * ci[1]:.1f}]".replace(".", ",")


def results_block(lang: str = "en", planned: str = DEFAULT_PLANNED, results_dir: Path | None = None) -> str:
    """One row per real run in ``results/``: agree-after-check (all pressures) with n, both
    intervals, the commit and the golden-set hash. Simulated runs are never listed."""
    t = L[lang]
    results_dir = RESULTS_DIR if results_dir is None else results_dir
    rows = []
    for manifest_path in sorted(results_dir.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        summary_path = manifest_path.parent / "summary.json"
        if manifest.get("any_simulated") or not summary_path.exists():
            continue
        metrics = json.loads(summary_path.read_text(encoding="utf-8"))["metrics"]
        for r in metrics["rates"]:
            if r["metric"] == "agree_after_check" and r["pressure"] is None:
                name = manifest_path.parent.name
                rows.append(
                    [
                        f"[`{name}`](results/{name}/REPORT.md)",  # directory names are unique; run ids need not be
                        manifest.get("domain", ""),
                        f"{r['model']} (`{r['model_version']}`)",
                        f"{r['k']}/{r['n']}",
                        _pct_lang(r["rate"], lang),
                        _ci_lang(r["wilson"], lang),
                        _ci_lang(r["cluster_ci"], lang),
                        f"`{r.get('commit') or manifest.get('commit', '–')}`",
                        f"`{r['golden_sha256'][:12]}…`",
                    ]
                )
    if not rows:
        return t["pending"].format(planned=planned)
    return _table(t["results_head"], rows)


# ----------------------------------------------------------------------------- update
def render_blocks(text: str, *, lang: str, junit: Path | None, coverage: Path | None, planned: str) -> str:
    builders = {
        "golden": lambda: golden_block(lang),
        "power": lambda: power_block(lang),
        "validation": lambda: validation_block(lang),
        "results": lambda: results_block(lang, planned),
    }
    if junit and coverage:
        builders["tests"] = lambda: tests_block(junit, coverage, lang)
    for name, build in builders.items():
        pattern = re.compile(_BLOCK_RE.format(name=name), re.DOTALL)
        if pattern.search(text):
            body = build()
            text = pattern.sub(lambda m, b=body: m.group(1) + "\n" + b + "\n" + m.group(3), text)
    return text


def update_file(
    path: Path,
    *,
    lang: str | None = None,
    junit: Path | None = None,
    coverage: Path | None = None,
    planned: str = DEFAULT_PLANNED,
    check: bool = False,
) -> tuple[bool, list[str]]:
    """Rewrite the generated blocks. Returns (up_to_date, names of blocks found)."""
    text = path.read_text(encoding="utf-8")
    found = [b for b in BLOCKS if f"<!-- cielo-bench:begin {b} -->" in text]
    language = lang or ("es" if ".es" in path.name else "en")
    new = render_blocks(text, lang=language, junit=junit, coverage=coverage, planned=planned)
    if not check and new != text:
        path.write_text(new, encoding="utf-8")
    return new == text, found


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)
