"""Domain registry: name -> "module:Class". Adding a domain is one line in REGISTRY.

``REGISTRY`` holds the domains with their own tools and data source; the MCP server serves exactly
these. ``VARIANTS`` holds item banks that reuse the tools of a registered domain (for example
``astronomy_near``, the same tools with premises close to the truth): the CLI, the docs and the CI see
them, the server does not, so its tool names do not change.
"""

from __future__ import annotations

from importlib import import_module

from ..domain import Domain

REGISTRY: dict[str, str] = {
    "astronomy": "cielo_bench.domains.astronomy:AstronomyDomain",
    "tabular": "cielo_bench.domains.tabular:TabularDomain",
}
VARIANTS: dict[str, str] = {
    "astronomy_near": "cielo_bench.domains.astronomy:AstronomyNearDomain",
}
AVAILABLE = (*REGISTRY, *VARIANTS)


def get_domain(name: str = "astronomy") -> Domain:
    try:
        target = REGISTRY.get(name) or VARIANTS[name]
    except KeyError as exc:
        raise KeyError(f"unknown domain {name!r}; available: {AVAILABLE}") from exc
    module_name, _, class_name = target.partition(":")
    return getattr(import_module(module_name), class_name)()
