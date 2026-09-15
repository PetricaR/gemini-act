"""Suprafața HTTP a evaluării: API-ul raportului React și un endpoint MCP real.

Al doilea serviciu Cloud Run, din aceeași imagine ca agentul de Chat, cu alt
entrypoint. Separarea e de *deployment*, nu de protocol:

* Agentul de Chat continuă să cheme evaluarea **în proces**
  (`imobiliare/agent_tools/`). Între el și pachetul acesta nu există graniță de
  vendor, de limbaj sau de încredere, deci MCP pe calea aceea ar fi doar
  `tools/list` plătit la fiecare tură LLM și predarea raportului ruptă în două
  procese — vezi `artifacts.py`.
* Aici MCP își câștigă locul: `/mcp` e pentru clienți pe care **nu** îi
  controlăm — Claude Desktop, alți agenți — pentru care granița chiar există.

Ce câștigă separarea: dependențele grele (reportlab, pypdf, pillow, browserul
headless) și munca de minute a unei evaluări primesc propriul CPU, propria
memorie și propriul blast radius. Un OOM la randarea unui PDF nu mai doboară
webhook-ul de Chat.
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from imobiliare.api.routes import router as api_router
from imobiliare.mcp.server import mcp

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# Cloud Run poate rula mai multe instanțe fără lipici de sesiune, iar o sesiune
# MCP cu stare ar trăi în memoria unei singure instanțe. Fără asta, al doilea
# request al unui client poate ateriza pe altă instanță și primi 404 pe sesiune.
mcp.settings.stateless_http = True
mcp.settings.json_response = True
# Calea internă a sub-aplicației; montată mai jos la `/mcp`, endpointul devine
# exact `/mcp` în loc de `/mcp/mcp`.
mcp.settings.streamable_http_path = "/"

_mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(_: FastAPI) -> Any:
    """Pornește managerul de sesiuni al sub-aplicației MCP.

    Montarea unei aplicații Starlette nu îi rulează și lifespan-ul; fără linia
    asta `tools/list` răspunde cu „Task group is not initialized".
    """
    async with _mcp_app.router.lifespan_context(_mcp_app):
        yield


app = FastAPI(
    title="Evaluator AI",
    description="Raportul de evaluare imobiliară: API-ul UI-ului React și serverul MCP.",
    lifespan=lifespan,
)
app.include_router(api_router)


@app.middleware("http")
async def _poarta_mcp(request: Request, call_next: Any) -> Any:
    """Cere un bearer token pe `/mcp`, și numai acolo.

    UI-ul React e deschis, ca și până acum — browserul nu poartă niciun token.
    Uneltele, în schimb, cheltuie bani (apeluri Gemini Vision, pe imagine) și
    lovesc site-uri terțe în numele nostru, deci nu pot sta pe un endpoint
    public.

    Se închide, nu se deschide, când `IMOBILIARE_MCP_TOKEN` lipsește: un deploy
    care uită variabila rămâne fără MCP, în loc să publice 28 de unelte în
    internet. Același tipar ca `chat_audience` din `gemini_act`.
    """
    if request.url.path.startswith("/mcp"):
        asteptat = os.environ.get("IMOBILIARE_MCP_TOKEN", "").strip()
        if not asteptat:
            return JSONResponse(
                {"detail": "Endpointul MCP este dezactivat: IMOBILIARE_MCP_TOKEN nu este setat."},
                status_code=503,
            )
        primit = request.headers.get("authorization", "")
        prefix = "bearer "
        dat = primit[len(prefix) :] if primit[: len(prefix)].lower() == prefix else ""
        if not secrets.compare_digest(dat, asteptat):
            return JSONResponse({"detail": "Token MCP invalid sau lipsă."}, status_code=401)
    return await call_next(request)


app.mount("/mcp", _mcp_app)

_POSSIBLE_DIST_DIRS = [
    Path(__file__).resolve().parents[2] / "web" / "dist",
    Path("/app/web/dist"),
    Path(os.getcwd()) / "web" / "dist",
]
_DIST_DIR = next((d for d in _POSSIBLE_DIST_DIRS if d.is_dir()), None)

if _DIST_DIR and (_DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST_DIR / "assets"), name="assets")


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "mcp": "/mcp", "ui": bool(_DIST_DIR)}


@app.get("/")
async def index() -> Any:
    if _DIST_DIR and (_DIST_DIR / "index.html").is_file():
        return FileResponse(_DIST_DIR / "index.html")
    return {
        "status": "ok",
        "mesaj": "Evaluator AI. UI-ul React nu este construit în imaginea asta.",
    }


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))  # noqa: S104
