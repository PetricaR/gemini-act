"""The FastAPI application served on Cloud Run."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from gemini_act.chat.auth import require_chat_request
from gemini_act.chat.events import handle_event, normalize_event
from gemini_act.config import get_settings
from gemini_act.oauth.routes import router as oauth_router
from imobiliare.api.routes import router as api_router

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Gemini Act & Evaluator AI",
    description="ADK agent for Google Chat, plus the Evaluator AI property audit web report",
)
app.include_router(oauth_router)
app.include_router(api_router)

# Resolve static assets for React Web UI
_POSSIBLE_DIST_DIRS = [
    (
        Path(__file__).resolve().parents[3] / "web" / "dist"
        if len(Path(__file__).resolve().parents) > 3
        else Path("web/dist")
    ),
    Path("/app/web/dist"),
    Path(os.getcwd()) / "web" / "dist",
]
_DIST_DIR = next((d for d in _POSSIBLE_DIST_DIRS if d.is_dir()), None)

if _DIST_DIR and (_DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST_DIR / "assets"), name="assets")


_PLACEHOLDER_HTML = """
<!DOCTYPE html>
<html lang="ro">
<head>
    <meta charset="UTF-8">
    <title>Evaluator AI - Audit tehnic si evaluare imobiliara</title>
</head>
<body style="font-family: system-ui, sans-serif; text-align: center; padding: 60px 20px;
             background: #0f172a; color: #f8fafc;">
    <h1 style="font-size: 2.2rem; color: #38bdf8;">🏢 Evaluator AI</h1>
    <p style="font-size: 1.1rem; color: #94a3b8; max-width: 600px; margin: 20px auto;">
        Platforma de audit imobiliar 360° este activă. Modulul React UI este în curs de încărcare.
    </p>
    <div style="margin-top: 30px;">
        <a href="/api/audit/demo"
           style="background: #2563eb; color: #fff; padding: 12px 24px; border-radius: 8px;
                  text-decoration: none; font-weight: 600; margin-right: 12px;">
            Testează API Demo
        </a>
        <a href="/healthz"
           style="background: #334155; color: #fff; padding: 12px 24px; border-radius: 8px;
                  text-decoration: none; font-weight: 600;">
            Status Server (Healthz)
        </a>
    </div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
async def serve_ui() -> Any:
    """Serve the React Web UI for property audits."""
    if _DIST_DIR and (_DIST_DIR / "index.html").is_file():
        return FileResponse(_DIST_DIR / "index.html")
    return HTMLResponse(_PLACEHOLDER_HTML)


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
