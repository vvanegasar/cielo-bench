"""The real transports and the command line.

* stdio: the server runs as a subprocess, exactly as Claude Desktop starts it, and is driven by
  the SDK's stdio client.
* Streamable HTTP: the server's ASGI app runs under uvicorn on 127.0.0.1 and is driven by the
  SDK's HTTP client.

Both run in the default cache-only mode, so neither touches the network.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from mcp import Client, StdioServerParameters

from cielo_mcp import __version__
from cielo_mcp.cli import config_from, main, parser
from cielo_mcp.server import USER_AGENT, build_server

from .server_support import SATURN_AT_21

SERVER_DIR = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {"body_position", "body_rise_set"}


async def list_and_call(target, mode: str = "auto") -> None:
    async with Client(target, mode=mode) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        result = await client.call_tool("body_position", SATURN_AT_21)
    assert names >= EXPECTED_TOOLS
    assert result.is_error is False
    assert result.structured_content["sources"][0]["service"] == "NASA/JPL Horizons API"


@pytest.mark.anyio
async def test_stdio_subprocess_serves_the_tools(mode, empty_live_cache):
    # `python -m cielo_mcp` is what the `cielo-mcp` entry point runs; "legacy" is the
    # initialize handshake Claude Desktop uses. --cache-dir keeps the subprocess hermetic too.
    params = StdioServerParameters(command=sys.executable, cwd=str(SERVER_DIR),
                                   args=["-m", "cielo_mcp", "--cache-dir", str(empty_live_cache)])
    await list_and_call(params, mode)


@pytest.fixture
def http_url() -> Iterator[str]:
    app = build_server().streamable_http_app()  # host 127.0.0.1: DNS-rebinding protection on
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=15)


@pytest.mark.anyio
async def test_streamable_http_serves_the_tools_on_loopback(http_url):
    await list_and_call(http_url)


# --- command line ----------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [
    ["--transport", "streamable-http", "--host", "0.0.0.0"],  # local use only
    ["--max-live-requests", "5"],  # meaningless without --live
    ["--live", "--max-live-requests", "0"],
])
def test_unsafe_or_meaningless_arguments_are_refused(argv):
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2


def test_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0 and __version__ in capsys.readouterr().out


def test_only_three_environment_settings_are_read_never_api_keys():
    environ = {
        "CIELO_ANTHROPIC_API_KEY": "sk-should-never-be-read",
        "ANTHROPIC_API_KEY": "sk-should-never-be-read",
        "CIELO_CA_BUNDLE": "/etc/ssl/ca.pem",
        "CIELO_CACHE_DIR": "/var/cache/cielo",
    }
    config = config_from(parser().parse_args(["--live"]), environ)
    assert config.settings() == {"CIELO_USER_AGENT": USER_AGENT, "CIELO_CA_BUNDLE": "/etc/ssl/ca.pem",
                                 "CIELO_CACHE_DIR": "/var/cache/cielo"}
    assert config.live and config.max_live_requests == 100
    assert config_from(argparse.Namespace(live=False, max_live_requests=None, log_level="WARNING"),
                       {"CIELO_USER_AGENT": "my-ua/1"}).user_agent == "my-ua/1"


def test_cache_dir_flag_wins_over_the_environment():
    args = parser().parse_args(["--live", "--cache-dir", "/srv/cielo-cache"])
    config = config_from(args, {"CIELO_CACHE_DIR": "/var/cache/cielo"})
    assert config.settings()["CIELO_CACHE_DIR"] == "/srv/cielo-cache"
    assert "CIELO_CACHE_DIR" not in config_from(parser().parse_args([]), {}).settings()
