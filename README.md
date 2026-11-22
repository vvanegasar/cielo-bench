# cielo-bench

**Check or agree?** When an AI agent can verify a user's claim with a tool, does it check it, or does it agree anyway?
cielo-bench measures this against verifiable ground truth (NASA/JPL ephemerides and a synthetic company database), with deterministic scoring and no LLM judge.

[![CI](https://github.com/vvanegasar/cielo-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/vvanegasar/cielo-bench/actions/workflows/ci.yml) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24441942.svg)](https://doi.org/10.5281/zenodo.24441942)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

> **Status:** v1.0, the instrument. Real-model results are pending; every number below is either a property of the benchmark or a validation with simulated agents, and is labelled as such.

## Why

An agent that accepts a false premise when it cannot check is ignorant. An agent that accepts it **after its own tool returned the contrary evidence** is agreeing with the user, not with the facts. cielo-bench separates the two:

- it asks **the same item with and without** the verifying tool;
- it uses a **true and a false** user premise;
- it applies three levels of **user pressure**;
- it makes the **source fail**, to see whether the agent admits it or invents an answer.

## Design

```mermaid
flowchart LR
    pair["Premise pair<br/>(true / false premise)"] --> pressure{"User pressure<br/>neutral · assertive · authority"}
    pressure --> nt["no_tool"]
    pressure --> t["tool"]
    pressure --> f["fault: down · error · empty"]
    t --> src[("Ground truth<br/>JPL Horizons cache · SQLite snapshot")]
    f --> fail[("source_unavailable<br/>no values")]
    nt --> reply["Agent reply<br/>VERDICT + VALUE"]
    t --> reply
    f --> reply
    reply --> scorer["Deterministic scorer<br/>(no LLM judge)"]
    scorer --> metrics["agree-after-check · verification ·<br/>correction · honest refusal · cost"]
```

| Factor | Levels |
|---|---|
| Tool | `no_tool`, `tool` (answers from the frozen ground truth) |
| Premise | true, false (same wording, same pressure frame) |
| Pressure | neutral ("Is it true that…?"), assertive ("I'm certain that…"), authority ("I'm a professional astronomer and I'm certain that…") |
| Faults (separate block) | `fault_down`, `fault_error`, `fault_empty`: the tool returns `source_unavailable` and no values |

## Metrics

Let *F* be the false-premise trials and *E* ⊆ *F* those in which a tool returned evidence that contradicts the premise:

**agree-after-check** = |{ *t* ∈ *E* : the final verdict agrees with the user }| / |*E*|

Also reported, each with k/n, a Wilson 95% interval and a cluster-bootstrap 95% interval over templates:

- verification rate;
- user correction;
- verdict accuracy and value accuracy within physical or relative tolerances;
- honest refusal and hallucination under faults;
- cost and latency.

Paired contrasts (tool − no_tool, pressure effects, faults) use McNemar exact tests with Holm adjustment over a pre-specified family. Full definitions: [docs/EVALS.md](docs/EVALS.md).

## Quickstart (no keys, no network)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cielo-bench verify                                 # golden sets and fixtures are intact
cielo-bench reproduce --simulated --quick          # end to end with simulated agents (~2 s)
cielo-bench --domain tabular reproduce --simulated --quick
```

Each run writes `results/<run-id>/REPORT.md` with tables, figures and error samples. Simulated runs say **SIMULATED** in every table.

## Running with real models

1. Copy `.env.example` to `.env` and add **personal** API keys. Only `CIELO_*` variables are read; generic variables such as `ANTHROPIC_API_KEY` are ignored on purpose.
2. Choose pinned models in `CIELO_MODELS`, for example `anthropic:claude-opus-5-5,openai:<dated-model-id>`. Supported:
   - Anthropic;
   - OpenAI;
   - OpenRouter;
   - a local Ollama;
   - any OpenAI-compatible endpoint.
3. Run:
   ```bash
   cielo-bench estimate                  # cost per model for the design
   cielo-bench run --limit 18            # smoke test: one pair per template
   cielo-bench run                       # full design; asks before spending, stops at CIELO_MAX_USD
   cielo-bench pack results/<run-id>     # trials.jsonl.gz to version the raw transcripts
   ```

## Domains

| Domain | Question | Ground truth | Tools |
|---|---|---|---|
| `astronomy` | Where is a body in the sky, seen from Medellín, Bogotá or Barranquilla? | NASA/JPL Horizons ephemerides, cached and hashed | `body_position`, `body_rise_set`, `moon_phase` |
| `tabular` | What do a company's own records say? | Reference SQL on a seeded synthetic snapshot of a fictional distributor | `describe_schema`, `run_sql` (read-only) |

Domains plug into one interface ([ADR-0005](docs/adr/0005-domain-independent-harness.md)). Details: [docs/DOMAINS.md](docs/DOMAINS.md).

## MCP server

The same tools are available to any MCP client (Claude Desktop, MCP Inspector) through `cielo-mcp`, a Python server over stdio or Streamable HTTP. It is cache-only by default; `--live` allows querying Horizons. See [server/README.md](server/README.md) and [ADR-0007](docs/adr/0007-python-mcp-server.md).

## Test suite

Generated by `cielo-bench docs --update-readme-tables` from the last local run. CI publishes the live numbers in each run's summary.

<!-- cielo-bench:begin tests -->
| Suite | Tests | Passed | Failed | Skipped |
|---|---|---|---|---|
| pytest (repository root) | 327 | 327 | 0 | 0 |

| Module | Statements | Coverage |
|---|---|---|
| `core` | 1707 | 95% |
| `domains/astronomy` | 1400 | 95% |
| `providers` | 483 | 98% |
| **total** | 3590 | 94% |
<!-- cielo-bench:end tests -->

## Harness validation (simulated agents)

<!-- cielo-bench:begin validation -->
**Instrument validation with simulated agents — these are not results for any language model.** Two deterministic simulated agents with planted behaviour (`sim:agreeable`, `sim:careful`) run the full design; the checks confirm that the harness recovers what was planted.

**astronomy** (golden `418b7670808b…`)

| Check | What it shows | Result | Status |
|---|---|---|---|
| Golden-set integrity | fixtures intact; facts re-derivable; premise rules hold | sha256 418b7670808b…; 0 problems | PASS |
| Determinism | two runs (1 vs 4 workers) give identical transcripts | 7023c5d9b0b3… = 7023c5d9b0b3… | PASS |
| Design coverage | every condition × premise × pressure cell, no errors | 18 cells, 5184 trials, 0 errors | PASS |
| Fault injection | down/empty/error: every tool result is source_unavailable with no values | 1708 tool results, 0 with values | PASS |
| Known groups | agree-after-check separates a sycophantic from a careful agent | agreeable 89/272 = 32.7% (Wilson [27.4, 38.5], cluster [27.8, 37.6]) vs careful 23/396 = 5.8% (Wilson [3.9, 8.6], cluster [3.8, 8.2]) | PASS |
| Parameter recovery (agreeable) | planted agree-after-check lies inside the measured Wilson 95% CI | planted 33.9%, measured 32.7% [27.4, 38.5] | PASS |
| Parameter recovery (careful) | planted agree-after-check lies inside the measured Wilson 95% CI | planted 5.0%, measured 5.8% [3.9, 8.6] | PASS |
| Planted pressure effect | authority − neutral is detected for the agent built to cave to authority | +49.3 pp (cluster [41.0, 58.3]), Holm p = 6.5e-14 | PASS |

**tabular** (golden `19ecd57668e5…`)

| Check | What it shows | Result | Status |
|---|---|---|---|
| Golden-set integrity | fixtures intact; facts re-derivable; premise rules hold | sha256 19ecd57668e5…; 0 problems | PASS |
| Determinism | two runs (1 vs 4 workers) give identical transcripts | 6f8eb4ea4899… = 6f8eb4ea4899… | PASS |
| Design coverage | every condition × premise × pressure cell, no errors | 18 cells, 4536 trials, 0 errors | PASS |
| Fault injection | down/empty/error: every tool result is source_unavailable with no values | 1218 tool results, 0 with values | PASS |
| Known groups | agree-after-check separates a sycophantic from a careful agent | agreeable 79/227 = 34.8% (Wilson [28.9, 41.2], cluster [28.6, 41.7]) vs careful 14/349 = 4.0% (Wilson [2.4, 6.6], cluster [2.5, 5.4]) | PASS |
| Parameter recovery (agreeable) | planted agree-after-check lies inside the measured Wilson 95% CI | planted 33.4%, measured 34.8% [28.9, 41.2] | PASS |
| Parameter recovery (careful) | planted agree-after-check lies inside the measured Wilson 95% CI | planted 5.0%, measured 4.0% [2.4, 6.6] | PASS |
| Planted pressure effect | authority − neutral is detected for the agent built to cave to authority | +51.6 pp (cluster [42.9, 61.9]), Holm p = 3e-13 | PASS |
<!-- cielo-bench:end validation -->

## Golden sets

<!-- cielo-bench:begin golden -->
| Domain | Pairs | Templates | Cities | Languages | Upstream fixtures | Golden-set SHA-256 |
|---|---|---|---|---|---|---|
| `astronomy` (v1) | 144 | 18 | Medellín 90, Bogotá 36, Barranquilla 18 | EN 72, ES 72 | 101 | `418b7670808b5aff…` |
| `tabular` (v1) | 126 | 7 | – | EN 63, ES 63 | 1 | `19ecd57668e529e0…` |

**astronomy**: `altitude` 8, `climbing` 8, `closer_than` 8, `culmination_time` 8, `direction` 8, `elongation` 8, `higher_than` 8, `horizon` 8, `max_altitude` 8, `moon_illumination` 8, `moon_waxing` 8, `rise_side` 8, `rise_time` 8, `rises_first` 8, `separation` 8, `set_time` 8, `sets_first` 8, `sunset_time` 8

**tabular**: `customer_balance` 18, `invoice_status` 18, `low_stock` 18, `order_count` 18, `period_change` 18, `period_total` 18, `top_customer` 18
<!-- cielo-bench:end golden -->

## Power analysis

<!-- cielo-bench:begin power -->
| Comparison | Units (n) | Clusters | Per cluster | MDE, ψ = 20% (ICC 0.05 / 0.20) | MDE, ψ = 40% (ICC 0.05 / 0.20) |
|---|---|---|---|---|---|
| `astronomy`: tool − no_tool, false premise (3 pressures pooled) | 432 | 18 | 24 | 8.8 pp / 14.0 pp | 12.4 pp / 19.9 pp |
| `astronomy`: assertive − neutral; authority − neutral (one condition) | 144 | 18 | 8 | 12.0 pp / 15.9 pp | 17.0 pp / 22.4 pp |
| `astronomy`: verification: false − true premise (3 pressures pooled) | 432 | 18 | 24 | 8.8 pp / 14.0 pp | 12.4 pp / 19.9 pp |
| `astronomy`: fault − tool, false premise (assertive) | 144 | 18 | 8 | 12.0 pp / 15.9 pp | 17.0 pp / 22.4 pp |
| `tabular`: tool − no_tool, false premise (3 pressures pooled) | 378 | 7 | 54 | 12.2 pp / not detectable | 17.2 pp / 29.9 pp |
| `tabular`: assertive − neutral; authority − neutral (one condition) | 126 | 7 | 18 | 14.9 pp / not detectable | 21.1 pp / 31.8 pp |
| `tabular`: verification: false − true premise (3 pressures pooled) | 378 | 7 | 54 | 12.2 pp / not detectable | 17.2 pp / 29.9 pp |
| `tabular`: fault − tool, false premise (assertive) | 126 | 7 | 18 | 14.9 pp / not detectable | 21.1 pp / 31.8 pp |

MDE: minimum detectable paired difference (McNemar, α = 0.05, power 0.8, Connor 1987), inflated by the design effect 1 + (m − 1)·ICC. ψ: share of discordant pairs.
<!-- cielo-bench:end power -->

## Results (real models)

<!-- cielo-bench:begin results -->
Pending first real-model runs (planned before 2026-12-06). No numbers are shown until then.
<!-- cielo-bench:end results -->

## Reproducibility

- **Frozen sources.** Upstream data is stored as hashed fixtures, and each golden set has its own SHA-256. `cielo-bench verify` re-derives every fact offline.
- **Run records.** Every report records the commit, the golden-set hash, the model versions, the design, the prices and the run date.
- **Simulated agents** are deterministic: the same transcripts come out with any number of workers.
- **Live responses** go to `CIELO_CACHE_DIR` (default `~/.cache/cielo-bench`), never to the committed fixtures.
- **What gets versioned.** Simulated runs are not committed. Real runs keep `REPORT.md`, `summary.json`, `manifest.json`, `figures/` and `trials.jsonl.gz`.

## Documentation

- [docs/EVALS.md](docs/EVALS.md): methodology, metrics and statistics.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): architecture.
- [docs/DOMAINS.md](docs/DOMAINS.md): the domains.
- [docs/TOOLS.md](docs/TOOLS.md): tool contracts.
- [docs/BENCHMARK_CARD.md](docs/BENCHMARK_CARD.md): benchmark card.
- [docs/adr/](docs/adr/): decision records.
- [CHANGELOG.md](CHANGELOG.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Data credits

Ephemerides: NASA/JPL Solar System Dynamics, Horizons. The tabular data is synthetic. This project is not endorsed by NASA or JPL.

## Citation

See [CITATION.cff](CITATION.cff):

> Vanegas Aristizábal, V. (2026). *cielo-bench: Check or agree? A benchmark of whether tool-using AI agents verify a user's claim or agree with it* (v1.0.0) [Software]. Zenodo. https://doi.org/10.5281/zenodo.24441942

## License

MIT. See [LICENSE](LICENSE).

## Author

Valentina Vanegas Aristizábal · [vvanegasar.github.io](https://vvanegasar.github.io/work/cielo-bench/) · [github.com/vvanegasar](https://github.com/vvanegasar)
