"""Read-only SQL execution with layered guards.

A query has to pass every layer before a single row is returned:

1. **Static validation**: one statement, at most ``MAX_SQL_CHARS`` characters, starting with
   ``SELECT`` or ``WITH``, with no write, schema, transaction, ``ATTACH`` or ``PRAGMA``
   keyword outside string literals and comments (``replace(...)`` the string function is
   allowed; ``REPLACE INTO`` is not).
2. **Read-only connection**: the file is opened with ``mode=ro`` and ``PRAGMA query_only``.
3. **Authorizer**: SQLite asks permission for every action while compiling the statement;
   only reading tables and columns, ``SELECT``, recursive CTEs and ordinary functions are
   allowed. Pragmas (including ``pragma_*`` table functions), ``ATTACH`` and every write are
   denied, so even a statement that slipped through layer 1 cannot run.
4. **Resource limits**: string/blob length, SQL length and attached databases are capped
   with ``sqlite3.Connection.setlimit``; a deterministic work budget (SQLite virtual-machine
   steps, counted by a progress handler) plus a wall-clock backstop stop runaway queries;
   at most ``MAX_ROWS`` rows and ``MAX_RESULT_CHARS`` characters are returned, and the result
   says when it was truncated.

The step budget is deterministic for a given SQLite version, so whether a query is cut off
does not depend on machine load (the wall-clock backstop is far above it).
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_SQL_CHARS = 10_000
MAX_ROWS = 200
MAX_CELL_CHARS = 500
MAX_RESULT_CHARS = 60_000
PROGRESS_INTERVAL = 1_000  # VM instructions between progress-handler calls
STEP_BUDGET = 100_000  # progress-handler calls (about 100 million VM instructions)
WALL_LIMIT_S = 10.0  # backstop only; the step budget is the real limit
FLOAT_DECIMALS = 6

ALLOWED_FIRST = ("select", "with")
FORBIDDEN_WORDS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "replace",
        "upsert",
        "merge",
        "create",
        "drop",
        "alter",
        "truncate",
        "rename",
        "attach",
        "detach",
        "pragma",
        "vacuum",
        "reindex",
        "analyze",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "release",
        "transaction",
        "grant",
        "revoke",
        "load_extension",
    }
)
DENIED_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"})
_ALLOWED_ACTIONS = frozenset(
    {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
)

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class QueryRejected(ValueError):
    """The query is not allowed (static validation or the authorizer). Status invalid_input."""


class QueryFailed(ValueError):
    """The query is allowed but SQLite rejected it (syntax, unknown column...). invalid_input."""


class QueryTooExpensive(ValueError):
    """The query used up the work budget. invalid_input (the query should aggregate or filter)."""


class DatabaseUnavailable(RuntimeError):
    """The database could not answer at all. Status source_unavailable; no values."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def strip_sql(sql: str) -> str:
    """The SQL with comments removed and every literal or quoted identifier blanked.

    String literals become ``''`` and quoted identifiers ``""``, so keywords inside them
    (``WHERE name = 'Drop Shop'``) are not mistaken for statements.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j
            out.append(" ")
        elif ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j < 0 else j + 2
            out.append(" ")
        elif ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:  # doubled quote = escaped quote
                        j += 2
                        continue
                    break
                j += 1
            out.append("''" if ch == "'" else '""')
            i = j + 1
        elif ch == "[":
            j = sql.find("]", i + 1)
            out.append('""')
            i = n if j < 0 else j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def validate(sql: Any) -> str:
    """Static checks. Returns the SQL to run (trailing semicolons removed) or raises."""
    if not isinstance(sql, str) or not sql.strip():
        raise QueryRejected("sql must be a non-empty string")
    if len(sql) > MAX_SQL_CHARS:
        raise QueryRejected(f"sql is longer than {MAX_SQL_CHARS} characters")
    if "\x00" in sql:
        raise QueryRejected("sql contains a NUL character")
    stripped = strip_sql(sql).strip()
    while stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    if ";" in stripped:
        raise QueryRejected("only one statement is allowed")
    words = [m.group(0) for m in _WORD.finditer(stripped)]
    if not words or words[0].lower() not in ALLOWED_FIRST:
        raise QueryRejected("only a single read-only SELECT statement (optionally starting with WITH) is allowed")
    for m in _WORD.finditer(stripped):
        word = m.group(0).lower()
        if word.startswith("pragma"):
            raise QueryRejected("PRAGMA is not allowed")
        if word in FORBIDDEN_WORDS:
            rest = stripped[m.end() :].lstrip()
            if word == "replace" and rest.startswith("("):
                continue  # the replace(x, y, z) string function
            raise QueryRejected(f"{word.upper()} is not allowed: the database is read-only")
    body = sql.rstrip()
    while body.endswith(";"):
        body = body[:-1].rstrip()
    return body


def _authorizer(deny_reads: bool) -> Callable[..., int]:
    def check(action: int, arg1: str | None, arg2: str | None, _db: str | None, _src: str | None) -> int:
        if action == sqlite3.SQLITE_READ and deny_reads:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in DENIED_FUNCTIONS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY

    return check


@dataclass(frozen=True)
class Limits:
    step_budget: int = STEP_BUDGET
    max_rows: int = MAX_ROWS
    max_chars: int | None = MAX_RESULT_CHARS  # None: no size cap (internal build-time queries)
    deny_reads: bool = False  # the permission_denied fault profile

    @property
    def interval(self) -> int:
        # With no budget at all (the timeout fault profile) the handler runs on every VM
        # instruction, so even a trivial statement is interrupted.
        return PROGRESS_INTERVAL if self.step_budget > 0 else 1


def connect(path: Path, limits: Limits) -> sqlite3.Connection:
    """A read-only connection with the authorizer, limits and work budget installed."""
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False)
    except sqlite3.Error as exc:
        raise DatabaseUnavailable("connection_failed", str(exc)) from exc
    try:
        con.execute("PRAGMA query_only = ON")
        con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1_000_000)
        con.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_CHARS + 100)
        con.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        con.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 50)
    except sqlite3.DatabaseError as exc:  # for example "file is not a database"
        con.close()
        raise DatabaseUnavailable("database_error", str(exc)) from exc
    con.set_authorizer(_authorizer(limits.deny_reads))
    return con


def _install_budget(con: sqlite3.Connection, limits: Limits) -> dict[str, Any]:
    state = {"calls": 0, "deadline": time.monotonic() + WALL_LIMIT_S, "exhausted": False}

    def progress() -> int:
        state["calls"] += 1
        if state["calls"] > limits.step_budget or time.monotonic() > state["deadline"]:
            state["exhausted"] = True
            return 1
        return 0

    con.set_progress_handler(progress, limits.interval)
    return state


def _cell(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        rounded = round(value, FLOAT_DECIMALS)
        return 0.0 if rounded == 0 else rounded
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<blob {len(bytes(value))} bytes>"
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value


_UNAVAILABLE_MARKERS = (
    "unable to open",
    "disk i/o",
    "not a database",
    "malformed",
    "locked",
    "busy",
    "out of memory",
    "corrupt",
)


def _classify(exc: sqlite3.Error, state: dict[str, Any], limits: Limits) -> Exception:
    """Map a SQLite error to the tool contract: the model's fault, or the source's."""
    message = str(exc)
    low = message.lower()
    if state.get("exhausted") or low == "interrupted":
        if limits.step_budget <= 0:
            return DatabaseUnavailable("timeout", "statement timeout")
        return QueryTooExpensive("the query exceeded the work limit; filter or aggregate in SQL instead")
    if "not authorized" in low or "prohibited" in low:
        if limits.deny_reads:
            return DatabaseUnavailable("permission_denied", "the database user may not read these tables")
        return QueryRejected("the statement is not allowed: the database is read-only and only SELECT may run")
    if "readonly" in low or "read-only" in low:
        return QueryRejected("the database is read-only")
    if any(marker in low for marker in _UNAVAILABLE_MARKERS):
        return DatabaseUnavailable("database_error", message)
    if isinstance(exc, sqlite3.ProgrammingError):  # for example two statements at once
        return QueryRejected(message)
    if isinstance(exc, (sqlite3.OperationalError, sqlite3.DataError, sqlite3.IntegrityError, sqlite3.Warning)):
        return QueryFailed(message)  # syntax errors, unknown tables or columns, misuse of functions
    return DatabaseUnavailable("database_error", message)


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool

    @property
    def row_count(self) -> int:
        return len(self.rows)


def run_select(con: sqlite3.Connection, sql: str, limits: Limits) -> QueryResult:
    """Run one validated SELECT on a guarded connection."""
    state = _install_budget(con, limits)
    try:
        cursor = con.execute(sql)
        columns = [d[0] for d in (cursor.description or [])]
        fetched = cursor.fetchmany(limits.max_rows + 1)
    except sqlite3.Error as exc:
        raise _classify(exc, state, limits) from exc
    finally:
        con.set_progress_handler(None, 0)
    truncated = len(fetched) > limits.max_rows
    rows = [[_cell(v) for v in row] for row in fetched[: limits.max_rows]]
    if limits.max_chars is None:
        return QueryResult(columns=columns, rows=rows, truncated=truncated)
    size = len(json.dumps(rows, ensure_ascii=False, default=str))
    while rows and size > limits.max_chars:
        drop = max(1, len(rows) // 10)
        rows = rows[:-drop]
        truncated = True
        size = len(json.dumps(rows, ensure_ascii=False, default=str))
    return QueryResult(columns=columns, rows=rows, truncated=truncated)
