"""The about resource, the check_claim prompt and the server instructions."""

from __future__ import annotations

import pytest
from mcp import Client

from cielo_mcp import __version__
from cielo_mcp.server import ABOUT_URI, build_server

pytestmark = pytest.mark.anyio


async def test_about_resource_describes_tools_contract_method_and_credits(mode):
    async with Client(build_server(), mode=mode) as client:
        listed = (await client.list_resources()).resources
        contents = (await client.read_resource(ABOUT_URI)).contents
    assert [str(r.uri) for r in listed] == [ABOUT_URI]
    assert listed[0].mime_type == "text/markdown"
    text = contents[0].text
    for expected in ("`body_position`", "`body_rise_set`", "`moon_phase`", "Cache only", "`source_unavailable`",
                     "`retrieved_at_utc`", "agree-after-check", "NASA/JPL", "not endorsed"):
        assert expected in text, expected


async def test_check_claim_prompt_carries_the_claim(mode):
    claim = "Saturn sets after midnight in Medellín on 12 December 2026"
    async with Client(build_server(), mode=mode) as client:
        prompts = (await client.list_prompts()).prompts
        rendered = await client.get_prompt("check_claim", {"claim": claim})
    assert [p.name for p in prompts] == ["check_claim"]
    assert [(a.name, a.required) for a in prompts[0].arguments] == [("claim", True)]
    text = rendered.messages[0].content.text
    assert claim in text and "source_unavailable" in text and "give no number" in text


async def test_server_identifies_itself_and_states_the_contract():
    async with Client(build_server(), mode="legacy") as client:
        info, instructions = client.server_info, client.instructions
    assert (info.name, info.version) == ("cielo", __version__)
    assert "source_unavailable" in instructions and "no values" in instructions
    assert "Cache only" in instructions  # the mode is stated, so a failure is not a surprise
