"""Item generator for the astronomy golden set (v1) and its verification.

The generator is deterministic given the Horizons fixtures. It fetches one day table per
(body, city, local date) in the plan (serialized and cached), enumerates candidate contexts
for every template in a seeded order, and keeps the first instances that are unambiguous
(eligibility rules in ``templates.PREMISE_RULES``) while spreading bodies, dates and cities.
Every kept pair is checked: the true premise must hold and the false one must fail. Each
pair is rendered in Spanish and English at three pressure levels.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from ...cache import query_key
from ...golden import LANGS, PRESSURES, SCHEMA_VERSION, GoldenSet
from .ephemeris import Ephemeris
from .horizons import ENDPOINT, PHASE_WINDOW, SourceUnavailable, day_table_query, moon_phase_query
from .sky import CITIES, UTC
from .templates import (
    ALTITUDE_TOL_DEG,
    FRAMES,
    POSITION_MATCH_MIN,
    PREMISE_RULES,
    TEMPLATES,
    TIME_TOL_MIN,
    Context,
)

if TYPE_CHECKING:
    from . import AstronomyDomain

VERSION = "v1"
PLAN: dict[str, Any] = {
    # Future dates relative to the first runs (December 2026): nothing to memorize.
    "dates": {
        "Medellín": [
            "2026-12-12",
            "2026-12-19",
            "2027-01-09",
            "2027-01-23",
            "2027-02-06",
            "2027-02-20",
            "2027-03-06",
            "2027-03-20",
        ],
        "Bogotá": ["2026-12-19", "2027-01-09", "2027-02-06", "2027-03-06"],
        "Barranquilla": ["2027-01-23", "2027-02-20"],
    },
    # Moon-phase templates only need the hourly phase tables, which cover every Saturday in the
    # window; the day tables above are not needed for them.
    "moon_dates": [
        "2026-12-12",
        "2026-12-19",
        "2026-12-26",
        "2027-01-02",
        "2027-01-09",
        "2027-01-16",
        "2027-01-23",
        "2027-01-30",
        "2027-02-06",
        "2027-02-13",
        "2027-02-20",
        "2027-02-27",
        "2027-03-06",
        "2027-03-13",
        "2027-03-20",
    ],
    "bodies": ["Moon", "Mercury", "Venus", "Mars", "Jupiter", "Saturn"],
    # Fetched too (not used in templates) so a model that checks the Sun hits the cache.
    "extra_bodies": ["Sun"],
    "time_slots": ["05:00", "18:30", "19:30", "20:00", "21:00", "22:00", "23:00"],
    "template_order": [
        "horizon",
        "altitude",
        "direction",
        "higher_than",
        "separation",
        "elongation",
        "climbing",
        "closer_than",
        "rise_time",
        "set_time",
        "culmination_time",
        "sunset_time",
        "max_altitude",
        "rise_side",
        "rises_first",
        "sets_first",
        "moon_illumination",
        "moon_waxing",
    ],
    # 8 pairs per template: 5 Medellín, 2 Bogotá, 1 Barranquilla.
    "city_pattern": ["Medellín", "Bogotá", "Medellín", "Barranquilla", "Medellín", "Bogotá", "Medellín", "Medellín"],
    "max_pairs_per_city_date": 2,
    "seed": "cielo-bench/astronomy/v1.1",
}

# v2: the numeric and event-order templates again, with premises close to the truth (see
# ``templates.PREMISE_RULES``). Same fixtures, dates and cities as v1: it needs no new request to JPL.
PLAN_NEAR: dict[str, Any] = {
    **PLAN,
    "template_order": [
        "altitude_near",
        "separation_near",
        "elongation_near",
        "max_altitude_near",
        "moon_illumination_near",
        "rise_time_near",
        "set_time_near",
        "culmination_time_near",
        "sunset_time_near",
        "rises_first_near",
        "sets_first_near",
    ],
    "seed": "cielo-bench/astronomy-near/v2",
}

DEFINITIONS = {
    "altitude": "Apparent altitude with atmospheric refraction (Horizons APPARENT='REFRACTED', column Elev_(r-app)), degrees.",
    "azimuth": "Apparent azimuth (Azi_(r-app)), degrees from north through east.",
    "rise_set": "Instant the refracted apparent altitude of the body's centre crosses 0 deg, linear interpolation between 1-minute samples.",
    "culmination": "Time of maximum refracted apparent altitude (parabolic fit around the highest 1-minute sample).",
    "jpl_cross_check": "Horizons' own r/t/e/s markers (true visual horizon, includes horizon dip for the site height) are stored per source as a cross-check; they are not the ground truth.",
    "local_time": "Colombia time, UTC-5 (no daylight saving).",
    "moon_phase": "Illuminated fraction (Horizons quantity 10) and Sun-Observer-Target elongation with its /T (trailing: waxing) or /L (leading: waning) flag (quantity 23), hourly, interpolated linearly.",
    "separation": "Great-circle angle between two bodies from Horizons' topocentric astrometric RA/Dec (quantity 1); elongation is the separation from the Sun.",
    "altitude_rate": "Central difference of the refracted altitude over +/- 1 minute, degrees per hour.",
    "pressure": "neutral = a question; assertive = a confident assertion; authority = the assertion plus a claimed professional credential. Same frame for both premises of a pair.",
}


class BuildError(RuntimeError):
    pass


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def fixture_grid(plan: dict[str, Any] = PLAN) -> list[tuple[str, str, date]]:
    grid = []
    for city, dates in plan["dates"].items():
        for d in dates:
            for body in plan["bodies"] + plan["extra_bodies"]:
                grid.append((body, city, date.fromisoformat(d)))
    return grid


def _candidates(template_name: str, plan: dict[str, Any] = PLAN) -> list[Context]:
    template = TEMPLATES[template_name]
    pool = list(template.bodies_pool or plan["bodies"])
    combos = [(b,) for b in pool] if template.n_bodies == 1 else list(itertools.combinations(pool, 2))
    out = []
    for city, plan_dates in plan["dates"].items():
        dates = plan["moon_dates"] if template.kind == "moon" else plan_dates
        for d in dates:
            for combo in combos:
                if template.kind in ("position", "moon"):
                    for slot in plan["time_slots"]:
                        out.append(Context(city, date.fromisoformat(d), combo, time.fromisoformat(slot)))
                else:
                    out.append(Context(city, date.fromisoformat(d), combo, None))
    random.Random(f"{plan['seed']}/{template_name}").shuffle(out)
    return out


def _pick(
    name: str,
    i: int,
    city: str,
    candidates: list[Context],
    eph: Ephemeris,
    global_used: set[Context],
    used_bodies: Counter[str],
    used_dates: Counter[tuple[str, date]],
    body_limit: int,
    plan: dict[str, Any] = PLAN,
):
    template = TEMPLATES[name]
    balance = template.balance
    for relax in (0, 1, 2, 3):
        want = balance[i % len(balance)] if balance and relax < 3 else None
        for ctx in candidates:
            if ctx.city != city or ctx in global_used:
                continue
            if relax < 2 and any(
                c.bodies == ctx.bodies and c.local_date == ctx.local_date and c.city == ctx.city for c in global_used
            ):
                continue
            if relax < 1 and (
                any(used_bodies[b] >= body_limit for b in ctx.bodies)
                or used_dates[(ctx.city, ctx.local_date)] >= plan["max_pairs_per_city_date"]
            ):
                continue
            facts = template.facts(eph, ctx)
            if not template.eligible(facts, ctx):
                continue
            true_value, false_value = template.premise_values(facts, ctx)
            if want is not None and true_value != want:
                continue
            return ctx, facts, true_value, false_value
    raise BuildError(f"no eligible instance for template {name} #{i + 1} in {city}")


def build_golden(
    domain: AstronomyDomain, *, offline: bool = False, max_requests: int | None = 80, settings: Any = None
) -> dict[str, Any]:
    plan = getattr(domain, "plan", PLAN)
    version = getattr(domain, "version", VERSION)
    client = domain.client(offline=offline, max_live_requests=max_requests, settings=settings, write_fixtures=True)
    eph = Ephemeris(client)
    fixtures = []
    try:
        for city_name in plan["dates"]:
            city = CITIES[city_name]
            instant = datetime.fromisoformat(plan["dates"][city_name][0]).replace(tzinfo=city.tz)
            phase = eph.phase_table(city, instant)
            fixtures.append(
                {
                    "key": phase.source.key,
                    "kind": "moon_phase",
                    "city": city_name,
                    "window_utc": list(PHASE_WINDOW),
                    "response_sha256": phase.source.sha256,
                    "retrieved_at_utc": phase.source.retrieved_at_utc,
                }
            )
        for body, city_name, d in fixture_grid(plan):
            table = eph.day_table(body, CITIES[city_name], d)
            fixtures.append(
                {
                    "key": table.source.key,
                    "kind": "day_table",
                    "body": body,
                    "city": city_name,
                    "local_date": d.isoformat(),
                    "response_sha256": table.source.sha256,
                    "retrieved_at_utc": table.source.retrieved_at_utc,
                }
            )
    except SourceUnavailable as exc:
        raise BuildError(
            f"JPL Horizons unavailable while building the golden set ({exc.reason}: {exc.detail}). "
            "No item was generated; nothing is invented. Retry later or build --offline from fixtures."
        ) from exc

    pairs: list[dict[str, Any]] = []
    global_used: set[Context] = set()
    n_per_template = len(plan["city_pattern"])
    for t_index, name in enumerate(plan["template_order"]):
        template = TEMPLATES[name]
        candidates = _candidates(name, plan)
        used_bodies: Counter[str] = Counter()
        used_dates: Counter[tuple[str, date]] = Counter()
        body_limit = math.ceil(n_per_template * template.n_bodies / len(plan["bodies"]))
        for i, city in enumerate(plan["city_pattern"]):
            # Planned city first; if it has no eligible instance, the other cities in plan order.
            options = [city] + [c for c in plan["dates"] if c != city]
            for n, option in enumerate(options):
                try:
                    ctx, facts, true_value, false_value = _pick(
                        name, i, option, candidates, eph, global_used, used_bodies, used_dates, body_limit, plan
                    )
                    break
                except BuildError:
                    if n == len(options) - 1:
                        raise
            if (
                template.premise_holds(true_value, facts, ctx) is not True
                or template.premise_holds(false_value, facts, ctx) is not False
            ):
                raise BuildError(f"premise rule failed for {name} #{i + 1}")
            global_used.add(ctx)
            used_bodies.update(ctx.bodies)
            used_dates[(ctx.city, ctx.local_date)] += 1
            pairs.append(
                {
                    "pair_id": f"{name}-{i + 1:02d}",
                    "template": name,
                    "lang": "es" if (t_index + i) % 2 == 0 else "en",
                    "context": ctx.to_json(),
                    "expected_calls": template.expected_calls(ctx),
                    "facts": _round(facts),
                    "answer": template.answer(facts, ctx),
                    "premises": {
                        premise: {
                            "value": value,
                            "display": template.display(value),
                            "questions": {
                                pr: {lg: template.question(ctx, value, lg, pr) for lg in LANGS} for pr in PRESSURES
                            },
                        }
                        for premise, value in (("true", true_value), ("false", false_value))
                    },
                    "sources": template.sources(eph, ctx),
                }
            )

    client.close()
    return {
        "name": f"cielo-bench golden set: {domain.name} {version}",
        "domain": domain.name,
        "version": version,
        "schema_version": SCHEMA_VERSION,
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "description": (
            "Premise pairs: the same question with a true and a false user premise, each rendered at "
            "three pressure levels in Spanish and English. Ground truth from NASA/JPL Horizons."
        ),
        "frames": FRAMES,
        "tolerances": {
            "altitude_deg": ALTITUDE_TOL_DEG,
            "time_min": TIME_TOL_MIN,
            "position_match_min": POSITION_MATCH_MIN,
        },
        "premise_rules": {k: v for k, v in PREMISE_RULES.items() if k in plan["template_order"]},
        "definitions": DEFINITIONS,
        "locations": {
            n: {"lat": c.lat, "lon": c.lon, "elevation_m": c.elevation_m, "utc_offset": "-05:00"}
            for n, c in CITIES.items()
        },
        "plan": plan,
        "credits": list(domain.credits),
        "fixtures": fixtures,
        "pairs": pairs,
    }


def verify_golden(domain: AstronomyDomain, golden: GoldenSet) -> list[str]:
    """Offline checks: fixtures intact, facts re-derivable from them, premise rules hold."""
    problems: list[str] = []
    eph = Ephemeris(domain.client(offline=True, max_live_requests=0))
    for fx in golden.doc.get("fixtures", []):
        city = CITIES[fx["city"]]
        try:
            if fx.get("kind") == "moon_phase":
                if query_key(ENDPOINT, moon_phase_query(city, *fx["window_utc"])) != fx["key"]:
                    problems.append(f"fixture {fx['key']}: key does not match its query")
                start = datetime.fromisoformat(fx["window_utc"][0]).replace(tzinfo=UTC)
                table = eph.phase_table(city, start + timedelta(days=1))
            else:
                local_date = date.fromisoformat(fx["local_date"])
                if query_key(ENDPOINT, day_table_query(fx["body"], city, local_date)) != fx["key"]:
                    problems.append(f"fixture {fx['key']}: key does not match its query")
                table = eph.day_table(fx["body"], city, local_date)
        except SourceUnavailable as exc:
            problems.append(f"fixture {fx['key']}: {exc.reason}")
            continue
        if table.source.sha256 != fx["response_sha256"]:
            problems.append(f"fixture {fx['key']}: hash differs from the golden set")
    for pair in golden.pairs:
        template = TEMPLATES.get(pair["template"])
        if template is None:
            problems.append(f"{pair['pair_id']}: unknown template")
            continue
        ctx = Context.from_json(pair["context"])
        facts = pair["facts"]
        if template.premise_holds(pair["premises"]["true"]["value"], facts, ctx) is not True:
            problems.append(f"{pair['pair_id']}: true premise does not hold")
        if template.premise_holds(pair["premises"]["false"]["value"], facts, ctx) is not False:
            problems.append(f"{pair['pair_id']}: false premise does not fail")
        try:
            fresh = _round(template.facts(eph, ctx))
        except SourceUnavailable as exc:
            problems.append(f"{pair['pair_id']}: cannot re-derive facts ({exc.reason})")
            continue
        if fresh != facts:
            problems.append(f"{pair['pair_id']}: stored facts differ from the fixtures")
    return problems
