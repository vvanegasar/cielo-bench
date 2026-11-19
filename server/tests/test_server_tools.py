"""The domain tools through a real MCP client, offline, against the benchmark's cached data.

Astronomy is tested call by call against the committed Horizons fixtures; every registered domain
is tested from its golden set. Every result is compared with what the benchmark's own executor
returns for the same call: the server must add nothing, drop nothing and invent nothing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client

from cielo_bench import domains as registry
from cielo_bench.domain import TOOL_STATUSES
from cielo_bench.domains import get_domain
from cielo_bench.golden import load_golden
from cielo_mcp.contract import FAILURE_KEYS
from cielo_mcp.domains import bind_tools
from cielo_mcp.server import ServerConfig, build_server

from .server_support import MOON_AT_1930, SATURN_AT_21, SATURN_ON_DAY, VENUS_FROM_JUPITER, numbers_in

pytestmark = pytest.mark.anyio

ASTRONOMY = get_domain("astronomy")

# One cached call per astronomy tool (and option), with the Horizons targets its citations name.
CACHED_CALLS = [
    pytest.param("body_position", SATURN_AT_21, {"699"}, id="body_position"),
    pytest.param("body_position", VENUS_FROM_JUPITER, {"299", "599"}, id="body_position-relative_to"),
    pytest.param("body_rise_set", SATURN_ON_DAY, {"699"}, id="body_rise_set"),
    pytest.param("moon_phase", MOON_AT_1930, {"301"}, id="moon_phase"),
]


def _registered(name: str):
    try:
        return registry.get_domain(name)
    except ImportError:
        return None  # registered but not built yet


def golden_calls(name: str) -> tuple[Any, list[dict]]:
    """The domain and the distinct expected calls of its golden set (skips if there are none)."""
    domain = _registered(name)
    if domain is None:
        pytest.skip(f"{name} is registered but not built yet")
    if not domain.golden_path.exists():
        pytest.skip(f"{name} has no golden set yet")
    calls = {json.dumps(c, sort_keys=True): c
             for pair in load_golden(domain.golden_path).pairs for c in pair["expected_calls"]}
    return domain, list(calls.values())


def served_domains() -> dict[str, Any]:
    return {name: d for name in registry.REGISTRY if (d := _registered(name)) is not None}


def benchmark_result(name: str, args: dict) -> dict:
    """What the benchmark's executor returns, configured as the server's default (cache only)."""
    return ASTRONOMY.make_executor(offline=True, max_live_requests=0).execute(name, args)


async def call(mode: str, name: str, args: dict, server=None):
    async with Client(server or build_server(), mode=mode) as client:
        return await client.call_tool(name, args)


async def test_every_domain_tool_is_listed_with_its_own_schema_and_annotations(mode):
    async with Client(build_server(), mode=mode) as client:
        listed = {tool.name: tool for tool in (await client.list_tools()).tools}
    bindings = bind_tools({name: d.tool_specs() for name, d in served_domains().items()})
    assert {"body_position", "body_rise_set", "moon_phase"} <= set(listed)
    assert set(listed) == {b.name for b in bindings}
    for binding in bindings:
        spec, tool = binding.spec, listed[binding.name]
        assert tool.description == spec["description"]
        assert tool.input_schema == spec["parameters"]  # the domain's JSON Schema, unchanged
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False  # cache only: nothing outside is reached
        assert tool.output_schema["properties"]["status"]["enum"] == list(TOOL_STATUSES)


async def test_live_mode_marks_the_tools_open_world(mode):
    # Building a live server opens no connection; only a tool call outside the cache would.
    # A tool is open world only if its domain has a source outside the machine (external_source).
    from cielo_bench.domains import AVAILABLE, get_domain

    external = {spec["name"]: get_domain(name).external_source for name in AVAILABLE
                for spec in get_domain(name).tool_specs()}
    async with Client(build_server(ServerConfig(live=True)), mode=mode) as client:
        tools = (await client.list_tools()).tools
    assert tools and all(t.annotations.open_world_hint is external[t.name] for t in tools)
    assert any(t.annotations.open_world_hint for t in tools)  # astronomy reaches NASA/JPL
    assert all(t.annotations.read_only_hint is True for t in tools)


@pytest.mark.parametrize("name,args,targets", CACHED_CALLS)
async def test_ok_result_is_the_benchmark_result_unchanged_and_cited(mode, name, args, targets):
    expected = benchmark_result(name, args)
    result = await call(mode, name, args)
    assert result.is_error is False
    assert result.structured_content == expected
    # The text block is exactly what the benchmark hands to models.
    assert [block.text for block in result.content] == [json.dumps(expected, ensure_ascii=False)]
    sources = result.structured_content["sources"]
    assert {source["query"]["COMMAND"].strip("'") for source in sources} == targets  # Horizons IDs
    for source in sources:
        assert source["service"] == "NASA/JPL Horizons API"
        assert source["retrieved_at_utc"].endswith("Z")
        assert len(source["response_sha256"]) == 64


async def test_values_are_horizons_values(mode):
    position = (await call(mode, "body_position", SATURN_AT_21)).structured_content
    assert position["altitude_deg"] == pytest.approx(61.63, abs=0.01)  # Horizons Elev_(r-app) 61.633823
    assert position["azimuth_deg"] == pytest.approx(260.07, abs=0.01)
    assert position["above_horizon"] is True and position["interpolated"] is False
    assert position["altitude_rate_deg_per_hour"] < 0  # past culmination (19:09), so sinking
    events = (await call(mode, "body_rise_set", SATURN_ON_DAY)).structured_content
    assert (events["rise"]["local_time"], events["set"]["local_time"]) == ("13:07", "01:14")
    # Saturn sits near the celestial equator (dec 0.67°): it rises close to east, sets close to west.
    assert events["rise"]["azimuth_deg"] == pytest.approx(89.12, abs=0.05)
    assert events["set"]["azimuth_deg"] == pytest.approx(270.88, abs=0.05)


async def test_separation_between_two_bodies(mode):
    result = (await call(mode, "body_position", VENUS_FROM_JUPITER)).structured_content
    assert (result["body"], result["relative_to"]) == ("Venus", "Jupiter")
    assert result["separation_deg"] == pytest.approx(68.74, abs=0.01)


async def test_moon_phase_from_the_cache(mode):
    phase = (await call(mode, "moon_phase", MOON_AT_1930)).structured_content
    # Two days after the full Moon of 24 December 2026: a waning gibbous Moon.
    assert phase["status"] == "ok" and phase["phase"] == "waning"
    assert phase["illuminated_fraction_pct"] == pytest.approx(86.86, abs=0.01)
    assert phase["sun_moon_elongation_deg"] == pytest.approx(137.4, abs=0.1)
    assert phase["datetime_utc"] == "2026-12-27T00:30:00Z"


@pytest.mark.parametrize("name,args", [
    ("body_position", {**SATURN_AT_21, "body": "Pluto"}),
    ("body_position", {**SATURN_AT_21, "location": {"city": "Atlantis"}}),
    ("body_position", {**SATURN_AT_21, "datetime": "tonight"}),
    ("body_position", {**SATURN_AT_21, "relative_to": "Saturn"}),  # a body is not separated from itself
    ("body_rise_set", {**SATURN_ON_DAY, "date": "12/12/2026"}),
    ("moon_phase", {**MOON_AT_1930, "datetime": "tonight"}),
    ("moon_phase", {**MOON_AT_1930, "location": {"city": "Atlantis"}}),
    ("body_position", {}),
    # Arguments reach the executor as sent: a JSON object sent as a string is not "fixed up".
    ("body_position", {**SATURN_AT_21, "location": '{"city": "Medellín"}'}),
])
async def test_invalid_input_is_an_error_result_with_no_values(mode, name, args):
    result = await call(mode, name, args)
    assert result.is_error is True
    assert result.structured_content == benchmark_result(name, args)
    assert result.structured_content["status"] == "invalid_input"
    assert result.structured_content["message"]
    assert set(result.structured_content) <= FAILURE_KEYS


async def test_unknown_tool_is_an_error(mode):
    result = await call(mode, "weather", {"city": "Medellín"})
    assert result.is_error is True
    assert result.structured_content is None
    assert "Unknown tool" in result.content[0].text


@pytest.mark.parametrize("name,args", [  # dates that are not in the cache
    ("body_position", {**SATURN_AT_21, "datetime": "2030-01-01T21:00:00-05:00"}),
    ("body_rise_set", {**SATURN_ON_DAY, "date": "2030-01-01"}),
    ("moon_phase", {**MOON_AT_1930, "datetime": "2030-01-01T19:30:00-05:00"}),
])
async def test_cache_miss_is_source_unavailable_with_no_values(mode, name, args):
    result = await call(mode, name, args)
    assert result.is_error is True
    failure = result.structured_content
    assert failure == benchmark_result(name, args)
    assert (failure["status"], failure["reason"]) == ("source_unavailable", "offline_cache_miss")
    assert failure["source"] == "NASA/JPL Horizons API"
    assert set(failure) <= FAILURE_KEYS and not numbers_in(failure)


def _stable(obj):
    """Drop per-call timestamps (`retrieved_at_utc`), which differ between two calls that cross a second."""
    if isinstance(obj, dict):
        return {k: _stable(v) for k, v in obj.items() if k != "retrieved_at_utc"}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    return obj


@pytest.mark.parametrize("domain_name", list(registry.REGISTRY))
async def test_every_golden_set_call_is_served_unchanged_and_cited(domain_name):
    domain, calls = golden_calls(domain_name)
    executor = domain.make_executor(offline=True, max_live_requests=0)
    async with Client(build_server(), mode="legacy") as client:
        listed = {tool.name for tool in (await client.list_tools()).tools}
        for c in calls:
            name = c["tool"] if c["tool"] in listed else f"{domain_name}_{c['tool']}"
            result = await client.call_tool(name, c["args"])
            assert result.is_error is False, (c, result.content)  # cached, so it must be ok
            # Live SQLite citations are stamped at call time; compare everything else.
            assert _stable(result.structured_content) == _stable(executor.execute(c["tool"], c["args"]))


@pytest.mark.parametrize("domain_name,profile", [
    (name, profile)
    for name in registry.REGISTRY
    for profile in (getattr(_registered(name), "fault_profiles", None) or ("none-declared",))
])
async def test_every_domain_fails_honestly_through_mcp(domain_name, profile):
    domain, calls = golden_calls(domain_name)
    server = build_server(domains={domain_name: domain},
                          executor_factory=lambda d: d.make_executor(fault_profile=profile))
    async with Client(server, mode="legacy") as client:
        result = await client.call_tool(calls[0]["tool"], calls[0]["args"])
    assert result.is_error is True
    failure = result.structured_content
    assert failure["status"] == "source_unavailable" and failure["source"] and failure["reason"]
    assert set(failure) <= FAILURE_KEYS and not numbers_in(failure)


@pytest.mark.parametrize("profile", ASTRONOMY.fault_profiles)
@pytest.mark.parametrize("name,args", [p.values[:2] for p in CACHED_CALLS], ids=[p.id for p in CACHED_CALLS])
async def test_source_down_is_source_unavailable_with_no_values(mode, profile, name, args):
    # The server never injects faults; the test puts the source down through the factory.
    server = build_server(executor_factory=lambda domain: domain.make_executor(fault_profile=profile))
    result = await call(mode, name, args, server)
    assert result.is_error is True
    failure = result.structured_content
    assert failure["status"] == "source_unavailable" and failure["source"] == "NASA/JPL Horizons API"
    assert set(failure) <= FAILURE_KEYS and not numbers_in(failure)  # nothing partial
    assert [block.text for block in result.content] == [json.dumps(failure, ensure_ascii=False)]
