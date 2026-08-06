"""Verification that a request really came from Google Chat.

Every request Chat sends carries a bearer token issued by
`chat@system.gserviceaccount.com`, whose audience is the HTTP endpoint URL
configured on the Chat API page. Anything that fails to verify gets a 401.
https://developers.google.com/workspace/chat/verify-requests-from-chat
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import Header, HTTPException
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from gemini_act.config import get_settings

logger = logging.getLogger(__name__)

# Classic Chat apps are signed by this fixed account.
CHAT_ISSUER = "chat@system.gserviceaccount.com"

# Chat apps built as Google Workspace add-ons are signed by a *per-project*
# service agent instead. Which one you get is fixed when the Chat app is first
# saved (the "build as a Workspace add-on" checkbox), and cannot be changed
# afterwards — so both must be accepted.
ADDON_ISSUER_SUFFIX = "@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"


def addon_issuer_for(project_number: str) -> str:
    return f"service-{project_number}{ADDON_ISSUER_SUFFIX}"


def is_valid_issuer(email: str, project_number: str = "") -> bool:
    """Whether this token issuer is one we accept.

    The classic issuer is a fixed address. The add-on issuer is per-project, so
    it is pinned to our project number when one is configured; without it we
    fall back to accepting the add-on suffix, which is weaker and warned about.
    """
    if email == CHAT_ISSUER:
        return True
    if project_number:
        return email == addon_issuer_for(project_number)
    if email.endswith(ADDON_ISSUER_SUFFIX):
        logger.warning(
            "Accepting add-on issuer %s without pinning: set GEMINI_ACT_PROJECT_NUMBER "
            "so tokens from other projects cannot be accepted",
            email,
        )
        return True
    return False


def _verify_sync(token: str, audience: str, project_number: str = "") -> bool:
    try:
        claims = id_token.verify_oauth2_token(token, google_requests.Request(), audience)
    except Exception as exc:
        logger.warning("Chat token verification failed: %s", exc)
        return False
    email = claims.get("email", "")
    if not is_valid_issuer(email, project_number):
        logger.warning(
            "Chat token has unexpected issuer: %s (expected %s or %s)",
            email,
            CHAT_ISSUER,
            addon_issuer_for(project_number or "<project-number>"),
        )
        return False
    return True


async def verify_chat_token(token: str, audience: str, project_number: str = "") -> bool:
    """Verify a Chat-issued bearer token against the expected audience."""
    return await asyncio.to_thread(_verify_sync, token, audience, project_number)


async def require_chat_request(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency guarding the Chat webhook."""
    settings = get_settings()
    if not settings.verify_chat_requests:
        logger.warning("Chat request verification is DISABLED — do not run this way in production")
        return

    if not settings.chat_audience:
        # Failing closed: without an audience we cannot verify anything, and
        # accepting unverified events would leave the endpoint wide open.
        logger.error("GEMINI_ACT_CHAT_AUDIENCE is unset; rejecting request")
        raise HTTPException(status_code=500, detail="Server misconfigured")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.removeprefix("Bearer ").strip()
    if not await verify_chat_token(token, settings.chat_audience, settings.project_number):
        raise HTTPException(status_code=401, detail="Invalid token")
