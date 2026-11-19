"""cielo-mcp: the cielo-bench tools as an MCP server.

The server holds no domain logic. It loads every domain registered in
``cielo_bench.domains``, exposes each domain's tools with the domain's own JSON Schema, runs
them with the domain's executor and returns the executor's result unchanged. See
docs/adr/0007-python-mcp-server.md.
"""

__version__ = "0.1.0"
