# ADR-0003 — Host the remote server on Cloudflare Workers (free plan)

- Status: Accepted · 2026-10-20

## Context
The server must be reachable over HTTPS for remote MCP clients, at no cost, with caching.

## Options
| Option | Notes (checked 2026-10-20) |
|---|---|
| **Cloudflare Workers Free** | About 100,000 requests/day and 10 ms CPU per request; network wait does not count toward CPU. KV and Cache API available |
| Vercel Hobby | Restricted to non-commercial use. Fine for a portfolio, but it limits future options |
| Hugging Face Spaces | Compute Spaces now require a paid plan |

## Decision
Use Cloudflare Workers, with the Cache API or KV for caching. Use one Durable Object or a single-flight lock only if needed to keep JPL requests serialized.

## Consequences
- The CPU limit means no heavy local computation. Visibility logic stays light, and the heavy work is JPL's.
- Before going public: rate-limit per IP and monitor usage, so upstream services are not overloaded.
