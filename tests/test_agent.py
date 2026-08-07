"""Agent assembly, tool behaviour, and config validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gemini_act.agent.factory import build_agent
from gemini_act.agent.tools import business, workspace_mcp
from gemini_act.config import MCP_SCOPES, MCP_SERVERS, Settings


def _settings(**overrides) -> Settings:
    return Settings(**{"token_store": "memory", **overrides})


class FakeAgentRegistry:
    """Stands in for `AgentRegistry`: no ADC, no network.

    Real `AgentRegistry.__init__` calls `google.auth.default()` and
    `get_mcp_toolset()` makes a live call to agentregistry.googleapis.com to
    resolve each server's endpoint — neither is available in tests.
    """

    def __init__(self, *, project_id: str, location: str) -> None:
        self.project_id = project_id
        self.location = location

    def get_mcp_toolset(self, mcp_server_name: str):
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import (
            StreamableHTTPConnectionParams,
        )

        server_id = mcp_server_name.rsplit("/", 1)[-1]
        return McpToolset(
            connection_params=StreamableHTTPConnectionParams(
                url=f"https://example.invalid/{server_id}"
            ),
            tool_name_prefix=server_id,
        )


# --- configuration ---


def test_mcp_enabled_accepts_csv():
    assert _settings(mcp_enabled="gmail, drive").mcp_enabled == ("gmail", "drive")


def test_mcp_enabled_parses_from_environment(monkeypatch):
    """The env path differs from init kwargs: pydantic-settings would otherwise
    JSON-decode this field and blow up on plain CSV. Cloud Run sets it this way."""
    monkeypatch.setenv("GEMINI_ACT_MCP_ENABLED", "gmail,drive,calendar,chat,people")
    assert Settings(token_store="memory").mcp_enabled == (
        "gmail",
        "drive",
        "calendar",
        "chat",
        "people",
    )


def test_empty_mcp_enabled_from_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_ACT_MCP_ENABLED", "")
    assert Settings(token_store="memory").mcp_enabled == ()


def test_unknown_mcp_server_is_rejected_at_startup():
    with pytest.raises(ValidationError, match="Unknown MCP server"):
        _settings(mcp_enabled="gmail,teleportation")


def test_every_server_has_declared_scopes():
    assert set(MCP_SERVERS) == set(MCP_SCOPES)


def test_oauth_scopes_cover_enabled_servers_without_duplicates():
    scopes = _settings(mcp_enabled="gmail,drive,calendar").oauth_scopes
    assert len(scopes) == len(set(scopes)), "scopes must not repeat"
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
    assert "https://www.googleapis.com/auth/drive.readonly" in scopes


# --- agent assembly ---


def test_anonymous_agent_omits_workspace_toolsets():
    """`adk web` has no Chat user, so per-user MCP servers must be left out."""
    agent = build_agent(_settings(), token_service=None)
    assert len(agent.tools) == len(business.BUSINESS_TOOLS) + 3  # + chat tools


def test_agent_with_token_service_adds_one_toolset_per_enabled_server(token_service, monkeypatch):
    monkeypatch.setattr(workspace_mcp, "AgentRegistry", FakeAgentRegistry)
    settings = _settings(mcp_enabled="gmail,calendar")
    agent = build_agent(settings, token_service=token_service)
    base = len(business.BUSINESS_TOOLS) + 3
    assert len(agent.tools) == base + 2


def test_workspace_toolsets_are_empty_without_a_token_service():
    assert workspace_mcp.build_workspace_toolsets(_settings(), None) == []


async def test_header_provider_supplies_the_users_bearer_token(token_service, monkeypatch):
    async def fake_access_token(user_id):
        return f"token-for-{user_id}"

    monkeypatch.setattr(token_service, "get_access_token", fake_access_token)
    provider = workspace_mcp._make_header_provider(token_service)

    class Ctx:
        user_id = "users/123"

    headers = await provider(Ctx())
    assert headers["Authorization"] == "Bearer token-for-users/123"


async def test_header_provider_omits_authorization_when_user_has_no_token(token_service):
    provider = workspace_mcp._make_header_provider(token_service)

    class Ctx:
        user_id = "users/unknown"

    headers = await provider(Ctx())
    assert "Authorization" not in headers


async def test_different_users_get_different_headers(token_service, monkeypatch):
    """Header isolation is what keeps ADK's pooled MCP sessions per-user."""

    async def fake_access_token(user_id):
        return f"token-{user_id}"

    monkeypatch.setattr(token_service, "get_access_token", fake_access_token)
    provider = workspace_mcp._make_header_provider(token_service)

    class Ctx:
        def __init__(self, uid):
            self.user_id = uid

    a = await provider(Ctx("users/1"))
    b = await provider(Ctx("users/2"))
    assert a["Authorization"] != b["Authorization"]


# --- business tools ---


def test_current_time_returns_requested_zone():
    result = business.current_time("Europe/Bucharest")
    assert result["status"] == "success"
    assert result["timezone"] == "Europe/Bucharest"


def test_current_time_rejects_unknown_zone():
    result = business.current_time("Mars/Olympus_Mons")
    assert result["status"] == "error"
    assert "IANA" in result["error_message"]


async def test_reference_lookup_hit_and_miss():
    found = await business.lookup_reference_data("store", "1234")
    assert found["status"] == "success"
    assert found["record"]["city"] == "Bucharest"

    missing = await business.lookup_reference_data("store", "9999")
    assert missing["status"] == "error"


def test_summarize_numbers():
    result = business.summarize_numbers([1, 2, 3, 4], label="sales")
    assert result["status"] == "success"
    assert result["mean"] == 2.5
    assert result["total"] == 10
    assert result["label"] == "sales"


def test_summarize_numbers_rejects_empty_input():
    assert business.summarize_numbers([])["status"] == "error"


def test_every_business_tool_documents_itself():
    """ADK derives each tool's schema from its docstring, so it must exist."""
    for tool in business.BUSINESS_TOOLS:
        assert tool.__doc__, f"{tool.__name__} needs a docstring"
        assert "Returns:" in tool.__doc__, f"{tool.__name__} must document its return shape"


def test_mcp_toolsets_override_the_five_second_default(token_service, monkeypatch):
    """ADK defaults StreamableHTTP timeout to 5s; the Workspace MCP servers
    routinely take longer, which silently strips the agent of its tools.
    AgentRegistry.get_mcp_toolset() builds its own connection params with that
    same 5s default and does not expose a way to override it, so it must be
    raised after construction."""
    from google.adk.tools.mcp_tool.mcp_session_manager import (
        StreamableHTTPConnectionParams,
    )

    monkeypatch.setattr(workspace_mcp, "AgentRegistry", FakeAgentRegistry)
    settings = _settings(mcp_enabled="gmail,calendar", mcp_timeout_seconds=90.0)
    toolsets = workspace_mcp.build_workspace_toolsets(settings, token_service)

    assert toolsets, "expected toolsets to be built"
    for toolset in toolsets:
        params = toolset._inner._mcp_session_manager._connection_params
        assert isinstance(params, StreamableHTTPConnectionParams)
        assert params.timeout == 90.0
        assert params.timeout > StreamableHTTPConnectionParams(url="x").timeout


def test_prompt_forbids_inventing_causes_for_tool_failures():
    """The agent once told a user to fix account settings for an error whose
    real cause was Developer Preview enrolment — a fix that could not work."""
    from gemini_act.agent.prompts import SYSTEM_INSTRUCTION

    lowered = SYSTEM_INSTRUCTION.lower()
    assert "do not guess why" in lowered
    assert "verbatim" in lowered
    assert "i don't know why that failed" in lowered


def test_cloud_platform_scope_is_always_requested():
    """Workspace MCP calls need the IAM permission mcp.tools.call, which is only
    evaluated when the token carries cloud-platform. Without it every tool call
    fails with a misleading "caller does not have permission"."""
    scopes = _settings(mcp_enabled="gmail").oauth_scopes
    assert "https://www.googleapis.com/auth/cloud-platform" in scopes


def test_cloud_platform_requested_even_with_no_mcp_servers():
    assert "https://www.googleapis.com/auth/cloud-platform" in _settings(
        mcp_enabled=""
    ).oauth_scopes


def test_instruction_carries_todays_date():
    """The agent is built once per process, so the date must resolve per call
    or "today" silently drifts on a long-lived instance."""
    from datetime import UTC, datetime

    from gemini_act.agent.prompts import build_instruction

    text = build_instruction()
    assert datetime.now(UTC).strftime("%Y-%m-%d") in text
    assert "Gemini Act" in text


def test_agent_receives_instruction_as_a_callable():
    from gemini_act.agent.prompts import build_instruction

    agent = build_agent(_settings(), token_service=None)
    assert agent.instruction is build_instruction
