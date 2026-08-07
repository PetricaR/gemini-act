"""A toolset wrapper that caches its inner toolset's tool list.

ADK calls `get_tools()` on every LLM turn, and each call is a live `list_tools`
round trip to the MCP server. The Workspace MCP servers take 15-25 seconds to
answer one of those, so with several servers wired up an agent turn spends most
of its budget rediscovering tool definitions that never change.

Cross-request caching is an open ADK feature request, not something the library
does yet (google/adk-python#3659), so it is done here.

Cached per user: the tool list a server returns can in principle depend on the
caller's grants, and the header provider resolves a different token per user, so
sharing one list across users would be wrong.

Wraps by composition rather than subclassing a specific toolset class, so it can
sit in front of anything that implements `BaseToolset` — including the
`AgentRegistrySingleMcpToolset` returned by `AgentRegistry.get_mcp_toolset()`.
"""

from __future__ import annotations

import asyncio
import logging
import time

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset

logger = logging.getLogger(__name__)


class CachingToolset(BaseToolset):
    """Wraps a toolset and reuses a previously fetched tool list for a while."""

    def __init__(self, inner: BaseToolset, *, cache_ttl_seconds: float = 3600.0) -> None:
        super().__init__(tool_filter=inner.tool_filter, tool_name_prefix=inner.tool_name_prefix)
        self._inner = inner
        self._cache_ttl_seconds = cache_ttl_seconds
        self._tool_cache: dict[str, tuple[float, list[BaseTool]]] = {}
        self._cache_locks: dict[str, asyncio.Lock] = {}
        self._label = inner.tool_name_prefix or "mcp"

    def _fresh(self, key: str) -> list[BaseTool] | None:
        entry = self._tool_cache.get(key)
        if entry is None:
            return None
        fetched_at, tools = entry
        if time.monotonic() - fetched_at >= self._cache_ttl_seconds:
            return None
        return tools

    async def get_tools(self, readonly_context: ReadonlyContext | None = None) -> list[BaseTool]:
        key = readonly_context.user_id if readonly_context else ""

        cached = self._fresh(key)
        if cached is not None:
            return cached

        lock = self._cache_locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another turn may have populated the cache while we waited.
            cached = self._fresh(key)
            if cached is not None:
                return cached

            started = time.monotonic()
            tools = await self._inner.get_tools(readonly_context)
            elapsed = time.monotonic() - started
            self._tool_cache[key] = (time.monotonic(), tools)
            logger.info(
                "Discovered %d %s tool(s) in %.1fs; cached for %.0fs",
                len(tools),
                self._label,
                elapsed,
                self._cache_ttl_seconds,
            )
            return tools

    async def close(self) -> None:
        await self._inner.close()

    def invalidate(self, user_id: str | None = None) -> None:
        """Drop cached tools, for one user or for everyone."""
        if user_id is None:
            self._tool_cache.clear()
        else:
            self._tool_cache.pop(user_id, None)
