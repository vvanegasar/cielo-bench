# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html). For the benchmark, a change to a golden set (new SHA-256) is a minor version, and a change to a metric definition is a major version.

## [Unreleased]

Toward 1.2: a harder test. The v1.1 results sat on the difficulty floor (every model checked on every astronomy trial), so this work makes the instrument harder before adding a second provider. The v1 golden set (`418b7670…`) and the v1.1 results are unchanged.

### Added

- **Golden set `astronomy-near-v2`** (domain `astronomy_near`): 88 pairs in 11 templates, same fixtures, dates, cities and tools as v1, so it needs no new request to JPL.
  - The false premises are close to the truth: 15° (v1: 30°) for angles, 20 pp (v1: 40) for the Moon's illumination, 30 min (v1: 90 to 180) for times. Their failure thresholds are tightened to match (`PREMISE_RULES`).
  - The direction of the error is balanced by a hash of the context (v1 almost always put the false value above the truth).
  - `rises_first_near` and `sets_first_near` only use events in the same half of the local day and 20 to 150 minutes apart, which removes the "which night" ambiguity of `sets_first` (see the results note, section 2).
  - The prompt's format examples (`52°`, `07:23`) are never a premise value, because premise values are multiples of 5. The examples of v1 (`35°`, `19:40`) could anchor an answer.
- **Pilot of the v2 set** (Haiku 5.5, 1,056 trials, US$1.08): agree-after-check 0 of 264 with the tool, so near premises do not break the floor. Results note: `docs/results/2026-11-near-premises-pilot.md`; run in `results/2026-11-24-astronomy-near-pilot-claude-haiku-5-5/`. The next lever is multi-turn insistence (ROADMAP v1.2).
- Tests for the new set (shape, rules, distance to the truth, balance, same half-day, example collision, offline rebuild) and for the scorer change below.

### Fixed

- **The scorer reads `VALUE: unknown (…)` as no value.** A line that opens with a no-value word and then only explains, with no digit, states nothing. One with a digit ("unknown (about 18:00)") still counts as stating a value.
- A golden set carries only the premise rules of its own templates, so adding templates does not change the hash of an existing set.

## [1.1.1] - 2026-11-23

Packaging and documentation only. The golden sets (same SHA-256), the metric definitions and the results are unchanged: `cielo-bench report` rebuilds `REPORT.md` and `summary.json` of every versioned run byte for byte. The MCP server is released with it as `cielo-mcp` 0.1.1.

### Added

- **`pip install cielo-bench` works offline outside the repository.** The wheel now ships both golden sets and the Horizons and tabular fixtures, so `verify`, simulated runs and `report` need neither the repository nor the network.
  - The build maps `evals/golden` and `evals/fixtures` into the package as `cielo_bench/_data` (`pyproject.toml`). Nothing moves in the repository.
  - Installed, the code reads its data from the package and uses the working directory for `results/` and `.env`. From a checkout nothing changes.
  - Run manifests record golden sets as the repository names them (`evals/golden/…`) in both layouts, so existing manifests keep working.
- **`pip install cielo-mcp`** installs the MCP server together with the core.
- **Publishing workflow** `.github/workflows/publish.yml`, on a published release or by hand.
  - It builds the sdist and the wheel of both packages, runs `twine check`, installs the wheels into a clean virtual environment and runs `verify` for every domain and a simulated run there.
  - It then publishes to PyPI with Trusted Publishing: `cielo-bench` (environment `pypi`) first, then `cielo-mcp` (environment `pypi-mcp`).
- **MCP Registry entry** `server/server.json` (`io.github.vvanegasar/cielo-mcp`, package type `pypi`), and the `mcp-name` line in the server's README that the registry checks.
- **Install section** in both READMEs, with the Claude Desktop configuration, and a link to the technical report (doi:10.5281/zenodo.24481194).
- **Tests for the installed package**: data resolution in both layouts, a run that records and reloads the repository path, and a build of the real sdist and wheel whose installed code runs `verify` and a simulated run outside the repository.

### Changed

- **Packages.** `cielo-bench` 1.1.1 and `cielo-mcp` 0.1.1.
  - Both have a PyPI README with absolute links, a license file, classifiers, keywords and project URLs.
  - The server's author is Valentina Vanegas Aristizábal.
  - The server declares the core, `cielo-bench>=1.1.1,<1.2`, instead of asking for it to be installed first (amendment to ADR-0007).
  - The `dev` extra adds `setuptools`, used by the packaging tests.
- **Run records from an installed wheel** give the commit as `no-commit`. The code is identified by `code_version`, and a git repository in the working directory is not the code that ran.
- `CITATION.cff` and `.zenodo.json` are at 1.1.1, and `.zenodo.json` links the technical report.

### Fixed

Wording only; no number changed.

- **Results note, §3, "What depends on the template".** The bullet on template-level tests now says that neither model's effect is significant outside `sets_first` (sign test p = 0.12 for Haiku and 0.062 for Sonnet), and that on the full set the template-level tests give p = 0.062 (Haiku) and 0.031 (Sonnet).
- **Results note, tabular verification.** The reason the evidence rule did not count a check is stated for the six cases read by hand (audit rows A15 to A20), not for all 109.
- **Results note, §7.**
  - The lower no-tool agreement figures are marked as coming from the post hoc analysis in §3.
  - Under faults, the models "abstained without giving a value" (70% and 74%; Haiku on company data, 92%) instead of "reported the failure", and otherwise "gave a verdict or a value anyway".
- **EVALS.md, §7.** "Eight clusters" becomes "Few clusters (18 templates in astronomy, 7 in tabular)".
- **Benchmark card.** The sentence "No funding." is removed from the creator line.

## [1.1.0] - 2026-11-23

First real-model results. Both golden sets are unchanged from 1.0.0 (same SHA-256), and so are the metric definitions. One scorer bug was fixed so that the scores follow those definitions (see Fixed).

### Added

- **First real-model runs** (2026-11-23, Anthropic API; pinned model ids `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5` and `claude-fable-5-2`). Each run is in `results/<run>/` with `REPORT.md`, `summary.json`, `manifest.json`, `figures/` and a sanitized `trials.jsonl.gz`:
  - Claude Haiku 5.5, astronomy, full design (2,592 trials);
  - Claude Haiku 5.5, tabular, full design (2,268 trials);
  - Claude Sonnet 5.5, astronomy, core block on all 144 pairs plus the fault block on 36 pairs (1,944 trials);
  - Claude Opus 5.5 and Claude Fable 5.2, astronomy, `tool` condition on a matched subset of 36 pairs (2 per template), both premises and three pressures (216 trials each).
- **Matched comparisons**:
  - the four models on identical units (`results/2026-11-23-astronomy-matched-comparison/`);
  - Haiku and Sonnet on the core block and Sonnet's 36 fault pairs (`results/2026-11-23-astronomy-haiku-sonnet-comparison/`).
- **`cielo-bench compare RUN_DIR ... --out DIR`.** It compares models from several runs on the units they all share and reports:
  - per-model Wilson and cluster-bootstrap intervals;
  - paired differences between models (descriptive, outside the pre-specified family), including honest refusal and fabricated values under faults;
  - a breakdown of values within tolerance, outside tolerance and missing.
- **Results note** `docs/results/2026-11-first-real-runs.md`. It gives:
  - the designs and why they were chosen;
  - the headline numbers with n and intervals;
  - the tool versus no-tool contrast, with a labelled post hoc analysis without the `sets_first` template;
  - the fault block, cost, latency and limitations;
  - the author's interpretation.
- **Tabular evidence-rule audit** `docs/results/2026-11-tabular-evidence-audit.md`. A seeded sample of 30 transcripts, stratified by template and condition, read against a written checklist. It is agent-assisted, and the author spot-checked it (rows A15 to A20, all six agreed).

### Changed

- **`cielo-bench pack` sanitizes the transcripts it packs.**
  - Thinking-block signatures become `"<stripped>"`.
  - Provider message and tool-use ids become ids derived from the trial id.
  - Scoring reads neither, so reports from the packed file are identical.
- **Resumed runs and run ids.** A resumed run keeps its first run id, commit and start time, and its manifest lists every session in `sessions`. Run ids carry a random suffix, so they are unique even for runs started in the same second.
- **README results table.**
  - It is generated by `cielo-bench docs` and names each run by its directory.
  - It shows the commit and links the run's report.
  - The Spanish README has Spanish headers and decimal commas.
- **REPORT.md.**
  - The design lines list the conditions that ran, and print "–" when there is no fault block.
  - Real runs point to `trials.jsonl.gz`.
  - Section 12 links the results notes that cite the run.

### Fixed

- **The scorer now follows EVALS.md for faults.** It read the VALUE line only on templates with a numeric answer, so an UNKNOWN that stated a value on another template counted as an honest refusal. A VALUE line now counts on every template unless it only says that the value is unknown. For Claude Haiku 5.5 in astronomy, honest refusal under fault is 589/864, not 594/864, and hallucination is 273/864, not 268/864.
- **A real run could stall silently for hours when the machine slept.**
  - On macOS a real run now holds an idle-sleep assertion (`caffeinate -i`) while it lasts. The helper is released in `finally` and killed if it does not exit.
  - A watchdog reports on stderr when no trial has finished for five minutes, naming the oldest trial in flight, and when the machine was asleep.
  - Progress lines come every 50 trials instead of 200.
- **Edge errors are retried.** HTTP 520–524 errors from the edge in front of the model API are now retried like 502–504 instead of failing the trial.
- **`compare` paths.** `cielo-bench compare` stores run directories relative to the project.
- **Documentation matches the code and the data.**
  - EVALS.md now gives the `moon_phase` matching window (±60 min) and says that evidence needs one `ok` matching call per body.
  - It also says that "fabricated value" counts VALUE lines, not numbers stated in the prose.
  - EVALS.md and the benchmark card say that rough knowledge can reject many false premises, so the no-tool condition is not pure ignorance.

## [1.0.0] - 2026-11-22

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

[Unreleased]: https://github.com/vvanegasar/cielo-bench/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/vvanegasar/cielo-bench/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/vvanegasar/cielo-bench/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/vvanegasar/cielo-bench/releases/tag/v1.0.0
