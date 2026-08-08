"""A Chat message that is rewritten while it is still being written.

Google Chat has no typing indicator an app can raise, and no partial-message
API. What it does have is `spaces.messages.patch`, so the effect is built from
two ordinary operations: post a placeholder the instant the question arrives,
then rewrite that same message as the model produces text. The user sees an
answer growing in place rather than 30 seconds of silence followed by a wall of
text.

Everything here degrades rather than fails. If the placeholder cannot be posted
the object quietly becomes a plain "post once at the end" — which is exactly
what this service did before — and a failed rewrite mid-stream is dropped, since
the next one carries the whole text anyway.

Writes are serialised and stop once `finish` has run, so the last thing written
is the final answer. One residual race is not fixable from here: the agent turn
runs under `asyncio.wait_for`, and a timeout that lands while a rewrite is in
flight cancels the coroutine but not the worker thread already inside the HTTP
call, which can then arrive after the timeout message. It needs the rewrite to
be mid-flight at the exact moment the budget expires, and costs a stale message
rather than a lost one.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# What the user sees between asking and the first token arriving.
PLACEHOLDER = "💭 Thinking…"

# Appended while text is still arriving, and gone from the final message. A
# block rather than an ellipsis so it reads as a caret, not as truncation.
CURSOR = " ▌"

# Chat rejects a message body over 4096 characters. Streaming updates are
# trimmed to stay clear of that; the limit is on the message, so a long answer
# would have failed to post before this existed too.
MAX_TEXT = 4000
_TRUNCATION_NOTE = "\n\n_(truncated)_"


def _fit(text: str) -> str:
    if len(text) <= MAX_TEXT:
        return text
    return text[: MAX_TEXT - len(_TRUNCATION_NOTE)] + _TRUNCATION_NOTE


class LiveReply:
    """One reply, posted immediately and rewritten as the agent writes it."""

    def __init__(
        self,
        client: Any,
        space: str,
        *,
        thread_name: str | None = None,
        thread_key: str | None = None,
        interval_seconds: float = 1.0,
        placeholder: str = PLACEHOLDER,
    ) -> None:
        self._client = client
        self._space = space
        self._thread_name = thread_name
        self._thread_key = thread_key
        self._interval_seconds = interval_seconds
        self._placeholder = placeholder
        self._name: str | None = None
        self._sent = ""
        self._sent_at = 0.0
        self._finished = False
        # Serialises rewrites so a slow one cannot be overtaken by the next,
        # which would leave the message showing older text than it already did.
        self._write_lock = asyncio.Lock()

    @property
    def is_live(self) -> bool:
        """Whether there is a posted message to rewrite."""
        return self._name is not None

    async def start(self) -> None:
        """Post the placeholder. Silent failure is intended — see module docs."""
        try:
            result = await self._client.post_message(
                self._space,
                {"text": self._placeholder},
                thread_name=self._thread_name,
                thread_key=self._thread_key,
            )
        except Exception:
            logger.warning("Could not post the placeholder into %s", self._space, exc_info=True)
            return

        self._name = (result or {}).get("name")
        if self._name is None:
            # Not an error: the fake clients in the tests, and any Chat response
            # without a name, simply mean there is nothing to rewrite later.
            logger.debug("Placeholder in %s has no message name; streaming off", self._space)
            return
        self._sent = self._placeholder
        self._sent_at = time.monotonic()

    async def push(self, text: str) -> None:
        """Show `text` as the answer so far, at most once per interval.

        Dropping an update is free: each one carries the whole text written so
        far, not a delta, so the next one supersedes whatever was skipped, and
        `finish` always writes the last state regardless of the interval.
        """
        if self._name is None or self._finished or not text.strip():
            return
        if time.monotonic() - self._sent_at < self._interval_seconds:
            return
        await self._write({"text": _fit(text) + CURSOR})

    async def finish(self, body: dict[str, Any]) -> None:
        """Replace the message with the final body, or post it if not live.

        After this, `push` is a no-op: the answer is settled, and a straggling
        rewrite would only put half of it back.
        """
        if "text" in body:
            body = {**body, "text": _fit(body["text"])}
        self._finished = True
        if self._name is not None:
            # `cardsV2` alone would leave the streamed text above the card, so
            # the empty text is what clears it — see `ChatClient.update_message`.
            final = {"text": "", **body} if "cardsV2" in body else body
            if await self._write(final, force=True):
                return
            # The message is unreachable, so the placeholder cannot be trusted
            # to disappear on its own — take it down before posting again,
            # otherwise the user is left with a "Thinking…" that never resolved.
            logger.warning("Falling back to a new message in %s", self._space)
            await self._discard_placeholder()

        try:
            result = await self._client.post_message(
                self._space,
                body,
                thread_name=self._thread_name,
                thread_key=self._thread_key,
            )
        except Exception:
            logger.exception("Could not post reply into %s", self._space)
            return
        logger.info(
            "Posted reply %s into thread %s of %s",
            (result or {}).get("name"),
            ((result or {}).get("thread") or {}).get("name"),
            self._space,
        )

    async def _discard_placeholder(self) -> None:
        """Best effort: it is already gone in the likeliest failure case."""
        try:
            await self._client.delete_message(self._name)
        except Exception:
            logger.debug("Could not remove the placeholder %s", self._name, exc_info=True)

    async def _write(self, body: dict[str, Any], *, force: bool = False) -> bool:
        async with self._write_lock:
            # Re-checked under the lock: `finish` may have settled the message
            # while this rewrite was queued behind a slower one.
            if self._finished and not force:
                return True
            if body.get("text", None) == self._sent and "cardsV2" not in body:
                return True
            try:
                await self._client.update_message(self._name, body)
            except Exception:
                logger.warning("Could not rewrite %s", self._name, exc_info=True)
                return False
            self._sent = body.get("text", "")
            self._sent_at = time.monotonic()
            return True
