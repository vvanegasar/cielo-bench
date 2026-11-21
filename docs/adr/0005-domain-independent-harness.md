# ADR-0005 — A domain-independent harness, local tool executors, astronomy as domain 1

- Status: Accepted · 2026-11-19 (proposed 2026-11-18; accepted by Valentina Vanegas)
- Builds on: ADR-0001 (benchmark first). Deviates from: ADR-0002 (provider SDKs), the v0 tool list in `docs/TOOLS.md`, the User-Agent line in `docs/DATA-SOURCES.md`. The change of the MCP server from TypeScript on Workers to Python is recorded in the server's own ADR.

## Context

The research question is "Check or agree? Does a tool-using agent verify a user's claim, or agree with it?". Answering it needs:

- the same items with and without the tool;
- true and false user premises;
- graded user pressure;
- tool failures;
- deterministic ground truth, with no LLM judge;
- statistics that respect dependent items.

It started as a pilot and became v1, a complete, reproducible benchmark to be published from a personal account. It must not be tied to one domain: the choice of domain has to be justified by method, and a business-relevant domain must plug in without changes to the rest.

## Decisions

### 1. The harness is domain-independent

`evals/cielo_bench/domain.py` defines a `Domain` interface with four parts:

1. **item generator**: builds the golden set of premise pairs, tagged by template (the statistical cluster);
2. **tools**: provider-neutral definitions plus an executor with the fault kinds `down`, `error` and `empty`;
3. **ground truth and tolerances**: `premise_holds(pair, value, facts)`, with explicit margins;
4. **evidence**: `evidence(pair, trace)`, which reports which expected checks were attempted and succeeded, and the facts they returned.

The runner, the providers, the scorer, the statistics and the report only talk to this interface. So does the simulated model, which therefore works for any domain. One tool-result contract holds everywhere: `status` in `ok | invalid_input | source_unavailable | out_of_scope`, and a non-`ok` result carries no values. Domains are registered with one line in `domains/__init__.py`.

### 2. Why astronomy is domain 1 (method, not taste)

| Requirement | Astronomy (JPL Horizons) |
|---|---|
| Exact, external, computable ground truth | Positions and rise/set times are computed by NASA/JPL from planetary ephemerides; no annotator or model decides the answer |
| **Cannot be memorized** | The answer depends on body, date, time and place (here future dates in three Colombian cities), so it is in no training set. The no-tool condition measures inference, not recall, and contamination is limited by construction |
| Clear tolerances | Physical units (degrees, minutes); false premises are far from the truth, so verdicts are unambiguous |
| No LLM judge | A fixed verdict line plus a number compared with the truth; scoring is deterministic |
| Same item with and without the tool | Natural: the tool answers exactly the question asked |
| Honest failure is testable | The source can be made unavailable, and the correct behaviour is well defined: say so and state no number |

The domain is a domain novelty, not the contribution. The contribution is the design: toggling the tool on identical items, grading user pressure, and measuring agreement **after** the tool returned contrary evidence (*agree-after-check*).

### 3. Why not only astronomy

Astronomy has low stakes for businesses. External validity for companies comes from **domain 2, tabular company data**: a seeded synthetic SQLite database and a read-only SQL tool. This is the real situation of an agent working on a client's data that agrees with the user although the query says otherwise. It is built by another contributor in `domains/tabular/`, on this interface.

**Domain 3 (option): official statistics** (World Bank API, DANE). Real figures, but models may have memorized them, and the truth must be pinned to a dated vintage. It also adds an upstream source, so it needs its own ADR and a terms check.

### 4. Tools are local executors

- `body_position` follows the TOOLS.md contract, with `location` restricted to the built-in city table (Medellín, Bogotá, Barranquilla) so model calls hit the cached fixtures.
- `body_rise_set` is **new**: rise, culmination and set for one local date. This ADR is the record that rule 6 requires.
- `moon_phase`, `body_position.relative_to` (angular separation), `altitude_rate_deg_per_hour` and the rise/set azimuth were added for v1's 18 templates; they are recorded in ADR-0008. The domain stays at 3 tools.
- `sky_tonight` and `object_lookup` are deferred, and SIMBAD is not used.
- The executors are plain Python, called in-process by the harness. The MCP server in `server/` wraps the same executors, so both paths give the same answers.

### 5. Model calls over plain HTTP (deviation from ADR-0002)

`httpx` for every provider: Anthropic Messages, OpenAI Chat Completions, OpenRouter, Ollama and any other compatible endpoint. Dependencies stay minimal, every raw response is logged exactly, and all providers share one code path with retries, rate limiting and an output cache.

- Anthropic: `anthropic-version: 2026-10-21`; no sampling parameters; assistant content is passed back unchanged across tool rounds.
- **No server-side refusal fallbacks**: every trial must be attributable to one pinned model. Refusals are recorded.
- Keys come **only** from `CIELO_*` settings (the local `.env`); generic variables such as `ANTHROPIC_API_KEY` are ignored (tested).

### 6. Ground truth from 1-minute Horizons tables

- One observer table per (body, city, local date), from local midnight to local midnight: 98 tables (plus 3 hourly Moon-phase tables, ADR-0008), fetched in series, cached under a normalized-query key with the SHA-256 of each response, and logged.
- Altitude and azimuth are refracted apparent values. **Rise and set are the moment the refracted altitude of the body's centre crosses 0°.** Horizons' own markers, which use the true visual horizon including dip, are kept as a cross-check; in Medellín they differ by about 4 to 6 minutes.
- If Horizons fails, the result is `source_unavailable`, never invented. A golden-set build fails rather than write an item without data.

### 7. Conditions, pressure and faults

- Core: (`no_tool` | `tool`) × (true | false premise) × (`neutral` | `assertive` | `authority` pressure). The frames are nested, so each adds one ingredient; both premises use the same frame.
- Faults: `fault_down`, `fault_error` and `fault_empty` × premise, at assertive pressure by default.
- Deferred: multi-turn insistence, group (Asch-style) pressure, and acting vs. answering.

### 8. User-Agent without personal data (deviation from DATA-SOURCES)

`cielo-bench/<version> (non-commercial research benchmark)`, overridable with `CIELO_USER_AGENT`. The repository URL can be added once it is public; a personal email is never added.

### 9. TLS

The certifi CA bundle is used by default, because a machine-wide `SSL_CERT_FILE` may lack an upstream's root (it lacked JPL's on the development machine). `CIELO_CA_BUNDLE` selects another bundle. Verification is never disabled.

## Consequences

- `cielo-bench reproduce --simulated` runs end to end without network or keys. Real runs need only a personal `.env`.
- Results refer to "a model with these tools, called in-process". The MCP path is a separate measurement and can be compared with it.
- A second domain is an addition, not a rewrite.
- The statistical precision is bound by the number of templates. Adding templates helps more than adding pairs, which is why astronomy grew from 8 to 18 templates (ADR-0008; see `docs/EVALS.md` §5).
