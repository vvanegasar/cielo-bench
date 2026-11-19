"""Regression test: the fault files must be safe to build from many threads at once.

CI once failed with ``table customers already exists`` because two runner threads built the
``empty`` replica at the same time on the first call.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

from cielo_bench.domains.tabular import tools


def _fresh_fault_cache() -> None:
    tools.reset_fault_files()


def test_empty_replica_is_built_once_under_concurrency():
    _fresh_fault_cache()
    with ThreadPoolExecutor(max_workers=16) as pool:
        paths = list(pool.map(lambda _: tools.empty_replica(), range(64)))
    assert len(set(paths)) == 1
    con = sqlite3.connect(paths[0])
    try:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "customers" in tables
        assert con.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0
    finally:
        con.close()


def test_corrupted_file_is_built_once_under_concurrency():
    _fresh_fault_cache()
    with ThreadPoolExecutor(max_workers=16) as pool:
        paths = list(pool.map(lambda _: tools.corrupted_file(), range(64)))
    assert len(set(paths)) == 1
    assert paths[0].read_bytes().startswith(b"cielo-bench: simulated corrupted database file")
