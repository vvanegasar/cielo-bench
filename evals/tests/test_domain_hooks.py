"""The optional domain hooks (ADR-0009): their defaults keep the question-answering design, and a
domain that overrides them gets its own conditions, worlds, prompts, texts and per-trial sandboxes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cielo_bench.domain import Domain, Evidence, TrialContext
from cielo_bench.golden import (
    LANGS,
    PRESSURES,
    WORLDS_SCHEMA_VERSION,
    GoldenSet,
    validate_structure,
    validate_worlds_structure,
)
from cielo_bench.prompts import answer_format, system_prompt
from cielo_bench.providers.base import Conversation, Provider, Turn, Usage
from cielo_bench.runner import (
    CONDITIONS,
    PREMISES,
    RunSpec,
    execute_run,
    plan_trials,
    prompts_for_manifest,
    round_robin,
    system_prompts,
    world_free_id,
)


class Echo(Provider):
    """Answers every turn with one line and no tool call; records what it was sent."""

    provider = "simulated"
    simulated = True

    def __init__(self) -> None:
        super().__init__("echo", label="sim:echo")
        self.seen: list[tuple[str, str, list[str]]] = []
        self.effort: str | None = None

    def complete(self, conv: Conversation) -> Turn:
        self.seen.append((conv.system, conv.user_text, [t["name"] for t in conv.tools or []]))
        conv.messages.append({"role": "assistant", "content": "done"})
        return Turn("done", [], "end_turn", Usage(1, 1), "echo", {}, {}, 0.0)

    def add_tool_results(self, conv: Conversation, turn: Turn, results: list[dict[str, Any]]) -> None:
        raise AssertionError("no tool calls in this test")

    def set_effort(self, effort: str) -> bool:
        self.effort = effort
        return True


class Plain(Domain):
    """A minimal question-answering domain: every hook keeps its default."""

    name = "plain"

    @property
    def golden_path(self) -> Path:
        return Path("unused")

    def build_golden(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def verify_golden(self, golden: Any) -> list[str]:
        return []

    def system_preamble(self, lang: str) -> str:
        return f"role text ({lang})"

    def tool_specs(self) -> list[dict[str, Any]]:
        return [{"name": "look", "description": "d", "parameters": {"type": "object"}}]

    def make_executor(self, **kwargs: Any) -> Any:
        return None

    def premise_holds(self, pair, premise_value, facts):
        return None

    def evidence(self, pair, trace):
        return Evidence(False, False)


class Sandbox:
    def __init__(self, ctx: TrialContext, log: list[TrialContext]) -> None:
        self.executor = None
        self.ctx = ctx
        self.ended: list[int] = []
        log.append(ctx)

    def end_turn(self, turn: int) -> str | None:
        self.ended.append(turn)
        return "again" if turn == 1 else None

    def record(self) -> dict[str, Any]:
        return {"world": self.ctx.premise, "ended": list(self.ended)}

    def close(self) -> None:
        pass


class Worlds(Plain):
    """Overrides every hook, the way a domain that varies the data does."""

    name = "worlds"
    effort = "medium"
    interleave_templates = True
    report_kind = "act"

    def __init__(self) -> None:
        self.opened: list[TrialContext] = []

    def conditions(self):
        return ("ask", "act", "blind")

    def premises(self):
        return ("true", "far", "near")

    def premises_for(self, condition, premises):
        return ("any",) if condition == "blind" else premises

    def tools_for(self, condition):
        return None if condition == "blind" else self.tool_specs()

    def answer_mode(self, condition):
        return condition == "ask"

    def trial_text(self, pair, ctx):
        return f"request {pair['pair_id']} {ctx.pressure} {ctx.lang}"

    def round_caps(self, condition):
        return (3, 2)

    def open_trial(self, pair, ctx):
        return Sandbox(ctx, self.opened)


def golden_of(n_per_template: int = 2, templates: tuple[str, ...] = ("a", "b")) -> GoldenSet:
    pairs = [
        {"pair_id": f"{t}-{i}", "template": t, "lang": LANGS[i % 2]} for t in templates for i in range(n_per_template)
    ]
    return GoldenSet(doc={"pairs": pairs, "sha256": "0" * 64, "domain": "x"}, path=Path("golden.json"))


def run_spec(domain: Domain, golden: GoldenSet, out: Path, **kw: Any) -> RunSpec:
    return RunSpec(
        domain=domain, golden=golden, providers=[Echo()], out_dir=out, run_id="r", simulated=True, progress=False, **kw
    )


def test_defaults_keep_the_question_answering_design(tmp_path):
    domain = Plain()
    assert domain.conditions() is None and domain.premises() is None and domain.effort is None
    assert domain.premises_for("tool", PREMISES) == PREMISES
    assert domain.tools_for("no_tool") is None and domain.tools_for("tool") == domain.tool_specs()
    assert (
        domain.answer_mode("tool") and domain.round_caps("tool") is None and domain.make_simulator("x", None, 0) is None
    )
    spec = run_spec(domain, golden_of(), tmp_path)
    assert spec.conditions == CONDITIONS and spec.premises == PREMISES
    for lang in LANGS:  # the answer format is appended as before, with or without a condition
        assert system_prompt(domain, lang) == system_prompt(domain, lang, "tool")
        assert system_prompt(domain, lang).endswith(answer_format(domain, lang))
    assert prompts_for_manifest(system_prompts(domain, CONDITIONS)) == {
        lang: system_prompt(domain, lang) for lang in LANGS
    }
    order = [p["pair_id"] for p in round_robin(golden_of().pairs, None)]
    assert order == ["a-0", "a-1", "b-0", "b-1"]  # the golden set's order, unless asked to interleave


def test_conditions_worlds_and_world_free_conditions_are_planned_from_the_domain(tmp_path):
    domain = Worlds()
    spec = run_spec(domain, golden_of(), tmp_path, pressures=PRESSURES)
    assert spec.conditions == ("ask", "act", "blind") and spec.premises == ("true", "far", "near")
    plans = plan_trials(spec)
    # per pair: 3 worlds x 2 world-dependent conditions x 3 pressures + 1 world-free condition x 3 pressures
    assert len(plans) == 4 * (3 * 2 * 3 + 3)
    assert {p.premise for p in plans if p.condition == "blind"} == {"any"}
    assert [p.pair_id for p in plans][:: 3 * 2 * 3 + 3] == ["a-0", "b-0", "a-1", "b-1"]  # interleaved, in blocks
    with pytest.raises(ValueError, match="unknown condition"):
        plan_trials(run_spec(domain, golden_of(), tmp_path, conditions=("tool",)))
    with pytest.raises(ValueError, match="unknown premise"):
        plan_trials(run_spec(domain, golden_of(), tmp_path, premises=("false",)))
    a, b = [p for p in plans if p.pair_id == "a-0" and p.condition == "act" and p.pressure == "neutral"][:2]
    assert a.premise != b.premise and world_free_id(a, "m") == world_free_id(b, "m")


def test_answer_mode_prompts_differ_by_condition_in_the_manifest():
    domain = Worlds()
    prompts = system_prompts(domain, ("ask", "act", "blind"))
    assert prompts[("en", "act")] == prompts[("en", "blind")] == "role text (en)"
    assert prompts[("en", "ask")].endswith(answer_format(domain, "en"))
    keyed = prompts_for_manifest(prompts)
    assert set(keyed) == {f"{lang}|{c}" for lang in LANGS for c in ("ask", "act", "blind")}


def test_a_run_uses_the_hooks_end_to_end(tmp_path):
    domain = Worlds()
    provider = Echo()
    spec = RunSpec(
        domain=domain,
        golden=golden_of(1, ("a",)),
        providers=[provider],
        out_dir=tmp_path / "run",
        run_id="r",
        simulated=True,
        progress=False,
        pressures=("neutral",),
        workers=1,
    )
    run = execute_run(spec)
    records = [json.loads(line) for line in (run / "trials.jsonl").read_text().splitlines()]
    manifest = json.loads((run / "manifest.json").read_text())
    assert provider.effort == "medium" and manifest["design"]["effort"] == "medium"
    assert manifest["tools_by_condition"] == {"ask": ["look"], "act": ["look"], "blind": []}
    assert len(records) == 3 * 2 + 1 and len(domain.opened) == len(records)
    for r in records:
        assert r["user_text"] == f"request a-0 neutral {r['lang']}"
        assert r["sandbox"] == {"world": r["premise"], "ended": [1, 2]}  # the sandbox asked for a second turn
        assert [t["turn"] for t in r["turns"]] == [1, 2] and r["turns"][1]["user_text"] == "again"
        assert [rnd["turn"] for rnd in r["rounds"]] == [1, 2]
        assert r["system_prompt_sha256"] == manifest["system_prompts_sha256"][f"{r['lang']}|{r['condition']}"]
        assert r["tools_offered"] == ([] if r["condition"] == "blind" else ["look"])
    sent = {(system, tools[0] if tools else None) for system, _user, tools in provider.seen}
    lang = records[0]["lang"]
    assert ("role text (" + lang + ")", "look") in sent  # act: role text alone, with tools
    assert ("role text (" + lang + ")", None) in sent  # blind: role text alone, no tools
    assert (system_prompt(domain, lang, "ask"), "look") in sent  # answer mode: role text and answer format


def test_worlds_schema_validation():
    pair = {
        "pair_id": "t-01",
        "template": "t",
        "lang": "en",
        "context": {},
        "expected_calls": [{"tool": "run_sql", "args": {"sql": "SELECT 1"}}],
        "request": {"tool": "do", "args": {}},
        "requests": {p: {lang: "please" for lang in LANGS} for p in PRESSURES},
        "insistence": {lang: "again" for lang in LANGS},
        "worlds": {"true": {"patch": [], "patch_sha256": "x", "pre_sha256": "y", "facts": {}}},
    }
    doc = {"schema_version": WORLDS_SCHEMA_VERSION, "pairs": [pair]}
    assert validate_structure(doc) == validate_worlds_structure(doc) == []
    broken = json.loads(json.dumps(doc))
    del broken["pairs"][0]["requests"]["authority"]
    del broken["pairs"][0]["worlds"]["true"]["pre_sha256"]
    broken["pairs"].append(dict(broken["pairs"][0]))
    problems = validate_structure(broken)
    assert any("authority/en request" in p for p in problems)
    assert any("pre_sha256" in p for p in problems)
    assert any("duplicate pair_id" in p for p in problems)
    assert validate_worlds_structure({"pairs": []}) == ["golden set has no pairs"]
