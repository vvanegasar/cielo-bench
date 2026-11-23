"""Find the benchmark's domains and give each of their tools an MCP name.

The server has no domain knowledge of its own, but it serves **only an allowlist of domains**,
``SERVED_DOMAINS``, and fails closed (ADR-0007, ADR-0009). A domain that is not listed is never
imported or instantiated by the server, so a new domain, for example one with write tools, is not
served unless it is added here on purpose. A listed domain is loaded with the core's own loader,
and its tools are exactly its ``tool_specs()``. A listed domain that cannot be loaded is skipped
with a warning, so the other domains are still served.
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

# The only domains the server loads. Every tool of a served domain must declare readOnlyHint: true
# in its spec, or the server refuses to start (server.build_server). Never add a domain with write
# tools here: serving write tools over MCP needs its own ADR (ADR-0009, "Alternatives considered").
SERVED_DOMAINS = ("astronomy", "tabular")


def skip_reason(exc: BaseException) -> str:
    """Short reason shown to clients; the full error goes to the server log (stderr)."""
    return f"could not be loaded ({type(exc).__name__})"


def load_domains() -> tuple[dict[str, Domain], dict[str, str]]:
    """Every allowlisted domain that loads, and why each of the others was skipped.

    A registered domain outside ``SERVED_DOMAINS`` is neither imported nor listed."""
    loaded: dict[str, Domain] = {}
    skipped: dict[str, str] = {}
    for name in SERVED_DOMAINS:
        if name not in registry.REGISTRY:
            skipped[name] = "is not registered in the benchmark"
            continue
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
