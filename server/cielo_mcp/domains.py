"""Find the benchmark's domains and give each of their tools an MCP name.

The server has no domain knowledge of its own. Every domain registered in
``cielo_bench.domains.REGISTRY`` is loaded with the core's own loader, and a domain's tools are
exactly its ``tool_specs()``. A registered domain that cannot be loaded (for example one that is
still being built) is skipped with a warning, so the other domains are still served.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cielo_bench import domains as registry
from cielo_bench.domain import Domain

log = logging.getLogger(__name__)


def skip_reason(exc: BaseException) -> str:
    """Short reason shown to clients; the full error goes to the server log (stderr)."""
    return f"could not be loaded ({type(exc).__name__})"


def load_domains() -> tuple[dict[str, Domain], dict[str, str]]:
    """Every registered domain that loads, and why each of the others was skipped."""
    loaded: dict[str, Domain] = {}
    skipped: dict[str, str] = {}
    for name in registry.REGISTRY:
        try:
            loaded[name] = registry.get_domain(name)
        except Exception as exc:  # one domain that does not load must not take the others down
            log.warning("domain %r is registered but could not be loaded, skipping it: %r", name, exc)
            skipped[name] = skip_reason(exc)
    return loaded, skipped


@dataclass(frozen=True)
class ToolBinding:
    """One MCP tool: the name clients see, and the domain tool it runs."""

    name: str  # the domain's own tool name, or "<domain>_<tool>" when two domains share it
    domain: str
    tool: str  # the name the domain's executor expects
    spec: Mapping[str, Any]


def bind_tools(specs: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[ToolBinding]:
    """Name every tool. A name used by more than one domain gets the domain as a prefix."""
    uses = Counter(spec["name"] for domain_specs in specs.values() for spec in domain_specs)
    bindings = [
        ToolBinding(
            name=f"{domain}_{spec['name']}" if uses[spec["name"]] > 1 else spec["name"],
            domain=domain, tool=spec["name"], spec=spec,
        )
        for domain, domain_specs in specs.items()
        for spec in domain_specs
    ]
    clashes = sorted(name for name, n in Counter(b.name for b in bindings).items() if n > 1)
    if clashes:
        raise ValueError(f"tool names collide even with the domain prefix: {clashes}")
    return bindings
