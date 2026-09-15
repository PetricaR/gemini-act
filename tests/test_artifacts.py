"""The side-channel that keeps tool-produced files out of the conversation."""

from __future__ import annotations

import time

import pytest

from gemini_act.chat.reply_attachment import parse_reply_attachment
from imobiliare import artifacts


@pytest.fixture(autouse=True)
def _clean_store():
    """Each test gets an empty store: it is module-level process state."""
    artifacts._store.clear()
    yield
    artifacts._store.clear()


def test_put_returns_a_token_that_resolves_to_the_bytes():
    token = artifacts.put("evaluare-1.md", "text/markdown", b"# raport")
    stored = artifacts.take(token)
    assert stored is not None
    assert (stored.filename, stored.mime_type, stored.data) == (
        "evaluare-1.md",
        "text/markdown",
        b"# raport",
    )


def test_take_consumes_so_a_report_is_never_sent_twice():
    """A model repeating a token from an earlier turn must miss, not re-send a
    report the user already has."""
    token = artifacts.put("r.md", "text/markdown", b"x")
    assert artifacts.take(token) is not None
    assert artifacts.take(token) is None


def test_peek_does_not_consume():
    token = artifacts.put("r.md", "text/markdown", b"x")
    assert artifacts.peek(token) is not None
    assert artifacts.peek(token) is not None
    assert artifacts.take(token) is not None


def test_unknown_token_resolves_to_nothing():
    assert artifacts.take("art_nonexistent") is None


def test_expired_entries_are_dropped():
    token = artifacts.put("r.md", "text/markdown", b"x")
    entry = artifacts._store[token]
    artifacts._store[token] = type(entry)(
        entry.filename, entry.mime_type, entry.data, time.time() - artifacts.TTL_SECONDS - 1
    )
    # Eviction runs on write, so any later put sweeps the expired entry.
    artifacts.put("other.md", "text/markdown", b"y")
    assert artifacts.take(token) is None


def test_store_is_bounded():
    """A runaway loop must not be able to exhaust the instance."""
    tokens = [
        artifacts.put(f"r{i}.md", "text/markdown", b"x")
        for i in range(artifacts.MAX_ENTRIES + 10)
    ]
    assert len(artifacts._store) <= artifacts.MAX_ENTRIES
    # The most recent survive; the oldest were evicted first.
    assert artifacts.peek(tokens[-1]) is not None
    assert artifacts.peek(tokens[0]) is None


# -- the reply payload ----------------------------------------------------


def test_attachment_payload_accepts_an_artifact_token():
    token = artifacts.put("evaluare-275807510.md", "text/markdown", b"# Analiza")
    parsed = parse_reply_attachment(f'{{"artifactId": "{token}"}}', max_bytes=10_000)
    assert parsed is not None
    assert parsed.filename == "evaluare-275807510.md"
    assert parsed.data == b"# Analiza"


def test_stored_metadata_wins_over_what_the_model_repeated():
    """The tool that wrote the file knows its name; the model is quoting from
    memory and may have drifted."""
    token = artifacts.put("real.md", "text/markdown", b"content")
    parsed = parse_reply_attachment(
        f'{{"artifactId": "{token}", "filename": "hallucinated.csv", "mimeType": "text/csv"}}',
        max_bytes=10_000,
    )
    assert parsed is not None
    assert parsed.filename == "real.md"
    assert parsed.mime_type == "text/markdown"


def test_an_expired_token_degrades_to_no_attachment():
    assert parse_reply_attachment('{"artifactId": "art_gone"}', max_bytes=10_000) is None


def test_an_oversized_artifact_is_refused():
    token = artifacts.put("big.md", "text/markdown", b"x" * 100)
    assert parse_reply_attachment(f'{{"artifactId": "{token}"}}', max_bytes=10) is None


def test_the_inline_base64_payload_still_works():
    """The original shape must keep working — the model still composes small
    files itself, and only tool output goes through the store."""
    import base64

    encoded = base64.b64encode(b"a,b\n1,2").decode()
    payload = f'{{"filename": "a.csv", "mimeType": "text/csv", "contentBase64": "{encoded}"}}'
    parsed = parse_reply_attachment(payload, max_bytes=10_000)
    assert parsed is not None
    assert parsed.data == b"a,b\n1,2"
