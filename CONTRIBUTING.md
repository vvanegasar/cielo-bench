# Contributing to cielo-bench

Thank you for your interest. cielo-bench measures whether tool-using AI agents check a user's claim or agree with it. Contributions are welcome when they keep its central property: **every score comes from verifiable ground truth and deterministic rules, and nothing is invented.**

## Set up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"            # the benchmark (Python 3.11+)
pip install -e "server[dev]"       # optional: the MCP server (Python 3.12+)
```

## Before opening a pull request

```bash
ruff check . && ruff format --check . --extend-exclude server
python -m pytest --cov                      # coverage of the core must stay >= 85 %
cielo-bench reproduce --simulated --quick   # end to end, no network, no keys
cielo-bench docs --update-readme-tables     # if a golden set, a metric or the design changed
(cd server && python -m pytest)             # if you touched the tools or the server
```

CI runs the same steps on Python 3.11, 3.12 and 3.13, without secrets and without model calls.

## Ground rules

- **No invented data.** When a source fails, a tool returns `status: source_unavailable` with no values. Every new tool needs tests for its failure path.
- **No keys in code, logs or transcripts.** Keys are read only from `CIELO_*` settings (a local, git-ignored `.env`). Never use or commit someone else's key.
- **No personal data** in requests to upstream services. The User-Agent stays generic.
- **New tools or sources need an ADR.** Any new tool, tool parameter or upstream source is recorded in `docs/adr/` before it is merged.
- **Respect upstream terms.** JPL Horizons gets one request at a time, cached, and is credited. New upstream sources need an ADR and a check of their terms.
- **Fixtures are read-only.** Only `cielo-bench build-golden` writes to `evals/fixtures/`. Live responses go to `CIELO_CACHE_DIR` (default `~/.cache/cielo-bench`).
- **Simulated numbers are never results.** Reports of simulated runs say so in every table. Do not present them as model results.
- **Results policy.** Simulated runs are not versioned. For a real run, version `REPORT.md`, `summary.json`, `manifest.json`, `figures/` and `trials.jsonl.gz` (`cielo-bench pack <run>`). Never version the raw `trials.jsonl` or the run's `cache/`: `pack` strips thinking-block signatures and replaces provider message and tool-use ids, and only the packed file is published. The interpretation of a report is written by a person, in a results note under `docs/results/`.

## Adding a domain

1. Create `evals/cielo_bench/domains/<name>/` with a class that implements `cielo_bench.domain.Domain`:
   - **item generator**: `build_golden` and `verify_golden`;
   - **tools**: `tool_specs` and `make_executor`, supporting the fault kinds `down`, `error` and `empty`;
   - **ground truth**: `premise_holds`;
   - **evidence**: `evidence`, `value_from_facts` and, optionally, `perturb_call` and `value_examples`.
2. Write its golden set in schema 2 (`cielo_bench/golden.py`): premise pairs × three pressure levels × ES/EN, each pair tagged with its template (the statistical cluster). Aim for at least 15 templates; power depends on the number of clusters more than on the number of pairs.
3. Register it with one line in `domains/__init__.py` (`REGISTRY`).
4. Add tests under `evals/tests/`. Write an ADR and add the domain to `docs/DOMAINS.md`.

## Adding a model provider

Add an adapter in `evals/cielo_bench/providers/` that turns a `Conversation` into one request and parses tool calls, usage and the reported model id. Reuse `HTTPProviderMixin` for retries, rate limiting and the output cache. Add mock-transport tests; no test may call a real API.

## Commits and pull requests

- English, [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- One topic per pull request. Describe what changed and how you verified it.
- Update `CHANGELOG.md` under *Unreleased*.

## Reporting problems

- **Bugs, wrong ground truth or unclear docs:** open an issue with the command you ran, its output, and the golden-set hash.
- **Security issues:** follow `SECURITY.md` and report privately.
