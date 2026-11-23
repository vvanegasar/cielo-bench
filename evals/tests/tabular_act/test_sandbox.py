"""The per-trial in-memory database: isolation, patches, hashes, guards and read copies."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from cielo_bench.domains.tabular.sqlguard import Limits, QueryRejected, run_select
from cielo_bench.domains.tabular_act import sandbox as sb
from cielo_bench.domains.tabular_act.sandbox import (
    BaseFixture,
    Grant,
    PatchError,
    SandboxError,
    TrialDB,
    open_memory,
    patch_sha256,
    sidecar_files,
    world_db,
)

from .tiny import write_tiny

PAY = {"op": "insert", "table": "payments", "key": {"payment_id": 11},
       "values": {"invoice_id": 2, "payment_date": "2026-09-28", "amount": 60.0, "method": "card"}}  # fmt: skip
PAID = {"op": "update", "table": "invoices", "key": {"invoice_id": 2}, "values": {"status": "paid"}}


@pytest.fixture
def base(tmp_path):
    return BaseFixture(write_tiny(tmp_path / "tiny.sqlite"))


def test_the_trial_database_has_no_file_and_no_attachments(base):
    db = TrialDB(base, [])
    try:
        with pytest.raises(sqlite3.DatabaseError):  # the guard denies every pragma...
            db.con.execute("PRAGMA database_list")
        with pytest.raises(sqlite3.DatabaseError):  # ...and ATTACH, which is also capped at zero
            db.con.execute("ATTACH DATABASE ':memory:' AS other")
        assert db.con.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED) == 0
        db.con.set_authorizer(None)  # look behind the guard
        assert [row[2] for row in db.con.execute("PRAGMA database_list")] == [""]  # main is in memory, no file
        assert db.con.execute("PRAGMA temp_store").fetchone()[0] == 2  # MEMORY
    finally:
        db.close()


def test_a_fixture_in_wal_mode_is_refused(tmp_path):
    path = write_tiny(tmp_path / "wal.sqlite")
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode = WAL")
    con.close()
    with pytest.raises(SandboxError, match="rollback-journal"):
        BaseFixture(path)


def test_writes_never_reach_the_fixture_or_the_disk(base, tmp_path):
    before = base.path.read_bytes()
    listing = sorted(p.name for p in tmp_path.iterdir())
    db = TrialDB(base, [PAY, PAID])
    db.guard.grant = Grant(insert=frozenset({"refunds"}))
    db.con.execute("INSERT INTO refunds VALUES (1, 1, '2026-09-30', 10.0, 'return')")
    db.close()
    assert base.path.read_bytes() == before
    assert sidecar_files(base.path) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == listing  # no file was created anywhere


def test_patch_hash_is_checked_before_the_patch_is_applied(base):
    with pytest.raises(PatchError, match="patch_sha256"):
        TrialDB(base, [PAY], expected_patch_sha256=patch_sha256([PAID]))
    db = TrialDB(base, [PAY], expected_patch_sha256=patch_sha256([PAY]))
    assert db.patch_sha256 == patch_sha256([dict(PAY)])
    db.close()


@pytest.mark.parametrize(
    "op, message",
    [
        (
            {"op": "upsert", "table": "invoices", "key": {"invoice_id": 1}, "values": {"status": "x"}},
            "unknown patch op",
        ),
        (
            {"op": "update", "table": "system_info", "key": {"key": "business_date"}, "values": {"value": "x"}},
            "may not",
        ),
        (
            {"op": "update", "table": "invoices", "key": {"invoice_number": "x"}, "values": {"status": "x"}},
            "primary key",
        ),
        ({"op": "update", "table": "invoices", "key": {"invoice_id": 1}, "values": {"colour": "x"}}, "unknown column"),
        ({"op": "update", "table": "invoices", "key": {"invoice_id": 1}, "values": {}}, "needs values"),
        ({"op": "delete", "table": "payments", "key": {"payment_id": 10}, "values": {"amount": 1}}, "no values"),
        ({"op": "update", "table": "invoices", "key": {"invoice_id": 99}, "values": {"status": "paid"}}, "expected 1"),
        ({"op": "insert", "table": "payments", "key": {"payment_id": 10}, "values": {"invoice_id": 1}}, "could not"),
    ],
)
def test_bad_patches_are_refused(base, op, message):
    with pytest.raises(PatchError, match=message):
        TrialDB(base, [op])


def test_content_hash_is_exact_and_deterministic(base):
    empty = TrialDB(base, [])
    assert empty.pre_sha256 == base.content_sha256
    empty.close()
    a, b = TrialDB(base, [PAY, PAID]), TrialDB(base, [PAY, PAID])
    assert a.pre_sha256 == b.pre_sha256 != base.content_sha256
    # the cached per-table hashes give the same result as hashing every table again
    fresh = sb.combine_hashes({t.name: sb.table_sha256(a.con, t.name) for t in sb.S.TABLES})
    assert a.pre_sha256 == fresh
    a.guard.grant = Grant(insert=frozenset({"reorders"}))
    a.con.execute("INSERT INTO reorders VALUES (11, 1, 'Norte', 10, '2026-09-30', 'open', NULL)")
    a.guard.grant = sb.READ_ONLY
    after = a.content_sha256()
    assert after != a.pre_sha256
    assert after == sb.combine_hashes({t.name: sb.table_sha256(a.con, t.name) for t in sb.S.TABLES})
    a.close()
    b.close()


def test_the_guard_denies_every_write_outside_the_grant(base):
    db = TrialDB(base, [])
    try:
        db.guard.grant = Grant(insert=frozenset({"refunds"}))
        for sql in (
            "UPDATE invoices SET status = 'paid' WHERE invoice_id = 2",
            "DELETE FROM payments",
            "INSERT INTO payments VALUES (99, 2, '2026-09-30', 60.0, 'cash')",
            "DROP TABLE refunds",
            "CREATE TABLE x (a)",
            "PRAGMA writable_schema = ON",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                db.con.execute(sql)
        db.guard.grant = sb.READ_ONLY
        assert db.query("SELECT status FROM invoices WHERE invoice_id = 2") == [("overdue",)]
        assert db.guard.denied  # every refusal is recorded
        assert db.content_sha256() == db.pre_sha256
    finally:
        db.close()


def test_reads_run_on_a_throwaway_copy(base):
    db = TrialDB(base, [])
    limits = Limits()
    copy = db.read_copy(limits)
    try:
        assert run_select(copy, "SELECT COUNT(*) FROM invoices", limits).rows == [[3]]
        with pytest.raises((QueryRejected, sqlite3.DatabaseError)):
            run_select(copy, "DELETE FROM invoices", limits)
        copy.set_authorizer(None)  # force a write past every guard: it can only touch the copy
        copy.execute("PRAGMA query_only = OFF")
        copy.execute("DELETE FROM invoices")
        assert db.query("SELECT COUNT(*) FROM invoices") == [(3,)]
        assert db.content_sha256() == db.pre_sha256
    finally:
        copy.close()
        db.close()


def test_parallel_trials_never_see_each_others_rows(base):
    seen: dict[int, int] = {}

    def trial(i: int) -> None:
        db = TrialDB(base, [])
        db.guard.grant = Grant(insert=frozenset({"reorders"}))
        for k in range(20):
            db.con.execute(
                "INSERT INTO reorders VALUES (?, 1, 'Sur', 5, '2026-09-30', 'open', NULL)", (1000 * (i + 1) + k,)
            )
        db.guard.grant = sb.READ_ONLY
        seen[i] = db.query("SELECT COUNT(*) FROM reorders")[0][0]
        db.close()

    threads = [threading.Thread(target=trial, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {i: 21 for i in range(4)}  # one row of the fixture plus its own twenty


def test_world_db_checks_the_recorded_pre_hash(base):
    good = TrialDB(base, [PAY])
    world = {"patch": [PAY], "patch_sha256": good.patch_sha256, "pre_sha256": good.pre_sha256}
    good.close()
    world_db(base, world).close()
    with pytest.raises(SandboxError, match="pre_sha256"):
        world_db(base, {**world, "pre_sha256": "0" * 64})


def test_sidecar_files_are_detected(base):
    side = base.path.with_name(base.path.name + "-journal")
    side.write_bytes(b"")
    assert sidecar_files(base.path) == [side]


def test_open_memory_releases_the_connection_on_bad_bytes():
    with pytest.raises(sqlite3.DatabaseError):
        open_memory(b"not a database" * 10).execute("SELECT * FROM sqlite_master")
