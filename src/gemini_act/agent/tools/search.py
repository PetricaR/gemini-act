"""Google Search grounding — the model's own built-in web search.

Unlike every other tool group here, `GoogleSearchTool` is not a regular
function tool that ADK calls and gets a plain result back from: it is a
built-in Gemini capability that attaches `types.Tool(google_search=...)`
directly to the LLM request, and the model answers with grounded text. Gemini
does not allow that built-in tool to share a request with custom
function-declaration tools (Workspace MCP, business tools, custom MCP, ...),
so a raw `google_search` alongside anything else here would break at the
first turn that has more than one tool group.

ADK's documented workaround, switched on below via `bypass_multi_tools_limit`,
is to run `google_search` inside its own single-tool sub-agent and expose that
sub-agent as an ordinary callable tool (`google_search_agent`) instead: the
root agent calls it like any other tool, and the grounded request happens in
isolation. The cost is one extra LLM round trip whenever the agent decides to
search, and — on Vertex AI — grounded requests are billed separately from
ordinary model calls, which is why this is a toggle like the MCP servers
rather than always on.
"""

from __future__ import annotations

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.google_search_tool import GoogleSearchTool

from gemini_act.config import Settings


def build_search_tools(settings: Settings) -> list[BaseTool]:
    """The Google Search tool, or an empty list when disabled."""
    if not settings.web_search_enabled:
        return []
    return [GoogleSearchTool(bypass_multi_tools_limit=True)]
