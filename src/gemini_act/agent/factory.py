"""Assembly of the root agent."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from google.adk import Agent
from google.genai import types

from gemini_act.agent.prompts import build_instruction
from gemini_act.agent.tools import (
    BUSINESS_TOOLS,
    CHAT_TOOLS,
    CustomMcpToolset,
    build_search_tools,
    build_workspace_toolsets,
)
from gemini_act.config import Settings, get_settings
from gemini_act.mcp.store import McpRegistry
from gemini_act.oauth.store import TokenService

logger = logging.getLogger(__name__)


def build_generate_content_config(settings: Settings) -> types.GenerateContentConfig | None:
    """Model-level generation settings, or None to keep ADK's own defaults.

    Only thinking is pinned here — see `Settings.thinking_level` for why it is
    worth pinning at all. Everything else is deliberately left to ADK so this
    does not quietly diverge from the library's defaults.
    """
    if not settings.thinking_level:
        return None
    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel(settings.thinking_level)
        )
    )


def build_agent(
    settings: Settings | None = None,
    token_service: TokenService | None = None,
    mcp_registry: McpRegistry | None = None,
) -> Agent:
    """Build the root agent.

    Args:
        settings: Configuration; falls back to the process settings.
        token_service: Source of per-user Workspace access tokens. When None,
            the Workspace MCP toolsets are left out entirely — that is the
            anonymous mode used by `adk web`, where there is no Chat user to
            act as. Business and Chat tools still work.
        mcp_registry: Source of the servers each user connected themselves.
            When None, the toolset is left out — the agent then has only the
            tools this deployment ships with.
    """
    settings = settings or get_settings()
    tools: list[Any] = [*BUSINESS_TOOLS, *CHAT_TOOLS, *build_search_tools(settings)]
    tools.extend(build_workspace_toolsets(settings, token_service))
    if settings.custom_mcp_enabled and mcp_registry is not None:
        # Resolves per turn against the calling user, so this single toolset
        # covers every user's servers — see `CustomMcpToolset`.
        tools.append(CustomMcpToolset(mcp_registry, settings))

    logger.info(
        "Built agent on %s with %d tool group(s), thinking %s, workspace access %s",
        settings.model,
        len(tools),
        settings.thinking_level or "default",
        "on" if token_service else "off",
    )
    return Agent(
        name="gemini_act",
        model=settings.model,
        description="Takes actions in Google Workspace on behalf of a Google Chat user.",
        instruction=build_instruction,
        tools=tools,
        generate_content_config=build_generate_content_config(settings),
    )


@lru_cache
def get_agent() -> Agent:
    """The process-wide agent used to serve Chat traffic.

    A single instance is safe to share: per-user credentials are resolved at
    tool-call time by the MCP header provider, and ADK pools MCP sessions per
    resolved header set, so users never share an upstream session.
    """
    from gemini_act.mcp.store import get_mcp_registry
    from gemini_act.oauth.store import get_token_service

    return build_agent(get_settings(), get_token_service(), get_mcp_registry())
