"""The Chat API client, and the thread-safety it has to provide.

`googleapiclient` is built on `httplib2`, whose `Http` object is not thread-safe.
Every call here runs on a worker thread and several are routinely in flight at
once — one instance serves many spaces, and a streamed reply rewrites its
message every couple of seconds — so sharing one transport would let concurrent
requests interleave on a single connection.
"""

from __future__ import annotations

import asyncio

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


class FakeService:
    def __init__(self) -> None:
        self.calls: list = []

    def spaces(self):
        return FakeSpaces(self.calls)


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
