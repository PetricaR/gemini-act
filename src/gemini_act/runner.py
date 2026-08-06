"""ADK Runner wiring: one agent turn, from Chat text to reply text."""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService
from google.genai import types

from gemini_act.agent.factory import get_agent
from gemini_act.config import get_settings

logger = logging.getLogger(__name__)

APP_NAME = "gemini_act"


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


async def run_agent(user_id: str, session_id: str, message: str) -> str:
    """Run one turn and return the agent's final text.

    Raises:
        TimeoutError: if the turn exceeds the configured budget.
    """
    settings = get_settings()
    runner = get_runner()
    content = types.Content(role="user", parts=[types.Part(text=message)])

    async def _run() -> str:
        final = ""
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(part.text or "" for part in event.content.parts)
                if text.strip():
                    final = text
        return final

    result = await asyncio.wait_for(_run(), timeout=settings.agent_timeout_seconds)
    return result.strip() or "I finished, but produced no text to show."
