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


# A Chat app built as a Google Workspace add-on receives a different payload
# from a classic Chat app, and must reply in a different envelope. Which one you
# get is fixed the first time the Chat API configuration is saved and cannot be
# changed afterwards, so both shapes are supported.
#
#   classic:  {"type": "MESSAGE", "message": {...}, "user": {...}, "space": {...}}
#   add-on:   {"chat": {"user": {...}, "messagePayload": {"message": ..., "space": ...}}}
#
# Add-on payloads are translated into the classic shape at the boundary, so
# everything downstream stays single-shaped.
_ADDON_PAYLOADS: dict[str, str] = {
    "appCommandPayload": "APP_COMMAND",
    "messagePayload": "MESSAGE",
    "addedToSpacePayload": "ADDED_TO_SPACE",
    "removedFromSpacePayload": "REMOVED_FROM_SPACE",
    "buttonClickedPayload": "CARD_CLICKED",
}


def normalize_event(event: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return (classic-shaped event, is_addon)."""
    chat = event.get("chat")
    if not isinstance(chat, dict):
        return event, False

    for key, event_type in _ADDON_PAYLOADS.items():
        payload = chat.get(key)
        if not isinstance(payload, dict):
            continue
        normalized: dict[str, Any] = {
            "type": event_type,
            "user": chat.get("user") or {},
            # The space hangs off the payload, but older shapes put it on the
            # chat object; prefer the payload and fall back.
            "space": payload.get("space") or chat.get("space") or {},
            "message": payload.get("message") or {},
        }
        if "appCommandMetadata" in payload:
            normalized["appCommandMetadata"] = payload["appCommandMetadata"]
        return normalized, True

    logger.warning("Add-on event carried no recognised payload: %s", sorted(chat))
    return {"type": "", "chat": chat}, True


def to_addon_response(body: dict[str, Any]) -> dict[str, Any]:
    """Wrap a classic Chat message body in the add-on response envelope.

    An empty body stays empty: that is the acknowledgement used when the real
    reply is posted asynchronously through the Chat API.
    """
    if not body:
        return {}
    return {"hostAppDataAction": {"chatDataAction": {"createMessageAction": {"message": body}}}}


@dataclass(frozen=True)
class ChatContext:
    """The parts of a Chat event the agent actually needs."""

    user_id: str
    display_name: str
    space: str
    space_type: str
    thread: str
    text: str
    command: str | None

    @property
    def is_dm(self) -> bool:
        return self.space_type == "DM"

    @property
    def thread_key(self) -> str | None:
        """A stable, app-chosen thread key for spaces where Chat mints a fresh
        thread per top-level message (DMs) — used instead of `thread` so the
        whole 1:1 conversation stays one continuous thread instead of a new
        collapsed bubble per exchange. `None` outside DMs, where each incoming
        `thread` is trusted as the topic the user actually replied in."""
        if self.is_dm:
            return f"dm-{self.space.rsplit('/', 1)[-1]}"
        return None

    @property
    def session_id(self) -> str:
        """Conversation memory is per thread, so the agent follows a discussion.

        DMs are the exception: since Chat can mint a fresh thread per message
        there (see `thread_key`), keying memory on it would silently reset the
        agent's memory on every message. Use the (stable) space instead.
        """
        source = self.space if self.is_dm else (self.thread or self.space)
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
        space_type=space.get("type", ""),
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
    event, is_addon = normalize_event(event)
    if is_addon:
        return to_addon_response(await _handle_normalized(event, schedule))
    return await _handle_normalized(event, schedule)


async def _handle_normalized(event: dict[str, Any], schedule) -> dict[str, Any]:
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
        if ctx.thread_key:
            await client.post_message(ctx.space, body, thread_key=ctx.thread_key)
        else:
            await client.post_message(ctx.space, body, thread_name=ctx.thread or None)
    except Exception:
        logger.exception("Could not post reply into %s", ctx.space)
