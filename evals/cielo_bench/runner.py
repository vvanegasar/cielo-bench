"""Run the benchmark: models x pairs x premises x pressures x conditions x repetitions -> JSONL.

Conditions:

* ``no_tool``     - no tool definitions are sent;
* ``tool``        - the domain's tools are offered and answer from the real source (cached);
* ``fault_down``  - tools offered, the source cannot be reached;
* ``fault_error`` - tools offered, the source answers with an error;
* ``fault_empty`` - tools offered, the source answers with no data.

The core block (``no_tool``, ``tool``) crosses premise x pressure on every pair. The fault
block runs at the pressures in ``fault_pressures`` (default: assertive) on ``fault_limit``
pairs (default: all). Every trial is one JSON line with the full exchange: raw responses,
tool calls, tool results, usage and cost. Scores are computed later, from these records only.
"""

from __future__ import annotations

import json
import platform
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .agent import run_conversation
from .config import PROJECT_ROOT, git_commit, user_agent
from .domain import FAULT_KINDS, Domain, ToolExecutor
from .golden import LANGS, PRESSURES, GoldenSet
from .pricing import PRICES_AS_OF, cost_usd, price_for
from .prompts import prompt_sha256, system_prompt
from .providers.base import Provider
from .providers.http import HTTPProviderMixin, ResponseCache

CORE_CONDITIONS = ("no_tool", "tool")
FAULT_CONDITIONS = {f"fault_{kind}": kind for kind in FAULT_KINDS}
CONDITIONS = CORE_CONDITIONS + tuple(FAULT_CONDITIONS)
TOOL_CONDITIONS = ("tool", *FAULT_CONDITIONS)
PREMISES = ("true", "false")
COT = timezone(timedelta(hours=-5), "COT")


@dataclass(frozen=True)
class TrialPlan:
    trial_id: str
    provider_index: int
    pair_id: str
    premise: str
    pressure: str
    condition: str
    lang: str
    rep: int


@dataclass
class RunSpec:
    domain: Domain
    golden: GoldenSet
    providers: list[Provider]
    out_dir: Path
    run_id: str
    simulated: bool
    settings: dict[str, str] = field(default_factory=dict)
    conditions: tuple[str, ...] = CONDITIONS
    premises: tuple[str, ...] = PREMISES
    pressures: tuple[str, ...] = PRESSURES
    fault_pressures: tuple[str, ...] = ("assertive",)
    fault_limit: int | None = None
    reps: int = 1
    langs: str = "assigned"  # "assigned" (one language per pair) or "both"
    limit_pairs: int | None = None
    seed: int = 20261206
    workers: int = 1
    max_usd: float | None = None
    max_live_requests: int | None = 40
    offline: bool = True
    resume: bool = False
    cache_outputs: bool = True
    progress: bool = True


def round_robin(pairs: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """All pairs, or a subset taken round-robin across templates (keeps clusters balanced)."""
    if limit is None or limit >= len(pairs):
        return list(pairs)
    queues: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        queues.setdefault(pair["template"], []).append(pair)
    ordered = list(queues.values())
    chosen: list[dict[str, Any]] = []
    i = 0
    while len(chosen) < limit:
        queue = ordered[i % len(ordered)]
        if queue:
            chosen.append(queue.pop(0))
        i += 1
    return chosen


def plan_trials(spec: RunSpec) -> list[TrialPlan]:
    for condition in spec.conditions:
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition {condition!r}; choose from {CONDITIONS}")
    for pressure in (*spec.pressures, *spec.fault_pressures):
        if pressure not in PRESSURES:
            raise ValueError(f"unknown pressure {pressure!r}; choose from {PRESSURES}")
    pairs = round_robin(spec.golden.pairs, spec.limit_pairs)
    fault_ids = {p["pair_id"] for p in round_robin(pairs, spec.fault_limit)}
    plans = []
    for pair in pairs:
        langs = [pair["lang"]] if spec.langs == "assigned" else list(LANGS)
        for lang in langs:
            for premise in spec.premises:
                for condition in spec.conditions:
                    is_fault = condition in FAULT_CONDITIONS
                    if is_fault and pair["pair_id"] not in fault_ids:
                        continue
                    for pressure in spec.fault_pressures if is_fault else spec.pressures:
                        for rep in range(spec.reps):
                            for index, provider in enumerate(spec.providers):
                                trial_id = (
                                    f"{provider.label}|{pair['pair_id']}|{lang}|{premise}|{pressure}|{condition}|r{rep}"
                                )
                                plans.append(
                                    TrialPlan(trial_id, index, pair["pair_id"], premise, pressure, condition, lang, rep)
                                )
    return plans


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def make_executors(spec: RunSpec) -> dict[str, ToolExecutor | None]:
    executors: dict[str, ToolExecutor | None] = {"no_tool": None}
    if "tool" in spec.conditions:
        executors["tool"] = spec.domain.make_executor(
            offline=spec.offline, max_live_requests=spec.max_live_requests, settings=spec.settings
        )
    for condition, kind in FAULT_CONDITIONS.items():
        if condition in spec.conditions:
            if kind not in spec.domain.fault_profiles:
                raise ValueError(f"domain {spec.domain.name!r} does not support fault profile {kind!r}")
            executors[condition] = spec.domain.make_executor(fault_profile=kind, settings=spec.settings)
    return executors


def execute_run(spec: RunSpec) -> Path:
    out = spec.out_dir
    out.mkdir(parents=True, exist_ok=True)
    trials_path = out / "trials.jsonl"
    manifest_path = out / "manifest.json"
    done: set[str] = set()
    if trials_path.exists():
        if not spec.resume:
            raise FileExistsError(f"{trials_path} exists; use --resume or another --out")
        for line in trials_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                if not record.get("error"):
                    done.add(record["trial_id"])

    domain, golden = spec.domain, spec.golden
    tool_specs = domain.tool_specs()
    executors = make_executors(spec)
    if spec.cache_outputs:
        for provider in spec.providers:
            if isinstance(provider, HTTPProviderMixin):
                provider.cache = ResponseCache(out / "cache")
    systems = {lang: system_prompt(domain, lang) for lang in LANGS}
    descriptions = [p.describe() for p in spec.providers]
    prices = [price_for(d, spec.settings) for d in descriptions]
    plans = plan_trials(spec)
    pending = [p for p in plans if p.trial_id not in done]
    now = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "run_id": spec.run_id,
        "status": "running",
        "simulated": all(p.simulated for p in spec.providers),
        "any_simulated": any(p.simulated for p in spec.providers),
        "created_at_utc": _iso(now),
        "created_at_cot": now.astimezone(COT).isoformat(timespec="seconds"),
        "commit": git_commit(),
        "code_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "domain": domain.name,
        "domain_title": domain.title,
        "credits": list(domain.credits),
        "golden": {
            "path": relative(golden.path),
            "sha256": golden.sha256,
            "n_pairs": len(golden.pairs),
            "templates": golden.templates,
            "version": golden.doc.get("version"),
        },
        "models": descriptions,
        "prices_usd_per_mtok": {d["label"]: p for d, p in zip(descriptions, prices, strict=True)},
        "prices_as_of": PRICES_AS_OF,
        "design": {
            "conditions": list(spec.conditions),
            "premises": list(spec.premises),
            "pressures": list(spec.pressures),
            "fault_pressures": list(spec.fault_pressures),
            "fault_limit": spec.fault_limit,
            "fault_profiles": {c: k for c, k in FAULT_CONDITIONS.items() if c in spec.conditions},
            "reps": spec.reps,
            "langs": spec.langs,
            "limit_pairs": spec.limit_pairs,
            "seed": spec.seed,
        },
        "max_live_requests": spec.max_live_requests,
        "offline_source": spec.offline,
        "output_cache": spec.cache_outputs,
        "user_agent": user_agent(spec.settings),
        "system_prompts_sha256": {lang: prompt_sha256(text) for lang, text in systems.items()},
        "system_prompts": systems,
        "tools": [t["name"] for t in tool_specs],
        "n_trials_planned": len(plans),
        "n_trials_already_done": len(done),
        "max_usd": spec.max_usd,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lock = threading.Lock()
    state: dict[str, Any] = {"cost": 0.0, "completed": 0, "errors": 0, "stopped": None}

    def run_one(plan: TrialPlan) -> dict[str, Any]:
        provider = spec.providers[plan.provider_index]
        pair = golden.pair(plan.pair_id)
        question = GoldenSet.question(pair, plan.premise, plan.pressure, plan.lang)
        offered = None if plan.condition == "no_tool" else tool_specs
        conversation = run_conversation(
            provider,
            trial_id=plan.trial_id,
            system=systems[plan.lang],
            user_text=question,
            tools=offered,
            executor=executors.get(plan.condition),
        )
        return {
            "trial_id": plan.trial_id,
            "run_id": spec.run_id,
            "model_label": provider.label,
            "provider": provider.provider,
            "model_id": provider.model,
            "pair_id": plan.pair_id,
            "template": pair["template"],
            "lang": plan.lang,
            "premise": plan.premise,
            "pressure": plan.pressure,
            "condition": plan.condition,
            "rep": plan.rep,
            "fault_kind": FAULT_CONDITIONS.get(plan.condition),
            "system_prompt_sha256": manifest["system_prompts_sha256"][plan.lang],
            "user_text": question,
            "tools_offered": [t["name"] for t in offered or []],
            **conversation,
            "cost_usd": cost_usd(provider.provider, conversation["usage_total"], prices[plan.provider_index]),
        }

    def record_done(record: dict[str, Any]) -> None:
        with lock:
            with trials_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            state["completed"] += 1
            state["errors"] += bool(record.get("error"))
            state["cost"] += record.get("cost_usd") or 0.0
            if spec.progress and (state["completed"] % 200 == 0 or state["completed"] == len(pending)):
                print(
                    f"  [{state['completed']}/{len(pending)}] trials done, cost so far "
                    f"US${state['cost']:.4f}, errors {state['errors']}",
                    file=sys.stderr,
                )

    with ThreadPoolExecutor(max_workers=max(1, spec.workers)) as pool:
        in_flight: set[Future[dict[str, Any]]] = set()
        for plan in pending:
            if spec.max_usd is not None and state["cost"] >= spec.max_usd:
                state["stopped"] = f"budget of US${spec.max_usd} reached"
                break
            in_flight.add(pool.submit(run_one, plan))
            if len(in_flight) >= max(1, spec.workers):
                finished, in_flight = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in finished:
                    record_done(future.result())
        for future in in_flight:
            record_done(future.result())

    tool_executor = executors.get("tool")
    manifest.update(
        {
            "status": "stopped" if state["stopped"] else "complete",
            "stopped_reason": state["stopped"],
            "finished_at_utc": _iso(datetime.now(UTC)),
            "n_trials_completed_this_session": state["completed"],
            "n_trial_errors_this_session": state["errors"],
            "cost_usd_this_session": round(state["cost"], 6),
            "source_live_requests": tool_executor.live_requests if tool_executor is not None else 0,
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
