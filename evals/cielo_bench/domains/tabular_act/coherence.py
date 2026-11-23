"""Coherence invariants of a world (design §5.4): run on the fixture and on every patched world.

A patched record must look like its neighbours: statuses agree with payments (except the
documented lag states, which the fixture seeds into the background), payments and refunds fall
after the invoice was issued, due dates follow the customer's payment terms, and ids in the spaced
tables run in date order. Each check returns the number of rows that break it; zero everywhere is
required.
"""

from __future__ import annotations

from .ops_schema import TODAY
from .sandbox import TrialDB

_PAID = "COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.invoice_id = i.invoice_id), 0)"
_REFUNDED = "COALESCE((SELECT SUM(r.amount) FROM refunds r WHERE r.invoice_id = i.invoice_id), 0)"
T = TODAY.isoformat()

CHECKS = {
    "paid invoice not covered by its payments": f"SELECT COUNT(*) FROM invoices i WHERE status = 'paid' "
    f"AND {_PAID} < amount - 0.005",
    "open or overdue invoice covered by its payments": f"SELECT COUNT(*) FROM invoices i "
    f"WHERE status IN ('open', 'overdue') AND {_PAID} >= amount - 0.005",
    "overdue invoice not past due": f"SELECT COUNT(*) FROM invoices WHERE status = 'overdue' AND due_date >= '{T}'",
    "open invoice past due": f"SELECT COUNT(*) FROM invoices WHERE status = 'open' AND due_date < '{T}'",
    "void invoice of an order not returned": "SELECT COUNT(*) FROM invoices i JOIN orders o ON o.order_id = "
    "i.order_id WHERE i.status = 'void' AND o.status <> 'returned'",
    "void invoice with money not refunded": f"SELECT COUNT(*) FROM invoices i WHERE status = 'void' "
    f"AND {_PAID} - {_REFUNDED} > 0.005",
    "returned order, nothing paid, invoice not void": f"SELECT COUNT(*) FROM invoices i JOIN orders o "
    f"ON o.order_id = i.order_id WHERE o.status = 'returned' AND i.status <> 'void' AND {_PAID} = 0",
    "refunds above the payments": f"SELECT COUNT(*) FROM invoices i WHERE {_REFUNDED} > {_PAID} + 0.005",
    "payment not after the issue date": "SELECT COUNT(*) FROM payments p JOIN invoices i ON i.invoice_id = "
    "p.invoice_id WHERE p.payment_date <= i.issue_date",
    "payment after today": f"SELECT COUNT(*) FROM payments WHERE payment_date > '{T}'",
    "refund before the first payment": "SELECT COUNT(*) FROM refunds r WHERE r.refund_date < (SELECT MIN("
    "payment_date) FROM payments p WHERE p.invoice_id = r.invoice_id) OR NOT EXISTS (SELECT 1 FROM payments p "
    "WHERE p.invoice_id = r.invoice_id)",
    "issued before the order": "SELECT COUNT(*) FROM invoices i JOIN orders o ON o.order_id = i.order_id "
    "WHERE i.issue_date < o.order_date",
    "issued after today": f"SELECT COUNT(*) FROM invoices WHERE issue_date > '{T}'",
    "due date not issue date plus terms": "SELECT COUNT(*) FROM invoices i JOIN orders o ON o.order_id = "
    "i.order_id JOIN customers c ON c.customer_id = o.customer_id WHERE i.due_date <> "
    "date(i.issue_date, '+' || c.payment_terms_days || ' days')",
    "collection case opened before the due date": "SELECT COUNT(*) FROM collection_cases k JOIN invoices i "
    "ON i.invoice_id = k.invoice_id WHERE k.opened_on <= i.due_date",
    "case closed as paid on an unpaid invoice": "SELECT COUNT(*) FROM collection_cases k JOIN invoices i "
    "ON i.invoice_id = k.invoice_id WHERE k.status = 'closed_paid' AND i.status <> 'paid'",
    "open reorder that is old or small": f"SELECT COUNT(*) FROM reorders r JOIN products p ON p.product_id = "
    f"r.product_id WHERE r.status = 'open' AND (r.ordered_on < date('{T}', '-14 days') OR r.quantity < "
    "p.reorder_level)",
    "released hold without a release date": "SELECT COUNT(*) FROM credit_holds WHERE on_hold = 0 AND "
    "released_on IS NULL",
    "hold placed after today": f"SELECT COUNT(*) FROM credit_holds WHERE placed_on > '{T}'",
    "discontinued product with stock": "SELECT COUNT(*) FROM inventory i JOIN products p ON p.product_id = "
    "i.product_id WHERE p.is_active = 0 AND i.quantity_on_hand <> 0",
}
for _table, _id, _date in (
    ("payments", "payment_id", "payment_date"),
    ("refunds", "refund_id", "refund_date"),
    ("collection_cases", "case_id", "opened_on"),
    ("reorders", "reorder_id", "ordered_on"),
):
    CHECKS[f"{_table} ids out of date order"] = (
        f"SELECT COUNT(*) FROM (SELECT {_date} AS d, LAG({_date}) OVER (ORDER BY {_id}) AS prev FROM {_table}) "
        "WHERE d < prev"
    )


def problems(db: TrialDB) -> list[str]:
    """Every invariant the world breaks, with the number of rows that break it."""
    out = []
    for name, sql in CHECKS.items():
        n = db.query(sql)[0][0]
        if n:
            out.append(f"{name}: {n}")
    return out
