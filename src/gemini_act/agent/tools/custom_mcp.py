"""Tools from the MCP servers each user connected for themselves.

The Workspace toolsets in `workspace_mcp.py` are a fixed list, known when the
process starts. These are the opposite: they differ per user and change while
the process is running — someone pastes a server into the chat and expects its
tools on their next message, with no redeploy and without affecting anyone else.

ADK makes that straightforward. It calls `get_tools()` once per LLM turn and
passes a `ReadonlyContext` carrying the calling user's id, so the lookup belongs
there rather than at agent construction, and one shared agent still serves
everyone. Live `McpToolset`s are cached by connection fingerprint, so a user's
second message reuses the first one's session, and two users who connected the
same server with the same credentials share it.

Each server's tools carry its own name as a prefix (`notion_search`), which
keeps two servers' `search` apart and tells the model — and the user reading the
reply — where a tool came from.

One ADK behaviour matters here in a way it does not for the Workspace servers.
`MCPSessionManager._get_mtls_transport` calls `google.auth.default` for every
HTTP connection and, if it manages to negotiate mTLS, installs a transport whose
`before_request` adds `Authorization: Bearer <the app's own ADC token>` for the
target host. Against Google's own endpoints that is the point of it. Against a
host someone pasted into a chat message it would hand a third party this
service's cloud-platform token. The whole path is skipped when
`GOOGLE_API_USE_CLIENT_CERTIFICATE=false`, which `deploy/deploy_cloud_run.sh`
sets — so that env var is a security control for this feature, not just noise
suppression, and `_warn_if_client_certs_enabled` says so out loud at startup if
it is ever dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections import OrderedDict

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.mcp_tool import (
    McpToolset,
    SseConnectionParams,
    StreamableHTTPConnectionParams,
)

from gemini_act.agent.tools.caching_toolset import CachingToolset
from gemini_act.config import Settings
from gemini_act.mcp.spec import McpServerSpec
from gemini_act.mcp.store import McpRegistry

logger = logging.getLogger(__name__)

# Live sessions are cheap but not free, and the number of distinct configs is
# bounded by what users paste. Evict the least recently used past this.
_MAX_LIVE_TOOLSETS = 64

_CLIENT_CERT_ENV = "GOOGLE_API_USE_CLIENT_CERTIFICATE"


def _warn_if_client_certs_enabled() -> None:
    """Flag the one environment setting this feature's safety depends on.

    See the module docstring: with client certificates enabled, ADK may attach
    this service's own Google credentials to requests aimed at whatever host a
    user pasted.
    """
    if os.environ.get(_CLIENT_CERT_ENV, "true").lower() != "false":
        logger.warning(
            "%s is not 'false' while user-connected MCP servers are enabled: ADK may "
            "attach this service's own Google credentials to a user-supplied host. "
            "Set %s=false (deploy/deploy_cloud_run.sh does).",
            _CLIENT_CERT_ENV,
            _CLIENT_CERT_ENV,
        )


def build_connection_params(
    spec: McpServerSpec, settings: Settings
) -> StreamableHTTPConnectionParams | SseConnectionParams:
    """Connection params for one server.

    Both transports get `mcp_timeout_seconds` rather than ADK's 5s default, for
    the same reason the Workspace servers do: a cold remote MCP server can take
    longer than that just to answer `list_tools`.
    """
    if spec.transport == "sse":
        return SseConnectionParams(
            url=spec.url,
            headers=dict(spec.headers) or None,
            timeout=settings.mcp_timeout_seconds,
        )
    return StreamableHTTPConnectionParams(
        url=spec.url,
        headers=dict(spec.headers) or None,
        timeout=settings.mcp_timeout_seconds,
    )


def build_toolset(spec: McpServerSpec, settings: Settings) -> McpToolset:
    return McpToolset(
        connection_params=build_connection_params(spec, settings),
        tool_name_prefix=spec.name,
    )


async def probe_server(spec: McpServerSpec, settings: Settings) -> list[str]:
    """Connect to a server and return its tool names, then disconnect.

    Used before saving a pasted server: a URL that does not speak MCP, or whose
    token is wrong, should fail once here — where the user is waiting and can be
    told why — instead of silently failing on every future turn.

    Raises whatever the connection raised, including `TimeoutError`.
    """
    toolset = build_toolset(spec, settings)
    try:
        tools = await asyncio.wait_for(toolset.get_tools(), timeout=settings.mcp_timeout_seconds)
        return [tool.name for tool in tools]
    finally:
        with contextlib.suppress(Exception):
            await toolset.close()


class CustomMcpToolset(BaseToolset):
    """Every tool from the calling user's own MCP servers.

    Carries no `tool_name_prefix` of its own: the per-server toolsets inside it
    each apply theirs, and a prefix here would stack on top of those.
    """

    def __init__(self, registry: McpRegistry, settings: Settings) -> None:
        super().__init__()
        self._registry = registry
        self._settings = settings
        self._toolsets: OrderedDict[str, CachingToolset] = OrderedDict()
        _warn_if_client_certs_enabled()

    async def get_tools(self, readonly_context: ReadonlyContext | None = None) -> list[BaseTool]:
        # No context means no user (ADK's anonymous paths, e.g. `adk web`), and
        # these servers only exist per user.
        if readonly_context is None or not readonly_context.user_id:
            return []

        specs = await self._registry.list(readonly_context.user_id)
        if not specs:
            return []

        tools: list[BaseTool] = []
        for spec in specs:
            toolset = await self._toolset_for(spec)
            try:
                # ...with_prefix, not get_tools: the prefix lives on the
                # per-server toolset, and this class has none to apply.
                tools.extend(await toolset.get_tools_with_prefix(readonly_context))
            except Exception:
                # One unreachable server must not cost the user their other
                # tools — or their whole turn. Nothing is cached on failure, so
                # the next turn tries again.
                logger.warning(
                    "Skipping MCP server %s (%s) for this turn",
                    spec.name,
                    spec.host,
                    exc_info=True,
                )
        return tools

    async def _toolset_for(self, spec: McpServerSpec) -> CachingToolset:
        cached = self._toolsets.get(spec.fingerprint)
        if cached is not None:
            self._toolsets.move_to_end(spec.fingerprint)
            return cached

        toolset = CachingToolset(
            build_toolset(spec, self._settings),
            cache_ttl_seconds=self._settings.mcp_cache_ttl_seconds,
        )
        self._toolsets[spec.fingerprint] = toolset
        logger.info("Connecting user MCP server %s (%s)", spec.name, spec.host)

        while len(self._toolsets) > _MAX_LIVE_TOOLSETS:
            _, evicted = self._toolsets.popitem(last=False)
            with contextlib.suppress(Exception):
                await evicted.close()
        return toolset

    async def close(self) -> None:
        while self._toolsets:
            _, toolset = self._toolsets.popitem()
            with contextlib.suppress(Exception):
                await toolset.close()
