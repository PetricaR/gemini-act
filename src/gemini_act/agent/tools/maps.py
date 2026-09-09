"""Google Maps Platform tools for the Gemini Act agent.

Exposes location intelligence tools adapted from Google Maps APIs:
- geocodare_adresa: address to coordinates and vice versa
- calculeaza_scor_accesibilitate: 0-100% composite accessibility score
- calculeaza_traseu: turn-by-turn routing with distance and duration
- matrice_distante: commute matrix across multiple origins and destinations
- cauta_locuri_in_apropiere: find amenities nearby with ratings and distance
- detalii_locatie: detailed place information (hours, website, rating)

All tools gracefully degrade when GEMINI_ACT_MAPS_API_KEY is unset.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from gemini_act.config import get_settings

logger = logging.getLogger(__name__)

TIMEOUT = 25.0
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places"

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


def geocodare_adresa(adresa_sau_coordonate: str) -> dict[str, Any]:
    """Convertește o adresă text în coordonate GPS sau coordonate în adresă (reverse geocoding).

    Args:
        adresa_sau_coordonate: Adresa completă (ex: "Bulevardul Unirii 10, București")
            sau coordonate "lat,lng" (ex: "44.4268,26.1025").

    Returns:
        Coordonate GPS, adresă formatată, place_id și precizia localizării.
    """
    err = _require_key()
    if err:
        return {"status": "error", "mesaj": err}

    coords = _parse_coords(adresa_sau_coordonate)
    params: dict[str, Any] = {"key": _key(), "language": "ro"}
    if coords:
        params["latlng"] = f"{coords[0]},{coords[1]}"
    else:
        params["address"] = adresa_sau_coordonate

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(GEOCODE_URL, params=params)
            data = resp.json()

        if data.get("status") != "OK" or not data.get("results"):
            return {
                "status": "error",
                "mesaj": f"Nu s-au găsit rezultate: {data.get('status', 'necunoscut')}",
            }

        res = data["results"][0]
        geometry = res.get("geometry", {})
        loc = geometry.get("location", {})

        return {
            "status": "success",
            "adresa_formatata": res.get("formatted_address"),
            "latitudine": loc.get("lat"),
            "longitudine": loc.get("lng"),
            "tip_localizare": geometry.get("location_type"),
            "place_id": res.get("place_id"),
        }
    except Exception as exc:
        logger.exception("Geocoding failed")
        return {"status": "error", "mesaj": str(exc)}


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


def calculeaza_traseu(
    origine: str, destinatie: str, mod: str = "driving"
) -> dict[str, Any]:
    """Calculează un traseu între două puncte, cu durată, distanță și instrucțiuni pas cu pas.

    Args:
        origine: Adresa de plecare sau coordonate "lat,lng".
        destinatie: Adresa de sosire sau coordonate "lat,lng".
        mod: Modul de deplasare: 'driving', 'walking', 'bicycling' sau 'transit'.

    Returns:
        Distanța totală, durata estimată și pașii traseului.
    """
    err = _require_key()
    if err:
        return {"status": "error", "mesaj": err}

    valid_modes = {"driving", "walking", "bicycling", "transit"}
    travel_mode = mod.lower() if mod.lower() in valid_modes else "driving"

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(
                DIRECTIONS_URL,
                params={
                    "origin": origine,
                    "destination": destinatie,
                    "mode": travel_mode,
                    "language": "ro",
                    "key": _key(),
                },
            )
            data = resp.json()

        if data.get("status") != "OK" or not data.get("routes"):
            return {
                "status": "error",
                "mesaj": f"Nu s-a găsit traseu: {data.get('status', 'necunoscut')}",
            }

        route = data["routes"][0]
        leg = route["legs"][0]

        steps = []
        for s in leg.get("steps", [])[:8]:
            instr = s.get("html_instructions", "").replace("<b>", "").replace("</b>", "")
            dist_text = s.get("distance", {}).get("text")
            dur_text = s.get("duration", {}).get("text")
            steps.append(f"{instr} ({dist_text}, {dur_text})")

        return {
            "status": "success",
            "origine": leg.get("start_address"),
            "destinatie": leg.get("end_address"),
            "mod_transport": travel_mode,
            "distanta": leg.get("distance", {}).get("text"),
            "durata": leg.get("duration", {}).get("text"),
            "durata_secunde": leg.get("duration", {}).get("value"),
            "distanta_metri": leg.get("distance", {}).get("value"),
            "instructiuni_principale": steps,
        }
    except Exception as exc:
        logger.exception("Directions failed")
        return {"status": "error", "mesaj": str(exc)}


def matrice_distante(
    origini: list[str], destinatii: list[str], mod: str = "driving"
) -> dict[str, Any]:
    """Calculează o matrice de distanțe și durate între mai multe origini și destinații.

    Utilă pentru a compara timpii de navetă de la diferite proprietăți către birou sau centru.

    Args:
        origini: Listă de adrese sau coordonate de plecare.
        destinatii: Listă de adrese sau coordonate de destinație.
        mod: Mod de deplasare: 'driving', 'walking', 'bicycling' sau 'transit'.

    Returns:
        Matrice cu timpi și distanțe pentru fiecare pereche origine-destinație.
    """
    err = _require_key()
    if err:
        return {"status": "error", "mesaj": err}

    valid_modes = {"driving", "walking", "bicycling", "transit"}
    travel_mode = mod.lower() if mod.lower() in valid_modes else "driving"

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(
                DISTANCE_MATRIX_URL,
                params={
                    "origins": "|".join(origini),
                    "destinations": "|".join(destinatii),
                    "mode": travel_mode,
                    "language": "ro",
                    "key": _key(),
                },
            )
            data = resp.json()

        if data.get("status") != "OK":
            return {
                "status": "error",
                "mesaj": f"Eroare calcul matrice: {data.get('status', 'necunoscut')}",
            }

        origin_addrs = data.get("origin_addresses", [])
        dest_addrs = data.get("destination_addresses", [])
        rows_data = []

        for i, row in enumerate(data.get("rows", [])):
            orig_name = origin_addrs[i] if i < len(origin_addrs) else f"Origine {i+1}"
            elements = []
            for j, elem in enumerate(row.get("elements", [])):
                dest_name = dest_addrs[j] if j < len(dest_addrs) else f"Destinație {j+1}"
                if elem.get("status") == "OK":
                    elements.append({
                        "destinatie": dest_name,
                        "distanta": elem.get("distance", {}).get("text"),
                        "durata": elem.get("duration", {}).get("text"),
                    })
                else:
                    elements.append({"destinatie": dest_name, "status": elem.get("status")})
            rows_data.append({"origine": orig_name, "rezultate": elements})

        return {
            "status": "success",
            "mod_transport": travel_mode,
            "matrice": rows_data,
        }
    except Exception as exc:
        logger.exception("Distance matrix failed")
        return {"status": "error", "mesaj": str(exc)}


def cauta_locuri_in_apropiere(
    adresa_sau_coordonate: str, tip_facilitate: str = "supermarket", raza_m: int = 1000
) -> dict[str, Any]:
    """Caută facilități sau puncte de interes în apropierea unei adrese/coordonate.

    Args:
        adresa_sau_coordonate: Adresa sau coordonate 'lat,lng'.
        tip_facilitate: Tipul facilității ('supermarket', 'school', 'park', 'pharmacy',
            'restaurant', 'subway_station', 'gym', 'hospital', etc.).
        raza_m: Raza de căutare în metri (implicit 1000m, maxim 5000m).

    Returns:
        Listă de locuri găsite cu denumire, rating, recenzii și adresă.
    """
    err = _require_key()
    if err:
        return {"status": "error", "mesaj": err}

    resolved = _resolve_lat_lon(adresa_sau_coordonate)
    if not resolved:
        return {"status": "error", "mesaj": f"Locația '{adresa_sau_coordonate}' nu a fost găsită."}

    lat, lon, formatted_addr = resolved
    radius = min(max(raza_m, 100), 5000)

    field_mask = (
        "places.id,places.displayName,places.rating,places.userRatingCount,"
        "places.shortFormattedAddress,places.location"
    )

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(
                PLACES_NEARBY_URL,
                json={
                    "includedTypes": [tip_facilitate],
                    "maxResultCount": 15,
                    "locationRestriction": {
                        "circle": {
                            "center": {"latitude": lat, "longitude": lon},
                            "radius": float(radius),
                        }
                    },
                },
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": _key(),
                    "X-Goog-FieldMask": field_mask,
                },
            )
            data = resp.json()

        places = []
        for p in data.get("places", []):
            places.append({
                "nume": (p.get("displayName") or {}).get("text") or "Fără nume",
                "adresa": p.get("shortFormattedAddress"),
                "rating": p.get("rating"),
                "numar_recenzii": p.get("userRatingCount"),
                "place_id": p.get("id"),
            })

        return {
            "status": "success",
            "locatie_centru": formatted_addr,
            "tip_cautat": tip_facilitate,
            "raza_metri": radius,
            "total_gasite": len(places),
            "locuri": places,
        }
    except Exception as exc:
        logger.exception("Nearby search failed")
        return {"status": "error", "mesaj": str(exc)}


def detalii_locatie(place_id: str) -> dict[str, Any]:
    """Obține detalii complete despre un loc specific după ID-ul său Google Maps (place_id).

    Args:
        place_id: ID-ul unic Google Maps al locului (ex: din rezultatele de căutare).

    Returns:
        Informații detaliate: nume, adresă completă, telefon, website, program de lucru, rating.
    """
    err = _require_key()
    if err:
        return {"status": "error", "mesaj": err}

    field_mask = (
        "displayName,formattedAddress,nationalPhoneNumber,websiteUri,"
        "regularOpeningHours,rating,userRatingCount,googleMapsUri"
    )

    try:
        url = f"{PLACE_DETAILS_URL}/{place_id}"
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(
                url,
                headers={
                    "X-Goog-Api-Key": _key(),
                    "X-Goog-FieldMask": field_mask,
                },
                params={"languageCode": "ro"},
            )
            data = resp.json()

        if resp.status_code != 200:
            return {
                "status": "error",
                "mesaj": f"Eroare obținere detalii: {data.get('error', {}).get('message')}",
            }

        hours = data.get("regularOpeningHours", {}).get("weekdayDescriptions", [])

        return {
            "status": "success",
            "nume": (data.get("displayName") or {}).get("text"),
            "adresa": data.get("formattedAddress"),
            "telefon": data.get("nationalPhoneNumber"),
            "website": data.get("websiteUri"),
            "link_google_maps": data.get("googleMapsUri"),
            "rating": data.get("rating"),
            "numar_recenzii": data.get("userRatingCount"),
            "program_lucru": hours,
        }
    except Exception as exc:
        logger.exception("Place details failed")
        return {"status": "error", "mesaj": str(exc)}


MAPS_TOOLS = [
    geocodare_adresa,
    calculeaza_scor_accesibilitate,
    calculeaza_traseu,
    matrice_distante,
    cauta_locuri_in_apropiere,
    detalii_locatie,
]
