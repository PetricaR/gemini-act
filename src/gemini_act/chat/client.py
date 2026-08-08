"""Google Chat API client, authenticated as the app itself.

Used to post the agent's answer after the webhook has already returned. Chat
gives a synchronous response about 30 seconds; an agent loop with tool calls
routinely exceeds that, so the real reply is delivered asynchronously here.

Auth is Application Default Credentials scoped to `chat.bot` — on Cloud Run
that is the runtime service account, with no key file involved.

Every call runs on a worker thread, and several can be in flight at once: one
instance serves many spaces, and a streamed reply rewrites its message every
couple of seconds for as long as the model is writing. `googleapiclient` is
built on `httplib2`, whose `Http` object is explicitly not thread-safe — sharing
the service's own would let two concurrent calls interleave on one connection.
So the service object (which is only metadata, and safe to share) is built once
and each request is given a fresh transport of its own; see `_new_http`.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

import google.auth
import google_auth_httplib2
import httplib2
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from gemini_act.config import CHAT_BOT_SCOPE

logger = logging.getLogger(__name__)

# Message body field -> the path naming it in `spaces.messages.patch`'s
# updateMask. The two differ: the body is JSON (`cardsV2`) while the mask names
# proto fields (`cards_v2`), per the Chat v1 discovery document, which also
# fixes the set of patchable fields — anything absent here cannot be updated at
# all, only replaced by a new message.
_UPDATE_MASK_PATHS: dict[str, str] = {
    "text": "text",
    "cardsV2": "cards_v2",
    "attachment": "attachment",
    "accessoryWidgets": "accessory_widgets",
}


class ChatClient:
    """Thin async wrapper over the (synchronous) Chat API client."""

    def __init__(self) -> None:
        self._service: Any | None = None
        self._credentials: Any | None = None
        self._lock = asyncio.Lock()

    async def _get_service(self) -> Any:
        if self._service is None:
            async with self._lock:
                if self._service is None:
                    self._service, self._credentials = await asyncio.to_thread(self._build_service)
        return self._service

    @staticmethod
    def _build_service() -> tuple[Any, Any]:
        credentials, _ = google.auth.default(scopes=[CHAT_BOT_SCOPE])
        service = build("chat", "v1", credentials=credentials, cache_discovery=False)
        return service, credentials

    def _new_http(self) -> Any:
        """A transport for exactly one request — see the module docstring.

        The credentials are shared deliberately: they are the expensive part (an
        ADC lookup, then a token fetch), and google-auth is built to be reused
        this way. Two threads racing to refresh an expired token both succeed;
        two threads sharing one `httplib2.Http` do not.
        """
        return google_auth_httplib2.AuthorizedHttp(self._credentials, http=httplib2.Http())

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
            return service.spaces().messages().create(**kwargs).execute(http=self._new_http())

        return await asyncio.to_thread(_execute)

    async def update_message(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        """Rewrite a message the app already posted.

        Used to stream a reply: the placeholder posted the moment the question
        arrives is rewritten in place as the model produces text, so the user
        watches the answer appear instead of staring at silence — see
        `chat/live_reply.py`.

        The update mask is derived from `body`, and a field that is masked but
        absent is *cleared*. That is deliberate: swapping the streamed text for
        a card at the end passes both keys so the half-written text goes away.

        Only the app's own messages can be updated, which is all this is for.

        Raises:
            ValueError: for a body field `patch` cannot update. Failing here
                beats a 400 from Chat halfway through a streamed reply.
        """
        service = await self._get_service()
        try:
            update_mask = ",".join(sorted(_UPDATE_MASK_PATHS[field] for field in body))
        except KeyError as exc:
            raise ValueError(f"Chat cannot patch the field {exc.args[0]!r}") from exc

        def _execute() -> dict[str, Any]:
            return (
                service.spaces()
                .messages()
                .patch(name=name, updateMask=update_mask, body=body)
                .execute(http=self._new_http())
            )

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
                .execute(http=self._new_http())
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
        # A user-identity service is built fresh per call and so already owns a
        # private transport; overriding it with `_new_http` would swap the
        # user's credentials for the app's and delete nothing.
        service = (
            await asyncio.to_thread(self._build_user_service, access_token)
            if access_token
            else await self._get_service()
        )
        http = None if access_token else self._new_http()

        def _execute() -> None:
            service.spaces().messages().delete(name=name, force=True).execute(http=http)

        await asyncio.to_thread(_execute)

    async def list_members(self, space: str) -> list[dict[str, Any]]:
        service = await self._get_service()

        def _execute() -> list[dict[str, Any]]:
            response = (
                service.spaces()
                .members()
                .list(parent=space, pageSize=100)
                .execute(http=self._new_http())
            )
            return response.get("memberships", [])

        return await asyncio.to_thread(_execute)

    async def download_attachment(self, resource_name: str) -> bytes:
        """Fetch the raw bytes of an attachment a user uploaded straight into Chat.

        Only for `Attachment.source == UPLOADED_CONTENT`; a Drive-sourced
        attachment has no bytes of its own here and is fetched from the Drive
        API instead, with the user's own token — see `chat/attachments.py`.
        `chat.bot` (already held for posting) is enough: it names the app as a
        member of the space the attachment lives in.

        `download_media` (not `download`) is the variant `googleapiclient`
        generates for a `supportsMediaDownload` method: it skips JSON parsing
        and returns the raw response body.
        """
        service = await self._get_service()

        def _execute() -> bytes:
            return (
                service.media()
                .download_media(resourceName=resource_name)
                .execute(http=self._new_http())
            )

        return await asyncio.to_thread(_execute)

    async def list_spaces(self) -> list[dict[str, Any]]:
        service = await self._get_service()

        def _execute() -> list[dict[str, Any]]:
            return (
                service.spaces().list(pageSize=100).execute(http=self._new_http()).get("spaces", [])
            )

        return await asyncio.to_thread(_execute)


@lru_cache
def get_chat_client() -> ChatClient:
    return ChatClient()
