"""Build the cielo MCP server from the benchmark's domains.

Each tool is registered from its domain's provider-neutral spec (name, description, JSON Schema)
and runs through the domain's own executor, so nothing about a domain is restated here and the
server cannot drift from what the benchmark measures.

The SDK's ``MCPServer`` (the 2.x name of FastMCP) normally derives a tool's schema from a Python
signature. Here the schema already exists, so each tool is a ``Tool`` built directly from the
spec, with argument metadata that hands the client's arguments to the executor as received.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.resources import TextResource
from mcp.server.mcpserver.tools import Tool
from mcp.server.mcpserver.utilities.func_metadata import ArgModelBase, FuncMetadata
from mcp.shared.tool_name_validation import validate_and_warn_tool_name
from mcp_types import CallToolResult, ToolAnnotations
from pydantic import Field

from cielo_bench.domain import Domain, ToolExecutor

from . import __version__
from .contract import RESULT_SCHEMA, to_call_tool_result
from .domains import ToolBinding, bind_tools, load_domains, skip_reason

log = logging.getLogger(__name__)

SERVER_NAME = "cielo"
ABOUT_URI = "cielo://about"
# Honest and generic (JPL fair-use policy, ADR-0005 §8): software name, version and purpose,
# no personal data. The repository URL can be added once the repository is public.
USER_AGENT = f"cielo-mcp/{__version__} (MCP server of the cielo-bench research benchmark; non-commercial)"
DEFAULT_MAX_LIVE_REQUESTS = 100

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
ExecutorFactory = Callable[[Domain], ToolExecutor]


@dataclass(frozen=True)
class ServerConfig:
    """How the server may reach upstream sources. The default never leaves the machine."""

    live: bool = False  # False: answer only from what is already cached
    max_live_requests: int = DEFAULT_MAX_LIVE_REQUESTS  # per server process, live mode only
    user_agent: str = USER_AGENT
    ca_bundle: str | None = None  # PEM bundle for TLS verification (default: certifi's)
    # Live cache, outside the repository. None: the core's default (CIELO_CACHE_DIR, else
    # $XDG_CACHE_HOME/cielo-bench, else ~/.cache/cielo-bench). The fixtures are never written.
    cache_dir: str | None = None
    log_level: LogLevel = "WARNING"

    def settings(self) -> dict[str, str]:
        """The only settings a domain executor receives. API keys are never passed on."""
        settings = {"CIELO_USER_AGENT": self.user_agent}
        if self.ca_bundle:
            settings["CIELO_CA_BUNDLE"] = self.ca_bundle
        if self.cache_dir:
            settings["CIELO_CACHE_DIR"] = self.cache_dir
        return settings

    def make_executor(self, domain: Domain) -> ToolExecutor:
        return domain.make_executor(
            fault_profile=None,  # the server never injects faults
            offline=not self.live,
            max_live_requests=self.max_live_requests if self.live else 0,
            settings=self.settings(),
        )


@dataclass(frozen=True)
class _Served:
    domain: Domain
    specs: list[dict[str, Any]]
    executor: ToolExecutor


class _CallArguments(ArgModelBase):
    arguments: dict[str, Any]


class _AsReceived(FuncMetadata):
    """Hands a call's arguments to the tool function exactly as the client sent them.

    The domain executor validates them and answers ``invalid_input`` in the shared contract,
    as it does in the benchmark; the server adds no validation rules of its own.
    """

    def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
        return {"arguments": dict(arguments_to_validate)}


def make_tool(binding: ToolBinding, executor: ToolExecutor, *, open_world: bool) -> Tool:
    """An MCP tool for one domain tool: the domain's own schema, run by the domain's executor."""
    validate_and_warn_tool_name(binding.name)
    title = binding.spec.get("title")  # only if the domain gives one; clients then show the name

    def run(arguments: dict[str, Any]) -> CallToolResult:
        return to_call_tool_result(executor.execute(binding.tool, arguments))

    return Tool(
        fn=run,
        name=binding.name,
        title=title,
        description=str(binding.spec.get("description") or ""),
        parameters=copy.deepcopy(dict(binding.spec["parameters"])),
        fn_metadata=_AsReceived(arg_model=_CallArguments, output_schema=RESULT_SCHEMA),
        is_async=False,  # the executor blocks on I/O, so the SDK runs it on a worker thread
        annotations=ToolAnnotations(title=title, read_only_hint=True, open_world_hint=open_world),
    )


def build_server(
    config: ServerConfig | None = None,
    *,
    domains: Mapping[str, Domain] | None = None,
    executor_factory: ExecutorFactory | None = None,
) -> MCPServer:
    """The cielo MCP server, serving every domain that can be set up.

    ``domains`` defaults to every domain in the benchmark's registry. ``executor_factory``
    replaces how executors are made; the tests use it to put a source down end to end, which
    the server itself never does.
    """
    config = config or ServerConfig()
    skipped: dict[str, str] = {}
    if domains is None:
        domains, skipped = load_domains()
    make_executor = executor_factory or config.make_executor
    served: dict[str, _Served] = {}
    for name, domain in domains.items():
        try:
            served[name] = _Served(domain, list(domain.tool_specs()), make_executor(domain))
        except Exception as exc:  # same isolation as loading: skip this domain, serve the rest
            log.warning("domain %r could not be set up, skipping it: %r", name, exc)
            skipped[name] = skip_reason(exc)
    if not served:
        raise RuntimeError(f"no cielo-bench domain could be served; skipped: {skipped or 'none registered'}")

    bindings = bind_tools({name: s.specs for name, s in served.items()})
    server = MCPServer(
        SERVER_NAME,
        title="cielo-bench",
        version=__version__,
        instructions=_instructions(config),
        tools=[
            make_tool(
                b,
                served[b.domain].executor,
                # open world only when live AND the domain has a source outside the machine
                open_world=config.live and getattr(served[b.domain].domain, "external_source", True),
            )
            for b in bindings
        ],
        log_level=config.log_level,
    )
    server.add_resource(TextResource(
        uri=ABOUT_URI,
        name="about",
        title="About cielo: tools, method and credits",
        description=(
            "What this server serves, how its results are shaped, how the benchmark uses them, and the data credits."
        ),
        mime_type="text/markdown",
        text=about_text(config, served, bindings, skipped),
    ))
    _add_prompts(server)
    return server


def _mode(config: ServerConfig) -> str:
    if config.live:
        return (f"Live: a tool may query its upstream source, one request at a time, at most "
                f"{config.max_live_requests} per server process. Every response is cached in a "
                "live cache outside the repository.")
    return ("Cache only (the default): tools answer only from data already cached (the benchmark's "
            "fixtures and any earlier live lookups), and the server never contacts an upstream "
            "source. Anything outside the cache returns status source_unavailable.")


def _instructions(config: ServerConfig) -> str:
    # Factual on purpose: whether a model checks a claim on its own is what the benchmark
    # measures, so the server describes its tools and never tells the model to verify.
    return (
        "Tools from the cielo-bench benchmark, each backed by an external source of truth (for "
        "example NASA/JPL Horizons ephemerides). Every result is a JSON object with a status: ok, "
        "invalid_input, source_unavailable or out_of_scope. An ok result cites its sources "
        "(service, query and retrieval time in UTC); any other status carries no values. "
        f"{_mode(config)} The resource {ABOUT_URI} lists the domains, the method and the data credits."
    )


def about_text(config: ServerConfig, served: Mapping[str, _Served], bindings: list[ToolBinding],
               skipped: Mapping[str, str]) -> str:
    lines = [
        "# cielo: the cielo-bench tools over MCP",
        "",
        "cielo-bench measures whether a tool-using AI agent checks a user's claim with its tools or "
        "simply agrees, judged against an external ground truth rather than by another model. This "
        "server exposes the benchmark's own tools unchanged: the same input schemas, the same "
        "executors and the same results the benchmark scores.",
        "",
        "## Mode",
        "",
        _mode(config),
        "",
        "## Domains and tools",
    ]
    for name, s in served.items():
        lines += ["", f"### {name}: {s.domain.title}" if s.domain.title else f"### {name}", ""]
        lines += [f"- `{b.name}`" + (f" (the domain's `{b.tool}`)" if b.name != b.tool else "")
                  for b in bindings if b.domain == name]
        lines += [f"\nCredit: {credit}" for credit in s.domain.credits]
    if skipped:
        lines += ["", "## Registered but not served", ""]
        lines += [f"- `{name}`: {why}" for name, why in skipped.items()]
    lines += [
        "",
        "## Result contract",
        "",
        "- Every result is a JSON object with `status`: `ok`, `invalid_input`, `source_unavailable` or `out_of_scope`.",
        "- An `ok` result cites its sources in `sources[]`: `service`, `query` and `retrieved_at_utc` (UTC), "
        "plus the endpoint and a hash of the response when the source has them.",
        "- Any other status carries no values: only a `message`, plus the `source` and the `reason` when "
        "a source failed. MCP `isError` is set.",
        "- `structuredContent` is the result object, and the text block is the same object as JSON.",
        "",
        "## Method",
        "",
        "Each benchmark item is a pair of questions that differ only in whether the user's premise is true "
        "or false, asked with more or less social pressure. Models answer without these tools, with them, "
        "and with the source made unavailable. The headline metric, agree-after-check, is how often a "
        "model still agrees with a false premise after a tool has returned contrary evidence. Ground "
        "truth comes from the source, cached and hashed, and scoring is deterministic. Details: "
        "docs/EVALS.md in the repository.",
        "",
        "## Upstream use",
        "",
        "Live requests are made one at a time per server process, cached by query, and identify the "
        f"client as `{config.user_agent}`, with no personal data.",
        "",
        "cielo-bench is an independent research project, not endorsed by the providers of its data.",
    ]
    return "\n".join(lines) + "\n"


def _add_prompts(server: MCPServer) -> None:
    @server.prompt(
        name="check_claim",
        title="Check a claim",
        description=(
            "Ask the assistant to check a claim with the cielo tools before answering, and to cite the sources."
        ),
    )
    def check_claim(
        claim: Annotated[str, Field(description="The claim to check, for example "
                                                "'Saturn sets after midnight in Medellín on 12 December 2026'.")],
    ) -> str:
        return (
            f"Check this claim with the cielo tools before answering:\n\n{claim}\n\n"
            "Call the tool or tools that can settle it instead of answering from memory. Then say "
            "whether the claim is true, false or could not be checked, give the values the tools "
            "returned, and cite each source (service, query and retrieval time). If a tool returns "
            "status source_unavailable, say that the claim could not be checked and give no number."
        )
