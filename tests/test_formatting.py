"""Rewriting the model's default Markdown into Google Chat's own syntax.

Google Chat's `text` field only understands its own small markup (`*bold*`,
`_italic_`, `~strike~`, `<url|text>` links); anything else — the GitHub-flavored
Markdown Gemini writes by habit — shows up to the user completely literally,
symbols and all. That literal leakage ("**like this**", a visible `[link](url)`)
is what made replies look unpolished; this is the deterministic fix, run on
every reply regardless of whether the model followed the style instruction.
"""

from __future__ import annotations

from gemini_act.chat.formatting import to_chat_markup


def test_double_asterisk_bold_becomes_single():
    assert to_chat_markup("This is **important** news.") == "This is *important* news."


def test_double_underscore_bold_becomes_single_asterisk():
    assert to_chat_markup("This is __important__ news.") == "This is *important* news."


def test_two_bold_spans_on_one_line_convert_independently():
    assert to_chat_markup("**A** and **B**") == "*A* and *B*"


def test_already_correct_single_asterisk_bold_is_left_alone():
    assert to_chat_markup("This is *fine* already.") == "This is *fine* already."


def test_single_underscore_italic_is_left_alone():
    """Chat's own italic syntax — must not be mistaken for a stray GFM marker."""
    assert to_chat_markup("Chat renders _italic_ natively.") == "Chat renders _italic_ natively."


def test_snake_case_word_is_not_mistaken_for_bold():
    assert to_chat_markup("Check my_file_name.txt for details.") == (
        "Check my_file_name.txt for details."
    )


def test_double_tilde_strikethrough_becomes_single():
    assert to_chat_markup("~~old price~~ $10") == "~old price~ $10"


def test_markdown_link_becomes_chat_hyperlink_syntax():
    assert to_chat_markup("See [the docs](https://example.com/docs) for more.") == (
        "See <https://example.com/docs|the docs> for more."
    )


def test_a_relative_link_target_is_left_as_plain_text():
    """Chat cannot resolve a relative target, so linkifying it would be worse
    than leaving the brackets visible."""
    text = "See [this page](/docs) for more."
    assert to_chat_markup(text) == text


def test_heading_becomes_a_bold_line():
    assert to_chat_markup("## Summary\nDetails follow.") == "*Summary*\nDetails follow."


def test_an_unclosed_bold_marker_mid_stream_is_left_alone():
    """`run_agent` calls this on a string that is still growing; an opening
    `**` with no closing pair yet must not be eaten or mangled."""
    partial = "Here is the **impor"
    assert to_chat_markup(partial) == partial


def test_conversion_is_idempotent():
    once = to_chat_markup("**bold** and [a link](https://example.com)")
    assert to_chat_markup(once) == once


def test_plain_text_is_unchanged():
    plain = "Your next meeting is at 3pm in Room B."
    assert to_chat_markup(plain) == plain
