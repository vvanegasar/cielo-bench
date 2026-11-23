"""Multi-turn trials (ADR-0009): a second user turn, sent when the sandbox asks for it, on both
adapters; synthetic results for calls left pending by a round cap; replay from the output cache."""

from __future__ import annotations

import json
from itertools import pairwise

import httpx
import pytest
from tabular_act.tiny import write_tiny

from cielo_bench.agent import CAP_RESULT, run_conversation
from cielo_bench.domains.tabular_act.sandbox import BaseFixture, TrialDB
from cielo_bench.domains.tabular_act.write_tools import READ_TOOL_SPECS, ActExecutor, FrozenClock
from cielo_bench.providers.anthropic import AnthropicProvider
from cielo_bench.providers.http import ResponseCache
from cielo_bench.providers.openai_compat import OpenAICompatProvider

KEY = "sk-test-NOT-A-REAL-KEY-123"
SQL = {"sql": "SELECT status FROM invoices WHERE invoice_number = 'INV-2026-00002'"}


class Script(httpx.BaseTransport):
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def handle_request(self, request):
        self.requests.append(json.loads(request.content))
        if not self.responses:
            raise AssertionError("unexpected request: the cache should have answered it")
        status, payload = self.responses.pop(0)
        return httpx.Response(status, json=payload)


def anthropic_tool_use(i: int) -> dict:
    return {
        "model": "m",
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 10, "output_tokens": 2},
        "content": [{"type": "tool_use", "id": f"toolu_{i}", "name": "run_sql", "input": SQL}],
    }


def anthropic_text(text: str) -> dict:
    return {"model": "m", "stop_reason": "end_turn", "usage": {"input_tokens": 10, "output_tokens": 2},
            "content": [{"type": "text", "text": text}]}  # fmt: skip


def openai_tool_use(i: int) -> dict:
    call = {"id": f"call_{i}", "type": "function", "function": {"name": "run_sql", "arguments": json.dumps(SQL)}}
    return {"model": "m", "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]},
                                       "finish_reason": "tool_calls"}], "usage": {}}  # fmt: skip


def openai_text(text: str) -> dict:
    return {"model": "m", "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {}}  # fmt: skip


@pytest.fixture
def executor(tmp_path):
    base = BaseFixture(write_tiny(tmp_path / "tiny.sqlite"))
    db = TrialDB(base, [])
    yield ActExecutor(db, frozenset({"run_sql", "describe_schema"}), FrozenClock("unit"))
    db.close()


class CountingExecutor:
    def __init__(self, inner):
        self.inner, self.calls, self.live_requests = inner, 0, 0
        self.positions: list[tuple[int, int]] = []

    def set_position(self, turn, round_index):
        self.positions.append((turn, round_index))
        self.inner.set_position(turn, round_index)

    def execute(self, name, arguments):
        self.calls += 1
        return self.inner.execute(name, arguments)


def anthropic(transport, cache=None):
    p = AnthropicProvider(api_key=KEY, model="m", transport=transport, sleep=lambda s: None, requests_per_minute=None)
    p.cache = cache
    return p


def openai(transport, cache=None):
    p = OpenAICompatProvider(
        api_key=KEY, model="m", transport=transport, sleep=lambda s: None, requests_per_minute=None
    )
    p.cache = cache
    return p


def test_turn_two_is_sent_only_when_the_sandbox_asks(executor):
    asked: list[int] = []

    def follow_up(turn: int) -> str | None:
        asked.append(turn)
        return "Go ahead." if turn == 1 else None

    transport = Script((200, anthropic_text("I won't.")), (200, anthropic_text("Still no.")))
    out = run_conversation(anthropic(transport), trial_id="t", system="s", user_text="Please do it.",
                           tools=READ_TOOL_SPECS, executor=executor, max_tool_rounds=(8, 4), follow_up=follow_up)  # fmt: skip
    assert asked == [1, 2] and [t["user_text"] for t in out["turns"]] == ["Please do it.", "Go ahead."]
    assert [r["turn"] for r in out["rounds"]] == [1, 2] and out["final_text"] == "Still no."
    assert transport.requests[1]["messages"][-1] == {"role": "user", "content": "Go ahead."}
    single = run_conversation(anthropic(Script((200, anthropic_text("ok")))), trial_id="u", system="s",
                              user_text="q", tools=READ_TOOL_SPECS, executor=executor, follow_up=lambda t: None)  # fmt: skip
    assert len(single["turns"]) == 1 and len(single["rounds"]) == 1


@pytest.mark.parametrize("adapter", ["anthropic", "openai"])
def test_a_cap_hit_in_turn_one_gets_synthetic_results_and_a_valid_turn_two(executor, adapter):
    tool_use, text, make = (
        (anthropic_tool_use, anthropic_text, anthropic)
        if adapter == "anthropic"
        else (openai_tool_use, openai_text, openai)
    )
    # turn 1: cap of 2 rounds, the model keeps calling; turn 2: one call, then an answer
    transport = Script(*((200, tool_use(i)) for i in range(3)), (200, tool_use(3)), (200, text("Done.")))
    counting = CountingExecutor(executor)
    out = run_conversation(make(transport), trial_id="t", system="s", user_text="Please.", tools=READ_TOOL_SPECS,
                           executor=counting, max_tool_rounds=(2, 4), follow_up=lambda t: "Go ahead." if t == 1 else None)  # fmt: skip
    assert out["error"] is None and out["final_text"] == "Done."
    capped = out["rounds"][2]
    assert capped["note"] == "max_tool_rounds_reached" and out["turns"][0]["cap_hit"] is True
    assert capped["tool_results"] == [
        {
            "id": capped["tool_calls"][0]["id"],
            "name": "run_sql",
            "arguments": SQL,
            "result": CAP_RESULT,
            "synthetic": True,
        }
    ]
    assert counting.calls == 3  # two rounds of turn 1 and one of turn 2: the capped round never ran
    assert counting.positions == [(1, 0), (1, 1), (2, 3)]
    turn_two = transport.requests[3]["messages"]
    if adapter == "anthropic":
        last = turn_two[-1]
        assert last["role"] == "user" and last["content"][0]["type"] == "tool_result"
        assert last["content"][0]["tool_use_id"] == "toolu_2" and last["content"][0]["is_error"] is True
        assert last["content"][-1] == {"type": "text", "text": "Go ahead."}  # follows the results, same message
        roles = [m["role"] for m in turn_two]
        assert all(a != b for a, b in pairwise(roles))  # user and assistant alternate
    else:
        assert turn_two[-2] == {"role": "tool", "tool_call_id": "call_2", "content": json.dumps(CAP_RESULT)}
        assert turn_two[-1] == {"role": "user", "content": "Go ahead."}


def test_the_output_cache_replays_a_two_turn_trial_and_resumes_it_mid_way(tmp_path, executor):
    responses = [(200, anthropic_tool_use(0)), (200, anthropic_text("No.")), (200, anthropic_tool_use(1)),
                 (200, anthropic_text("Still no."))]  # fmt: skip

    def trial(transport, clock_id="unit"):
        executor.clock = FrozenClock(clock_id)
        return run_conversation(anthropic(transport, ResponseCache(tmp_path / "cache")), trial_id="t", system="s",
                                user_text="Please.", tools=READ_TOOL_SPECS, executor=executor, max_tool_rounds=(8, 4),
                                follow_up=lambda t: "Go ahead." if t == 1 else None)  # fmt: skip

    # the first attempt dies in turn 2 (a non-retryable error), as an interrupted run would
    first = Script(*responses[:3], (400, {"error": "boom"}))
    assert "HTTP 400" in trial(first)["error"]
    # resuming re-runs the trial: the three finished rounds come from the cache, only the last is paid
    second = Script(responses[3])
    resumed = trial(second)
    assert resumed["error"] is None and len(second.requests) == 1 and resumed["final_text"] == "Still no."
    assert [r["request"]["from_cache"] for r in resumed["rounds"]] == [True, True, True, False]
    # a full replay costs nothing; it works because the frozen clock makes every request body identical
    assert trial(Script())["final_text"] == "Still no."
    with pytest.raises(AssertionError, match="unexpected request"):
        trial(Script(), clock_id="another clock")  # a different clock changes the tool results, so the bodies
