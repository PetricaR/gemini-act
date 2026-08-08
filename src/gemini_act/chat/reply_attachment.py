"""Letting the model attach a file to its own reply, not just read one.

`chat/attachments.py` covers a file coming *in* (the user dropped one on
their message); this is the same idea in reverse. There is no ADK helper for
either direction, so this uses the same convention as `chat/a2ui.py`: the
model ends its answer with a marker, then a small JSON object, which
`events.py` pulls back out before the answer ever reaches Chat.

The payload is deliberately just `{filename, mimeType, contentBase64}` — the
model composes small text-ish output itself (a CSV summary, a text report),
it does not have file bytes lying around to reference by id the way it does
Drive files, which it can already share as a link through its Drive tools
without needing this at all.

Sending the result is a second message, not merged into the reply: Chat's
own upload guide requires the *uploading* identity's own credentials for a
`spaces.messages.create` call that references the upload, and every other
reply in this app is posted as the app itself (`chat.bot`) — see
`ChatClient.upload_attachment`. Two messages, one from each identity, is the
honest shape of what is actually happening, not a limitation worth hiding.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import Any

# Mirrors chat/a2ui.py's MARKER; a distinct string so a model that (against
# the system instruction) tries to use both in one answer still gets each
# parsed for what it is, in whichever order they appear.
MARKER = "---chat_attachment_JSON---"

_REQUIRED_KEYS = ("filename", "mimeType", "contentBase64")


@dataclass(frozen=True)
class ReplyAttachment:
    filename: str
    mime_type: str
    data: bytes


def split_reply_attachment(text: str) -> tuple[str, str]:
    """Split an answer into its spoken part and a trailing raw JSON blob.

    Same contract as `a2ui.split_a2ui`: the second element is `""` with no
    marker, and this is safe to call on a partial, still-streaming string.
    """
    spoken, sep, raw = text.partition(MARKER)
    if not sep:
        return text, ""
    return spoken.rstrip(), raw.strip()


def parse_reply_attachment(raw: str, *, max_bytes: int) -> ReplyAttachment | None:
    """Parse and decode the JSON blob `split_reply_attachment` returned.

    `None` covers every way this can be unusable — malformed JSON, a missing
    field, base64 that does not decode, or a file over `max_bytes` — so the
    caller has one thing to check rather than a set of exceptions to catch.
    A model getting this wrong must degrade to "no attachment", never break
    the reply it is attached to.
    """
    import json

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or not all(k in payload for k in _REQUIRED_KEYS):
        return None

    filename, mime_type, content_b64 = (payload[k] for k in _REQUIRED_KEYS)
    if not isinstance(filename, str) or not isinstance(mime_type, str):
        return None
    if not isinstance(content_b64, str):
        return None

    try:
        data = base64.b64decode(content_b64, validate=True)
    except (binascii.Error, ValueError):
        return None

    if not filename or not mime_type or not data or len(data) > max_bytes:
        return None
    return ReplyAttachment(filename=filename, mime_type=mime_type, data=data)


def attachment_message(upload_response: dict[str, Any]) -> dict[str, Any]:
    """The message body that carries an uploaded attachment and nothing else.

    Per Chat's upload guide: `attachment` takes the upload response as-is —
    `contentName`/`contentType`/etc. are output-only fields Chat fills in
    itself once the message exists, not things this call sets.
    """
    return {"attachment": [upload_response]}
