"""Provider adapters against mock transports. No real API is ever called in tests."""

import json

import httpx
import pytest

from cielo_bench.agent import run_conversation
from cielo_bench.config import load_settings
from cielo_bench.pricing import ANTHROPIC_PRICES, cost_usd, price_for
from cielo_bench.providers import build_provider, provider_kind
from cielo_bench.providers.anthropic import API_VERSION, AnthropicProvider
from cielo_bench.providers.base import ProviderError
from cielo_bench.providers.http import RateLimiter, ResponseCache, post_json
from cielo_bench.providers.openai_compat import OpenAICompatProvider

FAKE_KEY = "sk-test-NOT-A-REAL-KEY-123"
TOOLS = [{"name": "body_position", "description": "d", "parameters": {"type": "object", "properties": {}}}]


class Script(httpx.BaseTransport):
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        status, payload = self.responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload, headers={"retry-after": "0"} if status == 429 else None)


class DownExecutor:
    live_requests = 0

    def execute(self, name, arguments):
        return {"status": "source_unavailable", "source": "x", "reason": "http_503", "message": "down"}


ANTHROPIC_TOOL_USE = {
    "model": "claude-x",
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 10, "output_tokens": 5},
    "content": [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "tool_use", "id": "toolu_1", "name": "body_position", "input": {"body": "Saturn"}},
    ],
}
ANTHROPIC_FINAL = {
    "model": "claude-x",
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 20, "output_tokens": 7},
    "content": [{"type": "text", "text": "Source down.\nVERDICT: UNKNOWN"}],
}


def test_anthropic_request_shape_and_tool_round():
    transport = Script((200, ANTHROPIC_TOOL_USE), (200, ANTHROPIC_FINAL))
    provider = AnthropicProvider(
        api_key=FAKE_KEY,
        model="claude-x",
        transport=transport,
        sleep=lambda s: None,
        requests_per_minute=None,
        effort="low",
    )
    out = run_conversation(provider, trial_id="t", system="sys", user_text="q?", tools=TOOLS, executor=DownExecutor())
    req = transport.requests[0]
    body = json.loads(req.content)
    assert req.headers["anthropic-version"] == API_VERSION and req.headers["x-api-key"] == FAKE_KEY
    assert "temperature" not in body and "top_p" not in body and "fallbacks" not in body
    assert body["tools"][0]["input_schema"] == TOOLS[0]["parameters"] and body["output_config"] == {"effort": "low"}
    follow = json.loads(transport.requests[1].content)["messages"]
    assert follow[1]["content"][0]["type"] == "thinking"  # assistant content passed back unchanged
    result_block = follow[2]["content"][0]
    assert result_block["type"] == "tool_result" and result_block["tool_use_id"] == "toolu_1"
    assert result_block["is_error"] is True
    assert out["final_text"].endswith("VERDICT: UNKNOWN")
    assert out["usage_total"]["input_tokens"] == 30
    assert out["rounds"][0]["model_reported"] == "claude-x"
    assert FAKE_KEY not in json.dumps(out)  # the key never reaches the raw record
    assert provider.describe()["fallbacks"] == "disabled"


def test_output_cache_replays_a_trial_without_new_requests(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    first = Script((200, ANTHROPIC_TOOL_USE), (200, ANTHROPIC_FINAL))
    p1 = AnthropicProvider(
        api_key=FAKE_KEY, model="claude-x", transport=first, sleep=lambda s: None, requests_per_minute=None
    )
    p1.cache = cache
    a = run_conversation(p1, trial_id="t1", system="sys", user_text="q?", tools=TOOLS, executor=DownExecutor())
    empty = Script()
    p2 = AnthropicProvider(
        api_key=FAKE_KEY, model="claude-x", transport=empty, sleep=lambda s: None, requests_per_minute=None
    )
    p2.cache = cache
    b = run_conversation(p2, trial_id="t1", system="sys", user_text="q?", tools=TOOLS, executor=DownExecutor())
    assert empty.requests == [] and a["final_text"] == b["final_text"]
    assert b["rounds"][0]["request"]["from_cache"] is True
    other = Script((200, ANTHROPIC_FINAL))
    p3 = AnthropicProvider(
        api_key=FAKE_KEY, model="claude-x", transport=other, sleep=lambda s: None, requests_per_minute=None
    )
    p3.cache = cache
    run_conversation(p3, trial_id="t2", system="sys", user_text="q?", tools=TOOLS, executor=DownExecutor())
    assert len(other.requests) == 1  # another trial id is not served from the cache
    cache._path("bad").parent.mkdir(parents=True, exist_ok=True)
    cache._path("bad").write_text("{broken")
    assert cache.get("bad") is None


def test_openai_tool_calls_bad_json_and_options():
    first = {
        "model": "gpt-x-2026-01-01",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "body_position", "arguments": '{"body": "Saturn"}'},
                        },
                        {"id": "c2", "type": "function", "function": {"name": "body_position", "arguments": "{oops"}},
                        {"id": "c3", "type": "function", "function": {"name": "body_position", "arguments": "[1]"}},
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3, "completion_tokens_details": {"reasoning_tokens": 2}},
    }
    second = {
        "model": "gpt-x-2026-01-01",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "VERDICT: FALSE"}]},
            }
        ],
        "usage": {"prompt_tokens": 30, "completion_tokens": 4},
    }
    transport = Script((200, first), (200, second))
    provider = OpenAICompatProvider(
        api_key=FAKE_KEY,
        model="gpt-x-2026-01-01",
        transport=transport,
        sleep=lambda s: None,
        max_tokens=500,
        temperature=0.0,
        reasoning_effort="low",
        requests_per_minute=None,
    )
    out = run_conversation(provider, trial_id="t", system="sys", user_text="q?", tools=TOOLS, executor=DownExecutor())
    body = json.loads(transport.requests[0].content)
    assert transport.requests[0].headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert body["tools"][0]["type"] == "function" and body["tool_choice"] == "auto"
    assert body["max_completion_tokens"] == 500 and body["temperature"] == 0.0 and body["reasoning_effort"] == "low"
    calls = out["rounds"][0]["tool_calls"]
    assert calls[0]["arguments"] == {"body": "Saturn"} and calls[1]["parse_error"] and calls[2]["parse_error"]
    assert out["rounds"][0]["tool_results"][1]["result"]["status"] == "invalid_input"
    follow = json.loads(transport.requests[1].content)["messages"]
    assert [m["role"] for m in follow] == ["system", "user", "assistant", "tool", "tool", "tool"]
    assert out["final_text"] == "VERDICT: FALSE" and out["usage_total"]["reasoning_tokens"] == 2
    assert FAKE_KEY not in json.dumps(out)


def test_ollama_needs_no_key_and_openrouter_uses_its_own_settings():
    settings = {
        "CIELO_OLLAMA_MODEL": "qwen3:8b",
        "CIELO_OPENROUTER_API_KEY": "k",
        "CIELO_OPENROUTER_MODEL": "vendor/model",
    }
    ollama = build_provider("ollama", settings=settings)
    assert ollama.label == "ollama:qwen3:8b" and ollama.base_url.startswith("http://localhost:11434")
    transport = Script((200, {"model": "qwen3:8b", "choices": [{"message": {"content": "VERDICT: TRUE"}}]}))
    ollama._http = httpx.Client(transport=transport)
    run_conversation(ollama, trial_id="t", system="s", user_text="q", tools=None, executor=None)
    assert "authorization" not in transport.requests[0].headers
    router = build_provider("openrouter", settings=settings)
    assert router.label == "openrouter:vendor/model" and router.max_tokens_param == "max_tokens"
    assert router.base_url == "https://openrouter.ai/api/v1"
    with pytest.raises(ValueError):
        build_provider("compat:some-model", settings={"CIELO_OPENAI_COMPAT_API_KEY": "k"})  # no base URL
    with pytest.raises(ValueError):
        provider_kind("gemini:x")


def test_retries_transient_then_succeeds_and_fails_fast_on_400():
    transport = Script(
        (529, {"error": "overloaded"}),
        (429, {"error": "slow down"}),
        (500, {"e": 1}),
        (520, {"e": "edge: unknown error from the origin"}),
        (200, {"ok": True}),
    )
    data, _ = post_json(httpx.Client(transport=transport), "https://x.test", {}, {}, sleep=lambda s: None)
    assert data == {"ok": True} and len(transport.requests) == 5
    with pytest.raises(ProviderError) as err:
        post_json(
            httpx.Client(transport=Script((400, {"error": "bad"}))), "https://x.test", {}, {}, sleep=lambda s: None
        )
    assert err.value.status == 400
    boom = Script(*[(0, httpx.ConnectError("down")) for _ in range(2)])
    with pytest.raises(ProviderError) as err:
        post_json(httpx.Client(transport=boom), "https://x.test", {}, {}, max_attempts=2, sleep=lambda s: None)
    assert err.value.retryable


def test_rate_limiter_spaces_requests():
    clock = {"t": 0.0}
    waits = []
    limiter = RateLimiter(60, clock=lambda: clock["t"], sleep=waits.append)
    for _ in range(3):
        limiter.acquire()
    assert waits == [1.0, 2.0]  # 60 rpm: one per second
    assert RateLimiter(None).acquire() == 0.0


def test_generic_provider_keys_are_never_used(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-another-account")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-another-account")
    settings = load_settings(env_file=tmp_path / "missing.env")
    assert "ANTHROPIC_API_KEY" not in settings and "OPENAI_API_KEY" not in settings
    with pytest.raises(ValueError, match="CIELO_ANTHROPIC_API_KEY"):
        build_provider("anthropic", settings=settings)
    with pytest.raises(ValueError, match="CIELO_OPENAI_API_KEY"):
        build_provider("openai:some-model", settings=settings)


def test_prices_and_costs():
    assert price_for({"provider": "anthropic", "model": "claude-opus-5-5"}, {}) == ANTHROPIC_PRICES["claude-opus-5-5"]
    assert price_for({"provider": "ollama", "model": "x"}, {}) == (0.0, 0.0)
    assert price_for({"provider": "openai", "model": "x"}, {}) is None
    assert price_for(
        {"provider": "openai", "model": "x"},
        {"CIELO_OPENAI_PRICE_IN_PER_MTOK": "2", "CIELO_OPENAI_PRICE_OUT_PER_MTOK": "10"},
    ) == (2.0, 10.0)
    assert price_for({"provider": "mystery", "model": "x"}, {}) is None
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000}
    assert cost_usd("anthropic", usage, (4.0, 20.0)) == pytest.approx(4.0 + 0.4 + 2.0)
    assert cost_usd("openai", usage, (2.0, 10.0)) == pytest.approx(2.0 + 1.0)
    assert cost_usd("openai", usage, None) is None
