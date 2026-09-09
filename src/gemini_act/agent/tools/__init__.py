"""Tool collections available to the agent."""

from gemini_act.agent.tools.business import BUSINESS_TOOLS
from gemini_act.agent.tools.chat_tools import CHAT_TOOLS
from gemini_act.agent.tools.custom_mcp import CustomMcpToolset, probe_server
from gemini_act.agent.tools.imobiliare import IMOBILIARE_TOOLS
from gemini_act.agent.tools.maps import MAPS_TOOLS
from gemini_act.agent.tools.search import build_search_tools
from gemini_act.agent.tools.workspace_mcp import build_workspace_toolsets

__all__ = [
    "BUSINESS_TOOLS",
    "CHAT_TOOLS",
    "CustomMcpToolset",
    "IMOBILIARE_TOOLS",
    "MAPS_TOOLS",
    "build_search_tools",
    "build_workspace_toolsets",
    "probe_server",
]
