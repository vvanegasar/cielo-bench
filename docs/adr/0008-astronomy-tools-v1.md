# ADR-0008 — Astronomy tools for v1: Moon phase, angular separation, altitude rate, rise/set azimuth

- Status: Accepted · 2026-11-19 (proposed 2026-11-19; accepted by Valentina Vanegas)
- Builds on: ADR-0005 (domain-independent harness) and ADR-0007 (Python MCP server). The contribution rules (CONTRIBUTING.md) require an ADR for every new tool.

## Context

With 8 templates, the minimum detectable paired difference was 15 to 30 percentage points, and some effects were not detectable at all with an intra-template correlation of 0.2. Precision is bound by the number of templates (clusters), not by the number of pairs (EVALS.md §5). To reach at least 16 templates, the astronomy domain needs question types whose answers its tools did not expose:

- the Moon's phase;
- the angle between two bodies, or between a planet and the Sun;
- whether a body is still climbing;
- on which side of due east a body rises.

The constraints were:

- at most 3 tools;
- ground truth read from NASA/JPL Horizons rather than recomputed by us wherever Horizons provides it;
- no more than 200 upstream requests in total.

## Decision

1. **New tool `moon_phase(location, datetime)`**, the third and last astronomy tool.
   - It returns `illuminated_fraction_pct`, `phase` (`waxing` | `waning`) and `sun_moon_elongation_deg`.
   - The source is Horizons quantity 10 (illuminated fraction) and quantity 23 (Sun–Observer–Target elongation with its `/T` trailing or `/L` leading flag; `/T` means waxing), in one hourly table per city covering 2026-12-11 to 2027-03-22. Values are interpolated linearly between hours.
   - Other dates use a 10-day window around the instant, fetched live into the live cache, never into the fixtures.
2. **`body_position.relative_to`** (optional, another body). It adds `separation_deg`, the great-circle angle between the two bodies from Horizons' topocentric astrometric RA/Dec (quantity 1), and cites both sources.
   - A separate `angular_separation` tool was rejected because it would be a fourth tool.
   - Leaving the angle to the model (from two RA/Dec readings) was rejected because it would measure the model's spherical trigonometry, not whether it checks.
3. **`body_position.altitude_rate_deg_per_hour`**, always present: the central difference of the refracted altitude over ±1 minute. Positive means the body is climbing.
4. **`azimuth_deg` on `body_rise_set`'s `rise` and `set`**, interpolated at the same instant as the 0° crossing.
5. **Ten new templates**, 18 in total:
   - `separation`, `elongation`, `climbing`, `closer_than`;
   - `sunset_time`, `max_altitude`, `rise_side`, `sets_first`;
   - `moon_illumination`, `moon_waxing`.

   Each template has 8 pairs, 144 in total. Binary templates are balanced 4/4. Rules and tolerances are in EVALS.md §1.
6. **Upstream cost**: 3 new Horizons requests, the Moon-phase tables, for 102 in total. Every other new template reads the 98 day tables already cached.
7. **`Domain.external_source`**:
   - True for astronomy, False for the tabular domain.
   - The MCP server sets `openWorldHint` only for tools of domains with an external source, and only in `--live` mode. This implements item 4 of ADR-0007's open points.
8. **Citation rule in the core contract.** `cielo_bench.domain.contract_problems` states that every `ok` result has a non-empty `sources` list naming `service`, `query` and `retrieved_at_utc`, and that any other result carries no values. A core test checks it on every expected call of every pair of every registered domain, and on the three fault kinds.

## Consequences

- The astronomy domain still has 3 tools. All changes are additive, and earlier tool calls keep working.
- Golden set v1 was rebuilt; it has a new SHA-256 (`418b7670…`).
- The MCP server serves the new tool and fields without changes, because it reads `tool_specs()`. Contracts are in `docs/TOOLS.md`.
- The minimum detectable paired difference for a single-condition contrast drops to 12–16 pp (ψ = 20 %) and 17–22 pp (ψ = 40 %), at intra-template correlations of 0.05–0.20 (EVALS.md §5).
- Two definitions are computed by us from Horizons outputs rather than read directly: separation (exact spherical geometry on Horizons' RA/Dec) and altitude rate (finite difference). Both are documented in the golden set's `definitions`.
