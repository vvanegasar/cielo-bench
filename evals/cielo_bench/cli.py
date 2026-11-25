"""Command line: ``cielo-bench <command>``.

cielo-bench reproduce --simulated      # end to end, no network, no keys (used in CI)
cielo-bench reproduce --simulated --quick
cielo-bench reproduce --from RUN_DIR   # rebuild a run's report from its raw transcripts
cielo-bench run                        # real models from .env (asks before spending)
cielo-bench run --simulated            # simulated models, full control of the design
cielo-bench report RUN_DIR             # REPORT.md + figures + summary.json from raw JSONL
cielo-bench compare RUN_DIR... --out D  # models on identical items, across runs (COMPARISON.md)
cielo-bench estimate                   # cost estimate of a design, per model
cielo-bench power                      # power and minimum detectable effects
cielo-bench build-golden               # (re)build the golden set from the source (cached)
cielo-bench verify                     # offline integrity checks of fixtures and golden set
cielo-bench domains                    # list registered domains
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent import run_conversation
from .config import RESULTS_DIR, load_settings
from .domain import Domain
from .domains import AVAILABLE, get_domain
from .golden import PRESSURES, GoldenSet, load_golden, write_golden
from .pricing import PRICES_AS_OF, price_for
from .prompts import system_prompt
from .providers import build_provider, is_simulated_spec, provider_kind
from .providers.simulated import SimulatedProvider
from .runner import CONDITIONS, PREMISES, RunSpec, execute_run, plan_trials
from .stats import design_effect, paired_mde, proportion_halfwidth

SIMULATED_MODELS = "sim:careful,sim:agreeable"
OUTPUT_TOKEN_SCENARIOS = (300, 1000, 3000)
QUICK_PAIRS = 18  # one pair per template (astronomy): the CI smoke design


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


# ----------------------------------------------------------------------------- golden set
def cmd_domains(args: argparse.Namespace) -> int:
    for name in AVAILABLE:
        domain = get_domain(name)
        print(f"{name}: {domain.title} (golden: {domain.golden_path})")
    return 0


def cmd_build_golden(args: argparse.Namespace) -> int:
    domain = get_domain(args.domain)
    doc = domain.build_golden(offline=args.offline, max_requests=args.max_requests, settings=load_settings())
    sha = write_golden(doc, domain.golden_path)
    golden = load_golden(domain.golden_path)
    print(f"golden set written: {domain.golden_path}\nsha256: {sha}")
    print(
        f"pairs: {len(golden.pairs)} · templates: {len(golden.templates)} · "
        f"langs: {dict(Counter(p['lang'] for p in golden.pairs))}"
    )
    problems = domain.verify_golden(golden)
    print("verify:", problems if problems else "ok")
    return 1 if problems else 0


def verify_domain(domain: Domain) -> tuple[GoldenSet, list[str]]:
    golden = load_golden(domain.golden_path)
    return golden, domain.verify_golden(golden)


def cmd_verify(args: argparse.Namespace) -> int:
    golden, problems = verify_domain(get_domain(args.domain))
    print(f"golden set {golden.path.name}: sha256 {golden.sha256} ({len(golden.pairs)} pairs)")
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        return 1
    print("ok: fixtures intact, facts re-derivable from fixtures, every premise rule holds")
    return 0


# ----------------------------------------------------------------------------- design helpers
def _spec_from_args(
    args: argparse.Namespace,
    domain: Domain,
    golden: GoldenSet,
    providers: list[Any],
    out: Path,
    run_id: str,
    simulated: bool,
    settings: dict[str, str],
) -> RunSpec:
    return RunSpec(
        domain=domain,
        golden=golden,
        providers=providers,
        out_dir=out,
        run_id=run_id,
        simulated=simulated,
        settings=settings,
        conditions=tuple(_csv(args.conditions)),
        premises=tuple(_csv(args.premises)),
        pressures=tuple(_csv(args.pressures)) if args.pressures else tuple(golden.doc.get("frames") or PRESSURES),
        pair_filter=args.pair_filter,
        fault_pressures=tuple(_csv(args.fault_pressures)),
        fault_limit=args.fault_limit,
        reps=args.reps,
        langs=args.langs,
        limit_pairs=args.limit,
        seed=args.seed,
        workers=getattr(args, "workers", 1),
        max_usd=getattr(args, "max_usd", None),
        max_live_requests=getattr(args, "max_live_requests", 40),
        offline=simulated or getattr(args, "offline", False),
        resume=getattr(args, "resume", False),
        cache_outputs=not getattr(args, "no_output_cache", False),
        progress=not getattr(args, "quiet", False),
    )


def estimate_costs(
    spec: RunSpec, descriptions: list[dict[str, Any]], settings: dict[str, str], sample_pairs: int = 24
) -> list[dict[str, Any]]:
    """Token profile from a simulated pass over a balanced sample of the real prompts and tool
    outputs (offline), scaled to the full design."""
    domain, golden = spec.domain, spec.golden
    sim = SimulatedProvider("careful", domain, golden)
    full = plan_trials(RunSpec(**{**spec.__dict__, "providers": [sim]}))
    sample_spec = RunSpec(
        **{**spec.__dict__, "providers": [sim], "limit_pairs": min(sample_pairs, spec.limit_pairs or sample_pairs)}
    )
    sample = plan_trials(sample_spec)
    executors = {"no_tool": None, "tool": domain.make_executor(offline=True, max_live_requests=0)}
    for condition in ("fault_down", "fault_error", "fault_empty"):
        executors[condition] = domain.make_executor(fault_profile=condition.removeprefix("fault_"))
    tools = domain.tool_specs()
    rounds = in_tokens = 0.0
    for plan in sample:
        pair = golden.pair(plan.pair_id)
        offered = None if plan.condition == "no_tool" else tools
        conv = run_conversation(
            sim,
            trial_id=plan.trial_id,
            system=system_prompt(domain, plan.lang),
            user_text=GoldenSet.question(pair, plan.premise, plan.pressure, plan.lang),
            tools=offered,
            executor=executors.get(plan.condition),
        )
        n = len(conv["rounds"])
        rounds += n
        # chars/4 x 1.2 (tokenizer margin) + ~400 hidden tool-use tokens per request with tools
        in_tokens += 1.2 * conv["usage_total"]["input_tokens"] + (400 * n if offered else 0)
    scale = len(full) / max(1, len(sample))
    out = []
    for d in descriptions:
        price = price_for(d, settings)
        row: dict[str, Any] = {
            "label": d["label"],
            "price": price,
            "trials": len(full),
            "requests": int(rounds * scale),
            "input_tokens": int(in_tokens * scale),
            "scenarios": {},
        }
        for per_call in OUTPUT_TOKEN_SCENARIOS:
            row["scenarios"][per_call] = (
                None if price is None else (in_tokens * scale * price[0] + rounds * scale * per_call * price[1]) / 1e6
            )
        out.append(row)
    return out


def print_estimates(rows: list[dict[str, Any]]) -> None:
    head = " | ".join(f"{n} out/request" for n in OUTPUT_TOKEN_SCENARIOS)
    print(f"Cost estimate (USD, prices as of {PRICES_AS_OF}); columns: output tokens per request (incl. reasoning)")
    print("  model | trials | requests | input tokens | " + head)
    for r in rows:
        cells = " | ".join("price unknown" if v is None else f"US${v:.2f}" for v in r["scenarios"].values())
        print(f"  {r['label']} | {r['trials']} | {r['requests']} | {r['input_tokens']:,} | {cells}")


def _descriptions_for(specs: list[str], settings: dict[str, str]) -> list[dict[str, Any]]:
    from .providers import SETTINGS_PREFIX

    out = []
    for s in specs:
        kind = provider_kind(s)
        model = s.partition(":")[2]
        if not model and kind in SETTINGS_PREFIX:
            model = settings.get(f"{SETTINGS_PREFIX[kind]}_MODEL", "")
        out.append({"label": s, "provider": kind, "model": model})
    return out


# ----------------------------------------------------------------------------- commands
def cmd_estimate(args: argparse.Namespace) -> int:
    domain = get_domain(args.domain)
    golden = load_golden(domain.golden_path)
    settings = load_settings()
    specs = (
        _csv(args.models)
        if args.models
        else ["anthropic:claude-opus-5-5", "anthropic:claude-sonnet-5-5", "anthropic:claude-haiku-5-5"]
    )
    spec = _spec_from_args(args, domain, golden, [], Path("."), "estimate", True, settings)
    print_estimates(estimate_costs(spec, _descriptions_for(specs, settings), settings))
    return 0


def cmd_power(args: argparse.Namespace) -> int:
    for label, n in (
        ("one pressure level", args.pairs),
        (f"pooled over {args.pressures} pressure levels", args.pairs * args.pressures),
    ):
        m = n / args.templates
        print(f"{label}: {n} units in {args.templates} templates ({m:.1f} per template)")
        print("  ICC | DEFF | ±half-width at 50% | MDE paired psi=20% | psi=40%")
        for icc in (0.0, 0.05, 0.2):
            deff = design_effect(m, icc)
            hw = proportion_halfwidth(n, 0.5, deff) or 0.0
            mdes = [paired_mde(n, 0.2, deff=deff), paired_mde(n, 0.4, deff=deff)]
            cells = " | ".join("not detectable" if v is None else f"{100 * v:.1f} pp" for v in mdes)
            print(f"  {icc:.2f} | {deff:.2f} | ±{100 * hw:.1f} pp | {cells}")
    return 0


def _run(args: argparse.Namespace, *, report: bool) -> tuple[int, Path | None]:
    domain = get_domain(args.domain)
    golden = load_golden(domain.golden_path)
    simulated = bool(args.simulated)
    if simulated:
        settings: dict[str, str] = {}  # a simulated run never reads .env or any key
        specs = _csv(args.models or SIMULATED_MODELS)
        if not all(is_simulated_spec(s) for s in specs):
            print("--simulated only accepts simulated models (sim:careful, sim:agreeable)", file=sys.stderr)
            return 2, None
    else:
        settings = load_settings()
        specs = _csv(args.models or settings.get("CIELO_MODELS", "anthropic,openai"))
    # unique even for runs started in the same second (a resumed run keeps its first id)
    run_id = f"{_stamp()}-{'simulated' if simulated else 'real'}-{secrets.token_hex(3)}"
    if args.resume and args.out is None:
        print("--resume needs --out <existing run dir>", file=sys.stderr)
        return 2, None
    out = Path(args.out) if args.out else RESULTS_DIR / run_id
    try:
        providers = [build_provider(s, settings=settings, domain=domain, golden=golden, seed=args.seed) for s in specs]
    except ValueError as exc:
        print(f"cannot set up the models: {exc}", file=sys.stderr)
        return 2, None
    if not simulated and args.max_usd is None:
        args.max_usd = float(settings.get("CIELO_MAX_USD") or 10)
    spec = _spec_from_args(args, domain, golden, providers, out, run_id, simulated, settings)
    if not simulated:
        descriptions = [p.describe() for p in providers]
        missing = [d["label"] for d in descriptions if price_for(d, settings) is None]
        if missing:
            print(
                f"no price known for {missing}: set <PREFIX>_PRICE_IN_PER_MTOK and <PREFIX>_PRICE_OUT_PER_MTOK "
                "in .env (the budget guard needs them)",
                file=sys.stderr,
            )
            return 2, None
        print_estimates(estimate_costs(spec, descriptions, settings))
        print(f"Budget guard: the run stops at US${spec.max_usd:.2f}.")
        if not args.yes:
            if not sys.stdin.isatty():
                print("refusing to spend without confirmation: rerun with --yes", file=sys.stderr)
                return 2, None
            if input("Proceed with the real run? [y/N] ").strip().lower() not in ("y", "yes"):
                print("cancelled")
                return 1, None
    print(f"run {run_id}: {len(plan_trials(spec))} trials -> {out}", file=sys.stderr)
    run_dir = execute_run(spec)
    print(f"raw transcripts: {run_dir / 'trials.jsonl'}")
    if report:
        from .report import build_report

        print(f"report: {build_report(run_dir)}")
    return 0, run_dir


def cmd_run(args: argparse.Namespace) -> int:
    return _run(args, report=not args.no_report)[0]


def cmd_report(args: argparse.Namespace) -> int:
    from .report import build_report

    print(build_report(args.run_dir, args.out))
    return 0


def cmd_ladder(args: argparse.Namespace) -> int:
    """Analyse a distance-ladder run: curve and H1, plus the confirmatory family when a config freezes the steps."""
    from .ladder import analyze, render
    from .report import score_run

    if len(args.run_dirs) > 1 and not args.out:
        print("several run directories need --out: the analysis is written there", file=sys.stderr)
        return 2
    scored: list[dict[str, Any]] = []
    for run_dir in args.run_dirs:  # the confirmatory design is several runs (tool and two-turn, per model)
        scored += score_run(run_dir)[1]
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else None
    result = analyze(scored, config)
    out = args.out or args.run_dirs[0]
    out.mkdir(parents=True, exist_ok=True)
    (out / "LADDER.md").write_text(render(result), encoding="utf-8")
    (out / "ladder_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out / "LADDER.md")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from .compare import compare

    try:
        print(compare(args.run_dirs, args.out))
    except ValueError as exc:
        print(f"cannot compare: {exc}", file=sys.stderr)
        return 2
    return 0


def cmd_reproduce(args: argparse.Namespace) -> int:
    from .report import build_report

    if args.from_run:
        print(f"report rebuilt from raw transcripts: {build_report(Path(args.from_run))}")
        return 0
    if not args.simulated:
        print("reproduce needs --simulated (no network, no keys) or --from RUN_DIR", file=sys.stderr)
        return 2
    domain = get_domain(args.domain)
    golden, problems = verify_domain(domain)
    if problems:
        print("verify failed:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print(f"verify: ok (golden {golden.sha256[:16]}…, {len(golden.pairs)} pairs)")
    run_args = argparse.Namespace(
        **{
            **vars(args),
            "models": SIMULATED_MODELS,
            "limit": QUICK_PAIRS if args.quick else None,
            "resume": False,
            "yes": True,
        }
    )
    code, run_dir = _run(run_args, report=True)
    if code or run_dir is None:
        return code
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    for r in summary["metrics"]["rates"]:
        if r["metric"] == "agree_after_check" and r["pressure"] is None:
            print(
                f"  [SIMULATED] agree-after-check {r['model']}: {r['k']}/{r['n']} = {100 * r['rate']:.1f}% "
                f"(Wilson {_fmt_ci(r['wilson'])}, cluster {_fmt_ci(r['cluster_ci'])})"
            )
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    from .report import pack_run

    packed = pack_run(args.run_dir)
    print(f"packed: {packed} ({packed.stat().st_size:,} bytes); trials.jsonl stays local (git-ignored)")
    return 0


def cmd_docs(args: argparse.Namespace) -> int:
    from .config import PROJECT_ROOT
    from .docs import update_file

    if not args.update_readme_tables:
        print("nothing to do: pass --update-readme-tables", file=sys.stderr)
        return 2
    files = [Path(f) for f in (args.file or [PROJECT_ROOT / "README.md"])]
    stale = []
    for path in files:
        up_to_date, found = update_file(
            path, lang=args.lang, junit=args.junit, coverage=args.coverage, planned=args.planned, check=args.check
        )
        if not found:
            print(f"{path}: no cielo-bench blocks")
            continue
        state = "up to date" if up_to_date else ("STALE" if args.check else "updated")
        print(f"{path}: {state} ({', '.join(found)})")
        if not up_to_date:
            stale.append(path)
    return 1 if (args.check and stale) else 0


def _fmt_ci(ci: Any) -> str:
    return "–" if not ci else f"[{100 * ci[0]:.1f}, {100 * ci[1]:.1f}]"


def _add_design_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--conditions", default=",".join(CONDITIONS))
    p.add_argument("--premises", default=",".join(PREMISES))
    p.add_argument(
        "--pressures",
        default=None,
        help="framings for no_tool and tool (default: every framing the golden set defines)",
    )
    p.add_argument("--pair-filter", default=None, help="only pairs whose id matches this regular expression")
    p.add_argument("--fault-pressures", default="assertive", help="pressure levels for the fault conditions")
    p.add_argument("--fault-limit", type=int, help="number of pairs in the fault block (default: all)")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument(
        "--langs",
        choices=["assigned", "both"],
        default="assigned",
        help="assigned: each pair in its own language (default); both: ES and EN",
    )
    p.add_argument("--limit", type=int, help="only N pairs, round-robin across templates")
    p.add_argument("--seed", type=int, default=20261206)


def _add_run_args(p: argparse.ArgumentParser) -> None:
    _add_design_args(p)
    p.add_argument(
        "--models",
        help="comma-separated: sim:careful, sim:agreeable, anthropic[:MODEL], "
        "openai[:MODEL], openrouter[:MODEL], ollama[:MODEL], compat[:MODEL]",
    )
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--max-usd", type=float, help="hard budget stop (default CIELO_MAX_USD or 10)")
    p.add_argument(
        "--max-live-requests",
        type=int,
        default=40,
        help="cap on live source requests (tool calls outside the cached fixtures)",
    )
    p.add_argument("--offline", action="store_true", help="tools answer from the cache only")
    p.add_argument("--out", type=Path, help="run directory (default results/<run-id>)")
    p.add_argument("--resume", action="store_true", help="continue an interrupted run in --out")
    p.add_argument("--no-output-cache", action="store_true", help="do not cache raw model responses")
    p.add_argument("--yes", action="store_true", help="do not ask before spending")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cielo-bench",
        description="Check or agree? A sycophancy benchmark for tool-using agents with verifiable ground truth.",
    )
    parser.add_argument("--domain", default="astronomy", choices=AVAILABLE)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="cache for live upstream responses (default CIELO_CACHE_DIR or ~/.cache/cielo-bench)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("domains", help="list registered domains").set_defaults(func=cmd_domains)

    p = sub.add_parser("build-golden", help="fetch fixtures (serialized, cached) and build the golden set")
    p.add_argument("--offline", action="store_true", help="use cached fixtures only")
    p.add_argument("--max-requests", type=int, default=80)
    p.set_defaults(func=cmd_build_golden)

    sub.add_parser("verify", help="offline integrity checks").set_defaults(func=cmd_verify)

    p = sub.add_parser("run", help="run a design and build its report")
    _add_run_args(p)
    p.add_argument(
        "--simulated",
        "--dry-run",
        dest="simulated",
        action="store_true",
        help="simulated models only: no network, no keys",
    )
    p.add_argument("--no-report", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("reproduce", help="end to end without network or keys (--simulated), or rebuild a report")
    _add_run_args(p)
    p.add_argument("--simulated", action="store_true", help="simulated models, offline sources, no keys")
    p.add_argument("--quick", action="store_true", help=f"{QUICK_PAIRS} pairs, round-robin across templates, for CI")
    p.add_argument("--from", dest="from_run", type=Path, help="rebuild the report of an existing run directory")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_reproduce)

    p = sub.add_parser("report", help="build REPORT.md, figures and summary from a run directory")
    p.add_argument("run_dir", type=Path)
    p.add_argument("--out", type=Path, help="output directory (default: the run directory)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("ladder", help="analyse distance-ladder runs (curve, H1; contrasts with a frozen config)")
    p.add_argument("run_dirs", type=Path, nargs="+", metavar="run_dir", help="one or several runs, analysed together")
    p.add_argument("--config", type=Path, help="JSON that freezes grey_steps (and insist_steps, equivalence_bound)")
    p.add_argument("--out", type=Path, help="output directory (default: the run directory)")
    p.set_defaults(func=cmd_ladder)

    p = sub.add_parser("compare", help="compare models from several runs on the units they all share")
    p.add_argument("run_dirs", type=Path, nargs="+")
    p.add_argument("--out", type=Path, required=True, help="directory for COMPARISON.md and comparison.json")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("estimate", help="cost estimate of a design, per model")
    _add_design_args(p)
    p.add_argument("--models", help="comma-separated model specs (default: three Anthropic models)")
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("pack", help="compress a run's trials.jsonl to trials.jsonl.gz for versioning")
    p.add_argument("run_dir", type=Path)
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("docs", help="regenerate the tables between cielo-bench markers in README files")
    p.add_argument("--update-readme-tables", action="store_true")
    p.add_argument("--file", action="append", help="Markdown file to update (repeatable; default README.md)")
    p.add_argument("--check", action="store_true", help="do not write; exit 1 if a block is out of date")
    p.add_argument("--junit", type=Path, help="pytest JUnit XML, for the test-suite table")
    p.add_argument("--coverage", type=Path, help="coverage JSON report, for the test-suite table")
    p.add_argument("--planned", default="before 2026-12-06", help="planned date of the first real-model runs")
    p.add_argument("--lang", choices=["en", "es"], help="table language (default: from the file name)")
    p.set_defaults(func=cmd_docs)

    p = sub.add_parser("power", help="power and minimum detectable effects of the design")
    p.add_argument("--pairs", type=int, default=120)
    p.add_argument("--templates", type=int, default=8)
    p.add_argument("--pressures", type=int, default=3)
    p.set_defaults(func=cmd_power)

    args = parser.parse_args(argv)
    if args.cache_dir:
        os.environ["CIELO_CACHE_DIR"] = str(args.cache_dir)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
