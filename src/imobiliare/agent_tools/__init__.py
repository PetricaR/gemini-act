"""Suprafața pentru agentul ADK peste evaluarea din `imobiliare.mcp`.

A treia față a aceluiași nucleu, alături de `mcp/` (serverul MCP) și `api/`
(HTTP). Funcții simple, fără import de ADK: schema fiecărui tool e derivată de
ADK din semnătură, adnotări și docstring, deci toate trei sunt purtătoare de
sens — vezi `CLAUDE.md`, „Adding tools".

Dependența merge doar într-un sens, `agent_tools` → `mcp`, niciodată invers.
"""

from imobiliare.agent_tools.imobiliare import IMOBILIARE_TOOLS
from imobiliare.agent_tools.maps import MAPS_TOOLS

__all__ = ["IMOBILIARE_TOOLS", "MAPS_TOOLS"]
