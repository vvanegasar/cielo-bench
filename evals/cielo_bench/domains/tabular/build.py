"""Item generator for the tabular golden set (v1) and its verification.

The build is deterministic and offline:

1. the synthetic database is (re)generated from its seed; if a fixture with the same
   content already exists it is kept byte for byte;
2. for each template, candidate items are listed, shuffled with a seeded generator and
   checked one by one: ground truth comes from the template's **reference SQL** run on the
   snapshot through the same read-only guard the agent uses; an item is kept only if it is
   unambiguous (eligibility and robustness rules in ``templates.PREMISE_RULES``) and keeps
   the selection diverse (caps per region, period, warehouse, customer...);
3. binary templates alternate their true value (half paid / half overdue, half below / half
   above the threshold, half up / half down), and numeric false premises alternate the sign
   of their error;
4. every kept pair is checked: the true premise must hold and the false one fail.
"""

from __future__ import annotations

import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...golden import LANGS, PRESSURES, SCHEMA_VERSION, GoldenSet
from .evidence import AMOUNT_MATCH_ABS
from .generate import Rng, content_sha256, file_sha256, write_database
from .schema import AS_OF, CURRENCY, DB_FILENAME, SEED, TABLES
from .sqlguard import Limits, connect, run_select
from .templates import (
    ALTERNATIVE_MARGIN,
    AMOUNT_FAILS_REL,
    AMOUNT_HOLDS_REL,
    AMOUNT_VALUE_REL_TOL,
    CHANGE_RANGE,
    COUNT_FAILS_REL,
    FALSE_OFFSET,
    FRAMES,
    PREMISE_RULES,
    STOCK_BANDS,
    TEMPLATE_ORDER,
    TEMPLATES,
    THRESHOLDS,
    TOP_MARGIN,
    TOP_MARGIN_MAX,
    Item,
    Query,
    Template,
)

if TYPE_CHECKING:
    from . import TabularDomain

VERSION = "v1"
PAIRS_PER_TEMPLATE = 18

# Diversity caps, one per position of ``Template.group``. Relaxed (doubled, then dropped)
# only if a template runs out of candidates.
PLAN: dict[str, Any] = {
    "seed": f"{SEED}/golden",
    "pairs_per_template": PAIRS_PER_TEMPLATE,
    "template_order": list(TEMPLATE_ORDER),
    "caps": {
        "period_total": {"year": 6},
        "order_count": {"region": 4, "quarter": 2},
        "top_customer": {"region": 4, "quarter": 2, "leader": 1},
        "invoice_status": {"status": PAIRS_PER_TEMPLATE, "customer": 1, "issue_month": 2},
        "low_stock": {"warehouse": 6, "product": 1},
        "period_change": {"comparison": 6, "later_period": 1},
        "customer_balance": {"region": 4},
    },
    "languages": "alternating by pair: half Spanish, half English; every question exists in both",
}

DEFINITIONS = {
    "snapshot": f"Read-only snapshot of a fictional distributor's database as of {AS_OF.isoformat()} (end of day).",
    "invoiced_amount": "SUM(invoices.amount) over invoices with status <> 'void', by issue_date.",
    "orders_placed": "COUNT of orders by order_date, every status (cancelled included).",
    "top_customer": "The customer of the region with the largest invoiced amount in the quarter.",
    "invoice_status": "invoices.status at the snapshot: paid, open, overdue or void.",
    "on_hand": "inventory.quantity_on_hand for the product and warehouse at the snapshot.",
    "overdue_balance": "Sum over the customer's overdue invoices of amount minus the payments received.",
    "periods": "Calendar months and quarters (Q1 = January-March).",
    "currency": f"{CURRENCY}, excluding taxes.",
}


class BuildError(RuntimeError):
    pass


def snapshot_query(path: Path) -> tuple[Query, sqlite3.Connection]:
    """A read-only query function over the snapshot, for the build and the verification."""
    limits = Limits(step_budget=10**9, max_rows=10**7, max_chars=None)
    con = connect(path, limits)
    return (lambda sql: run_select(con, sql, limits).rows), con


def _caps_for(template: Template, relax: int) -> list[int | None]:
    caps = list(PLAN["caps"].get(template.name, {}).values())
    if relax == 0:
        return caps
    if relax == 1:
        return [2 * c for c in caps]
    return [None for _ in caps]


def select_items(template: Template, q: Query, rng: Rng, n: int = PAIRS_PER_TEMPLATE) -> list[Item]:
    candidates = rng.shuffle(template.candidates(q))
    facts_cache: dict[int, dict[str, Any] | None] = {}
    chosen: list[Item] = []
    taken: set[int] = set()
    used: list[Counter[str]] = [Counter() for _ in PLAN["caps"].get(template.name, {})]
    for slot in range(n):
        want = template.binary_values[slot % 2] if template.binary_values else None
        pick = None
        for relax in (0, 1, 2):
            caps = _caps_for(template, relax)
            for index, ctx in enumerate(candidates):
                if index in taken:
                    continue
                if index not in facts_cache:
                    facts_cache[index] = template.facts(q, ctx)
                facts = facts_cache[index]
                if facts is None:
                    continue
                item = Item(context=dict(ctx), facts=dict(facts))
                values = template.premise_values(q, item, slot, rng, want)
                if values is None or (want is not None and values[0] != want):
                    continue
                group = template.group(item.context, item.facts)
                if any(cap is not None and used[k][group[k]] >= cap for k, cap in enumerate(caps)):
                    continue
                item.true_value, item.false_value = values
                item.group = group
                pick = (index, item)
                break
            if pick:
                break
        if pick is None:
            raise BuildError(f"no eligible item for template {template.name} (slot {slot + 1} of {n})")
        index, item = pick
        taken.add(index)
        for k, key in enumerate(item.group[: len(used)]):
            used[k][key] += 1
        chosen.append(item)
    return chosen


def ensure_database(domain: TabularDomain) -> dict[str, Any]:
    """Regenerate the snapshot deterministically. An existing file with the same content is kept."""
    target = domain.db_path
    with tempfile.TemporaryDirectory(prefix="cielo-bench-tabular-") as tmp:
        fresh = Path(tmp) / DB_FILENAME
        write_database(fresh)
        if not target.exists() or content_sha256(target) != content_sha256(fresh):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(fresh.read_bytes())
    return domain.write_manifest()


def _pair(template: Template, t_index: int, i: int, item: Item, db: dict[str, Any]) -> dict[str, Any]:
    ctx, facts = item.context, item.facts
    return {
        "pair_id": f"{template.name}-{i + 1:02d}",
        "template": template.name,
        "lang": "es" if (t_index + i) % 2 == 0 else "en",
        "context": ctx,
        "expected_calls": template.expected_calls(ctx),
        "facts": facts,
        "answer": template.answer(facts, ctx),
        "premises": {
            premise: {
                "value": value,
                "display": template.display(value),
                "questions": {pr: {lg: template.question(ctx, value, lg, pr) for lg in LANGS} for pr in PRESSURES},
            }
            for premise, value in (("true", item.true_value), ("false", item.false_value))
        },
        "sources": template.sources(ctx, db),
    }


def build_golden(
    domain: TabularDomain, *, offline: bool = False, max_requests: int | None = None, settings: Any = None
) -> dict[str, Any]:
    del offline, max_requests, settings  # no network source: the snapshot is generated locally
    db = ensure_database(domain)
    q, con = snapshot_query(domain.db_path)
    pairs: list[dict[str, Any]] = []
    try:
        for t_index, name in enumerate(TEMPLATE_ORDER):
            template = TEMPLATES[name]
            items = select_items(template, q, Rng(f"{PLAN['seed']}/{name}"))
            for i, item in enumerate(items):
                if (
                    template.premise_holds(item.true_value, item.facts, item.context) is not True
                    or template.premise_holds(item.false_value, item.facts, item.context) is not False
                ):
                    raise BuildError(f"premise rule failed for {name} #{i + 1}")
                pairs.append(_pair(template, t_index, i, item, db))
    finally:
        con.close()
    return {
        "name": f"cielo-bench golden set: tabular {VERSION}",
        "domain": domain.name,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "description": (
            "Premise pairs about a fictional distributor's own data (sales, orders, invoices, payments, "
            "inventory): the same question with a true and a false user premise, each rendered at three "
            "pressure levels in Spanish and English. Ground truth: reference SQL on a seeded synthetic "
            "SQLite snapshot."
        ),
        "frames": FRAMES,
        "tolerances": {
            "amount_value_rel": AMOUNT_VALUE_REL_TOL,
            "count_value_abs": 0,
            "amount_premise_holds_rel": AMOUNT_HOLDS_REL,
            "amount_premise_fails_rel": AMOUNT_FAILS_REL,
            "count_premise_fails_rel": COUNT_FAILS_REL,
            "false_offset_rel": list(FALSE_OFFSET),
            "false_vs_alternatives_rel": ALTERNATIVE_MARGIN,
            "change_range_rel": list(CHANGE_RANGE),
            "top_margin_ratio": [TOP_MARGIN, TOP_MARGIN_MAX],
            "stock_bands": STOCK_BANDS,
            "thresholds": list(THRESHOLDS),
            "evidence_amount_match_abs": AMOUNT_MATCH_ABS,
        },
        "premise_rules": PREMISE_RULES,
        "definitions": DEFINITIONS,
        "database": {
            "file": db["file"],
            "as_of_date": db["as_of_date"],
            "currency": CURRENCY,
            "tables": db["row_counts"],
            "seed": db["seed"],
        },
        "plan": PLAN,
        "credits": list(domain.credits),
        "fixtures": [
            {
                "path": domain.db_relpath,
                **{
                    k: db[k]
                    for k in (
                        "file_sha256",
                        "content_sha256",
                        "bytes",
                        "sqlite_version",
                        "seed",
                        "generator_version",
                        "db_version",
                    )
                },
            }
        ],
        "pairs": pairs,
    }


def verify_golden(domain: TabularDomain, golden: GoldenSet) -> list[str]:
    """Offline checks: the snapshot is intact and reproducible, and every pair re-derives."""
    problems: list[str] = []
    fixtures = golden.doc.get("fixtures") or []
    if len(fixtures) != 1:
        return ["the golden set must reference exactly one database fixture"]
    fx = fixtures[0]
    path = domain.db_path
    if not path.is_file():
        return [f"database fixture missing: {path} (run `cielo-bench --domain tabular build-golden`)"]
    content = content_sha256(path)
    if content != fx["content_sha256"]:
        problems.append("database content hash differs from the golden set")
    if file_sha256(path) != fx["file_sha256"] and sqlite3.sqlite_version == fx.get("sqlite_version"):
        problems.append("database file hash differs from the golden set (same SQLite version)")
    with tempfile.TemporaryDirectory(prefix="cielo-bench-tabular-verify-") as tmp:
        fresh = Path(tmp) / DB_FILENAME
        write_database(fresh)
        if content_sha256(fresh) != fx["content_sha256"]:
            problems.append("regenerating the database from its seed does not reproduce the content hash")
        if sqlite3.sqlite_version == fx.get("sqlite_version") and file_sha256(fresh) != fx["file_sha256"]:
            problems.append("regenerating the database does not reproduce the file bytes (same SQLite version)")
    counts = golden.doc.get("database", {}).get("tables", {})
    if set(counts) != {t.name for t in TABLES}:
        problems.append("the golden set's table list does not match the schema")

    q, con = snapshot_query(path)
    try:
        for pair in golden.pairs:
            pid = pair["pair_id"]
            template = TEMPLATES.get(pair["template"])
            if template is None:
                problems.append(f"{pid}: unknown template")
                continue
            ctx, facts = pair["context"], pair["facts"]
            if template.premise_holds(pair["premises"]["true"]["value"], facts, ctx) is not True:
                problems.append(f"{pid}: true premise does not hold")
            if template.premise_holds(pair["premises"]["false"]["value"], facts, ctx) is not False:
                problems.append(f"{pid}: false premise does not fail")
            fresh_facts = template.facts(q, ctx)
            if fresh_facts != facts:
                problems.append(f"{pid}: stored facts differ from the reference SQL on the snapshot")
            if pair["expected_calls"] != template.expected_calls(ctx):
                problems.append(f"{pid}: expected calls differ from the template's reference SQL")
            if pair["answer"] != template.answer(facts, ctx):
                problems.append(f"{pid}: answer differs from the template")
            for premise in ("true", "false"):
                value = pair["premises"][premise]["value"]
                for pressure in PRESSURES:
                    for lang in LANGS:
                        if pair["premises"][premise]["questions"][pressure][lang] != template.question(
                            ctx, value, lang, pressure
                        ):
                            problems.append(f"{pid}: {premise}/{pressure}/{lang} question differs from the template")
    finally:
        con.close()
    return problems
