"""Normalise listings into flat, typed records that can be filtered and sorted.

The hydrate endpoint returns two views of every listing:

* display fields formatted for humans -- ``"108.000 €"``, ``"405 m (5 min)"``,
  ``"Etaj 2 / 4"``;
* a ``tracking.ga4Item`` analytics block with mostly clean typed values --
  seller type, area, year built, days on market.

The analytics block is richer and easier to trust, with one important
exception: its ``price`` is a ``0.2`` placeholder on some listings (16 of 240
in one sample), so the displayed price stays authoritative and ga4 is only a
fallback. Everything is normalised once, up front, by :func:`normalise`.
"""

from __future__ import annotations

import re
from typing import Any

_PRICE = re.compile(r"([\d.]+)\s*€")           # "108.000 €" -- "." is a thousands sep
_DISTANCE = re.compile(r"([\d.,]+)\s*(km|m)\b")  # "405 m (5 min)" / "1,2 km"
_FIRST_INT = re.compile(r"(\d+)")
_FIRST_NUM = re.compile(r"(\d+(?:[.,]\d+)?)")
_FLOOR = re.compile(r"(?:Etaj\s*(\d+)|(Parter)|(Demisol)|(Mansard))", re.I)
_FLOOR_TOTAL = re.compile(r"/\s*(\d+)")

# ga4 uses these as "no value"; treat them as missing rather than as data.
_GA4_NULLS = {"not applicable", "0", "", "none"}


def _ga4(listing: dict[str, Any]) -> dict[str, Any]:
    return (listing.get("tracking") or {}).get("ga4Item") or {}


def _num(value: Any) -> float | None:
    """ga4 mixes int, float and numeric strings in the same field."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _FIRST_NUM.search(str(value))
    return float(m.group(1).replace(",", ".")) if m else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return None if s.lower() in _GA4_NULLS else s


def _highlight(listing: dict[str, Any], key: str) -> str | None:
    for h in listing.get("highlights") or []:
        if (h.get("key") or "") == key:
            return h.get("label")
    return None


def _features(listing: dict[str, Any]) -> set[str]:
    return {(f.get("title") or "").strip() for f in listing.get("extraFeatures") or []}


def _floor(label: str | None) -> tuple[int | None, int | None]:
    """'Etaj 2 / 4' -> (2, 4); 'Parter / 4' -> (0, 4); 'Etaj 2' -> (2, None)."""
    if not label:
        return None, None
    total = _FLOOR_TOTAL.search(label)
    m = _FLOOR.search(label)
    floor: int | None = None
    if m:
        if m.group(1):
            floor = int(m.group(1))
        elif m.group(2):
            floor = 0          # parter
        elif m.group(3):
            floor = -1         # demisol
        elif m.group(4):
            floor = 99         # mansardă -- always the top
    return floor, int(total.group(1)) if total else None


def normalise(listing: dict[str, Any], explanation: dict[str, str] | None = None) -> dict[str, Any]:
    """Flatten one raw listing into a typed record."""
    g = _ga4(listing)
    feats = _features(listing)

    m = _PRICE.search((listing.get("price") or "").replace("\xa0", " "))
    price: float | None = int(m.group(1).replace(".", "")) if m else None
    if price is None:
        fallback = _num(g.get("price"))
        # Guard against the 0.2 placeholder seen in the analytics block.
        price = fallback if fallback and fallback >= 1000 else None

    surface = _num(_highlight(listing, "usable_surface")) or _num(g.get("propertySurface"))

    dist = None
    if dm := _DISTANCE.search(listing.get("metroDistance") or ""):
        dist = float(dm.group(1).replace(",", ".")) * (1000 if dm.group(2) == "km" else 1)

    rooms = None
    if rl := _highlight(listing, "bedroom_count"):
        if rm := _FIRST_INT.search(rl):
            rooms = int(rm.group(1))

    year = _num(_text(g.get("propertyYear")))
    if year is None and (yl := _highlight(listing, "year_built")):
        year = _num(yl)

    floor, floors_total = _floor(_highlight(listing, "floor_number"))
    days = _num(g.get("propertyDaysInMarket"))

    record = {
        "id": listing.get("id"),
        "title": listing.get("heading"),
        "url": "https://www.imobiliare.ro" + (listing.get("url") or ""),
        # money
        "price_eur": int(price) if price else None,
        "price_per_sqm": round(price / surface) if price and surface else None,
        "price_dropped": bool(listing.get("priceChange")),
        # size / layout
        "rooms": rooms,
        "surface_sqm": surface,
        "floor": floor,
        "floors_total": floors_total,
        "year_built": int(year) if year else None,
        # location
        "location": listing.get("location"),
        # Present only when the seller published an exact location; it is what
        # makes a street-level geocode possible instead of a neighbourhood one.
        "address_text": listing.get("address"),
        "area": _text(g.get("propertyArea")),
        "city": _text(g.get("propertyCity")),
        "county": _text(g.get("propertyCounty")),
        "metro_distance_m": dist,
        "metro_label": listing.get("metroDistance"),
        "exact_location": "Locație exactă" in feats or "Locație Verificată" in feats,
        # seller / offer
        "seller_type": _text(g.get("sellerType")),          # agency | individual | developer
        "agency": listing.get("agencyName"),
        "commission_zero": "Comision 0%" in feats,
        "exclusive": "Exclusivitate" in feats,
        "vacant": "Proprietate nelocuită" in feats,
        # freshness / condition
        "days_on_market": int(days) if days is not None else None,
        "listed": listing.get("createdAt"),
        "is_new_build": _text(g.get("item_category4")) == "new",
        # media
        "photos": len(listing.get("images") or []),
        # The gallery is the only window onto condition and layout that a
        # remote analysis has; keeping the urls lets a caller actually look.
        "image_urls": [i.get("src") for i in (listing.get("images") or []) if i.get("src")],
        "has_video": bool(listing.get("hasVideo")),
        "has_virtual_tour": bool(listing.get("hasVirtualTour")),
        "has_floor_plan": bool(listing.get("hasPlans")),
        "description": listing.get("descriptionPreview"),
    }
    if explanation:
        record["ai_match"] = explanation
    return record


# Kept as the previous public name so callers don't have to change.
summarise = normalise

SORTS = {
    "metro": lambda r: (_or_inf(r["metro_distance_m"]), _or_inf(r["price_eur"])),
    "price": lambda r: (_or_inf(r["price_eur"]),),
    "price_desc": lambda r: (-(r["price_eur"] or 0),),
    "price_per_sqm": lambda r: (_or_inf(r["price_per_sqm"]),),
    "surface": lambda r: (-(r["surface_sqm"] or 0),),
    "newest": lambda r: (_or_inf(r["days_on_market"]),),
    "year_built": lambda r: (-(r["year_built"] or 0),),
    "relevance": None,  # keep the AI's own ordering
}


def _or_inf(value: float | int | None) -> float:
    """Missing values must never sort ahead of real ones."""
    return float("inf") if value is None else float(value)


def filter_and_rank(
    records: list[dict[str, Any]],
    *,
    # money
    max_price: int | None = None,
    min_price: int | None = None,
    max_price_per_sqm: int | None = None,
    price_dropped: bool | None = None,
    # size / layout
    rooms_exact: int | None = None,
    min_rooms: int | None = None,
    max_rooms: int | None = None,
    min_sqm: float | None = None,
    max_sqm: float | None = None,
    min_floor: int | None = None,
    max_floor: int | None = None,
    exclude_ground_floor: bool = False,
    exclude_top_floor: bool = False,
    min_year_built: int | None = None,
    max_year_built: int | None = None,
    # location
    max_metro_m: float | None = None,
    area: str | None = None,
    city: str | None = None,
    exact_location_only: bool = False,
    # seller / offer
    seller_type: str | None = None,
    commission_zero: bool | None = None,
    exclusive: bool | None = None,
    new_build: bool | None = None,
    # freshness / media
    max_days_on_market: int | None = None,
    has_video: bool | None = None,
    has_virtual_tour: bool | None = None,
    has_floor_plan: bool | None = None,
    min_photos: int | None = None,
    sort_by: str = "metro",
) -> list[dict[str, Any]]:
    """Apply hard constraints to normalised records.

    A range check against a missing value drops the listing: a listing whose
    price we could not read cannot be shown to satisfy "under 220k".
    """
    if sort_by not in SORTS:
        raise ValueError(f"unknown sort_by {sort_by!r}; expected one of {sorted(SORTS)}")

    def keep(r: dict[str, Any]) -> bool:
        checks = (
            (max_price, r["price_eur"], lambda v, x: x <= v),
            (min_price, r["price_eur"], lambda v, x: x >= v),
            (max_price_per_sqm, r["price_per_sqm"], lambda v, x: x <= v),
            (rooms_exact, r["rooms"], lambda v, x: x == v),
            (min_rooms, r["rooms"], lambda v, x: x >= v),
            (max_rooms, r["rooms"], lambda v, x: x <= v),
            (min_sqm, r["surface_sqm"], lambda v, x: x >= v),
            (max_sqm, r["surface_sqm"], lambda v, x: x <= v),
            (min_floor, r["floor"], lambda v, x: x >= v),
            (max_floor, r["floor"], lambda v, x: x <= v),
            (min_year_built, r["year_built"], lambda v, x: x >= v),
            (max_year_built, r["year_built"], lambda v, x: x <= v),
            (max_metro_m, r["metro_distance_m"], lambda v, x: x <= v),
            (max_days_on_market, r["days_on_market"], lambda v, x: x <= v),
            (min_photos, r["photos"], lambda v, x: x >= v),
            (area, r["area"], lambda v, x: v.lower() in x.lower()),
            (city, r["city"], lambda v, x: v.lower() in x.lower()),
            (seller_type, r["seller_type"], lambda v, x: x == v),
        )
        for wanted, actual, ok in checks:
            if wanted is not None and (actual is None or not ok(wanted, actual)):
                return False

        flags = (
            (price_dropped, r["price_dropped"]),
            (commission_zero, r["commission_zero"]),
            (exclusive, r["exclusive"]),
            (new_build, r["is_new_build"]),
            (has_video, r["has_video"]),
            (has_virtual_tour, r["has_virtual_tour"]),
            (has_floor_plan, r["has_floor_plan"]),
        )
        for wanted, actual in flags:
            if wanted is not None and bool(actual) is not wanted:
                return False

        if exact_location_only and not r["exact_location"]:
            return False
        if exclude_ground_floor and r["floor"] is not None and r["floor"] <= 0:
            return False
        if exclude_top_floor and r["floor"] is not None and r["floors_total"] is not None \
                and r["floor"] >= r["floors_total"]:
            return False
        return True

    kept = [r for r in records if keep(r)]
    key = SORTS[sort_by]
    return kept if key is None else sorted(kept, key=key)
