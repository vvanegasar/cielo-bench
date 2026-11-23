# Architecture (v1)

## Overview

```
                    ┌────────────────────── evals/cielo_bench (domain-independent core) ──────────────────────┐
 golden sets ─────► │ runner ─► agent loop ─► provider (Anthropic · OpenAI · OpenRouter · Ollama · simulated)  │
 (one per domain)   │             │  ▲                                                                         │
                    │             ▼  │ tool results                                                            │
                    │        tool executor ◄── fault profile (down · error · empty)                            │
                    │             │                                                                            │
                    │ trials.jsonl (raw) ─► scoring ─► metrics / stats ─► REPORT.md · figures · summary.json   │
                    │ docs.py ─► generated README tables (validation, golden sets, power, results, tests)      │
                    └─────────────┼─────────────────────────────────────────────┼──────────────────────────────┘
                                  │ Domain interface                             │ same executors
              ┌───────────────────┴───────────────┐                  ┌───────────┴────────────────────────────┐
              │ domains/astronomy                 │                  │ server/  cielo-mcp (Python, MCP SDK)   │
              │  tools ─► ephemeris ─► Horizons   │                  │  stdio · Streamable HTTP (127.0.0.1)   │
              │  client (serialized, cached,      │                  │  cache-only by default, --live opt-in  │
              │  SHA-256, generic User-Agent)     │                  └────────────────────────────────────────┘
              ├───────────────────────────────────┤
              │ domains/tabular                   │
              │  describe_schema · run_sql        │
              │  (read-only) ─► synthetic SQLite  │
              └───────────────────────────────────┘
```

The benchmark is the product (ADR-0001). The core knows nothing about astronomy or SQL: everything domain-specific sits behind the `Domain` interface (ADR-0005). The MCP server (ADR-0007) wraps the same tool executors, so an MCP client gets exactly what the benchmark's agents get.

## Core modules (`evals/cielo_bench/`)

| Module | Responsibility |
|---|---|
| `domain.py` | The `Domain` interface, `ToolEvent`, `Evidence`, tool-result statuses, fault kinds (`down`, `error`, `empty`), answer kinds and tolerance modes |
| `golden.py` | Golden-set schema 2 (pairs × premise × pressure × language), SHA-256 of the content, structural validation |
| `prompts.py` | System prompt = the domain's preamble + one shared answer format (`VERDICT` / `VALUE`, with domain-provided examples) |
| `agent.py` | The tool loop of one trial: ask, execute the tool calls, return the results, repeat (at most 4 tool rounds) |
| `runner.py` | Design → trial plan → threads with a budget guard, resume and an output cache → `trials.jsonl` + `manifest.json` |
| `scoring.py` | Judge-free trial coding: verdict, value (clock, angle, or number in English or Spanish formats), evidence, correction, honest refusal, hallucination, exclusions |
| `metrics.py` | Rates by condition × premise × pressure, pre-specified paired contrasts with Holm adjustment, breakdowns, power note, worst failures |
| `stats.py` | Wilson, cluster bootstrap, McNemar exact, Holm, design effect, minimum detectable effect (standard library only) |
| `report.py` | `REPORT.md`, figures and `summary.json`, built **only from the raw JSONL** (plain or packed `.gz`) |
| `docs.py` | The generated README tables, including the harness validation with simulated agents; `--check` mode for CI |
| `providers/` | `anthropic.py`, `openai_compat.py` (OpenAI, OpenRouter, Ollama, other compatible APIs), `simulated.py`, and `http.py` (retries, rate limiter, output cache) |
| `cache.py` | Content-addressed cache for upstream responses (gzip, SHA-256), and `LayeredCache` (read-only fixtures + writable live cache) |
| `pricing.py` · `net.py` · `config.py` · `cli.py` | Price table and cost per trial; TLS context (certifi); settings (`CIELO_*` only), paths, live cache directory and commit; command line |

## The `Domain` interface

| Part | Methods | What the domain provides |
|---|---|---|
| Item generator | `build_golden`, `verify_golden`, `golden_path` | Premise pairs with templates (clusters), ground-truth facts, sources and hashes; offline integrity checks |
| Tools | `tool_specs`, `make_executor(fault_profile=…)`, `system_preamble`, `value_examples` | Provider-neutral JSON-schema tools; an executor that honours the fault kinds `down`, `error` and `empty` |
| Ground truth and tolerances | `premise_holds(pair, value, facts)` | The rule that decides whether a premise holds, with explicit margins |
| Evidence | `evidence(pair, trace)`, `value_from_facts`, `perturb_call` | Which expected checks were attempted and succeeded, and the facts they returned |

Domains are registered in `domains/__init__.py` (`REGISTRY`, name → `module:Class`): `astronomy` and `tabular`. CI, `docs` and the MCP server discover them from the registry.

## Contracts

**Tool result.** A JSON object with `status` in `ok | invalid_input | source_unavailable | out_of_scope`.

- Successful results carry `sources[]` (service, endpoint or database, query, retrieval time, hash) and a credit line.
- A non-`ok` result carries **no values**.
- `reason: request_budget_exhausted` marks a result caused by the harness's own request cap; the scorer excludes those trials.
- Contracts per tool: [TOOLS.md](TOOLS.md).

**Trial record** (one line of `trials.jsonl`):

| Field | Content |
|---|---|
| `trial_id`, `run_id` | identifiers |
| `model_label`, `provider`, `model_id` | the model as configured |
| `pair_id`, `template`, `lang`, `premise`, `pressure`, `condition`, `fault_kind`, `rep` | the trial's place in the design |
| `system_prompt_sha256`, `user_text`, `tools_offered` | what the model was given |
| `rounds[]` | per round: request metadata, the raw response, usage, latency, the model id the API reported, the tool calls, and every tool call's arguments and result |
| `final_text`, `stop_reason`, `usage_total`, `cost_usd`, `latency_s_total`, `error` | the outcome |

API keys and request headers are never written (tested).

**Run directory** (`results/<run-id>/`):

| File | Content | Versioned |
|---|---|---|
| `manifest.json` | design, models and settings without secrets, prices, commit, golden-set hash, system prompts, live source requests; one entry per session in `sessions` (a resumed run keeps its first run id, commit and start time) | real runs |
| `trials.jsonl` | raw transcripts | local only; `trials.jsonl.gz` (from `cielo-bench pack`) is versioned |
| `scores.jsonl` | derived trial coding | local only |
| `summary.json` | all metrics | real runs |
| `REPORT.md` | the report | real runs |
| `figures/` | the figures | real runs |
| `cache/` | raw model responses, for resume | never |

Simulated runs (`results/*-simulated/`) are never versioned; CI regenerates them.

## Domains

**Astronomy** (`domains/astronomy/`)

| Module | Role |
|---|---|
| `horizons.py` | JPL Horizons client: one request at a time per process, with polite spacing; a cache keyed by the normalized query with the SHA-256 of each response; retries; the generic User-Agent `cielo-bench/<version> (non-commercial research benchmark)`; a request log; a request cap; fault profiles |
| `ephemeris.py` | 1-minute observer tables (positions, altitude rate, rise, set and culmination with azimuths) and hourly Moon-phase tables |
| `tools.py` | `body_position` (with optional `relative_to`), `body_rise_set` and `moon_phase` |
| `templates.py` | 18 question templates: eligibility, premise values, premise rules, three pressure frames in ES and EN, and how to read evidence back |
| `build.py` | The deterministic generator. Rebuilding offline from the fixtures reproduces the golden-set hash (tested) |

**Tabular** (`domains/tabular/`): a seeded synthetic SQLite snapshot of a fictional distributor, with read-only SQL tools in four layers of protection. See [DOMAINS.md](DOMAINS.md) and ADR-0006.

## Caches and fixtures

- **Fixtures** are the frozen ground truth of the golden sets, committed to git:
  - `evals/fixtures/astronomy/horizons/`: 101 gzip responses, plus `requests.log.jsonl`;
  - `evals/fixtures/tabular/`: the SQLite file and its manifest, versioned because they fix the exact bytes of every run.
- Only `cielo-bench build-golden` writes the fixtures.
- **Live responses**, from a real run or the MCP server with `--live`, are written to the live cache: `CIELO_CACHE_DIR`, or `--cache-dir`, otherwise `$XDG_CACHE_HOME/cielo-bench` or `~/.cache/cielo-bench`.
- Reads go through both layers (`LayeredCache`), so the fixtures answer first and are never modified.

## Reproducibility

- Upstream data is frozen as hashed fixtures. Each golden set has its own hash, and both are checked by `cielo-bench verify`.
- Simulated runs are deterministic: every decision is a hash of (seed, model, trial id, decision). The same trials give the same transcripts with any number of workers (tested and shown in the README's validation table).
- Every report records the commit, the golden-set hash, the model versions, the design, the prices and the run date (UTC and Colombia time).
- `cielo-bench reproduce --simulated` runs the whole pipeline without network or keys. `cielo-bench reproduce --from <run>` rebuilds a report from raw transcripts only.

## CI (`.github/workflows/ci.yml`)

- **Benchmark job**, on Python 3.11, 3.12 and 3.13:
  - `ruff check` and `ruff format --check`;
  - `pytest --cov` (the core has a coverage floor of 85 %);
  - `verify` and `reproduce --simulated --quick` for every registered domain;
  - `docs --update-readme-tables --check`.
- **MCP server job**, on Python 3.12 and 3.13: the server's tests, cache-only.
- No secrets and no model calls.

## Security and privacy

- Keys are read only from `CIELO_*` settings (the local `.env`, git-ignored); generic provider variables are ignored. Keys never reach logs or transcripts.
- Upstream requests carry a generic User-Agent without personal data. TLS is always verified, with the certifi bundle by default.
- Tool descriptions are static. Upstream text is data, never instructions. `run_sql` is read-only by construction.
- The fault profiles exist only inside the harness; the MCP server never injects faults.
