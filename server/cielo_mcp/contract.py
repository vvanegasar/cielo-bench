"""The tool-result contract shared by every cielo-bench domain, and its MCP form.

A domain executor returns a JSON object whose ``status`` is ``ok``, ``invalid_input``,
``source_unavailable`` or ``out_of_scope`` (``cielo_bench.domain``). Over MCP that object is
sent unchanged:

* ``structuredContent`` is the object itself;
* the text block is ``json.dumps(result, ensure_ascii=False)``, the same text the benchmark
  hands to models (``cielo_bench.providers``);
* ``isError`` is true for every status except ``ok``.

Before a result leaves the server, the two rules that matter most are checked, and the server
fails closed if a domain breaks either one: an ``ok`` result cites its sources (service, query
and retrieval time), and any other result carries no values.
"""

from __future__ import annotations

import json
from typing import Any

from mcp_types import CallToolResult, TextContent

from cielo_bench.domain import TOOL_STATUSES

# What a non-ok result may contain (docs/TOOLS.md): no values, ever.
FAILURE_KEYS = frozenset({"status", "source", "reason", "message"})
# What every citation in an ok result must name.
CITATION_KEYS = ("service", "query", "retrieved_at_utc")

# Advertised as each tool's outputSchema. It describes the contract, not a domain's fields,
# so it holds for every domain; clients validate ok results against it.
RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "cielo-bench tool result. status 'ok' carries the values and sources[]; any other "
        "status carries no values, only a message (plus source and reason when a source failed)."
    ),
    "properties": {
        "status": {"type": "string", "enum": list(TOOL_STATUSES)},
        "sources": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "query": {"description": "The query sent to the source, as the source received it."},
                    "retrieved_at_utc": {"type": "string"},
                },
                "required": list(CITATION_KEYS),
            },
        },
    },
    "required": ["status"],
    "if": {"properties": {"status": {"const": "ok"}}},
    "then": {"required": ["sources"]},
}


class ContractViolation(RuntimeError):
    """A domain returned a result that breaks the shared contract. It is never sent."""


def check_result(result: Any) -> dict[str, Any]:
    """Return the result if it honours the contract; raise ``ContractViolation`` otherwise."""
    if not isinstance(result, dict):
        raise ContractViolation(f"a tool result must be a JSON object, got {type(result).__name__}")
    status = result.get("status")
    if status not in TOOL_STATUSES:
        raise ContractViolation(f"unknown status {status!r}")
    if status == "ok":
        sources = result.get("sources")
        cited = isinstance(sources, list) and bool(sources) and all(
            isinstance(source, dict) and all(source.get(key) for key in CITATION_KEYS)
            for source in sources
        )
        if not cited:
            raise ContractViolation("an ok result must cite its sources: service, query, retrieved_at_utc")
    elif extra := sorted(set(result) - FAILURE_KEYS):
        raise ContractViolation(f"a {status} result must carry no values, found {extra}")
    return result


def to_call_tool_result(result: Any) -> CallToolResult:
    """The MCP form of a domain result: unchanged, with ``isError`` for every non-ok status."""
    checked = check_result(result)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(checked, ensure_ascii=False))],
        structured_content=checked,
        is_error=checked["status"] != "ok",
    )
