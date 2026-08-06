"""Google Chat API client, authenticated as the app itself.

Used to post the agent's answer after the webhook has already returned. Chat
gives a synchronous response about 30 seconds; an agent loop with tool calls
routinely exceeds that, so the real reply is delivered asynchronously here.

Auth is Application Default Credentials scoped to `chat.bot` — on Cloud Run
that is the runtime service account, with no key file involved.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

import google.auth
from googleapiclient.discovery import build

from gemini_act.config import CHAT_BOT_SCOPE

logger = logging.getLogger(__name__)


class ChatClient:
    """Thin async wrapper over the (synchronous) Chat API client."""

    def __init__(self) -> None:
        self._service: Any | None = None
        self._lock = asyncio.Lock()

    async def _get_service(self) -> Any:
        if self._service is None:
            async with self._lock:
                if self._service is None:
                    self._service = await asyncio.to_thread(self._build_service)
        return self._service

    @staticmethod
    def _build_service() -> Any:
        credentials, _ = google.auth.default(scopes=[CHAT_BOT_SCOPE])
        return build("chat", "v1", credentials=credentials, cache_discovery=False)

    async def post_text(
        self,
        space: str,
        text: str,
        thread_name: str | None = None,
    ) -> dict[str, Any]:
        """Post a plain-text message, optionally into an existing thread."""
        return await self.post_message(space, {"text": text}, thread_name=thread_name)

    async def post_message(
        self,
        space: str,
        body: dict[str, Any],
        thread_name: str | None = None,
    ) -> dict[str, Any]:
        """Post an arbitrary message body (text and/or cards) into a space."""
        service = await self._get_service()
        payload = dict(body)
        kwargs: dict[str, Any] = {"parent": space, "body": payload}
        if thread_name:
            payload["thread"] = {"name": thread_name}
            # Without this, a message naming a thread starts a new one instead.
            kwargs["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

        def _execute() -> dict[str, Any]:
            return service.spaces().messages().create(**kwargs).execute()

        return await asyncio.to_thread(_execute)

    async def list_members(self, space: str) -> list[dict[str, Any]]:
        service = await self._get_service()

        def _execute() -> list[dict[str, Any]]:
            response = service.spaces().members().list(parent=space, pageSize=100).execute()
            return response.get("memberships", [])

        return await asyncio.to_thread(_execute)

    async def list_spaces(self) -> list[dict[str, Any]]:
        service = await self._get_service()

        def _execute() -> list[dict[str, Any]]:
            return service.spaces().list(pageSize=100).execute().get("spaces", [])

        return await asyncio.to_thread(_execute)


@lru_cache
def get_chat_client() -> ChatClient:
    return ChatClient()
