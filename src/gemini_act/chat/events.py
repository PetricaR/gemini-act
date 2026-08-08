"""Routing of Google Chat events to the agent."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from google.genai import types

from gemini_act.agent.tools import probe_server
from gemini_act.chat import cards
from gemini_act.chat.attachments import resolve_attachments
from gemini_act.chat.client import get_chat_client
from gemini_act.chat.live_reply import PLACEHOLDER, LiveReply
from gemini_act.config import get_settings
from gemini_act.mcp.spec import (
    McpServerSpec,
    McpSpecError,
    looks_like_mcp_config,
    parse_mcp_config,
)
from gemini_act.mcp.store import get_mcp_registry
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
    "5": "clean",
    "6": "mcp",
}

_MCP_USAGE = (
    "<b>/mcp</b> — list the servers you've connected<br>"
    "<b>/mcp add</b> &lt;url or JSON config&gt; — connect one<br>"
    "<b>/mcp remove</b> &lt;name&gt; — disconnect one<br><br>"
    "You can also just paste a server URL or config on its own and I'll connect it."
)

# Enough of a failure to be actionable, short enough for a card.
_MAX_ERROR_LENGTH = 300

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
    is_dm: bool
    thread: str
    text: str
    command: str | None
    # Raw `Attachment` dicts straight off the Chat payload — see
    # `chat/attachments.py` for turning these into content the model can read.
    attachments: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def thread_key(self) -> str | None:
        """A stable, app-chosen thread key for spaces where Chat mints a fresh
        thread per top-level message (DMs) — one continuous thread instead of a
        new one per exchange. `None` outside DMs, where each incoming `thread`
        is trusted as the topic the user actually replied in. Only consulted
        when `chat_reply_in_thread` is on; replies are flat by default."""
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

    # Google Chat has three overlapping signals for "this is a 1:1 with the
    # bot", spread across API versions and payload shapes: the deprecated
    # `type: "DM"`, its replacement `spaceType: "DIRECT_MESSAGE"`, and the
    # boolean `singleUserBotDm`. Which ones a given event actually populates
    # is not consistent (Workspace add-on payloads have been observed to omit
    # the legacy `type` entirely), so check all three instead of trusting one.
    raw_type = space.get("spaceType") or space.get("type") or ""
    is_dm = raw_type in {"DIRECT_MESSAGE", "DM"} or bool(space.get("singleUserBotDm"))

    return ChatContext(
        user_id=user.get("name", ""),
        display_name=user.get("displayName", ""),
        space=space.get("name", ""),
        space_type=raw_type,
        is_dm=is_dm,
        thread=thread.get("name", ""),
        text=text,
        command=_extract_command(event, message),
        attachments=tuple(message.get("attachment") or ()),
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
    # Cheap insurance against a repeat of the deprecated-`type`-field bug: if
    # DM detection is ever wrong again for some other payload shape, this line
    # says so immediately instead of needing a debug redeploy to find out.
    logger.info(
        "space=%s space_type=%s is_dm=%s thread=%s",
        ctx.space,
        ctx.space_type,
        ctx.is_dm,
        ctx.thread,
    )

    if ctx.command:
        return await _handle_command(ctx, schedule)

    has_attachments = get_settings().chat_attachments_enabled and bool(ctx.attachments)
    if not ctx.text and not has_attachments:
        return cards.text_message("Say something and I'll get to work.")

    return await _handle_message(ctx, schedule)


async def _handle_command(ctx: ChatContext, schedule) -> dict[str, Any]:
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

    if ctx.command == "clean":
        # Deleting every message can take a while for a long history, well
        # past Chat's ~30s synchronous budget — same reasoning as _handle_message.
        schedule(clean_conversation_and_reply, ctx)
        return {}

    if ctx.command == "mcp":
        return await _handle_mcp_command(ctx, schedule)

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


def _command_argument(ctx: ChatContext) -> str:
    """Whatever followed the slash command.

    Chat strips the command out of `argumentText` only for commands registered
    on the Chat API page. One that reached us through the text fallback in
    `_extract_command` still carries it, so strip it here for both cases.
    """
    text = ctx.text.strip()
    if ctx.command and text.lower().startswith(f"/{ctx.command}"):
        text = text[len(ctx.command) + 1 :]
    return text.strip()


async def _handle_mcp_command(ctx: ChatContext, schedule) -> dict[str, Any]:
    if not get_settings().custom_mcp_enabled:
        return cards.text_message("Connecting your own MCP servers is turned off here.")

    argument = _command_argument(ctx)
    # maxsplit=1: a pasted JSON config runs over several lines and must survive
    # intact as the remainder.
    parts = argument.split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""

    if action in {"list", "ls"}:
        return cards.mcp_list_card(await get_mcp_registry().list(ctx.user_id))

    if action in {"add", "connect"}:
        if not rest.strip():
            return cards.text_message(
                "Give me a server — for example `/mcp add https://mcp.example.com/mcp`."
            )
        # Connecting means a live round trip to someone else's server, which can
        # outlast Chat's ~30s synchronous budget.
        schedule(connect_mcp_and_reply, ctx, rest)
        return {}

    if action in {"remove", "rm", "delete", "disconnect"}:
        name = rest.strip()
        if not name:
            return cards.text_message("Which one? `/mcp remove <name>`.")
        if await get_mcp_registry().remove(ctx.user_id, name):
            return cards.text_message(f"Disconnected *{name}*. Its tools are gone from my list.")
        return cards.text_message(
            f"You don't have a server called *{name}*. Use /mcp to see what you have."
        )

    # `/mcp https://…` — the argument is the server itself, not a subcommand.
    if looks_like_mcp_config(argument):
        schedule(connect_mcp_and_reply, ctx, argument)
        return {}

    return cards.mcp_usage_card(_MCP_USAGE)


async def _handle_message(ctx: ChatContext, schedule) -> dict[str, Any]:
    settings = get_settings()

    # A pasted server is an instruction to us, not a question for the model —
    # and it is answered before the auth check below, because a custom server
    # carries its own credentials and needs no Google consent.
    if settings.custom_mcp_enabled and looks_like_mcp_config(ctx.text):
        schedule(connect_mcp_and_reply, ctx, ctx.text)
        return {}

    # Without credentials the Workspace tools cannot do anything, so ask first
    # rather than letting the agent run and fail mid-way.
    if settings.mcp_enabled:
        token = await get_token_service().get_token(ctx.user_id)
        if token is None:
            return cards.auth_card(start_url(ctx.user_id, ctx.space, settings))

    schedule(run_and_reply, ctx)
    # Empty body: acknowledge now, deliver the real answer asynchronously.
    return {}


def _thread_target(ctx: ChatContext) -> tuple[str | None, str | None]:
    """The `(thread_name, thread_key)` a reply should be posted with.

    Flat by default: the answer is a new top-level message, so question and
    answer sit next to each other in the main window like any messaging app.
    Attaching it to a thread instead (either the incoming one or a stable
    per-DM key) is what made Chat collapse every exchange into a "N replies"
    bubble that had to be expanded to be read — correct threading, wrong shape
    for a 1:1 assistant. `chat_reply_in_thread` turns that back on for spaces
    where parallel topics genuinely need separating.
    """
    if not get_settings().chat_reply_in_thread:
        return None, None
    # In a DM, Chat mints a fresh thread per top-level message, so the incoming
    # `thread` would fragment the conversation; the stable app-chosen key keeps
    # it as one. Named spaces are the opposite: the incoming thread *is* the
    # topic the user chose to ask in.
    thread_key = ctx.thread_key
    return (None if thread_key else (ctx.thread or None)), thread_key


def _live_reply(client, ctx: ChatContext, placeholder: str = PLACEHOLDER) -> LiveReply:
    settings = get_settings()
    thread_name, thread_key = _thread_target(ctx)
    return LiveReply(
        client,
        ctx.space,
        thread_name=thread_name,
        thread_key=thread_key,
        interval_seconds=settings.chat_stream_interval_seconds,
        placeholder=placeholder,
    )


async def _post_reply(client, ctx: ChatContext, body: dict[str, Any]) -> None:
    """Post a reply in one piece, for answers that are not written gradually."""
    await _live_reply(client, ctx).finish(body)


def _short_reason(exc: BaseException) -> str:
    """A failure the user can act on, without a stack trace in their chat."""
    detail = str(exc).strip() or exc.__class__.__name__
    # ADK re-wraps its own message, so the raw text arrives as "Failed to create
    # MCP session: Failed to create MCP session: <the actual cause>".
    clauses = detail.split(": ")
    detail = ": ".join(
        clause for index, clause in enumerate(clauses) if index == 0 or clause != clauses[index - 1]
    )
    if len(detail) > _MAX_ERROR_LENGTH:
        detail = f"{detail[:_MAX_ERROR_LENGTH]}…"
    return detail


async def connect_mcp_and_reply(ctx: ChatContext, text: str) -> None:
    """Connect the server(s) described by `text`, then report what happened.

    Each server is connected for real before it is saved. A URL that does not
    speak MCP, or a token that is wrong, then fails once — here, while the user
    is waiting and can be told why — instead of being stored and quietly
    breaking every later turn.
    """
    client = get_chat_client()
    settings = get_settings()
    registry = get_mcp_registry()

    try:
        specs = parse_mcp_config(text, allowed_hosts=settings.custom_mcp_allowed_hosts)
    except McpSpecError as exc:
        # Rejected before anything was attempted, so there is nothing to show
        # progress for — post the error straight away.
        await _post_reply(client, ctx, cards.error_card(str(exc)))
        return

    # Probing is a live round trip per server, up to `mcp_timeout_seconds` each,
    # so this is exactly the wait that used to be silent.
    reply = _live_reply(client, ctx, placeholder="🔌 Connecting…")
    if settings.chat_streaming_enabled:
        await reply.start()

    connected: list[tuple[McpServerSpec, list[str]]] = []
    failed: list[tuple[McpServerSpec, str]] = []

    for spec in specs:
        await reply.push(f"🔌 Connecting to *{spec.name}*…")
        try:
            tools = await probe_server(spec, settings)
        except TimeoutError:
            failed.append(
                (spec, f"it didn't answer within {settings.mcp_timeout_seconds:.0f} seconds")
            )
            continue
        except Exception as exc:
            logger.warning("MCP probe failed for %s (%s)", spec.name, spec.host, exc_info=True)
            failed.append((spec, _short_reason(exc)))
            continue

        if not tools:
            # Storing it would put a server in the user's list that can never
            # contribute anything, which reads as a silent failure later.
            failed.append((spec, "it connected but offers no tools"))
            continue

        try:
            await registry.add(ctx.user_id, spec)
        except McpSpecError as exc:
            failed.append((spec, str(exc)))
            continue

        logger.info("User %s connected MCP server %s (%s)", ctx.user_id, spec.name, spec.host)
        connected.append((spec, tools))

    await reply.finish(cards.mcp_result_card(connected, failed))


async def _resolve_attachments(ctx: ChatContext) -> list[types.Part]:
    """Parts to append to the user's turn: inline file data, plus a note for
    anything that could not be included. Empty (not an error) when the feature
    is off or the message carried no attachments."""
    settings = get_settings()
    if not settings.chat_attachments_enabled or not ctx.attachments:
        return []

    parts, notes = await resolve_attachments(
        list(ctx.attachments),
        user_id=ctx.user_id,
        chat_client=get_chat_client(),
        token_service=get_token_service(),
        settings=settings,
    )
    parts.extend(types.Part(text=f"[Attachment note] {note}") for note in notes)
    return parts


async def run_and_reply(ctx: ChatContext) -> None:
    """Run the agent and show its answer being written.

    A placeholder goes up immediately and is rewritten as the model produces
    text. When streaming is off — or the placeholder could not be posted — the
    run is unstreamed and the answer arrives in one piece at the end, which is
    what `LiveReply.finish` does with a reply that was never started.
    """
    client = get_chat_client()
    reply = _live_reply(client, ctx)
    if get_settings().chat_streaming_enabled:
        await reply.start()

    try:
        attachment_parts = await _resolve_attachments(ctx)
        answer = await run_agent(
            ctx.user_id,
            ctx.session_id,
            ctx.text,
            on_progress=reply.push if reply.is_live else None,
            attachments=attachment_parts,
        )
        body = cards.text_message(answer)
    except TimeoutError:
        logger.warning("Agent timed out for %s in %s", ctx.user_id, ctx.space)
        body = cards.error_card("That took too long and I stopped. Try narrowing the request.")
    except Exception:
        logger.exception("Agent run failed for %s in %s", ctx.user_id, ctx.space)
        body = cards.error_card(
            "I hit an unexpected error and couldn't finish. The details are in the logs."
        )

    await reply.finish(body)


async def clean_conversation_and_reply(ctx: ChatContext) -> None:
    """Delete every message in the conversation, then confirm.

    The app deletes its own messages with its own identity; a human's
    messages can only be deleted with that human's own OAuth token (Chat does
    not let an app delete messages it did not send), which is why this needs
    the `chat.messages` scope granted during /auth. Also resets the agent's
    memory, same as /reset, so a clean conversation starts with a clean slate
    on both sides.
    """
    client = get_chat_client()
    try:
        access_token = await get_token_service().get_access_token(ctx.user_id)
        messages = await client.list_messages(ctx.space)

        deleted = 0
        skipped_own = 0
        for message in messages:
            name = message.get("name")
            if not name:
                continue
            is_bot_message = (message.get("sender") or {}).get("type") == "BOT"
            try:
                if is_bot_message:
                    await client.delete_message(name)
                elif access_token:
                    await client.delete_message(name, access_token=access_token)
                else:
                    skipped_own += 1
                    continue
                deleted += 1
            except Exception:
                logger.warning("Could not delete message %s", name, exc_info=True)

        await reset_session(ctx.user_id, ctx.session_id)

        if skipped_own:
            settings = get_settings()
            body = cards.auth_card(
                start_url(ctx.user_id, ctx.space, settings),
                reason=(
                    f"Deleted {deleted} message(s) I sent. Reconnect your account "
                    f"(scope update) so I can delete the {skipped_own} you sent too."
                ),
            )
        else:
            body = cards.text_message(f"🧹 Deleted {deleted} message(s). Clean slate.")
    except Exception:
        logger.exception("Clean failed for %s in %s", ctx.user_id, ctx.space)
        body = cards.error_card("Couldn't clean the conversation. Details are in the logs.")

    await _post_reply(client, ctx, body)
