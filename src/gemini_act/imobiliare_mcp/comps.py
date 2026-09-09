"""Comparable sourcing from imobiliare.ro's published sitemaps.

The AI search (`cauta`) needs a browser-originated session and is therefore
unusable unattended. The portal's robots.txt, however, publishes per-county
listing sitemaps, and `hydrate` needs no authentication -- so a comparable
pool can be assembled without a session at all.

Offer slugs carry the area and the room count
(``/oferta/apartament-de-vanzare-sector-3-titan-mobilat-3-camere-275807510``),
which lets us narrow to a few dozen candidates before hydrating any of them.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

SITEMAP = "https://www.imobiliare.ro/sitemap-listings-apartments-for-{deal}-{scope}.xml"
CACHE_DIR = Path.home() / ".cache" / "imobiliare-mcp"
CACHE_TTL = 24 * 3600  # sitemaps are regenerated daily; a day-old pool is fine

_OFFER = re.compile(r"/oferta/apartament-de-(?:vanzare|inchiriat)-(.+?)-(\d+)$")
_ROOMS = re.compile(r"-(\d+)-camere$")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml,text/xml,*/*",
}


@dataclass(frozen=True)
class Offer:
    """One sitemap entry, before hydration."""

    id: str
    slug: str          # e.g. "sector-3-titan-mobilat-3-camere"
    area: str          # e.g. "sector-3-titan"  (the -mobilat marker stripped)
    rooms: int | None
    furnished: bool    # the slug carried the -mobilat marker


def _slugify(value: str) -> str:
    """'Drumul Taberei, Sector 6' -> 'drumul-taberei-sector-6'."""
    stripped = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")


def _parse_offer(url: str) -> Offer | None:
    m = _OFFER.search(url)
    if not m:
        return None
    slug, listing_id = m.group(1), m.group(2)
    rooms = int(rm.group(1)) if (rm := _ROOMS.search(slug)) else None
    area = _ROOMS.sub("", slug)
    furnished = area.endswith("-mobilat")
    if furnished:
        area = area[: -len("-mobilat")]
    return Offer(id=listing_id, slug=slug, area=area, rooms=rooms, furnished=furnished)


def _fetch_cached(url: str, timeout: float = 120.0) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / (_slugify(url) + ".xml")
    if cached.exists() and time.time() - cached.stat().st_mtime < CACHE_TTL:
        return cached.read_text(encoding="utf-8")
    with httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
    cached.write_text(r.text, encoding="utf-8")
    return r.text


def offers(scope: str = "bucuresti", deal: str = "sale") -> list[Offer]:
    """Every listed offer for one county, straight from the published sitemap."""
    xml = _fetch_cached(SITEMAP.format(deal=deal, scope=scope))
    out = []
    for loc in re.findall(r"<loc>(.*?)</loc>", xml):
        if (offer := _parse_offer(loc)) is not None:
            out.append(offer)
    return out


def scope_for(county: str | None, city: str | None) -> str:
    """Map a listing's county onto the sitemap scope segment."""
    slug = _slugify(county or city or "")
    if not slug or "bucuresti" in slug or slug.startswith("sector"):
        return "bucuresti"
    return slug if slug.startswith("judetul-") else f"judetul-{slug}"


def area_slug_of(url: str) -> str | None:
    """The area segment of a subject's own offer URL."""
    offer = _parse_offer(url or "")
    return offer.area if offer else None


def candidates(
    area: str,
    rooms: int | None,
    scope: str = "bucuresti",
    deal: str = "sale",
    exclude: str | None = None,
    widen: bool = True,
) -> list[Offer]:
    """Offers in the same area with the same room count.

    Falls back to the parent sector when a narrow area is too thin -- a
    three-comparable grid is worth less than one drawn from a wider net.
    """
    pool = offers(scope, deal)
    same = [o for o in pool if o.area == area and (rooms is None or o.rooms == rooms)]
    if widen and len(same) < 8:
        # "sector-3-titan" -> "sector-3": keep the sector, drop the neighbourhood.
        if sector := re.match(r"(sector-\d+)", area):
            same = [
                o for o in pool
                if o.area.startswith(sector.group(1)) and (rooms is None or o.rooms == rooms)
            ]
    return [o for o in same if o.id != exclude]


def rank_by_similarity(subject: dict[str, Any], records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Closest comparables first: surface, then age, floor and metro distance.

    Weights follow how much each attribute actually moves price per sqm in
    this market, so the grid's smallest corrections land at the top.
    """
    def distance(r: dict[str, Any]) -> float:
        score = 0.0
        if subject.get("surface_sqm") and r.get("surface_sqm"):
            score += 3.0 * abs(r["surface_sqm"] - subject["surface_sqm"]) / subject["surface_sqm"]
        if subject.get("year_built") and r.get("year_built"):
            score += abs(r["year_built"] - subject["year_built"]) / 25.0
        if subject.get("floor") is not None and r.get("floor") is not None:
            score += abs(r["floor"] - subject["floor"]) / 12.0
        if subject.get("metro_distance_m") and r.get("metro_distance_m"):
            score += abs(r["metro_distance_m"] - subject["metro_distance_m"]) / 1200.0
        return score

    return sorted(records, key=distance)
