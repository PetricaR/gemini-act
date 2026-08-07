"""Smoke-test the Agent Registry MCP wiring without deploying or going through
Google Chat's OAuth flow.

`adk web` (agents/chat_agent/agent.py) runs in anonymous mode on purpose — no
Chat user means no per-user Workspace token, so it always skips gmail, drive,
calendar and people, not just the one you're missing. That is expected and
tells you nothing about whether Agent Registry resolution actually works.

This script builds the same toolsets `build_workspace_toolsets` builds for a
real Chat user, but authenticates as *you* (your own `gcloud`/ADC user
credentials) instead of a Chat user's OAuth token, and calls `get_tools()` on
each one. A failure here points at Agent Registry / IAM (endpoint not found,
no permission to call agentregistry.googleapis.com); a failure only when
deployed and driven from Chat points at the per-user OAuth flow instead — this
script does not exercise that part.

Usage:
    .venv/bin/python scripts/check_workspace_mcp.py [server ...]

With no arguments, checks every server in Settings.mcp_enabled. Requires
`gcloud auth application-default login` to have been run, or another source of
Application Default Credentials.
"""

from __future__ import annotations

import asyncio
import sys

import google.auth
import google.auth.transport.requests

from gemini_act.agent.tools import workspace_mcp
from gemini_act.config import MCP_SERVERS, get_settings


class Ctx:
    user_id = "workspace-mcp-smoke-test"


class ADCTokenService:
    """Stands in for the real per-user TokenService, handing back the
    *developer's* own ADC token instead of a Chat user's. Enough to prove Agent
    Registry resolution and a live tools/list round trip; a 403 from a specific
    server after this succeeds is an OAuth scope/consent problem, not an Agent
    Registry one — your gcloud user likely lacks the Workspace scopes a real
    Chat user would have granted.
    """

    def __init__(self) -> None:
        self._credentials, _ = google.auth.default()

    async def get_access_token(self, user_id: str) -> str | None:
        self._credentials.refresh(google.auth.transport.requests.Request())
        return self._credentials.token


async def main() -> None:
    requested = sys.argv[1:] or list(get_settings().mcp_enabled)
    unknown = sorted(set(requested) - MCP_SERVERS.keys())
    if unknown:
        raise SystemExit(
            f"Unknown server(s): {', '.join(unknown)}. Known: {', '.join(sorted(MCP_SERVERS))}"
        )

    settings = get_settings().model_copy(update={"mcp_enabled": tuple(requested)})
    toolsets = workspace_mcp.build_workspace_toolsets(settings, ADCTokenService())

    for server, toolset in zip(requested, toolsets, strict=True):
        print(f"--- {server} ({MCP_SERVERS[server]}) ---")
        try:
            tools = await toolset.get_tools(Ctx())
        except Exception as exc:  # noqa: BLE001 — this is a diagnostic script
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            continue
        print(f"  {len(tools)} tool(s):")
        for tool in tools[:10]:
            print(f"    - {tool.name}")
        if len(tools) > 10:
            print(f"    ... and {len(tools) - 10} more")


if __name__ == "__main__":
    asyncio.run(main())
