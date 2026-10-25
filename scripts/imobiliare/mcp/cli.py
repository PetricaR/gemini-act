"""The `imobiliare-mcp` command: run the server, or inspect what it publishes.

    imobiliare-mcp                                   # stdio, for a local client
    imobiliare-mcp --transport streamable-http       # HTTP on 127.0.0.1:8081/mcp
    imobiliare-mcp --list-tools                      # the catalogue, no server

Two defaults are chosen rather than inherited, and both are about the failure
they prevent:

**stdio carries the protocol on stdout**, so anything else written there
corrupts the stream and the client reports a parse error rather than the print
statement that caused it. FastMCP already sends its own logs to stderr; this
module makes that explicit for the root logger so a dependency that logs at
import — `httpx` does, on every request — cannot land in the transport.

**HTTP binds to loopback with DNS-rebinding protection on.** A server on
0.0.0.0 with no `Origin` check can be driven by any page the operator happens
to visit, and these tools reach a configured Google Drive folder and a Maps
key. `--host 0.0.0.0` is available for putting it behind a real proxy, and
says so when used.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8081
DEFAULT_PATH = "/mcp"


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("gemini-act")
    except PackageNotFoundError:  # pragma: no cover - running from a source tree
        return "0.0.0+source"


def _configure_logging(level: str) -> None:
    """Root logging to stderr, whatever the transport.

    `force=True` because FastMCP calls `basicConfig` itself when the server
    object is constructed — which happens at import, before this runs — and a
    second call without it would be a silent no-op.
    """
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def _catalogue() -> list[dict[str, Any]]:
    """Every published tool, as the wire describes it."""
    import asyncio

    from . import server  # noqa: F401 - importing it is what registers the tools
    from .app import mcp

    tools = asyncio.run(mcp.list_tools())
    out: list[dict[str, Any]] = []
    for t in sorted(tools, key=lambda t: t.name):
        ann = t.annotations
        out.append(
            {
                "name": t.name,
                "title": t.title,
                "description": (t.description or "").strip(),
                "read_only": bool(ann and ann.readOnlyHint),
                "destructive": bool(ann and ann.destructiveHint),
                "open_world": bool(ann and ann.openWorldHint),
                "parameters": sorted((t.inputSchema or {}).get("properties", {})),
                "required": sorted((t.inputSchema or {}).get("required", [])),
            }
        )
    return out


def _print_catalogue(as_json: bool) -> None:
    from .app import INSTRUCTIONS, SERVER_NAME

    tools = _catalogue()
    if as_json:
        json.dump(
            {"server": SERVER_NAME, "version": _version(), "tools": tools},
            sys.stdout,
            indent=2,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return

    print(f"{SERVER_NAME} {_version()} — {len(tools)} tools\n")
    print(INSTRUCTIONS.rstrip())
    print()
    for t in tools:
        if t["read_only"]:
            kind = "read-only"
        else:
            kind = "writes, destructive" if t["destructive"] else "writes"
        print(f"  {t['name']}")
        print(f"      {t['title']}  [{kind}]")
        for line in textwrap.wrap(_summary(t["description"]), width=88):
            print(f"      {line}")
        if t["required"]:
            print(f"      required: {', '.join(t['required'])}")
        print()


def _summary(description: str) -> str:
    """The docstring's first paragraph on one line.

    Not its first *line*: these docstrings wrap, so a line is usually half a
    sentence and reads as truncated.
    """
    paragraph: list[str] = []
    for line in description.splitlines():
        if not line.strip():
            break
        paragraph.append(line.strip())
    return " ".join(paragraph)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="imobiliare-mcp",
        description=(
            "MCP server for Romanian residential property search, valuation and due diligence."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Configuration is environment-driven (GEMINI_ACT_ prefix); see the package "
            "README for the variables each tool needs and which tools work without any."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    p.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default="stdio",
        help=(
            "stdio (default) for a local client that launches this as a subprocess; "
            "streamable-http to serve it over the network. sse is the legacy HTTP "
            "transport, deprecated by the specification — do not choose it for anything new."
        ),
    )
    p.add_argument("--host", default=DEFAULT_HOST, help=f"HTTP bind address ({DEFAULT_HOST})")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port ({DEFAULT_PORT})")
    p.add_argument("--path", default=DEFAULT_PATH, help=f"HTTP endpoint path ({DEFAULT_PATH})")
    p.add_argument(
        "--stateful",
        action="store_true",
        help=(
            "Keep per-client session state on the HTTP transport. Off by default: the "
            "protocol is moving to a stateless core, and stateless is what survives being "
            "run behind a load balancer or on more than one instance."
        ),
    )
    p.add_argument(
        "--allow-remote",
        action="store_true",
        help=(
            "Accept HTTP requests whose Origin is not loopback. Only with a proxy that "
            "authenticates in front of it — these tools read a configured Drive folder."
        ),
    )
    p.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
    )
    p.add_argument(
        "--list-tools",
        action="store_true",
        help="Print the tool catalogue and exit, without starting a server.",
    )
    p.add_argument("--json", action="store_true", help="With --list-tools, print JSON.")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    _configure_logging(args.log_level)

    if args.list_tools:
        _print_catalogue(args.json)
        return

    from . import server  # noqa: F401 - importing it is what registers the tools
    from .app import SERVER_NAME, mcp

    if args.transport == "stdio":
        logger.info("%s %s starting on stdio", SERVER_NAME, _version())
        mcp.run(transport="stdio")
        return

    if args.transport == "sse":
        logger.warning(
            "The sse transport is deprecated by the MCP specification; "
            "prefer --transport streamable-http."
        )

    from mcp.server.transport_security import TransportSecuritySettings

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.settings.streamable_http_path = args.path
    mcp.settings.stateless_http = not args.stateful
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=not args.allow_remote,
        allowed_hosts=[f"{args.host}:{args.port}", "localhost", "127.0.0.1"],
        allowed_origins=[f"http://{args.host}:{args.port}", "http://localhost", "http://127.0.0.1"],
    )

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning(
            "Binding %s, which is reachable off this machine. These tools read a "
            "configured Drive folder and spend a Maps key — put an authenticating "
            "proxy in front of this port.",
            args.host,
        )

    logger.info(
        "%s %s starting on http://%s:%s%s (%s)",
        SERVER_NAME,
        _version(),
        args.host,
        args.port,
        args.path,
        "stateful" if args.stateful else "stateless",
    )
    mcp.run(transport=args.transport)


if __name__ == "__main__":  # pragma: no cover
    main()
