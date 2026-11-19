# ADR-0001 — The benchmark is the product; the MCP server is the instrument

- Status: Accepted · 2026-10-20
- Decider: Valentina Vanegas

## Context
Several astronomy MCP servers already wrap the same catalogs (Gaia, SIMBAD, Horizons, MAST). Another wrapper adds little. The open problem in AI engineering is **measuring reliability**: tool choice, factual accuracy, honesty under failure, cost. Most evaluations depend on LLM judges, while astronomy offers exact, external ground truth.

## Decision
Build a benchmark that measures agent reliability against physical ground truth. Build a small MCP server (3 tools) as the system under test, designed for honest failure and citations.

## Consequences
- The value is in `evals/` (methodology, golden set, results). The server stays small.
- Success is measured by reproducible results and published error analysis, not by the number of tools.
- The scope has to stay small to ship in about 4 weeks of part-time work.
