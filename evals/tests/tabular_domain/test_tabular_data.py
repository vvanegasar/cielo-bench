"""The synthetic snapshot: deterministic, small, intact, realistic, and its ground truth agrees
with an independent computation from the generator's own rows (no SQL involved)."""

import json
import sqlite3
import time
from collections import defaultdict

import pytest

from cielo_bench.domains.tabular import generate as gen
from cielo_bench.domains.tabular.schema import AS_OF, DATA_TABLES, TABLES, table
from cielo_bench.domains.tabular.templates import bounds

MAX_BYTES = 5 * 1024 * 1024


@pytest.fixture(scope="module")
def db(tabular):
    con = sqlite3.connect(tabular.db_path.resolve().as_uri() + "?mode=ro", uri=True)
    yield con
    con.close()


@pytest.fixture(scope="module")
def dataset():
    return gen.generate()


def q(con, sql):
    return con.execute(sql).fetchall()


def test_generation_is_deterministic_and_matches_the_fixture(tmp_path, tabular):
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    gen.write_database(a)
    gen.write_database(b)
    assert gen.content_sha256(a) == gen.content_sha256(b)
    assert gen.file_sha256(a) == gen.file_sha256(b)  # same SQLite version: same bytes
    manifest = tabular.database_info()
    assert gen.content_sha256(a) == manifest["content_sha256"]  # the committed data comes from the seed


def test_fixture_is_small_intact_and_recorded_in_the_golden_set(tabular, tabular_golden):
    domain = tabular
    manifest = json.loads(domain.manifest_path.read_text(encoding="utf-8"))
    assert domain.db_path.stat().st_size < MAX_BYTES
    assert gen.file_sha256(domain.db_path) == manifest["file_sha256"]
    assert gen.content_sha256(domain.db_path) == manifest["content_sha256"]
    assert gen.row_counts(domain.db_path) == manifest["row_counts"]
    fixture = tabular_golden.doc["fixtures"][0]
    assert fixture["file_sha256"] == manifest["file_sha256"]
    assert fixture["content_sha256"] == manifest["content_sha256"]
    assert fixture["path"] == "evals/fixtures/tabular/distributor-v1.sqlite"


def test_regenerates_in_seconds(tmp_path):
    start = time.monotonic()
    gen.write_database(tmp_path / "x.sqlite")
    assert time.monotonic() - start < 10.0


def test_schema_matches_its_definitions(db):
    for t in TABLES:
        cols = [r[1] for r in q(db, f"SELECT * FROM pragma_table_info('{t.name}')")]
        assert cols == [c.name for c in t.columns], t.name
    assert dict(q(db, "SELECT key, value FROM snapshot_info"))["as_of_date"] == AS_OF.isoformat()
    for t in TABLES:  # NOT NULL where documented
        for c in t.columns:
            if not c.nullable:
                assert q(db, f"SELECT COUNT(*) FROM {t.name} WHERE {c.name} IS NULL")[0][0] == 0, (t.name, c.name)


def test_missing_values_only_where_documented(db):
    for t in TABLES:
        for c in t.columns:
            if c.nullable:
                assert q(db, f"SELECT COUNT(*) FROM {t.name} WHERE {c.name} IS NULL")[0][0] > 0, (t.name, c.name)


def test_seasonality_growth_and_order_life_cycle(db):
    monthly = dict(
        q(db, "SELECT substr(issue_date, 1, 7), SUM(amount) FROM invoices WHERE status <> 'void' GROUP BY 1")
    )
    for year in ("2024", "2025"):
        months = {m: v for m, v in monthly.items() if m.startswith(year)}
        assert max(months, key=months.get) == f"{year}-12"  # December peak
        assert months[f"{year}-12"] > 1.15 * months[f"{year}-01"]  # and a January dip
    assert sum(v for m, v in monthly.items() if m.startswith("2025")) > sum(
        v for m, v in monthly.items() if m.startswith("2024")
    )  # growth
    statuses = dict(q(db, "SELECT status, COUNT(*) FROM orders GROUP BY 1"))
    assert statuses["returned"] > 50 and statuses["cancelled"] > 50 and statuses["delivered"] > 5000
    # cancelled and pending orders are never invoiced; returned orders have a void invoice
    assert (
        q(
            db,
            """SELECT COUNT(*) FROM orders o JOIN invoices i ON i.order_id = o.order_id
                    WHERE o.status IN ('cancelled', 'pending')""",
        )[0][0]
        == 0
    )
    assert (
        q(
            db,
            """SELECT COUNT(*) FROM orders o JOIN invoices i ON i.order_id = o.order_id
                    WHERE o.status = 'returned' AND i.status <> 'void'""",
        )[0][0]
        == 0
    )
    assert q(db, "SELECT COUNT(*) FROM orders WHERE status = 'cancelled' AND ship_date IS NOT NULL")[0][0] == 0


def test_invoices_are_consistent_with_lines_payments_and_due_dates(db):
    as_of = AS_OF.isoformat()
    # invoice amount = sum of its lines, each rounded half up to the cent (exact, in integer cents)
    mismatches = q(
        db,
        """SELECT COUNT(*) FROM invoices i JOIN (
                            SELECT order_id, SUM((quantity * CAST(ROUND(unit_price * 100) AS INTEGER)
                                                  * (100 - CAST(ROUND(discount_pct * 100) AS INTEGER)) + 50) / 100) AS cents
                            FROM order_items GROUP BY order_id) s ON s.order_id = i.order_id
                          WHERE CAST(ROUND(i.amount * 100) AS INTEGER) <> s.cents""",
    )[0][0]
    assert mismatches == 0
    paid = """(SELECT COALESCE(SUM(p.amount), 0) FROM payments p WHERE p.invoice_id = i.invoice_id)"""
    assert q(db, f"SELECT COUNT(*) FROM invoices i WHERE {paid} > i.amount + 0.001")[0][0] == 0
    assert q(db, f"SELECT COUNT(*) FROM invoices i WHERE status = 'paid' AND {paid} < i.amount - 0.001")[0][0] == 0
    assert (
        q(
            db,
            f"SELECT COUNT(*) FROM invoices i WHERE status = 'overdue' AND (due_date >= '{as_of}' "
            f"OR {paid} >= i.amount - 0.001)",
        )[0][0]
        == 0
    )
    assert q(db, f"SELECT COUNT(*) FROM invoices WHERE status = 'open' AND due_date < '{as_of}'")[0][0] == 0
    assert q(db, f"SELECT COUNT(*) FROM payments WHERE payment_date > '{as_of}'")[0][0] == 0
    assert q(db, "SELECT COUNT(*) FROM invoices WHERE status = 'overdue'")[0][0] > 200
    assert q(db, "SELECT COUNT(*) FROM (SELECT invoice_id FROM payments GROUP BY 1 HAVING COUNT(*) > 1)")[0][0] > 100


def test_inventory_has_stock_outs_low_stock_and_partial_coverage(db):
    assert q(db, "SELECT COUNT(*) FROM inventory WHERE quantity_on_hand = 0")[0][0] > 0
    below = q(
        db,
        """SELECT COUNT(*) FROM inventory i JOIN products p ON p.product_id = i.product_id
                     WHERE i.quantity_on_hand < p.reorder_level""",
    )[0][0]
    total = q(db, "SELECT COUNT(*) FROM inventory")[0][0]
    assert 0.1 < below / total < 0.5
    # discontinued products are only stocked in the Centro warehouse
    assert (
        q(
            db,
            """SELECT COUNT(*) FROM inventory i JOIN products p ON p.product_id = i.product_id
                    WHERE p.is_active = 0 AND i.warehouse <> 'Centro'""",
        )[0][0]
        == 0
    )


def test_names_are_fictional_and_contacts_use_reserved_domains(db):
    names = [r[0] for r in q(db, "SELECT name FROM customers")]
    assert len(names) == len(set(names)) and all(n.isascii() for n in names)
    emails = [r[0] for r in q(db, "SELECT email FROM customers WHERE email IS NOT NULL")]
    assert emails and all(e.endswith(".example") for e in emails)  # RFC 2606: never a real domain


# ---- independent ground truth --------------------------------------------------------------
def _index(ds):
    customers = {c.customer_id: c for c in ds.customers}
    orders = {o[0]: o for o in ds.orders}
    paid = defaultdict(int)
    for _pid, iid, _d, cents, _m in ds.payments:
        paid[iid] += cents
    return customers, orders, paid


def _in(d, period):
    start, end = bounds(period)
    return start <= d.isoformat() < end


def independent_facts(ds, pair):
    customers, orders, paid = _index(ds)
    ctx, t = pair["context"], pair["template"]
    invoices = ds.invoices  # (id, number, order, issue, due, cents, status)

    def total(period):
        return round(sum(i[5] for i in invoices if i[6] != "void" and _in(i[3], period)) / 100, 2)

    if t == "period_total":
        return {"total": total(ctx["period"])}
    if t == "order_count":
        return {
            "count": sum(1 for o in ds.orders if customers[o[1]].region == ctx["region"] and _in(o[2], ctx["quarter"]))
        }
    if t == "top_customer":
        by = defaultdict(int)
        for i in invoices:
            c = customers[orders[i[2]][1]]
            if i[6] != "void" and c.region == ctx["region"] and _in(i[3], ctx["quarter"]):
                by[c.customer_id] += i[5]
        ranked = sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))
        return {"top": customers[ranked[0][0]].name, "runner_up": customers[ranked[1][0]].name}
    if t == "invoice_status":
        inv = next(i for i in invoices if i[1] == ctx["invoice_number"])
        return {"status": inv[6], "amount_paid": paid[inv[0]] / 100}
    if t == "low_stock":
        product = next(p for p in ds.products if p.sku == ctx["sku"])
        return {"on_hand": next(r[2] for r in ds.inventory if r[0] == product.product_id and r[1] == ctx["warehouse"])}
    if t == "period_change":
        return {"a_total": total(ctx["a"]), "b_total": total(ctx["b"])}
    if t == "customer_balance":
        owed = sum(i[5] - paid[i[0]] for i in invoices if i[6] == "overdue" and orders[i[2]][1] == ctx["customer_id"])
        return {"balance": round(owed / 100, 2)}
    raise AssertionError(t)


@pytest.mark.parametrize(
    "template",
    ["period_total", "order_count", "top_customer", "invoice_status", "low_stock", "period_change", "customer_balance"],
)
def test_reference_sql_agrees_with_an_independent_python_computation(dataset, template, tabular_golden):
    pairs = [p for p in tabular_golden.pairs if p["template"] == template]
    assert len(pairs) == 18
    for pair in pairs:
        expected = independent_facts(dataset, pair)
        for key, value in expected.items():
            if isinstance(value, str):
                assert pair["facts"][key] == value, (pair["pair_id"], key)
            else:
                assert pair["facts"][key] == pytest.approx(value, abs=0.005), (pair["pair_id"], key)


def test_every_data_table_is_populated(db):
    for name in DATA_TABLES:
        assert q(db, f"SELECT COUNT(*) FROM {name}")[0][0] > 0, name
    assert table("inventory").primary_key == ("product_id", "warehouse")
