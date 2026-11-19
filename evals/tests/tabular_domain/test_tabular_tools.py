"""describe_schema and run_sql: results, limits, read-only guards and the failure paths."""

import json
import sqlite3

import pytest

from cielo_bench.domains.tabular.generate import content_sha256
from cielo_bench.domains.tabular.schema import TABLE_NAMES
from cielo_bench.domains.tabular.sqlguard import (
    MAX_ROWS,
    Limits,
    QueryRejected,
    connect,
    run_select,
    strip_sql,
    validate,
)
from cielo_bench.domains.tabular.tools import FAILURE_KEYS, FAULT_PROFILES, TabularToolExecutor

MARCH_2025 = (
    "SELECT ROUND(SUM(amount), 2) AS total FROM invoices WHERE status <> 'void' "
    "AND issue_date >= '2025-03-01' AND issue_date < '2025-04-01'"
)

WRITES = [
    "INSERT INTO customers (customer_id, name) VALUES (9999, 'x')",
    "UPDATE invoices SET status = 'paid'",
    "DELETE FROM payments",
    "REPLACE INTO snapshot_info VALUES ('as_of_date', '2030-01-01')",
    "INSERT OR REPLACE INTO snapshot_info VALUES ('a', 'b')",
    "DROP TABLE invoices",
    "ALTER TABLE invoices ADD COLUMN x TEXT",
    "CREATE TABLE x (a INTEGER)",
    "CREATE TEMP TABLE x AS SELECT * FROM invoices",
    "CREATE INDEX i ON invoices(amount)",
    "ATTACH DATABASE 'other.sqlite' AS other",
    "DETACH DATABASE other",
    "PRAGMA writable_schema = ON",
    "PRAGMA table_info(invoices)",
    "pragma query_only = off",
    "SELECT * FROM pragma_table_info('invoices')",
    "VACUUM",
    "VACUUM INTO 'copy.sqlite'",
    "REINDEX",
    "ANALYZE",
    "BEGIN; DELETE FROM payments; COMMIT",
    "WITH x AS (SELECT 1) DELETE FROM payments",
    "WITH x AS (SELECT 1) INSERT INTO snapshot_info SELECT 'a', 'b' FROM x",
    "SELECT 1; DROP TABLE invoices",
    "SELECT load_extension('evil')",
    "SAVEPOINT s",
    "  /* hidden */ DROP TABLE invoices",
]


def fresh_executor(domain, **kw):
    return TabularToolExecutor(domain.db_path, content_sha256=domain.database_info()["content_sha256"], **kw)


def test_describe_schema_lists_every_table_with_counts_and_codes(tabular, tabular_executor):
    r = tabular_executor.execute("describe_schema", {})
    assert r["status"] == "ok" and r["dialect"] == "SQLite" and r["snapshot_as_of"] == "2026-09-30"
    assert [t["name"] for t in r["tables"]] == list(TABLE_NAMES)
    counts = tabular.database_info()["row_counts"]
    assert {t["name"]: t["row_count"] for t in r["tables"]} == counts
    invoices = next(t for t in r["tables"] if t["name"] == "invoices")
    status = next(c for c in invoices["columns"] if c["name"] == "status")
    assert status["allowed_values"] == ["paid", "open", "overdue", "void"]
    assert r["sources"][0]["content_sha256"] == tabular.database_info()["content_sha256"]
    one = tabular_executor.execute("describe_schema", {"table": "inventory"})
    assert [t["name"] for t in one["tables"]] == ["inventory"]
    assert one["tables"][0]["primary_key"] == ["product_id", "warehouse"]


def test_run_sql_returns_columns_rows_and_its_source(tabular_executor):
    r = tabular_executor.execute("run_sql", {"sql": MARCH_2025})
    assert r["status"] == "ok" and r["columns"] == ["total"] and r["row_count"] == 1 and r["truncated"] is False
    assert isinstance(r["rows"][0][0], float) and r["rows"][0][0] > 100_000
    src = r["sources"][0]
    assert src["query"] == MARCH_2025 and src["snapshot_as_of"] == "2026-09-30" and len(src["content_sha256"]) == 64
    json.dumps(r, allow_nan=False)  # strictly JSON-serializable


def test_row_limit_truncates_and_says_so(tabular_executor):
    r = tabular_executor.execute("run_sql", {"sql": "SELECT * FROM order_items"})
    assert r["status"] == "ok" and r["row_count"] == MAX_ROWS and r["truncated"] is True


def test_awkward_values_are_serializable(tabular_executor):
    r = tabular_executor.execute(
        "run_sql", {"sql": "SELECT randomblob(8) AS b, 1e999 AS big, -1e999 AS small, NULL AS n"}
    )
    assert r["status"] == "ok" and r["rows"] == [["<blob 8 bytes>", "inf", "-inf", None]]
    json.dumps(r, allow_nan=False)


@pytest.mark.parametrize("sql", WRITES)
def test_anything_but_a_select_is_rejected_and_nothing_changes(sql, tabular, tabular_executor):
    before = content_sha256(tabular.db_path)
    r = tabular_executor.execute("run_sql", {"sql": sql})
    assert r["status"] == "invalid_input" and set(r) == {"status", "message"}
    assert content_sha256(tabular.db_path) == before


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO snapshot_info VALUES ('a', 'b')",
        "UPDATE invoices SET status = 'paid'",
        "DELETE FROM payments",
        "DROP TABLE invoices",
        "CREATE TEMP TABLE x (a)",
        "ATTACH DATABASE 'other.sqlite' AS other",
        "PRAGMA writable_schema = ON",
        "SELECT * FROM pragma_table_info('invoices')",
    ],
)
def test_the_connection_refuses_writes_even_without_static_validation(sql, tabular):
    """Defence in depth: the authorizer (and mode=ro) stop what layer 1 would have caught."""
    with pytest.raises(QueryRejected):
        validate(sql)
    con = connect(tabular.db_path, Limits())
    try:
        with pytest.raises(QueryRejected):
            run_select(con, sql, Limits())
    finally:
        con.close()


def test_mode_ro_alone_blocks_writes(tabular):
    con = sqlite3.connect(tabular.db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("DELETE FROM payments")
    finally:
        con.close()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'DROP TABLE invoices; DELETE FROM payments' AS harmless",
        "-- update everything\nSELECT COUNT(*) FROM invoices",
        "SELECT replace(name, 'Market', 'Shop') FROM customers LIMIT 1",
        "with recent as (select * from invoices where issue_date >= '2026-09-01') select count(*) from recent;",
        'SELECT "status", COUNT(*) FROM invoices GROUP BY "status"',
    ],
)
def test_keywords_inside_literals_comments_and_functions_are_fine(sql, tabular_executor):
    assert tabular_executor.execute("run_sql", {"sql": sql})["status"] == "ok"


def test_strip_sql_blanks_literals_and_comments():
    assert strip_sql("SELECT 'a;b' -- c;\n/* d; */ FROM t").split() == ["SELECT", "''", "FROM", "t"]


def test_runaway_and_broken_queries_are_invalid_input(tabular_executor):
    heavy = tabular_executor.execute("run_sql", {"sql": "SELECT COUNT(*) FROM order_items a, order_items b"})
    assert heavy["status"] == "invalid_input" and "work limit" in heavy["message"]
    broken = tabular_executor.execute("run_sql", {"sql": "SELECT nope FROM invoices"})
    assert broken["status"] == "invalid_input" and "no such column" in broken["message"]
    syntax = tabular_executor.execute("run_sql", {"sql": "SELECT FROM WHERE"})
    assert syntax["status"] == "invalid_input"


@pytest.mark.parametrize(
    "name,args,status",
    [
        ("run_sql", None, "invalid_input"),
        ("run_sql", {}, "invalid_input"),
        ("run_sql", {"sql": ""}, "invalid_input"),
        ("run_sql", {"sql": 42}, "invalid_input"),
        ("run_sql", {"sql": "SELECT 1", "limit": 5}, "invalid_input"),
        ("run_sql", {"sql": "SELECT " + "1 + " * 5000 + "1"}, "invalid_input"),
        ("describe_schema", {"table": "secrets"}, "invalid_input"),
        ("describe_schema", {"verbose": True}, "invalid_input"),
        ("execute_python", {"code": "1"}, "out_of_scope"),
    ],
)
def test_invalid_arguments(name, args, status, tabular_executor):
    assert tabular_executor.execute(name, args)["status"] == status


EXPECTED_REASON = {
    "down": "connection_failed",
    "error": "database_error",
    "empty": "empty_result",
    "timeout": "timeout",
    "permission_denied": "permission_denied",
}


@pytest.mark.parametrize("profile", FAULT_PROFILES)
@pytest.mark.parametrize("name,args", [("run_sql", {"sql": MARCH_2025}), ("describe_schema", {})])
def test_source_down_returns_no_values(profile, name, args, tabular):
    r = fresh_executor(tabular, fault_profile=profile).execute(name, args)
    assert r["status"] == "source_unavailable" and r["reason"] == EXPECTED_REASON[profile]
    assert set(r) <= FAILURE_KEYS  # no rows, no counts, nothing partial
    assert not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in r.values())


@pytest.mark.parametrize("profile", FAULT_PROFILES)
def test_invalid_arguments_are_still_invalid_under_faults(profile, tabular):
    r = fresh_executor(tabular, fault_profile=profile).execute("run_sql", {"sql": "DROP TABLE invoices"})
    assert r["status"] == "invalid_input"


def test_required_fault_kinds_and_unknown_profiles(tabular):
    from cielo_bench.domain import FAULT_KINDS

    assert set(FAULT_KINDS) <= set(tabular.fault_profiles)
    assert tabular.default_fault_profile in tabular.fault_profiles
    with pytest.raises(ValueError):
        fresh_executor(tabular, fault_profile="meteor")


def test_every_ok_result_cites_service_query_and_retrieval_time(tabular, tabular_executor):
    """The contract guard (shared with the MCP server): each ok result carries a citation."""
    from datetime import UTC, datetime

    stamp = datetime(2026, 11, 18, 21, 30, 5, tzinfo=UTC)
    ex = fresh_executor(tabular, clock=lambda: stamp)
    calls = [
        ("run_sql", {"sql": MARCH_2025}, MARCH_2025),
        ("describe_schema", {}, "describe_schema"),
        ("describe_schema", {"table": "orders"}, "describe_schema(table=orders)"),
    ]
    for name, args, query in calls:
        r = ex.execute(name, args)
        assert r["status"] == "ok" and len(r["sources"]) == 1
        source = r["sources"][0]
        assert source["service"] and source["query"] == query
        assert source["retrieved_at_utc"] == "2026-11-18T21:30:05Z"
        assert datetime.fromisoformat(source["retrieved_at_utc"].replace("Z", "+00:00")) == stamp
        assert source["content_sha256"] == tabular.database_info()["content_sha256"]
        assert "bench" not in source["service"].lower()  # the model sees a company database, not a test
    live = tabular_executor.execute("run_sql", {"sql": "SELECT 1"})["sources"][0]["retrieved_at_utc"]
    assert datetime.fromisoformat(live.replace("Z", "+00:00")).tzinfo is not None


def test_executor_makes_no_network_requests(tabular):
    ex = fresh_executor(tabular)
    ex.execute("run_sql", {"sql": MARCH_2025})
    assert ex.live_requests == 0 and ex.queries_executed == 1
