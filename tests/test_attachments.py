"""Turning Chat attachment metadata into content the model can read.

The Chat webhook never used to look at `message.attachment` at all, which is
why an attached file appeared to the user as if the agent could not see it —
nothing downloaded it, let alone showed it to the model. These tests cover the
two download paths (`UPLOADED_CONTENT` via the Chat API, `DRIVE_FILE` via the
Drive API) and the failure modes that must produce a note instead of silence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from gemini_act.chat import attachments
from gemini_act.chat.attachments import resolve_attachments
from gemini_act.config import Settings
from gemini_act.oauth.store import InMemoryTokenStore, StoredToken, TokenService


def _settings(**overrides) -> Settings:
    return Settings(**{"token_store": "memory", **overrides})


class FakeChatClient:
    def __init__(self, data: bytes | Exception = b"raw-bytes") -> None:
        self._data = data
        self.requested: list[str] = []

    async def download_attachment(self, resource_name: str) -> bytes:
        self.requested.append(resource_name)
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


@pytest.fixture
async def token_service() -> TokenService:
    service = TokenService(InMemoryTokenStore(), _settings())
    await service.store.put(
        "users/123",
        StoredToken(
            refresh_token="r",
            scopes=["s"],
            access_token="tok",
            expiry=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    return service


def _uploaded(name: str = "photo.png", content_type: str = "image/png") -> dict:
    return {
        "contentName": name,
        "contentType": content_type,
        "source": "UPLOADED_CONTENT",
        "attachmentDataRef": {"resourceName": "spaces/AAA/messages/BBB/attachments/CCC"},
    }


def _drive(name: str = "notes.pdf", content_type: str = "application/pdf", file_id="F1") -> dict:
    return {
        "contentName": name,
        "contentType": content_type,
        "source": "DRIVE_FILE",
        "driveDataRef": {"driveFileId": file_id},
    }


# --- uploaded-to-Chat attachments ---


async def test_uploaded_attachment_is_downloaded_and_inlined(token_service):
    chat_client = FakeChatClient(b"\x89PNG-bytes")

    parts, notes = await resolve_attachments(
        [_uploaded()],
        user_id="users/123",
        chat_client=chat_client,
        token_service=token_service,
        settings=_settings(),
    )

    assert notes == []
    assert chat_client.requested == ["spaces/AAA/messages/BBB/attachments/CCC"]
    assert parts[0].text == "Attached file: photo.png (image/png)"
    assert parts[1].inline_data.data == b"\x89PNG-bytes"
    assert parts[1].inline_data.mime_type == "image/png"


async def test_unsupported_mime_type_is_reported_without_downloading(token_service):
    chat_client = FakeChatClient()

    parts, notes = await resolve_attachments(
        [_uploaded("archive.zip", "application/zip")],
        user_id="users/123",
        chat_client=chat_client,
        token_service=token_service,
        settings=_settings(),
    )

    assert parts == []
    assert chat_client.requested == [], "an unsupported type must never trigger a download"
    assert "archive.zip" in notes[0]
    assert "application/zip" in notes[0]


async def test_a_failed_download_is_reported_not_raised(token_service):
    chat_client = FakeChatClient(RuntimeError("Chat had a moment"))

    parts, notes = await resolve_attachments(
        [_uploaded()],
        user_id="users/123",
        chat_client=chat_client,
        token_service=token_service,
        settings=_settings(),
    )

    assert parts == []
    assert "photo.png" in notes[0]
    assert "could not be downloaded" in notes[0]


async def test_an_oversized_attachment_is_reported_not_inlined(token_service):
    chat_client = FakeChatClient(b"x" * 100)

    parts, notes = await resolve_attachments(
        [_uploaded()],
        user_id="users/123",
        chat_client=chat_client,
        token_service=token_service,
        settings=_settings(chat_attachment_max_bytes=50),
    )

    assert parts == []
    assert "too large" in notes[0]


async def test_missing_resource_name_is_reported(token_service):
    chat_client = FakeChatClient()
    attachment = _uploaded()
    attachment["attachmentDataRef"] = {}

    parts, notes = await resolve_attachments(
        [attachment],
        user_id="users/123",
        chat_client=chat_client,
        token_service=token_service,
        settings=_settings(),
    )

    assert parts == []
    assert chat_client.requested == []
    assert "missing download reference" in notes[0]


async def test_only_the_configured_max_count_is_read(token_service):
    chat_client = FakeChatClient(b"data")
    raw = [_uploaded(f"f{i}.png") for i in range(4)]

    parts, notes = await resolve_attachments(
        raw,
        user_id="users/123",
        chat_client=chat_client,
        token_service=token_service,
        settings=_settings(chat_attachment_max_count=2),
    )

    assert len(chat_client.requested) == 2
    assert "Only the first 2" in notes[-1]
    assert "2 more" in notes[-1]


# --- Drive-hosted attachments ---


async def test_drive_file_is_downloaded_with_the_users_own_token(token_service):
    chat_client = FakeChatClient()

    with patch.object(
        attachments, "_download_drive_file", AsyncMock(return_value=b"pdf-bytes")
    ) as fake_download:
        parts, notes = await resolve_attachments(
            [_drive()],
            user_id="users/123",
            chat_client=chat_client,
            token_service=token_service,
            settings=_settings(),
        )

    assert notes == []
    fake_download.assert_awaited_once_with("F1", "application/pdf", "tok")
    assert parts[1].inline_data.data == b"pdf-bytes"


async def test_a_google_native_doc_is_exported_and_relabelled_as_pdf(token_service):
    chat_client = FakeChatClient()
    doc = _drive("Q3 plan", "application/vnd.google-apps.document")

    with patch.object(attachments, "_download_drive_file", AsyncMock(return_value=b"%PDF")):
        parts, notes = await resolve_attachments(
            [doc],
            user_id="users/123",
            chat_client=chat_client,
            token_service=token_service,
            settings=_settings(),
        )

    assert notes == []
    assert parts[0].text == "Attached file: Q3 plan (application/pdf)"
    assert parts[1].inline_data.mime_type == "application/pdf"


async def test_drive_file_without_a_connected_account_is_reported(token_service):
    chat_client = FakeChatClient()

    parts, notes = await resolve_attachments(
        [_drive()],
        user_id="users/no-token",
        chat_client=chat_client,
        token_service=token_service,
        settings=_settings(),
    )

    assert parts == []
    assert "no access" in notes[0]


def test_export_map_only_covers_formats_gemini_can_read_as_pdf():
    assert set(attachments._DRIVE_EXPORT_MIME_TYPES.values()) == {"application/pdf"}
