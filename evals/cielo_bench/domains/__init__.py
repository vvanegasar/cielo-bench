"""Domain registry: name -> "module:Class". Adding a domain is one line in REGISTRY."""

from __future__ import annotations

from importlib import import_module

from ..domain import Domain

REGISTRY: dict[str, str] = {
    "astronomy": "cielo_bench.domains.astronomy:AstronomyDomain",
    "tabular": "cielo_bench.domains.tabular:TabularDomain",
    "tabular_act": "cielo_bench.domains.tabular_act:TabularActDomain",
}
AVAILABLE = tuple(REGISTRY)


def get_domain(name: str = "astronomy") -> Domain:
    try:
        target = REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"unknown domain {name!r}; available: {AVAILABLE}") from exc
    module_name, _, class_name = target.partition(":")
    return getattr(import_module(module_name), class_name)()
