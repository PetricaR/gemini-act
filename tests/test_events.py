"""Event parsing and routing."""

from __future__ import annotations

import json

import pytest

from gemini_act.chat import events, live_reply
from gemini_act.config import Settings
from gemini_act.oauth.store import StoredToken, TokenService


def message_event(
    text: str = "hello",
    *,
    command_id: str = "",
    thread: str = "t1",
    space_type: str = "DM",
    attachment: list[dict] | None = None,
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
    if attachment is not None:
        message["attachment"] = attachment
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


def _attachment(name: str = "photo.png") -> dict:
    return {
        "contentName": name,
        "contentType": "image/png",
        "source": "UPLOADED_CONTENT",
        "attachmentDataRef": {"resourceName": "spaces/AAA/messages/BBB/attachments/CCC"},
    }


def test_parse_event_extracts_attachments():
    ctx = events.parse_event(message_event("check this out", attachment=[_attachment()]))
    assert ctx.attachments == (_attachment(),)


def test_parse_event_defaults_to_no_attachments():
    assert events.parse_event(message_event("hello")).attachments == ()


def card_clicked_event(invoked_function: str = "", parameters: dict | None = None) -> dict:
    """A button rendered from an A2UI payload (see chat/a2ui.py) being clicked —
    the classic Chat app shape, `Event.common`, per Google's own reference."""
    event = {
        "type": "CARD_CLICKED",
        "user": {"name": "users/123", "displayName": "Ada"},
        "space": {"name": "spaces/AAA", "type": "DM"},
        "message": {
            "name": "spaces/AAA/messages/BBB",
            "space": {"name": "spaces/AAA", "type": "DM"},
        },
    }
    if invoked_function:
        event["common"] = {"invokedFunction": invoked_function, "parameters": parameters or {}}
    return event


def test_parse_event_synthesizes_text_from_a_card_click():
    ctx = events.parse_event(card_clicked_event("confirm_delete", {"event_id": "abc"}))
    assert ctx.command is None
    assert "confirm_delete" in ctx.text
    assert "event_id=abc" in ctx.text


def test_a_typed_message_is_never_overridden_by_a_stray_common_field():
    """A click's synthesized text must only ever fill in for a genuinely empty
    message — never shadow real text the user typed."""
    event = message_event("what's on my calendar")
    event["common"] = {"invokedFunction": "should_be_ignored"}
    assert events.parse_event(event).text == "what's on my calendar"


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


async def test_a_card_click_reaches_the_agent_like_an_ordinary_message(authorized, monkeypatch):
    await authorized()
    scheduler = Scheduler()

    response = await events.handle_event(
        card_clicked_event("confirm_delete", {"event_id": "abc"}), scheduler
    )

    assert response == {}
    fn, (ctx,) = scheduler.calls[0]
    assert fn is events.run_and_reply
    assert "confirm_delete" in ctx.text


async def test_a_card_click_with_no_function_asks_for_something(token_service, monkeypatch):
    """Defensive fallback: a click that carried no usable data degrades like
    any other empty message, rather than running the agent on nothing."""
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    response = await events.handle_event(card_clicked_event(), Scheduler())
    assert "Say something" in response["text"]


async def test_an_attachment_only_message_still_reaches_the_agent(authorized, monkeypatch):
    """A bare file with no caption is a real request, not nothing to do."""
    await authorized()
    scheduler = Scheduler()

    response = await events.handle_event(message_event("", attachment=[_attachment()]), scheduler)

    assert response == {}
    assert scheduler.calls and scheduler.calls[0][0] is events.run_and_reply


async def test_a_truly_empty_message_asks_for_something(token_service, monkeypatch):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    response = await events.handle_event(message_event(""), Scheduler())
    assert "Say something" in response["text"]


async def test_an_attachment_only_message_asks_for_something_when_the_feature_is_off(
    token_service, monkeypatch
):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    monkeypatch.setattr(events, "get_settings", lambda: Settings(chat_attachments_enabled=False))

    response = await events.handle_event(message_event("", attachment=[_attachment()]), Scheduler())

    assert "Say something" in response["text"]


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


class RecordingChatClient:
    """Behaves like the real client: a post gets a name, and a name can be
    rewritten. Replies stream, so what the user ends up looking at is usually
    the last rewrite rather than the last post — hence `delivered`."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.updates: list[dict] = []

    async def post_message(self, space, body, thread_name=None, thread_key=None):
        name = f"{space}/messages/m{len(self.posts) + 1}"
        self.posts.append(
            {
                "space": space,
                "body": body,
                "thread_name": thread_name,
                "thread_key": thread_key,
                "name": name,
            }
        )
        return {"name": name, "thread": {"name": thread_name or f"{space}/threads/auto"}}

    async def update_message(self, name, body):
        self.updates.append({"name": name, "body": body})
        return {"name": name}

    @property
    def delivered(self) -> dict:
        """The message body the user is left looking at."""
        return self.updates[-1]["body"] if self.updates else self.posts[-1]["body"]


def _recording_client(monkeypatch) -> RecordingChatClient:
    client = RecordingChatClient()
    monkeypatch.setattr(events, "get_chat_client", lambda: client)
    return client


def _reply_settings(monkeypatch, *, in_thread: bool = False, streaming: bool = True) -> None:
    monkeypatch.setattr(
        events,
        "get_settings",
        lambda: Settings(
            chat_reply_in_thread=in_thread,
            chat_streaming_enabled=streaming,
            # Every push must reach the fake, otherwise a test asserting on the
            # stream would be racing a wall-clock throttle.
            chat_stream_interval_seconds=0.0,
        ),
        raising=True,
    )


async def _fake_answer(user_id, session_id, message, on_progress=None, attachments=None):
    return "Your next meeting is at 3pm."


@pytest.mark.parametrize("space_type", ["DM", "SPACE"])
async def test_run_and_reply_posts_flat_by_default(monkeypatch, space_type):
    """The answer belongs in the main window next to the question. Threading it
    made Chat collapse every exchange into a bubble the user had to expand."""
    _reply_settings(monkeypatch, in_thread=False)
    client = _recording_client(monkeypatch)
    monkeypatch.setattr(events, "run_agent", _fake_answer)

    ctx = events.parse_event(message_event("when's my next meeting", space_type=space_type))
    await events.run_and_reply(ctx)

    assert client.posts[0]["space"] == "spaces/AAA"
    assert client.posts[0]["thread_name"] is None
    assert client.posts[0]["thread_key"] is None
    assert client.delivered["text"] == "Your next meeting is at 3pm."


async def test_run_and_reply_in_thread_mode_uses_stable_key_in_dm(monkeypatch):
    """Opt-in threading: a DM's incoming thread is fresh per message, so keying
    on it would fragment the conversation into one bubble per exchange."""
    _reply_settings(monkeypatch, in_thread=True)
    client = _recording_client(monkeypatch)
    monkeypatch.setattr(events, "run_agent", _fake_answer)

    ctx = events.parse_event(message_event("when's my next meeting", space_type="DM"))
    await events.run_and_reply(ctx)

    assert client.posts[0]["thread_key"] == "dm-AAA"
    assert client.posts[0]["thread_name"] is None


async def test_run_and_reply_in_thread_mode_uses_incoming_thread_in_space(monkeypatch):
    _reply_settings(monkeypatch, in_thread=True)
    client = _recording_client(monkeypatch)
    monkeypatch.setattr(events, "run_agent", _fake_answer)

    ctx = events.parse_event(message_event("when's my next meeting", space_type="SPACE"))
    await events.run_and_reply(ctx)

    assert client.posts[0]["thread_name"] == "spaces/AAA/threads/t1"
    assert client.posts[0]["thread_key"] is None


async def test_run_and_reply_reports_timeout_instead_of_failing_silently(monkeypatch):
    _reply_settings(monkeypatch)
    client = _recording_client(monkeypatch)

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        raise TimeoutError

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert client.delivered["cardsV2"][0]["cardId"] == "error"


async def test_run_and_reply_reports_agent_error(monkeypatch):
    _reply_settings(monkeypatch)
    client = _recording_client(monkeypatch)

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert client.delivered["cardsV2"][0]["cardId"] == "error"


# --- attachments riding along with a run ---


async def test_run_and_reply_forwards_resolved_attachment_parts(monkeypatch):
    from google.genai import types

    _reply_settings(monkeypatch)
    _recording_client(monkeypatch)
    resolved_part = types.Part(text="Attached file: photo.png (image/png)")

    async def fake_resolve(raw, **kwargs):
        assert raw == [_attachment()]
        return [resolved_part], []

    monkeypatch.setattr(events, "resolve_attachments", fake_resolve)

    seen: dict = {}

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        seen["attachments"] = attachments
        return "nice photo"

    monkeypatch.setattr(events, "run_agent", fake_run)

    ctx = events.parse_event(message_event("look at this", attachment=[_attachment()]))
    await events.run_and_reply(ctx)

    assert seen["attachments"] == [resolved_part]


async def test_run_and_reply_turns_notes_into_extra_text_parts(monkeypatch):
    _reply_settings(monkeypatch)
    _recording_client(monkeypatch)

    async def fake_resolve(raw, **kwargs):
        return [], ["photo.png: too large to include (20.0 MB)."]

    monkeypatch.setattr(events, "resolve_attachments", fake_resolve)

    seen: dict = {}

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        seen["attachments"] = attachments
        return "ok"

    monkeypatch.setattr(events, "run_agent", fake_run)

    ctx = events.parse_event(message_event("look at this", attachment=[_attachment()]))
    await events.run_and_reply(ctx)

    assert len(seen["attachments"]) == 1
    assert seen["attachments"][0].text == (
        "[Attachment note] photo.png: too large to include (20.0 MB)."
    )


async def test_run_and_reply_skips_resolution_without_attachments(monkeypatch):
    _reply_settings(monkeypatch)
    _recording_client(monkeypatch)

    async def fail_resolve(raw, **kwargs):
        raise AssertionError("must not resolve attachments that were never sent")

    monkeypatch.setattr(events, "resolve_attachments", fail_resolve)

    seen: dict = {}

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        seen["attachments"] = attachments
        return "ok"

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event("hello")))

    assert seen["attachments"] == []


# --- rendering an A2UI payload the model attached to its answer ---


def _a2ui_answer(spoken: str, components: list[dict]) -> str:
    import json

    from gemini_act.chat.a2ui import MARKER

    return f"{spoken}\n\n{MARKER}\n{json.dumps({'components': components})}"


async def test_run_and_reply_renders_an_a2ui_payload_into_a_card(monkeypatch):
    _reply_settings(monkeypatch)
    client = _recording_client(monkeypatch)
    answer = _a2ui_answer(
        "Here's what I found.",
        [{"id": "root", "component": "Text", "text": "Q3 report"}],
    )

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        return answer

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event("show me the report")))

    delivered = client.delivered
    assert delivered["text"] == "Here's what I found."
    assert delivered["cardsV2"][0]["card"]["sections"][0]["widgets"] == [
        {"textParagraph": {"text": "Q3 report"}}
    ]


async def test_run_and_reply_falls_back_to_plain_text_on_malformed_a2ui(monkeypatch):
    """A broken attempt at rich UI must never leak the raw JSON into the chat."""
    _reply_settings(monkeypatch)
    client = _recording_client(monkeypatch)
    from gemini_act.chat.a2ui import MARKER

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        return f"Here's what I found.\n\n{MARKER}\n{{not valid json"

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event("show me the report")))

    delivered = client.delivered
    assert delivered["text"] == "Here's what I found."
    assert "cardsV2" not in delivered
    assert "not valid json" not in str(delivered)


async def test_a2ui_rendering_can_be_turned_off(monkeypatch):
    client = _recording_client(monkeypatch)
    monkeypatch.setattr(
        events,
        "get_settings",
        lambda: Settings(chat_a2ui_enabled=False, chat_stream_interval_seconds=0.0),
    )
    components = [{"id": "root", "component": "Text", "text": "x"}]
    answer = _a2ui_answer("Here's what I found.", components)

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        return answer

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event("show me the report")))

    delivered = client.delivered
    assert delivered["text"] == "Here's what I found."
    assert "cardsV2" not in delivered


# --- streaming the reply ---


async def test_a_placeholder_goes_up_before_the_agent_has_written_anything(monkeypatch):
    """The whole point: the user sees something the moment they ask, instead of
    waiting out a multi-tool turn in silence."""
    _reply_settings(monkeypatch)
    client = _recording_client(monkeypatch)

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        assert client.posts, "the placeholder must already be up when the agent starts"
        return "done"

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert client.posts[0]["body"]["text"] == live_reply.PLACEHOLDER
    assert len(client.posts) == 1, "the answer rewrites the placeholder, not a second message"
    assert client.delivered["text"] == "done"


async def test_the_answer_is_rewritten_as_it_is_written(monkeypatch):
    _reply_settings(monkeypatch)
    client = _recording_client(monkeypatch)

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        await on_progress("Your next")
        await on_progress("Your next meeting")
        return "Your next meeting is at 3pm."

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    streamed = [update["body"]["text"] for update in client.updates]
    assert streamed[0].startswith("Your next")
    assert all(text.endswith(live_reply.CURSOR) for text in streamed[:-1])
    assert streamed[-1] == "Your next meeting is at 3pm.", "the caret is gone once it is done"


async def test_an_error_card_clears_the_half_written_text(monkeypatch):
    """Without the empty text the abandoned sentence stays above the card."""
    _reply_settings(monkeypatch)
    client = _recording_client(monkeypatch)

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        await on_progress("Let me check tha")
        raise RuntimeError("model exploded")

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert client.delivered["text"] == ""
    assert client.delivered["cardsV2"][0]["cardId"] == "error"


async def test_streaming_off_delivers_one_message_at_the_end(monkeypatch):
    _reply_settings(monkeypatch, streaming=False)
    client = _recording_client(monkeypatch)

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        assert on_progress is None, "nothing to stream into, so do not stream"
        return "Your next meeting is at 3pm."

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert client.updates == []
    assert client.posts[0]["body"]["text"] == "Your next meeting is at 3pm."


async def test_a_placeholder_that_cannot_be_posted_falls_back_to_the_old_behaviour(monkeypatch):
    """Chat being unavailable for the placeholder must not cost the answer."""
    _reply_settings(monkeypatch)
    posted: list[dict] = []

    class HalfBrokenClient(RecordingChatClient):
        async def post_message(self, space, body, thread_name=None, thread_key=None):
            if body.get("text") == live_reply.PLACEHOLDER:
                raise RuntimeError("Chat is having a moment")
            posted.append(body)
            return await super().post_message(space, body, thread_name, thread_key)

    monkeypatch.setattr(events, "get_chat_client", lambda: HalfBrokenClient())

    async def fake_run(user_id, session_id, message, on_progress=None, attachments=None):
        assert on_progress is None, "there is no live message to push into"
        return "Your next meeting is at 3pm."

    monkeypatch.setattr(events, "run_agent", fake_run)

    await events.run_and_reply(events.parse_event(message_event()))

    assert posted == [{"text": "Your next meeting is at 3pm."}]


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


# --- MCP servers the user connects themselves ---


@pytest.fixture
def registry(monkeypatch):
    """An empty per-user MCP registry wired into the event handlers."""
    from gemini_act.config import Settings
    from gemini_act.mcp.store import InMemoryMcpServerStore, McpRegistry

    registry = McpRegistry(InMemoryMcpServerStore(), Settings(token_store="memory"))
    monkeypatch.setattr(events, "get_mcp_registry", lambda: registry)
    return registry


def _spec(name: str = "acme"):
    from gemini_act.mcp.spec import McpServerSpec

    return McpServerSpec(name=name, url=f"https://{name}.example.com/mcp")


async def test_pasted_server_url_is_connected_not_sent_to_the_model(
    registry, token_service, monkeypatch
):
    """The whole point: paste a server, get a server — no /mcp add required."""
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    scheduler = Scheduler()

    response = await events.handle_event(message_event("https://mcp.acme.com/mcp"), scheduler)

    assert response == {}
    fn, (ctx, text) = scheduler.calls[0]
    assert fn is events.connect_mcp_and_reply
    assert text == "https://mcp.acme.com/mcp"


async def test_connecting_a_server_does_not_require_google_consent(
    registry, token_service, monkeypatch
):
    """A pasted server brings its own credentials; the auth card would be noise."""
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    scheduler = Scheduler()

    response = await events.handle_event(message_event("https://mcp.acme.com/mcp"), scheduler)

    assert response == {}, "an auth card here would block a flow that needs no auth"
    assert scheduler.calls


async def test_an_ordinary_question_still_reaches_the_agent(authorized, registry):
    await authorized()
    scheduler = Scheduler()

    await events.handle_event(message_event("summarise https://example.com/post"), scheduler)

    assert scheduler.calls[0][0] is events.run_and_reply


async def test_mcp_list_shows_connected_servers(registry, token_service, monkeypatch):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    await registry.add("users/123", _spec("acme"))

    response = await events.handle_event(message_event("/mcp", command_id="6"), Scheduler())

    text = response["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"]
    assert "acme" in text


async def test_mcp_list_is_empty_for_a_new_user(registry, token_service, monkeypatch):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    response = await events.handle_event(message_event("/mcp list", command_id="6"), Scheduler())
    assert "No MCP servers" in response["cardsV2"][0]["card"]["header"]["subtitle"]


async def test_mcp_add_schedules_a_connection(registry, token_service, monkeypatch):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    scheduler = Scheduler()

    response = await events.handle_event(
        message_event("/mcp add https://acme.example.com/mcp", command_id="6"), scheduler
    )

    assert response == {}
    fn, (_, text) = scheduler.calls[0]
    assert fn is events.connect_mcp_and_reply
    assert text == "https://acme.example.com/mcp"


async def test_mcp_add_works_when_chat_has_not_stripped_the_command(
    registry, token_service, monkeypatch
):
    """An unregistered slash command arrives with '/mcp' still in argumentText."""
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    scheduler = Scheduler()

    await events.handle_event(message_event("/mcp add https://acme.example.com/mcp"), scheduler)

    _, (_, text) = scheduler.calls[0]
    assert text == "https://acme.example.com/mcp"


async def test_mcp_remove_forgets_the_server(registry, token_service, monkeypatch):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    await registry.add("users/123", _spec("acme"))

    response = await events.handle_event(
        message_event("/mcp remove acme", command_id="6"), Scheduler()
    )

    assert "Disconnected" in response["text"]
    assert await registry.list("users/123") == []


async def test_mcp_remove_says_so_when_there_is_nothing_to_remove(
    registry, token_service, monkeypatch
):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    response = await events.handle_event(
        message_event("/mcp remove ghost", command_id="6"), Scheduler()
    )
    assert "don't have a server called" in response["text"]


async def test_mcp_with_an_unknown_subcommand_shows_usage(registry, token_service, monkeypatch):
    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    response = await events.handle_event(message_event("/mcp wibble", command_id="6"), Scheduler())
    text = response["cardsV2"][0]["card"]["sections"][0]["widgets"][0]["textParagraph"]["text"]
    assert "/mcp add" in text


async def test_mcp_can_be_turned_off_for_a_deployment(registry, token_service, monkeypatch):
    """With the feature off, a pasted URL is just a message again."""
    from gemini_act.config import Settings

    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    monkeypatch.setattr(events, "get_settings", lambda: Settings(custom_mcp_enabled=False))
    scheduler = Scheduler()

    response = await events.handle_event(message_event("https://mcp.acme.com/mcp"), scheduler)

    assert not scheduler.calls
    assert response["cardsV2"][0]["cardId"] == "auth", "handled as an ordinary message"


async def test_mcp_command_is_refused_when_turned_off(registry, token_service, monkeypatch):
    from gemini_act.config import Settings

    monkeypatch.setattr(events, "get_token_service", lambda: token_service)
    monkeypatch.setattr(events, "get_settings", lambda: Settings(custom_mcp_enabled=False))

    response = await events.handle_event(message_event("/mcp", command_id="6"), Scheduler())

    assert "turned off" in response["text"]


def _mcp_card_text(body: dict) -> str:
    widgets = body["cardsV2"][0]["card"]["sections"][0]["widgets"]
    return " ".join(widget["textParagraph"]["text"] for widget in widgets)


@pytest.fixture
def posted_replies(monkeypatch) -> RecordingChatClient:
    """Capture what the async MCP flow shows the user.

    Connecting streams too — probing is a live round trip per server — so the
    result card usually lands as a rewrite of the "Connecting…" placeholder
    rather than as a fresh post. `delivered` papers over which one it was.
    """
    return _recording_client(monkeypatch)


async def test_connecting_probes_before_saving(registry, posted_replies, monkeypatch):
    """A server is only stored once it has actually answered."""
    probed: list[str] = []

    async def fake_probe(spec, settings):
        probed.append(spec.url)
        return ["search", "fetch"]

    monkeypatch.setattr(events, "probe_server", fake_probe)
    ctx = events.parse_event(message_event("https://mcp.acme.com/mcp"))

    await events.connect_mcp_and_reply(ctx, "https://mcp.acme.com/mcp")

    assert probed == ["https://mcp.acme.com/mcp"]
    assert [spec.name for spec in await registry.list("users/123")] == ["acme"]
    assert "2 tool(s)" in _mcp_card_text(posted_replies.delivered)


async def test_a_server_that_will_not_connect_is_not_saved(registry, posted_replies, monkeypatch):
    """Storing it would turn one visible failure into a silent one every turn."""

    async def fake_probe(spec, settings):
        raise ConnectionError("Failed to create MCP session")

    monkeypatch.setattr(events, "probe_server", fake_probe)
    ctx = events.parse_event(message_event("https://mcp.acme.com/mcp"))

    await events.connect_mcp_and_reply(ctx, "https://mcp.acme.com/mcp")

    assert await registry.list("users/123") == []
    assert "Failed to create MCP session" in _mcp_card_text(posted_replies.delivered)


async def test_a_timeout_is_reported_as_a_timeout(registry, posted_replies, monkeypatch):
    async def fake_probe(spec, settings):
        raise TimeoutError

    monkeypatch.setattr(events, "probe_server", fake_probe)
    ctx = events.parse_event(message_event("https://mcp.acme.com/mcp"))

    await events.connect_mcp_and_reply(ctx, "https://mcp.acme.com/mcp")

    assert await registry.list("users/123") == []
    assert "answer within" in _mcp_card_text(posted_replies.delivered)


async def test_a_server_with_no_tools_is_not_saved(registry, posted_replies, monkeypatch):
    async def fake_probe(spec, settings):
        return []

    monkeypatch.setattr(events, "probe_server", fake_probe)
    ctx = events.parse_event(message_event("https://mcp.acme.com/mcp"))

    await events.connect_mcp_and_reply(ctx, "https://mcp.acme.com/mcp")

    assert await registry.list("users/123") == []
    assert "no tools" in _mcp_card_text(posted_replies.delivered)


async def test_unparseable_paste_explains_itself_without_probing(
    registry, posted_replies, monkeypatch
):
    async def fail(spec, settings):
        raise AssertionError("must not probe something we could not parse")

    monkeypatch.setattr(events, "probe_server", fail)
    ctx = events.parse_event(message_event("hello"))

    await events.connect_mcp_and_reply(ctx, '{"mcpServers": {"x": {"command": "npx"}}}')

    assert posted_replies.delivered["cardsV2"][0]["cardId"] == "error"
    assert "stdio" in _mcp_card_text(posted_replies.delivered)


async def test_a_multi_server_config_reports_each_one(registry, posted_replies, monkeypatch):
    async def fake_probe(spec, settings):
        if spec.name == "broken":
            raise ConnectionError("nope")
        return ["search"]

    monkeypatch.setattr(events, "probe_server", fake_probe)
    config = json.dumps(
        {
            "mcpServers": {
                "good": {"url": "https://good.example.com/mcp"},
                "broken": {"url": "https://broken.example.com/mcp"},
            }
        }
    )
    ctx = events.parse_event(message_event(config))

    await events.connect_mcp_and_reply(ctx, config)

    assert [spec.name for spec in await registry.list("users/123")] == ["good"]
    text = _mcp_card_text(posted_replies.delivered)
    assert "good" in text and "broken" in text


def test_a_repeated_error_prefix_is_said_once():
    """ADK wraps its own message, so the raw text arrives doubled."""
    exc = ConnectionError(
        "Failed to create MCP session: Failed to create MCP session: nodename not known"
    )
    assert events._short_reason(exc) == "Failed to create MCP session: nodename not known"


def test_a_long_error_is_truncated_for_the_card():
    assert len(events._short_reason(RuntimeError("x" * 5000))) <= events._MAX_ERROR_LENGTH + 1
