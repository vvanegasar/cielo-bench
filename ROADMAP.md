# Roadmap

Dates are targets in Colombia time (UTC−5). Each milestone ends with a changelog entry.

| Milestone | Target | Definition of done | Status |
|---|---|---|---|
| **v1.0 — The instrument** | Nov 2026 | Domain-independent harness; astronomy domain (144 pairs, 18 templates, JPL Horizons ground truth); tabular enterprise-data domain (126 pairs, synthetic SQLite); pressure × tool × premise design with fault injection; deterministic scorer; Wilson and cluster-bootstrap intervals, McNemar–Holm contrasts and power analysis; read-only MCP server; CI; harness validation with simulated agents | Done |
| **v1.1 — First real-model results** | Early Dec 2026 | Runs on at least two frontier models from different providers, pinned versions; `results/<run-id>/` with report, figures, summary and packed trials; error analysis; README results table filled from the generator | Next |
| **v1.2 — Broader coverage** | Q1 2027 | Tabular domain to 15+ templates; manual audit of the evidence rule on a sample of real transcripts; dataset card and dataset on Hugging Face; MCP Registry listing | Planned |
| **v1.3 — New conditions** | Q2 2027 | Multi-turn and group pressure; an "act vs. answer" contrast; a human-approval condition for agents that act; a third domain (official statistics) | Planned |

Out of scope for now: a web UI, accounts, any commercial use.
