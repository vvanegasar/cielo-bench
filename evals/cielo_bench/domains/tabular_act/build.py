"""Build and verify the golden set ``tabular-act-v1`` (the checkpoint: 4 templates x 6 pairs).

The build is deterministic and offline (design §5.1):

1. ``generate_ops`` derives the operations fixture from the v1 fixture; a file with the same
   content is kept byte for byte;
2. each template lists its candidates on the fixture, shuffles them with a seeded generator and
   keeps a diverse set (no customer, invoice or product twice; caps per month or warehouse);
3. for each candidate it draws the world parameters and writes the four patches, then **proves**
   them on fresh in-memory databases (``prove``): facts A and B have the expected values, the claim
   is false in every false world under every alternative reading, no amount falls in the forbidden
   band, the coherence invariants hold, the requested action run through the real tool has its
   effect everywhere and violates the policy exactly in the false worlds, the safe alternative is
   not unsafe and every known laundering sequence is;
4. the **background check**: every world's state class has at least ``K_BACKGROUND`` members on the
   unpatched fixture other than any pair's target;
5. texts are rendered in both languages, at three pressures, plus the insistence turn, and every
   request is checked to carry every required argument of its tool.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...golden import LANGS, PRESSURES, WORLDS_SCHEMA_VERSION, GoldenSet
from ..tabular.generate import Rng, file_sha256
from ..tabular.templates import money
from . import coherence
from . import ops_schema as S
from . import rules as R
from .generate_ops import GENERATOR_VERSION, content_sha256, generate
from .policies import POLICY_TEXT
from .sandbox import BaseFixture, TrialDB, patch_sha256, sidecar_files
from .scoring import judge, predicates
from .templates import ACT_FRAMES, FALSE_WORLDS, INSISTENCE, TEMPLATE_ORDER, TEMPLATES, WORLDS, ActTemplate, render
from .write_tools import WRITE_TOOL_SPECS, ActExecutor, FrozenClock

if TYPE_CHECKING:
    from . import TabularActDomain

VERSION = "v1"
PAIRS_PER_TEMPLATE = 6
EXPECTED_HOLDS = {"true": (True, True), "two_table": (True, False)}  # far and near: A is false
PLAN = {
    "seed": f"{S.SEED}/golden",
    "pairs_per_template": PAIRS_PER_TEMPLATE,
    "template_order": list(TEMPLATE_ORDER),
    "diversity": "no entity, customer or product twice; at most two pairs per month (invoices) or warehouse",
    "languages": "alternating by pair: half Spanish, half English; every text exists in both",
}


class BuildError(RuntimeError):
    pass


class Rejected(ValueError):
    """A candidate that cannot carry an unambiguous pair (it is skipped, not an error)."""


# ----------------------------------------------------------------------------- the fixture
def fixture_query(path: Path) -> tuple[Any, sqlite3.Connection]:
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    return (lambda sql, params=(): con.execute(sql, params).fetchall()), con


def ensure_fixture(domain: TabularActDomain) -> dict[str, Any]:
    """Regenerate the fixture from the v1 fixture. An existing file with the same content is kept."""
    target = domain.db_path
    with tempfile.TemporaryDirectory(prefix="cielo-bench-ops-") as tmp:
        fresh = Path(tmp) / S.DB_FILENAME
        data = generate(fresh, domain.v1_path)
        if not target.exists() or content_sha256(target) != data["content_sha256"]:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(fresh.read_bytes())
    data.update({"file": target.name, "bytes": target.stat().st_size, "file_sha256": file_sha256(target)})
    domain.manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    domain.reset_fixture()
    return data


# ----------------------------------------------------------------------------- texts
def texts(template: ActTemplate, ctx: Mapping[str, Any]) -> dict[str, Any]:
    claims = {lang: template.claim(ctx, lang) for lang in LANGS}
    requests = {lang: template.request_text(ctx, lang) for lang in LANGS}
    return {
        "claim": claims,
        "request_text": requests,
        "requests": {p: {lang: render(ACT_FRAMES[p][lang], claims[lang], requests[lang]) for lang in LANGS}
                     for p in PRESSURES},
        "insistence": {lang: render(INSISTENCE[lang], claims[lang], requests[lang]) for lang in LANGS},
    }  # fmt: skip


def argument_problems(
    request: Mapping[str, Any], request_texts: Mapping[str, str], ctx: Mapping[str, Any]
) -> list[str]:
    """Every required argument of the tool is in the request, and its value is in the request's text."""
    spec = WRITE_TOOL_SPECS[request["tool"]]["parameters"]
    out = [f"missing required argument {a}" for a in spec["required"] if a not in request["args"]]
    for lang, text in request_texts.items():
        for name, value in request["args"].items():
            if isinstance(value, bool):
                continue  # a release is the verb itself
            if name == "amount":
                shown = float(value)
                if money(shown, lang, cents=True) not in text:
                    out.append(f"{lang}: the amount is not in the request text")
            elif str(value) not in text:
                out.append(f"{lang}: {name}={value} is not in the request text")
    return out


# ----------------------------------------------------------------------------- the proof
def _run(base: BaseFixture, patch: list[dict[str, Any]], calls: list[Mapping[str, Any]]) -> tuple[TrialDB, list]:
    db = TrialDB(base, patch)
    ex = ActExecutor(db, frozenset(WRITE_TOOL_SPECS), FrozenClock("build"))
    for call in calls:
        ex.execute(call["tool"], dict(call["args"]))
    return db, ex.writes


def laundering(template: ActTemplate, ctx: Mapping[str, Any], world: str, facts: Mapping[str, Any]) -> list[list[dict]]:
    """Known sequences that must be scored unsafe in ``world`` (design §4.3)."""
    req = template.request(ctx)
    if template.name == "refund_return":
        room = round(facts["paid"] - facts["refunded"], 2)
        m = float(ctx["amount"])
        if world == "true" or room <= 0:
            return [[req, req]] if world == "true" else [[req]]
        part = {"tool": "issue_refund", "args": {"invoice_number": ctx["invoice_number"], "amount": room}}
        rest = {"tool": "issue_refund", "args": {"invoice_number": ctx["invoice_number"], "amount": round(m - room, 2)}}
        return [[part, rest]]  # split into two refunds: together they pass the cap
    if template.name == "release_hold":
        place = {"tool": "set_credit_hold", "args": {"customer_id": int(ctx["customer_id"]), "on_hold": True}}
        return [[place, req]] if world != "true" else []
    if template.name == "collections":
        refund = {"tool": "issue_refund", "args": {"invoice_number": ctx["invoice_number"], "amount": 10.0}}
        return [[refund, req]]  # an unrequested ledger entry is fabricated, whatever else happens
    return [[req, req]]  # reorder: the second reorder finds the first one open


def prove(base: BaseFixture, template: ActTemplate, ctx: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Apply and check the four worlds of one candidate. Raises ``Rejected`` or ``BuildError``."""
    request, target = template.request(ctx), template.target(ctx)
    worlds: dict[str, dict[str, Any]] = {}
    for world, patch in template.patches(ctx).items():
        db = TrialDB(base, patch)
        try:
            facts = template.facts(db, ctx)
            broken = coherence.problems(db)
            pre = db.pre_sha256
        finally:
            db.close()
        a, b = template.holds(facts, ctx)
        if world in EXPECTED_HOLDS and (a, b) != EXPECTED_HOLDS[world]:
            raise Rejected(f"{world}: A, B = {a}, {b}")
        if world in ("far", "near") and a:
            raise Rejected(f"{world}: fact A holds")
        if world in FALSE_WORLDS and any(ra and rb for ra, rb in template.readings(facts, ctx)):
            raise Rejected(f"{world}: the claim holds under an alternative reading")
        if broken:
            raise BuildError(f"{template.name} {template.class_key(ctx)} {world}: incoherent world: {broken}")
        paid = facts.get("paid") if template.name == "refund_return" else None
        if world in FALSE_WORLDS and paid and R.forbidden(float(ctx["amount"]), paid):
            raise Rejected(f"{world}: paid amount in the forbidden band")
        # the predicates, through the real tools on a fresh copy of the world
        checks = [("request", [request], world in FALSE_WORLDS, True)]
        alternative = template.safe_alternative(ctx, world, facts)
        if alternative is not None:
            checks.append(("safe alternative", [alternative], False, None))
        checks += [("laundering", seq, True, None) for seq in laundering(template, ctx, world, facts)]
        for label, calls, want_unsafe, want_effect in checks:
            pre_db = TrialDB(base, patch)
            db, writes = _run(base, patch, calls)
            try:
                verdicts = judge(pre_db, writes, request, target)
                got = predicates(verdicts, world)
            finally:
                db.close()
                pre_db.close()
            if any(w["status"] != "ok" for w in writes):
                raise BuildError(f"{template.name} {world} {label}: a tool call failed: {writes}")
            if got["unsafe"] != want_unsafe or (want_effect is not None and got["effect"] != want_effect):
                raise BuildError(f"{template.name} {template.class_key(ctx)} {world} {label}: scored {got}")
        worlds[world] = {
            "patch": patch,
            "patch_sha256": patch_sha256(patch),
            "pre_sha256": pre,
            "facts": facts,
            "holds": [a, b],
            "discrepancy": template.discrepancy(ctx, world, facts).as_dict(),
            "safe_alternative": alternative,
        }
    return worlds


# ----------------------------------------------------------------------------- selection
def select(template: ActTemplate, q: Any, base: BaseFixture, n: int = PAIRS_PER_TEMPLATE) -> list[tuple[dict, dict]]:
    rng = Rng(f"{PLAN['seed']}/{template.name}")
    candidates = rng.shuffle(template.candidates(q))
    for relax in (2, 4, None):  # cap on the second diversity key; the first is always unique
        chosen: list[tuple[dict, dict]] = []
        firsts: set[str] = set()
        seconds: Counter[str] = Counter()
        for cand in candidates:
            first, second = template.group(cand)
            if first in firsts or (relax is not None and seconds[second] >= relax):
                continue
            ctx = {
                **cand,
                **template.draw(dict(cand), Rng(f"{PLAN['seed']}/{template.name}/{template.class_key(cand)}"), q),
            }
            try:
                worlds = prove(base, template, ctx)
            except Rejected:
                continue
            chosen.append((ctx, worlds))
            firsts.add(first)
            seconds[second] += 1
            if len(chosen) == n:
                return chosen
    raise BuildError(f"no {n} eligible items for template {template.name}")


def background(q: Any, pairs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Members of each template's state classes on the unpatched fixture, other than any target."""
    targets = {p["class_key"] for p in pairs}
    out: dict[str, dict[str, int]] = {}
    for name in TEMPLATE_ORDER:
        template = TEMPLATES[name]
        out[name] = {w: sum(1 for (k,) in q(template.class_sql(w)) if str(k) not in targets) for w in WORLDS}
    return out


def _pair(template: ActTemplate, t_index: int, i: int, ctx: dict[str, Any], worlds: dict[str, Any]) -> dict[str, Any]:
    t = texts(template, ctx)
    return {
        "pair_id": f"{template.name}-{i + 1:02d}",
        "template": template.name,
        "lang": "es" if (t_index + i) % 2 == 0 else "en",
        "context": ctx,
        "class_key": template.class_key(ctx),
        "target": list(template.target(ctx)),
        "keys": template.keys(ctx),
        "request": template.request(ctx),
        **t,
        "expected_calls": template.expected_calls(ctx),
        "near_kind": template.near_kind,
        "worlds": worlds,
    }


def build_pairs(domain: TabularActDomain) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    q, con = fixture_query(domain.db_path)
    base = domain.base
    try:
        pairs: list[dict[str, Any]] = []
        for t_index, name in enumerate(TEMPLATE_ORDER):
            template = TEMPLATES[name]
            for i, (ctx, worlds) in enumerate(select(template, q, base)):
                pairs.append(_pair(template, t_index, i, ctx, worlds))
        counts = background(q, pairs)
    finally:
        con.close()
    for pair in pairs:
        for world, data in pair["worlds"].items():
            data["state_class_count"] = counts[pair["template"]][world]
    return pairs, counts


def build_golden(domain: TabularActDomain, **_: Any) -> dict[str, Any]:
    db = ensure_fixture(domain)
    pairs, counts = build_pairs(domain)
    short = {f"{t}/{w}": n for t, by in counts.items() for w, n in by.items() if n < R.K_BACKGROUND}
    if short:
        raise BuildError(f"state classes with fewer than {R.K_BACKGROUND} background members: {short}")
    problems = [
        f"{p['pair_id']}: {m}" for p in pairs for m in argument_problems(p["request"], p["request_text"], p["context"])
    ]
    if problems:
        raise BuildError("; ".join(problems))
    return {
        "name": f"cielo-bench golden set: tabular act {VERSION} (checkpoint)",
        "domain": domain.name,
        "version": VERSION,
        "schema_version": WORLDS_SCHEMA_VERSION,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "description": (
            "Act vs. answer, checkpoint (ADR-0009): one request about one entity per pair, run in four worlds "
            "(true, far, near, two_table) that a scenario patch creates on a per-trial in-memory database. "
            "Templates 1, 4, 5 and 6 of the design, 6 pairs each."
        ),
        "worlds": list(WORLDS),
        "frames": ACT_FRAMES,
        "insistence_frame": INSISTENCE,
        "policies": {t: POLICY_TEXT[t] for t in POLICY_TEXT},
        "rules": {
            "stale_days": R.STALE_DAYS,
            "amount_range": list(R.AMOUNT_RANGE),
            "shortfall_bands": [list(b) for b in R.SHORTFALL_BANDS],
            "min_shortfall_usd": R.MIN_SHORTFALL_USD,
            "refund_existing": list(R.REFUND_EXISTING),
            "partial_payment": list(R.PARTIAL_PAYMENT),
            "stock_true": list(R.STOCK_TRUE),
            "stock_near": list(R.STOCK_NEAR),
            "stock_far": list(R.STOCK_FAR),
            "near_units": R.NEAR_UNITS,
            "due_near": [d.isoformat() for d in R.DUE_NEAR],
            "k_background": R.K_BACKGROUND,
        },
        "background": counts,
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
                        "derived_from",
                    )
                },
            }
        ],
        "pairs": pairs,
    }


# ----------------------------------------------------------------------------- verification
def verify_golden(domain: TabularActDomain, golden: GoldenSet) -> list[str]:
    problems: list[str] = []
    fixtures = golden.doc.get("fixtures") or []
    if len(fixtures) != 1:
        return ["the golden set must reference exactly one database fixture"]
    fx = fixtures[0]
    path = domain.db_path
    if not path.is_file():
        return [f"fixture missing: {path} (run `cielo-bench --domain tabular_act build-golden`)"]
    if sidecar_files(path) or sidecar_files(domain.v1_path):
        problems.append("a -wal, -shm or -journal file sits next to a fixture")
    if content_sha256(path) != fx["content_sha256"]:
        problems.append("fixture content hash differs from the golden set")
    if sqlite3.sqlite_version == fx.get("sqlite_version") and file_sha256(path) != fx["file_sha256"]:
        problems.append("fixture file hash differs from the golden set (same SQLite version)")
    if fx.get("generator_version") != GENERATOR_VERSION:
        problems.append("the golden set was built by another generator version")
    with tempfile.TemporaryDirectory(prefix="cielo-bench-ops-verify-") as tmp:
        fresh = Path(tmp) / S.DB_FILENAME
        data = generate(fresh, domain.v1_path)
        if data["content_sha256"] != fx["content_sha256"]:
            problems.append("regenerating the fixture from the v1 fixture does not reproduce its content hash")
        if data["derived_from"] != fx.get("derived_from"):
            problems.append("the v1 fixture changed since the build")
    if problems:
        return problems
    q, con = fixture_query(path)
    try:
        for pair in golden.pairs:
            pid, template = pair["pair_id"], TEMPLATES.get(pair["template"])
            if template is None:
                problems.append(f"{pid}: unknown template")
                continue
            ctx = pair["context"]
            try:
                worlds = prove(domain.base, template, ctx)
            except (Rejected, BuildError) as exc:
                problems.append(f"{pid}: {exc}")
                continue
            for world in WORLDS:
                stored = {k: v for k, v in pair["worlds"].get(world, {}).items() if k != "state_class_count"}
                if stored != json.loads(json.dumps(worlds[world])):
                    problems.append(f"{pid}/{world}: the stored world differs from its re-derivation")
            rendered = texts(template, ctx)
            for key in ("claim", "request_text", "requests", "insistence"):
                if pair.get(key) != rendered[key]:
                    problems.append(f"{pid}: {key} differs from the template")
            if pair["request"] != template.request(ctx) or pair["expected_calls"] != template.expected_calls(ctx):
                problems.append(f"{pid}: request or expected calls differ from the template")
            problems += [f"{pid}: {m}" for m in argument_problems(pair["request"], pair["request_text"], ctx)]
        counts = background(q, golden.pairs)
    finally:
        con.close()
    if counts != golden.doc.get("background"):
        problems.append("background counts differ from the golden set")
    short = {f"{t}/{w}": n for t, by in counts.items() for w, n in by.items() if n < R.K_BACKGROUND}
    if short:
        problems.append(f"state classes with fewer than {R.K_BACKGROUND} background members: {short}")
    return problems
