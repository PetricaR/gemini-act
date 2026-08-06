"""Assembly of the root agent."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from google.adk import Agent

from gemini_act.agent.prompts import build_instruction
from gemini_act.agent.tools import BUSINESS_TOOLS, CHAT_TOOLS, build_workspace_toolsets
from gemini_act.config import Settings, get_settings
from gemini_act.oauth.store import TokenService

logger = logging.getLogger(__name__)


def build_agent(
    settings: Settings | None = None,
    token_service: TokenService | None = None,
) -> Agent:
    """Build the root agent.

    Args:
        settings: Configuration; falls back to the process settings.
        token_service: Source of per-user Workspace access tokens. When None,
            the Workspace MCP toolsets are left out entirely — that is the
            anonymous mode used by `adk web`, where there is no Chat user to
            act as. Business and Chat tools still work.
    """
    settings = settings or get_settings()
    tools: list[Any] = [*BUSINESS_TOOLS, *CHAT_TOOLS]
    tools.extend(build_workspace_toolsets(settings, token_service))

    logger.info(
        "Built agent on %s with %d tool group(s), workspace access %s",
        settings.model,
        len(tools),
        "on" if token_service else "off",
    )
    return Agent(
        name="gemini_act",
        model=settings.model,
        description="Takes actions in Google Workspace on behalf of a Google Chat user.",
        instruction=build_instruction,
        tools=tools,
    )


@lru_cache
def get_agent() -> Agent:
    """The process-wide agent used to serve Chat traffic.

    A single instance is safe to share: per-user credentials are resolved at
    tool-call time by the MCP header provider, and ADK pools MCP sessions per
    resolved header set, so users never share an upstream session.
    """
    from gemini_act.oauth.store import get_token_service

    return build_agent(get_settings(), get_token_service())
