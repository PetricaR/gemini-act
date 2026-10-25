"""Scorul de accesibilitate al unei locații (0-100%), pe facilitățile din jur.

Stă în `mcp/` pentru că evaluarea îl cere pentru fiecare proprietate
(`mcp/server.py::evaluare`), iar nucleul nu are voie să importe din
`agent_tools/` — direcția merge doar dinspre suprafețe către nucleu.
`agent_tools/maps.py` expune același calcul ca tool de agent, printr-un wrapper
subțire peste funcția de aici.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from imobiliare.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT = 25.0
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

ACCESSIBILITY_CATEGORIES: dict[str, tuple[str, str]] = {
    "metrou_si_tranzit": ("subway_station", "Stații de metrou și transport public"),
    "supermarket": ("supermarket", "Supermarketuri și magazine alimentare"),
    "farmacie": ("pharmacy", "Farmacii"),
    "banca": ("bank", "Bănci și bancomate"),
    "scoala": ("school", "Școli și grădinițe"),
    "parc": ("park", "Parcuri și spații verzi"),
}

def _key() -> str:
    return get_settings().maps_api_key or ""

def _require_key() -> str | None:
    if not _key():
        return (
            "Google Maps API Key nu este configurat. "
            "Setați GEMINI_ACT_MAPS_API_KEY în variabilele de mediu."
        )
    return None

def _parse_coords(coord_str: str) -> tuple[float, float] | None:
    parts = coord_str.split(",")
    if len(parts) == 2:
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            pass
    return None

def _resolve_lat_lon(location_query: str) -> tuple[float, float, str] | None:
    coords = _parse_coords(location_query)
    if coords:
        return coords[0], coords[1], location_query

    # Geocode address
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(
                GEOCODE_URL,
                params={"address": location_query, "key": _key(), "language": "ro"},
            )
            data = resp.json()
            if data.get("status") == "OK" and data.get("results"):
                res = data["results"][0]
                loc = res["geometry"]["location"]
                return loc["lat"], loc["lng"], res.get("formatted_address", location_query)
    except Exception as e:
        logger.warning("Geocoding failed for '%s': %s", location_query, e)
    return None

def calculeaza_scor_accesibilitate(adresa_sau_coordonate: str) -> dict[str, Any]:
    """Calculează scorul de accesibilitate (0-100%) al unei locații bazat pe facilități apropiate.

    Evaluează transportul public/metrou, supermarketurile, farmaciile, băncile,
    școlile și parcurile pe o rază de 1.000m.

    Args:
        adresa_sau_coordonate: Adresa sau coordonatele "lat,lng" ale locației analizate.

    Returns:
        Scor de accesibilitate (0-100%), rating calitativ (Excelent, Bun, Moderat, Scăzut)
        și defalcarea detaliată a facilităților găsite.
    """
    err = _require_key()
    if err:
        return {"status": "error", "mesaj": err}

    resolved = _resolve_lat_lon(adresa_sau_coordonate)
    if not resolved:
        msg = f"Locația '{adresa_sau_coordonate}' nu a putut fi găsită."
        return {"status": "error", "mesaj": msg}

    lat, lon, formatted_addr = resolved

    breakdown: dict[str, Any] = {}
    total_score = 0.0
    max_score = len(ACCESSIBILITY_CATEGORIES) * 10.0

    field_mask = (
        "places.displayName,places.location,places.rating,"
        "places.userRatingCount,places.shortFormattedAddress"
    )

    with httpx.Client(timeout=TIMEOUT) as client:
        for cat_key, (place_type, label) in ACCESSIBILITY_CATEGORIES.items():
            try:
                body = {
                    "includedTypes": [place_type],
                    "maxResultCount": 10,
                    "locationRestriction": {
                        "circle": {
                            "center": {"latitude": lat, "longitude": lon},
                            "radius": 1000.0,
                        }
                    },
                }
                resp = client.post(
                    PLACES_NEARBY_URL,
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Goog-Api-Key": _key(),
                        "X-Goog-FieldMask": field_mask,
                    },
                )
                places = resp.json().get("places", []) if resp.status_code == 200 else []
            except Exception:
                places = []

            count = len(places)
            cat_score = min(count * 2.0, 10.0)
            total_score += cat_score

            top_places = []
            for p in places[:3]:
                name = (p.get("displayName") or {}).get("text") or "Fără nume"
                rating = p.get("rating")
                top_places.append(f"{name}" + (f" ({rating}★)" if rating else ""))

            breakdown[cat_key] = {
                "categorie": label,
                "numar_gasite": count,
                "scor_categorie": cat_score,
                "disponibil": count > 0,
                "exemple": top_places,
            }

    final_score = round((total_score / max_score) * 100.0, 1) if max_score > 0 else 0.0
    if final_score >= 80:
        calificativ = "Excelent"
    elif final_score >= 60:
        calificativ = "Bun"
    elif final_score >= 40:
        calificativ = "Moderat"
    else:
        calificativ = "Scăzut"

    return {
        "status": "success",
        "locatie": formatted_addr,
        "coordonate": {"lat": lat, "lon": lon},
        "scor_accesibilitate": final_score,
        "calificativ": calificativ,
        "detalii_categorii": breakdown,
    }
