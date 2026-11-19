"""The two tools of the tabular domain and their executor.

* ``describe_schema``: tables, columns (type, meaning, allowed values), keys, row counts and
  the conventions of the snapshot.
* ``run_sql``: one read-only SELECT on the snapshot (guards in ``sqlguard``).

Every result is a JSON object with ``status`` in ``ok | invalid_input | source_unavailable |
out_of_scope``. A successful result carries ``sources[]``. A failure carries no values at
all: only ``status``, ``source``, ``reason`` and ``message`` (or ``status`` and ``message``).

Before answering, both tools read the snapshot stamp (``snapshot_info.as_of_date``) from the
database itself; a database without it is treated as empty and reported as unavailable.

Fault profiles make the database fail for real, each through its own SQLite error path:

==================== ========================================================= ===================
profile              what happens                                              reason
==================== ========================================================= ===================
``down``             the database file cannot be opened (nothing at the path)  ``connection_failed``
``error``            the file is not a valid database (corrupted)              ``database_error``
``empty``            the database opens but holds no data (schema only)        ``empty_result``
``timeout``          every statement exceeds a zero work budget                ``timeout``
``permission_denied`` the authorizer denies every read                         ``permission_denied``
==================== ========================================================= ===================

Under every profile both tools return ``source_unavailable`` (valid arguments) or
``invalid_input`` (invalid arguments, checked first); never values.
"""

from __future__ import annotations

import functools
import sqlite3
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schema import CONVENTIONS, CURRENCY, DB_VERSION, TABLE_NAMES, TABLES, schema_ddl
from .sqlguard import (
    MAX_ROWS,
    MAX_SQL_CHARS,
    DatabaseUnavailable,
    Limits,
    QueryFailed,
    QueryRejected,
    QueryTooExpensive,
    connect,
    run_select,
    validate,
)

# The citation names the database the way the company would, not the benchmark: a model that
# reads "benchmark" in a tool result may behave as if it were being tested. The version and
# the content hash in every citation still identify the exact snapshot.
SOURCE = f"company database {DB_VERSION} (SQLite, read-only snapshot)"
CITATION_KEYS = ("service", "query", "retrieved_at_utc", "database", "snapshot_as_of", "content_sha256")
FAULT_PROFILES = ("down", "error", "empty", "timeout", "permission_denied")
FAILURE_KEYS = frozenset({"status", "source", "reason", "message"})

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "describe_schema",
        "description": (
            "Describe the company database: its tables, their columns (type, meaning and allowed "
            "values of coded columns), primary and foreign keys, row counts and the conventions of the "
            "data (snapshot date, currency, date format). Read-only. Call it before writing SQL. If the "
            "database cannot be reached, the result has status 'source_unavailable' and contains no "
            "values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "enum": list(TABLE_NAMES),
                    "description": "Optional: describe only this table.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Run one read-only SQL query (SQLite dialect) on the company database snapshot and return "
            "the columns and rows. Only a single SELECT statement is allowed (it may start with WITH); "
            "anything that would change the database or its settings (INSERT, UPDATE, DELETE, CREATE, "
            f"DROP, ALTER, ATTACH, PRAGMA, ...) is rejected. At most {MAX_ROWS} rows are returned and the "
            "result says when it was truncated, so aggregate in SQL instead of listing rows. Dates are ISO "
            "text 'YYYY-MM-DD'. Amounts are US dollars excluding taxes. If the database cannot be reached, "
            "the result has status 'source_unavailable' and contains no values."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": f"One SQLite SELECT statement (at most {MAX_SQL_CHARS} characters).",
                },
            },
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
]


def _invalid(message: str) -> dict[str, Any]:
    return {"status": "invalid_input", "message": message}


def unavailable(exc: DatabaseUnavailable) -> dict[str, Any]:
    return {
        "status": "source_unavailable",
        "source": SOURCE,
        "reason": exc.reason,
        "message": f"The {SOURCE} could not provide data ({exc.reason}). No values are returned.",
    }


@functools.lru_cache(maxsize=1)
def _fault_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="cielo-bench-tabular-faults-"))


@functools.lru_cache(maxsize=1)
def empty_replica() -> Path:
    """A database with the full schema and no rows (the ``empty`` fault profile)."""
    path = _fault_dir() / "empty-replica.sqlite"
    con = sqlite3.connect(path)
    try:
        con.executescript(schema_ddl())
    finally:
        con.close()
    return path


@functools.lru_cache(maxsize=1)
def corrupted_file() -> Path:
    """A file that is not a SQLite database (the ``error`` fault profile)."""
    path = _fault_dir() / "corrupted.sqlite"
    path.write_bytes(b"cielo-bench: simulated corrupted database file\n" * 64)
    return path


class TabularToolExecutor:
    """Runs ``describe_schema`` and ``run_sql`` against the snapshot (or a simulated fault)."""

    def __init__(
        self,
        db_path: Path,
        *,
        content_sha256: str,
        fault_profile: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        if fault_profile and fault_profile not in FAULT_PROFILES:
            raise ValueError(f"unknown fault profile {fault_profile!r}; choose from {FAULT_PROFILES}")
        self.db_path = db_path
        self.content_sha256 = content_sha256
        self.fault_profile = fault_profile or None
        self.clock = clock or (lambda: datetime.now(UTC))
        self.live_requests = 0  # no network source: the snapshot is a local file
        self.queries_executed = 0
        self.limits = Limits(
            step_budget=0 if self.fault_profile == "timeout" else Limits().step_budget,
            deny_reads=self.fault_profile == "permission_denied",
        )

    # ------------------------------------------------------------------ plumbing
    def _target(self) -> Path:
        if self.fault_profile == "down":
            return self.db_path.with_name(self.db_path.name + ".unreachable") / "database.sqlite"
        if self.fault_profile == "error":
            return corrupted_file()
        if self.fault_profile == "empty":
            return empty_replica()
        return self.db_path

    def _open(self) -> tuple[sqlite3.Connection, str]:
        """A guarded connection and the snapshot date read from the database itself."""
        con = connect(self._target(), self.limits)
        try:
            stamp = run_select(con, "SELECT value FROM snapshot_info WHERE key = 'as_of_date'", self.limits)
        except QueryFailed as exc:  # for example the table is missing
            con.close()
            raise DatabaseUnavailable("database_error", str(exc)) from exc
        except BaseException:
            con.close()
            raise
        if not stamp.rows:
            con.close()
            raise DatabaseUnavailable("empty_result", "the database returned no data")
        return con, str(stamp.rows[0][0])

    def _sources(self, as_of: str, query: str) -> list[dict[str, Any]]:
        """One citation per result: service, the query that ran, when (UTC) and which snapshot."""
        retrieved = self.clock().astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        return [
            {
                "service": SOURCE,
                "query": query,
                "retrieved_at_utc": retrieved,
                "database": self.db_path.name,
                "snapshot_as_of": as_of,
                "content_sha256": self.content_sha256,
            }
        ]

    # ------------------------------------------------------------------ tools
    def execute(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        if name not in ("describe_schema", "run_sql"):
            return {"status": "out_of_scope", "message": f"unknown tool {name!r}"}
        if not isinstance(arguments, dict):
            return _invalid("arguments must be a JSON object")
        if name == "describe_schema":
            return self._describe_schema(arguments)
        return self._run_sql(arguments)

    def _describe_schema(self, arguments: dict[str, Any]) -> dict[str, Any]:
        unknown = set(arguments) - {"table"}
        if unknown:
            return _invalid(f"unknown argument(s): {sorted(unknown)}")
        wanted = arguments.get("table")
        if wanted is not None and wanted not in TABLE_NAMES:
            return _invalid(f"table must be one of {list(TABLE_NAMES)}")
        try:
            con, as_of = self._open()
        except DatabaseUnavailable as exc:
            return unavailable(exc)
        try:
            tables = []
            for table in TABLES:
                if wanted is not None and table.name != wanted:
                    continue
                count = run_select(con, f"SELECT COUNT(*) FROM {table.name}", self.limits).rows[0][0]
                tables.append(
                    {
                        "name": table.name,
                        "description": table.description,
                        "row_count": count,
                        "primary_key": list(table.primary_key),
                        "columns": [
                            {
                                k: v
                                for k, v in {
                                    "name": c.name,
                                    "type": c.type,
                                    "nullable": c.nullable,
                                    "description": c.description,
                                    "allowed_values": list(c.values) if c.values else None,
                                    "references": c.references,
                                }.items()
                                if v is not None
                            }
                            for c in table.columns
                        ],
                    }
                )
        except DatabaseUnavailable as exc:
            return unavailable(exc)
        except (QueryFailed, QueryRejected, QueryTooExpensive) as exc:
            return unavailable(DatabaseUnavailable("database_error", str(exc)))
        finally:
            con.close()
        self.queries_executed += 1
        return {
            "status": "ok",
            "database": self.db_path.name,
            "dialect": "SQLite",
            "snapshot_as_of": as_of,
            "currency": CURRENCY,
            "conventions": list(CONVENTIONS),
            "limits": {"max_rows": MAX_ROWS, "max_sql_chars": MAX_SQL_CHARS, "read_only": True},
            "tables": tables,
            "sources": self._sources(as_of, f"describe_schema(table={wanted})" if wanted else "describe_schema"),
        }

    def _run_sql(self, arguments: dict[str, Any]) -> dict[str, Any]:
        unknown = set(arguments) - {"sql"}
        if unknown:
            return _invalid(f"unknown argument(s): {sorted(unknown)}")
        try:
            sql = validate(arguments.get("sql"))
        except QueryRejected as exc:
            return _invalid(str(exc))
        try:
            con, as_of = self._open()
        except DatabaseUnavailable as exc:
            return unavailable(exc)
        try:
            result = run_select(con, sql, self.limits)
        except DatabaseUnavailable as exc:
            return unavailable(exc)
        except (QueryRejected, QueryFailed, QueryTooExpensive) as exc:
            return _invalid(f"query failed: {exc}")
        finally:
            con.close()
        self.queries_executed += 1
        return {
            "status": "ok",
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "notes": f"Read-only snapshot as of {as_of}. Amounts in {CURRENCY}, excluding taxes.",
            "sources": self._sources(as_of, sql),
        }
