"""Schema of the synthetic distributor database: the single source of truth.

The DDL, the catalogue that ``describe_schema`` returns, the allowed values of every coded
column and the content hash all come from the definitions below, so they cannot drift
apart. Everything here describes a *fictional* company: no real customer, product or
figure appears anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

DB_VERSION = "v1"
DB_FILENAME = f"distributor-{DB_VERSION}.sqlite"
MANIFEST_FILENAME = f"distributor-{DB_VERSION}.manifest.json"
SEED = f"cielo-bench/tabular/{DB_VERSION}"

# The data window: orders from START to AS_OF (inclusive). AS_OF is the snapshot date: invoice
# statuses, balances and stock levels are "as of the end of this day".
START = date(2024, 1, 1)
AS_OF = date(2026, 9, 30)
CURRENCY = "USD"

REGIONS = ("Centro", "Norte", "Sur", "Oriente", "Occidente")
WAREHOUSES = ("Centro", "Norte", "Sur")
# Which warehouse ships to which customer region (used by the generator for stock levels).
WAREHOUSE_OF_REGION = {"Centro": "Centro", "Oriente": "Centro", "Norte": "Norte", "Sur": "Sur", "Occidente": "Sur"}
SEGMENTS = ("retail", "horeca", "pharmacy", "institutional")
CATEGORIES = ("Beverages", "Snacks", "Dairy", "Pantry", "Cleaning", "Personal care", "Paper goods")
ORDER_STATUSES = ("pending", "shipped", "delivered", "cancelled", "returned")
INVOICE_STATUSES = ("paid", "open", "overdue", "void")
CHANNELS = ("field_sales", "phone", "web")
PAYMENT_METHODS = ("bank_transfer", "card", "check", "cash")
PAYMENT_TERMS = (15, 30, 45, 60)


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    description: str
    nullable: bool = False
    values: tuple[str, ...] | None = None  # allowed values of a coded column (CHECK ... IN)
    references: str | None = None  # "table.column"
    unique: bool = False


@dataclass(frozen=True)
class Table:
    name: str
    description: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]
    indexes: tuple[tuple[str, ...], ...] = field(default=())

    def column(self, name: str) -> Column:
        for col in self.columns:
            if col.name == name:
                return col
        raise KeyError(name)


TABLES: tuple[Table, ...] = (
    Table(
        "customers",
        "Customers (shops, restaurants, pharmacies and institutions). Each customer belongs to one sales region.",
        (
            Column("customer_id", "INTEGER", "Customer identifier."),
            Column("name", "TEXT", "Customer's trade name (unique).", unique=True),
            Column("segment", "TEXT", "Customer segment.", values=SEGMENTS),
            Column("region", "TEXT", "Sales region.", values=REGIONS),
            Column("email", "TEXT", "Purchasing contact e-mail; missing for some customers.", nullable=True),
            Column("credit_limit", "REAL", "Credit limit in USD; missing for some customers.", nullable=True),
            Column(
                "payment_terms_days",
                "INTEGER",
                "Days between invoice issue and due date.",
                values=tuple(str(t) for t in PAYMENT_TERMS),
            ),
            Column("created_on", "TEXT", "Date the customer account was opened (YYYY-MM-DD)."),
        ),
        ("customer_id",),
        (("region",),),
    ),
    Table(
        "products",
        "Product catalogue. Prices are per selling unit (a pack or a case), in USD, excluding taxes.",
        (
            Column("product_id", "INTEGER", "Product identifier."),
            Column("sku", "TEXT", "Stock-keeping unit code, for example 'BEV-0007' (unique).", unique=True),
            Column("name", "TEXT", "Product name and pack size."),
            Column(
                "category", "TEXT", "Product category; missing for a few products.", nullable=True, values=CATEGORIES
            ),
            Column("unit_price", "REAL", "Current list price per unit (USD)."),
            Column("unit_cost", "REAL", "Current unit cost (USD); missing for some products.", nullable=True),
            Column(
                "reorder_level", "INTEGER", "Stock level per warehouse below which the product should be reordered."
            ),
            Column("is_active", "INTEGER", "1 if the product is still sold, 0 if discontinued.", values=("0", "1")),
        ),
        ("product_id",),
    ),
    Table(
        "orders",
        "Customer orders, one row per order. Cancelled orders are kept. An order is invoiced when it ships.",
        (
            Column("order_id", "INTEGER", "Order identifier."),
            Column("customer_id", "INTEGER", "Customer who placed the order.", references="customers.customer_id"),
            Column("order_date", "TEXT", "Date the order was placed (YYYY-MM-DD)."),
            Column("status", "TEXT", "Order status as of the snapshot date.", values=ORDER_STATUSES),
            Column("channel", "TEXT", "Sales channel; missing for some orders.", nullable=True, values=CHANNELS),
            Column(
                "ship_date",
                "TEXT",
                "Date the order shipped (YYYY-MM-DD); empty for pending and "
                "cancelled orders and missing for a few others.",
                nullable=True,
            ),
        ),
        ("order_id",),
        (("customer_id",), ("order_date",)),
    ),
    Table(
        "order_items",
        "Order lines. Line amount = quantity * unit_price * (1 - discount_pct), rounded to the cent.",
        (
            Column("order_item_id", "INTEGER", "Order line identifier."),
            Column("order_id", "INTEGER", "Order.", references="orders.order_id"),
            Column("product_id", "INTEGER", "Product.", references="products.product_id"),
            Column("quantity", "INTEGER", "Units ordered."),
            Column("unit_price", "REAL", "Price charged per unit (USD), the list price on the order date."),
            Column("discount_pct", "REAL", "Discount as a fraction, for example 0.05 for 5 %."),
        ),
        ("order_item_id",),
        (("order_id",),),
    ),
    Table(
        "invoices",
        "One invoice per shipped order. Returned orders have their invoice voided. Status as of "
        "the snapshot date: 'paid' (fully paid), 'open' (not fully paid, not yet due), 'overdue' "
        "(not fully paid and past its due date), 'void' (cancelled by a return).",
        (
            Column("invoice_id", "INTEGER", "Invoice identifier."),
            Column("invoice_number", "TEXT", "Invoice number, for example 'INV-2026-01234' (unique).", unique=True),
            Column("order_id", "INTEGER", "Invoiced order.", references="orders.order_id", unique=True),
            Column("issue_date", "TEXT", "Issue date (YYYY-MM-DD)."),
            Column("due_date", "TEXT", "Due date (YYYY-MM-DD)."),
            Column("amount", "REAL", "Invoice total in USD, excluding taxes (the sum of the order lines)."),
            Column("status", "TEXT", "Invoice status as of the snapshot date.", values=INVOICE_STATUSES),
        ),
        ("invoice_id",),
        (("issue_date",),),
    ),
    Table(
        "payments",
        "Customer payments. An invoice can be paid in instalments.",
        (
            Column("payment_id", "INTEGER", "Payment identifier."),
            Column("invoice_id", "INTEGER", "Invoice paid.", references="invoices.invoice_id"),
            Column("payment_date", "TEXT", "Date the payment was received (YYYY-MM-DD)."),
            Column("amount", "REAL", "Amount received (USD)."),
            Column(
                "method", "TEXT", "Payment method; missing for some payments.", nullable=True, values=PAYMENT_METHODS
            ),
        ),
        ("payment_id",),
        (("invoice_id",),),
    ),
    Table(
        "inventory",
        "Stock on hand per product and warehouse as of the snapshot date. Discontinued products "
        "are only stocked in some warehouses.",
        (
            Column("product_id", "INTEGER", "Product.", references="products.product_id"),
            Column("warehouse", "TEXT", "Warehouse.", values=WAREHOUSES),
            Column("quantity_on_hand", "INTEGER", "Units on hand."),
            Column(
                "last_counted_on",
                "TEXT",
                "Date of the last physical count (YYYY-MM-DD); missing for some rows.",
                nullable=True,
            ),
        ),
        ("product_id", "warehouse"),
    ),
    Table(
        "snapshot_info",
        "Facts about this database snapshot (key/value).",
        (
            Column("key", "TEXT", "Property name."),
            Column("value", "TEXT", "Property value."),
        ),
        ("key",),
    ),
)

TABLE_NAMES = tuple(t.name for t in TABLES)
DATA_TABLES = tuple(t.name for t in TABLES if t.name != "snapshot_info")

SNAPSHOT_INFO = (
    ("as_of_date", AS_OF.isoformat()),
    ("currency", CURRENCY),
    ("amounts", "US dollars, excluding taxes"),
    ("periods", "calendar months and quarters (Q1 = January to March)"),
)

CONVENTIONS = (
    f"Read-only snapshot of the company database as of {AS_OF.isoformat()} (end of day).",
    "Amounts are US dollars, excluding taxes.",
    "Dates are ISO text 'YYYY-MM-DD'; compare them as text, for example "
    "issue_date >= '2025-07-01' AND issue_date < '2025-10-01'.",
    "Quarters are calendar quarters: Q1 = January-March, Q2 = April-June, Q3 = July-September, Q4 = October-December.",
    "Invoiced revenue is the sum of invoices.amount by issue_date; void invoices are usually excluded.",
    "Customers reach invoices through orders: customers.customer_id = orders.customer_id and "
    "orders.order_id = invoices.order_id.",
)


def _column_ddl(table: Table, col: Column) -> str:
    parts = [col.name, col.type]
    if not col.nullable:
        parts.append("NOT NULL")
    if col.unique:
        parts.append("UNIQUE")
    if col.values is not None:
        quoted = ", ".join(v if col.type == "INTEGER" else f"'{v}'" for v in col.values)
        parts.append(f"CHECK ({col.name} IN ({quoted}))")
    if col.references:
        ref_table, ref_col = col.references.split(".")
        parts.append(f"REFERENCES {ref_table}({ref_col})")
    return " ".join(parts)


def table_ddl(table: Table) -> str:
    lines = [_column_ddl(table, col) for col in table.columns]
    lines.append(f"PRIMARY KEY ({', '.join(table.primary_key)})")
    body = ",\n  ".join(lines)
    suffix = " WITHOUT ROWID" if len(table.primary_key) > 1 or table.name == "snapshot_info" else ""
    return f"CREATE TABLE {table.name} (\n  {body}\n){suffix};"


def index_ddl(table: Table) -> list[str]:
    return [
        f"CREATE INDEX idx_{table.name}_{'_'.join(cols)} ON {table.name}({', '.join(cols)});" for cols in table.indexes
    ]


def schema_ddl() -> str:
    """Tables only (indexes are created after the bulk insert)."""
    return "\n".join(table_ddl(t) for t in TABLES)


def indexes_ddl() -> str:
    return "\n".join(stmt for t in TABLES for stmt in index_ddl(t))


def table(name: str) -> Table:
    for t in TABLES:
        if t.name == name:
            return t
    raise KeyError(name)
