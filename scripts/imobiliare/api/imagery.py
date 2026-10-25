"""Location intelligence and real imagery for the Evaluator AI web report.

Everything Google-billed is fetched *server-side* and proxied, so the Maps key
never reaches the browser and repeated page loads hit a process-wide cache
instead of the API.

Three imagery sources, deliberately:

- **Street View Static** — a real photograph of the building from the street,
  the one visual the seller does not control. Fetched at four headings.
- **Maps Static (`roadmap`)** — the base map the facilities overlay is drawn on.
  The browser projects the POI coordinates onto it with the same Web Mercator
  math used here, which is why `zoom`/`width`/`height` are returned to it.
- **Aerial** — Google's `satellite`/`hybrid` map types are *not served to this
  account's region* (EEA: see developers.google.com/maps/comms/eea/maps-static,
  both Maps Static and Map Tiles answer 403). Google is still tried first so the
  report upgrades itself the day that entitlement changes; otherwise the aerial
  view is stitched from Esri World Imagery tiles, which is real orthophoto and
  is attributed as such in the UI.
"""

from __future__ import annotations

import io
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

from imobiliare.mcp import maps

logger = logging.getLogger(__name__)

# Real orthophoto, used because Google refuses satellite for this region.
ESRI_TILE_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
)
ESRI_ATTRIBUTION = "Esri, Maxar, Earthstar Geographics"
TILE_PX = 256
TIMEOUT = 25.0

# Street View headings. Four quadrants: the facade, both approaches down the
# street, and what the property looks out onto.
STREET_VIEW_HEADINGS = (0, 90, 180, 270)

# What the amenity map draws, in the order the legend lists them. Keys match
# `maps.PLACE_TYPES` / `locatie.CATEGORIES`; the label is what the UI shows and
# `icon` names the lucide glyph the pin is drawn with.
CATEGORY_META: dict[str, dict[str, str]] = {
    "metrou": {"eticheta": "Metrou", "icon": "train-front", "culoare": "#4338ca"},
    "transport": {"eticheta": "Transport public", "icon": "bus", "culoare": "#0891b2"},
    "scoli": {"eticheta": "Școli", "icon": "school", "culoare": "#c2410c"},
    "gradinite": {"eticheta": "Grădinițe & creșe", "icon": "baby", "culoare": "#db2777"},
    "parcuri": {"eticheta": "Parcuri", "icon": "trees", "culoare": "#15803d"},
    "joaca": {"eticheta": "Locuri de joacă", "icon": "toy-brick", "culoare": "#65a30d"},
    "supermarket": {"eticheta": "Supermarketuri", "icon": "shopping-cart", "culoare": "#0284c7"},
    "mall": {"eticheta": "Centre comerciale", "icon": "shopping-bag", "culoare": "#7c3aed"},
    "piata": {"eticheta": "Piețe", "icon": "store", "culoare": "#ca8a04"},
    "farmacii": {"eticheta": "Farmacii", "icon": "pill", "culoare": "#dc2626"},
    "medical": {"eticheta": "Medical", "icon": "stethoscope", "culoare": "#e11d48"},
    "sport": {"eticheta": "Sport & fitness", "icon": "dumbbell", "culoare": "#ea580c"},
}

# How many of each category the map pins and the list show. Places returns up to
# 20 per category; 20 pharmacy pins inside 500 m is noise, not information.
MAX_POI_PER_CATEGORY = 6

# Average walking pace, m/s, for POIs we do not spend a Routes call on.
WALK_SPEED_MS = 1.35


# --------------------------------------------------------------------------
# tiny TTL cache — one instance serves everyone, and a report page requests
# the same six images per viewer
# --------------------------------------------------------------------------


@dataclass
class _Entry:
    value: Any
    expires: float


class _TTLCache:
    def __init__(self, ttl: float = 6 * 3600, maxsize: int = 256) -> None:
        self._ttl = ttl
        self._maxsize = maxsize
        self._data: dict[str, _Entry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.expires < time.time():
            self._data.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any) -> Any:
        if len(self._data) >= self._maxsize:
            oldest = min(self._data, key=lambda k: self._data[k].expires)
            self._data.pop(oldest, None)
        self._data[key] = _Entry(value, time.time() + self._ttl)
        return value


_IMAGE_CACHE = _TTLCache(ttl=12 * 3600, maxsize=192)
_DATA_CACHE = _TTLCache(ttl=6 * 3600, maxsize=128)


# --------------------------------------------------------------------------
# Web Mercator — the browser overlay reimplements exactly this, so any change
# here has to be mirrored in web/src/lib/mercator.js
# --------------------------------------------------------------------------


def world_size(zoom: int) -> float:
    return TILE_PX * (2**zoom)


def project(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Lat/lon -> absolute pixel coordinates at `zoom`."""
    size = world_size(zoom)
    x = (lon + 180.0) / 360.0 * size
    sin_lat = math.sin(math.radians(max(min(lat, 85.05112878), -85.05112878)))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * size
    return x, y


def meters_per_pixel(lat: float, zoom: int) -> float:
    return 156543.03392 * math.cos(math.radians(lat)) / (2**zoom)


def fit_zoom(lat: float, radius_m: int, height_px: int, padding_px: int = 22) -> int:
    """Largest zoom at which a `radius_m` circle still fits the map's height."""
    usable = max((height_px / 2.0) - padding_px, 40.0)
    for zoom in range(19, 9, -1):
        if radius_m / meters_per_pixel(lat, zoom) <= usable:
            return zoom
    return 13


# --------------------------------------------------------------------------
# geocoding + amenities
# --------------------------------------------------------------------------


def geocode(adresa: str, fallback: str | None = None) -> dict[str, Any] | None:
    """Resolve an address to coordinates. Cached — the demo address is constant."""
    key = f"geo:{adresa}|{fallback or ''}"
    cached = _DATA_CACHE.get(key)
    if cached is not None:
        return cached or None
    if not maps.available():
        return None
    place = maps.geocode(adresa, fallback)
    if place is None:
        _DATA_CACHE.set(key, {})
        return None
    return _DATA_CACHE.set(
        key,
        {
            "lat": place.lat,
            "lon": place.lon,
            "adresa_formatata": place.display,
            "precizie": place.precision,
            "place_id": place.place_id,
            "google_maps_url": place.map_url,
        },
    )


def _poi_dict(poi: maps.MapsPoi, walk_seconds: int | None = None) -> dict[str, Any]:
    seconds = walk_seconds or round(poi.distance_m / WALK_SPEED_MS)
    return {
        "nume": poi.name,
        "categorie": poi.category,
        "distanta_m": poi.distance_m,
        "minute_mers": max(1, round(seconds / 60)),
        "minute_estimate": walk_seconds is None,
        "detaliu": poi.detail,
        "rating": poi.rating,
        "numar_recenzii": poi.ratings_count,
        "adresa": poi.address,
        "lat": poi.lat,
        "lon": poi.lon,
    }


def _accessibility_score(by_category: dict[str, list[dict[str, Any]]]) -> float:
    """0-10 from what is actually reachable on foot.

    Weighted by how much each category moves a buyer's decision: a metro entrance
    inside 500 m is worth more than a sixth pharmacy. A category scores full marks
    when its nearest member is within ~300 m and decays to zero at the search
    radius; the total is the weighted mean.
    """
    weights = {
        "metrou": 2.0,
        "supermarket": 1.6,
        "parcuri": 1.4,
        "scoli": 1.2,
        "gradinite": 1.0,
        "farmacii": 1.0,
        "transport": 1.0,
        "medical": 0.8,
        "sport": 0.7,
        "mall": 0.6,
        "piata": 0.5,
        "joaca": 0.5,
    }
    total_weight = sum(weights.values())
    earned = 0.0
    for category, weight in weights.items():
        items = by_category.get(category) or []
        if not items:
            continue
        nearest = min(item["distanta_m"] for item in items)
        proximity = 1.0 if nearest <= 300 else max(0.0, 1.0 - (nearest - 300) / 700.0)
        # A second nearby member of the same category is worth a little more.
        density = min(len(items), 3) / 3.0
        earned += weight * (0.75 * proximity + 0.25 * density)
    return round(min(10.0, earned / total_weight * 10.0), 1)


def facilities(lat: float, lon: float, radius_m: int = 500) -> dict[str, Any]:
    """Every mapped amenity inside `radius_m`, grouped by category.

    The nearest member of each category gets a real walking duration from the
    Routes API (one matrix call for all of them); the rest are estimated from
    straight-line distance, and say so via `minute_estimate`.
    """
    key = f"poi:{lat:.5f},{lon:.5f}:{radius_m}"
    cached = _DATA_CACHE.get(key)
    if cached is not None:
        return cached

    raw = maps.nearby(lat, lon, radius_m) if maps.available() else None
    if raw is None:
        return {"status": "indisponibil", "categorii": {}, "total": 0}

    trimmed: dict[str, list[maps.MapsPoi]] = {}
    for category in CATEGORY_META:
        items = [p for p in (raw.get(category) or []) if p.distance_m <= radius_m]
        if items:
            trimmed[category] = items[:MAX_POI_PER_CATEGORY]

    # One Routes matrix for the nearest of each category.
    nearest = [(cat, items[0]) for cat, items in trimmed.items() if items[0].lat is not None]
    walk_by_category: dict[str, int | None] = {}
    if nearest:
        try:
            durations = maps.walking_times(
                lat,
                lon,
                [(poi.lat, poi.lon) for _, poi in nearest],  # type: ignore[misc]
            )
        except Exception:  # pragma: no cover - never break the report on this
            durations = None
        if durations:
            for (category, _), seconds in zip(nearest, durations, strict=False):
                walk_by_category[category] = seconds

    by_category: dict[str, list[dict[str, Any]]] = {}
    for category, items in trimmed.items():
        rows = []
        for index, poi in enumerate(items):
            walk = walk_by_category.get(category) if index == 0 else None
            rows.append(_poi_dict(poi, walk))
        by_category[category] = rows

    result = {
        "status": "success",
        "raza_m": radius_m,
        "categorii": by_category,
        "total": sum(len(v) for v in by_category.values()),
        "scor_accesibilitate": _accessibility_score(by_category),
        "meta_categorii": {k: v for k, v in CATEGORY_META.items() if k in by_category},
    }
    return _DATA_CACHE.set(key, result)


# --------------------------------------------------------------------------
# imagery
# --------------------------------------------------------------------------


# Google's own POI icons are turned off on the base map. They are drawn from a
# different, unfiltered set than the amenities this report searched for, so
# leaving them on puts two competing layers of markers on one image and makes
# it impossible to tell which pins the 500 m analysis actually counted. Park and
# water geometry stays — that is terrain, not a marker.
_BASE_MAP_STYLE = (
    "feature:poi|element:labels|visibility:off",
    "feature:poi.business|visibility:off",
    "feature:transit|element:labels.icon|visibility:off",
    "feature:road|element:labels.icon|visibility:off",
)


def roadmap_image(lat: float, lon: float, zoom: int, width: int, height: int) -> bytes | None:
    """The base map the amenity pins are drawn on.

    No `markers` parameter: every pin is drawn by the browser so it can carry a
    category icon, a colour and a hover card, none of which a baked-in Static
    Maps marker can do.
    """
    key = f"road:{lat:.5f},{lon:.5f}:{zoom}:{width}x{height}"
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached
    if not maps.available():
        return None
    try:
        with httpx.Client(timeout=TIMEOUT) as http:
            # A list of pairs, not a dict: `style` is repeated once per rule
            # and a dict would keep only the last one.
            params: list[tuple[str, Any]] = [
                ("center", f"{lat},{lon}"),
                ("zoom", zoom),
                ("size", f"{width}x{height}"),
                ("scale", 2),
                ("maptype", "roadmap"),
                ("language", "ro"),
                ("region", "RO"),
                *[("style", rule) for rule in _BASE_MAP_STYLE],
                ("key", maps._key()),
            ]
            response = http.get(maps.STATIC_MAP_URL, params=params)
        if response.status_code != 200 or not response.content:
            logger.warning("Static roadmap -> %s: %s", response.status_code, response.text[:200])
            return None
        return _IMAGE_CACHE.set(key, response.content)
    except httpx.HTTPError:
        logger.debug("Static roadmap failed", exc_info=True)
        return None


def _esri_aerial(lat: float, lon: float, zoom: int, width: int, height: int) -> bytes | None:
    """Stitch Esri World Imagery tiles into one image centred on the property."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a hard dependency here
        logger.warning("Pillow missing; cannot stitch aerial tiles")
        return None

    centre_x, centre_y = project(lat, lon, zoom)
    left, top = centre_x - width / 2.0, centre_y - height / 2.0
    x0, y0 = int(math.floor(left / TILE_PX)), int(math.floor(top / TILE_PX))
    x1 = int(math.floor((left + width) / TILE_PX))
    y1 = int(math.floor((top + height) / TILE_PX))
    span = 2**zoom

    def fetch(tx: int, ty: int) -> tuple[int, int, bytes | None]:
        if not (0 <= ty < span):
            return tx, ty, None
        url = ESRI_TILE_URL.format(z=zoom, x=tx % span, y=ty)
        try:
            with httpx.Client(timeout=TIMEOUT) as http:
                response = http.get(url, headers={"User-Agent": "EvaluatorAI/1.0"})
            return tx, ty, response.content if response.status_code == 200 else None
        except httpx.HTTPError:
            return tx, ty, None

    coords = [(tx, ty) for tx in range(x0, x1 + 1) for ty in range(y0, y1 + 1)]
    canvas = Image.new("RGB", (width, height), (226, 232, 240))
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(coords)))) as pool:
        for tx, ty, payload in pool.map(lambda c: fetch(*c), coords):
            if not payload:
                continue
            try:
                tile = Image.open(io.BytesIO(payload)).convert("RGB")
            except Exception:
                continue
            canvas.paste(tile, (int(tx * TILE_PX - left), int(ty * TILE_PX - top)))

    buffer = io.BytesIO()
    canvas.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def aerial_image(
    lat: float, lon: float, zoom: int, width: int, height: int
) -> tuple[bytes | None, str]:
    """Real aerial imagery plus the source that must be credited alongside it.

    The source name is ASCII on purpose — it travels back as an HTTP header, and
    headers are latin-1, so the "©" belongs in the UI, not here.

    Google first — if this account ever gains satellite entitlement the report
    starts using it with no code change — then Esri orthophoto.
    """
    key = f"air:{lat:.5f},{lon:.5f}:{zoom}:{width}x{height}"
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached

    if maps.available():
        try:
            with httpx.Client(timeout=TIMEOUT) as http:
                response = http.get(
                    maps.STATIC_MAP_URL,
                    params={
                        "center": f"{lat},{lon}",
                        "zoom": zoom,
                        "size": f"{width}x{height}",
                        "scale": 2,
                        "maptype": "hybrid",
                        "language": "ro",
                        "key": maps._key(),
                    },
                )
            if response.status_code == 200 and response.content:
                return _IMAGE_CACHE.set(key, (response.content, "Google"))
            logger.info(
                "Google satellite unavailable (%s); using orthophoto fallback",
                response.status_code,
            )
        except httpx.HTTPError:
            logger.debug("Google satellite failed", exc_info=True)

    stitched = _esri_aerial(lat, lon, zoom, width, height)
    if stitched is None:
        return None, ""
    return _IMAGE_CACHE.set(key, (stitched, ESRI_ATTRIBUTION))


def street_view_image(
    lat: float, lon: float, heading: int, width: int, height: int, fov: int = 90, pitch: int = 8
) -> bytes | None:
    key = f"sv:{lat:.5f},{lon:.5f}:{heading}:{fov}:{width}x{height}"
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached
    payload = maps.street_view(
        lat, lon, size=f"{width}x{height}", heading=heading, pitch=pitch, fov=fov
    )
    if payload is None:
        return None
    return _IMAGE_CACHE.set(key, payload)


def street_view_info(lat: float, lon: float) -> dict[str, Any]:
    """Whether Street View has imagery here, and when it was taken."""
    key = f"svmeta:{lat:.5f},{lon:.5f}"
    cached = _DATA_CACHE.get(key)
    if cached is not None:
        return cached
    meta = maps.street_view_metadata(lat, lon) if maps.available() else None
    info = {
        "disponibil": bool(meta),
        "data_captura": (meta or {}).get("date"),
        "copyright": (meta or {}).get("copyright") or "© Google",
        "pano_id": (meta or {}).get("pano_id"),
    }
    return _DATA_CACHE.set(key, info)


# --------------------------------------------------------------------------
# the block the report page consumes
# --------------------------------------------------------------------------

# Square, and at the largest zoom the radius still fits: the circle is the
# subject of this image, so it should fill the frame rather than float in a
# corner of a landscape crop. 640 is the Static Maps ceiling per side.
MAP_WIDTH = 640
MAP_HEIGHT = 640
AERIAL_WIDTH = 640
AERIAL_HEIGHT = 480
AERIAL_ZOOM = 18


def build_location_block(
    adresa: str,
    *,
    fallback: str | None = None,
    radius_m: int = 500,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    """Coordinates, imagery URLs and amenities for one property.

    Image URLs point at this app's own proxy routes rather than at Google, so the
    key stays server-side and the browser gets cache hits.
    """
    resolved: dict[str, Any] | None = None
    if lat is not None and lon is not None:
        resolved = {
            "lat": lat,
            "lon": lon,
            "adresa_formatata": adresa,
            "precizie": "adresa",
            "google_maps_url": f"https://www.google.com/maps/search/?api=1&query={lat},{lon}",
        }
    elif adresa:
        resolved = geocode(adresa, fallback)

    if not resolved:
        return {
            "status": "indisponibil",
            "motiv": (
                "Cheia Google Maps nu este configurată pe server."
                if not maps.available()
                else "Adresa nu a putut fi geocodificată."
            ),
            "adresa_cautata": adresa,
        }

    lat_f, lon_f = float(resolved["lat"]), float(resolved["lon"])
    zoom = fit_zoom(lat_f, radius_m, MAP_HEIGHT)
    amenities = facilities(lat_f, lon_f, radius_m)
    sv = street_view_info(lat_f, lon_f)

    base = "/api/audit/imagery"
    coords = f"lat={lat_f}&lon={lon_f}"

    return {
        "status": "success",
        **resolved,
        "harta": {
            "url": f"{base}/roadmap?{coords}&zoom={zoom}&w={MAP_WIDTH}&h={MAP_HEIGHT}",
            "zoom": zoom,
            "latime": MAP_WIDTH,
            "inaltime": MAP_HEIGHT,
            "raza_m": radius_m,
            "metri_pe_pixel": round(meters_per_pixel(lat_f, zoom), 3),
            "atribuire": "Hartă © Google",
        },
        "satelit": {
            "url": f"{base}/aerial?{coords}&zoom={AERIAL_ZOOM}&w={AERIAL_WIDTH}&h={AERIAL_HEIGHT}",
            "zoom": AERIAL_ZOOM,
            "atribuire": ESRI_ATTRIBUTION,
        },
        "street_view": {
            **sv,
            "unghiuri": [
                {
                    "heading": heading,
                    "eticheta": eticheta,
                    "url": f"{base}/streetview?{coords}&heading={heading}&w=640&h=420",
                }
                for heading, eticheta in zip(
                    STREET_VIEW_HEADINGS,
                    ("Nord", "Est", "Sud", "Vest"),
                    strict=True,
                )
            ]
            if sv["disponibil"]
            else [],
        },
        "facilitati": amenities.get("categorii", {}),
        "meta_categorii": amenities.get("meta_categorii", {}),
        "total_facilitati": amenities.get("total", 0),
        "scor_accesibilitate": amenities.get("scor_accesibilitate"),
        "raza_m": radius_m,
    }
