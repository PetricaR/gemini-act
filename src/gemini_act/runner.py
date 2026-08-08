"""ADK Runner wiring: one agent turn, from Chat text to reply text."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.events.event import Event
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService
from google.genai import types

from gemini_act.agent.factory import get_agent
from gemini_act.config import get_settings

logger = logging.getLogger(__name__)

APP_NAME = "gemini_act"

# Called with the answer as it accumulates, so a caller can show it being
# written. Receives the whole text each time, not a delta.
ProgressCallback = Callable[[str], Awaitable[None]]


@lru_cache
def get_session_service() -> BaseSessionService:
    settings = get_settings()
    if settings.session_db_url:
        from google.adk.sessions import DatabaseSessionService

        logger.info("Using database session service")
        return DatabaseSessionService(db_url=settings.session_db_url)
    logger.info("Using in-memory session service (sessions reset on restart)")
    return InMemorySessionService()


@lru_cache
def get_runner() -> Runner:
    return Runner(
        app_name=APP_NAME,
        agent=get_agent(),
        session_service=get_session_service(),
        auto_create_session=True,
    )


async def reset_session(user_id: str, session_id: str) -> None:
    """Drop a thread's conversation memory (used by /reset)."""
    service = get_session_service()
    try:
        await service.delete_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    except Exception:
        logger.debug("No session to reset for %s/%s", user_id, session_id, exc_info=True)


def _event_text(event: Event) -> str:
    """The user-facing text of an event, with the model's reasoning left out.

    A part flagged `thought` is the model thinking aloud, not an answer. Nothing
    here asks for thought summaries, so in practice none arrive — but the text
    this returns is posted straight into a Chat space, and "the model was not
    supposed to send that" is a poor reason to have forwarded it.
    """
    if not event.content or not event.content.parts:
        return ""
    return "".join(part.text or "" for part in event.content.parts if not part.thought)


# How many sources to list. Grounding can return more chunks than are worth
# showing in a chat reply — this keeps it a source list, not a bibliography.
MAX_CITATIONS = 5


def _format_citations(grounding_metadata: types.GroundingMetadata | None) -> str:
    """Render Google Search grounding sources as text Chat can link.

    Grounding with Google Search requires showing where a grounded answer came
    from. `grounding_metadata.search_entry_point.rendered_content` is the HTML
    widget Google's own docs point to for that, but it is meant for a web page
    or app webview — Chat's plain-text messages cannot render it. This instead
    turns each source in `grounding_chunks` into Chat's own link syntax
    (`<url|title>`, see developers.google.com/workspace/chat/format-messages),
    which achieves the same thing within what a Chat message can show.
    """
    if not grounding_metadata or not grounding_metadata.grounding_chunks:
        return ""
    seen: set[str] = set()
    lines: list[str] = []
    for chunk in grounding_metadata.grounding_chunks:
        web = chunk.web
        if not web or not web.uri or web.uri in seen:
            continue
        seen.add(web.uri)
        lines.append(f"- <{web.uri}|{web.title or web.uri}>")
        if len(lines) == MAX_CITATIONS:
            break
    if not lines:
        return ""
    return "\n\nSources:\n" + "\n".join(lines)


async def run_agent(
    user_id: str,
    session_id: str,
    message: str,
    on_progress: ProgressCallback | None = None,
    attachments: list[types.Part] | None = None,
) -> str:
    """Run one turn and return the agent's final text.

    Args:
        on_progress: Called with the text written so far as it arrives. Passing
            it switches the run to SSE streaming; without it the turn runs
            unstreamed and the caller only sees the finished answer. The
            callback is awaited inline, so it must be cheap or throttled — the
            model's output is not consumed while it runs (`LiveReply.push`
            throttles for exactly this reason).
        attachments: Extra parts appended after the text, e.g. inline file data
            resolved by `chat/attachments.py`, or a note about one that could
            not be included. `message` may be empty when a Chat message was
            attachment-only; the two together must still add up to a
            non-empty turn.

    Raises:
        TimeoutError: if the turn exceeds the configured budget.
    """
    settings = get_settings()
    runner = get_runner()
    parts: list[types.Part] = [types.Part(text=message)] if message else []
    parts.extend(attachments or [])
    content = types.Content(role="user", parts=parts or [types.Part(text="")])
    run_config = RunConfig(streaming_mode=StreamingMode.SSE if on_progress else StreamingMode.NONE)

    async def _run() -> str:
        final = ""
        # Partial events carry deltas; the aggregated event that closes a
        # streamed response then repeats the whole thing, so the buffer is only
        # ever read while streaming and reset once the complete text arrives.
        streamed = ""
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
            run_config=run_config,
        ):
            text = _event_text(event)
            if event.partial:
                if text and on_progress:
                    streamed += text
                    await on_progress(streamed)
                continue
            if event.is_final_response() and text.strip():
                # A turn that calls tools produces several of these — a remark
                # before the tool call, then the real answer. The last one wins,
                # but each is shown as it lands so the wait is not silent.
                final = text + _format_citations(event.grounding_metadata)
                streamed = ""
                if on_progress:
                    await on_progress(final)
        return final

    result = await asyncio.wait_for(_run(), timeout=settings.agent_timeout_seconds)
    return result.strip() or "I finished, but produced no text to show."
