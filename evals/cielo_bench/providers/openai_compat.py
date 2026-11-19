"""OpenAI Chat Completions and compatible APIs (OpenRouter, Ollama, others) over plain HTTP.

One adapter, several flavours that differ only in base URL, key and defaults:

* ``openai``      - https://api.openai.com/v1, ``max_completion_tokens``;
* ``openrouter``  - https://openrouter.ai/api/v1, ``max_tokens``;
* ``ollama``      - http://localhost:11434/v1 (local, no key, no cost);
* ``openai_compat`` - any other compatible endpoint (configure everything).

Optional fields (max tokens, temperature, reasoning effort) are only sent when configured.
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

FLAVOURS: dict[str, dict[str, Any]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "max_tokens_param": "max_completion_tokens",
        "needs_key": True,
        "label": "openai",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "max_tokens_param": "max_tokens",
        "needs_key": True,
        "label": "openrouter",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "max_tokens_param": "max_tokens",
        "needs_key": False,
        "label": "ollama",
    },
    "openai_compat": {"base_url": "", "max_tokens_param": "max_tokens", "needs_key": True, "label": "compat"},
}
DEFAULT_BASE_URL = FLAVOURS["openai"]["base_url"]


class OpenAICompatProvider(HTTPProviderMixin, Provider):
    provider = "openai_compat"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        flavour: str = "openai",
        base_url: str | None = None,
        max_tokens: int | None = None,
        max_tokens_param: str | None = None,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        timeout_s: float = 600.0,
        requests_per_minute: float | None = 60,
        key_name: str = "CIELO_OPENAI_API_KEY",
        transport: httpx.BaseTransport | None = None,
        settings: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if flavour not in FLAVOURS:
            raise ValueError(f"unknown flavour {flavour!r}; choose from {sorted(FLAVOURS)}")
        spec = FLAVOURS[flavour]
        super().__init__(model, label=f"{spec['label']}:{model}")
        self.provider = flavour
        if spec["needs_key"] and not api_key:
            raise ValueError(f"missing {key_name} (a personal key, in .env)")
        if not model:
            raise ValueError("missing model id for the OpenAI-compatible provider")
        self._api_key = api_key
        self.base_url = (base_url or spec["base_url"]).rstrip("/")
        if not self.base_url:
            raise ValueError("missing base URL for the OpenAI-compatible provider")
        self.max_tokens = max_tokens
        self.max_tokens_param = max_tokens_param or spec["max_tokens_param"]
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort or None
        self._sleep = sleep
        self.limiter = RateLimiter(requests_per_minute, sleep=sleep)
        verify = ssl_context(settings) if self.base_url.startswith("https://") else True
        self._http = httpx.Client(transport=transport, timeout=timeout_s, verify=verify)

    def describe(self) -> dict[str, Any]:
        return {
            **super().describe(),
            "api": "chat.completions",
            "base_url": self.base_url,
            "max_tokens": self.max_tokens,
            "max_tokens_param": self.max_tokens_param,
            "temperature": self.temperature,
            "reasoning_effort": self.reasoning_effort,
            "requests_per_minute": 60.0 / self.limiter.interval if self.limiter.interval else None,
        }

    def new_conversation(
        self, system: str, user_text: str, tools: list[dict[str, Any]] | None, trial_id: str
    ) -> Conversation:
        conv = Conversation(system=system, user_text=user_text, tools=tools, trial_id=trial_id)
        conv.messages += [{"role": "system", "content": system}, {"role": "user", "content": user_text}]
        return conv

    def build_body(self, conv: Conversation) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "messages": conv.messages}
        if conv.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]},
                }
                for t in conv.tools
            ]
            body["tool_choice"] = "auto"
        if self.max_tokens:
            body[self.max_tokens_param] = self.max_tokens
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        return body

    def complete(self, conv: Conversation) -> Turn:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = json.loads(json.dumps(self.build_body(conv)))
        data, latency, cached = self._send(f"{self.base_url}/chat/completions", headers, body, salt=self.salt(conv))
        return self.parse_response(conv, data, latency, cached=cached)

    def parse_response(self, conv: Conversation, data: dict[str, Any], latency: float, *, cached: bool = False) -> Turn:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):  # some providers return content parts
            text = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        else:
            text = content or ""
        calls: list[ToolCall] = []
        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = tc.get("function") or {}
            raw = fn.get("arguments")
            args, error = None, None
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, dict):
                    args = parsed
                else:
                    error = "arguments are not a JSON object"
            except json.JSONDecodeError as exc:
                error = f"invalid JSON: {exc}"
            calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{i}",
                    name=fn.get("name", ""),
                    arguments=args,
                    raw_arguments=raw if isinstance(raw, str) else None,
                    parse_error=error,
                )
            )
        assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
        if message.get("tool_calls"):
            assistant["tool_calls"] = message["tool_calls"]
        conv.messages.append(assistant)
        u = data.get("usage") or {}
        details = u.get("completion_tokens_details") or {}
        prompt_details = u.get("prompt_tokens_details") or {}
        usage = Usage(
            input_tokens=int(u.get("prompt_tokens") or 0),
            output_tokens=int(u.get("completion_tokens") or 0),
            cache_read_input_tokens=int(prompt_details.get("cached_tokens") or 0),
            reasoning_tokens=int(details.get("reasoning_tokens") or 0),
        )
        meta = {
            "endpoint": "/chat/completions",
            "model": self.model,
            "from_cache": cached,
            "tools": [t["name"] for t in conv.tools or []],
            "n_messages": len(conv.messages) - 1,
        }
        return Turn(
            text=text,
            tool_calls=calls,
            stop_reason=choice.get("finish_reason"),
            usage=usage,
            model_reported=data.get("model"),
            raw_response=data,
            request_meta=meta,
            latency_s=latency,
        )

    def add_tool_results(self, conv: Conversation, turn: Turn, results: list[dict[str, Any]]) -> None:
        for call, result in zip(turn.tool_calls, results, strict=True):
            conv.messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)}
            )
