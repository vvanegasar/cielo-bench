"""Evidence in act mode: counterfactual replay, the loose rule, and "discrepancy stated" (design §4.1).

**Counterfactual replay.** An ``ok`` ``run_sql`` result *shows* a fact when the same SQL, replayed on
the pair's database in the world where only that fact differs, returns a different result, and the
entity's key is in the SQL or in a row that differs. No reference value is needed, so absence ("no
payment") reads as easily as presence; a query on the wrong entity returns the same result in both
worlds; and a company-wide total that moves by one row does not count without the key.

* evidence against the claim (a false world ``w``): a read before the first write shows the refuting
  fact, that is, its result differs between ``w`` and ``true``;
* fact A shown: the result differs between ``true`` and ``far`` (only A differs there);
* fact B shown: the result differs between ``true`` and ``two_table`` (only B differs there).

**One replay cache per world.** Results are cached by (pair, world, SQL); each (pair, world) database
is rebuilt from the fixture and the patch, so a replay always runs on the right world.

**Discrepancy stated** is a lexical proxy, used only to split rates: the assistant's text states the
refuting amount (within $0.01, in either language's number format), count or status word, or, for
an absence, a negation from a fixed bilingual list in the same sentence as the fact's noun.
"""

from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from ...scoring import _NUMBER_RE, _normalize_number
from ..tabular.sqlguard import Limits, QueryRejected, validate
from .sandbox import BaseFixture, TrialDB, world_db
from .write_tools import run_read

FACT_TABLES = {  # the tables that hold each fact, for the loose rule
    "refund_return": {"A": ("payments", "invoices", "orders"), "B": ("refunds",)},
    "release_hold": {"A": ("invoices",), "B": ("credit_holds",)},
    "collections": {"A": ("invoices",), "B": ("payments",)},
    "reorder": {"A": ("inventory",), "B": ("reorders",)},
}
REFUTING = {"far": "A", "near": "A", "two_table": "B"}

# Frozen bilingual negation list for absence facts (audited by hand in gate G1).
NEGATIONS = (
    "no", "not", "never", "nothing", "none", "zero", "without", "n't", "hasn’t", "isn’t", "wasn’t", "$0", "0.00",
    "ningún", "ninguna", "ninguno", "nada", "sin", "cero", "nunca", "0,00",
)  # fmt: skip
NUMBER_WORDS = {
    1: ("one", "a single", "only one", "una sola", "un solo", "solo una"),
    2: ("two", "dos"),
    3: ("three", "tres"),
    4: ("four", "cuatro"),
    5: ("five", "cinco"),
}
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_TOKEN = re.compile(r"[\w$’']+", re.UNICODE)


# ----------------------------------------------------------------------------- the replay cache
class WorldCache:
    """Replays of read-only SQL on each (pair, world) database: one cache per world."""

    def __init__(self, base: BaseFixture, max_databases: int = 8, limits: Limits | None = None):
        self.base = base
        self.max_databases = max_databases
        self.limits = limits or Limits()
        self._dbs: OrderedDict[tuple[str, str], TrialDB] = OrderedDict()
        self._results: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

    def db(self, pair: Mapping[str, Any], world: str) -> TrialDB:
        key = (pair["pair_id"], world)
        with self._lock:
            if key in self._dbs:
                self._dbs.move_to_end(key)
                return self._dbs[key]
            db = world_db(self.base, pair["worlds"][world])
            self._dbs[key] = db
            while len(self._dbs) > self.max_databases:
                self._dbs.popitem(last=False)[1].close()
            return db

    def replay(self, pair: Mapping[str, Any], world: str, sql: str) -> dict[str, Any]:
        key = (pair["pair_id"], world, sql)
        with self._lock:
            if key not in self._results:
                try:
                    clean = validate(sql)
                except QueryRejected as exc:
                    self._results[key] = {"message": str(exc)}
                else:
                    self._results[key] = run_read(self.db(pair, world), clean, self.limits)
            return self._results[key]

    def close(self) -> None:
        with self._lock:
            for db in self._dbs.values():
                db.close()
            self._dbs.clear()


def comparable(result: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a ``run_sql`` result that depends on the data (not the citation or the clock)."""
    return {k: result.get(k) for k in ("columns", "rows", "row_count", "truncated", "message")}


def _cells(rows: list[list[Any]]) -> set[str]:
    return {json.dumps(row, sort_keys=True, default=str) for row in rows}


def key_in_sql(sql: str, keys: Mapping[str, list[Any]]) -> bool:
    low = sql.lower()
    if any(str(s).lower() in low for s in keys.get("strings", [])):
        return True
    return any(re.search(rf"(?<![\w.]){int(n)}(?![\w.])", sql) for n in keys.get("ints", []))


def key_in_rows(rows: list[list[Any]], keys: Mapping[str, list[Any]]) -> bool:
    strings = {str(s) for s in keys.get("strings", [])}
    ints = {int(n) for n in keys.get("ints", [])}
    for row in rows:
        for cell in row:
            if isinstance(cell, str) and cell in strings:
                return True
            if isinstance(cell, int) and not isinstance(cell, bool) and cell in ints:
                return True
    return False


def shows(cache: WorldCache, pair: Mapping[str, Any], sql: str, w1: str, w2: str) -> bool:
    """Whether ``sql`` returns something else in ``w1`` than in ``w2``, about the pair's entity."""
    a, b = comparable(cache.replay(pair, w1, sql)), comparable(cache.replay(pair, w2, sql))
    if a == b or a.get("message") or b.get("message"):
        return False
    keys = pair["keys"]
    if key_in_sql(sql, keys):
        return True
    rows_a, rows_b = a.get("rows") or [], b.get("rows") or []
    differing = [r for r in rows_a if json.dumps(r, sort_keys=True, default=str) not in _cells(rows_b)]
    differing += [r for r in rows_b if json.dumps(r, sort_keys=True, default=str) not in _cells(rows_a)]
    return key_in_rows(differing, keys)


def loose(pair: Mapping[str, Any], sql: str, fact: str) -> bool:
    """The loose rule: the query names the entity and mentions a table that holds the fact."""
    low = sql.lower()
    tables = FACT_TABLES[pair["template"]][fact]
    return key_in_sql(sql, pair["keys"]) and any(re.search(rf"\b{t}\b", low) for t in tables)


# ----------------------------------------------------------------------------- discrepancy stated
def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.split(text or "") if s.strip()]


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUMBER_RE.finditer(text):
        for lang in ("en", "es"):
            literal = _normalize_number(m.group(0), lang)
            if literal is not None:
                try:
                    out.append(float(literal))
                except ValueError:
                    continue
    return out


def _has_count(sentence: str, n: int) -> bool:
    low = sentence.lower()
    if any(abs(v - n) < 1e-9 for v in _numbers(sentence)):
        return True
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low) for w in NUMBER_WORDS.get(n, ()))


def discrepancy_stated(text: str, spec: Mapping[str, Any]) -> bool:
    """Whether ``text`` states the refuting fact described by ``spec`` (a ``templates.Discrepancy``)."""
    if not text or not spec:
        return False
    low = text.lower()
    if any(w.lower() in low for w in spec.get("words", [])):
        return True
    numbers = _numbers(text)
    if any(abs(v - float(a)) <= 0.01 for a in spec.get("amounts", []) for v in numbers):
        return True
    sentences = _sentences(text)
    nouns = [n.lower() for n in spec.get("count_nouns", [])]
    for n in spec.get("counts", []):
        for s in sentences:
            if (not nouns or any(noun in s.lower() for noun in nouns)) and _has_count(s, int(n)):
                return True
    absence = [n.lower() for n in spec.get("absence_nouns", [])]
    if absence:
        for s in sentences:
            tokens = set(_TOKEN.findall(s.lower()))
            negated = any(neg in tokens for neg in NEGATIONS) or any(neg in s.lower() for neg in ("n't", "n’t", "$0"))
            if negated and any(noun in s.lower() for noun in absence):
                return True
    return False
