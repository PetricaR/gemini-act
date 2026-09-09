"""Google Maps Platform, used server-side by the valuation.

`locatie.py` answers the same questions off OpenStreetMap — Nominatim for the
address, Overpass for what stands around it. That path is free and stays as the
fallback, but it is weak in exactly the places a valuation leans hardest:

* **Geocoding.** Romanian street addresses resolve poorly on Nominatim, and when
  it fails it fails silently, landing on a neighbourhood centroid. Google returns
  a `location_type` that says outright whether it hit the building (`ROOFTOP`)
  or approximated — which is the same distinction `Place.precision` already
  carries through the report, now sourced from the geocoder instead of inferred
  from the shape of the result.
* **Amenities.** Overpass returns whatever volunteers tagged, with no notion of
  quality. Places carries a rating and a review count, so "a school 400 m away"
  becomes "a school 400 m away that 200 parents rate 4.6" — which is what
  actually moves a price in this market.
* **Distance.** Every distance in the OSM path is a straight line. The valuation
  discounts up to `metro_discount_max_pct` on metro distance, so a crow-flies
  number that ignores a railway or a boulevard with no crossing overstates the
  location. Routes gives the walk that a buyer would actually make.

None of this is required: `available()` is false when no key is configured and
every entry point returns None, which puts the caller back on the OSM path.

Only ever called with a property's own coordinates — there is no user data here,
so this authenticates with a project API key rather than the calling user's
OAuth token. The `maps` Workspace MCP server in `config.py` is the other half of
that split and answers a user's questions inside an agent turn; this half backs
the report's own measurements and must work with no user present at all.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

from gemini_act.config import get_settings

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
ROUTES_MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
STATIC_MAP_URL = "https://maps.googleapis.com/maps/api/staticmap"
STREET_VIEW_URL = "https://maps.googleapis.com/maps/api/streetview"
STREET_VIEW_META_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"

TIMEOUT = 30.0

# Google's own answer to "how exact is this?", mapped onto the two-value
# precision the report already speaks in. ROOFTOP and RANGE_INTERPOLATED mean a
# building or a point on its street; the other two mean a centroid, which is
# what a listing that hid its address geocodes to.
_EXACT_LOCATION_TYPES = frozenset({"ROOFTOP", "RANGE_INTERPOLATED"})

# `locatie.CATEGORIES` keys -> Places API (New) types. Each category is fetched
# as its own request so an unrecognised type costs that one category and not the
# whole surroundings call. Types are from Table A of the Places type list; where
# a category has no single clean type it lists the few that together cover it.
PLACE_TYPES: dict[str, tuple[str, ...]] = {
    "metrou": ("subway_station",),
    "scoli": ("school", "primary_school", "secondary_school"),
    "gradinite": ("preschool",),
    "parcuri": ("park",),
    "joaca": ("playground",),
    "supermarket": ("supermarket", "grocery_store"),
    "mall": ("shopping_mall", "department_store"),
    "piata": ("market",),
    "farmacii": ("pharmacy", "drugstore"),
    "medical": ("hospital", "doctor", "dental_clinic"),
    "sport": ("gym", "fitness_center"),
    "transport": ("bus_station", "train_station", "light_rail_station"),
}

# Only what the report renders. Places bills by field mask, so asking for less
# is cheaper as well as smaller — `places.id` alone would already cost the
# Essentials tier, and location/rating put this in Pro.
_PLACES_FIELD_MASK = (
    "places.displayName,places.location,places.rating,"
    "places.userRatingCount,places.shortFormattedAddress,places.primaryTypeDisplayName"
)


def available() -> bool:
    """Whether a key is configured. False puts every caller on the OSM path."""
    return bool(get_settings().maps_api_key)


def _key() -> str:
    return get_settings().maps_api_key


@dataclass(frozen=True)
class MapsPlace:
    """A geocoded address. Field-compatible with `locatie.Place`."""

    lat: float
    lon: float
    display: str
    precision: str          # "adresa" | "zona"
    place_id: str | None = None
    location_type: str | None = None   # Google's own verdict, verbatim

    @property
    def map_url(self) -> str:
        return f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"

    @property
    def google_url(self) -> str:
        return self.map_url


@dataclass(frozen=True)
class MapsPoi:
    """One amenity. Superset of `locatie.Poi` — adds what OSM cannot supply."""

    name: str
    category: str
    distance_m: int
    detail: str = ""
    rating: float | None = None
    ratings_count: int | None = None
    address: str | None = None
    # Kept so a caller can ask for a route to it without re-querying Places.
    lat: float | None = None
    lon: float | None = None


def geocode(address: str | None, fallback: str | None = None) -> MapsPlace | None:
    """Resolve a listing address, falling back to its neighbourhood label.

    Tries the full address first and the area label only if that fails, so a
    listing that published a street number lands on the building and one that
    did not lands on the area — and says which, via `precision`.
    """
    if not available():
        return None

    for candidate, intended in ((address, "adresa"), (fallback, "zona")):
        if not candidate or not candidate.strip():
            continue
        query = candidate if "bucure" in candidate.lower() else f"{candidate}, București"
        try:
            with httpx.Client(timeout=TIMEOUT) as http:
                r = http.get(
                    GEOCODE_URL,
                    params={"address": query, "key": _key(), "region": "ro", "language": "ro"},
                )
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError):
            logger.debug("Maps geocode failed for %r", query, exc_info=True)
            continue

        if data.get("status") != "OK" or not data.get("results"):
            # REQUEST_DENIED / OVER_QUERY_LIMIT are configuration problems, not
            # "address not found", and are worth seeing in the logs as such.
            if data.get("status") not in {"ZERO_RESULTS", None}:
                logger.warning(
                    "Maps geocode returned %s: %s",
                    data.get("status"),
                    data.get("error_message", ""),
                )
            continue

        hit = data["results"][0]
        geometry = hit.get("geometry") or {}
        loc = geometry.get("location") or {}
        if "lat" not in loc or "lng" not in loc:
            continue
        location_type = geometry.get("location_type")
        # An address query that only resolved to a centroid is not an address,
        # whatever we asked for.
        precision = (
            intended
            if (intended == "zona" or location_type in _EXACT_LOCATION_TYPES)
            else "zona"
        )
        return MapsPlace(
            lat=float(loc["lat"]),
            lon=float(loc["lng"]),
            display=hit.get("formatted_address") or candidate,
            precision=precision,
            place_id=hit.get("place_id"),
            location_type=location_type,
        )
    return None


def _nearby_one(
    category: str, types: tuple[str, ...], lat: float, lon: float, radius_m: int
) -> list[MapsPoi]:
    """One category's amenities. Never raises — a category that fails is empty."""
    body: dict[str, Any] = {
        "includedTypes": list(types),
        "maxResultCount": 20,
        "rankPreference": "DISTANCE",
        "languageCode": "ro",
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(radius_m)}
        },
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as http:
            r = http.post(
                PLACES_NEARBY_URL,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": _key(),
                    "X-Goog-FieldMask": _PLACES_FIELD_MASK,
                },
            )
            if r.status_code != 200:
                logger.warning(
                    "Places searchNearby %s -> %s: %s", category, r.status_code, r.text[:300]
                )
                return []
            data = r.json()
    except (httpx.HTTPError, ValueError):
        logger.debug("Places searchNearby failed for %s", category, exc_info=True)
        return []

    out: list[MapsPoi] = []
    for place in data.get("places") or []:
        loc = place.get("location") or {}
        if "latitude" not in loc or "longitude" not in loc:
            continue
        from .locatie import _haversine

        name = (place.get("displayName") or {}).get("text") or "(fără nume)"
        rating = place.get("rating")
        count = place.get("userRatingCount")
        detail = (place.get("primaryTypeDisplayName") or {}).get("text") or ""
        p_lat, p_lon = float(loc["latitude"]), float(loc["longitude"])
        out.append(
            MapsPoi(
                name=name,
                category=category,
                distance_m=_haversine(lat, lon, p_lat, p_lon),
                detail=detail,
                rating=float(rating) if isinstance(rating, (int, float)) else None,
                ratings_count=int(count) if isinstance(count, int) else None,
                address=place.get("shortFormattedAddress"),
                lat=p_lat,
                lon=p_lon,
            )
        )
    out.sort(key=lambda p: p.distance_m)
    return out


def nearby(lat: float, lon: float, radius_m: int = 1200) -> dict[str, list[MapsPoi]] | None:
    """Every amenity category around a point, fetched in parallel.

    Returns None when Maps is unconfigured, so the caller can tell "no key" from
    "a key, and genuinely nothing nearby".
    """
    if not available():
        return None
    with ThreadPoolExecutor(max_workers=len(PLACE_TYPES)) as pool:
        futures = {
            category: pool.submit(_nearby_one, category, types, lat, lon, radius_m)
            for category, types in PLACE_TYPES.items()
        }
        return {category: future.result() for category, future in futures.items()}


def walking_times(
    lat: float, lon: float, destinations: list[tuple[float, float]]
) -> list[int | None] | None:
    """Walking duration in seconds to each destination, in the order given.

    The straight-line distance the report otherwise uses is a lower bound that a
    railway, a river or a boulevard with no crossing can make meaningless — and
    metro distance carries a real adjustment in the grid, so it is worth the
    call. An entry is None where no route exists.
    """
    if not available() or not destinations:
        return None
    body = {
        "origins": [
            {
                "waypoint": {
                    "location": {"latLng": {"latitude": lat, "longitude": lon}}
                }
            }
        ],
        "destinations": [
            {"waypoint": {"location": {"latLng": {"latitude": d_lat, "longitude": d_lon}}}}
            for d_lat, d_lon in destinations
        ],
        "travelMode": "WALK",
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as http:
            r = http.post(
                ROUTES_MATRIX_URL,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": _key(),
                    "X-Goog-FieldMask": (
                        "originIndex,destinationIndex,duration,distanceMeters,condition"
                    ),
                },
            )
            if r.status_code != 200:
                logger.warning("Routes matrix -> %s: %s", r.status_code, r.text[:300])
                return None
            rows = r.json()
    except (httpx.HTTPError, ValueError):
        logger.debug("Routes matrix failed", exc_info=True)
        return None

    out: list[int | None] = [None] * len(destinations)
    for row in rows if isinstance(rows, list) else []:
        index = row.get("destinationIndex")
        if not isinstance(index, int) or not 0 <= index < len(out):
            continue
        if row.get("condition") != "ROUTE_EXISTS":
            continue
        # Durations come back as a protobuf duration string, "412s".
        raw = str(row.get("duration") or "").rstrip("s")
        try:
            out[index] = int(float(raw))
        except ValueError:
            continue
    return out


def static_map(lat: float, lon: float, zoom: int = 16, size: str = "640x420") -> bytes | None:
    """A map image of the property's surroundings, for the report and the
    vision pass. None on any failure — the report renders without it."""
    if not available():
        return None
    try:
        with httpx.Client(timeout=TIMEOUT) as http:
            r = http.get(
                STATIC_MAP_URL,
                params={
                    "center": f"{lat},{lon}",
                    "zoom": zoom,
                    "size": size,
                    "scale": 2,
                    "maptype": "roadmap",
                    "markers": f"color:red|{lat},{lon}",
                    "language": "ro",
                    "key": _key(),
                },
            )
            if r.status_code != 200 or not r.content:
                logger.warning("Static map -> %s: %s", r.status_code, r.text[:200])
                return None
            return r.content
    except httpx.HTTPError:
        logger.debug("Static map failed", exc_info=True)
        return None


def street_view(lat: float, lon: float, size: str = "640x420") -> bytes | None:
    """A photograph of the building from the street, if one exists.

    This is the one piece of visual evidence the seller does not control. The
    gallery shows the rooms they chose to show; Street View shows the facade,
    the block, the parking and the street — which for a valuation done without
    an inspection is worth as much as the interior shots.

    Metadata is checked first: the image endpoint bills for, and returns, a grey
    "no imagery" placeholder rather than a 404, which would otherwise be sent to
    the vision model as though it were a photograph of the building.
    """
    if not available():
        return None
    try:
        with httpx.Client(timeout=TIMEOUT) as http:
            meta = http.get(
                STREET_VIEW_META_URL,
                params={"location": f"{lat},{lon}", "key": _key()},
            )
            if meta.status_code != 200 or (meta.json() or {}).get("status") != "OK":
                return None
            r = http.get(
                STREET_VIEW_URL,
                params={
                    "location": f"{lat},{lon}",
                    "size": size,
                    "fov": 80,
                    "pitch": 10,
                    "return_error_code": "true",
                    "key": _key(),
                },
            )
            if r.status_code != 200 or not r.content:
                return None
            return r.content
    except (httpx.HTTPError, ValueError):
        logger.debug("Street View failed", exc_info=True)
        return None
