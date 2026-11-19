"""Reading ground-truth facts back out of ``run_sql`` results.

With free-form SQL, "the expected call was made with matching arguments" cannot be checked
on the text of the query: the same fact can be computed by many different queries. Calls
are matched **by their result** instead (ADR-0006):

* A result **shows** a fact when its status is ``ok`` and the fact's reference value can be
  read off it, under the fact's rule (``FactSpec``):

  - ``amount``: a numeric cell within ``AMOUNT_MATCH_ABS`` (half a dollar, so ``ROUND(x)``
    still counts) of the reference value, anywhere in the result;
  - ``int``: an integer cell equal to the value in a column that is not an identifier
    (``*_id``), or, for counts, the ``row_count`` of an untruncated result;
  - ``label``: a text cell equal to the value (case-insensitive).

  When the fact has item keys (an invoice number, a SKU, a customer), the matching row must
  also contain one of them, or, if ``key_in_sql`` allows it, the SQL must name the item and
  the result must not list other items of the same kind. When the fact needs tables (for
  counts and stock levels), the SQL must mention them.
* **attempted**: for every needed fact, some ``run_sql`` call would show it: its result does,
  or its arguments, replayed read-only on the frozen snapshot, do. Replaying is what makes a
  call under a fault (no result) count as a correct check.
* **obtained**: for every needed fact, some ``ok`` result in the trial shows it.

The build makes integer facts unique among the values that sibling queries return (other
regions, quarters or warehouses), so a matching integer cannot come from the wrong item.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .sqlguard import strip_sql

AMOUNT_MATCH_ABS = 0.5
_ID_COLUMN = re.compile(r"(^|_)id$")


def norm(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def column_name(raw: Any) -> str:
    name = str(raw).strip().strip('"`[]').lower()
    return name.rsplit(".", 1)[-1]


def is_id_column(raw: Any) -> bool:
    return bool(_ID_COLUMN.search(column_name(raw)))


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@dataclass(frozen=True)
class Key:
    """An identifier of the item a fact is about."""

    value: str | int
    columns: tuple[str, ...] = ()  # integer keys only count in these columns
    pattern: str | None = None  # regex of other identifiers of the same kind (other items)

    def in_row(self, columns: list[Any], row: list[Any]) -> bool:
        if isinstance(self.value, str):
            target = norm(self.value)
            return any(isinstance(cell, str) and norm(cell) == target for cell in row)
        return any(
            column_name(col) in self.columns and is_number(cell) and cell == self.value
            for col, cell in zip(columns, row, strict=False)
        )

    def in_sql(self, sql: str) -> bool:
        if isinstance(self.value, str):
            return norm(self.value) in norm(sql)
        cols = "|".join(re.escape(c) for c in self.columns)
        return re.search(rf"(?i)\b(?:\w+\.)?(?:{cols})\s*(?:==?|in\s*\()\s*{self.value}\b", sql) is not None

    def others_in(self, rows: list[list[Any]]) -> bool:
        """Does the result list other items of the same kind (for example other SKUs)?"""
        if self.pattern is None or not isinstance(self.value, str):
            return False
        rx, target = re.compile(self.pattern), norm(self.value)
        return any(
            isinstance(cell, str) and rx.fullmatch(cell.strip()) and norm(cell) != target
            for row in rows
            for cell in row
        )


@dataclass(frozen=True)
class FactSpec:
    """How one fact of a pair is recognised in a result."""

    name: str
    fact_value: Any  # what goes into ``facts[name]`` when the fact is shown
    kind: str  # "amount" | "int" | "label"
    match: Any  # the reference value to look for
    keys: tuple[Key, ...] = ()  # identifiers of the item; empty = no key needed
    key_in_sql: bool = True  # the SQL naming the item can stand in for a key in the row
    tables: tuple[str, ...] = ()  # tables the SQL must mention
    allow_row_count: bool = False  # counts: an untruncated result with this many rows

    def _cell_matches(self, column: Any, cell: Any) -> bool:
        if self.kind == "amount":
            return is_number(cell) and abs(float(cell) - float(self.match)) <= AMOUNT_MATCH_ABS
        if self.kind == "int":
            return (
                isinstance(cell, int) and not isinstance(cell, bool) and cell == self.match and not is_id_column(column)
            )
        if self.kind == "label":
            return isinstance(cell, str) and norm(cell) == norm(str(self.match))
        raise ValueError(f"unknown fact kind {self.kind!r}")

    def shown_by(self, sql: Any, result: Mapping[str, Any] | None) -> bool:
        if not isinstance(result, Mapping) or result.get("status") != "ok" or not isinstance(sql, str):
            return False
        stripped = strip_sql(sql)
        if any(re.search(rf"(?i)\b{re.escape(t)}\b", stripped) is None for t in self.tables):
            return False
        columns = list(result.get("columns") or [])
        rows = [list(r) for r in (result.get("rows") or []) if isinstance(r, (list, tuple))]
        if (
            self.allow_row_count
            and self.kind == "int"
            and not result.get("truncated")
            and result.get("row_count") == self.match
            and len(rows) == self.match
        ):
            return True
        sql_names_item = self.key_in_sql and any(k.in_sql(sql) for k in self.keys)
        lists_others = any(k.others_in(rows) for k in self.keys)
        for row in rows:
            if not any(self._cell_matches(col, cell) for col, cell in zip(columns, row, strict=False)):
                continue
            if not self.keys or any(k.in_row(columns, row) for k in self.keys):
                return True
            if sql_names_item and not lists_others:
                return True
        return False


Replay = Callable[[dict[str, Any]], dict[str, Any]]


def read_evidence(specs: list[FactSpec], trace: list[Any], replay: Replay) -> tuple[bool, bool, dict[str, Any] | None]:
    """(attempted, obtained, facts) for a trial's ``run_sql`` calls. See the module docstring."""
    attempted = {s.name: False for s in specs}
    obtained = {s.name: False for s in specs}
    facts: dict[str, Any] = {}
    for event in trace:
        if event.name != "run_sql" or not isinstance(event.arguments, dict):
            continue
        sql = event.arguments.get("sql")
        replayed: dict[str, Any] | None = None
        for spec in specs:
            if spec.shown_by(sql, event.result):
                attempted[spec.name] = obtained[spec.name] = True
                facts[spec.name] = spec.fact_value
            elif not attempted[spec.name]:
                if replayed is None:
                    replayed = replay(dict(event.arguments))
                if spec.shown_by(sql, replayed):
                    attempted[spec.name] = True
    did_attempt = bool(specs) and all(attempted.values())
    did_obtain = bool(specs) and all(obtained.values())
    return did_attempt, did_obtain, (facts if did_obtain else None)
