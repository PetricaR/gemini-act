"""Google Search grounding and URL reading — the model's own built-in web tools.

Unlike every other tool group here, `google_search` and `url_context` are not
regular function tools that ADK calls and gets a plain result back from: they
are built-in Gemini capabilities that attach `types.Tool(google_search=...)`
/ `types.Tool(url_context=...)` directly to the LLM request, and the model
answers with grounded text or with a page's content folded into its context.
`url_context` is what lets the agent read a specific page in full — a search
result, a URL the user pasted, docs — rather than reason from a search
snippet alone.

Gemini does not allow a built-in tool to share a request with custom
function-declaration tools (Workspace MCP, business tools, custom MCP, ...),
so either of these directly alongside anything else here would break at the
first turn that has more than one tool group. It does allow several built-in
tools to share a request with *each other*, though, so both are combined in
one single-purpose sub-agent and exposed to the root agent as one ordinary
callable tool (`google_search_agent`): the same pattern ADK applies
automatically for `google_search` alone via `bypass_multi_tools_limit`, done
by hand here because `url_context` has no such built-in shortcut (as of ADK
2.6.2 that flag exists only on `GoogleSearchTool` / `VertexAiSearchTool`).

The sub-agent keeps the name `google_search_agent` on purpose, even though it
now also reads URLs: ADK's own grounding-metadata propagation
(`base_llm_flow.py::_maybe_add_grounding_metadata`) looks for a tool with
that exact name to copy citations onto the root agent's reply, which is what
`runner.py::_format_citations` turns into the "Sources:" list. Renaming the
sub-agent would silently stop citations from showing up.

The cost is one extra LLM round trip whenever the agent decides to search or
read a page, and — on Vertex AI — grounded requests are billed separately
from ordinary model calls, which is why this is a toggle like the MCP
servers rather than always on.
"""

from __future__ import annotations

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.google_search_tool import google_search
from google.adk.tools.url_context_tool import url_context

from gemini_act.config import Settings

_INSTRUCTION = """\
You answer questions that need information from the open web, for another
agent that will call you as a tool.

Use `google_search` to find relevant pages. Use `url_context` to fetch and
read the full content of a specific URL — one you found via search, or one
the calling agent gave you directly — whenever a search snippet is not
enough. The two combine freely: search first, then read the most relevant
result in depth.

Answer in your own words and mention which pages you drew from.
"""


def build_search_tools(settings: Settings) -> list[BaseTool]:
    """A web-research tool (search plus reading a URL in full), or an empty
    list when disabled."""
    if not settings.web_search_enabled:
        return []
    agent = LlmAgent(
        name="google_search_agent",
        model=settings.model,
        description=(
            "Searches the web and can read the full content of a specific URL. "
            "Use for anything outside Workspace and the business tools: current "
            "events, public facts, or a page whose content is needed in depth, "
            "not just a search snippet."
        ),
        instruction=_INSTRUCTION,
        tools=[google_search, url_context],
    )
    return [AgentTool(agent=agent, propagate_grounding_metadata=True)]
