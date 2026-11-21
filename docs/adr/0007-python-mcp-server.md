# ADR-0007 — The v1 MCP server is Python over stdio, not TypeScript on Workers

- Status: Accepted · 2026-11-19 (proposed 2026-11-18; accepted by Valentina Vanegas)
- Supersedes: ADR-0002 for `server/` (the `evals/` part stands). Defers: ADR-0003 (no hosted server in v1). Amends: ADR-0004 (no npm package). Builds on: ADR-0001 and ADR-0005.

## Context

ADR-0002 and ADR-0003 planned the `cielo` server in TypeScript, on Cloudflare Workers, over Streamable HTTP. It was never built. Since then, ADR-0005 put the benchmark's tools in Python, behind a domain interface (`cielo_bench.domain`) and a registry (`cielo_bench.domains.REGISTRY`). The harness calls them in-process. A second domain, tabular company data (ADR-0006), is registered on the same interface.

A TypeScript server would have to reimplement every tool: the Horizons client with its cache and serialization, the ephemeris parsing, the rise and set definitions, and later the SQL guard of domain 2. Two implementations of the instrument drift apart. The MCP condition would then measure tools that differ from the ones the benchmark validated.

Hosting on Workers also means running and protecting a public endpoint: rate limits, abuse, an account, and JPL fair use at the scale of every visitor. All of that serves a research instrument that its users run on their own machines. Claude Desktop and most local MCP clients start servers over stdio, and the official MCP Python SDK supports stdio and Streamable HTTP.

## Decision

### 1. Python, the official SDK, stdio

- `server/` is a Python package, `cielo_mcp`, built on the official MCP Python SDK, pinned to `mcp==2.3.0` (latest release, 2026-10-02). Its high-level server is `MCPServer`, the 2.x name of FastMCP (`mcp.server.fastmcp` was removed in 2.0).
- Transport: stdio, the default (Claude Desktop). Streamable HTTP is available for local use only. `--transport streamable-http` refuses any host that is not a loopback address, and the SDK turns on DNS-rebinding protection for localhost. No hosting, no remote endpoint, no accounts.
- Packaging: the server has its own `server/pyproject.toml`, so the core's packaging is untouched. The core is required but not declared as a dependency. It is not on PyPI, and declaring it would let `pip` resolve the name from a public index (dependency confusion). The install order (core, then server) is documented, and the entry point gives a clear message if the core is missing.

### 2. No domain logic in the server

- Domains come from `cielo_bench.domains.REGISTRY` and are loaded with the core's `get_domain`. If a registered domain cannot be loaded or set up, it is skipped with a warning and listed in `cielo://about`, and the other domains are still served. A domain that is still being built cannot take the server down.
- Each MCP tool is one entry of a domain's `tool_specs()`: the same name, description and JSON Schema the benchmark hands to model APIs. Tools are built as SDK `Tool` objects directly from that spec, with hand-built argument metadata, instead of from a Python signature, so no schema is restated.
- Arguments reach the domain executor exactly as the client sent them. The executor validates them and answers `invalid_input`, as it does in the benchmark. The server adds no validation rules of its own and does not repair malformed arguments.
- A tool name used by two domains is exposed as `<domain>_<tool>` for both. The executor still receives its own name. Names that collide even after prefixing stop the server at start-up.
- Executors are made with `fault_profile=None`, `offline` set to the inverse of `--live`, a request cap (0 in cache-only mode), and settings that hold only `CIELO_USER_AGENT` and, when given, `CIELO_CA_BUNDLE` and `CIELO_CACHE_DIR` (`--cache-dir`). API keys and the project's `.env` are never read.

### 3. Results: the contract, unchanged

- `structuredContent` is the executor's result object. The single text block is `json.dumps(result, ensure_ascii=False)`, the same text the benchmark sends to models. `isError` is true for every status except `ok`.
- Every tool advertises the same `outputSchema`, which describes the shared contract: `status` is one of the four statuses, and an `ok` result carries `sources[]`, each with `service`, `query` and `retrieved_at_utc`.
- The server fails closed. An `ok` result without a full citation, a failure that carries values, or an unknown status is not sent. The client gets a generic tool error, and the violation is logged on stderr.

### 4. Cache-only by default, live on request

- **Default: cache only.** Tools answer from what is already cached, and nothing leaves the machine. That is the benchmark's committed fixtures, then the live cache. With an empty live cache, which is how the tests run, it reproduces what the benchmark scored. Anything outside the cache returns `source_unavailable` (`offline_cache_miss`), which also shows the honest-failure path.
- **`--live`.** Tools may query their upstream source. For JPL Horizons the domain's client sends one request at a time per process, at least 1 s apart, with retries and backoff, and caches each response by query. It identifies itself as `cielo-mcp/0.1.0 (MCP server of the cielo-bench research benchmark; non-commercial)`, with no personal data (ADR-0005 §8). Live requests are capped at 100 per server process by default (`--max-live-requests`); past the cap, results are `source_unavailable` with reason `request_budget_exhausted`.
- **The live cache is outside the repository.** Its location is `--cache-dir`, else `CIELO_CACHE_DIR`, else `$XDG_CACHE_HOME/cielo-bench`, else `~/.cache/cielo-bench`, and the core resolves it. The repository's fixtures are written only by `cielo-bench build-golden`.

### 5. Annotations, instructions, resources and prompts

- Every tool is annotated `readOnlyHint: true`. `openWorldHint` is true only with `--live`, because a cache-only tool cannot reach anything outside the machine.
- The server instructions state what the tools are and what the contract guarantees, and nothing more. They never tell the model to verify a claim: whether a model checks on its own is what the benchmark measures, so the instrument must not prompt it.
- Resource `cielo://about` (Markdown) lists the domains and their tools, the mode, the result contract, the method and the data credits.
- Prompt `check_claim(claim)` asks the assistant to check a claim with the tools and cite the sources. It is invoked by the user and never used by the benchmark.

### 6. Faults are never injected by the server

There is no flag or header for fault injection. `build_server(executor_factory=...)` is the in-process seam that the tests use to put a source down end to end. A future MCP adapter in the harness can use it for the fault conditions.

## Why

- **One language with the benchmark and the tools.** The server *is* the benchmark's tools. A test checks that for each call the MCP result equals the executor's result and the text block is byte-identical. A second implementation could not offer that.
- **No infrastructure of anyone's.** No account, no cost, no public endpoint to protect. JPL sees only the load one local user generates, and no personal data is sent anywhere.
- **Where the clients are.** Local stdio is how Claude Desktop runs servers. The official SDK keeps the protocol work maintained: both protocol eras (the `initialize` handshake and 2026-07-28) work, and the tests run both.

## What this replaces

| ADR | It said | Now |
|---|---|---|
| 0002 | `server/` in TypeScript with the official MCP TypeScript SDK, deployed as a Cloudflare Worker; two toolchains, and CI runs both | `server/` in Python with the official MCP Python SDK; one toolchain. The `evals/` decision stands |
| 0003 | Remote server on Cloudflare Workers Free; Workers KV or the Cache API for caching; a Durable Object or a single-flight lock to serialize JPL requests | Deferred: no hosted server in v1. The cache is the core's content-addressed disk cache: the read-only fixtures layered over a live cache outside the repository. Serialization is the Horizons client's per-process lock. A hosted server needs a new ADR |
| 0004 | An npm package for local stdio use; an MCP Registry entry `io.github.vvanegasar/<name>` | No npm package. If the server is ever distributed, it would be a Python package (the official MCP Registry also lists PyPI packages). Nothing is published now. The registry rules stand: choose the final name before the first publish, because entries cannot be unpublished |

`docs/TOOLS.md` now documents what exists. `docs/ARCHITECTURE.md` (server diagram, Workers runtime, fault-injection header) and the component table in `README.md` still describe the TypeScript design; they are outside this change.

## Consequences

- One implementation of each tool, served two ways (in-process for the benchmark, MCP for any client), with a parity test between them.
- The server tests run offline. They cover the tool listing, `ok` calls, a replay of every golden-set call of each registered domain, every input error case, cache misses, and every fault profile each domain declares. They run over both protocol eras and both real transports (a stdio subprocess and Streamable HTTP on 127.0.0.1), with a guard that fails any test that tries to use the network.
- The contract guard applies to every domain, and both registered domains meet it. The golden-set replay test checks it for each one.
- No remote endpoint. Clients that need a URL on the internet, such as web-based connectors, cannot use the server.
- Live lookups never touch the repository. They go to the live cache with their request log, so they do not mix with the golden-set fixtures and do not show up in `git status`. In cache-only mode they are served again, so a user's earlier `--live` lookups also answer offline.
- Serialization is per process. Two live servers, or a live server and a benchmark run at the same time, could send two requests to JPL in parallel. Run one live client at a time.
- The SDK is used through `Tool` objects built from the JSON Schema, a path the SDK supports, with one override (`FuncMetadata.validate_arguments`). The pinned version and the tests guard against API drift; check both before upgrading the SDK.
- Each Horizons day table the server has served stays in memory for the life of the process. Memory is bounded by the cache plus the live-request cap.

## Open questions

1. Move the citation rule into `cielo_bench.domain`, next to the statuses. The rule: every `ok` citation carries `service`, `query` and `retrieved_at_utc`, and a domain may add its own fields, as tabular adds `snapshot_as_of` and `content_sha256`. Today only the server enforces it, so the core's own domain tests would check it too.
2. Should `--live` be the default for Claude Desktop? Proposed: keep cache-only as the default, and show `--live` in the Claude Desktop example in `server/README.md`.
3. Whether the benchmark should add an MCP arm (the same items run through this server) to measure MCP-specific effects such as tool discovery.
4. A per-domain way to declare that a domain has no upstream source, so `openWorldHint` can be false for tabular even in `--live` mode.
