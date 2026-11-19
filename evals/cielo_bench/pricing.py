"""Prices (USD per million tokens) and per-trial cost.

Anthropic list prices are the first-party API rates as cached in the Claude API reference on
2026-11-03 (re-check https://platform.claude.com/docs/en/about-claude/pricing before a run).
Prices for OpenAI, OpenRouter and other compatible endpoints come from the local settings
(``<PREFIX>_PRICE_IN_PER_MTOK`` / ``<PREFIX>_PRICE_OUT_PER_MTOK``), because they depend on the
model chosen. A local Ollama model costs nothing; a simulated model costs nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PRICES_AS_OF = "2026-11-03"
ANTHROPIC_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),  # prompts up to 100K tokens
    "claude-fable-5-2": (8.00, 40.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
}
_PREFIX = {
    "anthropic": "CIELO_ANTHROPIC",
    "openai": "CIELO_OPENAI",
    "openrouter": "CIELO_OPENROUTER",
    "openai_compat": "CIELO_OPENAI_COMPAT",
}


def _pair(settings: Mapping[str, str], prefix: str) -> tuple[float, float] | None:
    raw_in = (settings.get(f"{prefix}_PRICE_IN_PER_MTOK") or "").strip()
    raw_out = (settings.get(f"{prefix}_PRICE_OUT_PER_MTOK") or "").strip()
    if raw_in and raw_out:
        return float(raw_in), float(raw_out)
    return None


def price_for(description: Mapping[str, Any], settings: Mapping[str, str]) -> tuple[float, float] | None:
    provider, model = description["provider"], description["model"]
    if provider in ("simulated", "ollama"):
        return (0.0, 0.0)
    if provider == "anthropic":
        return _pair(settings, _PREFIX["anthropic"]) or ANTHROPIC_PRICES.get(model)
    if provider in _PREFIX:
        return _pair(settings, _PREFIX[provider])
    return None


def cost_usd(provider: str, usage: Mapping[str, int], price: tuple[float, float] | None) -> float | None:
    if price is None:
        return None
    p_in, p_out = price
    tokens_in = float(usage.get("input_tokens", 0))
    if provider == "anthropic":  # input_tokens excludes cache reads and writes there
        tokens_in += 1.25 * usage.get("cache_creation_input_tokens", 0) + 0.1 * usage.get("cache_read_input_tokens", 0)
    return (tokens_in * p_in + usage.get("output_tokens", 0) * p_out) / 1_000_000
