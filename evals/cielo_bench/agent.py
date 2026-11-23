"""The agent loop for one trial: ask, run any tool calls, return the results, repeat.

A trial has one user turn unless a ``follow_up`` callback is given. Then, when a turn ends, the
callback is asked for the next user turn (``None`` ends the trial), and each turn has its own
cap on tool rounds (``max_tool_rounds`` as a tuple, one cap per turn; the last cap repeats).

When a turn stops at its round cap, the tool calls of its last round are never run. Both APIs
reject a user turn that follows unanswered tool calls, so before a further user turn the loop
answers each pending call with a synthetic ``invalid_input`` result (``CAP_RESULT``), through the
provider's own ``add_tool_results``. Those results are recorded with ``"synthetic": true`` and
are not tool calls of the trial.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from .domain import ToolExecutor
from .providers.base import Provider, ProviderError, Usage

MAX_TOOL_ROUNDS = 4
CAP_RESULT = {"status": "invalid_input", "message": "round limit reached; this call was not run"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_conversation(
    provider: Provider,
    *,
    trial_id: str,
    system: str,
    user_text: str,
    tools: list[dict[str, Any]] | None,
    executor: ToolExecutor | None,
    max_tool_rounds: int | Sequence[int] = MAX_TOOL_ROUNDS,
    follow_up: Callable[[int], str | None] | None = None,
) -> dict[str, Any]:
    caps = (max_tool_rounds,) if isinstance(max_tool_rounds, int) else tuple(max_tool_rounds)
    multi_turn = follow_up is not None
    started, t0 = _now(), time.monotonic()
    conv = provider.new_conversation(system, user_text, tools, trial_id)
    rounds: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = [{"turn": 1, "user_text": user_text, "first_round": 0, "cap_hit": False}]
    total = Usage()
    error: str | None = None
    stop_reason: str | None = None
    set_position = getattr(executor, "set_position", None)
    try:
        turn_no = 1
        while True:
            cap = caps[min(turn_no, len(caps)) - 1]
            pending = None
            for round_in_turn in range(cap + 1):
                turn = provider.complete(conv)
                total.add(turn.usage)
                stop_reason = turn.stop_reason
                entry: dict[str, Any] = {
                    "index": len(rounds),
                    "request": turn.request_meta,
                    "response": turn.raw_response,
                    "latency_s": round(turn.latency_s, 3),
                    "usage": asdict(turn.usage),
                    "stop_reason": turn.stop_reason,
                    "model_reported": turn.model_reported,
                    "text": turn.text,
                    "tool_calls": [asdict(c) for c in turn.tool_calls],
                    "tool_results": [],
                }
                if multi_turn:
                    entry["turn"] = turn_no
                    entry["round_in_turn"] = round_in_turn
                rounds.append(entry)
                if not turn.tool_calls or not tools or executor is None:
                    break
                if round_in_turn == cap:
                    entry["note"] = "max_tool_rounds_reached"
                    pending = turn
                    turns[-1]["cap_hit"] = True
                    break
                if set_position is not None:
                    set_position(turn_no, entry["index"])
                results = []
                for call in turn.tool_calls:
                    if call.parse_error:
                        result = {
                            "status": "invalid_input",
                            "message": f"arguments could not be parsed: {call.parse_error}",
                        }
                    else:
                        result = executor.execute(call.name, call.arguments)
                    results.append(result)
                    entry["tool_results"].append(
                        {"id": call.id, "name": call.name, "arguments": call.arguments, "result": result}
                    )
                provider.add_tool_results(conv, turn, results)
            if follow_up is None:
                break
            next_text = follow_up(turn_no)
            if next_text is None:
                break
            if pending is not None:  # close the unanswered calls of the capped round, without running them
                synthetic = [dict(CAP_RESULT) for _ in pending.tool_calls]
                provider.add_tool_results(conv, pending, synthetic)
                rounds[-1]["tool_results"] = [
                    {"id": c.id, "name": c.name, "arguments": c.arguments, "result": r, "synthetic": True}
                    for c, r in zip(pending.tool_calls, synthetic, strict=True)
                ]
            provider.add_user_turn(conv, next_text)
            turn_no += 1
            turns.append({"turn": turn_no, "user_text": next_text, "first_round": len(rounds), "cap_hit": False})
    except ProviderError as exc:
        error = f"{type(exc).__name__}: {exc}"
    final_text = rounds[-1]["text"] if rounds else ""
    out = {
        "rounds": rounds,
        "final_text": final_text,
        "stop_reason": stop_reason,
        "usage_total": asdict(total),
        "latency_s_total": round(time.monotonic() - t0, 3),
        "error": error,
        "started_at_utc": started,
        "finished_at_utc": _now(),
    }
    if multi_turn:
        out["turns"] = turns
    return out
