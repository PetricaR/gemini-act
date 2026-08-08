"""MCP servers a user connects for themselves, at runtime, from the chat."""

from gemini_act.mcp.spec import (
    McpServerSpec,
    McpSpecError,
    looks_like_mcp_config,
    parse_mcp_config,
)
from gemini_act.mcp.store import (
    InMemoryMcpServerStore,
    McpRegistry,
    build_mcp_server_store,
    get_mcp_registry,
)

__all__ = [
    "InMemoryMcpServerStore",
    "McpRegistry",
    "McpServerSpec",
    "McpSpecError",
    "build_mcp_server_store",
    "get_mcp_registry",
    "looks_like_mcp_config",
    "parse_mcp_config",
]
