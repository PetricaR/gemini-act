"""The user-facing OAuth consent flow.

`/oauth/start` is linked from the auth card the Chat app posts when it meets a
user it has no credentials for. `/oauth/callback` is the redirect URI registered
on the OAuth client.
"""

from __future__ import annotations

import logging
from datetime import UTC

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from gemini_act.config import Settings, get_settings
from gemini_act.oauth.store import StoredToken, TokenService, get_token_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])

_STATE_SALT = "gemini-act-oauth-state"
_STATE_MAX_AGE_SECONDS = 900  # 15 minutes to complete consent


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.state_secret, salt=_STATE_SALT)


def make_state(user_id: str, space: str, settings: Settings) -> str:
    """Sign the Chat identity into the OAuth `state` so the callback can trust it."""
    return _serializer(settings).dumps({"user_id": user_id, "space": space})


def read_state(state: str, settings: Settings) -> dict[str, str]:
    try:
        return _serializer(settings).loads(state, max_age=_STATE_MAX_AGE_SECONDS)
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired state") from exc


def authorization_url(user_id: str, space: str, settings: Settings) -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": settings.oauth_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.oauth_scopes),
        "state": make_state(user_id, space, settings),
        # We need a refresh token, and we need it every time so re-consenting
        # after a scope change does not leave us without one.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def start_url(user_id: str, space: str, settings: Settings) -> str:
    """The `/oauth/start` link embedded in the auth card."""
    from urllib.parse import urlencode

    query = urlencode({"state": make_state(user_id, space, settings)})
    return f"{settings.public_base_url.rstrip('/')}/oauth/start?{query}"


def _page(title: str, body: str, ok: bool = True) -> HTMLResponse:
    colour = "#137333" if ok else "#c5221f"
    return HTMLResponse(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title></head>
<body style="font-family:system-ui,sans-serif;max-width:34rem;margin:4rem auto;padding:0 1rem">
<h1 style="color:{colour};font-size:1.4rem">{title}</h1>
<p style="color:#3c4043;line-height:1.6">{body}</p>
</body></html>""",
        status_code=200 if ok else 400,
    )


@router.get("/start")
async def oauth_start(state: str = Query(...)) -> RedirectResponse:
    """Bounce the user to Google's consent screen, preserving the signed state."""
    settings = get_settings()
    claims = read_state(state, settings)
    url = authorization_url(claims["user_id"], claims.get("space", ""), settings)
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
async def oauth_callback(
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    settings = get_settings()
    claims = read_state(state, settings)
    user_id = claims["user_id"]

    if error or not code:
        return _page(
            "Authorization cancelled",
            f"Google reported: <code>{error or 'no authorization code'}</code>. "
            "You can retry from Google Chat with <code>/auth</code>.",
            ok=False,
        )

    try:
        stored = await _exchange_code(code, settings)
    except Exception:
        logger.exception("Token exchange failed for %s", user_id)
        return _page(
            "Could not complete authorization",
            "The token exchange with Google failed. Please try <code>/auth</code> again.",
            ok=False,
        )

    service: TokenService = get_token_service()
    await service.store.put(user_id, stored)
    logger.info("Stored credentials for %s (%s)", user_id, stored.email or "unknown email")

    await _notify_user(user_id, claims.get("space", ""), stored.email)

    return _page(
        "You're connected",
        f"Gemini Act can now act on your behalf as "
        f"<strong>{stored.email or 'your account'}</strong>. "
        "Head back to Google Chat and carry on the conversation.",
    )


async def _exchange_code(code: str, settings: Settings) -> StoredToken:
    """Swap the authorization code for tokens, and look up the user's email."""
    import asyncio

    import google_auth_oauthlib.flow

    def _run() -> StoredToken:
        flow = google_auth_oauthlib.flow.Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.oauth_client_id,
                    "client_secret": settings.oauth_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.oauth_redirect_uri],
                }
            },
            scopes=None,  # accept whatever the user actually granted
            redirect_uri=settings.oauth_redirect_uri,
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials

        expiry = credentials.expiry
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)

        email = ""
        try:
            from googleapiclient.discovery import build

            info = build("oauth2", "v2", credentials=credentials).userinfo().get().execute()
            email = info.get("email", "")
        except Exception:  # email is nice-to-have, not required
            logger.debug("Could not resolve user email", exc_info=True)

        if not credentials.refresh_token:
            raise RuntimeError("Google returned no refresh token; re-consent with prompt=consent")

        return StoredToken(
            refresh_token=credentials.refresh_token,
            scopes=list(credentials.scopes or []),
            email=email,
            access_token=credentials.token or "",
            expiry=expiry,
        )

    return await asyncio.to_thread(_run)


async def _notify_user(user_id: str, space: str, email: str) -> None:
    """Best-effort 'you're connected' message back in the Chat space."""
    if not space:
        return
    try:
        from gemini_act.chat.client import get_chat_client

        who = f" as {email}" if email else ""
        await get_chat_client().post_text(
            space=space,
            text=f"✅ Authorization complete{who}. Ask me anything.",
        )
    except Exception:
        logger.warning(
            "Could not notify %s in %s of successful auth", user_id, space, exc_info=True
        )
