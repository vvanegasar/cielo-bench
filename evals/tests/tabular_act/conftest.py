"""Fixtures for the act-domain tests: the domain, its golden set, a scorer, and a scripted agent that
produces real trial records (through the agent loop, the trial sandbox and the real tools)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pytest

from cielo_bench.agent import run_conversation
from cielo_bench.domains import get_domain
from cielo_bench.golden import load_golden
from cielo_bench.prompts import system_prompt
from cielo_bench.providers.base import Conversation, Provider, ToolCall, Turn, Usage
from cielo_bench.runner import TrialPlan, trial_context


@pytest.fixture(scope="session")
def act():
    return get_domain("tabular_act")


@pytest.fixture(scope="session")
def act_golden(act):
    return load_golden(act.golden_path)


@pytest.fixture(scope="session")
def pairs(act_golden):
    return {p["pair_id"]: p for p in act_golden.pairs}


@pytest.fixture(scope="session")
def scorer(act, act_golden):
    s = act.scorer(act_golden)
    yield s
    s.close()


class Scripted(Provider):
    """Plays a script: per user turn, a list of steps; a step is a list of (tool, args) calls or a text."""

    provider = "simulated"
    simulated = True

    def __init__(self, script: dict[int, list[Any]]):
        super().__init__("scripted", label="sim:scripted")
        self.script = script

    def complete(self, conv: Conversation) -> Turn:
        users = [i for i, m in enumerate(conv.messages) if m.get("role") == "user"]
        turn = len(users)
        rnd = sum(1 for m in conv.messages[users[-1] :] if m.get("role") == "assistant")
        steps = self.script.get(turn, ["(no more steps)"])
        step = steps[rnd] if rnd < len(steps) else "(no more steps)"
        calls = (
            [ToolCall(id=f"c{turn}{rnd}{i}", name=n, arguments=a) for i, (n, a) in enumerate(step)]
            if isinstance(step, list)
            else []
        )
        text = step if isinstance(step, str) else ""
        conv.messages.append({"role": "assistant", "content": text, "tool_calls": [asdict(c) for c in calls]})
        return Turn(text, calls, "tool_use" if calls else "end_turn", Usage(100, 10), "scripted", {}, {}, 0.0)

    def add_tool_results(self, conv: Conversation, turn: Turn, results: list[dict[str, Any]]) -> None:
        conv.messages.append({"role": "tool_results", "results": results})


def run_script(act, pair, world: str, script, *, condition: str = "act_check", pressure: str = "assertive") -> dict:
    """A trial record, as the runner writes it, for a scripted agent on one pair and world."""
    premise = "any" if condition == "act_blind" else world
    trial_id = f"sim:scripted|{pair['pair_id']}|{pair['lang']}|{premise}|{pressure}|{condition}|r0"
    plan = TrialPlan(trial_id, 0, pair["pair_id"], premise, pressure, condition, pair["lang"], 0)
    ctx = trial_context(plan, "sim:scripted")
    sandbox = act.open_trial(pair, ctx)
    try:
        conv = run_conversation(
            Scripted(script),
            trial_id=trial_id,
            system=system_prompt(act, pair["lang"], condition),
            user_text=act.trial_text(pair, ctx),
            tools=act.tools_for(condition),
            executor=sandbox.executor,
            max_tool_rounds=act.round_caps(condition),
            follow_up=sandbox.end_turn,
        )
    finally:
        record = sandbox.record()
        sandbox.close()
    return {
        "trial_id": trial_id,
        "model_label": "sim:scripted",
        "model_id": "scripted",
        "pair_id": pair["pair_id"],
        "template": pair["template"],
        "lang": pair["lang"],
        "premise": premise,
        "pressure": pressure,
        "condition": condition,
        "rep": 0,
        **conv,
        "cost_usd": 0.0,
        "sandbox": record,
    }


@pytest.fixture
def scripted(act):
    def run(pair, world, script, **kw):
        return run_script(act, pair, world, script, **kw)

    return run


def sql(pair, fact: str) -> tuple[str, dict]:
    """The pair's reference read for fact A or B, as a call."""
    call = next(c for c in pair["expected_calls"] if c["fact"] == fact)
    return ("run_sql", dict(call["args"]))


def request(pair) -> tuple[str, dict]:
    return (pair["request"]["tool"], dict(pair["request"]["args"]))
