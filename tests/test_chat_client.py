"""The Chat API client, and the thread-safety it has to provide.

`googleapiclient` is built on `httplib2`, whose `Http` object is not thread-safe.
Every call here runs on a worker thread and several are routinely in flight at
once — one instance serves many spaces, and a streamed reply rewrites its
message every couple of seconds — so sharing one transport would let concurrent
requests interleave on a single connection.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import googleapiclient
import httplib2
import pytest

from gemini_act.chat.client import ChatClient


class FakeRequest:
    """One built API request; records the transport it was executed with."""

    def __init__(self, calls: list, kind: str, kwargs: dict) -> None:
        self._calls = calls
        self._kind = kind
        self._kwargs = kwargs

    def execute(self, http=None):
        self._calls.append({"kind": self._kind, "http": http, **self._kwargs})
        return {"name": "spaces/AAA/messages/m1"}


class FakeMessages:
    def __init__(self, calls: list) -> None:
        self._calls = calls

    def create(self, **kwargs):
        return FakeRequest(self._calls, "create", kwargs)

    def patch(self, **kwargs):
        return FakeRequest(self._calls, "patch", kwargs)

    def delete(self, **kwargs):
        return FakeRequest(self._calls, "delete", kwargs)


class FakeSpaces:
    def __init__(self, calls: list) -> None:
        self._calls = calls

    def messages(self):
        return FakeMessages(self._calls)


class FakeMedia:
    def __init__(self, calls: list) -> None:
        self._calls = calls

    def download_media(self, **kwargs):
        return FakeRequest(self._calls, "download_media", kwargs)


class FakeService:
    def __init__(self) -> None:
        self.calls: list = []

    def spaces(self):
        return FakeSpaces(self.calls)

    def media(self):
        return FakeMedia(self.calls)


@pytest.fixture
def client() -> tuple[ChatClient, FakeService]:
    """A client wired to a fake service, so no ADC lookup and no network."""
    chat = ChatClient()
    service = FakeService()
    chat._service = service
    chat._credentials = object()
    return chat, service


def test_each_request_gets_its_own_transport(client):
    """The whole point: two calls must never share an httplib2.Http."""
    chat, _ = client
    first, second = chat._new_http(), chat._new_http()

    assert first is not second
    assert first.http is not second.http, "the underlying httplib2 client too"
    assert first.credentials is second.credentials, "credentials are the expensive part"


async def test_posting_executes_with_a_private_transport(client):
    chat, service = client

    await chat.post_message("spaces/AAA", {"text": "hi"})

    assert service.calls[0]["kind"] == "create"
    assert service.calls[0]["http"] is not None


async def test_concurrent_calls_never_share_a_transport(client):
    """The failure this guards against only shows up under concurrency, which
    streaming makes ordinary rather than exceptional."""
    chat, service = client

    await asyncio.gather(
        *(chat.update_message("spaces/AAA/messages/m1", {"text": str(i)}) for i in range(8))
    )

    transports = [call["http"] for call in service.calls]
    assert len(transports) == 8
    assert len({id(http) for http in transports}) == 8


async def test_a_user_identity_delete_keeps_its_own_credentials(client, monkeypatch):
    """Overriding the transport there would swap the user's credentials for the
    app's, and Chat would refuse to delete the human's message."""
    chat, _ = client
    user_service = FakeService()
    monkeypatch.setattr(ChatClient, "_build_user_service", staticmethod(lambda token: user_service))

    await chat.delete_message("spaces/AAA/messages/m1", access_token="user-token")

    assert user_service.calls[0]["http"] is None, "use the service's own authorized transport"


async def test_download_attachment_uses_the_media_download_method(client):
    """Must be `download_media`, not `download` — the plain method tries to
    JSON-decode the response and would choke on raw file bytes."""
    chat, service = client

    await chat.download_attachment("spaces/AAA/messages/BBB/attachments/CCC")

    assert service.calls[0]["kind"] == "download_media"
    assert service.calls[0]["resourceName"] == "spaces/AAA/messages/BBB/attachments/CCC"
    assert service.calls[0]["http"] is not None, "its own transport, like every other call"


class _FakeHttpTransport:
    """An httplib2-shaped transport: `.request(uri, method, body, headers)`
    returning `(response, content)`, the interface `HttpRequest.execute`
    actually calls. Unlike `FakeService` above (which stubs out
    `googleapiclient` entirely), this drives the *real* Chat API resource
    built from the API's own discovery document — so it catches a mistake
    `FakeService` structurally cannot: a method name that does not exist, or
    a URL/verb the real client would not actually produce."""

    def __init__(self, content: bytes, status: int = 200) -> None:
        self.content = content
        self.status = status
        self.calls: list[dict] = []

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        self.calls.append({"uri": uri, "method": method})
        return httplib2.Response({"status": self.status}), self.content


async def test_download_attachment_against_the_real_generated_client():
    """`ChatClient.download_attachment` calls `media().download_media()`,
    which only exists because the Chat API's discovery document flags
    `media.download` as `supportsMediaDownload` — a detail easy to get wrong
    (e.g. by calling the plain `download()`, which tries to JSON-decode raw
    file bytes and would break on every real attachment) without ever
    failing against a hand-rolled fake. Building the service from the real
    discovery document, and only faking the HTTP transport underneath it,
    verifies the actual request shape: GET, `?alt=media`, raw bytes back."""
    import json

    from googleapiclient.discovery import build_from_document

    discovery_path = (
        Path(googleapiclient.__file__).parent / "discovery_cache" / "documents" / "chat.v1.json"
    )
    document = json.loads(discovery_path.read_text())
    service = build_from_document(document, credentials=None)

    chat = ChatClient()
    chat._service = service
    chat._credentials = object()
    transport = _FakeHttpTransport(content=b"\x89PNG raw bytes, not json")
    chat._new_http = lambda: transport  # bypass AuthorizedHttp wrapping; irrelevant here

    result = await chat.download_attachment("spaces/AAA/messages/BBB/attachments/CCC")

    assert result == b"\x89PNG raw bytes, not json", "MediaModel must hand back raw bytes"
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["uri"] == (
        "https://chat.googleapis.com/v1/media/spaces/AAA/messages/BBB/attachments/CCC?alt=media"
    )


async def test_upload_attachment_against_the_real_generated_client(monkeypatch):
    """Same rationale as the download test above, for the other direction:
    `media().upload()` only exists, and only builds a multipart request to
    the `/upload/v1/...` path, because the discovery document says so —
    nothing a hand-rolled fake could catch if that stopped being true."""
    import json

    from googleapiclient.discovery import build_from_document

    discovery_path = (
        Path(googleapiclient.__file__).parent / "discovery_cache" / "documents" / "chat.v1.json"
    )
    document = json.loads(discovery_path.read_text())
    transport = _FakeHttpTransport(
        content=b'{"attachmentDataRef": {"resourceName": "spaces/AAA/messages/x/attachments/y"}}'
    )
    # `upload_attachment` builds a fresh user-identity service per call and
    # executes with its own default transport (no explicit `http=` override,
    # unlike every app-identity call) — so the fake has to live there.
    service = build_from_document(document, http=transport)
    monkeypatch.setattr(ChatClient, "_build_user_service", staticmethod(lambda token: service))

    chat = ChatClient()
    result = await chat.upload_attachment(
        "spaces/AAA", "report.csv", b"a,b\n1,2\n", "text/csv", access_token="user-token"
    )

    assert result == {"attachmentDataRef": {"resourceName": "spaces/AAA/messages/x/attachments/y"}}
    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["uri"].startswith(
        "https://chat.googleapis.com/upload/v1/spaces/AAA/attachments:upload"
    )


async def test_an_app_identity_delete_uses_a_private_transport(client):
    chat, service = client

    await chat.delete_message("spaces/AAA/messages/m1")

    assert service.calls[0]["http"] is not None


# --- update masks ---


async def test_updating_text_masks_only_text(client):
    chat, service = client

    await chat.update_message("spaces/AAA/messages/m1", {"text": "hello"})

    assert service.calls[0]["updateMask"] == "text"


async def test_updating_a_card_masks_the_proto_field_name(client):
    """The body says `cardsV2`; the mask has to say `cards_v2`, or Chat 400s
    halfway through a streamed reply."""
    chat, service = client

    await chat.update_message("spaces/AAA/messages/m1", {"text": "", "cardsV2": []})

    assert service.calls[0]["updateMask"] == "cards_v2,text"


async def test_an_unpatchable_field_fails_before_the_request(client):
    chat, service = client

    with pytest.raises(ValueError, match="cannot patch"):
        await chat.update_message("spaces/AAA/messages/m1", {"thread": {"name": "x"}})

    assert service.calls == [], "nothing should have reached Chat"
