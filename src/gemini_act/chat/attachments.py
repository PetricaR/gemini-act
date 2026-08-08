"""Turning Google Chat attachments into content the model can actually read.

A message a user attaches a file to carries only metadata in the webhook
payload: a name, a MIME type, and a reference to fetch the bytes from
elsewhere. Which elsewhere depends on `Attachment.source`:

  UPLOADED_CONTENT — the file was dropped straight into Chat. Its bytes live
  behind the Chat API's own `media.download`, reachable with the app's own
  `chat.bot` identity (see `ChatClient.download_attachment`).

  DRIVE_FILE — the user picked a file already in their Drive. Its bytes live
  behind the Drive API and must be fetched with the *user's* OAuth token; the
  app has no standing access to someone's Drive. A Google-native file (Doc,
  Sheet, Slide) has no bytes of its own at all and is exported to PDF first,
  which Gemini reads natively.

Either way the result becomes a `types.Part` Gemini can read inline. Anything
that cannot be fetched, or is not a type Gemini accepts inline, is reported
back as a line of text instead of silently vanishing — that silence is exactly
the bug this module exists to fix (the agent looked like it could not see the
user's files because nothing upstream of it ever tried to fetch them).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from google.genai import types

from gemini_act.chat.client import ChatClient
from gemini_act.config import Settings
from gemini_act.oauth.store import TokenService

logger = logging.getLogger(__name__)

# MIME types (or prefixes) Gemini accepts as inline data. Office formats
# (docx/xlsx/pptx) are deliberately absent: unlike the Drive-native formats
# below, they are ZIP/XML containers the model cannot read as raw bytes.
_INLINE_PREFIXES = ("image/", "audio/", "video/", "text/")
_INLINE_EXACT = frozenset({"application/pdf", "application/json", "application/rtf"})

# Google-native Drive formats have no bytes of their own; each is exported to
# PDF first. Formats not listed here (Forms, Drawings, Sites, Apps Script, ...)
# have no export path worth taking.
_DRIVE_EXPORT_MIME_TYPES: dict[str, str] = {
    "application/vnd.google-apps.document": "application/pdf",
    "application/vnd.google-apps.spreadsheet": "application/pdf",
    "application/vnd.google-apps.presentation": "application/pdf",
}


def _is_inlineable(content_type: str) -> bool:
    return content_type in _INLINE_EXACT or content_type.startswith(_INLINE_PREFIXES)


async def _download_drive_file(file_id: str, content_type: str, access_token: str) -> bytes:
    """Fetch a Drive-hosted attachment's bytes, exporting Google-native files first.

    Runs in a worker thread: `googleapiclient` is synchronous, same as every
    call `ChatClient` makes.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    def _execute() -> bytes:
        service = build(
            "drive", "v3", credentials=Credentials(token=access_token), cache_discovery=False
        )
        export_mime = _DRIVE_EXPORT_MIME_TYPES.get(content_type)
        if export_mime:
            return service.files().export_media(fileId=file_id, mimeType=export_mime).execute()
        return service.files().get_media(fileId=file_id).execute()

    return await asyncio.to_thread(_execute)


async def resolve_attachments(
    raw_attachments: list[dict[str, Any]],
    *,
    user_id: str,
    chat_client: ChatClient,
    token_service: TokenService,
    settings: Settings,
) -> tuple[list[types.Part], list[str]]:
    """Download and convert Chat attachments into parts for the model.

    Returns `(parts, notes)`. `parts` is ready to append to the user's turn.
    `notes` describes anything that could not be included (wrong type, too
    large, download failed) so the caller can tell the model about it — the
    same "report the failure, don't invent a cause" rule the system
    instruction applies to tool errors applies here too.
    """
    parts: list[types.Part] = []
    notes: list[str] = []

    for attachment in raw_attachments[: settings.chat_attachment_max_count]:
        name = attachment.get("contentName") or "attachment"
        content_type = attachment.get("contentType") or "application/octet-stream"
        source = attachment.get("source")

        if not _is_inlineable(content_type) and content_type not in _DRIVE_EXPORT_MIME_TYPES:
            notes.append(f"{name} ({content_type}): this file type can't be read directly.")
            continue

        try:
            if source == "DRIVE_FILE":
                file_id = (attachment.get("driveDataRef") or {}).get("driveFileId")
                access_token = await token_service.get_access_token(user_id)
                if not file_id or not access_token:
                    notes.append(f"{name}: no access to this Drive file.")
                    continue
                data = await _download_drive_file(file_id, content_type, access_token)
                # A Google-native file arrives as the exported PDF, not its
                # original type — the part below must be labelled to match.
                if content_type in _DRIVE_EXPORT_MIME_TYPES:
                    content_type = "application/pdf"
            elif source == "UPLOADED_CONTENT":
                resource_name = (attachment.get("attachmentDataRef") or {}).get("resourceName")
                if not resource_name:
                    notes.append(f"{name}: missing download reference.")
                    continue
                data = await chat_client.download_attachment(resource_name)
            else:
                notes.append(f"{name}: unrecognised attachment source.")
                continue
        except Exception:
            logger.warning(
                "Failed to download attachment %s (%s)", name, content_type, exc_info=True
            )
            notes.append(f"{name}: could not be downloaded.")
            continue

        if len(data) > settings.chat_attachment_max_bytes:
            notes.append(f"{name}: too large to include ({len(data) / 1_000_000:.1f} MB).")
            continue

        parts.append(types.Part(text=f"Attached file: {name} ({content_type})"))
        parts.append(types.Part.from_bytes(data=data, mime_type=content_type))

    if len(raw_attachments) > settings.chat_attachment_max_count:
        skipped = len(raw_attachments) - settings.chat_attachment_max_count
        notes.append(
            f"Only the first {settings.chat_attachment_max_count} attachment(s) were read; "
            f"{skipped} more were ignored."
        )

    return parts, notes
