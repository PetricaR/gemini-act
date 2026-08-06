"""Google Workspace remote MCP servers, wired in as ADK toolsets.

These servers are three-legged OAuth: every call must carry the *end user's*
access token, not the app's. `McpToolset` supports a `header_provider` callback
that runs per invocation and receives a `ReadonlyContext`, so we resolve the
token there from `ctx.user_id` (which the runner sets to the Chat user id).

That keeps a single set of toolsets shared across users: ADK's MCP session
manager pools sessions keyed by a hash of the resolved headers, so each user's
token gets its own upstream session.
"""

from __future__ import annotations

import logging

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

from gemini_act.config import MCP_SERVERS, Settings
from gemini_act.oauth.store import TokenService

logger = logging.getLogger(__name__)

# MCP over Streamable HTTP negotiates between JSON and SSE responses.
_ACCEPT = "application/json, text/event-stream"


def _make_header_provider(server: str, token_service: TokenService):
    async def provide_headers(ctx: ReadonlyContext) -> dict[str, str]:
        access_token = await token_service.get_access_token(ctx.user_id)
        if not access_token:
            # Returning no Authorization makes the MCP server reject the call,
            # which the model surfaces as a tool error. The webhook checks for
            # credentials up front, so reaching here means they expired or were
            # revoked mid-conversation.
            logger.warning("No access token for %s calling %s MCP", ctx.user_id, server)
            return {"Accept": _ACCEPT}
        return {"Authorization": f"Bearer {access_token}", "Accept": _ACCEPT}

    return provide_headers


def build_workspace_toolsets(
    settings: Settings,
    token_service: TokenService | None,
) -> list[BaseToolset]:
    """One toolset per enabled Workspace MCP server.

    Returns an empty list when `token_service` is None (the anonymous case, e.g.
    `adk web`), because these servers cannot do anything useful without a user.
    """
    if token_service is None:
        return []

    toolsets: list[BaseToolset] = []
    for server in settings.mcp_enabled:
        url = MCP_SERVERS[server]
        toolsets.append(
            McpToolset(
                connection_params=StreamableHTTPConnectionParams(
                    url=url,
                    # ADK defaults this to 5s; these servers need far more.
                    timeout=settings.mcp_timeout_seconds,
                ),
                header_provider=_make_header_provider(server, token_service),
                # Namespace tool names so e.g. Gmail's and Chat's `search` do
                # not collide in the model's tool list.
                tool_name_prefix=server,
            )
        )
        logger.info("Enabled %s MCP toolset (%s)", server, url)
    return toolsets
