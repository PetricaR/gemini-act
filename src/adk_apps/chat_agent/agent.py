"""Entry point for `adk web` / `adk run` / `adk deploy`.

This runs the agent in *anonymous* mode: there is no Chat user, so no Workspace
access token, so the Workspace MCP toolsets are left out. Business and Chat
tools work as normal, which is what you want for iterating on prompts and tool
schemas in the dev UI.

The Chat webhook builds its own agent with a token service attached — see
`gemini_act.agent.factory.get_agent`.
"""

from gemini_act.agent.factory import build_agent

root_agent = build_agent(token_service=None)
