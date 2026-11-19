"""Shared fixtures for the server tests.

No test touches the network. The server runs in its default cache-only mode on the benchmark's
committed fixtures, and an autouse guard fails any connection or name lookup that is not to this
machine (the HTTP transport test talks to 127.0.0.1). The live cache is an empty temporary
directory, so a developer's own earlier live lookups can never change a result.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo
    attempts: list[str] = []

    def connect(self: socket.socket, address: Any) -> None:
        local = self.family == getattr(socket, "AF_UNIX", None) or (
            isinstance(address, tuple) and address[0] in LOOPBACK)
        if not local:
            attempts.append(f"connect {address!r}")
            raise OSError(f"network blocked in tests: {address!r}")
        return real_connect(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host is not None and host not in LOOPBACK:
            attempts.append(f"resolve {host!r}")
            raise OSError(f"name resolution blocked in tests: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    # Checked after the test too: the MCP layer turns exceptions into error results, so a
    # blocked attempt could otherwise pass unnoticed.
    assert not attempts, f"the test tried to use the network: {attempts}"


@pytest.fixture(autouse=True)
def empty_live_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The core reads the live cache location from CIELO_CACHE_DIR (cielo_bench.config)."""
    cache = tmp_path / "live-cache"
    monkeypatch.setenv("CIELO_CACHE_DIR", str(cache))
    return cache


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(params=["legacy", "auto"])
def mode(request: pytest.FixtureRequest) -> str:
    """Both protocol eras: the initialize handshake (what Claude Desktop speaks today) and
    2026-07-28, which the SDK client picks for an in-process server in ``auto`` mode."""
    return request.param
