"""Entry point for talking to the agent out loud: `adk web agents`, then the
microphone.

Same agent as `chat_agent` — same tools, same instruction — on a Live model
instead of a request/response one, so ADK can hold an audio session open in
both directions (`Runner.run_live`). See `gemini_act.config.Settings.live_model`
for what that model is and which backend serves it.

Anonymous, exactly like `chat_agent`: there is no Chat user behind `adk web`,
so no Workspace OAuth token and no Gmail/Drive/Calendar tools. Business, Chat
and web-research tools all work.
"""

from gemini_act.agent.factory import build_agent

root_agent = build_agent(token_service=None, live=True)
