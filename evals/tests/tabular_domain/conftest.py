"""Fixtures for the tabular-domain tests. Offline: the snapshot is a local SQLite file."""

from __future__ import annotations

import pytest

from cielo_bench.domains import get_domain
from cielo_bench.golden import load_golden


@pytest.fixture(scope="session")
def tabular():
    domain = get_domain("tabular")
    domain.database_info()  # checks the snapshot against its manifest
    return domain


@pytest.fixture(scope="session")
def tabular_golden(tabular):
    return load_golden(tabular.golden_path)


@pytest.fixture(scope="session")
def tabular_executor(tabular):
    return tabular.make_executor()
