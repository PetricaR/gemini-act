"""A pragmatic subset of Google's A2UI protocol, rendered onto Cards v2.

A2UI (see https://github.com/google/A2UI) lets an agent describe a UI as a
flat list of components — buttons, text, images, layout — instead of only
text, so a client can render it natively. The real protocol is built for a
client with its own component catalog and a live, incrementally-patched
"surface" (`createSurface` / `updateComponents` messages over a JSONL
stream); Google Chat has neither concept — a message is `text` and/or
`cardsV2`, sent whole, once. There is also no ADK helper (as of the version
this app uses) that builds A2UI on the Python side; the actual convention,
per Google's own Chat quickstart, is that the *model* writes the JSON itself
as part of its answer.

So this is a deliberately smaller thing: the model may end its answer with a
marker followed by a single JSON object naming one root component and its
descendants by id, using A2UI's own field names (`component`, `child`,
`children`, `action.event`) for whichever of that catalog Cards v2 can
actually represent — see `_RENDERERS`. Anything else in the real catalog
(sliders, checkboxes, tabs, modals, form inputs, live incremental updates)
has no equivalent here and degrades to a visible "unsupported" note rather
than breaking the whole reply — Cards v2 itself has no such widgets, so no
amount of parsing sophistication would change that.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

# Matches the marker Google's own A2UI Chat quickstart uses to separate an
# agent's spoken answer from the UI payload that follows it.
MARKER = "---a2ui_JSON---"

# A component tree deep enough to need this is almost certainly a mistake (or
# a cycle) rather than a deliberately deep layout; this bounds the recursion
# instead of letting a malformed payload from the model take down the reply.
_MAX_DEPTH = 12


def split_a2ui(text: str) -> tuple[str, str]:
    """Split an answer into its spoken part and a trailing raw JSON blob.

    The second element is `""` when there is no marker — the common case, an
    answer with no attached UI. Safe to call on a partial, still-streaming
    string: nothing after an as-yet-unwritten marker is treated as spoken
    text, since `partition` simply does not find it yet.
    """
    spoken, sep, raw = text.partition(MARKER)
    if not sep:
        return text, ""
    return spoken.rstrip(), raw.strip()


def parse_a2ui(raw: str) -> dict[str, Any] | None:
    """Parse the JSON blob `split_a2ui` returned, or `None` if it is not one.

    A model that gets the shape wrong (or an incomplete blob, e.g. if the
    turn ended mid-JSON) must not break the reply — the caller falls back to
    the spoken text alone.
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _unsupported(label: str) -> dict[str, Any]:
    return {"textParagraph": {"text": f"⚠️ Unsupported UI element: {escape(label)}"}}


def _child_ids(component: dict[str, Any]) -> list[str]:
    children = component.get("children")
    if isinstance(children, list):
        return [c for c in children if isinstance(c, str)]
    child = component.get("child")
    return [child] if isinstance(child, str) else []


def _render_text(component: dict[str, Any], _by_id: dict, _depth: int) -> list[dict[str, Any]]:
    return [{"textParagraph": {"text": escape(str(component.get("text", "")))}}]


def _render_divider(_component: dict, _by_id: dict, _depth: int) -> list[dict[str, Any]]:
    return [{"divider": {}}]


def _render_image(component: dict[str, Any], _by_id: dict, _depth: int) -> list[dict[str, Any]]:
    url = component.get("url")
    if not isinstance(url, str) or not url:
        return [_unsupported("Image with no url")]
    image: dict[str, Any] = {"imageUrl": url}
    if component.get("altText"):
        image["altText"] = str(component["altText"])
    return [{"image": image}]


def _render_button(component: dict[str, Any], _by_id: dict, _depth: int) -> list[dict[str, Any]]:
    text = str(component.get("text", "OK"))
    event = (component.get("action") or {}).get("event")
    url = component.get("url")
    if isinstance(event, dict) and event.get("name"):
        context = event.get("context") if isinstance(event.get("context"), dict) else {}
        on_click: dict[str, Any] = {
            "action": {
                "function": str(event["name"]),
                "parameters": [
                    {"key": str(key), "value": str(value)} for key, value in context.items()
                ],
            }
        }
    elif isinstance(url, str) and url:
        on_click = {"openLink": {"url": url}}
    else:
        return [_unsupported(f'Button "{text}" has no action or url')]
    return [{"buttonList": {"buttons": [{"text": escape(text), "onClick": on_click}]}}]


def _render_layout(
    component: dict[str, Any], by_id: dict[str, dict], depth: int
) -> list[dict[str, Any]]:
    """`Card`, `Column` and `Row` all flatten to the same thing here: Cards v2
    has one section of stacked widgets, not nested cards or side-by-side
    layout, so there is no meaningful difference left to preserve between
    them once rendered."""
    widgets: list[dict[str, Any]] = []
    for child_id in _child_ids(component):
        widgets.extend(_render_component(child_id, by_id, depth + 1))
    return widgets


_RENDERERS = {
    "Text": _render_text,
    "Divider": _render_divider,
    "Image": _render_image,
    "Button": _render_button,
    "Card": _render_layout,
    "Column": _render_layout,
    "Row": _render_layout,
}


def _render_component(
    component_id: str, by_id: dict[str, dict[str, Any]], depth: int
) -> list[dict[str, Any]]:
    if depth > _MAX_DEPTH:
        return [_unsupported(f'"{component_id}" nested too deep')]
    component = by_id.get(component_id)
    if component is None:
        return [_unsupported(f'missing component "{component_id}"')]
    renderer = _RENDERERS.get(component.get("component", ""))
    if renderer is None:
        return [_unsupported(str(component.get("component", "unknown")))]
    return renderer(component, by_id, depth)


def render_a2ui(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Render a parsed A2UI payload into Cards v2 widgets, or `None`.

    `None` means the payload was not usable at all (no `components` list, or
    no component with id `"root"`) — the caller's fallback is the spoken text
    alone, same as if there had been no UI payload. A malformed *component*
    inside an otherwise valid tree does not get the same treatment: it
    becomes a visible "unsupported" note in place of just that piece, so one
    bad widget cannot cost the whole card.
    """
    components = payload.get("components")
    if not isinstance(components, list):
        return None
    by_id = {
        component["id"]: component
        for component in components
        if isinstance(component, dict) and isinstance(component.get("id"), str)
    }
    if "root" not in by_id:
        return None
    return _render_component("root", by_id, 0)
