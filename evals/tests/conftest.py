"""Shared test helpers. No test touches the network: clients are offline or use mock transports."""

from __future__ import annotations

import pytest

from cielo_bench.domains import get_domain
from cielo_bench.golden import load_golden


@pytest.fixture(scope="session")
def domain():
    return get_domain("astronomy")


@pytest.fixture(scope="session")
def golden(domain):
    return load_golden(domain.golden_path)


@pytest.fixture(scope="session")
def executor(domain):
    return domain.make_executor(offline=True, max_live_requests=0)


@pytest.fixture(autouse=True)
def no_real_keep_awake(monkeypatch):
    """Never start the real macOS keep-awake helper from a test; tests that need it fake it."""
    from cielo_bench import runner

    monkeypatch.setattr(runner, "caffeinate_argv", lambda: None)
