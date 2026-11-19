"""``cielo-mcp``: run the cielo MCP server over stdio (Claude Desktop) or local Streamable HTTP."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING

from . import __version__

if TYPE_CHECKING:
    from .server import ServerConfig

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cielo-mcp",
        description="MCP server for the cielo-bench tools. By default the tools answer only from "
                    "the benchmark's cache and nothing leaves the machine.",
    )
    p.add_argument("--live", action="store_true",
                   help="let tools query their upstream source (NASA/JPL Horizons): serialized, "
                        "cached, generic User-Agent")
    p.add_argument("--max-live-requests", type=_positive_int, default=None, metavar="N",
                   help="with --live: cap on upstream requests per server process (default 100)")
    p.add_argument("--cache-dir", metavar="DIR",
                   help="live cache: where --live responses are written and read back (default "
                        "CIELO_CACHE_DIR, else $XDG_CACHE_HOME/cielo-bench, else ~/.cache/cielo-bench); "
                        "the repository's fixtures are never written")
    p.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio",
                   help="stdio for Claude Desktop and other local clients (default); "
                        "streamable-http serves http://HOST:PORT/mcp on this machine only")
    p.add_argument("--host", default="127.0.0.1", help="streamable-http only; loopback addresses only")
    p.add_argument("--port", type=int, default=8000, help="streamable-http only (default 8000)")
    p.add_argument("--log-level", choices=LOG_LEVELS, default="WARNING", help="logs go to stderr")
    p.add_argument("--version", action="version", version=f"cielo-mcp {__version__}")
    return p


def config_from(args: argparse.Namespace, environ: Mapping[str, str]) -> ServerConfig:
    """Server settings from the command line. From the environment, only three names are read:
    ``CIELO_USER_AGENT``, ``CIELO_CA_BUNDLE`` and ``CIELO_CACHE_DIR``. API keys never are."""
    from .server import DEFAULT_MAX_LIVE_REQUESTS, USER_AGENT, ServerConfig

    return ServerConfig(
        live=args.live,
        max_live_requests=args.max_live_requests or DEFAULT_MAX_LIVE_REQUESTS,
        user_agent=environ.get("CIELO_USER_AGENT") or USER_AGENT,
        ca_bundle=environ.get("CIELO_CA_BUNDLE") or None,
        cache_dir=getattr(args, "cache_dir", None) or environ.get("CIELO_CACHE_DIR") or None,
        log_level=args.log_level,
    )


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    if args.max_live_requests is not None and not args.live:
        p.error("--max-live-requests only applies with --live")
    if args.transport == "streamable-http" and args.host not in LOOPBACK_HOSTS:
        p.error(f"--host must be a loopback address {LOOPBACK_HOSTS}: the HTTP transport is for "
                "local use only and has no authentication")

    try:
        from .server import build_server
    except ImportError as exc:  # the benchmark core is a separate install (server/README.md)
        print(f"cielo-mcp: {exc}. Install the benchmark core first: `pip install -e .` from the "
              "repository root, then `pip install -e ./server`.", file=sys.stderr)
        return 1

    server = build_server(config_from(args, os.environ))
    try:
        if args.transport == "stdio":
            server.run("stdio")
        else:
            host = f"[{args.host}]" if ":" in args.host else args.host
            print(f"cielo-mcp {__version__}: http://{host}:{args.port}/mcp "
                  f"({'live' if args.live else 'cache only'})", file=sys.stderr)
            server.run("streamable-http", host=args.host, port=args.port)
    except KeyboardInterrupt:  # Ctrl-C on a server started by hand
        return 130
    return 0
