"""Anthropic Messages API over plain HTTP, with client-side tool calling.

Notes for current models (checked 2026-11-18): send ``anthropic-version: 2026-10-21``; do
not send ``temperature``/``top_p``/``top_k`` (rejected); forced ``tool_choice`` is not used
(``auto`` is the default when tools are present). The assistant ``content`` is appended back
unchanged, so thinking blocks are preserved across tool rounds. Server-side refusal
fallbacks are deliberately NOT enabled: a fallback would let another model answer some
trials, and each trial must be attributable to one pinned model. A refusal is recorded as
``stop_reason == "refusal"``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from ..net import ssl_context
from .base import Conversation, Provider, ToolCall, Turn, Usage
from .http import HTTPProviderMixin, RateLimiter

API_VERSION = "2026-10-21"
DEFAULT_BASE_URL = "https://api.anthropic.com"


class AnthropicProvider(HTTPProviderMixin, Provider):
    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        max_tokens: int = 16000,
        effort: str | None = None,
        timeout_s: float = 600.0,
        requests_per_minute: float | None = 50,
        transport: httpx.BaseTransport | None = None,
        settings: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__(model, label=f"anthropic:{model}")
        if not api_key:
            raise ValueError("missing CIELO_ANTHROPIC_API_KEY (a personal key, in .env)")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.effort = effort or None
        self._sleep = sleep
        self.limiter = RateLimiter(requests_per_minute, sleep=sleep)
        self._http = httpx.Client(transport=transport, timeout=timeout_s, verify=ssl_context(settings))

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "api": "messages",
            "anthropic_version": API_VERSION,
            "base_url": self.base_url,
            "max_tokens": self.max_tokens,
            "effort": self.effort,
            "sampling": "provider default (temperature not sent)",
            "fallbacks": "disabled",
            "requests_per_minute": 60.0 / self.limiter.interval if self.limiter.interval else None,
        }

    @staticmethod
    def tool_definitions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]

    def build_body(self, conv: Conversation) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": conv.system,
            "messages": conv.messages,
        }
        if conv.tools:
            body["tools"] = self.tool_definitions(conv.tools)
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        return body

    def complete(self, conv: Conversation) -> Turn:
        body = json.loads(json.dumps(self.build_body(conv)))  # snapshot: later rounds mutate messages
        headers = {"x-api-key": self._api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        data, latency, cached = self._send(f"{self.base_url}/v1/messages", headers, body, salt=self.salt(conv))
        return self.parse_response(conv, data, latency, cached=cached)

    def parse_response(self, conv: Conversation, data: dict[str, Any], latency: float, *, cached: bool = False) -> Turn:
        content = data.get("content") or []
        text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
        calls = [
            ToolCall(
                id=b.get("id", ""),
                name=b.get("name", ""),
                arguments=b.get("input") if isinstance(b.get("input"), dict) else None,
                parse_error=None if isinstance(b.get("input"), dict) else "input is not an object",
            )
            for b in content
            if b.get("type") == "tool_use"
        ]
        conv.messages.append({"role": "assistant", "content": content})
        u = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(u.get("input_tokens") or 0),
            output_tokens=int(u.get("output_tokens") or 0),
            cache_read_input_tokens=int(u.get("cache_read_input_tokens") or 0),
            cache_creation_input_tokens=int(u.get("cache_creation_input_tokens") or 0),
        )
        meta = {
            "endpoint": "/v1/messages",
            "anthropic_version": API_VERSION,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "effort": self.effort,
            "from_cache": cached,
            "tools": [t["name"] for t in conv.tools or []],
            "n_messages": len(conv.messages) - 1,
        }
        return Turn(
            text=text,
            tool_calls=calls,
            stop_reason=data.get("stop_reason"),
            usage=usage,
            model_reported=data.get("model"),
            raw_response=data,
            request_meta=meta,
            latency_s=latency,
        )

    def add_tool_results(self, conv: Conversation, turn: Turn, results: list[dict[str, Any]]) -> None:
        blocks = []
        for call, result in zip(turn.tool_calls, results, strict=True):
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
            if result.get("status") != "ok":
                block["is_error"] = True
            blocks.append(block)
        conv.messages.append({"role": "user", "content": blocks})  # all results in one message

    def add_user_turn(self, conv: Conversation, text: str) -> None:
        """A further user turn. After tool results it joins their message as a text block that follows
        them, so user and assistant messages still alternate."""
        last = conv.messages[-1] if conv.messages else None
        if last and last.get("role") == "user" and isinstance(last.get("content"), list):
            last["content"].append({"type": "text", "text": text})
        else:
            conv.messages.append({"role": "user", "content": text})

    def set_effort(self, effort: str) -> bool:
        self.effort = effort
        return True
