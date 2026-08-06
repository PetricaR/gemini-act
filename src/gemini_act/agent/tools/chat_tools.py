"""Actions the app takes in Google Chat *as itself*, using app credentials.

These differ from the Chat MCP toolset, which acts as the end user. Use these
when the app should be the visible actor — announcing into a space it is a
member of, for instance.
"""

from __future__ import annotations

import logging
from typing import Any

from gemini_act.chat.client import get_chat_client

logger = logging.getLogger(__name__)


async def post_message_to_space(space: str, text: str) -> dict[str, Any]:
    """Post a message into a Google Chat space as this app.

    Use for announcements or notifications the app should be seen to send. To
    answer the person you are talking to, just reply normally instead.

    Args:
        space: Space resource name, e.g. "spaces/AAAA1111". The app must
            already be a member of the space.
        text: Message text. Supports Chat's simple markdown (*bold*, _italic_).

    Returns:
        A dict with "status" ("success" or "error"), and on success the created
        message's "name"; on error an "error_message".
    """
    try:
        created = await get_chat_client().post_text(space=space, text=text)
    except Exception as exc:
        logger.exception("post_message_to_space failed for %s", space)
        return {"status": "error", "error_message": str(exc)}
    return {"status": "success", "name": created.get("name", "")}


async def list_space_members(space: str) -> dict[str, Any]:
    """List the members of a Google Chat space, as seen by this app.

    Args:
        space: Space resource name, e.g. "spaces/AAAA1111".

    Returns:
        A dict with "status", and on success "members": a list of dicts with
        "name" and "display_name"; on error an "error_message".
    """
    try:
        memberships = await get_chat_client().list_members(space=space)
    except Exception as exc:
        logger.exception("list_space_members failed for %s", space)
        return {"status": "error", "error_message": str(exc)}

    members = [
        {
            "name": m.get("member", {}).get("name", ""),
            "display_name": m.get("member", {}).get("displayName", ""),
        }
        for m in memberships
    ]
    return {"status": "success", "members": members}


async def list_app_spaces() -> dict[str, Any]:
    """List the Google Chat spaces this app is a member of.

    Useful for discovering a space resource name before posting into it.

    Returns:
        A dict with "status", and on success "spaces": a list of dicts with
        "name", "display_name" and "type"; on error an "error_message".
    """
    try:
        spaces = await get_chat_client().list_spaces()
    except Exception as exc:
        logger.exception("list_app_spaces failed")
        return {"status": "error", "error_message": str(exc)}

    return {
        "status": "success",
        "spaces": [
            {
                "name": s.get("name", ""),
                "display_name": s.get("displayName", ""),
                "type": s.get("spaceType", ""),
            }
            for s in spaces
        ],
    }


CHAT_TOOLS = [post_message_to_space, list_space_members, list_app_spaces]
