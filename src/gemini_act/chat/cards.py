"""Google Chat message bodies (Cards v2)."""

from __future__ import annotations

from html import escape
from typing import Any

APP_TITLE = "Gemini Act"

# How many of a server's tool names to show before summarising the rest.
_TOOL_PREVIEW = 6


def text_message(text: str) -> dict[str, Any]:
    return {"text": text}


def a2ui_message(text: str, widgets: list[dict[str, Any]]) -> dict[str, Any]:
    """A reply with rich content the model asked for, alongside its spoken
    text — see `chat/a2ui.py`. No app header: unlike the cards below, this
    accompanies an ordinary conversational answer rather than standing in for
    one, and Chat already shows the app's own name and avatar on the message."""
    return {
        "text": text,
        "cardsV2": [{"cardId": "a2ui", "card": {"sections": [{"widgets": widgets}]}}],
    }


def _card(card_id: str, sections: list[dict[str, Any]], subtitle: str = "") -> dict[str, Any]:
    header: dict[str, Any] = {"title": APP_TITLE}
    if subtitle:
        header["subtitle"] = subtitle
    return {
        "cardsV2": [
            {
                "cardId": card_id,
                "card": {"header": header, "sections": sections},
            }
        ]
    }


def welcome_card() -> dict[str, Any]:
    return _card(
        "welcome",
        subtitle="Ready to act",
        sections=[
            {
                "widgets": [
                    {
                        "textParagraph": {
                            "text": (
                                "Hi — I can act in Google Workspace on your behalf: "
                                "search your mail, check your calendar, find files, and "
                                "run internal lookups.<br><br>"
                                "Connect your account with <b>/auth</b>, then just ask."
                            )
                        }
                    },
                    {
                        "textParagraph": {
                            "text": (
                                "You can also paste an MCP server's URL or config and I'll "
                                "connect it for you — its tools become yours from the next "
                                "message."
                            )
                        }
                    },
                    {
                        "textParagraph": {
                            "text": (
                                "<b>Commands</b><br>"
                                "/auth — connect or reconnect your Google account<br>"
                                "/mcp — list, add or remove your MCP servers<br>"
                                "/reset — forget this thread's conversation<br>"
                                "/clean — delete every message in this conversation<br>"
                                "/whoami — show which account I'm using<br>"
                                "/help — show this message"
                            )
                        }
                    },
                ]
            }
        ],
    )


def auth_card(auth_url: str, reason: str = "") -> dict[str, Any]:
    lead = reason or (
        "Before I can act on your behalf I need permission to reach your Google Workspace data."
    )
    return _card(
        "auth",
        subtitle="Authorization needed",
        sections=[
            {
                "widgets": [
                    {"textParagraph": {"text": lead}},
                    {
                        "buttonList": {
                            "buttons": [
                                {
                                    "text": "Connect Google account",
                                    "onClick": {"openLink": {"url": auth_url}},
                                }
                            ]
                        }
                    },
                ]
            }
        ],
    )


def mcp_result_card(
    connected: list[tuple[Any, list[str]]],
    failed: list[tuple[Any, str]],
) -> dict[str, Any]:
    """The outcome of connecting one or more pasted MCP servers.

    Both lists hold `(McpServerSpec, ...)` pairs — a whole config can be pasted
    at once, and some of its servers can work while others do not, so this
    reports per server rather than one verdict for the batch.
    """
    widgets: list[dict[str, Any]] = []

    for spec, tools in connected:
        preview = ", ".join(tools[:_TOOL_PREVIEW])
        if len(tools) > _TOOL_PREVIEW:
            preview += f", +{len(tools) - _TOOL_PREVIEW} more"
        widgets.append(
            {
                "textParagraph": {
                    "text": (
                        f"✅ <b>{escape(spec.name)}</b> connected — {len(tools)} tool(s) "
                        f"from {escape(spec.host)}.<br>{escape(preview)}"
                    )
                }
            }
        )

    for spec, reason in failed:
        widgets.append(
            {
                "textParagraph": {
                    "text": (
                        f"⚠️ Couldn't connect <b>{escape(spec.name)}</b> "
                        f"({escape(spec.host)}): {escape(reason)}"
                    )
                }
            }
        )

    if connected:
        widgets.append(
            {
                "textParagraph": {
                    "text": (
                        "Tools are named after the server, so you'll see "
                        f"<b>{escape(connected[0][0].name)}_…</b> in my replies. They're live "
                        "from your next message — /mcp to review, /mcp remove &lt;name&gt; to "
                        "disconnect."
                    )
                }
            }
        )

    subtitle = "MCP server connected" if connected else "MCP server not connected"
    return _card("mcp", [{"widgets": widgets}], subtitle)


def mcp_list_card(servers: list[Any]) -> dict[str, Any]:
    """The user's connected servers, or how to add one when there are none."""
    if not servers:
        return _card(
            "mcp",
            subtitle="No MCP servers connected",
            sections=[
                {
                    "widgets": [
                        {
                            "textParagraph": {
                                "text": (
                                    "You haven't connected any MCP servers yet. Paste a server "
                                    "URL — or the JSON config a vendor gives you — and I'll "
                                    "connect it.<br><br>"
                                    "<b>/mcp add</b> https://mcp.example.com/mcp<br>"
                                    "<b>/mcp remove</b> &lt;name&gt;"
                                )
                            }
                        }
                    ]
                }
            ],
        )

    lines = "<br>".join(
        f"<b>{escape(spec.name)}</b> — {escape(spec.url)}"
        + (f" ({escape(spec.transport)})" if spec.transport != "http" else "")
        for spec in servers
    )
    return _card(
        "mcp",
        subtitle=f"{len(servers)} MCP server(s) connected",
        sections=[
            {
                "widgets": [
                    {"textParagraph": {"text": lines}},
                    {
                        "textParagraph": {
                            "text": "Disconnect one with <b>/mcp remove</b> &lt;name&gt;."
                        }
                    },
                ]
            }
        ],
    )


def mcp_usage_card(usage_html: str) -> dict[str, Any]:
    """What /mcp accepts, shown when the subcommand wasn't recognised."""
    return _card(
        "mcp",
        subtitle="Your MCP servers",
        sections=[{"widgets": [{"textParagraph": {"text": usage_html}}]}],
    )


def error_card(message: str) -> dict[str, Any]:
    return _card(
        "error",
        subtitle="Something went wrong",
        sections=[{"widgets": [{"textParagraph": {"text": message}}]}],
    )
