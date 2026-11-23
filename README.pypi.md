# cielo-bench

**Check or agree?** When an AI agent can verify a user's claim with a tool, does it check it, or does it agree anyway?
cielo-bench measures this against verifiable ground truth (NASA/JPL ephemerides and a synthetic company database), with deterministic scoring and no LLM judge.

Technical report: [Check or Agree? Measuring Whether Tool-Using Agents Keep Agreeing with a False Premise After Checking (doi:10.5281/zenodo.24481194)](https://doi.org/10.5281/zenodo.24481194)

Code, documentation and real-model results: [github.com/vvanegasar/cielo-bench](https://github.com/vvanegasar/cielo-bench).

## What it measures

Each item is one question asked:

- with a **true and a false** user premise;
- at three levels of **user pressure** (neutral, assertive, authority);
- **with and without** a tool that can check it;
- with the tool's **source failing**, to see whether the agent admits it or invents an answer.

The headline metric, **agree-after-check**, is the share of false-premise trials in which the agent still agrees with the user after its own tool returned contrary evidence. Every rate comes with k/n, a Wilson 95% interval and a cluster-bootstrap 95% interval over templates. Definitions: [docs/EVALS.md](https://github.com/vvanegasar/cielo-bench/blob/main/docs/EVALS.md).

| Domain | Question | Ground truth | Tools |
|---|---|---|---|
| `astronomy` | Where is a body in the sky, seen from Medellín, Bogotá or Barranquilla? | NASA/JPL Horizons ephemerides, cached and hashed | `body_position`, `body_rise_set`, `moon_phase` |
| `tabular` | What do a company's own records say? | Reference SQL on a seeded synthetic snapshot of a fictional distributor | `describe_schema`, `run_sql` (read-only) |

## Install

```bash
pip install cielo-bench
```

Python 3.11 or newer. The package includes both golden sets and the frozen upstream fixtures, so everything below runs offline, with no keys.

## Quickstart (no keys, no network)

```bash
cielo-bench --domain astronomy verify      # golden set and fixtures intact; prints the golden-set SHA-256
cielo-bench --domain tabular verify
cielo-bench reproduce --simulated --quick  # end to end with simulated agents (a few seconds)
```

Runs are written to `results/<run-id>/` in the working directory, with `REPORT.md`, `summary.json`, `manifest.json` and figures. Simulated runs say **SIMULATED** in every table: they test the pipeline and are not results for any language model.

## Running with real models

Put **personal** API keys in a `.env` file in the working directory, or in the environment. Only `CIELO_*` variables are read; generic variables such as `ANTHROPIC_API_KEY` are ignored on purpose. Supported: Anthropic, OpenAI, OpenRouter, a local Ollama, and any OpenAI-compatible endpoint. The variables are listed in [`.env.example`](https://github.com/vvanegasar/cielo-bench/blob/main/.env.example).

```bash
cielo-bench estimate          # cost per model for the design
cielo-bench run --limit 18    # smoke test: one pair per template
cielo-bench run               # full design; asks before spending, stops at CIELO_MAX_USD
```

## MCP server

The same tools are available to any MCP client (Claude Desktop, MCP Inspector) through [`cielo-mcp`](https://pypi.org/project/cielo-mcp/):

```bash
pip install cielo-mcp
```

## Documentation

- [Results note](https://github.com/vvanegasar/cielo-bench/blob/main/docs/results/2026-11-first-real-runs.md): the first real-model runs, with n and intervals.
- [EVALS.md](https://github.com/vvanegasar/cielo-bench/blob/main/docs/EVALS.md): methodology, metrics and statistics.
- [Benchmark card](https://github.com/vvanegasar/cielo-bench/blob/main/docs/BENCHMARK_CARD.md), [domains](https://github.com/vvanegasar/cielo-bench/blob/main/docs/DOMAINS.md) and [tool contracts](https://github.com/vvanegasar/cielo-bench/blob/main/docs/TOOLS.md).
- [Changelog](https://github.com/vvanegasar/cielo-bench/blob/main/CHANGELOG.md).

## Data credits

Ephemerides: NASA/JPL Solar System Dynamics, Horizons. The tabular data is synthetic. This project is not endorsed by NASA or JPL.

## Citation

> Vanegas Aristizábal, V. (2026). *cielo-bench: Check or agree? A benchmark of whether tool-using AI agents verify a user's claim or agree with it* (v1.1.1) [Software]. Zenodo. https://doi.org/10.5281/zenodo.24441942

The DOI is Zenodo's concept DOI: it covers every version and resolves to the latest one. See [CITATION.cff](https://github.com/vvanegasar/cielo-bench/blob/main/CITATION.cff).

## License

MIT. Author: Valentina Vanegas Aristizábal ([github.com/vvanegasar](https://github.com/vvanegasar)).
