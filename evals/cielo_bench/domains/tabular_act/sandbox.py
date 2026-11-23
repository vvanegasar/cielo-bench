"""The per-trial database: in memory, built from the fixture's bytes and a scenario patch.

* **No write path to disk.** The fixture is read once, read-only, as bytes. Each trial calls
  ``sqlite3.connect(":memory:")`` and ``Connection.deserialize``: the connection has no file
  behind it, ``PRAGMA temp_store = MEMORY`` keeps sort spills in memory, ``ATTACH`` is capped at
  zero and denied by the authorizer, and no write tool takes SQL text.
* **One authorizer, three modes.** Every statement on a trial connection is compiled under a
  :class:`Guard` (the statement cache is off, so none escapes it). In ``read`` mode only reads run.
  In ``patch`` mode the patch's tables may be written. In a tool's mode only that tool's table and
  columns may be written (``Grant``). The guard also records every table a statement may write,
  which keeps the content hash exact and cheap.
* **Structured patches.** A patch is a list of row operations, ``{op, table, key, values}``, each
  run with bound parameters. ``patch_sha256`` is the hash of its canonical JSON.
* **Content hash.** SHA-256 over the DDL and one hash per table (its rows in primary-key order),
  so a table that no statement wrote keeps the hash computed once for the fixture.
* **Reads run on a copy.** ``read_copy`` serializes the trial database into a second in-memory
  connection, guarded as read-only. The agent reads its own writes; a statement that slipped
  through every guard would change only the throwaway copy.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..tabular.sqlguard import Limits, guard
from . import ops_schema as S

PATCH_OPS = ("insert", "update", "delete")
SIDECARS = ("-wal", "-shm", "-journal")
_READ_ACTIONS = frozenset(
    {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
)
_WRITE_ACTIONS = {sqlite3.SQLITE_INSERT: "insert", sqlite3.SQLITE_UPDATE: "update", sqlite3.SQLITE_DELETE: "delete"}
DENIED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"})


class SandboxError(RuntimeError):
    """The sandbox refused to build or change a trial database (a harness error, never the agent's)."""


class PatchError(SandboxError):
    pass


# ----------------------------------------------------------------------------- the fixture
def journal_mode_ok(data: bytes) -> bool:
    """Bytes 18 and 19 of the header are 1 in rollback-journal mode (an in-memory database cannot use WAL)."""
    return len(data) >= 100 and data[18] == 1 and data[19] == 1


class BaseFixture:
    """The fixture's bytes, read once, and the hash of each of its tables (computed once)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if not journal_mode_ok(self.data):
            raise SandboxError(f"{self.path.name} is not in rollback-journal mode (header bytes 18-19)")
        self._lock = threading.Lock()
        self._hashes: dict[str, str] | None = None

    @property
    def table_hashes(self) -> dict[str, str]:
        with self._lock:
            if self._hashes is None:
                con = open_memory(self.data)
                try:
                    self._hashes = {t.name: table_sha256(con, t.name) for t in S.TABLES}
                finally:
                    con.close()
            return dict(self._hashes)

    @property
    def content_sha256(self) -> str:
        return combine_hashes(self.table_hashes)


def sidecar_files(path: Path) -> list[Path]:
    """Journal or WAL files next to a fixture: proof that something opened it for writing."""
    return [p for p in (path.with_name(path.name + s) for s in SIDECARS) if p.exists()]


# ----------------------------------------------------------------------------- connections
def open_memory(data: bytes) -> sqlite3.Connection:
    """An in-memory database holding ``data``. No file behind it, no attached databases."""
    con = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False, cached_statements=0)
    try:
        con.deserialize(data)
        con.execute("PRAGMA temp_store = MEMORY")
        con.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    except BaseException:
        con.close()
        raise
    return con


@dataclass(frozen=True)
class Grant:
    """What one mode may write: whole tables to insert into, (table, column) pairs to update, and
    tables to delete from. Reads are always allowed."""

    insert: frozenset[str] = frozenset()
    update: frozenset[tuple[str, str]] = frozenset()
    delete: frozenset[str] = frozenset()


READ_ONLY = Grant()


@dataclass
class Guard:
    """The authorizer of a trial connection: the current grant, and every table a statement could write."""

    grant: Grant = READ_ONLY
    dirty: set[str] = field(default_factory=set)
    denied: list[str] = field(default_factory=list)

    def __call__(self, action: int, arg1: str | None, arg2: str | None, _db: str | None, _src: str | None) -> int:
        if action in _READ_ACTIONS:
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in DENIED_FUNCTIONS:
                return self._deny(action, arg1, arg2)
            return sqlite3.SQLITE_OK
        kind = _WRITE_ACTIONS.get(action)
        allowed = (
            (kind == "insert" and arg1 in self.grant.insert)
            or (kind == "update" and (arg1, arg2) in self.grant.update)
            or (kind == "delete" and arg1 in self.grant.delete)
        )
        if not allowed:
            return self._deny(action, arg1, arg2)
        self.dirty.add(str(arg1))
        return sqlite3.SQLITE_OK

    def _deny(self, action: int, arg1: str | None, arg2: str | None) -> int:
        self.denied.append(f"{action}:{arg1}:{arg2}")
        return sqlite3.SQLITE_DENY


# ----------------------------------------------------------------------------- hashing
def _table_rows(con: sqlite3.Connection, name: str) -> Iterable[tuple[Any, ...]]:
    t = S.table(name)
    cols = ", ".join(c.name for c in t.columns)
    return con.execute(f"SELECT {cols} FROM {name} ORDER BY {', '.join(t.primary_key)}")


def table_sha256(con: sqlite3.Connection, name: str) -> str:
    h = hashlib.sha256()
    for row in _table_rows(con, name):
        h.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def combine_hashes(table_hashes: Mapping[str, str]) -> str:
    """Content hash: the DDL and each table's hash, in schema order."""
    h = hashlib.sha256(S.schema_ddl().encode("utf-8"))
    for t in S.TABLES:
        h.update(f"\n#{t.name} {table_hashes[t.name]}".encode())
    return h.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def patch_sha256(ops: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical(list(ops)).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------- patches
def _columns(table: str) -> set[str]:
    return {c.name for c in S.table(table).columns}


def check_op(op: Mapping[str, Any]) -> None:
    """A row operation names a known table and known columns, and its key is the table's primary key."""
    kind, table = op.get("op"), op.get("table")
    if kind not in PATCH_OPS:
        raise PatchError(f"unknown patch op {kind!r}")
    if table not in S.TABLE_NAMES or table == "system_info":
        raise PatchError(f"a patch may not touch table {table!r}")
    key, values = dict(op.get("key") or {}), dict(op.get("values") or {})
    columns = _columns(str(table))
    if set(key) != set(S.table(str(table)).primary_key):
        raise PatchError(f"{table}: the key must be the primary key {S.table(str(table)).primary_key}")
    unknown = (set(key) | set(values)) - columns
    if unknown:
        raise PatchError(f"{table}: unknown column(s) {sorted(unknown)}")
    if kind == "update" and not values:
        raise PatchError(f"{table}: an update needs values")
    if kind == "delete" and values:
        raise PatchError(f"{table}: a delete takes no values")


def patch_grant(ops: Sequence[Mapping[str, Any]]) -> Grant:
    insert, update, delete = set(), set(), set()
    for op in ops:
        if op["op"] == "insert":
            insert.add(op["table"])
        elif op["op"] == "update":
            update |= {(op["table"], c) for c in op["values"]}
        else:
            delete.add(op["table"])
    return Grant(frozenset(insert), frozenset(update), frozenset(delete))


def apply_op(con: sqlite3.Connection, op: Mapping[str, Any]) -> None:
    table, key, values = op["table"], dict(op["key"]), dict(op.get("values") or {})
    where = " AND ".join(f"{k} = ?" for k in key)
    if op["op"] == "insert":
        row = {**key, **values}
        cols = list(row)
        cur = con.execute(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [row[c] for c in cols]
        )
    elif op["op"] == "update":
        sets = ", ".join(f"{k} = ?" for k in values)
        cur = con.execute(f"UPDATE {table} SET {sets} WHERE {where}", [*values.values(), *key.values()])
    else:
        cur = con.execute(f"DELETE FROM {table} WHERE {where}", list(key.values()))
    if cur.rowcount != 1:
        raise PatchError(f"{op['op']} on {table} {key} changed {cur.rowcount} rows, expected 1")


# ----------------------------------------------------------------------------- one trial's database
class TrialDB:
    """One trial's database: the fixture plus a patch, in memory, under a :class:`Guard`."""

    def __init__(self, base: BaseFixture, patch: Sequence[Mapping[str, Any]], expected_patch_sha256: str | None = None):
        ops = [dict(op) for op in patch]
        digest = patch_sha256(ops)
        if expected_patch_sha256 is not None and digest != expected_patch_sha256:
            raise PatchError("patch_sha256 does not match the patch: refusing to apply it")
        for op in ops:
            check_op(op)
        self.base = base
        self.patch_sha256 = digest
        self.con = open_memory(base.data)
        self.guard = Guard()
        self.con.set_authorizer(self.guard)
        self._hashes = base.table_hashes
        try:
            self.guard.grant = patch_grant(ops)
            for op in ops:
                apply_op(self.con, op)
        except sqlite3.Error as exc:
            self.close()
            raise PatchError(f"the patch could not be applied: {exc}") from exc
        except BaseException:
            self.close()
            raise
        finally:
            self.guard.grant = READ_ONLY
        self.pre_sha256 = self.content_sha256()

    # ---- hashing
    def content_sha256(self) -> str:
        for name in sorted(self.guard.dirty):
            self._hashes[name] = table_sha256(self.con, name)
        self.guard.dirty.clear()
        return combine_hashes(self._hashes)

    # ---- access
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """A harness read on the trial database (read mode)."""
        self.guard.grant = READ_ONLY
        return self.con.execute(sql, list(params)).fetchall()

    def read_copy(self, limits: Limits) -> sqlite3.Connection:
        """A throwaway in-memory copy, guarded as read-only like the tabular domain's snapshot."""
        copy = open_memory(self.con.serialize())
        guard(copy, limits)
        return copy

    def close(self) -> None:
        self.con.close()


def world_db(base: BaseFixture, world: Mapping[str, Any]) -> TrialDB:
    """The database of one golden-set world, checked against its recorded hashes."""
    db = TrialDB(base, world["patch"], world.get("patch_sha256"))
    expected = world.get("pre_sha256")
    if expected is not None and db.pre_sha256 != expected:
        db.close()
        raise SandboxError("the patched database does not match the world's pre_sha256")
    return db
