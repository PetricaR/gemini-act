"""Tool-list caching, which ADK does not provide (google/adk-python#3659)."""

from __future__ import annotations

import asyncio

from gemini_act.agent.tools.caching_toolset import CachingMcpToolset


class Ctx:
    def __init__(self, user_id: str = "users/1") -> None:
        self.user_id = user_id


def _toolset(monkeypatch, ttl: float = 3600.0, tools=None) -> tuple[CachingMcpToolset, list[int]]:
    """A toolset whose upstream discovery is counted rather than performed."""
    from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

    ts = CachingMcpToolset(
        connection_params=StreamableHTTPConnectionParams(url="https://example.invalid/mcp"),
        cache_ttl_seconds=ttl,
    )
    calls: list[int] = []

    async def fake_super(self, readonly_context=None):
        calls.append(1)
        return list(tools if tools is not None else ["tool-a", "tool-b"])

    monkeypatch.setattr("google.adk.tools.mcp_tool.McpToolset.get_tools", fake_super)
    return ts, calls


async def test_second_call_is_served_from_cache(monkeypatch):
    ts, calls = _toolset(monkeypatch)

    first = await ts.get_tools(Ctx())
    second = await ts.get_tools(Ctx())

    assert first == second
    assert len(calls) == 1, "the MCP server must be queried only once"


async def test_cache_is_per_user(monkeypatch):
    """Different users resolve different tokens, so lists must not be shared."""
    ts, calls = _toolset(monkeypatch)

    await ts.get_tools(Ctx("users/1"))
    await ts.get_tools(Ctx("users/2"))

    assert len(calls) == 2


async def test_expired_entry_is_refetched(monkeypatch):
    ts, calls = _toolset(monkeypatch, ttl=0.0)

    await ts.get_tools(Ctx())
    await ts.get_tools(Ctx())

    assert len(calls) == 2


async def test_concurrent_turns_discover_once(monkeypatch):
    """A cold cache under concurrent turns must not stampede the slow server."""
    ts, calls = _toolset(monkeypatch)

    async def slow_super(self, readonly_context=None):
        calls.append(1)
        await asyncio.sleep(0.05)
        return ["tool-a"]

    monkeypatch.setattr("google.adk.tools.mcp_tool.McpToolset.get_tools", slow_super)

    results = await asyncio.gather(*(ts.get_tools(Ctx()) for _ in range(5)))

    assert all(r == ["tool-a"] for r in results)
    assert len(calls) == 1


async def test_invalidate_forces_refetch(monkeypatch):
    ts, calls = _toolset(monkeypatch)

    await ts.get_tools(Ctx())
    ts.invalidate("users/1")
    await ts.get_tools(Ctx())

    assert len(calls) == 2


async def test_invalidate_all(monkeypatch):
    ts, calls = _toolset(monkeypatch)

    await ts.get_tools(Ctx("users/1"))
    await ts.get_tools(Ctx("users/2"))
    ts.invalidate()
    await ts.get_tools(Ctx("users/1"))

    assert len(calls) == 3
