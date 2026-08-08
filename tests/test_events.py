"""Event parsing and routing."""

from __future__ import annotations

import pytest

from gemini_act.chat import events
from gemini_act.config import Settings
from gemini_act.oauth.store import StoredToken, TokenService


def message_event(
    text: str = "hello", *, command_id: str = "", thread: str = "t1", space_type: str = "DM"
) -> dict:
    message: dict = {
        "name": "spaces/AAA/messages/BBB",
        "text": text,
        "argumentText": text,
        "sender": {"name": "users/123", "displayName": "Ada"},
        "thread": {"name": f"spaces/AAA/threads/{thread}"},
        "space": {"name": "spaces/AAA", "type": space_type},
    }
    if command_id:
        message["slashCommand"] = {"commandId": command_id}
    return {
        "type": "MESSAGE",
        "message": message,
        "user": {"name": "users/123", "displayName": "Ada"},
        "space": {"name": "spaces/AAA", "type": space_type},
    }


def addon_message_event(text: str = "hello", *, command_id: str = "") -> dict:
    """The payload shape a Chat app built as a Workspace add-on receives."""
    message = {
        "name": "spaces/AAA/messages/BBB",
        "text": text,
        "argumentText": text,
        "thread": {"name": "spaces/AAA/threads/t1"},
    }
    payload: dict = {"message": message, "space": {"name": "spaces/AAA", "type": "DM"}}
    key = "messagePayload"
    if command_id:
        key = "appCommandPayload"
        payload["appCommandMetadata"] = {
            "appCommandId": command_id,
            "appCommandType": "SLASH_COMMAND",
        }
    return {
        "chat": {"user": {"name": "users/123", "displayName": "Ada"}, key: payload},
        "commonEventObject": {"hostApp": "CHAT"},
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


def test_session_id_is_per_thread_outside_dms():
    """Named spaces can hold several topics; keep memory separate per thread."""
    a = events.parse_event(message_event(thread="t1", space_type="SPACE")).session_id
    b = events.parse_event(message_event(thread="t2", space_type="SPACE")).session_id
    assert a != b
    assert "/" not in a


def test_session_id_falls_back_to_space_without_thread():
    event = message_event(space_type="SPACE")
    del event["message"]["thread"]
    assert events.parse_event(event).session_id == "spaces_AAA"


def test_dm_session_id_is_stable_across_threads():
    """Chat can mint a fresh thread per message in a DM; memory must not reset."""
    a = events.parse_event(message_event(thread="t1", space_type="DM")).session_id
    b = events.parse_event(message_event(thread="t2", space_type="DM")).session_id
    assert a == b == "spaces_AAA"


def test_dm_thread_key_is_stable_and_space_scoped():
    ctx = events.parse_event(message_event(thread="t1", space_type="DM"))
    assert ctx.thread_key == "dm-AAA"


def test_non_dm_has_no_thread_key():
    ctx = events.parse_event(message_event(thread="t1", space_type="SPACE"))
    assert ctx.thread_key is None


# --- DM detection across payload shapes ---
#
# `type: "DM"` is deprecated; real Workspace add-on payloads have been observed
# to send only `spaceType` or only `singleUserBotDm`, with the legacy `type`
# absent entirely. Each of these must be recognised on its own.


def test_dm_detected_via_space_type_field():
    event = message_event(thread="t1")
    del event["space"]["type"]
    del event["message"]["space"]["type"]
    event["space"]["spaceType"] = "DIRECT_MESSAGE"
    event["message"]["space"]["spaceType"] = "DIRECT_MESSAGE"
    ctx = events.parse_event(event)
    assert ctx.is_dm is True
    assert ctx.thread_key == "dm-AAA"


def test_dm_detected_via_single_user_bot_dm_flag():
    event = message_event(thread="t1")
    del event["space"]["type"]
    del event["message"]["space"]["type"]
    event["space"]["singleUserBotDm"] = True
    ctx = events.parse_event(event)
    assert ctx.is_dm is True


def test_group_chat_space_type_is_not_a_dm():
    event = message_event(thread="t1")
    event["space"]["type"] = "ROOM"
    event["message"]["space"]["type"] = "ROOM"
    event["space"]["spaceType"] = "GROUP_CHAT"
    event["message"]["space"]["spaceType"] = "GROUP_CHAT"
    ctx = events.parse_event(event)
    assert ctx.is_dm is False
    assert ctx.thread_key is None


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

    assert cleared == [("users/123", "spaces_AAA")]
    assert "fresh" in response["text"]


async def test_whoami_reports_connected_account(authorized, monkeypatch):
    await authorized()
    response = await events.handle_event(message_event("/whoami", command_id="4"), Scheduler())
    assert "ada@example.com" in response["text"]


# --- /clean ---


def test_clean_command_recognised_by_id():
    assert events.parse_event(message_event("/clean", command_id="5")).command == "clean"


async def test_clean_command_schedules_and_acks_empty(monkeypatch, token_service):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    scheduler = Scheduler()

    response = await events.handle_event(message_event("/clean", command_id="5"), scheduler)

    assert response == {}, "deleting messages can be slow, so it runs like /message does"
    assert len(scheduler.calls) == 1
    fn, (ctx,) = scheduler.calls[0]
    assert fn is events.clean_conversation_and_reply


class FakeCleanClient:
    """Records list/delete calls and the final confirmation post."""

    def __init__(self, messages: list[dict]) -> None:
        self._messages = messages
        self.deleted: list[tuple[str, str | None]] = []
        self.posted: list[dict] = []

    async def list_messages(self, space):
        return self._messages

    async def delete_message(self, name, *, access_token=None):
        self.deleted.append((name, access_token))

    async def post_message(self, space, body, thread_name=None, thread_key=None):
        self.posted.append(body)
        return {}


async def test_clean_deletes_bot_messages_with_app_identity_and_users_with_their_token(
    monkeypatch, token_service
):
    async def fake_access_token(user_id):
        return "user-token"

    monkeypatch.setattr(token_service, "get_access_token", fake_access_token)
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)

    fake = FakeCleanClient(
        [
            {"name": "spaces/AAA/messages/1", "sender": {"type": "HUMAN"}},
            {"name": "spaces/AAA/messages/2", "sender": {"type": "BOT"}},
        ]
    )
    monkeypatch.setattr(events, "get_chat_client", lambda: fake)

    reset_calls: list[tuple[str, str]] = []

    async def fake_reset(user_id, session_id):
        reset_calls.append((user_id, session_id))

    monkeypatch.setattr(events, "reset_session", fake_reset)

    ctx = events.parse_event(message_event("/clean", command_id="5"))
    await events.clean_conversation_and_reply(ctx)

    assert ("spaces/AAA/messages/1", "user-token") in fake.deleted
    assert ("spaces/AAA/messages/2", None) in fake.deleted
    assert reset_calls == [("users/123", "spaces_AAA")]
    assert "2 message" in fake.posted[0]["text"]


async def test_clean_without_authorization_only_deletes_bot_messages_and_asks_to_reconnect(
    monkeypatch, token_service
):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)

    fake = FakeCleanClient(
        [
            {"name": "spaces/AAA/messages/1", "sender": {"type": "HUMAN"}},
            {"name": "spaces/AAA/messages/2", "sender": {"type": "BOT"}},
        ]
    )
    monkeypatch.setattr(events, "get_chat_client", lambda: fake)
    monkeypatch.setattr(events, "reset_session", _fake_reset)

    ctx = events.parse_event(message_event("/clean", command_id="5"))
    await events.clean_conversation_and_reply(ctx)

    assert fake.deleted == [("spaces/AAA/messages/2", None)], "only the bot's own message"
    assert fake.posted[0]["cardsV2"][0]["cardId"] == "auth"


async def test_clean_continues_past_individual_delete_failures(monkeypatch, token_service):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    monkeypatch.setattr(events, "reset_session", _fake_reset)

    class FlakyClient(FakeCleanClient):
        async def delete_message(self, name, *, access_token=None):
            if name.endswith("1"):
                raise RuntimeError("boom")
            await super().delete_message(name, access_token=access_token)

    fake = FlakyClient(
        [
            {"name": "spaces/AAA/messages/1", "sender": {"type": "BOT"}},
            {"name": "spaces/AAA/messages/2", "sender": {"type": "BOT"}},
        ]
    )
    monkeypatch.setattr(events, "get_chat_client", lambda: fake)

    ctx = events.parse_event(message_event("/clean", command_id="5"))
    await events.clean_conversation_and_reply(ctx)

    assert fake.deleted == [("spaces/AAA/messages/2", None)]
    assert "1 message" in fake.posted[0]["text"]


async def _fake_reset(user_id: str, session_id: str) -> None:
    pass


def _recording_client(posted: list[dict]):
    class FakeClient:
        async def post_message(self, space, body, thread_name=None, thread_key=None):
            posted.append(
                {"space": space, "body": body, "thread_name": thread_name, "thread_key": thread_key}
            )
            return {}

    return FakeClient()


def _reply_settings(monkeypatch, *, in_thread: bool) -> None:
    monkeypatch.setattr(
        events, "get_settings", lambda: Settings(chat_reply_in_thread=in_thread), raising=True
    )


async def _fake_answer(user_id, session_id, message):
    return "Your next meeting is at 3pm."


@pytest.mark.parametrize("space_type", ["DM", "SPACE"])
async def test_run_and_reply_posts_flat_by_default(monkeypatch, space_type):
    """The answer belongs in the main window next to the question. Threading it
    made Chat collapse every exchange into a bubble the user had to expand."""
    posted: list[dict] = []
    _reply_settings(monkeypatch, in_thread=False)
    monkeypatch.setattr(events, "get_chat_client", lambda: _recording_client(posted))
    monkeypatch.setattr(events, "run_agent", _fake_answer)

    ctx = events.parse_event(message_event("when's my next meeting", space_type=space_type))
    await events.run_and_reply(ctx)

    assert posted[0]["space"] == "spaces/AAA"
    assert posted[0]["thread_name"] is None
    assert posted[0]["thread_key"] is None
    assert posted[0]["body"]["text"] == "Your next meeting is at 3pm."


async def test_run_and_reply_in_thread_mode_uses_stable_key_in_dm(monkeypatch):
    """Opt-in threading: a DM's incoming thread is fresh per message, so keying
    on it would fragment the conversation into one bubble per exchange."""
    posted: list[dict] = []
    _reply_settings(monkeypatch, in_thread=True)
    monkeypatch.setattr(events, "get_chat_client", lambda: _recording_client(posted))
    monkeypatch.setattr(events, "run_agent", _fake_answer)

    ctx = events.parse_event(message_event("when's my next meeting", space_type="DM"))
    await events.run_and_reply(ctx)

    assert posted[0]["thread_key"] == "dm-AAA"
    assert posted[0]["thread_name"] is None


async def test_run_and_reply_in_thread_mode_uses_incoming_thread_in_space(monkeypatch):
    posted: list[dict] = []
    _reply_settings(monkeypatch, in_thread=True)
    monkeypatch.setattr(events, "get_chat_client", lambda: _recording_client(posted))
    monkeypatch.setattr(events, "run_agent", _fake_answer)

    ctx = events.parse_event(message_event("when's my next meeting", space_type="SPACE"))
    await events.run_and_reply(ctx)

    assert posted[0]["thread_name"] == "spaces/AAA/threads/t1"
    assert posted[0]["thread_key"] is None


async def test_run_and_reply_reports_timeout_instead_of_failing_silently(monkeypatch):
    posted: list[dict] = []

    class FakeClient:
        async def post_message(self, space, body, thread_name=None, thread_key=None):
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
        async def post_message(self, space, body, thread_name=None, thread_key=None):
            posted.append(body)
            return {}

    async def fake_run(user_id, session_id, message):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(events, "get_chat_client", lambda: FakeClient())
    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert posted[0]["cardsV2"][0]["cardId"] == "error"


# --- Google Workspace add-on payload shape ---


def test_normalize_passes_classic_event_through():
    event, is_addon = events.normalize_event(message_event("hi"))
    assert is_addon is False
    assert event["type"] == "MESSAGE"


def test_normalize_unwraps_addon_message():
    event, is_addon = events.normalize_event(addon_message_event("find my doc"))
    assert is_addon is True
    assert event["type"] == "MESSAGE"
    ctx = events.parse_event(event)
    assert ctx.user_id == "users/123"
    assert ctx.space == "spaces/AAA"
    assert ctx.thread == "spaces/AAA/threads/t1"
    assert ctx.text == "find my doc"


def test_normalize_unwraps_addon_app_command():
    event, is_addon = events.normalize_event(addon_message_event("/help", command_id="1"))
    assert is_addon is True
    assert event["type"] == "APP_COMMAND"
    assert events.parse_event(event).command == "help"


def test_normalize_unwraps_addon_added_to_space():
    raw = {
        "chat": {
            "user": {"name": "users/1"},
            "addedToSpacePayload": {"space": {"name": "spaces/Z"}},
        }
    }
    event, is_addon = events.normalize_event(raw)
    assert (event["type"], is_addon) == ("ADDED_TO_SPACE", True)


def test_normalize_flags_unrecognised_addon_payload():
    event, is_addon = events.normalize_event({"chat": {"mysteryPayload": {}}})
    assert is_addon is True
    assert event["type"] == ""


def test_addon_response_envelope():
    wrapped = events.to_addon_response({"text": "hello"})
    assert wrapped == {
        "hostAppDataAction": {
            "chatDataAction": {"createMessageAction": {"message": {"text": "hello"}}}
        }
    }


def test_addon_empty_response_stays_empty():
    """The async-reply acknowledgement must not be wrapped, or Chat posts a blank."""
    assert events.to_addon_response({}) == {}


async def test_addon_added_to_space_returns_wrapped_welcome():
    raw = {
        "chat": {
            "user": {"name": "users/1"},
            "addedToSpacePayload": {"space": {"name": "spaces/Z"}},
        }
    }
    response = await events.handle_event(raw, Scheduler())
    message = response["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]
    assert message["cardsV2"][0]["cardId"] == "welcome"


async def test_addon_unauthorized_user_gets_wrapped_auth_card(monkeypatch, token_service):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    response = await events.handle_event(addon_message_event("find my doc"), Scheduler())
    message = response["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]
    assert message["cardsV2"][0]["cardId"] == "auth"


async def test_addon_authorized_user_acks_empty_and_schedules(monkeypatch, token_service):
    from gemini_act.oauth.store import StoredToken

    await token_service.store.put("users/123", StoredToken(refresh_token="r", scopes=["s"]))
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    scheduler = Scheduler()

    response = await events.handle_event(addon_message_event("do a thing"), scheduler)

    assert response == {}, "ack must be a bare empty body, not a wrapped empty message"
    assert len(scheduler.calls) == 1
