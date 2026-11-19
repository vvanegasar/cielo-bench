"""Domain discovery, tool naming, the result-contract guard and executor settings.

Fake domains here implement only what the server uses: ``title``, ``credits``, ``tool_specs()``
and ``make_executor()``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client

from cielo_bench import domains as registry
from cielo_mcp.contract import ContractViolation, check_result
from cielo_mcp.domains import bind_tools
from cielo_mcp.server import USER_AGENT, ServerConfig, about_text, build_server

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


class FakeDomain:
    credits = ("Fake data, for tests.",)

    def __init__(self, name: str, tools: list[str], answer=None):
        self.title = f"Fake domain {name}"
        self._tools = tools
        self.executor = FakeExecutor(answer or (lambda tool, args: {
            "status": "ok", "domain": name, "tool": tool, "sources": [CITATION]}))
        self.executor_kwargs: dict[str, Any] | None = None

    def tool_specs(self) -> list[dict[str, Any]]:
        return [{"name": t, "description": f"{t} (fake)",
                 "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}
                for t in self._tools]

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

async def test_every_registered_domain_is_served():
    names = await tool_names(build_server())
    for name in registry.REGISTRY:
        try:
            domain = registry.get_domain(name)
        except ImportError:
            continue  # registered but not built yet: covered by the next test
        assert {spec["name"] for spec in domain.tool_specs()} <= names | {
            f"{name}_{spec['name']}" for spec in domain.tool_specs()}


async def test_a_registered_domain_that_does_not_exist_yet_is_skipped(monkeypatch):
    monkeypatch.setitem(registry.REGISTRY, "ghost", "cielo_bench.domains.ghost:GhostDomain")
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
