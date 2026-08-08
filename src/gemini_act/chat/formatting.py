"""Normalizing the model's Markdown habits into Google Chat's text syntax.

Gemini writes GitHub-flavored Markdown by default — `**bold**`, `# headings`,
`[text](url)` links — because that is what it was trained on. Google Chat's
`text` field understands none of that: it has its own, much smaller markup
(`*bold*`, `_italic_`, `~strike~`, `<url|text>` links) and shows anything else
completely literally, asterisks and brackets included. The system instruction
asks the model to write Chat's syntax directly, but a style instruction is not
a guarantee — this is the deterministic backstop, run on every reply before it
reaches Chat, so a slip reads as clean text instead of a message full of stray
punctuation.

Deliberately narrow: it rewrites the handful of GFM constructs Gemini reaches
for out of habit, not Markdown in general. Tables are not among them — Chat
has no markup for one at all, and degrading an actual table into something
readable is a separate, harder problem not worth solving for how rarely a
*brief chat reply* (see `SYSTEM_INSTRUCTION`) should contain one.
"""

from __future__ import annotations

import re

# `**bold**` / `__bold__` -> `*bold*`. Non-greedy so one line with two spans
# ("**A** and **B**") closes each at its own `**` rather than spanning both;
# the lookaround pair rules out an opening/closing marker glued to whitespace,
# which is almost always two separate literal asterisks, not a bold span. Left
# unmatched (and so untouched) when a pair has not closed yet — the state
# `runner.run_agent` calls this with mid-stream, on a string still growing.
_BOLD = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*|__(?!\s)(.+?)(?<!\s)__")

# `~~strike~~` -> `~strike~`.
_STRIKE = re.compile(r"~~(?!\s)(.+?)(?<!\s)~~")

# `[text](url)` -> `<url|text>`, Chat's own hyperlink syntax. Restricted to
# http(s) so a relative or malformed target is left as plain text instead of
# becoming a link Chat cannot resolve.
_LINK = re.compile(r"\[([^\[\]]+)\]\((https?://[^\s()]+)\)")

# `# Heading` / `## Heading` -> a bold line. Chat has no heading markup at
# all; the raw hashes read worse than losing the size distinction entirely.
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+)$", re.MULTILINE)


def to_chat_markup(text: str) -> str:
    """Rewrite common GFM constructs as their Google Chat equivalents.

    Idempotent, and safe to call repeatedly on a partial, still-streaming
    string: a marker pair that has not closed yet simply does not match, and
    is picked up on a later call once the whole thing has arrived.
    """
    text = _LINK.sub(r"<\2|\1>", text)
    text = _HEADING.sub(r"*\1*", text)
    text = _BOLD.sub(lambda m: f"*{m.group(1) or m.group(2)}*", text)
    text = _STRIKE.sub(r"~\1~", text)
    return text
