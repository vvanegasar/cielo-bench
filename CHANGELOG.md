# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html). For the benchmark, a change to a golden set (new SHA-256) is a minor version, and a change to a metric definition is a major version.

## [Unreleased]

## [1.0.0] - Unreleased (the date is set when the release is tagged)

First public release. No real-model results are included yet: every number in the repository comes from simulated agents and is labelled as such.

### Added

- **Domain-independent harness** (`evals/cielo_bench/`). A `Domain` interface covers the item generator, tools, ground truth with tolerances, and evidence. On top of it sit a runner, a deterministic judge-free scorer, metrics, statistics, reports and a CLI.
- **Design.** Every item is asked with and without the tool, with a true and a false premise, and at neutral, assertive and authority pressure. A separate block makes the source fail (`down`, `error`, `empty`).
- **Metrics.**
  - The headline is *agree-after-check*, with a formal definition.
  - Also verification rate, user correction, verdict accuracy and value accuracy within tolerance.
  - Under faults: honest refusal, hallucination and fabricated values.
  - Cost and latency.
- **Statistics.**
  - Wilson intervals and a cluster bootstrap over templates.
  - Paired contrasts (McNemar exact) with Holm adjustment over a pre-specified family.
  - Design-effect power analysis and minimum detectable effects.
- **Astronomy domain.**
  - 144 premise pairs in 18 templates, from Medellín, Bogotá and Barranquilla, in Spanish and English.
  - Ground truth: NASA/JPL Horizons, with 98 one-minute observer tables and 3 hourly Moon-phase tables, cached with SHA-256. The upstream source received 102 requests in total.
  - Tools: `body_position` (with `relative_to`), `body_rise_set` and `moon_phase`.
- **Tabular domain.** 126 premise pairs in 7 templates over a seeded, synthetic SQLite database of a fictional distributor. Tools: `describe_schema` and read-only `run_sql`.
- **Providers.** Anthropic, OpenAI, OpenRouter, a local Ollama and any OpenAI-compatible endpoint, plus deterministic simulated agents. The model version is recorded per trial; requests have retries, rate limiting and an output cache; transcripts are raw JSONL. Keys are read only from `CIELO_*` settings.
- **CLI commands.**
  - `reproduce --simulated` runs end to end without network or keys.
  - `run`, `report`, `estimate`, `power`, `verify`, `build-golden` and `domains`.
  - `docs` generates the README tables. `pack` compresses raw transcripts.
- **MCP server** (`server/`, Python, stdio and Streamable HTTP), serving the same tool executors.
- **Live cache.** Live upstream responses go to `CIELO_CACHE_DIR` or `--cache-dir`, never to the committed fixtures.
- **CI.** Python 3.11–3.13 for the benchmark and 3.12–3.13 for the server. No secrets and no model calls.
- **Documentation.** `docs/EVALS.md`, `docs/ARCHITECTURE.md`, `docs/TOOLS.md`, `docs/DOMAINS.md`, `docs/BENCHMARK_CARD.md`, ADR-0005, ADR-0006 and ADR-0007, `CONTRIBUTING.md` and `CITATION.cff`.

[Unreleased]: https://github.com/vvanegasar/cielo-bench/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/vvanegasar/cielo-bench/releases/tag/v1.0.0
