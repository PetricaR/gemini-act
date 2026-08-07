"""Google Chat message bodies (Cards v2)."""

from __future__ import annotations

from typing import Any

APP_TITLE = "Gemini Act"


def text_message(text: str) -> dict[str, Any]:
    return {"text": text}


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
                                "<b>Commands</b><br>"
                                "/auth — connect or reconnect your Google account<br>"
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


def error_card(message: str) -> dict[str, Any]:
    return _card(
        "error",
        subtitle="Something went wrong",
        sections=[{"widgets": [{"textParagraph": {"text": message}}]}],
    )
