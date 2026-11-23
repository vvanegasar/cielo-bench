"""Domain discovery, tool naming, the result-contract guard and executor settings.

Fake domains here implement only what the server uses: ``title``, ``credits``, ``tool_specs()``
and ``make_executor()``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

import pytest
from mcp import Client

from cielo_bench import domains as registry
from cielo_mcp import domains as server_domains
from cielo_mcp.contract import ContractViolation, check_result
from cielo_mcp.domains import SERVED_DOMAINS, ToolBinding, bind_tools, load_domains
from cielo_mcp.server import (
    USER_AGENT,
    NotReadOnly,
    ServerConfig,
    about_text,
    build_server,
    make_tool,
    read_only,
)

pytestmark = pytest.mark.anyio

CITATION = {"service": "Fake source", "query": {"q": "x"}, "retrieved_at_utc": "2026-11-18T00:00:00Z"}


class FakeExecutor:
    live_requests = 0

    def __init__(self, answer):
        self.answer = answer
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name: str, arguments: dict[str, Any] | None) -> Any:
        self.calls.append((name, arguments))
        return self.answer(name, arguments)


READ_ONLY = {"readOnlyHint": True}


class FakeDomain:
    credits = ("Fake data, for tests.",)

    def __init__(self, name: str, tools: list[str], answer=None, annotations: dict[str, Any] | None = None):
        self.title = f"Fake domain {name}"
        self._tools = tools
        self.executor = FakeExecutor(answer or (lambda tool, args: {
            "status": "ok", "domain": name, "tool": tool, "sources": [CITATION]}))
        self.executor_kwargs: dict[str, Any] | None = None
        self.annotations = {t: READ_ONLY for t in tools} if annotations is None else annotations

    def tool_specs(self) -> list[dict[str, Any]]:
        specs = [{"name": t, "description": f"{t} (fake)",
                  "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}
                 for t in self._tools]
        for spec in specs:
            if spec["name"] in self.annotations:
                spec["annotations"] = self.annotations[spec["name"]]
        return specs

    def make_executor(self, **kwargs: Any) -> FakeExecutor:
        self.executor_kwargs = kwargs
        return self.executor


class BrokenDomain(FakeDomain):
    def tool_specs(self) -> list[dict[str, Any]]:
        raise RuntimeError("cannot open its data")


async def tool_names(server) -> set[str]:
    async with Client(server) as client:
        return {tool.name for tool in (await client.list_tools()).tools}


# --- discovery -------------------------------------------------------------------------------

async def test_every_allowlisted_domain_is_served():
    names = await tool_names(build_server())
    for name in SERVED_DOMAINS:
        try:
            domain = registry.get_domain(name)
        except ImportError:
            continue  # registered but not built yet: covered by the next test
        assert {spec["name"] for spec in domain.tool_specs()} <= names | {
            f"{name}_{spec['name']}" for spec in domain.tool_specs()}


async def test_an_allowlisted_domain_that_does_not_exist_yet_is_skipped(monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "ghost", "cielo_bench.domains.ghost:GhostDomain")
    monkeypatch.setattr(server_domains, "SERVED_DOMAINS", (*SERVED_DOMAINS, "ghost"))
    server = build_server()
    assert {"body_position", "body_rise_set"} <= await tool_names(server)
    async with Client(server) as client:
        about = (await client.read_resource("cielo://about")).contents[0].text
    assert "`ghost`: could not be loaded (ModuleNotFoundError)" in about


async def test_a_domain_that_fails_to_set_up_is_skipped_and_the_rest_served():
    server = build_server(domains={"good": FakeDomain("good", ["lookup"]),
                                   "broken": BrokenDomain("broken", ["other"])})
    assert await tool_names(server) == {"lookup"}


def test_no_servable_domain_is_an_error():
    with pytest.raises(RuntimeError, match="no cielo-bench domain"):
        build_server(domains={"broken": BrokenDomain("broken", ["other"])})


# --- the read-only guard (ADR-0009) ------------------------------------------------------------

def test_only_allowlisted_domains_are_loaded_and_the_rest_are_never_imported(monkeypatch):
    # A registered domain outside the allowlist would blow up if the server imported it.
    monkeypatch.setitem(registry.REGISTRY, "trap", "cielo_mcp_trap_never_imported:Trap")
    loaded, skipped = load_domains()
    assert set(loaded) == set(SERVED_DOMAINS) and "trap" not in skipped
    assert "cielo_mcp_trap_never_imported" not in sys.modules
    assert SERVED_DOMAINS == ("astronomy", "tabular")


def test_the_server_never_imports_the_act_domain():
    code = (
        "import sys\n"
        "from cielo_bench import domains\n"
        "from cielo_mcp.server import build_server\n"
        "build_server()\n"
        "assert 'tabular_act' in domains.REGISTRY, 'the act domain is registered in the benchmark'\n"
        "assert not [m for m in sys.modules if m.startswith('cielo_bench.domains.tabular_act')], 'imported'\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-2000:]


@pytest.mark.parametrize("annotations", [
    {"lookup": READ_ONLY},  # "write" has no annotation at all: a missing readOnlyHint counts as false
    {"lookup": READ_ONLY, "write": {"readOnlyHint": False, "destructiveHint": True}},
    {"lookup": READ_ONLY, "write": {"destructiveHint": False}},
    {"lookup": READ_ONLY, "write": {"readOnlyHint": "true"}},  # only the boolean true counts
])
def test_the_server_refuses_to_start_unless_every_tool_is_read_only(annotations):
    domain = FakeDomain("fake", ["lookup", "write"], annotations=annotations)
    with pytest.raises(NotReadOnly, match=r"\['write'\]"):
        build_server(domains={"fake": domain})
    assert domain.executor_kwargs is None  # refused before any executor was built


def test_annotations_come_from_the_spec():
    spec = {"name": "w", "description": "d", "parameters": {"type": "object"},
            "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                            "openWorldHint": False}}
    tool = make_tool(ToolBinding("w", "x", "w", spec), FakeExecutor(lambda t, a: {}), open_world=True)
    notes = tool.annotations
    assert (notes.read_only_hint, notes.destructive_hint, notes.idempotent_hint, notes.open_world_hint) == (
        False, True, True, False)
    bare = make_tool(ToolBinding("b", "x", "b", {**spec, "annotations": None}), FakeExecutor(lambda t, a: {}),
                     open_world=False)
    assert bare.annotations.read_only_hint is False and bare.annotations.open_world_hint is False
    assert read_only({"annotations": {"readOnlyHint": True}}) and not read_only({})


# --- naming ----------------------------------------------------------------------------------

async def test_a_tool_name_shared_by_two_domains_gets_the_domain_prefix():
    alpha = FakeDomain("alpha", ["lookup", "only_alpha"])
    beta = FakeDomain("beta", ["lookup"])
    server = build_server(domains={"alpha": alpha, "beta": beta})
    assert await tool_names(server) == {"alpha_lookup", "beta_lookup", "only_alpha"}
    async with Client(server) as client:
        result = await client.call_tool("beta_lookup", {"q": "x"})
    assert result.structured_content["domain"] == "beta"
    assert beta.executor.calls == [("lookup", {"q": "x"})]  # the executor sees its own tool name
    assert alpha.executor.calls == []


@pytest.mark.parametrize("specs", [
    {"a": [{"name": "t"}, {"name": "b_t"}], "b": [{"name": "t"}]},  # prefixing creates a clash
    {"a": [{"name": "t"}, {"name": "t"}]},  # one domain declares a tool twice
])
def test_names_that_still_collide_are_refused(specs):
    with pytest.raises(ValueError, match="collide"):
        bind_tools(specs)


# --- the contract guard ----------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"status": "ok", "value": 42},  # values with no citation
    {"status": "ok", "value": 42, "sources": [{"service": "Fake source", "value": 42}]},  # incomplete citation
    {"status": "source_unavailable", "message": "down", "value": 42},  # a failure carrying a value
    {"status": "maybe", "value": 42},
    [42],
])
async def test_a_result_that_breaks_the_contract_is_never_sent(bad):
    server = build_server(domains={"fake": FakeDomain("fake", ["lookup"], answer=lambda t, a: bad)})
    async with Client(server) as client:
        result = await client.call_tool("lookup", {"q": "x"})
    assert result.is_error is True
    assert result.structured_content is None
    text = json.dumps([block.model_dump() for block in result.content])
    assert "42" not in text  # nothing from the rejected result leaves the server


def test_check_result_accepts_the_contract():
    assert check_result({"status": "ok", "x": 1, "sources": [CITATION]})
    assert check_result({"status": "invalid_input", "message": "bad date"})
    assert check_result({"status": "source_unavailable", "source": "S", "reason": "timeout", "message": "m"})
    with pytest.raises(ContractViolation):
        check_result({"status": "ok", "sources": []})


# --- executor settings -----------------------------------------------------------------------

def test_default_executor_is_cache_only_with_no_faults_and_no_keys():
    domain = FakeDomain("fake", ["lookup"])
    ServerConfig().make_executor(domain)
    assert domain.executor_kwargs == {"fault_profile": None, "offline": True, "max_live_requests": 0,
                                      "settings": {"CIELO_USER_AGENT": USER_AGENT}}


def test_live_executor_is_capped_identified_and_cached_where_asked():
    domain = FakeDomain("fake", ["lookup"])
    ServerConfig(live=True, max_live_requests=7, ca_bundle="/etc/ca.pem",
                 cache_dir="/tmp/cielo-live").make_executor(domain)
    assert domain.executor_kwargs == {
        "fault_profile": None, "offline": False, "max_live_requests": 7,
        "settings": {"CIELO_USER_AGENT": USER_AGENT, "CIELO_CA_BUNDLE": "/etc/ca.pem",
                     "CIELO_CACHE_DIR": "/tmp/cielo-live"}}


def test_user_agent_is_generic():
    assert USER_AGENT.startswith("cielo-mcp/") and "@" not in USER_AGENT


def test_about_text_names_mode_and_skipped_domains():
    text = about_text(ServerConfig(live=True, max_live_requests=5), {}, [], {"ghost": "could not be loaded"})
    assert "at most 5 per server process" in text and "`ghost`: could not be loaded" in text
