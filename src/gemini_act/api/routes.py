"""REST API routes for Evaluator AI property audits and report generation."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from gemini_act.api import imagery
from gemini_act.api.demo_data import DEMO_AUDIT_DATA
from gemini_act.imobiliare_mcp import generator_pdf, paths, server

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditRequest(BaseModel):
    url_sau_id: str | None = Field(
        default=None,
        description="URL anunț imobiliare.ro, ID anunț sau adresă proprietate",
        examples=["https://www.imobiliare.ro/oferta/12345", "demo"],
    )
    url: str | None = Field(
        default=None,
        description="Alias pentru url_sau_id",
    )
    demo_mode: bool = Field(
        default=False,
        description="Activează modul demonstrativ instantaneu",
    )
    is_demo: bool = Field(
        default=False,
        description="Alias pentru demo_mode",
    )
    include_satelit: bool = Field(
        default=True,
        description="Include ortofotoplan satelitar al zonei",
    )


def _with_location(date_audit: dict[str, Any]) -> dict[str, Any]:
    """Attach live coordinates, imagery URLs and 500 m amenities to an audit.

    Never fatal: a missing Maps key or an unresolvable address leaves a
    `locatie` block with `status: "indisponibil"` and the report renders the
    rest of its sections normally.
    """
    if date_audit.get("locatie", {}).get("status") == "success":
        return date_audit
    try:
        date_audit["locatie"] = imagery.build_location_block(
            date_audit.get("adresa") or "",
            fallback=date_audit.get("complex_name"),
            radius_m=500,
            lat=date_audit.get("lat"),
            lon=date_audit.get("lon"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Nu s-a putut compune blocul de locație: %s", exc)
        date_audit["locatie"] = {"status": "indisponibil", "motiv": str(exc)}
    return date_audit


@router.get("/demo")
async def get_demo_audit() -> dict[str, Any]:
    """Returnează setul de date demonstrativ complet pentru inspecția instantanee a interfeței."""
    demo_copy = _with_location(dict(DEMO_AUDIT_DATA))
    pdf_path = generator_pdf.genereaza_raport_complet_pdf(demo_copy)
    filename = Path(pdf_path).name
    pdf_url = f"/api/audit/pdf/{filename}"
    return {
        "status": "success",
        "data": demo_copy,
        "date_audit": demo_copy,
        "pdf_url": pdf_url,
        "pdf_download_url": pdf_url,
        "mesaj": "Set de date demonstrativ încărcat cu succes.",
    }


@router.post("/generate")
async def generate_audit_report(request: AuditRequest) -> dict[str, Any]:
    """Generează raportul complet de audit și fișierul PDF oficial."""
    query = (request.url_sau_id or request.url or "demo").strip()
    is_demo = request.demo_mode or request.is_demo

    # Verificare dacă se solicită mod demo
    if is_demo or query.lower() in ("demo", "test", "aviatiei", "sample"):
        demo_copy = _with_location(dict(DEMO_AUDIT_DATA))
        # Generare PDF din datele demo
        pdf_path = generator_pdf.genereaza_raport_complet_pdf(demo_copy)
        filename = Path(pdf_path).name
        pdf_url = f"/api/audit/pdf/{filename}"
        return {
            "status": "success",
            "data": demo_copy,
            "date_audit": demo_copy,
            "cale_pdf": pdf_path,
            "pdf_url": pdf_url,
            "pdf_download_url": pdf_url,
            "mesaj": "Raport demonstrativ generat cu succes.",
        }

    try:
        # Rulare pipeline complet din server.py
        result = server.genereaza_raport_complet_pdf(
            adresa_sau_identificator=query,
        )
        pdf_path = result.get("cale_pdf", "")
        filename = Path(pdf_path).name if pdf_path else ""
        date_audit = result.get("date_audit") or {
            "id": result.get("proprietate_id"),
            "titlu": result.get("titlu"),
            "adresa": query,
        }
        date_audit = _with_location(date_audit)
        pdf_url = f"/api/audit/pdf/{filename}" if filename else ""

        return {
            "status": "success",
            "data": date_audit,
            "date_audit": date_audit,
            "cale_pdf": pdf_path,
            "pdf_url": pdf_url,
            "pdf_download_url": pdf_url,
            "mesaj": result.get("mesaj", "Raport generat cu succes."),
        }
    except Exception as exc:
        logger.exception("Eroare la generarea raportului de audit: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Eroare la generarea raportului: {exc!s}",
        ) from exc


@router.get("/pdf/{filename}")
async def download_pdf_report(filename: str) -> FileResponse:
    """Descarcă fișierul PDF oficial generat."""
    # Protecție împotriva Directory Traversal
    safe_name = os.path.basename(filename)
    if safe_name != filename or not re.match(r"^[a-zA-Z0-9_\-\.]+\.pdf$", safe_name):
        raise HTTPException(status_code=400, detail="Nume de fișier PDF invalid.")

    # Căutare în directoarele de ieșire uzuale
    possible_dirs = [
        paths.reports_dir(),
        Path("/tmp"),
        Path(os.getcwd()) / "reports",
        Path("/app/reports"),
    ]

    target_file = None
    for directory in possible_dirs:
        candidate = directory / safe_name
        if candidate.is_file():
            target_file = candidate
            break

    if not target_file:
        raise HTTPException(status_code=404, detail="Raportul PDF nu a fost găsit.")

    return FileResponse(
        path=str(target_file),
        media_type="application/pdf",
        filename=safe_name,
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


# --------------------------------------------------------------------------
# Location & imagery
#
# Every Google-billed image is fetched server-side and proxied through here, so
# the Maps key is never shipped to the browser and the process-wide cache in
# `imagery.py` absorbs repeat views of the same report.
# --------------------------------------------------------------------------

# Browsers may cache proxied imagery for a day; the upstream photos do not move.
_IMAGE_CACHE_HEADER = "public, max-age=86400"


@router.get("/location")
async def get_location(
    adresa: str = Query(..., description="Adresa proprietății"),
    raza_m: int = Query(500, ge=100, le=2000, description="Raza de căutare a facilităților"),
    lat: float | None = Query(None, description="Latitudine cunoscută (sare peste geocodare)"),
    lon: float | None = Query(None, description="Longitudine cunoscută"),
) -> dict[str, Any]:
    """Coordonate, URL-uri de imagini reale și facilitățile din rază."""
    return imagery.build_location_block(adresa, radius_m=raza_m, lat=lat, lon=lon)


@router.get("/imagery/roadmap")
async def get_roadmap_image(
    lat: float = Query(...),
    lon: float = Query(...),
    zoom: int = Query(15, ge=10, le=20),
    w: int = Query(640, ge=160, le=640),
    h: int = Query(480, ge=160, le=640),
) -> Response:
    """Harta rutieră de bază peste care interfața desenează pinii facilităților."""
    payload = imagery.roadmap_image(lat, lon, zoom, w, h)
    if payload is None:
        raise HTTPException(status_code=503, detail="Harta Google nu este disponibilă.")
    return Response(
        content=payload,
        media_type="image/png",
        headers={"Cache-Control": _IMAGE_CACHE_HEADER},
    )


@router.get("/imagery/aerial")
async def get_aerial_image(
    lat: float = Query(...),
    lon: float = Query(...),
    zoom: int = Query(18, ge=12, le=20),
    w: int = Query(640, ge=160, le=640),
    h: int = Query(480, ge=160, le=640),
) -> Response:
    """Ortofotoplan / imagine satelitară reală a imobilului și a incintei."""
    payload, attribution = imagery.aerial_image(lat, lon, zoom, w, h)
    if payload is None:
        raise HTTPException(status_code=503, detail="Imaginea aeriană nu este disponibilă.")
    media_type = "image/png" if payload[:4] == b"\x89PNG" else "image/jpeg"
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Cache-Control": _IMAGE_CACHE_HEADER, "X-Image-Attribution": attribution},
    )


@router.get("/imagery/streetview")
async def get_street_view_image(
    lat: float = Query(...),
    lon: float = Query(...),
    heading: int = Query(0, ge=0, le=359),
    fov: int = Query(90, ge=20, le=120),
    pitch: int = Query(8, ge=-90, le=90),
    w: int = Query(640, ge=160, le=640),
    h: int = Query(420, ge=160, le=640),
) -> Response:
    """Fotografie Google Street View a clădirii, pe un unghi dat."""
    payload = imagery.street_view_image(lat, lon, heading, w, h, fov=fov, pitch=pitch)
    if payload is None:
        raise HTTPException(status_code=404, detail="Nu există imagini Street View pentru punct.")
    return Response(
        content=payload,
        media_type="image/jpeg",
        headers={"Cache-Control": _IMAGE_CACHE_HEADER},
    )
