"""A pragmatic subset of Google's A2UI protocol, rendered onto Cards v2.

There is no ADK helper that builds A2UI content, and Google Chat has no
native A2UI renderer — the convention (per Google's own Chat quickstart) is
that the model writes a marker followed by raw JSON as part of its answer,
and the app is on its own to parse and render it. These tests cover that
parsing/rendering, and — just as importantly — that a malformed attempt at
rich UI degrades to plain text instead of leaking raw JSON into the chat.
"""

from __future__ import annotations

from gemini_act.chat.a2ui import MARKER, parse_a2ui, render_a2ui, split_a2ui

# --- splitting the marker out of an answer ---


def test_split_with_no_marker_returns_the_whole_text_unchanged():
    assert split_a2ui("just an ordinary answer") == ("just an ordinary answer", "")


def test_split_separates_spoken_text_from_the_json_tail():
    text = f'Here you go.\n\n{MARKER}\n{{"components": []}}'
    assert split_a2ui(text) == ("Here you go.", '{"components": []}')


def test_split_on_a_string_still_growing_mid_stream_finds_nothing_yet():
    """`runner.run_agent` calls this on a partial buffer; the marker has not
    fully arrived yet, so everything so far must read as spoken text."""
    partial = "Here you go.\n\n---a2ui_J"
    assert split_a2ui(partial) == (partial, "")


# --- parsing the JSON tail ---


def test_parse_valid_json_object():
    assert parse_a2ui('{"components": []}') == {"components": []}


def test_parse_rejects_malformed_json():
    assert parse_a2ui('{"components": [') is None


def test_parse_rejects_a_json_value_that_is_not_an_object():
    assert parse_a2ui("[1, 2, 3]") is None


# --- rendering the component tree ---


def test_missing_components_list_is_not_renderable():
    assert render_a2ui({}) is None


def test_missing_root_component_is_not_renderable():
    assert render_a2ui({"components": [{"id": "x", "component": "Text", "text": "hi"}]}) is None


def test_a_bare_text_root_renders_as_one_widget():
    payload = {"components": [{"id": "root", "component": "Text", "text": "Hello"}]}
    assert render_a2ui(payload) == [{"textParagraph": {"text": "Hello"}}]


def test_text_content_is_html_escaped():
    payload = {"components": [{"id": "root", "component": "Text", "text": "<script>x</script>"}]}
    widgets = render_a2ui(payload)
    assert "<script>" not in widgets[0]["textParagraph"]["text"]


def test_divider_renders_with_no_fields():
    payload = {"components": [{"id": "root", "component": "Divider"}]}
    assert render_a2ui(payload) == [{"divider": {}}]


def test_image_renders_url_and_alt_text():
    payload = {
        "components": [
            {
                "id": "root",
                "component": "Image",
                "url": "https://example.com/x.png",
                "altText": "a cat",
            }
        ]
    }
    assert render_a2ui(payload) == [
        {"image": {"imageUrl": "https://example.com/x.png", "altText": "a cat"}}
    ]


def test_image_without_a_url_is_reported_as_unsupported():
    payload = {"components": [{"id": "root", "component": "Image"}]}
    widgets = render_a2ui(payload)
    assert "Unsupported" in widgets[0]["textParagraph"]["text"]


def test_button_with_a_url_becomes_a_link_button():
    payload = {
        "components": [
            {"id": "root", "component": "Button", "text": "Open", "url": "https://example.com"}
        ]
    }
    button = render_a2ui(payload)[0]["buttonList"]["buttons"][0]
    assert button == {"text": "Open", "onClick": {"openLink": {"url": "https://example.com"}}}


def test_button_with_an_action_event_becomes_a_callback_button():
    payload = {
        "components": [
            {
                "id": "root",
                "component": "Button",
                "text": "Confirm",
                "action": {"event": {"name": "confirm_delete", "context": {"item_id": "42"}}},
            }
        ]
    }
    button = render_a2ui(payload)[0]["buttonList"]["buttons"][0]
    assert button["onClick"]["action"]["function"] == "confirm_delete"
    assert button["onClick"]["action"]["parameters"] == [{"key": "item_id", "value": "42"}]


def test_button_with_neither_action_nor_url_is_reported_as_unsupported():
    payload = {"components": [{"id": "root", "component": "Button", "text": "Mystery"}]}
    widgets = render_a2ui(payload)
    assert "Unsupported" in widgets[0]["textParagraph"]["text"]
    assert "Mystery" in widgets[0]["textParagraph"]["text"]


def test_card_column_and_row_all_flatten_to_their_childrens_widgets():
    for wrapper in ("Card", "Column", "Row"):
        payload = {
            "components": [
                {"id": "root", "component": wrapper, "children": ["a", "b"]},
                {"id": "a", "component": "Text", "text": "first"},
                {"id": "b", "component": "Text", "text": "second"},
            ]
        }
        assert render_a2ui(payload) == [
            {"textParagraph": {"text": "first"}},
            {"textParagraph": {"text": "second"}},
        ]


def test_card_with_a_single_child_uses_the_child_field():
    payload = {
        "components": [
            {"id": "root", "component": "Card", "child": "a"},
            {"id": "a", "component": "Text", "text": "only child"},
        ]
    }
    assert render_a2ui(payload) == [{"textParagraph": {"text": "only child"}}]


def test_a_realistic_confirmation_card():
    """The shape the system instruction actually asks the model for: a
    message plus a couple of named options to confirm."""
    payload = {
        "components": [
            {"id": "root", "component": "Card", "children": ["msg", "div", "yes", "no"]},
            {"id": "msg", "component": "Text", "text": "Delete this event?"},
            {"id": "div", "component": "Divider"},
            {
                "id": "yes",
                "component": "Button",
                "text": "Yes, delete it",
                "action": {"event": {"name": "confirm_delete", "context": {"event_id": "abc"}}},
            },
            {
                "id": "no",
                "component": "Button",
                "text": "Cancel",
                "url": "https://example.com/cancel",
            },
        ]
    }
    widgets = render_a2ui(payload)
    assert widgets[0] == {"textParagraph": {"text": "Delete this event?"}}
    assert widgets[1] == {"divider": {}}
    assert widgets[2]["buttonList"]["buttons"][0]["text"] == "Yes, delete it"
    assert widgets[3]["buttonList"]["buttons"][0]["onClick"]["openLink"]["url"] == (
        "https://example.com/cancel"
    )


# --- degrading instead of failing ---


def test_an_unknown_component_type_is_a_visible_note_not_a_crash():
    payload = {"components": [{"id": "root", "component": "Slider", "min": 0, "max": 10}]}
    widgets = render_a2ui(payload)
    assert "Slider" in widgets[0]["textParagraph"]["text"]


def test_a_missing_child_reference_is_a_visible_note_not_a_crash():
    payload = {"components": [{"id": "root", "component": "Column", "children": ["ghost"]}]}
    widgets = render_a2ui(payload)
    assert "ghost" in widgets[0]["textParagraph"]["text"]


def test_a_self_referencing_component_does_not_recurse_forever():
    payload = {"components": [{"id": "root", "component": "Column", "children": ["root"]}]}
    widgets = render_a2ui(payload)
    assert widgets, "must return something rather than hang or crash"
