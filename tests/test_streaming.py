"""Streaming a reply: how ADK's partial events become a message being written."""

from __future__ import annotations

import pytest
from google.adk.agents.run_config import StreamingMode
from google.adk.events.event import Event
from google.genai import types

from gemini_act import runner as runner_module
from gemini_act.chat.live_reply import CURSOR, MAX_TEXT, PLACEHOLDER, LiveReply
from gemini_act.config import Settings


def _event(
    text: str,
    *,
    partial: bool = False,
    thought: str = "",
    grounding_metadata: types.GroundingMetadata | None = None,
) -> Event:
    parts = [types.Part(text=thought, thought=True)] if thought else []
    parts.append(types.Part(text=text))
    return Event(
        author="gemini_act",
        content=types.Content(role="model", parts=parts),
        partial=partial,
        grounding_metadata=grounding_metadata,
    )


def _grounding(*sources: tuple[str, str]) -> types.GroundingMetadata:
    """`sources` is (uri, title) pairs, matching what Google Search grounding returns."""
    return types.GroundingMetadata(
        grounding_chunks=[
            types.GroundingChunk(web=types.GroundingChunkWeb(uri=uri, title=title))
            for uri, title in sources
        ]
    )


class FakeRunner:
    """Replays a canned event stream and records the RunConfig it was given."""

    def __init__(self, events: list[Event]) -> None:
        self._events = events
        self.run_config = None
        self.new_message = None

    async def run_async(self, *, user_id, session_id, new_message, run_config=None):
        self.run_config = run_config
        self.new_message = new_message
        for event in self._events:
            yield event


@pytest.fixture
def fake_runner(monkeypatch):
    """Installs a canned event stream in place of the real ADK runner."""

    def install(events: list[Event]) -> FakeRunner:
        fake = FakeRunner(events)
        monkeypatch.setattr(runner_module, "get_runner", lambda: fake)
        monkeypatch.setattr(runner_module, "get_settings", lambda: Settings(token_store="memory"))
        return fake

    return install


@pytest.fixture
def streamed(fake_runner):
    """Run an event stream and return `(progress texts, final answer)`."""

    async def run(events: list[Event]) -> tuple[list[str], str]:
        fake_runner(events)
        seen: list[str] = []

        async def on_progress(text: str) -> None:
            seen.append(text)

        answer = await runner_module.run_agent("users/1", "s", "hi", on_progress=on_progress)
        return seen, answer

    return run


# --- runner ---


async def test_partial_events_accumulate_into_the_progress_callback(streamed):
    """ADK sends deltas while streaming, so each one has to be appended — a
    callback given the raw event text would show only the last few characters."""
    seen, result = await streamed(
        [
            _event("Your ", partial=True),
            _event("next meeting ", partial=True),
            _event("is at 3pm.", partial=True),
            _event("Your next meeting is at 3pm."),
        ]
    )

    assert seen[:3] == ["Your ", "Your next meeting ", "Your next meeting is at 3pm."]
    assert result == "Your next meeting is at 3pm."


async def test_the_aggregated_event_does_not_double_the_streamed_text(streamed):
    """ADK closes a streamed response by repeating the whole thing; appending
    that to the buffer would show the answer twice."""
    seen, _ = await streamed([_event("half ", partial=True), _event("half whole")])

    assert seen[-1] == "half whole"


async def test_a_turn_with_a_tool_call_shows_each_response_then_keeps_the_last(streamed):
    """The model's remark before a tool call is worth showing while the tool
    runs, but the answer that follows must replace it, not append to it."""
    seen, result = await streamed(
        [
            _event("Let me check ", partial=True),
            _event("Let me check your calendar."),
            _event("Nothing ", partial=True),
            _event("until 3pm.", partial=True),
            _event("Nothing until 3pm."),
        ]
    )

    assert "Nothing until 3pm." in seen
    assert not any(text.startswith("Let me check your calendar.Nothing") for text in seen)
    assert result == "Nothing until 3pm."


async def test_the_models_reasoning_is_never_posted_into_the_space(streamed):
    """A thought part is the model thinking aloud. Nothing here asks for thought
    summaries, but this text goes straight into a Chat space."""
    seen, result = await streamed(
        [
            _event("The answer ", partial=True, thought="the user probably means..."),
            _event("The answer is 42.", thought="settled on 42"),
        ]
    )

    assert "probably means" not in " ".join(seen)
    assert result == "The answer is 42."


async def test_search_grounded_answers_list_their_sources(streamed):
    """Google's Grounding with Google Search terms require showing where a
    grounded answer came from; Chat can't render the HTML widget Google's own
    docs point to for that, so this has to become Chat's own link syntax."""
    seen, result = await streamed(
        [
            _event(
                "Paris is the capital of France.",
                grounding_metadata=_grounding(("https://example.com/paris", "Paris — Example")),
            )
        ]
    )

    assert result == (
        "Paris is the capital of France.\n\nSources:\n- <https://example.com/paris|Paris — Example>"
    )
    assert seen[-1] == result, (
        "the streamed update must carry the sources too, not just the final return"
    )


async def test_grounding_sources_are_deduplicated_and_capped(streamed):
    sources = [(f"https://example.com/{i}", f"Source {i}") for i in range(8)]
    sources.append(sources[0])  # a repeat, as real grounding responses do
    _, result = await streamed([_event("answer", grounding_metadata=_grounding(*sources))])

    listed = [line for line in result.splitlines() if line.startswith("- <")]
    assert len(listed) == runner_module.MAX_CITATIONS
    assert len(set(listed)) == len(listed), "no source should be listed twice"


async def test_a_source_without_a_title_falls_back_to_its_url(streamed):
    _, result = await streamed(
        [_event("answer", grounding_metadata=_grounding(("https://example.com/x", "")))]
    )
    assert "<https://example.com/x|https://example.com/x>" in result


async def test_an_ungrounded_answer_has_no_sources_section(streamed):
    _, result = await streamed([_event("just an answer, no search involved")])
    assert "Sources:" not in result


async def test_streaming_is_only_requested_when_someone_is_listening(fake_runner):
    """SSE costs nothing here, but asking for it with no callback would mean
    paying for partial events that are then thrown away."""
    fake = fake_runner([_event("done")])
    await runner_module.run_agent("users/1", "s", "hi")
    assert fake.run_config.streaming_mode is StreamingMode.NONE

    fake = fake_runner([_event("done")])

    async def on_progress(text: str) -> None:
        pass

    await runner_module.run_agent("users/1", "s", "hi", on_progress=on_progress)
    assert fake.run_config.streaming_mode is StreamingMode.SSE


async def test_a_turn_that_produced_no_text_still_says_something(fake_runner):
    fake_runner([])
    assert await runner_module.run_agent("users/1", "s", "hi") == (
        "I finished, but produced no text to show."
    )


# --- attachments riding along with the turn ---


async def test_attachments_are_appended_after_the_text_part(fake_runner):
    fake = fake_runner([_event("done")])
    extra = types.Part.from_bytes(data=b"\x89PNG", mime_type="image/png")

    await runner_module.run_agent("users/1", "s", "hi", attachments=[extra])

    assert fake.new_message.parts[0].text == "hi"
    assert fake.new_message.parts[1] is extra


async def test_an_attachment_only_message_needs_no_text_part(fake_runner):
    """A Chat message can be a bare file with no caption; the turn must still
    reach the model as something, not an empty parts list."""
    fake = fake_runner([_event("done")])
    note = types.Part(text="[Attachment note] report.docx: this file type can't be read directly.")

    await runner_module.run_agent("users/1", "s", "", attachments=[note])

    assert fake.new_message.parts == [note]


async def test_no_message_and_no_attachments_still_produces_a_content_part(fake_runner):
    fake = fake_runner([_event("done")])
    await runner_module.run_agent("users/1", "s", "")
    assert fake.new_message.parts == [types.Part(text="")]


# --- LiveReply ---


class FakeChat:
    def __init__(self, *, name: str | None = "spaces/AAA/messages/m1") -> None:
        self._name = name
        self.posts: list[dict] = []
        self.updates: list[dict] = []
        self.deleted: list[str] = []

    async def post_message(self, space, body, thread_name=None, thread_key=None):
        self.posts.append(body)
        return {"name": self._name} if self._name else {}

    async def update_message(self, name, body):
        self.updates.append(body)
        return {"name": name}

    async def delete_message(self, name, *, access_token=None):
        self.deleted.append(name)


async def test_updates_are_throttled_to_protect_the_write_quota():
    """Every rewrite is a Chat API write against the space's quota, so a fast
    token stream must not turn into a rewrite per token."""
    chat = FakeChat()
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=3600)
    await reply.start()

    await reply.push("one")
    await reply.push("one two")

    assert chat.updates == [], "both fall inside the interval"
    await reply.finish({"text": "one two three"})
    assert chat.updates == [{"text": "one two three"}], "finish ignores the interval"


async def test_the_placeholder_is_replaced_not_appended_to():
    chat = FakeChat()
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=0)
    await reply.start()

    assert chat.posts == [{"text": PLACEHOLDER}]
    await reply.push("writing")
    assert chat.updates[-1] == {"text": "writing" + CURSOR}


async def test_without_a_message_name_nothing_is_pushed():
    """A Chat response with no name leaves nothing to rewrite; pushing anyway
    would raise on every token."""
    chat = FakeChat(name=None)
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=0)
    await reply.start()

    assert reply.is_live is False
    await reply.push("writing")
    assert chat.updates == []


async def test_a_long_answer_is_trimmed_to_what_chat_accepts():
    """Chat rejects a body over 4096 characters outright, so an over-long answer
    has to arrive trimmed rather than not at all."""
    chat = FakeChat()
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=0)
    await reply.start()

    await reply.finish({"text": "x" * (MAX_TEXT * 2)})

    text = chat.updates[-1]["text"]
    assert len(text) <= MAX_TEXT
    assert text.endswith("_(truncated)_")


async def test_a_failed_rewrite_falls_back_to_a_fresh_message():
    """Losing the answer because the placeholder became unreachable would be
    worse than an orphaned placeholder."""

    class BrokenUpdates(FakeChat):
        async def update_message(self, name, body):
            raise RuntimeError("message is gone")

    chat = BrokenUpdates()
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=0)
    await reply.start()

    await reply.finish({"text": "the answer"})

    assert chat.posts[-1] == {"text": "the answer"}


async def test_finish_posts_once_when_the_reply_never_started():
    chat = FakeChat()
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=0)

    await reply.finish({"text": "the answer"})

    assert chat.posts == [{"text": "the answer"}]
    assert chat.updates == []


# --- the Chat update call itself ---


def test_the_update_mask_names_proto_fields_not_json_ones():
    """The body says `cardsV2`; the mask has to say `cards_v2`, or Chat 400s
    halfway through a streamed reply."""
    from gemini_act.chat.client import _UPDATE_MASK_PATHS

    assert _UPDATE_MASK_PATHS["cardsV2"] == "cards_v2"
    assert _UPDATE_MASK_PATHS["text"] == "text"


def test_every_body_live_reply_sends_is_patchable():
    """LiveReply only ever sends text and cards; both must be updatable."""
    from gemini_act.chat.client import _UPDATE_MASK_PATHS

    assert {"text", "cardsV2"} <= set(_UPDATE_MASK_PATHS)


async def test_a_push_that_arrives_after_finish_is_ignored():
    """The turn is settled; a straggling rewrite would put half the answer back."""
    chat = FakeChat()
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=0)
    await reply.start()

    await reply.finish({"text": "the whole answer"})
    await reply.push("the wh")

    assert [update["text"] for update in chat.updates] == ["the whole answer"]


async def test_an_unreachable_message_does_not_leave_a_thinking_placeholder():
    """Posting the answer as a new message is the fallback; leaving a "Thinking…"
    that never resolves next to it is not."""

    class BrokenUpdates(FakeChat):
        async def update_message(self, name, body):
            raise RuntimeError("message is gone")

    chat = BrokenUpdates()
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=0)
    await reply.start()

    await reply.finish({"text": "the answer"})

    assert chat.deleted == ["spaces/AAA/messages/m1"]
    assert chat.posts[-1] == {"text": "the answer"}


async def test_rewrites_do_not_overtake_each_other():
    """A slow rewrite must not be passed by the next one, which would leave the
    message showing older text than it already did."""
    import asyncio

    order: list[str] = []

    class SlowFirstUpdate(FakeChat):
        async def update_message(self, name, body):
            text = body["text"]
            order.append(f"start {text}")
            await asyncio.sleep(0.02 if "first" in text else 0)
            order.append(f"end {text}")
            return await super().update_message(name, body)

    chat = SlowFirstUpdate()
    reply = LiveReply(chat, "spaces/AAA", interval_seconds=0)
    await reply.start()

    await asyncio.gather(reply.push("first"), reply.push("second"))

    assert order.index("end first" + CURSOR) < order.index("start second" + CURSOR)
