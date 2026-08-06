"""Routing of Google Chat events to the agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from gemini_act.chat import cards
from gemini_act.chat.client import get_chat_client
from gemini_act.config import get_settings
from gemini_act.oauth.routes import start_url
from gemini_act.oauth.store import get_token_service
from gemini_act.runner import reset_session, run_agent

logger = logging.getLogger(__name__)

# Slash command ids as configured on the Chat API page. Keep in sync with the
# README's setup table; the text fallback below covers a mismatch.
SLASH_COMMANDS: dict[str, str] = {
    "1": "help",
    "2": "auth",
    "3": "reset",
    "4": "whoami",
}

KNOWN_COMMANDS = frozenset(SLASH_COMMANDS.values())


@dataclass(frozen=True)
class ChatContext:
    """The parts of a Chat event the agent actually needs."""

    user_id: str
    display_name: str
    space: str
    thread: str
    text: str
    command: str | None

    @property
    def session_id(self) -> str:
        """Conversation memory is per thread, so the agent follows a discussion."""
        source = self.thread or self.space
        return source.replace("/", "_") or "unknown"


def parse_event(event: dict[str, Any]) -> ChatContext:
    message = event.get("message") or {}
    user = event.get("user") or message.get("sender") or {}
    space = event.get("space") or message.get("space") or {}
    thread = message.get("thread") or {}

    # argumentText has the app mention and slash command stripped out; fall back
    # to the raw text for events that do not provide it.
    text = (message.get("argumentText") or message.get("text") or "").strip()

    return ChatContext(
        user_id=user.get("name", ""),
        display_name=user.get("displayName", ""),
        space=space.get("name", ""),
        thread=thread.get("name", ""),
        text=text,
        command=_extract_command(event, message),
    )


def _extract_command(event: dict[str, Any], message: dict[str, Any]) -> str | None:
    """Identify a slash command by id, falling back to the literal text."""
    metadata = event.get("appCommandMetadata") or {}
    command_id = str(metadata.get("appCommandId") or "")
    if not command_id:
        command_id = str((message.get("slashCommand") or {}).get("commandId") or "")
    if command_id and command_id in SLASH_COMMANDS:
        return SLASH_COMMANDS[command_id]

    raw = (message.get("text") or "").strip()
    if raw.startswith("/"):
        candidate = raw[1:].split(maxsplit=1)[0].lower()
        if candidate in KNOWN_COMMANDS:
            return candidate
    return None


async def handle_event(event: dict[str, Any], schedule) -> dict[str, Any]:
    """Produce the synchronous reply, scheduling slow work via `schedule`.

    `schedule(coro_fn, *args)` runs after the response is sent — Chat allows
    roughly 30 seconds synchronously, which an agent turn can exceed.
    """
    event_type = event.get("type") or ""

    if event_type in {"ADDED_TO_SPACE", "APP_ADDED_TO_SPACE"}:
        return cards.welcome_card()

    if event_type in {"REMOVED_FROM_SPACE", "APP_REMOVED_FROM_SPACE"}:
        return {}

    if event_type not in {"MESSAGE", "APP_COMMAND"}:
        logger.info("Ignoring unhandled event type %s", event_type)
        return {}

    ctx = parse_event(event)
    if not ctx.user_id or not ctx.space:
        logger.warning("Event missing user or space; ignoring")
        return {}

    if ctx.command:
        return await _handle_command(ctx)

    if not ctx.text:
        return cards.text_message("Say something and I'll get to work.")

    return await _handle_message(ctx, schedule)


async def _handle_command(ctx: ChatContext) -> dict[str, Any]:
    settings = get_settings()

    if ctx.command == "help":
        return cards.welcome_card()

    if ctx.command == "auth":
        return cards.auth_card(
            start_url(ctx.user_id, ctx.space, settings),
            reason="Connect your Google account so I can act on your behalf.",
        )

    if ctx.command == "reset":
        await reset_session(ctx.user_id, ctx.session_id)
        return cards.text_message("🧹 Forgotten. This thread starts fresh.")

    if ctx.command == "whoami":
        token = await get_token_service().get_token(ctx.user_id)
        if token is None:
            return cards.auth_card(
                start_url(ctx.user_id, ctx.space, settings),
                reason="You haven't connected an account yet.",
            )
        scopes = len(token.scopes)
        return cards.text_message(
            f"I'm acting as *{token.email or ctx.user_id}* with {scopes} granted scope(s)."
        )

    return cards.text_message(f"I don't know the command /{ctx.command}.")


async def _handle_message(ctx: ChatContext, schedule) -> dict[str, Any]:
    settings = get_settings()

    # Without credentials the Workspace tools cannot do anything, so ask first
    # rather than letting the agent run and fail mid-way.
    if settings.mcp_enabled:
        token = await get_token_service().get_token(ctx.user_id)
        if token is None:
            return cards.auth_card(start_url(ctx.user_id, ctx.space, settings))

    schedule(run_and_reply, ctx)
    # Empty body: acknowledge now, deliver the real answer asynchronously.
    return {}


async def run_and_reply(ctx: ChatContext) -> None:
    """Run the agent, then post its answer back into the thread."""
    client = get_chat_client()
    try:
        answer = await run_agent(ctx.user_id, ctx.session_id, ctx.text)
        body = cards.text_message(answer)
    except TimeoutError:
        logger.warning("Agent timed out for %s in %s", ctx.user_id, ctx.space)
        body = cards.error_card("That took too long and I stopped. Try narrowing the request.")
    except Exception:
        logger.exception("Agent run failed for %s in %s", ctx.user_id, ctx.space)
        body = cards.error_card(
            "I hit an unexpected error and couldn't finish. The details are in the logs."
        )

    try:
        await client.post_message(ctx.space, body, thread_name=ctx.thread or None)
    except Exception:
        logger.exception("Could not post reply into %s", ctx.space)
