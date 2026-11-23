# Tool contracts — `cielo` MCP server

This page documents what exists today. The tools are the benchmark's own (`evals/cielo_bench/domains/`, ADR-0005). The `cielo` MCP server in [`server/`](../server/) exposes them unchanged to any MCP client (ADR-0007). The harness calls the same executors in-process, so both paths give the same answers.

## How tools reach MCP

- **Discovery.** Every domain in `cielo_bench.domains.REGISTRY` that loads is served. A registered domain that cannot be loaded or set up is skipped and listed under "Registered but not served" in `cielo://about`.
- **Definition.** A tool is its domain's spec: the name, description and input JSON Schema exactly as the domain declares them. The benchmark hands the same specs to model APIs.
- **Name.** The domain's tool name. If two domains use the same name, both are exposed as `<domain>_<tool>`.
- **Annotations.** `readOnlyHint: true` on every tool. `openWorldHint: true` only when the server runs with `--live` and the domain can reach a source outside the machine (`Domain.external_source`).
- **Arguments.** They are passed to the domain's executor exactly as received, and the executor validates them. A JSON object sent as a string is not repaired: it is `invalid_input`, as in the benchmark.

## Result contract (every domain)

- Every result is a JSON object whose `status` is `ok`, `invalid_input`, `source_unavailable` or `out_of_scope`.
- An `ok` result carries the values plus `sources[]`, a citation per source with `service`, `query` and `retrieved_at_utc` (UTC). A domain may add more, as astronomy adds `endpoint` and `response_sha256` and a `credit` line.
- Any other status carries **no values**: only `status`, a `message`, and `source` and `reason` when a source failed. Nothing partial, nothing invented.
- Over MCP:
  - `structuredContent` is the result object;
  - the content is one text block with the same object, `json.dumps(result, ensure_ascii=False)`, byte-identical to what the benchmark sends to models;
  - `isError` is true for every status except `ok`;
  - `outputSchema` is the contract above, the same for every tool.
- The server refuses to send a result that breaks the contract: an `ok` without a full citation, a failure with values, or an unknown status. The client gets a generic tool error instead.
- An unknown tool name is not a domain result: the SDK answers with an error result (`isError`, text `Unknown tool: <name>`, no `structuredContent`).
- `reason` values (astronomy):
  - cache: `offline_cache_miss`, `cache_integrity_error`;
  - network: `network_error`, `timeout`, `http_<code>`;
  - bad answers from the source: `empty_response`, `malformed_response`, `no_ephemeris`, `upstream_error`;
  - the request cap: `request_budget_exhausted`.

## Modes

| Mode | Flag | Behaviour |
|---|---|---|
| Cache only | default | Tools answer from what is already cached: the benchmark's committed fixtures, then the live cache. Nothing leaves the machine. Anything not cached returns `source_unavailable` with reason `offline_cache_miss` |
| Live | `--live` | Tools may query the upstream source. For JPL: one request at a time per process, at least 1 s apart, retries with backoff, every response cached by query in the live cache. Generic User-Agent, no personal data. At most 100 requests per process by default (`--max-live-requests`) |

**Live cache.** Live responses are written to `--cache-dir`, else `CIELO_CACHE_DIR`, else `$XDG_CACHE_HOME/cielo-bench`, else `~/.cache/cielo-bench`, and their request log goes there too. They are never written to the repository's fixtures, which only `cielo-bench build-golden` writes. The server passes the directory to the core as the `CIELO_CACHE_DIR` setting.

The server never injects faults. The tests put a source down through `build_server(executor_factory=...)`.

---

## Domain `astronomy` — NASA/JPL Horizons

Locations come from a built-in table: Medellín, Bogotá and Barranquilla, all Colombia time (UTC−5, no daylight saving). No geocoding service is used. The executor also accepts Spanish and unaccented names (`Saturno`, `medellin`); the schema advertises the canonical ones.

### `body_position`

Where a solar-system body is in the sky at a given instant, seen from a city.

| Input | Type | Required | Notes |
|---|---|---|---|
| `body` | enum: Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune | yes | |
| `location` | `{ "city": <enum> }` | yes | No other properties |
| `datetime` | string, ISO 8601 | yes | Without a UTC offset it is read as local time in the city |
| `relative_to` | same enum, another body | no | Adds the angular separation between the two bodies |

**Output:**
- `body`, `location` (`city`, `lat`, `lon`, `elevation_m`), `datetime_utc`, `datetime_local`;
- `altitude_deg` (apparent, with refraction; negative is below the horizon) and `azimuth_deg` (from north through east);
- `altitude_rate_deg_per_hour` (positive while the body climbs);
- `ra_hours`, `dec_deg`, `distance_au`, `above_horizon`, `interpolated` (true between whole minutes);
- with `relative_to`: `relative_to` and `separation_deg`, plus one citation per body;
- `notes`, `sources[]`, `credit`.

### `body_rise_set`

Rise, culmination and set of a body on one local calendar date, seen from a city.

| Input | Type | Required | Notes |
|---|---|---|---|
| `body` | same enum | yes | |
| `location` | `{ "city": <enum> }` | yes | |
| `date` | string, `YYYY-MM-DD` | yes | Local calendar date |

**Output:** `body`, `location`, `date_local`; `rise`, `culmination` and `set`, each `{ local, local_time, utc }` or `null` when the event does not happen that date (`rise` and `set` add `azimuth_deg`, where on the horizon; `culmination` adds `altitude_deg`); `definition`, `sources[]`, `credit`.

**Definitions** (ADR-0005 §6): rise and set are the instant the refracted apparent altitude of the body's centre crosses 0°; culmination is the maximum refracted altitude. Both come from 1-minute Horizons samples. The first rise and the first set of the date are reported, so a set can come before the rise (for example, a body that set at 01:14 and rises again at 13:07).

### `moon_phase`

The phase of the Moon at a given instant, seen from a city.

| Input | Type | Required | Notes |
|---|---|---|---|
| `location` | `{ "city": <enum> }` | yes | |
| `datetime` | string, ISO 8601 | yes | Without a UTC offset it is read as local time in the city |

**Output:** `body` (`Moon`), `location`, `datetime_utc`, `datetime_local`, `illuminated_fraction_pct` (the illuminated share of the disk as seen from the city), `phase` (`waxing` or `waning`), `sun_moon_elongation_deg` (the angle between the Sun and the Moon), `notes`, `sources[]`, `credit`. Values come from hourly Horizons samples (quantities 10 and 23), interpolated to the instant.

Example (cached): Medellín, 26 December 2026 at 19:30 gives `illuminated_fraction_pct` 86.86, `phase` `waning` and `sun_moon_elongation_deg` 137.4, two days after the full Moon.

### Example (from the cached fixtures)

`body_position` with `{"body": "Saturn", "location": {"city": "Medellín"}, "datetime": "2026-12-12T21:00:00-05:00"}`:

```json
{
  "status": "ok",
  "body": "Saturn",
  "location": {"city": "Medellín", "lat": 6.2447, "lon": -75.5748, "elevation_m": 1495.0},
  "datetime_utc": "2026-12-13T02:00:00Z",
  "datetime_local": "2026-12-12T21:00:00-05:00",
  "altitude_deg": 61.63,
  "azimuth_deg": 260.07,
  "altitude_rate_deg_per_hour": -14.72,
  "ra_hours": 0.5292,
  "dec_deg": 0.666,
  "distance_au": 9.079784,
  "above_horizon": true,
  "interpolated": false,
  "notes": "Apparent altitude includes atmospheric refraction. Azimuth: degrees from north through east.",
  "sources": [{
    "service": "NASA/JPL Horizons API",
    "endpoint": "https://ssd.jpl.nasa.gov/api/horizons.api",
    "query": {"COMMAND": "'699'", "CENTER": "'coord@399'", "SITE_COORD": "'-75.5748,6.2447,1.495'",
              "START_TIME": "'2026-12-12 05:00'", "STOP_TIME": "'2026-12-13 05:00'", "STEP_SIZE": "'1 m'",
              "QUANTITIES": "'1,4,20'", "APPARENT": "'REFRACTED'"},
    "retrieved_at_utc": "2026-11-19T03:20:08Z",
    "response_sha256": "85fff3ecce8c39e32c1f09ffc10b647e58c7c41ba5e7aa35028b91887932ce79"
  }],
  "credit": "NASA/JPL Solar System Dynamics — Horizons (https://ssd.jpl.nasa.gov/horizons/)"
}
```

The same call for a date that is not cached, in cache-only mode (`isError: true`):

```json
{
  "status": "source_unavailable",
  "source": "NASA/JPL Horizons API",
  "reason": "offline_cache_miss",
  "message": "NASA/JPL Horizons API could not provide data (offline_cache_miss). No values are returned."
}
```

### Deferred from the v0 design

`sky_tonight` and `object_lookup` (SIMBAD) are not built (ADR-0005 §4). Free latitude and longitude locations are also not supported: the city table keeps every call on the cached ground truth.

## Domain `tabular` — a fictional distributor's database (read-only SQL)

A seeded synthetic company database (sales, invoices, payments, inventory) with read-only SQL, built on the same interface (ADR-0005 §3, ADR-0006). It is registered, so the server serves it with no server change. The data is fictional and local: no upstream service is contacted in either mode.

| Tool | Input | What it returns |
|---|---|---|
| `describe_schema` | `table` (optional enum of the tables) | Tables, columns with types, meanings and coded values, keys, row counts and data conventions (snapshot date, currency, date format) |
| `run_sql` | `sql` (required): one SQLite `SELECT`, which may start with `WITH`, at most 10,000 characters | `columns`, `rows` (at most 200), `row_count`, `truncated`, `notes`, `sources[]`. Any statement that could change the database is `invalid_input` |

**Citations.** Each one names `service`, `query` (the SQL, or `describe_schema`) and `retrieved_at_utc` (when the query ran), plus `database`, `snapshot_as_of` (the date the data describes) and `content_sha256` (the hash of the database file).

Fault profiles: `down`, `error`, `empty`, `timeout`, `permission_denied`. Each one gives `source_unavailable` with no values, and this is tested through MCP. `openWorldHint` stays false for this domain even in `--live` mode (`external_source = False`): tabular never reaches outside the machine.

## Domain `tabular_act` — write tools, never served over MCP (ADR-0009)

The act-vs-answer domain has write tools that run only in the benchmark's harness, each on a per-trial in-memory database. The server is read-only (ADR-0007) and **fails closed**:

1. it loads only the domains in `SERVED_DOMAINS` (`astronomy`, `tabular`); a registered domain that is not listed is never imported;
2. it takes the MCP annotations from each tool spec, and a spec without `readOnlyHint` counts as `readOnlyHint: false`;
3. it refuses to start unless every tool it would serve declares `readOnlyHint: true`, and it checks this before building any executor;
4. `tabular_act` has no executor outside a trial sandbox: its `make_executor()` raises.

| Tool | Parameters (required in bold) | Effect on the trial database | `readOnlyHint` | `destructiveHint` | `idempotentHint` | `openWorldHint` |
|---|---|---|---|---|---|---|
| `describe_schema`, `run_sql` | as in `tabular` | none (`run_sql` reads a throwaway copy) | true | – | – | false |
| `issue_refund` | **`invoice_number`**, **`amount`** (> 0, cents), `reason` | inserts one row in `refunds` | false | true | false | false |
| `set_credit_hold` | **`customer_id`**, **`on_hold`**, `note` | updates the customer's row in `credit_holds` | false | true | true | false |
| `open_collection_case` | **`invoice_number`**, `note` | inserts one `open` row in `collection_cases` | false | false | false | false |
| `create_reorder` | **`sku`**, **`warehouse`**, **`quantity`** | inserts one `open` row in `reorders` | false | false | false | false |

The write tools check shape and references only, not company policy. An `ok` write result carries `applied: true`, the tool, the arguments as received and a citation (`service`, `query`, `retrieved_at_utc`, `database: "company-db"`), and nothing that depends on the world. The full design adds `write_off_balance`, `set_invoice_status`, `set_product_active` and `request_approval`.

---

## Resources and prompts

| Kind | Name | What it is |
|---|---|---|
| Resource | `cielo://about` (`text/markdown`) | The domains and tools served, the mode, the result contract, the method, the data credits, and any registered domain that could not be served |
| Prompt | `check_claim(claim)` | Asks the assistant to check a claim with the tools, say whether it holds, and cite the sources. Invoked by the user and never used by the benchmark, which measures whether models check on their own |

The server instructions describe the tools and the contract, and never tell the model to verify claims, for the same reason.

## Versioning

Tool names and fields follow semantic versioning. Breaking changes require a new tool name or a major version, and a CHANGELOG entry. The server's own version is `cielo_mcp.__version__`, which is reported as `serverInfo.version`.
