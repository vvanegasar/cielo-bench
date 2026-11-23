"""A tiny database with the operations schema, for the sandbox and write-tool tests.

It has every table of ``distributor-ops-v1`` and a handful of rows, so the tests of the in-memory
sandbox and of the tools do not depend on the generated fixture.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cielo_bench.domains.tabular_act import ops_schema as S

ROWS: dict[str, list[tuple]] = {
    "customers": [
        (1, "Tienda Uno", "retail", "Centro", None, 5000.0, 30, "2024-01-10"),
        (2, "Cafe Dos", "horeca", "Norte", "a@b.example", None, 15, "2024-02-01"),
        (3, "Farmacia Tres", "pharmacy", "Sur", None, 8000.0, 45, "2024-03-05"),
    ],
    "products": [
        (1, "BEV-0001", "Agua 600 ml x24", "Beverages", 8.3, 5.1, 40, 1),
        (2, "SNK-0002", "Galletas x12", "Snacks", 12.0, None, 20, 1),
        (3, "PAP-0003", "Servilletas x50", "Paper goods", 4.5, 2.0, 10, 0),
    ],
    "orders": [
        (10, 1, "2026-08-01", "returned", "web", "2026-08-02"),
        (11, 2, "2026-08-10", "delivered", "phone", "2026-08-11"),
        (12, 3, "2026-09-01", "delivered", None, "2026-09-02"),
    ],
    "order_items": [(100, 10, 1, 10, 8.3, 0.0), (101, 11, 2, 5, 12.0, 0.0), (102, 12, 1, 20, 8.3, 0.05)],
    "invoices": [
        (1, "INV-2026-00001", 10, "2026-08-02", "2026-09-01", 83.0, "paid"),
        (2, "INV-2026-00002", 11, "2026-08-11", "2026-08-26", 60.0, "overdue"),
        (3, "INV-2026-00003", 12, "2026-09-02", "2026-10-17", 157.7, "open"),
    ],
    "payments": [(10, 1, "2026-08-20", 83.0, "card")],
    "inventory": [(1, "Centro", 25, "2026-09-20"), (1, "Norte", 90, None), (2, "Centro", 5, "2026-09-01")],
    "refunds": [],
    "credit_holds": [
        (2, 1, "late_payment", "2026-09-15", None, None),
        (3, 0, "risk_review", "2026-05-01", "2026-06-01", None),
    ],
    "collection_cases": [(10, 2, "2026-09-20", "open", None, None)],
    "reorders": [(10, 2, "Centro", 40, "2026-09-25", "open", None)],
    "system_info": sorted(S.SYSTEM_INFO),
}


def write_tiny(path: Path) -> Path:
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("PRAGMA journal_mode = DELETE")
        con.executescript(S.schema_ddl())
        for table in S.TABLES:
            marks = ", ".join("?" for _ in table.columns)
            con.executemany(f"INSERT INTO {table.name} VALUES ({marks})", ROWS[table.name])
        con.executescript(S.indexes_ddl())
    finally:
        con.close()
    return path
