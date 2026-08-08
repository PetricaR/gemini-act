"""The per-user registry of connected MCP servers, and the toolset over it."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset

from gemini_act.agent.tools import custom_mcp
from gemini_act.agent.tools.custom_mcp import CustomMcpToolset
from gemini_act.config import Settings
from gemini_act.mcp.spec import McpServerSpec, McpSpecError
from gemini_act.mcp.store import InMemoryMcpServerStore, McpRegistry

ADA = "users/ada"
BOB = "users/bob"


def _settings(**overrides) -> Settings:
    return Settings(token_store="memory", **overrides)


def _registry(**overrides) -> McpRegistry:
    settings = _settings(**overrides)
    return McpRegistry(InMemoryMcpServerStore(), settings)


def _spec(name: str = "acme", url: str = "", **overrides) -> McpServerSpec:
    return McpServerSpec(name=name, url=url or f"https://{name}.example.com/mcp", **overrides)


def _context(user_id: str, invocation_id: str = "inv-1") -> ReadonlyContext:
    """A ReadonlyContext carrying just what a toolset reads off it."""
    return ReadonlyContext(
        SimpleNamespace(
            invocation_id=invocation_id,
            user_id=user_id,
            session=SimpleNamespace(state={}),
            agent=None,
        )
    )


class FakeTool(BaseTool):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description=name)


class FakeToolset(BaseToolset):
    """Stands in for a live McpToolset, without a server behind it.

    Reachability is read from `broken` on every call, not captured at build
    time: a real server can come back up under a connection we already hold.
    """

    def __init__(self, tool_names: list[str], prefix: str, broken: set[str]) -> None:
        super().__init__(tool_name_prefix=prefix)
        self._tool_names = tool_names
        self._broken = broken
        self.closed = False

    async def get_tools(self, readonly_context=None) -> list[BaseTool]:
        if self.tool_name_prefix in self._broken:
            raise ConnectionError("server is down")
        return [FakeTool(name) for name in self._tool_names]

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_servers(monkeypatch):
    """Replace live connections with fakes, and record what was built."""
    built: list[McpServerSpec] = []
    broken: set[str] = set()

    def fake_build(spec: McpServerSpec, settings: Settings) -> FakeToolset:
        built.append(spec)
        return FakeToolset(["search", "fetch"], prefix=spec.name, broken=broken)

    monkeypatch.setattr(custom_mcp, "build_toolset", fake_build)
    return SimpleNamespace(built=built, broken=broken)


# --- the registry ---


async def test_a_users_servers_are_their_own():
    registry = _registry()
    await registry.add(ADA, _spec("acme"))

    assert [spec.name for spec in await registry.list(ADA)] == ["acme"]
    assert await registry.list(BOB) == []


async def test_adding_the_same_name_replaces_rather_than_duplicates():
    """Re-pasting a server with a new token is an update, not a second entry."""
    registry = _registry()
    await registry.add(ADA, _spec("acme", headers={"Authorization": "old"}))
    replaced = await registry.add(ADA, _spec("acme", headers={"Authorization": "new"}))

    servers = await registry.list(ADA)
    assert replaced is True
    assert len(servers) == 1
    assert servers[0].headers == {"Authorization": "new"}


async def test_stops_at_the_per_user_limit():
    registry = _registry(custom_mcp_max_per_user=2)
    await registry.add(ADA, _spec("one"))
    await registry.add(ADA, _spec("two"))

    with pytest.raises(McpSpecError, match="limit"):
        await registry.add(ADA, _spec("three"))


async def test_replacing_a_server_is_allowed_at_the_limit():
    """Otherwise a full list could never have a token refreshed."""
    registry = _registry(custom_mcp_max_per_user=1)
    await registry.add(ADA, _spec("one"))
    assert await registry.add(ADA, _spec("one", headers={"A": "b"})) is True


async def test_remove_reports_whether_there_was_anything_to_remove():
    registry = _registry()
    await registry.add(ADA, _spec("acme"))

    assert await registry.remove(ADA, "acme") is True
    assert await registry.remove(ADA, "acme") is False
    assert await registry.list(ADA) == []


async def test_clear_drops_them_all_and_counts():
    registry = _registry()
    await registry.add(ADA, _spec("one"))
    await registry.add(ADA, _spec("two"))

    assert await registry.clear(ADA) == 2
    assert await registry.list(ADA) == []


async def test_unknown_user_has_no_servers():
    assert await _registry().list("") == []


# --- the toolset ---


async def test_no_servers_means_no_tools(fake_servers):
    toolset = CustomMcpToolset(_registry(), _settings())
    assert await toolset.get_tools(_context(ADA)) == []
    assert fake_servers.built == []


async def test_tools_are_prefixed_with_their_server(fake_servers):
    registry = _registry()
    await registry.add(ADA, _spec("acme"))
    toolset = CustomMcpToolset(registry, _settings())

    tools = await toolset.get_tools(_context(ADA))

    assert sorted(tool.name for tool in tools) == ["acme_fetch", "acme_search"]


async def test_two_servers_keep_their_same_named_tools_apart(fake_servers):
    registry = _registry()
    await registry.add(ADA, _spec("acme"))
    await registry.add(ADA, _spec("globex"))
    toolset = CustomMcpToolset(registry, _settings())

    names = sorted(tool.name for tool in await toolset.get_tools(_context(ADA)))

    assert names == ["acme_fetch", "acme_search", "globex_fetch", "globex_search"]


async def test_one_users_servers_are_invisible_to_another(fake_servers):
    """The whole point of resolving per invocation rather than at build time."""
    registry = _registry()
    await registry.add(ADA, _spec("acme"))
    toolset = CustomMcpToolset(registry, _settings())

    assert await toolset.get_tools(_context(BOB)) == []
    assert [tool.name for tool in await toolset.get_tools(_context(ADA))]


async def test_no_context_means_no_tools(fake_servers):
    """ADK's anonymous paths (`adk web`) have no user to resolve servers for."""
    toolset = CustomMcpToolset(_registry(), _settings())
    assert await toolset.get_tools(None) == []


async def test_one_connection_is_reused_across_turns(fake_servers):
    registry = _registry()
    await registry.add(ADA, _spec("acme"))
    toolset = CustomMcpToolset(registry, _settings())

    await toolset.get_tools(_context(ADA, "inv-1"))
    await toolset.get_tools(_context(ADA, "inv-2"))

    assert len(fake_servers.built) == 1


async def test_changed_credentials_open_a_new_connection(fake_servers):
    """Reusing the old session would keep calling with the old token."""
    registry = _registry()
    await registry.add(ADA, _spec("acme", headers={"Authorization": "old"}))
    toolset = CustomMcpToolset(registry, _settings())
    await toolset.get_tools(_context(ADA, "inv-1"))

    await registry.add(ADA, _spec("acme", headers={"Authorization": "new"}))
    await toolset.get_tools(_context(ADA, "inv-2"))

    assert len(fake_servers.built) == 2


async def test_a_broken_server_does_not_cost_the_others(fake_servers):
    registry = _registry()
    await registry.add(ADA, _spec("broken"))
    await registry.add(ADA, _spec("acme"))
    fake_servers.broken.add("broken")
    toolset = CustomMcpToolset(registry, _settings())

    names = sorted(tool.name for tool in await toolset.get_tools(_context(ADA)))

    assert names == ["acme_fetch", "acme_search"]


async def test_a_broken_server_is_retried_next_turn(fake_servers):
    """Nothing is cached on failure, so recovery needs no intervention."""
    registry = _registry()
    await registry.add(ADA, _spec("acme"))
    fake_servers.broken.add("acme")
    toolset = CustomMcpToolset(registry, _settings())
    assert await toolset.get_tools(_context(ADA, "inv-1")) == []

    fake_servers.broken.clear()
    assert len(await toolset.get_tools(_context(ADA, "inv-2"))) == 2


async def test_close_shuts_every_connection_down(fake_servers):
    registry = _registry()
    await registry.add(ADA, _spec("acme"))
    toolset = CustomMcpToolset(registry, _settings())
    await toolset.get_tools(_context(ADA))

    await toolset.close()

    assert await toolset.get_tools(_context(ADA))  # reconnects on demand
    assert len(fake_servers.built) == 2


# --- the environment guard ---


def test_warns_when_client_certificates_could_leak_our_own_token(monkeypatch, caplog):
    monkeypatch.delenv(custom_mcp._CLIENT_CERT_ENV, raising=False)
    with caplog.at_level(logging.WARNING):
        custom_mcp._warn_if_client_certs_enabled()
    assert custom_mcp._CLIENT_CERT_ENV in caplog.text


def test_silent_when_client_certificates_are_off(monkeypatch, caplog):
    monkeypatch.setenv(custom_mcp._CLIENT_CERT_ENV, "false")
    with caplog.at_level(logging.WARNING):
        custom_mcp._warn_if_client_certs_enabled()
    assert caplog.text == ""
