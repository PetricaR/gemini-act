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
from google.oauth2.credentials import Credentials
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

    @staticmethod
    def _build_user_service(access_token: str) -> Any:
        """A one-off service acting as the given user, not the app.

        Used only for deleting the user's *own* messages (/clean): the app's
        own `chat.bot` identity can delete its own messages, but Chat does not
        let an app delete messages a human sent — that requires the human's
        own OAuth token and the `chat.messages` scope.
        """
        credentials = Credentials(token=access_token)
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
        thread_key: str | None = None,
    ) -> dict[str, Any]:
        """Post an arbitrary message body (text and/or cards) into a space.

        With neither thread argument the message is a new top-level message in
        the space's main stream — the default for replies, see
        `chat/events.py::_post_reply`. `thread_name` targets an existing thread
        resource by name, keeping a reply attached to whatever thread its
        triggering message arrived in. `thread_key` is a caller-chosen stable
        string instead: Chat maps it to one thread and reuses it across calls,
        which holds a DM in a single continuous thread rather than fragmenting
        into a new one per exchange. Pass at most one; `thread_name` wins if
        both are given.
        """
        service = await self._get_service()
        payload = dict(body)
        kwargs: dict[str, Any] = {"parent": space, "body": payload}
        if thread_name:
            payload["thread"] = {"name": thread_name}
            # Without this, a message naming a thread starts a new one instead.
            kwargs["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
        elif thread_key:
            payload["thread"] = {"threadKey": thread_key}
            kwargs["messageReplyOption"] = "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

        def _execute() -> dict[str, Any]:
            return service.spaces().messages().create(**kwargs).execute()

        return await asyncio.to_thread(_execute)

    async def list_messages(self, space: str) -> list[dict[str, Any]]:
        """List every message in a space, across all pages.

        Uses the app's own identity: a Chat app that is a member of the space
        can read messages there, including the human's, even though it cannot
        delete anyone's but its own (see `delete_message`).
        """
        service = await self._get_service()
        messages: list[dict[str, Any]] = []
        page_token: str | None = None

        def _execute(token: str | None) -> dict[str, Any]:
            return (
                service.spaces()
                .messages()
                .list(parent=space, pageSize=100, pageToken=token)
                .execute()
            )

        while True:
            response = await asyncio.to_thread(_execute, page_token)
            messages.extend(response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return messages

    async def delete_message(self, name: str, *, access_token: str | None = None) -> None:
        """Delete a message.

        With app identity (the default), this only succeeds for a message the
        app itself sent. Pass `access_token` (the sender's own OAuth token) to
        delete a message a human sent instead — Chat requires the human's own
        credentials for that, not the app's.

        `force=True` also deletes any threaded replies, so this does not fail
        when called on a thread's root message out of order.
        """
        service = (
            await asyncio.to_thread(self._build_user_service, access_token)
            if access_token
            else await self._get_service()
        )

        def _execute() -> None:
            service.spaces().messages().delete(name=name, force=True).execute()

        await asyncio.to_thread(_execute)

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
