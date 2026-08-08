"""The model attaching a file to its own reply — the reverse of an incoming
attachment. Same marker+JSON convention as chat/a2ui.py, so these tests mirror
test_a2ui.py's shape: split the marker out, parse and decode what follows, and
make sure anything malformed degrades to "no attachment" rather than breaking
the reply or leaking raw base64 into the chat.
"""

from __future__ import annotations

import base64

from gemini_act.chat.reply_attachment import (
    MARKER,
    ReplyAttachment,
    attachment_message,
    parse_reply_attachment,
    split_reply_attachment,
)


def _payload(content: bytes, filename: str = "report.csv", mime_type: str = "text/csv") -> str:
    import json

    return json.dumps(
        {
            "filename": filename,
            "mimeType": mime_type,
            "contentBase64": base64.b64encode(content).decode("ascii"),
        }
    )


# --- splitting the marker out of an answer ---


def test_split_with_no_marker_returns_the_whole_text_unchanged():
    assert split_reply_attachment("just an ordinary answer") == ("just an ordinary answer", "")


def test_split_separates_spoken_text_from_the_json_tail():
    text = f"Here's your report.\n\n{MARKER}\n" + _payload(b"a,b\n1,2\n")
    spoken, raw = split_reply_attachment(text)
    assert spoken == "Here's your report."
    assert raw == _payload(b"a,b\n1,2\n")


def test_split_on_a_string_still_growing_mid_stream_finds_nothing_yet():
    partial = "Here's your report.\n\n---chat_attachment_J"
    assert split_reply_attachment(partial) == (partial, "")


# --- parsing and decoding ---


def test_a_valid_payload_decodes_to_the_original_bytes():
    raw = _payload(b"hello world", "notes.txt", "text/plain")
    result = parse_reply_attachment(raw, max_bytes=1_000)
    assert result == ReplyAttachment(filename="notes.txt", mime_type="text/plain", data=b"hello world")


def test_malformed_json_is_not_an_attachment():
    assert parse_reply_attachment("{not valid json", max_bytes=1_000) is None


def test_a_json_value_that_is_not_an_object_is_not_an_attachment():
    assert parse_reply_attachment("[1, 2, 3]", max_bytes=1_000) is None


def test_a_missing_required_field_is_not_an_attachment():
    import json

    raw = json.dumps({"filename": "x.txt", "mimeType": "text/plain"})  # no contentBase64
    assert parse_reply_attachment(raw, max_bytes=1_000) is None


def test_invalid_base64_is_not_an_attachment():
    import json

    raw = json.dumps({"filename": "x.txt", "mimeType": "text/plain", "contentBase64": "not-b64!!"})
    assert parse_reply_attachment(raw, max_bytes=1_000) is None


def test_an_empty_filename_is_not_an_attachment():
    import json

    raw = json.dumps(
        {"filename": "", "mimeType": "text/plain", "contentBase64": base64.b64encode(b"x").decode()}
    )
    assert parse_reply_attachment(raw, max_bytes=1_000) is None


def test_a_file_over_the_size_cap_is_not_an_attachment():
    raw = _payload(b"x" * 2_000)
    assert parse_reply_attachment(raw, max_bytes=1_000) is None


def test_a_non_string_field_is_not_an_attachment():
    import json

    raw = json.dumps({"filename": 123, "mimeType": "text/plain", "contentBase64": "eA=="})
    assert parse_reply_attachment(raw, max_bytes=1_000) is None


# --- building the outgoing message body ---


def test_attachment_message_wraps_the_upload_response_verbatim():
    upload_response = {"attachmentDataRef": {"resourceName": "spaces/AAA/.../attachments/CCC"}}
    assert attachment_message(upload_response) == {"attachment": [upload_response]}
