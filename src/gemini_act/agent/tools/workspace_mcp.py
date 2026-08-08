"""Google Workspace MCP servers, resolved via Cloud Agent Registry.

These are Google's own first-party MCP servers (Gmail, Drive, Calendar, Chat,
People) — the same ones documented at
https://developers.google.com/workspace/guides/configure-mcp-servers — but
reached through Agent Registry (`AgentRegistry.get_mcp_toolset`) instead of
their direct public https://*mcp.googleapis.com/mcp/v1 URLs. The direct URLs
belong to the Workspace MCP Developer Preview Program, which is allowlist-gated
per GCP project; a project that is not enrolled gets a 403 on every call, no
matter how correct the OAuth setup is. Agent Registry exposes the same servers
under a broader entitlement and does not require that enrollment. See
`config.MCP_SERVERS` for the registered server ids.

These servers are three-legged OAuth: every call must carry the *end user's*
access token, not the app's. `header_provider` runs per invocation and receives
a `ReadonlyContext`, so we resolve the token there from `ctx.user_id` (which the
runner sets to the Chat user id).

That keeps a single set of toolsets shared across users: ADK's MCP session
manager pools sessions keyed by a hash of the resolved headers, so each user's
token gets its own upstream session.
"""

from __future__ import annotations

import logging

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.tools.base_toolset import BaseToolset

from gemini_act.agent.tools.caching_toolset import CachingToolset
from gemini_act.config import MCP_ENDPOINT_OVERRIDES, MCP_SERVERS, Settings
from gemini_act.oauth.store import TokenService

logger = logging.getLogger(__name__)


def _make_header_provider(token_service: TokenService):
    async def provide_headers(ctx: ReadonlyContext) -> dict[str, str]:
        access_token = await token_service.get_access_token(ctx.user_id)
        if not access_token:
            # Returning no Authorization makes the MCP server reject the call,
            # which the model surfaces as a tool error. The webhook checks for
            # credentials up front, so reaching here means they expired or were
            # revoked mid-conversation.
            logger.warning("No access token for %s calling Workspace MCP", ctx.user_id)
            return {}
        return {"Authorization": f"Bearer {access_token}"}

    return provide_headers


def build_workspace_toolsets(
    settings: Settings,
    token_service: TokenService | None,
    registry: AgentRegistry | None = None,
) -> list[BaseToolset]:
    """One toolset per enabled Workspace MCP server, via Agent Registry.

    Returns an empty list when `token_service` is None (the anonymous case, e.g.
    `adk web`), because these servers cannot do anything useful without a user.

    `registry` is normally left to default (a real `AgentRegistry`, which needs
    Google Cloud ADC and makes a live call per server to resolve its endpoint);
    tests inject a fake here instead of hitting the network.
    """
    if token_service is None:
        return []

    registry = registry or AgentRegistry(project_id=settings.project, location=settings.location)
    header_provider = _make_header_provider(token_service)

    toolsets: list[BaseToolset] = []
    for server in settings.mcp_enabled:
        server_id = MCP_SERVERS[server]
        resource_name = (
            f"projects/{settings.project}/locations/{settings.location}/mcpServers/{server_id}"
        )
        toolset = registry.get_mcp_toolset(resource_name)

        # get_mcp_toolset() builds its header provider as a plain sync function
        # that does `headers.update(self._header_provider(ctx))` with no await.
        # Ours is async (resolving a user's token is a Firestore/HTTP call), so
        # routed through there it would hand `.update()` an un-awaited
        # coroutine. `McpToolset._execute_with_session` does await awaitables,
        # so set our provider directly on the toolset instead.
        toolset._header_provider = header_provider
        # get_mcp_toolset() also always builds its connection params with ADK's
        # 5s default timeout and does not expose a way to override it; these
        # servers routinely take 15-25s, so raise it after construction.
        toolset._connection_params.timeout = settings.mcp_timeout_seconds

        # Same reason we reach into the connection params above: the URL comes
        # from the registry entry, and one of those entries is wrong. See
        # MCP_ENDPOINT_OVERRIDES for which, and why it is not inferable.
        override = MCP_ENDPOINT_OVERRIDES.get(server)
        if override and override != toolset._connection_params.url:
            logger.info(
                "Overriding %s MCP endpoint: registry says %s, using %s",
                server,
                toolset._connection_params.url,
                override,
            )
            toolset._connection_params.url = override
        # Keep our own short, predictable prefix (registry derives one from the
        # server's registered display name, which need not match `server`) so
        # e.g. Gmail's and Chat's `search` do not collide in the model's tool
        # list, and it stays stable regardless of how the server is labelled.
        toolset.tool_name_prefix = server

        toolsets.append(CachingToolset(toolset, cache_ttl_seconds=settings.mcp_cache_ttl_seconds))
        logger.info("Enabled %s MCP toolset via Agent Registry (%s)", server, resource_name)
    return toolsets
