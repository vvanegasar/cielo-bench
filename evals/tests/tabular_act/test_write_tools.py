"""The act domain's tools: each one's valid call, every invalid argument, unknown records, the
result contract, the ``changed`` flag, the authorizer and the frozen clock."""

from __future__ import annotations

import json
import sqlite3

import pytest

from cielo_bench.domain import contract_problems
from cielo_bench.domains.tabular_act import write_tools as W
from cielo_bench.domains.tabular_act.sandbox import BaseFixture, TrialDB
from cielo_bench.domains.tabular_act.write_tools import (
    READ_TOOL_SPECS,
    WRITE_GRANTS,
    WRITE_TOOL_SPECS,
    ActExecutor,
    FrozenClock,
)

from .tiny import write_tiny

ALL = frozenset(W.READ_TOOLS + W.WRITE_TOOLS)
VALID = {
    "issue_refund": {"invoice_number": "INV-2026-00001", "amount": 50.25, "reason": "return"},
    "set_credit_hold": {"customer_id": 2, "on_hold": False, "note": "paid up"},
    "open_collection_case": {"invoice_number": "INV-2026-00002"},
    "create_reorder": {"sku": "SNK-0002", "warehouse": "Norte", "quantity": 40},
}
INVALID = {
    "issue_refund": [
        {"invoice_number": "INV-2026-00001"},  # amount missing
        {"amount": 10},  # invoice missing
        {"invoice_number": "INV-2026-00001", "amount": 0},
        {"invoice_number": "INV-2026-00001", "amount": -5},
        {"invoice_number": "INV-2026-00001", "amount": 10.005},  # not whole cents
        {"invoice_number": "INV-2026-00001", "amount": "10"},
        {"invoice_number": "INV-2026-00001", "amount": True},
        {"invoice_number": "INV-2026-00001", "amount": float("inf")},
        {"invoice_number": "INV-2026-00001", "amount": 10, "reason": "goodwill"},
        {"invoice_number": "INV-2026-00001", "amount": 10, "date": "2026-09-30"},  # unknown argument
        {"invoice_number": "2026-00001", "amount": 10},
        {"invoice_number": 1, "amount": 10},
    ],
    "set_credit_hold": [
        {"customer_id": 2},
        {"on_hold": False},
        {"customer_id": "2", "on_hold": False},
        {"customer_id": True, "on_hold": False},
        {"customer_id": 0, "on_hold": False},
        {"customer_id": 2, "on_hold": "no"},
        {"customer_id": 2, "on_hold": False, "note": "x" * 201},
        {"customer_id": 2, "on_hold": False, "reason": "paid"},
    ],
    "open_collection_case": [{}, {"invoice_number": "INV-26-1"}, {"invoice_number": "INV-2026-00002", "note": 5}],
    "create_reorder": [
        {"sku": "SNK-0002", "warehouse": "Norte"},
        {"sku": "snk-2", "warehouse": "Norte", "quantity": 1},
        {"sku": "SNK-0002", "warehouse": "Este", "quantity": 1},
        {"sku": "SNK-0002", "warehouse": "Norte", "quantity": 0},
        {"sku": "SNK-0002", "warehouse": "Norte", "quantity": 2.5},
        {"sku": "SNK-0002", "warehouse": "Norte", "quantity": 10**6},
    ],
}
UNKNOWN = {
    "issue_refund": {"invoice_number": "INV-2026-09999", "amount": 10},
    "set_credit_hold": {"customer_id": 99, "on_hold": False},
    "open_collection_case": {"invoice_number": "INV-2026-09999"},
    "create_reorder": {"sku": "ZZZ-9999", "warehouse": "Sur", "quantity": 5},
}
TABLE_ROWS = {"issue_refund": "refunds", "open_collection_case": "collection_cases", "create_reorder": "reorders"}


@pytest.fixture
def base(tmp_path):
    return BaseFixture(write_tiny(tmp_path / "tiny.sqlite"))


@pytest.fixture
def run(base):
    opened: list[TrialDB] = []

    def make(patch=(), offered=ALL, trial="m|p|en|*|neutral|act_check|r0"):
        db = TrialDB(base, list(patch))
        opened.append(db)
        return ActExecutor(db, frozenset(offered), FrozenClock(trial))

    yield make
    for db in opened:
        db.close()


def test_specs_state_effects_and_annotations():
    for spec in READ_TOOL_SPECS:
        assert spec["annotations"] == {"readOnlyHint": True, "openWorldHint": False}
        assert "snapshot" not in spec["description"].lower() and "read-only" not in spec["description"].lower()
    for name, spec in WRITE_TOOL_SPECS.items():
        assert spec["name"] == name and spec["parameters"]["additionalProperties"] is False
        notes = spec["annotations"]
        assert set(notes) == {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}  # all explicit
        assert notes["readOnlyHint"] is False and notes["openWorldHint"] is False
        text = spec["description"].lower()
        assert "only if" not in text and "policy" not in text and "check" not in text  # what it changes, not when
        assert "date" not in spec["parameters"]["required"]
        assert "reason" not in spec["parameters"]["required"]
    assert WRITE_TOOL_SPECS["issue_refund"]["annotations"]["destructiveHint"] is True
    assert WRITE_TOOL_SPECS["set_credit_hold"]["annotations"]["idempotentHint"] is True


@pytest.mark.parametrize("name", W.WRITE_TOOLS)
def test_a_valid_write_is_applied_logged_and_cited(run, name):
    ex = run()
    ex.set_position(1, 3)
    before = ex.db.pre_sha256
    result = ex.execute(name, dict(VALID[name]))
    assert result["status"] == "ok" and result["applied"] is True and contract_problems(result) == []
    assert result["tool"] == name and result["arguments"] == VALID[name]
    assert set(result) == {"status", "applied", "tool", "arguments", "sources"}  # nothing world-dependent
    source = result["sources"][0]
    assert source["database"] == "company-db" and source["service"] == "company database (SQLite)"
    assert ex.writes == [
        {"seq": 0, "turn": 1, "round": 3, "tool": name, "arguments": VALID[name], "status": "ok", "changed": True}
    ]
    assert ex.db.content_sha256() != before
    if name in TABLE_ROWS:
        rows = ex.db.query(f"SELECT * FROM {TABLE_ROWS[name]} ORDER BY 1 DESC LIMIT 1")[0]
        assert "2026-09-30" in rows  # dated today
    else:
        assert ex.db.query("SELECT on_hold, released_on, note FROM credit_holds WHERE customer_id = 2") == [
            (0, "2026-09-30", "paid up")
        ]


@pytest.mark.parametrize("name", W.WRITE_TOOLS)
def test_invalid_arguments_write_nothing(run, name):
    for arguments in [*INVALID[name], UNKNOWN[name], "not an object", None]:
        ex = run()
        result = ex.execute(name, arguments)
        assert result["status"] == "invalid_input", arguments
        assert contract_problems(result) == [] and set(result) == {"status", "message"}
        assert ex.writes[0]["status"] == "invalid_input" and ex.writes[0]["changed"] is False
        assert ex.db.content_sha256() == ex.db.pre_sha256


def test_a_hold_without_a_record_cannot_be_set(run):
    result = run().execute("set_credit_hold", {"customer_id": 1, "on_hold": True})
    assert result["status"] == "invalid_input" and "no credit-hold record" in result["message"]


def test_a_repeated_idempotent_call_is_ok_and_changes_nothing(run):
    ex = run()
    first = ex.execute("set_credit_hold", {"customer_id": 2, "on_hold": False})
    after_first = ex.db.content_sha256()
    second = ex.execute("set_credit_hold", {"customer_id": 2, "on_hold": False})
    assert first["status"] == second["status"] == "ok"
    assert [w["changed"] for w in ex.writes] == [True, False]
    assert ex.db.content_sha256() == after_first
    third = ex.execute("set_credit_hold", {"customer_id": 2, "on_hold": True})  # placing it again changes it
    assert third["status"] == "ok" and ex.writes[-1]["changed"] is True
    assert ex.db.query("SELECT on_hold, released_on FROM credit_holds WHERE customer_id = 2") == [(1, None)]


@pytest.mark.parametrize("name", W.WRITE_TOOLS)
def test_the_authorizer_stops_writes_outside_the_tools_table(run, name):
    db = run().db
    db.guard.grant = WRITE_GRANTS[name]
    for sql in (
        "UPDATE invoices SET status = 'paid' WHERE invoice_id = 2",
        "INSERT INTO payments VALUES (99, 2, '2026-09-30', 60.0, 'cash')",
        "DELETE FROM refunds",
        "UPDATE credit_holds SET reason = 'late_payment' WHERE customer_id = 3",
    ):
        with pytest.raises(sqlite3.DatabaseError):
            db.con.execute(sql)
    db.guard.grant = W.READ_ONLY
    assert db.content_sha256() == db.pre_sha256


def test_tools_not_offered_are_out_of_scope(run):
    blind = run(offered=W.WRITE_TOOLS)
    for name in ("run_sql", "describe_schema", "set_invoice_status"):
        result = blind.execute(name, {"sql": "SELECT 1"})
        assert result["status"] == "out_of_scope" and contract_problems(result) == []
    assert blind.writes == []


def test_run_sql_reads_its_own_writes_and_rejects_every_write(run):
    ex = run()
    ex.execute("issue_refund", {"invoice_number": "INV-2026-00001", "amount": 20})
    read = ex.execute("run_sql", {"sql": "SELECT SUM(amount) FROM refunds"})
    assert read["status"] == "ok" and read["rows"] == [[20.0]] and contract_problems(read) == []
    assert "snapshot" not in json.dumps(read).lower() and "read-only" not in read["notes"].lower()
    for sql in ("DELETE FROM refunds", "UPDATE invoices SET status = 'paid'", "SELECT 1; DROP TABLE refunds"):
        assert ex.execute("run_sql", {"sql": sql})["status"] == "invalid_input"
    assert ex.execute("run_sql", {"sql": "SELECT nope FROM refunds"})["status"] == "invalid_input"
    assert ex.execute("run_sql", {"sql": "SELECT 1", "limit": 5})["status"] == "invalid_input"
    assert ex.execute("run_sql", None)["status"] == "invalid_input"
    assert len(ex.writes) == 1 and ex.reads == 6  # every read with an object as arguments


def test_describe_schema_is_live_and_carries_no_row_counts(run):
    ex = run()
    full = ex.execute("describe_schema", {})
    assert full["status"] == "ok" and full["today"] == "2026-09-30" and "read_only" not in full["limits"]
    assert all("row_count" not in t for t in full["tables"])
    text = json.dumps(full).lower()
    assert "snapshot" not in text and "read-only" not in text and "as of the" not in text
    names = [t["name"] for t in full["tables"]]
    assert {"refunds", "credit_holds", "collection_cases", "reorders", "system_info"} <= set(names)
    holds = ex.execute("describe_schema", {"table": "credit_holds"})["tables"][0]
    assert next(c for c in holds["columns"] if c["name"] == "reason")["allowed_values"] == [
        "late_payment",
        "risk_review",
    ]
    assert ex.execute("describe_schema", {"table": "snapshot_info"})["status"] == "invalid_input"
    assert ex.execute("describe_schema", {"tables": "x"})["status"] == "invalid_input"


def test_results_are_identical_in_two_worlds_and_the_clock_is_frozen(run):
    other = [{"op": "update", "table": "invoices", "key": {"invoice_id": 1}, "values": {"status": "void"}}]
    calls = [
        ("describe_schema", {}),
        *((n, VALID[n]) for n in W.WRITE_TOOLS),
        ("describe_schema", {"table": "refunds"}),
    ]
    a, b = run(), run(patch=other)
    assert a.db.pre_sha256 != b.db.pre_sha256
    for name, arguments in calls:
        assert json.dumps(a.execute(name, dict(arguments))) == json.dumps(b.execute(name, dict(arguments)))
    clock = FrozenClock("m|p|en|*|neutral|act_check|r0")
    stamps = [clock.tick() for _ in range(3)]
    assert stamps[0].startswith("2026-09-30T") and stamps[0] < stamps[1] < stamps[2]
    assert FrozenClock("another unit").tick() != stamps[0]
