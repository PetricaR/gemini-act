"""Event parsing and routing."""

from __future__ import annotations

import pytest

from gemini_act.chat import events
from gemini_act.oauth.store import StoredToken, TokenService


def message_event(text: str = "hello", *, command_id: str = "", thread: str = "t1") -> dict:
    message: dict = {
        "name": "spaces/AAA/messages/BBB",
        "text": text,
        "argumentText": text,
        "sender": {"name": "users/123", "displayName": "Ada"},
        "thread": {"name": f"spaces/AAA/threads/{thread}"},
        "space": {"name": "spaces/AAA", "type": "DM"},
    }
    if command_id:
        message["slashCommand"] = {"commandId": command_id}
    return {
        "type": "MESSAGE",
        "message": message,
        "user": {"name": "users/123", "displayName": "Ada"},
        "space": {"name": "spaces/AAA", "type": "DM"},
    }


class Scheduler:
    """Captures what would run in the background."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, fn, *args) -> None:
        self.calls.append((fn, args))


@pytest.fixture
def authorized(monkeypatch, token_service: TokenService):
    """A token service where users/123 has already consented."""

    async def _seed():
        await token_service.store.put(
            "users/123",
            StoredToken(refresh_token="r", scopes=["s"], email="ada@example.com"),
        )

    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    return _seed


def test_parse_event_extracts_identity_and_thread():
    ctx = events.parse_event(message_event("what's on my calendar"))
    assert ctx.user_id == "users/123"
    assert ctx.display_name == "Ada"
    assert ctx.space == "spaces/AAA"
    assert ctx.text == "what's on my calendar"
    assert ctx.command is None


def test_session_id_is_per_thread():
    a = events.parse_event(message_event(thread="t1")).session_id
    b = events.parse_event(message_event(thread="t2")).session_id
    assert a != b
    assert "/" not in a


def test_session_id_falls_back_to_space_without_thread():
    event = message_event()
    del event["message"]["thread"]
    assert events.parse_event(event).session_id == "spaces_AAA"


def test_command_recognised_by_id():
    assert events.parse_event(message_event("/help", command_id="1")).command == "help"


def test_command_recognised_by_text_when_id_missing():
    event = message_event("/reset")
    assert events.parse_event(event).command == "reset"


def test_unknown_slash_text_is_not_a_command():
    assert events.parse_event(message_event("/deploy prod")).command is None


async def test_added_to_space_returns_welcome():
    response = await events.handle_event({"type": "ADDED_TO_SPACE"}, Scheduler())
    assert response["cardsV2"][0]["cardId"] == "welcome"


async def test_unknown_event_type_is_ignored():
    assert await events.handle_event({"type": "SOMETHING_ELSE"}, Scheduler()) == {}


async def test_unauthorized_user_gets_auth_card(monkeypatch, token_service):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    scheduler = Scheduler()

    response = await events.handle_event(message_event("find my budget doc"), scheduler)

    assert response["cardsV2"][0]["cardId"] == "auth"
    assert not scheduler.calls, "must not run the agent before the user has consented"


async def test_authorized_user_schedules_agent_run(authorized, monkeypatch):
    await authorized()
    scheduler = Scheduler()

    response = await events.handle_event(message_event("find my budget doc"), scheduler)

    assert response == {}, "webhook acknowledges immediately; the reply arrives async"
    assert len(scheduler.calls) == 1
    fn, (ctx,) = scheduler.calls[0]
    assert fn is events.run_and_reply
    assert ctx.text == "find my budget doc"


async def test_help_command_needs_no_authorization(token_service, monkeypatch):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    response = await events.handle_event(message_event("/help", command_id="1"), Scheduler())
    assert response["cardsV2"][0]["cardId"] == "welcome"


async def test_auth_command_returns_signed_link(token_service, monkeypatch):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    response = await events.handle_event(message_event("/auth", command_id="2"), Scheduler())
    button = response["cardsV2"][0]["card"]["sections"][0]["widgets"][1]["buttonList"]["buttons"][0]
    assert "/oauth/start?state=" in button["onClick"]["openLink"]["url"]


async def test_reset_command_clears_the_session(monkeypatch, token_service):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    cleared: list[tuple[str, str]] = []

    async def fake_reset(user_id, session_id):
        cleared.append((user_id, session_id))

    monkeypatch.setattr(events, "reset_session", fake_reset)
    response = await events.handle_event(message_event("/reset", command_id="3"), Scheduler())

    assert cleared == [("users/123", "spaces_AAA_threads_t1")]
    assert "fresh" in response["text"]


async def test_whoami_reports_connected_account(authorized, monkeypatch):
    await authorized()
    response = await events.handle_event(message_event("/whoami", command_id="4"), Scheduler())
    assert "ada@example.com" in response["text"]


async def test_run_and_reply_posts_answer_in_thread(monkeypatch):
    posted: list[dict] = []

    class FakeClient:
        async def post_message(self, space, body, thread_name=None):
            posted.append({"space": space, "body": body, "thread": thread_name})
            return {}

    async def fake_run(user_id, session_id, message):
        return "Your next meeting is at 3pm."

    monkeypatch.setattr(events, "get_chat_client", lambda: FakeClient())
    monkeypatch.setattr(events, "run_agent", fake_run)

    ctx = events.parse_event(message_event("when's my next meeting"))
    await events.run_and_reply(ctx)

    assert posted[0]["space"] == "spaces/AAA"
    assert posted[0]["thread"] == "spaces/AAA/threads/t1"
    assert posted[0]["body"]["text"] == "Your next meeting is at 3pm."


async def test_run_and_reply_reports_timeout_instead_of_failing_silently(monkeypatch):
    posted: list[dict] = []

    class FakeClient:
        async def post_message(self, space, body, thread_name=None):
            posted.append(body)
            return {}

    async def fake_run(user_id, session_id, message):
        raise TimeoutError

    monkeypatch.setattr(events, "get_chat_client", lambda: FakeClient())
    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert posted[0]["cardsV2"][0]["cardId"] == "error"


async def test_run_and_reply_reports_agent_error(monkeypatch):
    posted: list[dict] = []

    class FakeClient:
        async def post_message(self, space, body, thread_name=None):
            posted.append(body)
            return {}

    async def fake_run(user_id, session_id, message):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(events, "get_chat_client", lambda: FakeClient())
    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert posted[0]["cardsV2"][0]["cardId"] == "error"
