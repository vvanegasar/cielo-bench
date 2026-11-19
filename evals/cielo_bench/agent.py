"""The agent loop for one trial: ask, run any tool calls, return the results, repeat."""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from .domain import ToolExecutor
from .providers.base import Provider, ProviderError, Usage

MAX_TOOL_ROUNDS = 4


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
    max_tool_rounds: int = MAX_TOOL_ROUNDS,
) -> dict[str, Any]:
    started, t0 = _now(), time.monotonic()
    conv = provider.new_conversation(system, user_text, tools, trial_id)
    rounds: list[dict[str, Any]] = []
    total = Usage()
    error: str | None = None
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
        error = f"{type(exc).__name__}: {exc}"
    final_text = rounds[-1]["text"] if rounds else ""
    return {
        "rounds": rounds,
        "final_text": final_text,
        "stop_reason": stop_reason,
        "usage_total": asdict(total),
        "latency_s_total": round(time.monotonic() - t0, 3),
        "error": error,
        "started_at_utc": started,
        "finished_at_utc": _now(),
    }
