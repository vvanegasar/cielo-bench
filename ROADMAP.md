# Roadmap

Dates are targets in Colombia time (UTC−5). Each milestone ends with a changelog entry.

| Milestone | Target | Definition of done | Status |
|---|---|---|---|
| **v1.0 — The instrument** | Nov 2026 | Domain-independent harness; astronomy domain (144 pairs, 18 templates, JPL Horizons ground truth); tabular enterprise-data domain (126 pairs, synthetic SQLite); pressure × tool × premise design with fault injection; deterministic scorer; Wilson and cluster-bootstrap intervals, McNemar–Holm contrasts and power analysis; read-only MCP server; CI; harness validation with simulated agents | Done |
| **v1.1 — First real-model results (one provider)** | Nov 2026 | Runs on frontier models from one provider with pinned versions (Claude Haiku 5.5 on both domains; Claude Sonnet 5.5, Claude Opus 5.5 and Claude Fable 5.2 on astronomy, with a matched four-model comparison); `results/<run>/` with report, figures, summary and packed, sanitized trials; README results table filled from the generator; results note; agent-assisted audit of the tabular evidence rule | Done (2026-11-23). Redefined from "two providers": the second provider and the manual error analysis moved to v1.2 |
| **v1.2 — Second provider and broader coverage** | Q1 2027 | A frontier model from a second provider, pinned, on the same designs; manual error analysis of the real transcripts, including the author's spot check of the tabular audit; golden set v2 that fixes the `sets_first` and `rises_first` items mixing events from different nights; tabular domain to 15+ templates; dataset card and dataset on Hugging Face; MCP Registry listing | Planned |
| **v1.3 — New conditions** | Q2 2027 | Harder tests of agree-after-check: multi-turn insistence and group pressure, premises closer to the truth, and a free-form answer instead of the VERDICT line; an "act vs. answer" contrast; a human-approval condition for agents that act; a third domain (official statistics) | Planned |

Out of scope for now: a web UI, accounts, any commercial use.
