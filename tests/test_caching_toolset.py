"""Tool-list caching, which ADK does not provide (google/adk-python#3659)."""

from __future__ import annotations

import asyncio

from gemini_act.agent.tools.caching_toolset import CachingToolset


class Ctx:
    def __init__(self, user_id: str = "users/1") -> None:
        self.user_id = user_id


class FakeInnerToolset:
    """A toolset whose upstream discovery is counted rather than performed."""

    def __init__(self, tools=None) -> None:
        self.tool_filter = None
        self.tool_name_prefix = "mcp"
        self._tools = list(tools if tools is not None else ["tool-a", "tool-b"])
        self.calls: list[int] = []

    async def get_tools(self, readonly_context=None):
        self.calls.append(1)
        return list(self._tools)

    async def close(self) -> None:
        pass


def _toolset(ttl: float = 3600.0, tools=None) -> tuple[CachingToolset, FakeInnerToolset]:
    inner = FakeInnerToolset(tools)
    return CachingToolset(inner, cache_ttl_seconds=ttl), inner


async def test_second_call_is_served_from_cache():
    ts, inner = _toolset()

    first = await ts.get_tools(Ctx())
    second = await ts.get_tools(Ctx())

    assert first == second
    assert len(inner.calls) == 1, "the MCP server must be queried only once"


async def test_cache_is_per_user():
    """Different users resolve different tokens, so lists must not be shared."""
    ts, inner = _toolset()

    await ts.get_tools(Ctx("users/1"))
    await ts.get_tools(Ctx("users/2"))

    assert len(inner.calls) == 2


async def test_expired_entry_is_refetched():
    ts, inner = _toolset(ttl=0.0)

    await ts.get_tools(Ctx())
    await ts.get_tools(Ctx())

    assert len(inner.calls) == 2


async def test_concurrent_turns_discover_once():
    """A cold cache under concurrent turns must not stampede the slow server."""
    ts, inner = _toolset()

    async def slow_get_tools(readonly_context=None):
        inner.calls.append(1)
        await asyncio.sleep(0.05)
        return ["tool-a"]

    inner.get_tools = slow_get_tools

    results = await asyncio.gather(*(ts.get_tools(Ctx()) for _ in range(5)))

    assert all(r == ["tool-a"] for r in results)
    assert len(inner.calls) == 1


async def test_invalidate_forces_refetch():
    ts, inner = _toolset()

    await ts.get_tools(Ctx())
    ts.invalidate("users/1")
    await ts.get_tools(Ctx())

    assert len(inner.calls) == 2


async def test_invalidate_all():
    ts, inner = _toolset()

    await ts.get_tools(Ctx("users/1"))
    await ts.get_tools(Ctx("users/2"))
    ts.invalidate()
    await ts.get_tools(Ctx("users/1"))

    assert len(inner.calls) == 3


async def test_close_delegates_to_inner():
    closed = []

    class TrackingInner(FakeInnerToolset):
        async def close(self) -> None:
            closed.append(1)

    ts = CachingToolset(TrackingInner())
    await ts.close()

    assert closed == [1]
