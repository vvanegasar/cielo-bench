# ADR-0002 — TypeScript for the server, Python for the evaluation harness

- Status: Accepted · 2026-10-20

## Context
The server must run on an edge runtime with the official MCP SDK. The evaluation stack (statistics, data handling, model SDKs) is most mature in Python. Python also shows up in 70 % of the AI engineering job postings reviewed (Oct 2026).

## Decision
- `server/`: TypeScript, using the official MCP TypeScript SDK, deployed as a Cloudflare Worker.
- `evals/`: Python 3.12+, `uv`, `pytest`; official provider SDKs for model calls.

## Consequences
- Two toolchains. CI runs both.
- The contract between them is the MCP protocol itself plus versioned golden-set fixtures (JSON).
