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
from mcp.server.transport_security import TransportSecuritySettings

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
# Calea internă a sub-aplicației. Montată mai jos la `/mcp` cu calea internă
# `/mcp`, nu `/`: cu `/` endpointul real devine `/mcp/`, iar Starlette răspunde
# la `/mcp` cu un redirect de slash construit ca URL absolut. În spatele unui
# proxy care termină TLS — adică pe Cloud Run — acel URL iese `http://`, browserul
# sau clientul e trimis mai departe printr-un 302 http→https care transformă
# POST-ul în GET și pierde corpul cererii. Fără slash de rezolvat, nu există
# redirect și nu există problema.
mcp.settings.streamable_http_path = "/mcp"

# Protecția anti DNS-rebinding a SDK-ului validează `Host` față de o listă care
# implicit conține doar localhost, deci pe Cloud Run fiecare cerere primea
# „Invalid Host header" → 421. Hostul serviciului nu e cunoscut la momentul
# build-ului, așa că vine din mediu; gol înseamnă „acceptă orice host", ceea ce
# e sigur aici pentru că `/mcp` e oricum păzit de bearer token mai jos.
_HOSTURI = [h.strip() for h in os.environ.get("IMOBILIARE_MCP_HOSTS", "").split(",") if h.strip()]
if _HOSTURI:
    mcp.settings.transport_security = TransportSecuritySettings(allowed_hosts=_HOSTURI)
else:
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

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


_POSSIBLE_DIST_DIRS = [
    Path(__file__).resolve().parents[2] / "web" / "dist",
    Path("/app/web/dist"),
    Path(os.getcwd()) / "web" / "dist",
]
_DIST_DIR = next((d for d in _POSSIBLE_DIST_DIRS if d.is_dir()), None)

if _DIST_DIR and (_DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST_DIR / "assets"), name="assets")


@app.get("/healthz")
@app.get("/status")
async def healthz() -> dict[str, Any]:
    """Starea serviciului, pe două căi.

    `/healthz` funcționează local, dar pe Cloud Run nu ajunge niciodată la
    container: răspunsul vine fără `x-cloud-trace-context`, deci ceva din fața
    Cloud Run îl răspunde cu un 404 propriu (la fel pentru orice cale
    necunoscută). `/status` trece, așa că el este cel de folosit din exterior;
    `/healthz` rămâne pentru rulările locale și pentru orice sondă care îl
    caută după nume.
    """
    return {"status": "ok", "mcp": "/mcp", "ui": bool(_DIST_DIR)}


@app.get("/")
async def index() -> Any:
    if _DIST_DIR and (_DIST_DIR / "index.html").is_file():
        return FileResponse(_DIST_DIR / "index.html")
    return {
        "status": "ok",
        "mesaj": "Evaluator AI. UI-ul React nu este construit în imaginea asta.",
    }


# Montat ULTIMUL și la rădăcină, intenționat. Sub-aplicația își poartă singură
# calea `/mcp`, deci montarea la `/mcp` ar da `/mcp/mcp`, iar montarea la `/mcp`
# cu calea internă `/` ar da `/mcp/` plus un redirect de slash. Un Mount pe `/`
# prinde însă orice cale, așa că trebuie să vină după toate rutele de mai sus —
# Starlette potrivește în ordinea declarării. Ce ajunge aici și nu e `/mcp` ar fi
# dat oricum 404.
app.mount("/", _mcp_app)


def main() -> None:
    import uvicorn

    # Cloud Run termină TLS și trimite mai departe pe http; fără astea uvicorn
    # crede că schema e http și construiește redirecturi absolute greșite.
    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104
        port=int(os.environ.get("PORT", "8080")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
