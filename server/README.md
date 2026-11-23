# cielo-mcp — the cielo-bench tools as an MCP server

<!-- mcp-name: io.github.vvanegasar/cielo-mcp -->

`cielo` is the MCP server of [cielo-bench](https://github.com/vvanegasar/cielo-bench), a benchmark that measures whether AI agents check a user's claim with their tools or simply agree with it, judged against an external ground truth (NASA/JPL Horizons ephemerides) instead of another model.

The server exposes **the benchmark's own tools, unchanged**, to any MCP client, such as Claude Desktop or MCP Inspector. A test checks that every MCP result equals what the benchmark's executor returns for the same call. Every `ok` result cites its source (service, query and retrieval time), and when the source is down or a value is not available the tool says so and returns no numbers.

- Python, built on the official [MCP Python SDK](https://pypi.org/project/mcp/) (`mcp==2.3.0`, whose `MCPServer` is the 2.x name of FastMCP).
- stdio for Claude Desktop and other local clients; Streamable HTTP on `127.0.0.1` for local use.
- Read-only tools, a resource with the method and credits (`cielo://about`), and a prompt (`check_claim`).
- Domains are discovered from the benchmark's registry: astronomy, and tabular company data. A new domain's tools are served with no change here.

Design: [ADR-0007](https://github.com/vvanegasar/cielo-bench/blob/main/docs/adr/0007-python-mcp-server.md). Tool contracts: [docs/TOOLS.md](https://github.com/vvanegasar/cielo-bench/blob/main/docs/TOOLS.md).

## Tools

| Tool | What it answers | Source |
|---|---|---|
| `body_position` | Altitude, azimuth, rate of climb, RA/Dec and distance of the Sun, the Moon or a planet at an instant, from Medellín, Bogotá or Barranquilla; with `relative_to`, the angular separation from a second body | NASA/JPL Horizons |
| `body_rise_set` | Rise and set (with their azimuths) and culmination of a body on a local date | NASA/JPL Horizons |
| `moon_phase` | Illuminated fraction of the Moon, waxing or waning, and the Sun–Moon elongation at an instant | NASA/JPL Horizons |
| `describe_schema` | Read-only: tables, columns, keys and conventions of a fictional distributor's database | Synthetic, seeded SQLite snapshot |
| `run_sql` | Read-only: one `SELECT` on that database; anything that could write is rejected as `invalid_input` | Synthetic, seeded SQLite snapshot |

All tools are annotated `readOnlyHint: true`. `openWorldHint` is `true` only in `--live` mode, and only for domains whose tools can reach a source outside the machine (`Domain.external_source`: astronomy yes, tabular no). The tool list comes from the domains themselves, so a new tool appears here without a server change (contracts in [docs/TOOLS.md](https://github.com/vvanegasar/cielo-bench/blob/main/docs/TOOLS.md)).

Each domain also declares fault profiles that make its source behave as down:
- astronomy: `down`, `error`, `empty`, `malformed` and `timeout`;
- tabular: `down`, `error`, `empty`, `timeout` and `permission_denied`.

The benchmark and the tests use them, and every one of them yields `source_unavailable` with no values through MCP. The server itself never injects a fault.

## Install

Python 3.12 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install cielo-mcp       # this server and the benchmark core (cielo-bench); pins mcp==2.3.0
cielo-mcp --version         # cielo-mcp 0.1.1
```

The benchmark core, `cielo-bench`, is installed with it (a 1.1.x release, 1.1.1 or newer) and carries the golden sets and the cached fixtures, so the server works offline. No API keys are needed, and the server never reads any.

From a checkout of the repository, install the core first, then the server:

```bash
pip install -e .            # the benchmark core (cielo_bench)
pip install -e ./server     # this server
```

## Run

```bash
cielo-mcp                                        # stdio, cache only (what a client starts)
cielo-mcp --live                                 # stdio, may query NASA/JPL Horizons
cielo-mcp --live --cache-dir ~/cielo-cache       # same, with the live cache somewhere else
cielo-mcp --transport streamable-http --port 8000   # http://127.0.0.1:8000/mcp
```

Started by hand over stdio, the server waits silently for a client on stdin; stop it with Ctrl-C. Logs go to stderr (`--log-level INFO` for more).

**Cache only (default).** The tools answer from what is already cached, and nothing leaves the machine. The cache is the benchmark's committed fixtures, which cover the golden set's dates (for example 12 December 2026 in Medellín), plus whatever earlier `--live` runs stored in the live cache. For anything else the tools return `source_unavailable` with reason `offline_cache_miss`, which is the honest-failure path the benchmark measures.

**Live (`--live`).** The tools may query NASA/JPL Horizons, following its fair-use policy. The client sends one request at a time, at least 1 s apart, caches every response by query, and identifies itself as `cielo-mcp/0.1.1 (MCP server of the cielo-bench research benchmark; non-commercial)`, with no personal data. There are at most 100 requests per server process (`--max-live-requests N`).

**Live cache.** Live responses, and the log of each request, are stored outside the repository: in `--cache-dir DIR` if given, else `CIELO_CACHE_DIR`, else `$XDG_CACHE_HOME/cielo-bench`, else `~/.cache/cielo-bench`. The repository's fixtures are never written.

Environment variables (optional):
- `CIELO_USER_AGENT` replaces the User-Agent; keep it free of personal data.
- `CIELO_CA_BUNDLE` points TLS verification at another CA bundle.
- `CIELO_CACHE_DIR` sets the live cache (`--cache-dir` wins).

The server reads no other variables. For the default live-cache location the core also honours `XDG_CACHE_HOME`.

## Claude Desktop

Open **Settings → Developer → Edit Config**, or edit the file directly:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Add the server, using the absolute path to `cielo-mcp` in the virtual environment where it is installed (`which cielo-mcp` prints it):

```json
{
  "mcpServers": {
    "cielo": {
      "command": "/absolute/path/to/.venv/bin/cielo-mcp",
      "args": ["--live"]
    }
  }
}
```

On Windows the command is `C:\\absolute\\path\\to\\.venv\\Scripts\\cielo-mcp.exe`. Restart Claude Desktop. Then ask, for example, *"Where will Saturn be from Medellín at 9 pm on 12 December 2026?"*, or use the `check_claim` prompt with a claim to check. Remove `"--live"` to run cache-only. On macOS the server's stderr is in `~/Library/Logs/Claude/mcp-server-cielo.log`.

## MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) v2 needs Node.js (`^22.23.4`, `^24.22.1` or `>=26.12.1`). The commands below use its v2 syntax.

```bash
# Web UI over stdio: list the tools, read cielo://about, call a tool
npx @modelcontextprotocol/inspector@2 /absolute/path/to/.venv/bin/cielo-mcp

# CLI: list the tools, then call one (cached, so it works offline)
npx @modelcontextprotocol/inspector@2 --cli /absolute/path/to/.venv/bin/cielo-mcp \
  --method tools/list
npx @modelcontextprotocol/inspector@2 --cli /absolute/path/to/.venv/bin/cielo-mcp \
  --method tools/call --tool-name body_position \
  --tool-args-json '{"body": "Saturn", "location": {"city": "Medellín"}, "datetime": "2026-12-12T21:00:00-05:00"}'

# Streamable HTTP: start the server, then point the Inspector at it
cielo-mcp --transport streamable-http --port 8000
npx @modelcontextprotocol/inspector@2 --server-url http://127.0.0.1:8000/mcp --transport http
```

The Inspector CLI exits with code 5 when a result has `isError: true`, for example a `source_unavailable` result.

## Example calls

Real results from the cached fixtures. `structuredContent` holds the object, and the text block holds the same JSON.

**`body_position`** with `{"body": "Saturn", "location": {"city": "Medellín"}, "datetime": "2026-12-12T21:00:00-05:00"}` returns `isError: false` (abbreviated):

```json
{
  "status": "ok",
  "body": "Saturn",
  "datetime_local": "2026-12-12T21:00:00-05:00",
  "altitude_deg": 61.63,
  "azimuth_deg": 260.07,
  "altitude_rate_deg_per_hour": -14.72,
  "above_horizon": true,
  "sources": [{
    "service": "NASA/JPL Horizons API",
    "endpoint": "https://ssd.jpl.nasa.gov/api/horizons.api",
    "query": {"COMMAND": "'699'", "SITE_COORD": "'-75.5748,6.2447,1.495'", "STEP_SIZE": "'1 m'", "…": "…"},
    "retrieved_at_utc": "2026-11-19T03:20:08Z",
    "response_sha256": "85fff3ecce8c39e32c1f09ffc10b647e58c7c41ba5e7aa35028b91887932ce79"
  }],
  "credit": "NASA/JPL Solar System Dynamics — Horizons (https://ssd.jpl.nasa.gov/horizons/)"
}
```

Saturn is sinking at 14.72° per hour, two hours after it culminated. Adding `"relative_to": "Jupiter"` to a `body_position` call adds `separation_deg`, with one citation per body: from Medellín at 05:00 on 12 December 2026, Venus is 68.74° from Jupiter.

**`body_rise_set`** with `{"body": "Saturn", "location": {"city": "Medellín"}, "date": "2026-12-12"}` gives:
- a rise at `13:07`, at azimuth 89.12° (almost due east);
- culmination at `19:09`, 84.57° high;
- a set at `01:14` (the night before), at azimuth 270.88°.

Each time comes in local time and UTC, with the same citation.

**`moon_phase`** with `{"location": {"city": "Medellín"}, "datetime": "2026-12-26T19:30:00-05:00"}` gives `illuminated_fraction_pct` 86.86, `phase` `waning` and `sun_moon_elongation_deg` 137.4, two days after the full Moon.

**A date outside the cache**, in cache-only mode, returns `isError: true` and no values:

```json
{"status": "source_unavailable", "source": "NASA/JPL Horizons API", "reason": "offline_cache_miss",
 "message": "NASA/JPL Horizons API could not provide data (offline_cache_miss). No values are returned."}
```

**Invalid input**, such as `"body": "Pluto"`, returns `isError: true`:

```json
{"status": "invalid_input", "message": "body must be one of ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune']"}
```

From Python, with the SDK's client:

```python
import anyio
from mcp import Client, StdioServerParameters

async def main() -> None:
    server = StdioServerParameters(command="cielo-mcp")
    async with Client(server) as client:
        result = await client.call_tool("body_position", {
            "body": "Saturn", "location": {"city": "Medellín"}, "datetime": "2026-12-12T21:00:00-05:00"})
        print(result.is_error, result.structured_content["altitude_deg"])  # False 61.63

anyio.run(main)
```

## Tests

```bash
pip install -e "./server[dev]"
pytest server/tests        # or: cd server && pytest
```

The suite runs offline (127 tests in about 8 s). A guard fails any test that tries to reach the network, and the live cache is an empty temporary directory. It covers:

- the tool listing (schemas, annotations, output schema);
- `ok` calls compared with the benchmark's executor (same object, byte-identical text), including `moon_phase`, `relative_to`, and a replay of every call in each registered domain's golden set;
- every input error case and cache misses;
- every fault profile each domain declares, run end to end through MCP;
- the command line, including `--cache-dir` and the environment settings it reads;
- domain discovery, including a registered domain that does not exist yet;
- name prefixing when two domains share a tool name, and the contract guard;
- the resource and the prompt.

The MCP cases run over both protocol eras: the `initialize` handshake (what Claude Desktop speaks) and 2026-07-28. The real transports are tested too: the server as a stdio subprocess, in both eras, and Streamable HTTP on 127.0.0.1.

## Credits

Ephemerides: NASA/JPL Solar System Dynamics — Horizons. cielo-bench is an independent project and is not endorsed by NASA or JPL. See [DATA-SOURCES](https://github.com/vvanegasar/cielo-bench/blob/main/docs/DATA-SOURCES.md).

MIT license, see [LICENSE](https://github.com/vvanegasar/cielo-bench/blob/main/LICENSE).
