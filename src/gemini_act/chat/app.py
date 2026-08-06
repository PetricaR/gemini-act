"""The FastAPI application served on Cloud Run."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Request

from gemini_act.chat.auth import require_chat_request
from gemini_act.chat.events import handle_event, normalize_event
from gemini_act.config import get_settings
from gemini_act.oauth.routes import router as oauth_router

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Gemini Act", description="An ADK agent that acts from Google Chat")
app.include_router(oauth_router)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "model": settings.model,
        "mcp_enabled": list(settings.mcp_enabled),
        "verify_chat_requests": settings.verify_chat_requests,
    }


@app.post("/", dependencies=[Depends(require_chat_request)])
async def chat_webhook(request: Request, background: BackgroundTasks) -> dict[str, Any]:
    """Receive a Google Chat event.

    Returns quickly; anything slow is handed to `background`, which FastAPI runs
    after the response has been sent.
    """
    event = await request.json()
    # Log the normalized type: the raw add-on payload has no top-level "type",
    # so reading it here would log None for every add-on request.
    normalized, is_addon = normalize_event(event)
    logger.info(
        "Chat event: %s (%s)",
        normalized.get("type") or "unrecognised",
        "add-on" if is_addon else "classic",
    )
    return await handle_event(event, background.add_task)


def main() -> None:
    """Entry point for `gemini-act` / local `python -m`."""
    import uvicorn

    uvicorn.run(
        "gemini_act.chat.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
    )


if __name__ == "__main__":
    main()
