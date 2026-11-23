"""Seeded derivation of ``distributor-ops-v1.sqlite`` from the tabular fixture ``distributor-v1.sqlite``.

The v1 fixture is opened read-only and never changes (ADR-0006). The generator copies its rows,
then **seeds into the background every state that a scenario patch can create** (design §5.5), so a
patched target is one of several records of its kind:

=========================================== ============================== ======================
background state                            how many                       state class of
=========================================== ============================== ======================
returned, unpaid, invoice void (v1)         the rest of the returned       template 1 ``far``
returned, paid, refunded in full, void      about 45 % of older returns    history
returned and paid, awaiting the refund      8 recent returns               template 1 ``true``
returned, partly paid, awaiting the refund  8 recent returns               template 1 ``near``
returned, paid, partly refunded             8 recent returns               template 1 ``two_table``
late-payment hold, 3 or more overdue        10 customers                   template 4 ``far``
late-payment hold, exactly one overdue      20 customers                   template 4 ``near``
late-payment hold, nothing overdue          8 customers                    template 4 ``true``
risk-review hold, nothing overdue           7 customers                    template 4 ``two_table``
risk-review hold with overdue; released     3; 12 customers                history
collection case open                        about a third of overdue       history (template 5)
collection case closed (paid, uncollect.)   about 40; 12                   history
stock at 110-130 % of the reorder level     10 rows                        template 6 ``near``
open reorder, recent and material           half the rows below the level  template 6 ``two_table``
received and cancelled reorders             150; 25                        history
discontinued products                       all of them, at zero stock     (template 7, later)
=========================================== ============================== ======================

Ids in ``payments`` and the operational tables are reassigned in date order with gaps of
``rules.GAP``, so a row that a patch inserts takes an id from the gap that matches its date and
looks like its neighbours. Money is handled in integer cents. The only randomness is
``Rng`` (``random.Random(seed).random()``), as in the v1 generator.
"""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..tabular.generate import Rng, file_sha256
from ..tabular.generate import content_sha256 as v1_content_sha256
from . import ops_schema as S
from .rules import GAP, REFUND_EXISTING, REORDER_RECENT_DAYS, SHORTFALL_BANDS
from .sandbox import BaseFixture

GENERATOR_VERSION = "1"
RECENT = date(2026, 1, 1)  # returns still awaiting a refund were issued from here on
BASE_TABLES = ("customers", "products", "orders", "order_items", "invoices", "payments", "inventory")
NICE = (10, 15, 20, 25, 30, 40, 50, 60, 75, 80, 100, 120, 150, 200, 250, 300, 400, 500)


def _d(text: str) -> date:
    return date.fromisoformat(text)


def _cents(amount: float) -> int:
    return round(amount * 100)


def _iso(d: date) -> str:
    return d.isoformat()


def shortfall(rng: Rng) -> float:
    """A share of the amount left unpaid, inside one of the allowed bands (weighted by width)."""
    widths = [hi - lo for lo, hi in SHORTFALL_BANDS]
    lo, hi = rng.weighted(SHORTFALL_BANDS, widths)
    return round(rng.uniform(lo, hi), 4)


def nice_quantity(units: float) -> int:
    return min(NICE, key=lambda n: (abs(n - units), n))


def load_v1(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    """The v1 fixture's rows, read-only, per base table, in primary-key order."""
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        out = {}
        for name in BASE_TABLES:
            t = S.table(name)
            cols = ", ".join(c.name for c in t.columns)
            out[name] = con.execute(f"SELECT {cols} FROM {name} ORDER BY {', '.join(t.primary_key)}").fetchall()
        return out
    finally:
        con.close()


class Ops:
    """Working state of the derivation: rows as mutable dicts, money in cents."""

    def __init__(self, v1: dict[str, list[tuple[Any, ...]]]):
        self.v1 = v1
        self.customers = {r[0]: r for r in v1["customers"]}
        self.products = {r[0]: list(r) for r in v1["products"]}
        self.orders = {r[0]: r for r in v1["orders"]}
        self.invoices = {r[0]: list(r) for r in v1["invoices"]}  # id, number, order, issue, due, amount, status
        self.payments: list[list[Any]] = [[r[0], r[1], r[2], _cents(r[3]), r[4]] for r in v1["payments"]]
        self.inventory = {(r[0], r[1]): list(r) for r in v1["inventory"]}
        self.refunds: list[list[Any]] = []  # id, invoice_id, date, cents, reason
        self.holds: dict[int, list[Any]] = {}  # customer -> on_hold, reason, placed_on, released_on, note
        self.cases: list[list[Any]] = []  # id, invoice_id, opened_on, status, closed_on, note
        self.reorders: list[list[Any]] = []  # id, product, warehouse, qty, ordered_on, status, received_on
        self.customer_of_order = {oid: r[1] for oid, r in self.orders.items()}

    # ---- derived views
    def paid_cents(self) -> dict[int, int]:
        paid: dict[int, int] = defaultdict(int)
        for p in self.payments:
            paid[p[1]] += p[3]
        return paid

    def overdue_by_customer(self) -> dict[int, list[list[Any]]]:
        out: dict[int, list[list[Any]]] = defaultdict(list)
        for inv in self.invoices.values():
            if inv[6] == "overdue":
                out[self.customer_of_order[inv[2]]].append(inv)
        return out

    def add_payment(self, invoice_id: int, when: date, cents: int, rng: Rng) -> None:
        method = rng.weighted(("bank_transfer", "card", "check", "cash"), (0.65, 0.15, 0.12, 0.08))
        self.payments.append([None, invoice_id, _iso(when), cents, method])


# ----------------------------------------------------------------------------- the seeding steps
def seed_inventory(ops: Ops, rng: Rng) -> int:
    """Discontinued products at zero stock, and a few rows just above their reorder level."""
    for key, row in ops.inventory.items():
        if ops.products[key[0]][7] == 0:  # discontinued: kept with zero stock
            row[2] = 0
    above = [row for key, row in sorted(ops.inventory.items()) if ops.products[key[0]][7] == 1]
    above = [row for row in above if row[2] >= ops.products[row[0]][6]]
    seeded = 0
    for row in rng.shuffle(above)[:10]:  # 110-130 % of the level and at least 3 units above it
        level = ops.products[row[0]][6]
        row[2] = max(level + 3, int(level * rng.uniform(1.10, 1.30)))
        seeded += row[2] <= 1.30 * level
    return seeded


def seed_returns(ops: Ops, rng: Rng) -> dict[str, list[int]]:
    returned = [inv for inv in ops.invoices.values() if ops.orders[inv[2]][3] == "returned"]
    recent = rng.shuffle([inv for inv in returned if _d(inv[3]) >= RECENT])
    older = rng.shuffle([inv for inv in returned if _d(inv[3]) < RECENT])
    states: dict[str, list[int]] = defaultdict(list)
    plan = [("paid_awaiting_refund", 8), ("partly_paid_awaiting_refund", 8), ("paid_partly_refunded", 8),
            ("refunded_in_full", 6)]  # fmt: skip
    for state, n in plan:
        for inv in recent[:n]:
            states[state].append(inv[0])
        recent = recent[n:]
    for inv in older:
        if rng.chance(0.45):
            states["refunded_in_full"].append(inv[0])
    for state, ids in states.items():
        for invoice_id in ids:
            inv = ops.invoices[invoice_id]
            issue, cents = _d(inv[3]), _cents(inv[5])
            latest = S.TODAY - timedelta(days=3)
            pay_day = min(issue + timedelta(days=rng.int(5, 30)), latest)
            if state == "partly_paid_awaiting_refund":
                paid = cents - round(cents * shortfall(rng))
                ops.add_payment(invoice_id, pay_day, paid, rng)
                inv[6] = "overdue" if _d(inv[4]) < S.TODAY else "open"
                continue
            ops.add_payment(invoice_id, pay_day, cents, rng)
            if state == "paid_awaiting_refund":
                inv[6] = "paid"
            elif state == "paid_partly_refunded":
                share = rng.uniform(*REFUND_EXISTING)
                refund_day = min(pay_day + timedelta(days=rng.int(3, 20)), S.TODAY - timedelta(days=1))
                ops.refunds.append([None, invoice_id, _iso(refund_day), round(cents * share), "return"])
                inv[6] = "paid"
            else:  # refunded in full: the invoice is voided
                refund_day = min(pay_day + timedelta(days=rng.int(5, 25)), S.TODAY - timedelta(days=1))
                ops.refunds.append([None, invoice_id, _iso(refund_day), cents, "return"])
                inv[6] = "void"
    return dict(states)


def seed_holds(ops: Ops, rng: Rng) -> dict[str, list[int]]:
    overdue = ops.overdue_by_customer()
    customers = sorted(ops.customers)
    by_count = {
        "three_plus": [c for c in customers if len(overdue.get(c, [])) >= 3],
        "one": [c for c in customers if len(overdue.get(c, [])) == 1],
        "none": [c for c in customers if not overdue.get(c)],
    }
    pools = {k: rng.shuffle(v) for k, v in by_count.items()}
    groups: dict[str, list[int]] = {
        "late_three_plus": pools["three_plus"][:10],
        "late_one": pools["one"][:20],
        "late_none": pools["none"][:8],
        "risk_none": pools["none"][8:15],
        "released": pools["none"][15:27],
        "risk_overdue": pools["three_plus"][10:12] + pools["one"][20:21],
    }
    for group, members in groups.items():
        for c in members:
            if group in ("late_three_plus", "late_one"):
                first_due = min(_d(inv[4]) for inv in overdue[c])
                placed = min(first_due + timedelta(days=rng.int(15, 40)), S.TODAY - timedelta(days=1))
                ops.holds[c] = [1, "late_payment", _iso(placed), None, None]
            elif group == "late_none":
                ops.holds[c] = [1, "late_payment", _iso(S.TODAY - timedelta(days=rng.int(10, 60))), None, None]
            elif group in ("risk_none", "risk_overdue"):
                ops.holds[c] = [1, "risk_review", _iso(S.TODAY - timedelta(days=rng.int(20, 200))), None, None]
            else:
                placed = S.TODAY - timedelta(days=rng.int(60, 400))
                released = min(placed + timedelta(days=rng.int(10, 60)), S.TODAY - timedelta(days=1))
                reason = "risk_review" if rng.chance(0.2) else "late_payment"
                ops.holds[c] = [0, reason, _iso(placed), _iso(released), None]
    return groups


def seed_cases(ops: Ops, rng: Rng) -> None:
    paid = ops.paid_cents()
    last_payment: dict[int, date] = {}
    for p in ops.payments:
        day = _d(p[2])
        last_payment[p[1]] = max(day, last_payment.get(p[1], day))
    latest = S.TODAY - timedelta(days=1)
    for inv in sorted(ops.invoices.values()):
        invoice_id, due, status = inv[0], _d(inv[4]), inv[6]
        if status == "overdue" and ops.orders[inv[2]][3] != "returned":
            if due < date(2026, 3, 1) and paid.get(invoice_id, 0) == 0 and rng.chance(0.06):
                opened = due + timedelta(days=30)
                closed = min(opened + timedelta(days=rng.int(90, 200)), latest)
                ops.cases.append([None, invoice_id, _iso(opened), "closed_uncollectible", _iso(closed), None])
            elif rng.chance(1 / 3):
                opened = due + timedelta(days=rng.int(20, 45))
                if opened <= latest:
                    ops.cases.append([None, invoice_id, _iso(opened), "open", None, None])
        elif (
            status == "paid"
            and invoice_id in last_payment
            and last_payment[invoice_id] > due + timedelta(days=30)
            and rng.chance(0.05)
        ):
            opened = due + timedelta(days=rng.int(20, 30))
            ops.cases.append([None, invoice_id, _iso(opened), "closed_paid", _iso(last_payment[invoice_id]), None])


def seed_reorders(ops: Ops, rng: Rng) -> None:
    rows = sorted(ops.inventory.values())
    for product_id, warehouse, qty, _counted in rows:
        level = ops.products[product_id][6]
        if ops.products[product_id][7] == 1 and qty < level and rng.chance(0.5):
            ordered = S.TODAY - timedelta(days=rng.int(1, REORDER_RECENT_DAYS - 1))
            units = nice_quantity(level * rng.uniform(1.5, 3.0))
            ops.reorders.append([None, product_id, warehouse, max(units, level), _iso(ordered), "open", None])
    active = [r for r in rows if ops.products[r[0]][7] == 1]
    for _ in range(150):
        product_id, warehouse = rng.choice(active)[:2]
        ordered = S.TODAY - timedelta(days=rng.int(30, 600))
        received = ordered + timedelta(days=rng.int(4, 15))
        units = nice_quantity(ops.products[product_id][6] * rng.uniform(1.5, 3.0))
        ops.reorders.append([None, product_id, warehouse, units, _iso(ordered), "received", _iso(received)])
    for _ in range(25):
        product_id, warehouse = rng.choice(active)[:2]
        ordered = S.TODAY - timedelta(days=rng.int(30, 400))
        units = nice_quantity(ops.products[product_id][6] * rng.uniform(1.5, 3.0))
        ops.reorders.append([None, product_id, warehouse, units, _iso(ordered), "cancelled", None])


def renumber(rows: list[list[Any]], date_index: int) -> list[list[Any]]:
    """Ids in date order (ties keep their order of creation), with gaps: the i-th row gets GAP * (i + 1)."""
    ordered = [row for _, _, row in sorted((r[date_index], i, r) for i, r in enumerate(rows))]
    for i, row in enumerate(ordered):
        row[0] = GAP * (i + 1)
    return ordered


def derive(v1: dict[str, list[tuple[Any, ...]]], seed: str = S.SEED) -> tuple[dict[str, list[tuple]], dict[str, Any]]:
    """The operations fixture's rows per table, and a summary of what was seeded."""
    ops = Ops(v1)
    near_stock = seed_inventory(ops, Rng(f"{seed}/inventory"))
    returns = seed_returns(ops, Rng(f"{seed}/returns"))
    holds = seed_holds(ops, Rng(f"{seed}/holds"))
    seed_cases(ops, Rng(f"{seed}/cases"))
    seed_reorders(ops, Rng(f"{seed}/reorders"))
    payments = renumber(ops.payments, 2)
    refunds = renumber(ops.refunds, 2)
    cases = renumber(ops.cases, 2)
    reorders = renumber(ops.reorders, 4)
    rows: dict[str, list[tuple]] = {
        "customers": list(v1["customers"]),
        "products": [tuple(p) for p in sorted(ops.products.values())],
        "orders": list(v1["orders"]),
        "order_items": list(v1["order_items"]),
        "invoices": [tuple(i) for i in sorted(ops.invoices.values())],
        "payments": sorted((p[0], p[1], p[2], p[3] / 100, p[4]) for p in payments),
        "inventory": [tuple(r) for r in sorted(ops.inventory.values())],
        "refunds": sorted((r[0], r[1], r[2], r[3] / 100, r[4]) for r in refunds),
        "credit_holds": sorted((c, *h) for c, h in ops.holds.items()),
        "collection_cases": sorted(tuple(c) for c in cases),
        "reorders": sorted(tuple(r) for r in reorders),
        "system_info": sorted(S.SYSTEM_INFO),
    }
    summary = {
        "returns": {k: len(v) for k, v in sorted(returns.items())},
        "holds": {k: len(v) for k, v in sorted(holds.items())},
        "collection_cases": len(cases),
        "reorders": len(reorders),
        "stock_near_reorder_level": near_stock,
    }
    return rows, summary


def write_ops(path: Path, rows: dict[str, list[tuple]]) -> None:
    """Write the fixture atomically, in rollback-journal mode, in primary-key order, then VACUUM."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp, isolation_level=None)
    try:
        con.execute("PRAGMA page_size = 4096")
        con.execute("PRAGMA journal_mode = DELETE")
        con.execute("PRAGMA user_version = 1")
        con.executescript(S.schema_ddl())
        con.execute("BEGIN")
        for t in S.TABLES:
            marks = ", ".join("?" for _ in t.columns)
            con.executemany(f"INSERT INTO {t.name} VALUES ({marks})", rows[t.name])
        con.execute("COMMIT")
        con.executescript(S.indexes_ddl())
        con.execute("VACUUM")
    finally:
        con.close()
    os.replace(tmp, path)


def content_sha256(path: Path) -> str:
    """The fixture's content hash: the DDL and one hash per table (``sandbox.combine_hashes``)."""
    return BaseFixture(path).content_sha256


def row_counts(path: Path) -> dict[str, int]:
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return {t.name: con.execute(f"SELECT COUNT(*) FROM {t.name}").fetchone()[0] for t in S.TABLES}
    finally:
        con.close()


def manifest(path: Path, v1_path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "file": path.name,
        "db_version": S.DB_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": S.SEED,
        "derived_from": {"file": v1_path.name, "content_sha256": v1_content_sha256(v1_path)},
        "business_date": S.TODAY.isoformat(),
        "bytes": path.stat().st_size,
        "file_sha256": file_sha256(path),
        "content_sha256": content_sha256(path),
        "sqlite_version": sqlite3.sqlite_version,
        "row_counts": row_counts(path),
        "seeded": summary,
        "note": (
            "Synthetic data, derived from distributor-v1 by a seeded generator: the company, customers and "
            "products are fictional. file_sha256 depends on the SQLite version that wrote the file; "
            "content_sha256 does not."
        ),
    }


def generate(target: Path, v1_path: Path) -> dict[str, Any]:
    """Derive the operations fixture from the v1 fixture and write it with its manifest data."""
    rows, summary = derive(load_v1(v1_path))
    write_ops(target, rows)
    return manifest(target, v1_path, summary)
