# ADR-0004 — Distribution: official MCP Registry + npm; no OpenAI listing in v0

- Status: Accepted · 2026-10-20

## Context
The server must be discoverable and installable from a personal account at no cost.

## Decision
1. Source on GitHub under the personal account (`vvanegasar`), public, MIT license.
2. Package on npm, so the server can also run locally (stdio).
3. Listing in the official MCP Registry under the namespace `io.github.vvanegasar/<name>`, authenticated with GitHub.
   - **Registry entries cannot be unpublished.** The final name is chosen before the first publish.
   - Community directories that index the official registry (for example Glama) pick it up automatically.
4. **No OpenAI listing in v0.** It requires individual identity verification plus an organization, and its policy rejects unofficial connectors to third-party services.
5. **Claude connector directory: deferred.** Its policy asks developers to own or control the APIs they connect to. Ask mcp-review@anthropic.com before applying.

## Consequences
- Zero cost.
- Discoverability depends on the registry plus the write-up and the demo video. The project is promoted through results, not directory listings.
