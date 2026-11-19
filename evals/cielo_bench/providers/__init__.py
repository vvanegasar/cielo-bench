"""Provider factory.

Model specs: ``sim:<persona>``, ``anthropic[:<model>]``, ``openai[:<model>]``,
``openrouter[:<model>]``, ``ollama[:<model>]``, ``compat[:<model>]``.

Real providers read their settings, keys included, only from project settings (``CIELO_*``
names, see ``config.load_settings``), never from generic variables such as
``ANTHROPIC_API_KEY`` or ``OPENAI_API_KEY``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import Provider, ProviderError
from .simulated import PERSONAS, SimulatedProvider

__all__ = ["PERSONAS", "SETTINGS_PREFIX", "Provider", "ProviderError", "build_provider", "is_simulated_spec"]

# provider name -> settings prefix
SETTINGS_PREFIX = {
    "anthropic": "CIELO_ANTHROPIC",
    "openai": "CIELO_OPENAI",
    "openrouter": "CIELO_OPENROUTER",
    "ollama": "CIELO_OLLAMA",
    "openai_compat": "CIELO_OPENAI_COMPAT",
}
SPEC_KINDS = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openrouter": "openrouter",
    "ollama": "ollama",
    "compat": "openai_compat",
    "openai_compat": "openai_compat",
}
DEFAULT_RPM = {"anthropic": 50.0, "openai": 60.0, "openrouter": 20.0, "ollama": None, "openai_compat": 30.0}


def is_simulated_spec(spec: str) -> bool:
    return spec.strip().startswith("sim:")


def provider_kind(spec: str) -> str:
    kind = spec.strip().partition(":")[0]
    if kind == "sim":
        return "simulated"
    if kind not in SPEC_KINDS:
        raise ValueError(f"unknown model spec {spec!r}; use sim:, anthropic:, openai:, openrouter:, ollama: or compat:")
    return SPEC_KINDS[kind]


def _get(settings: Mapping[str, str], key: str) -> str:
    return (settings.get(key) or "").strip()


def _int(value: str) -> int | None:
    return int(value) if value else None


def _float(value: str) -> float | None:
    return float(value) if value else None


def _rpm(settings: Mapping[str, str], prefix: str, kind: str) -> float | None:
    raw = _get(settings, f"{prefix}_RPM")
    if raw:
        return float(raw) or None
    return DEFAULT_RPM[kind]


def build_provider(
    spec: str, *, settings: Mapping[str, str], domain: Any = None, golden: Any = None, seed: int = 0
) -> Provider:
    kind = provider_kind(spec)
    model = spec.strip().partition(":")[2]
    if kind == "simulated":
        if domain is None or golden is None:
            raise ValueError("the simulated provider needs the domain and the golden set")
        return SimulatedProvider(model or "careful", domain, golden, seed=seed)
    prefix = SETTINGS_PREFIX[kind]
    if kind == "anthropic":
        from .anthropic import DEFAULT_BASE_URL, AnthropicProvider

        return AnthropicProvider(
            api_key=_get(settings, f"{prefix}_API_KEY"),
            model=model or _get(settings, f"{prefix}_MODEL") or "claude-opus-5-5",
            base_url=_get(settings, f"{prefix}_BASE_URL") or DEFAULT_BASE_URL,
            max_tokens=_int(_get(settings, f"{prefix}_MAX_TOKENS")) or 16000,
            effort=_get(settings, f"{prefix}_EFFORT") or None,
            requests_per_minute=_rpm(settings, prefix, kind),
            settings=settings,
        )
    from .openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(
        api_key=_get(settings, f"{prefix}_API_KEY"),
        model=model or _get(settings, f"{prefix}_MODEL"),
        flavour=kind,
        base_url=_get(settings, f"{prefix}_BASE_URL") or None,
        max_tokens=_int(_get(settings, f"{prefix}_MAX_TOKENS")),
        max_tokens_param=_get(settings, f"{prefix}_MAX_TOKENS_PARAM") or None,
        temperature=_float(_get(settings, f"{prefix}_TEMPERATURE")),
        reasoning_effort=_get(settings, f"{prefix}_REASONING_EFFORT") or None,
        requests_per_minute=_rpm(settings, prefix, kind),
        key_name=f"{prefix}_API_KEY",
        settings=settings,
    )
