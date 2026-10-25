"""Anunțuri de pe storia.ro, aduse în aceeași formă ca cele de pe imobiliare.ro.

storia.ro e un Next.js: pagina poartă tot anunțul, deja structurat, într-un
`__NEXT_DATA__`. Nu e nevoie nici de sesiune capturată din browser (ca la
căutarea pe imobiliare.ro), nici de browserul headless — un simplu GET ajunge,
ceea ce face calea asta mai robustă decât cea de pe imobiliare.ro, nu mai puțin.

Tot ce iese de aici respectă exact cheile produse de `parse.normalise`, pentru
că restul conductei — comparabile, evaluarea GEV 630, raportul, PDF-ul — citește
acele chei și nu trebuie să știe de pe ce site a venit anunțul.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.storia.ro"
TIMEOUT = 40.0
# Fără un User-Agent de browser, storia răspunde cu o pagină de provocare.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_NEXT_DATA = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_HOST = re.compile(r"^https?://(?:www\.)?storia\.ro/", re.I)
# Slug-ul se termină în ID + un cod scurt: .../oferta/3-camere-...-IDIxfT
_ID_DIN_SLUG = re.compile(r"-(ID[A-Za-z0-9]+)/?$")


class StoriaIndisponibil(RuntimeError):
    """Anunțul nu a putut fi citit de pe storia.ro."""


def este_url_storia(text: str) -> bool:
    """Dacă textul e un link de anunț storia.ro."""
    return bool(_HOST.match((text or "").strip()))


def id_din_url(url: str) -> str | None:
    """Codul din slug (`IDIxfT`), cel pe care îl vede utilizatorul în link."""
    m = _ID_DIN_SLUG.search((url or "").split("?")[0].strip())
    return m.group(1) if m else None


def _ad(url: str) -> dict[str, Any]:
    """Anunțul brut din `__NEXT_DATA__`."""
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA})
    except httpx.HTTPError as exc:
        raise StoriaIndisponibil(f"storia.ro nu a răspuns: {exc}") from exc
    if resp.status_code != 200:
        raise StoriaIndisponibil(f"storia.ro a răspuns {resp.status_code} pentru {url}")
    m = _NEXT_DATA.search(resp.text)
    if not m:
        raise StoriaIndisponibil(
            "Pagina storia.ro nu conține blocul de date al anunțului. "
            "Fie linkul nu e un anunț, fie site-ul și-a schimbat structura."
        )
    try:
        date = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise StoriaIndisponibil(f"Datele anunțului storia.ro nu se pot citi: {exc}") from exc
    ad = (date.get("props") or {}).get("pageProps", {}).get("ad")
    if not isinstance(ad, dict):
        raise StoriaIndisponibil("Anunțul storia.ro pare expirat sau retras.")
    return ad


def _int(value: Any) -> int | None:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _prim(value: Any) -> Any:
    """Storia dă multe câmpuri ca listă de un element."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _etaj(value: Any) -> int | None:
    """`floor_6` -> 6, `ground_floor` -> 0, mansarda/demisol -> None.

    Parterul trebuie să iasă 0, nu None: evaluarea aplică un discount de parter
    (`ground_floor_discount_default`), iar un None l-ar face să nu se aplice
    niciodată pe anunțurile de aici.
    """
    brut = str(_prim(value) or "").strip().lower()
    if not brut:
        return None
    if brut in ("ground_floor", "parter"):
        return 0
    m = re.search(r"(\d+)", brut)
    return int(m.group(1)) if m else None


def _caracteristici(ad: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c.get("key"): c for c in (ad.get("characteristics") or []) if isinstance(c, dict)}


def _zile_de_la(iso: Any) -> int | None:
    try:
        creat = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return max(0, (datetime.now(UTC) - creat).days)


def _localitate(ad: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """(zonă, oraș, județ) din reverse geocoding, care e singurul consecvent.

    `location.address` vine aproape gol pe anunțurile bucureștene — orașul și
    județul sunt `null` acolo, dar sectorul și municipiul apar corect în lista
    de locații a reverse geocoding-ului.
    """
    loc = ad.get("location") or {}
    niveluri = {
        x.get("locationLevel"): x.get("name")
        for x in ((loc.get("reverseGeocoding") or {}).get("locations") or [])
        if isinstance(x, dict)
    }
    zona = niveluri.get("sector") or niveluri.get("district") or niveluri.get("subdistrict")
    oras = niveluri.get("city") or niveluri.get("municipality") or niveluri.get("county")
    judet = niveluri.get("county") or niveluri.get("province")
    return zona, oras, judet


def normalise(ad: dict[str, Any], url: str = "") -> dict[str, Any]:
    """Anunțul storia, cu cheile pe care le produce `parse.normalise`."""
    target = ad.get("target") or {}
    car = _caracteristici(ad)
    zona, oras, judet = _localitate(ad)
    loc = ad.get("location") or {}
    coord = loc.get("coordinates") or {}
    strada = ((loc.get("address") or {}).get("street") or {}).get("name")

    pret = _int((car.get("price") or {}).get("value")) or _int(target.get("Price"))
    suprafata = _float(target.get("Area")) or _float((car.get("m") or {}).get("value"))
    pe_mp = _float(target.get("Price_per_m")) or _float((car.get("price_per_m") or {}).get("value"))
    if pe_mp is None and pret and suprafata:
        pe_mp = round(pret / suprafata, 2)

    imagini = [i.get("large") or i.get("medium") for i in (ad.get("images") or [])]
    imagini = [i for i in imagini if i]

    adresa = ", ".join(x for x in (strada, zona, oras) if x)

    return {
        "id": str(ad.get("id") or id_din_url(url) or ""),
        "title": ad.get("title"),
        "url": ad.get("url") or url,
        "price_eur": pret,
        "price_per_sqm": pe_mp,
        "price_dropped": None,
        "rooms": _int(_prim(target.get("Rooms_num"))),
        "surface_sqm": suprafata,
        "floor": _etaj(target.get("Floor_no")),
        "floors_total": _int(target.get("Building_floors_num")),
        "year_built": _int(target.get("Build_year")),
        "location": (
            {"lat": coord.get("latitude"), "lon": coord.get("longitude")}
            if coord.get("latitude")
            else None
        ),
        "address_text": adresa or None,
        "area": zona,
        "city": oras,
        "county": judet,
        # storia nu publică distanța la metrou; conducta o calculează singură din
        # coordonate când are cheia Maps, așa că un None aici nu pierde nimic.
        "metro_distance_m": None,
        "metro_label": None,
        "exact_location": bool(coord.get("latitude")),
        "seller_type": "agency" if target.get("user_type") == "agency" else "private",
        "agency": (ad.get("owner") or {}).get("name"),
        "commission_zero": None,
        "exclusive": None,
        "vacant": None,
        "days_on_market": _zile_de_la(ad.get("createdAt")),
        "listed": ad.get("createdAt"),
        "is_new_build": str(target.get("MarketType") or "").lower() == "primary",
        "photos": len(imagini),
        "image_urls": imagini,
        "has_video": bool(ad.get("isAiVideoEnabled")),
        "has_virtual_tour": None,
        "has_floor_plan": bool(ad.get("floorPlans")),
        "description": re.sub(r"<[^>]+>", " ", ad.get("description") or "").strip() or None,
        "source": "storia.ro",
    }


def detalii(url: str) -> dict[str, Any]:
    """Un anunț storia.ro, gata de dus în conducta de evaluare."""
    if not este_url_storia(url):
        raise StoriaIndisponibil(f"{url!r} nu este un link storia.ro.")
    return normalise(_ad(url), url)
