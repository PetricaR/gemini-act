"""Where the property actually is, and what stands around it.

Listings carry no coordinates -- only a text address whose precision depends
on whether the seller published an exact location. So the address is geocoded
through Nominatim and the surroundings are read from OpenStreetMap via
Overpass. Both are cached on disk: they are free services and this asks the
same questions repeatedly.

The precision of everything here is inherited from the address. When a
listing hides its exact location, the geocode lands on the neighbourhood and
every distance below is indicative, not measured -- `Place.precision` says
which case you are in and the report repeats the warning.
"""

from __future__ import annotations

import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"
CACHE_DIR = Path.home() / ".cache" / "imobiliare-mcp" / "geo"
CACHE_TTL = 30 * 24 * 3600  # streets and schools do not move

# Nominatim's policy requires a real identifying User-Agent.
UA = "imobiliare-mcp/0.1 (property valuation; contact via repository)"


@dataclass
class Place:
    lat: float
    lon: float
    display: str
    precision: str      # "adresa" | "zona"

    @property
    def map_url(self) -> str:
        return f"https://www.openstreetmap.org/?mlat={self.lat}&mlon={self.lon}#map=17/{self.lat}/{self.lon}"

    @property
    def google_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"


@dataclass
class Poi:
    name: str
    category: str
    distance_m: int
    detail: str = ""
    # Supplied only by the Google Places path; OSM has no notion of either, so
    # these stay None there and the report simply omits the column.
    rating: float | None = None
    ratings_count: int | None = None
    # Actual walking time, seconds. `distance_m` above is a straight line in
    # both paths — for a metro station on the far side of a railway the two are
    # not the same question, and the grid adjusts on metro distance.
    walk_seconds: int | None = None


# What a family actually asks about a neighbourhood, in the order they ask it.
CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "metrou": ("Stații de metrou", ['["station"="subway"]', '["railway"="subway_entrance"]']),
    "scoli": ("Școli", ['["amenity"="school"]']),
    "gradinite": ("Grădinițe și creșe", ['["amenity"="kindergarten"]']),
    "parcuri": ("Parcuri și spații verzi", ['["leisure"="park"]']),
    "joaca": ("Locuri de joacă", ['["leisure"="playground"]']),
    "supermarket": ("Supermarketuri", ['["shop"="supermarket"]']),
    "mall": ("Centre comerciale", ['["shop"="mall"]', '["shop"="department_store"]']),
    "piata": ("Piețe agroalimentare", ['["amenity"="marketplace"]']),
    "farmacii": ("Farmacii", ['["amenity"="pharmacy"]']),
    "medical": ("Unități medicale", ['["amenity"="hospital"]', '["amenity"="clinic"]', '["amenity"="doctors"]']),
    "sport": ("Sport și fitness", ['["leisure"="fitness_centre"]', '["leisure"="sports_centre"]']),
    "transport": ("Transport de suprafață", ['["highway"="bus_stop"]', '["railway"="tram_stop"]']),
}


def _cache(key: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    slug = "".join(c if c.isalnum() else "-" for c in key)[:120]
    return CACHE_DIR / f"{slug}.json"


def _cached_json(key: str, fetch) -> Any:
    path = _cache(key)
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _strip_diacritics(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


_STREET = re.compile(
    r"((?:strada|str\.?|bulevardul|bd\.?|b-dul|calea|aleea|soseaua|șoseaua|intrarea|splaiul)\s+[^,]+)",
    re.I)
_NUMBER = re.compile(r"^\s*(\d+[A-Za-z]?)\s*,")


def _street_query(address: str) -> str | None:
    """Pull just street and number out of a listing address.

    The rest of the label is the seller's own neighbourhood claim, and it is
    not always right -- appending it to the query makes Nominatim fail on a
    contradiction instead of finding the street.
    """
    if not (m := _STREET.search(address)):
        return None
    street = m.group(1).strip()
    number = n.group(1) if (n := _NUMBER.search(address)) else None
    return f"{street} {number}" if number else street


def geocode(address: str | None, fallback: str | None = None) -> Place | None:
    """Resolve a listing's address, falling back to its neighbourhood label.

    A listing that published a street number geocodes to the building; one
    that did not lands on the area centroid, and says so.

    Google Maps answers this when a key is configured — it resolves Romanian
    street addresses far more reliably, and reports its own precision rather
    than leaving it to be inferred. Without a key this is the Nominatim path
    below, unchanged.
    """
    from . import maps

    if (hit := maps.geocode(address, fallback)) is not None:
        return Place(hit.lat, hit.lon, hit.display, hit.precision)

    attempts: list[tuple[str, str]] = []
    if address and (street := _street_query(address)):
        attempts.append((street, "adresa"))
    if address:
        attempts.append((address, "adresa"))
    if fallback:
        attempts.append((fallback, "zona"))

    for candidate, precision in attempts:
        query = f"{_strip_diacritics(candidate)}, Bucuresti, Romania"

        def fetch(q=query):
            with httpx.Client(timeout=30, headers={"User-Agent": UA}) as c:
                r = c.get(NOMINATIM, params={"q": q, "format": "json", "limit": 1,
                                             "addressdetails": 0})
                r.raise_for_status()
                return r.json()

        try:
            results = _cached_json(f"geo-{query}", fetch)
        except Exception:
            continue
        if results:
            hit = results[0]
            # A street-level query that only resolved to a suburb is not an address.
            got = precision
            if precision == "adresa" and hit.get("type") in {"suburb", "neighbourhood", "quarter", "city_district"}:
                got = "zona"
            return Place(float(hit["lat"]), float(hit["lon"]), hit.get("display_name", candidate), got)
    return None


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(r * 2 * math.asin(math.sqrt(a))))


# Nominatim fallback: what to ask for, and which OSM types count as an answer.
NOMINATIM_TERMS: dict[str, tuple[str, set[str]]] = {
    "metrou": ("metrou", {"subway_entrance", "station", "subway"}),
    "scoli": ("scoala", {"school"}),
    "gradinite": ("gradinita", {"kindergarten", "school"}),
    "parcuri": ("parc", {"park", "garden"}),
    "joaca": ("loc de joaca", {"playground"}),
    "supermarket": ("supermarket", {"supermarket", "convenience"}),
    "mall": ("centru comercial", {"mall", "department_store", "retail"}),
    "piata": ("piata agroalimentara", {"marketplace"}),
    "farmacii": ("farmacie", {"pharmacy", "chemist"}),
    "medical": ("spital clinica", {"hospital", "clinic", "doctors"}),
    "sport": ("sala fitness", {"fitness_centre", "sports_centre", "gym"}),
}


@dataclass
class Surroundings:
    pois: dict[str, list[Poi]]
    source: str      # which service answered
    radius_m: int


def _nominatim_surroundings(place: Place, radius_m: int) -> dict[str, list[Poi]]:
    """Bounded free-text search, one category at a time.

    Less exhaustive than Overpass -- it returns what the search index ranks,
    not every tagged object -- but it runs off the host that answers, and the
    report says which service produced the list.
    """
    deg = radius_m / 111_000
    box = f"{place.lon - deg * 1.4},{place.lat + deg},{place.lon + deg * 1.4},{place.lat - deg}"
    out: dict[str, list[Poi]] = {k: [] for k in CATEGORIES}
    for key, (term, types) in NOMINATIM_TERMS.items():
        def fetch(t=term):
            with httpx.Client(timeout=40, headers={"User-Agent": UA}) as c:
                r = c.get(NOMINATIM, params={"q": t, "viewbox": box, "bounded": 1,
                                             "format": "json", "limit": 12})
                r.raise_for_status()
                return r.json()
        try:
            rows = _cached_json(f"poi-nom-{key}-{place.lat:.5f}-{place.lon:.5f}-{radius_m}", fetch)
        except Exception:
            continue
        for row in rows:
            if row.get("type") not in types:
                continue
            lat, lon = float(row["lat"]), float(row["lon"])
            dist = _haversine(place.lat, place.lon, lat, lon)
            if dist > radius_m:
                continue
            name = (row.get("display_name") or "").split(",")[0].strip()
            out[key].append(Poi(name or "(fără nume)", key, dist))
        time.sleep(1.1)   # Nominatim usage policy: at most one request per second
    for key in out:
        seen, uniq = set(), []
        for poi in sorted(out[key], key=lambda x: x.distance_m):
            if poi.name.lower() in seen:
                continue
            seen.add(poi.name.lower())
            uniq.append(poi)
        out[key] = uniq
    return out


def _google_surroundings(place: Place, radius_m: int) -> dict[str, list[Poi]] | None:
    """Places, plus a real walking time to the nearest few metro stations.

    Only the metro entries get the Routes call: it is the one category the grid
    actually adjusts on, and one matrix request for the three closest stations
    is cheap where thirteen categories of them would not be.
    """
    from . import maps

    found = maps.nearby(place.lat, place.lon, radius_m)
    if found is None:
        return None

    out = {
        key: [
            Poi(p.name, p.category, p.distance_m, p.detail,
                rating=p.rating, ratings_count=p.ratings_count)
            for p in items
        ]
        for key, items in found.items()
    }

    # Only the three closest, and only the ones Places gave coordinates for:
    # `walking_times` answers positionally, so the list it is handed and the
    # list its answer is zipped back onto must be the same one.
    stations = [p for p in (found.get("metrou") or []) if p.lat is not None][:3]
    if stations:
        walks = maps.walking_times(place.lat, place.lon, [(p.lat, p.lon) for p in stations])
        if walks:
            by_name = {(p.name, p.distance_m): w for p, w in zip(stations, walks, strict=True)}
            for poi in out["metrou"]:
                poi.walk_seconds = by_name.get((poi.name, poi.distance_m))
    return out


def nearby(place: Place, radius_m: int = 1200) -> Surroundings:
    """Amenities around the property, from whichever service is reachable.

    Google Places first when a key is configured — it is faster than Overpass,
    parallel per category, and carries ratings. Then the two OSM paths, in the
    order they were already tried.
    """
    if (pois := _google_surroundings(place, radius_m)) and any(pois.values()):
        return Surroundings(pois, "Google Maps Platform (Places)", radius_m)
    if pois := surroundings(place, radius_m):
        return Surroundings(pois, "OpenStreetMap / Overpass", radius_m)
    return Surroundings(_nominatim_surroundings(place, radius_m),
                        "OpenStreetMap / Nominatim (Overpass indisponibil)", radius_m)


def surroundings(place: Place, radius_m: int = 1200) -> dict[str, list[Poi]]:
    """Every relevant amenity within walking distance, by category."""
    clauses = []
    for _, (_, selectors) in CATEGORIES.items():
        for sel in selectors:
            for kind in ("node", "way"):
                clauses.append(f'{kind}{sel}(around:{radius_m},{place.lat},{place.lon});')
    query = f"[out:json][timeout:60];({''.join(clauses)});out center tags;"

    def fetch():
        headers = {"User-Agent": UA, "Accept": "application/json",
                   "Content-Type": "application/x-www-form-urlencoded"}
        with httpx.Client(timeout=120, headers=headers) as c:
            r = c.post(OVERPASS, content=f"data={quote(query)}".encode())
            r.raise_for_status()
            return r.json()

    try:
        data = _cached_json(f"poi-{place.lat:.5f}-{place.lon:.5f}-{radius_m}", fetch)
    except Exception:
        return {}
    if not (data.get("elements") or []):
        return {}

    out: dict[str, list[Poi]] = {k: [] for k in CATEGORIES}
    seen: set[tuple] = set()
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        key = _classify(tags)
        if not key:
            continue
        name = tags.get("name") or tags.get("operator") or "(fără nume)"
        dedup = (key, name, round(lat, 4), round(lon, 4))
        if dedup in seen:
            continue
        seen.add(dedup)
        out[key].append(Poi(name, key, _haversine(place.lat, place.lon, lat, lon),
                            _detail(tags)))
    for key in out:
        out[key].sort(key=lambda p: p.distance_m)
    return out


def _classify(tags: dict[str, str]) -> str | None:
    if tags.get("station") == "subway" or tags.get("railway") == "subway_entrance":
        return "metrou"
    amenity, shop, leisure = tags.get("amenity"), tags.get("shop"), tags.get("leisure")
    if amenity == "school":
        return "scoli"
    if amenity == "kindergarten":
        return "gradinite"
    if amenity == "marketplace":
        return "piata"
    if amenity == "pharmacy":
        return "farmacii"
    if amenity in {"hospital", "clinic", "doctors"}:
        return "medical"
    if shop in {"mall", "department_store"}:
        return "mall"
    if shop == "supermarket":
        return "supermarket"
    if leisure == "park":
        return "parcuri"
    if leisure == "playground":
        return "joaca"
    if leisure in {"fitness_centre", "sports_centre"}:
        return "sport"
    if tags.get("highway") == "bus_stop" or tags.get("railway") == "tram_stop":
        return "transport"
    return None


def _detail(tags: dict[str, str]) -> str:
    bits = []
    if tags.get("amenity") == "school" and (grades := tags.get("isced:level") or tags.get("school:type")):
        bits.append(grades)
    if tags.get("opening_hours") == "24/7":
        bits.append("non-stop")
    if tags.get("brand"):
        bits.append(tags["brand"])
    return ", ".join(bits)
