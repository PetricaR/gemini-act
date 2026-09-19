"""The MCP server instance, and the policy every tool on it shares.

`server.py` holds the tools; this module holds everything that is true of all
of them — the server's identity and instructions, the annotation vocabulary,
and the wrapper that turns a raised exception into an MCP tool error.

Three decisions are worth stating, because each has a cheaper-looking
alternative that is wrong here.

**The wire name and the Python name are deliberately different.** Over MCP a
tool is `imobiliare_search_listings`; in Python the same function is still
`cauta`. The wire name follows the convention every MCP client's tool list is
read under — `{service}_{action}_{resource}`, English, prefixed so it cannot
collide with another server loaded beside it. The Python name stays because
`imobiliare/agent_tools/` imports these functions and calls them directly, in
process, and renaming them would be a large diff through working code for no
reader's benefit. `@tool(name=...)` is where the two meet.

**The decorator registers a wrapper but returns the original function.** So
`server.cauta` is still the plain, synchronous function it always was and the
in-process adapter is unaffected, while what MCP sees is `async` and hops to a
worker thread. That matters: everything underneath is blocking `httpx`, an
appraisal spends minutes in it, and FastMCP calls a synchronous tool inline on
the event loop — one appraisal would otherwise stall every other client of an
HTTP-transport server for the duration.

**Failures are raised, not returned.** A dict with `status: "error"` comes back
over MCP as `isError: false`, which reads to a model as success; only a raised
error sets the flag. That is the opposite of the convention in
`gemini_act/agent/tools/`, where an ADK function tool has no such flag and the
dict is the only channel there is. Both are the same intent — a failure must
read as a failure — expressed in the vocabulary each protocol gives.
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

import anyio.to_thread

# The class was renamed between MCP SDK majors: `FastMCP` on 1.x, `MCPServer`
# on 2.x. Accept either rather than forcing a resolution that would fight the
# google-adk pin (1.x). `ToolError` moved with it.
try:  # pragma: no cover - depends on which SDK major is installed
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP as MCPServer
    from mcp.server.fastmcp.exceptions import ToolError

from mcp.types import ToolAnnotations

from .client import SessionError

logger = logging.getLogger(__name__)

__all__ = [
    "INSTRUCTIONS",
    "SERVER_NAME",
    "ToolError",
    "local",
    "mcp",
    "read_only",
    "tool",
    "writes",
]

# `{service}_mcp`, the naming convention MCP clients' server lists are read
# under. Not `imobiliare_ro_mcp`: imobiliare.ro is one of four listing sources
# behind these tools, not the whole of what the server does.
SERVER_NAME = "imobiliare_mcp"

WEBSITE_URL = "https://www.imobiliare.ro"

# Shown to the model once, ahead of the tool list. It is the only place that
# can say what the tools cannot say individually: which source to reach for,
# in what order to work, and what the numbers mean.
INSTRUCTIONS = """\
Romanian residential property intelligence: listing search across four sources, a
valuation under the Romanian standards, due-diligence audits, and a PDF dossier.

The four search tools are not interchangeable:

* `imobiliare_search_listings` — imobiliare.ro's own AI search. Best relevance, but it
  needs a browser-captured session that expires within minutes; it falls back to the
  headless route by itself when the session is gone.
* `imobiliare_search_listings_headless` — the same site with no credential at all.
* `imobiliare_search_imo360` — nationwide, unauthenticated, selects geographically rather
  than textually, and is the only source carrying rentals, so the only one that makes a
  gross yield computable (`imobiliare_get_market_pulse`).
* `imobiliare_search_imoradar` — an aggregator over imobiliare.ro, storia.ro, olx.ro and
  publi24.ro at once, so the only one that reaches owner-posted stock.

An order of work that avoids wasted calls:

1. Search once, then keep the `resume_token`. `imobiliare_resume_search` and
   `imobiliare_get_market_stats` re-read it without spending a fresh session, so change
   filters there rather than searching again.
2. Read `imobiliare_get_market_stats` before individual listings — it establishes what a
   fair price per usable sqm is for the segment, which every later judgement rests on.
3. `imobiliare_appraise_property` values one property under SEV 2025 / GEV 630 with a
   comparables grid, the location, and a vision pass over the photographs. Then
   `imobiliare_plan_negotiation` on the same id turns that into an offer ladder.
4. `imobiliare_generate_pdf_report` last: it orchestrates the audits into one dossier and
   is the most expensive call here.

Conventions in every result: prices are EUR; surfaces are usable sqm; floors are
normalised to integers (parter 0, demisol -1, mansardă 99); a listing id is the trailing
number of an imobiliare.ro offer URL. A missing value is reported as null and is never
treated as satisfying a constraint.

Tools report failure as a tool error carrying the reason and, where one exists, the
alternative worth trying. Relay that reason; never present a failed call as a result.
"""

mcp = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS, website_url=WEBSITE_URL)


# --- the annotation vocabulary -------------------------------------------
#
# Per the specification, `destructiveHint` and `idempotentHint` are meaningful
# only when `readOnlyHint` is false, so the read-only helper below omits them
# rather than asserting defaults that say nothing. Annotations are hints for
# how a client should present a call, never a security boundary.


def read_only(title: str) -> ToolAnnotations:
    """A tool that only reads, and reads from somewhere outside this process."""
    return ToolAnnotations(title=title, readOnlyHint=True, openWorldHint=True)


def local(title: str) -> ToolAnnotations:
    """A tool that only reads, and answers entirely from data shipped in-package."""
    return ToolAnnotations(title=title, readOnlyHint=True, openWorldHint=False)


def writes(title: str, *, destructive: bool = False, idempotent: bool = False) -> ToolAnnotations:
    """A tool that changes something — a file on disk, or state upstream.

    `destructive` is set for the tools that take a caller-chosen output path
    and overwrite whatever is there; it is what makes a client ask first, which
    is the same contract the Chat agent's prompt imposes on writing tools.
    """
    return ToolAnnotations(
        title=title,
        readOnlyHint=False,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        openWorldHint=True,
    )


# --- failures ------------------------------------------------------------

# Every deliberate failure in this package is a `RuntimeError` subclass defined
# in one of its own modules: SessionError, Imo360Error, ImoradarError,
# DriveIndisponibil, StoriaIndisponibil, RegistruIndisponibil, Blocked. Each
# already carries a message written to be read. Recognising them by origin
# rather than by import keeps this module from pulling in the eight modules
# that define them just to name their exception types.
_PACKAGE = "imobiliare."

# Said when the imobiliare.ro AI session is gone, which is the failure a caller
# hits most and the one where doing something else works immediately.
_SESSION_HINT = (
    " The session for imobiliare.ro's AI search has to be captured from a browser and "
    "expires within minutes. Use imobiliare_search_listings_headless, "
    "imobiliare_search_imo360 or imobiliare_search_imoradar instead — none of them needs "
    "a credential — or imobiliare_resume_search with a resume_token from an earlier "
    "search, which outlives the session that produced it."
)


def _as_tool_error(tool_name: str, exc: Exception) -> ToolError:
    """Turn whatever was raised into a message the caller can act on."""
    if isinstance(exc, SessionError):
        return ToolError(f"{exc}.{_SESSION_HINT}")

    if isinstance(exc, RuntimeError) and type(exc).__module__.startswith(_PACKAGE):
        # Raised on purpose by this package, with its own explanation.
        return ToolError(str(exc))

    if isinstance(exc, (ValueError, LookupError)):
        # Almost always an identifier that resolved to nothing.
        return ToolError(
            f"{exc} — check the listing id or address. A listing id is the trailing "
            f"number of an imobiliare.ro offer URL."
        )

    if isinstance(exc, PermissionError):
        return ToolError(f"Cannot write there: {exc}. Choose a path this process may write to.")

    if isinstance(exc, OSError):
        return ToolError(f"Filesystem or network error: {exc}")

    # Anything else is a defect rather than a condition. The traceback goes to
    # the server's log; the caller gets the type and message, which is enough
    # to decide whether to retry, and no internals.
    logger.exception("Unhandled error in %s", tool_name)
    return ToolError(f"{type(exc).__name__}: {exc}")


def _guarded(tool_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """`fn`, off the event loop, with its exceptions mapped to tool errors.

    `functools.wraps` is load-bearing beyond cosmetics: FastMCP builds the
    input and output schemas with `inspect.signature(..., eval_str=True)`,
    which follows `__wrapped__` back to `fn` and so evaluates its annotations
    against *its* module globals. Without that the postponed annotations in
    `server.py` (`Filters | None`, `SortBy`) would be resolved here, where
    those names do not exist.
    """

    @functools.wraps(fn)
    async def run(**kwargs: Any) -> Any:
        def call() -> Any:
            try:
                return fn(**kwargs)
            except ToolError:
                raise
            except Exception as exc:  # noqa: BLE001 - every failure is reported as one
                raise _as_tool_error(tool_name, exc) from exc

        return await anyio.to_thread.run_sync(call)

    return run


def tool(
    *,
    name: str,
    annotations: ToolAnnotations,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Publish a function over MCP under `name`, and hand the function back.

    Args:
        name: The tool's name on the wire — prefixed, English, snake_case.
        annotations: Built by `read_only`, `local` or `writes`; carries the
            human-readable title as well as the behaviour hints.

    Returns:
        A decorator returning its argument unchanged, so the module-level name
        in `server.py` stays the plain function that `agent_tools` imports.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        registered = fn if inspect.iscoroutinefunction(fn) else _guarded(name, fn)
        mcp.tool(name=name, title=annotations.title, annotations=annotations)(registered)
        return fn

    return decorator
