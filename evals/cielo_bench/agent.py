"""The agent loop for one trial: ask, run any tool calls, return the results, repeat.

Multi-turn designs add ``followups``: after the model's final answer, each branch copies the
conversation, appends one fixed user message and runs the same loop again. Every branch therefore
starts from the same first answer, so two branches (for example a directional insistence and a
neutral challenge) differ only in the message they receive.
"""

from __future__ import annotations

import copy
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from .domain import ToolExecutor
from .providers.base import Conversation, Provider, ProviderError, Usage

MAX_TOOL_ROUNDS = 4


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _converse(
    provider: Provider,
    conv: Conversation,
    *,
    tools: list[dict[str, Any]] | None,
    executor: ToolExecutor | None,
    max_tool_rounds: int,
    rounds: list[dict[str, Any]],
    total: Usage,
) -> tuple[str | None, str | None]:
    """Run the ask / tool / answer loop on ``conv``; append one entry per model call to ``rounds``.

    Returns ``(stop_reason, error)``.
    """
    stop_reason: str | None = None
    try:
        for index in range(max_tool_rounds + 1):
            turn = provider.complete(conv)
            total.add(turn.usage)
            stop_reason = turn.stop_reason
            entry: dict[str, Any] = {
                "index": index,
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
            rounds.append(entry)
            if not turn.tool_calls or not tools or executor is None:
                break
            if index == max_tool_rounds:
                entry["note"] = "max_tool_rounds_reached"
                break
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
    except ProviderError as exc:
        return stop_reason, f"{type(exc).__name__}: {exc}"
    return stop_reason, None


def run_conversation(
    provider: Provider,
    *,
    trial_id: str,
    system: str,
    user_text: str,
    tools: list[dict[str, Any]] | None,
    executor: ToolExecutor | None,
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
    followups: dict[str, str] | None = None,
) -> dict[str, Any]:
    started, t0 = _now(), time.monotonic()
    conv = provider.new_conversation(system, user_text, tools, trial_id)
    rounds: list[dict[str, Any]] = []
    total = Usage()
    stop_reason, error = _converse(
        provider,
        conv,
        tools=tools,
        executor=executor,
        max_tool_rounds=max_tool_rounds,
        rounds=rounds,
        total=total,
    )
    final_text = rounds[-1]["text"] if rounds else ""
    branches: dict[str, dict[str, Any]] = {}
    if followups and error is None and rounds:
        for branch, text in followups.items():
            fork = copy.deepcopy(conv)
            fork.trial_id = f"{trial_id}#{branch}"  # a distinct output-cache salt per branch
            provider.add_user_message(fork, text)
            branch_rounds: list[dict[str, Any]] = []
            branch_stop, branch_error = _converse(
                provider,
                fork,
                tools=tools,
                executor=executor,
                max_tool_rounds=max_tool_rounds,
                rounds=branch_rounds,
                total=total,
            )
            branches[branch] = {
                "user_text": text,
                "rounds": branch_rounds,
                "final_text": branch_rounds[-1]["text"] if branch_rounds else "",
                "stop_reason": branch_stop,
                "error": branch_error,
            }
    out: dict[str, Any] = {
        "rounds": rounds,
        "final_text": final_text,
        "stop_reason": stop_reason,
        "usage_total": asdict(total),
        "latency_s_total": round(time.monotonic() - t0, 3),
        "error": error,
        "started_at_utc": started,
        "finished_at_utc": _now(),
    }
    if followups:
        out["followups"] = branches
    return out
