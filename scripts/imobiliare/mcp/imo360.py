"""Market data from imo360.ro's explorer API -- a second, session-free source.

Why this exists next to `client.py`: the imobiliare.ro path needs a
browser-originated `session_id` that expires in minutes (`cauta`), or a
headless browser (`obscura`), or a daily sitemap scrape (`comps`). This host
needs none of it -- plain `GET`, JSON, no token -- so it is the source that
still answers at three in the morning on Cloud Run.

It is also a *different kind* of source, not a mirror of the same listings:

* **Geographic, not textual.** Results are selected by bounding box or by zone
  id, so "everything within 800 m of this address" is one call rather than a
  slug-matching exercise. `/zones` publishes the gazetteer behind that: 1588
  zones nationwide with bbox, ~450 of them with real polygons.
* **Rentals are in the same index** (`transaction=rent`). That is the missing
  half of a yield calculation -- imobiliare.ro's AI search gives us sale
  comparables only, so gross yield was previously not computable at all.
* **`total` is a real count** whenever `totalIsCapped` is false, which makes
  the endpoint double as a supply counter: how many 2-room flats are on the
  market in this zone *right now*, not how many we managed to scrape.
* **Every listing carries the vendor's own score block** -- value, yield,
  liquidity, appreciation, location, negotiation, condition, trust, each with
  a confidence. Treat it as one opinion among several (see the warning on
  `_score` below), never as the valuation.

Traps, all of them paid for once already:

**The `title` is the source ad's headline and is regularly wrong about the
location.** Listing 5194980 is titled "zona Carpati 1 - Satu Mare" and sits on
Strada Ganea in Sector 1, București. The geo fields (`latitude`, `longitude`,
`zone`, `locality`, `region`) come from imo360's own resolution and are the
ones to trust; the title is display text.

**`usableArea` is missing about half the time** (24 of 50 in one sample) while
`totalArea` is always there. They are not the same number -- built area runs
roughly 15-20% above usable in Romanian stock -- so a price per sqm computed
from whichever happens to be present is not comparable across listings.
`surface_basis` records which one was used; anything doing comparables must
either read it or filter on it.

**Prices are not all in EUR.** A handful are `"ron"`. There is no FX rate in
this codebase and inventing one would quietly corrupt every downstream
average, so `price_eur` is set only for EUR listings and the raw
`price`/`currency` pair is kept alongside.

Scope, same as the rest of this package: undocumented API, no published terms.
`GET`s go through `throttle` so this host gets its own paced clock, request
volume stays modest, and there are no retries beyond what `throttle` already
does.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from . import paths, throttle

logger = logging.getLogger(__name__)

BASE = "https://admin.imo360.ro/v1/market/explorer"
LISTINGS_URL = f"{BASE}/listings"
ZONES_URL = f"{BASE}/zones"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

# The host caps `total` at this value and says so via `totalIsCapped`. Above it
# the number means "at least this many" and must not be reported as a count.
TOTAL_CAP = 10000

# Page size. The API accepts larger, but a page is also the unit of work that
# `throttle` paces, and 100 keeps a zone sweep to a handful of calls.
PAGE_SIZE = 100

# The gazetteer changes when a zone is redrawn, which is roughly never.
ZONES_TTL = 7 * 24 * 3600

Transaction = Literal["sale", "rent"]
PropertyType = Literal["apartment", "house", "land", "commercial_space", "office"]


class Imo360Error(RuntimeError):
    """The explorer API refused or could not answer a request."""


@dataclass
class SearchPage:
    """One page of results, plus how many exist behind it."""

    listings: list[dict[str, Any]]
    total: int
    # `total` saturates at TOTAL_CAP. A capped total is a floor, not a count --
    # every caller that reports a number to a user has to know which it has.
    total_is_capped: bool
    zone_ids: list[int] = field(default_factory=list)

    @property
    def supply(self) -> int | None:
        """The real number of listings matching, or None when it is capped."""
        return None if self.total_is_capped else self.total


@dataclass(frozen=True)
class Zone:
    """One entry from the published gazetteer."""

    id: int
    name: str
    slug: str
    path: str  # "romania/bucuresti/sector-3/titan"
    lat: float | None
    lng: float | None
    bbox: tuple[float, float, float, float] | None  # west, south, east, north
    has_polygon: bool

    @property
    def city(self) -> str:
        parts = self.path.split("/")
        return parts[2].replace("-", " ").title() if len(parts) > 2 else ""

    @property
    def county(self) -> str:
        parts = self.path.split("/")
        return parts[1].replace("-", " ").title() if len(parts) > 1 else ""


def _slugify(value: str) -> str:
    """'Titan - Balta Albă' -> 'titan-balta-alba'."""
    stripped = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")


class Imo360Client:
    """Read-only client for the explorer API. No credentials of any kind."""

    def __init__(self, timeout: float = 45.0):
        self._http = httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Imo360Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        # Through `throttle` for the same reasons as `client.py`: one paced
        # clock per host, shared across threads, and a body that is not JSON
        # is recognised rather than parsed as data.
        r = throttle.request("GET", url, http=self._http, params=params or {})
        if r.status_code >= 400:
            # The host answers an unsupported enum value (`status=all`, say)
            # with a bare 500 and an HTML body, so the status line is all the
            # detail there is -- quote it rather than dressing it up.
            raise Imo360Error(f"{url} -> HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as exc:
            raise Imo360Error(f"{url} -> non-JSON response: {r.text[:200]}") from exc

    # -- listings ---------------------------------------------------------

    def search(
        self,
        *,
        transaction: Transaction = "sale",
        bbox: tuple[float, float, float, float] | None = None,
        zone_ids: list[int] | None = None,
        property_type: str | None = None,
        rooms: int | None = None,
        rooms_min: int | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        area_min: float | None = None,
        score_min: float | None = None,
        text: str | None = None,
        sort_by: str = "score",
        sort_order: str = "desc",
        limit: int = PAGE_SIZE,
        offset: int = 0,
    ) -> SearchPage:
        """One page of active listings.

        Either `bbox` (west, south, east, north) or `zone_ids` selects the
        geography; `zone_ids` alone is enough, the bounding box is not
        required. Everything else narrows server-side, which matters: the
        host caps `total` at 10000, so a filter applied here rather than
        locally is also what turns that cap back into a usable count.
        """
        params: dict[str, Any] = {
            "status": "active",
            "transaction": transaction,
            "limit": max(1, min(limit, PAGE_SIZE)),
            "offset": max(0, offset),
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        if bbox:
            west, south, east, north = bbox
            params |= {"west": west, "south": south, "east": east, "north": north}
        if zone_ids:
            params["zoneIds"] = ",".join(str(z) for z in zone_ids)
        if not bbox and not zone_ids:
            raise Imo360Error("a search needs either a bounding box or zone ids")
        # Server-side names differ from ours; only send what was asked for, so
        # an unset filter never becomes a default the caller did not choose.
        optional = {
            "propertyType": property_type,
            "rooms": rooms,
            "roomsMin": rooms_min,
            "priceMin": price_min,
            "priceMax": price_max,
            "areaMin": area_min,
            "scoreMin": score_min,
            "search": text,
        }
        params |= {k: v for k, v in optional.items() if v is not None}

        data = self._get(LISTINGS_URL, params)
        if not isinstance(data, dict) or "listings" not in data:
            raise Imo360Error(f"unexpected payload: {json.dumps(data)[:200]}")
        total = int(data.get("total") or 0)
        return SearchPage(
            listings=data.get("listings") or [],
            total=total,
            # Trust the flag when it is sent, and fall back to the cap itself:
            # a payload that omits the flag but reports exactly 10000 is
            # saturated, and reporting that as a count would be a lie.
            total_is_capped=bool(data.get("totalIsCapped", total >= TOTAL_CAP)),
            zone_ids=list(zone_ids or []),
        )

    def collect(self, *, max_results: int = 300, **kwargs: Any) -> SearchPage:
        """Page through a search until `max_results` or the results run out."""
        first = self.search(limit=PAGE_SIZE, offset=0, **kwargs)
        out = list(first.listings)
        while len(out) < max_results and len(out) < first.total:
            page = self.search(limit=PAGE_SIZE, offset=len(out), **kwargs)
            if not page.listings:
                break
            out.extend(page.listings)
        first.listings = out[:max_results]
        return first

    def listing(self, listing_id: int | str) -> dict[str, Any]:
        """One listing in full: gallery urls and the source ad's attributes."""
        data = self._get(f"{LISTINGS_URL}/{listing_id}")
        if not isinstance(data, dict) or "id" not in data:
            raise Imo360Error(f"listing {listing_id} not found")
        return data

    # -- gazetteer --------------------------------------------------------

    def zones(self) -> list[Zone]:
        """Every published zone, memoised in-process and on disk.

        ~590 KB of JSON for the whole country. Fetching it per search would
        dwarf the search itself, and it changes on the order of never.
        """
        if cached := throttle.cached("imo360:zones"):
            return cached
        raw = _zones_from_disk()
        if raw is None:
            raw = self._get(ZONES_URL)
            _zones_to_disk(raw)
        zones = [z for z in (_zone(entry) for entry in raw or []) if z is not None]
        return throttle.remember("imo360:zones", zones)

    def find_zones(self, name: str, city: str | None = None, limit: int = 8) -> list[Zone]:
        """Resolve a neighbourhood name to zone ids.

        Ranked, because the answer is genuinely ambiguous: "Militari" is two
        zones (Sector 5 and Sector 6) and dropping one of them would silently
        halve the market being measured. Callers that want the whole
        neighbourhood should pass every id back into `search`.
        """
        wanted, city_slug = _slugify(name), _slugify(city or "")
        if not wanted:
            return []

        def rank(z: Zone) -> tuple[int, int, int]:
            exact = z.slug == wanted
            prefix = z.slug.startswith(wanted)
            in_city = bool(city_slug) and city_slug in z.path
            # Exact before prefix before substring; then the requested city;
            # then prefer a zone with a real polygon, which is the better
            # geography when one exists.
            return (
                0 if exact else (1 if prefix else 2),
                0 if in_city else 1,
                0 if z.has_polygon else 1,
            )

        hits = [z for z in self.zones() if wanted in z.slug or z.slug in wanted]
        if city_slug:
            scoped = [z for z in hits if city_slug in z.path]
            # Only narrow to the city when it actually matches something --
            # a typo'd city must not turn a good name match into no answer.
            hits = scoped or hits
        return sorted(hits, key=rank)[:limit]


def _zone(entry: Any) -> Zone | None:
    if not isinstance(entry, dict) or entry.get("id") is None:
        return None
    raw_bbox = entry.get("bbox") or []
    bbox = None
    if len(raw_bbox) == 4:
        west, south, east, north = (float(v) for v in raw_bbox)
        # Zones without a polygon publish a degenerate bbox -- the same point
        # four times. Passing that to a bbox search returns nothing, so it is
        # reported as "no bounding box" and the caller uses the zone id.
        if east > west and north > south:
            bbox = (west, south, east, north)
    return Zone(
        id=int(entry["id"]),
        name=str(entry.get("name") or ""),
        slug=str(entry.get("slug") or _slugify(entry.get("name") or "")),
        path=str(entry.get("path") or ""),
        lat=_f(entry.get("lat")),
        lng=_f(entry.get("lng")),
        bbox=bbox,
        has_polygon=bool(entry.get("geometry")),
    )


def _zones_cache_file():
    cache = paths.ensure_dir(paths.cache_dir())
    return cache / "imo360-zones.json" if cache else None


def _zones_from_disk() -> Any | None:
    cached = _zones_cache_file()
    if not cached or not cached.exists():
        return None
    if time.time() - cached.stat().st_mtime > ZONES_TTL:
        return None
    try:
        return json.loads(cached.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _zones_to_disk(raw: Any) -> None:
    # No writable cache (read-only filesystem) degrades to re-fetching, never
    # to failing the search that needed the gazetteer.
    if cached := _zones_cache_file():
        try:
            cached.write_text(json.dumps(raw), encoding="utf-8")
        except (OSError, TypeError):
            pass


# -- normalisation --------------------------------------------------------

# Kept verbatim off the score block. Documented here because the names are
# imo360's, not ours, and their meaning is the vendor's to define.
_SCORE_FIELDS = (
    "total",
    "grade",
    "confidence",
    "valueScore",
    "yieldScore",
    "liquidityScore",
    "appreciationScore",
    "locationScore",
    "negotiationScore",
    "conditionScore",
    "appealScore",
    "trustScore",
)


def _f(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    v = _f(value)
    return int(v) if v is not None else None


def _score(listing: dict[str, Any]) -> dict[str, Any] | None:
    """The vendor's own scoring, flattened -- as *their* opinion, not ours.

    It is kept under a `imo360_score` key rather than merged into the record
    precisely so that nothing downstream can mistake it for a value this
    package computed. The ANEVAR valuation in `anevar.py` has to be derivable
    from comparables and stated adjustments; an opaque vendor score is
    evidence to weigh next to it, never an input to it.
    """
    raw = listing.get("score")
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {k: raw.get(k) for k in _SCORE_FIELDS if raw.get(k) is not None}
    if not out:
        return None
    inner = raw.get("factors")
    if isinstance(inner, dict):
        if factors := inner.get("factors"):
            out["factors"] = list(factors)
        if summary := inner.get("summary"):
            out["summary"] = str(summary)
        if missing := inner.get("missing_signals"):
            # What the score could *not* see matters as much as what it saw:
            # a high score with four missing signals is a thinner claim.
            out["missing_signals"] = list(missing)
    if calculated := raw.get("calculatedAt"):
        out["calculated_at"] = str(calculated)
    return out


def normalise(listing: dict[str, Any]) -> dict[str, Any]:
    """Flatten one explorer listing into this package's canonical record.

    Deliberately the same shape `parse.normalise` produces, so that
    `filter_and_rank`, the comparables grid and the report renderer all work
    on imo360 records without knowing where they came from -- which means
    every key that layer indexes has to be present, including the ones this
    source does not publish (metro distance, agency name, vacancy). Those are
    `None`, never a stand-in value: a missing value has to keep failing its
    constraint, which is the invariant the whole filter layer rests on.
    """
    price = _f(listing.get("price"))
    currency = str(listing.get("currency") or "").lower()
    # No FX rate here, and guessing one would corrupt every average built on
    # top. A non-EUR listing keeps its raw price and simply has no price_eur.
    price_eur = int(price) if price and currency == "eur" else None

    usable, total_area = _f(listing.get("usableArea")), _f(listing.get("totalArea"))
    surface = usable or total_area
    listing_id = listing.get("id")

    record: dict[str, Any] = {
        "id": listing_id,
        "source": "imo360",
        "title": listing.get("title"),
        # The public site has no stable per-listing page to point at, and
        # inventing one would produce links that 404. The API's own detail
        # endpoint is the address that actually resolves.
        "url": listing.get("externalUrl") or f"{LISTINGS_URL}/{listing_id}",
        # money
        "price_eur": price_eur,
        "price_raw": int(price) if price else None,
        "currency": currency or None,
        # Rounded to whole euros on the sale side, where a euro is noise, but
        # to two decimals below 100 -- a rent of 9.1 EUR/sqm rounded to 9 is a
        # 1.1% error on the rent and the same error again on every yield built
        # from it, which is enough to move a decision.
        "price_per_sqm": _per_sqm_value(price_eur, surface),
        "price_dropped": False,  # not published by this source
        # size / layout
        "rooms": _i(listing.get("rooms")),
        "surface_sqm": surface,
        # Which surface the numbers above are built on. Comparing a usable-area
        # price per sqm against a built-area one is a ~15-20% error dressed up
        # as a market difference.
        "surface_basis": "usable" if usable else ("total" if total_area else None),
        "total_area_sqm": total_area,
        "land_area_sqm": _f(listing.get("landArea")),
        "floor": _i(listing.get("floor")),  # 0 is parter, same as parse.py
        "floors_total": _i(listing.get("floorMax")),
        "year_built": _i(listing.get("constructionYear")),
        "property_type": listing.get("propertyType"),
        "transaction": listing.get("transaction"),
        # location -- these are imo360's resolution and are trustworthy; the
        # title above is the source ad's headline and often is not.
        "location": listing.get("fullAddress"),
        "address_text": listing.get("fullAddress") or listing.get("address"),
        "area": listing.get("zone"),
        "city": listing.get("locality"),
        "county": listing.get("region"),
        "zone_id": _i(listing.get("zoneId")),
        "lat": _f(listing.get("latitude")),
        "lng": _f(listing.get("longitude")),
        "postal_code": listing.get("postalCode"),
        # An exact coordinate *is* the exact location; `exact_location` gates
        # street-level geocoding downstream and this source always has one.
        "exact_location": listing.get("latitude") is not None,
        # Not published by this source, but present as None rather than
        # absent: `filter_and_rank` indexes these keys directly, and a missing
        # value has to reach it as a value that fails its constraint -- an
        # absent key would be a KeyError instead.
        "metro_distance_m": None,
        "metro_label": None,
        # seller / offer
        "seller_type": listing.get("sellerType"),
        "agency": None,
        "vacant": None,
        "commission_zero": False,  # not published by this source
        "exclusive": False,
        # freshness
        "listed": listing.get("createdAt"),
        "updated": listing.get("updatedAt"),
        "days_on_market": _days_since(listing.get("createdAt")),
        "is_new_build": None,
        # media
        "image_urls": _images(listing),
        "has_video": False,
        "has_virtual_tour": False,
        "has_floor_plan": False,
        "description": listing.get("description"),
    }
    record["photos"] = len(record["image_urls"])
    if score := _score(listing):
        record["imo360_score"] = score
    # Flagged, never dropped -- see the note above `_suspect`. Everything that
    # averages, and only that, filters on it.
    if reason := _suspect(record):
        record["suspect"] = reason
    return record


def _per_sqm_value(price_eur: int | None, surface: float | None) -> float | None:
    if not price_eur or not surface:
        return None
    value = price_eur / surface
    return round(value) if value >= 100 else round(value, 2)


def _images(listing: dict[str, Any]) -> list[str]:
    """Gallery urls, the detail endpoint's list first, then the card's single one."""
    urls = [
        url
        for image in listing.get("images") or []
        if isinstance(image, dict) and (url := image.get("url") or image.get("imageUrl"))
    ]
    if not urls and (single := listing.get("imageUrl")):
        urls = [single]
    return urls


def _days_since(timestamp: Any) -> int | None:
    """Days since the ad was first indexed -- this source's days-on-market.

    Not the same measure imobiliare.ro publishes: it is time since *imo360*
    first saw the ad, so a listing that predates their indexing reads younger
    than it is. Good enough to sort freshness by, not to quote as a fact.
    """
    if not timestamp:
        return None
    try:
        seen = datetime.fromisoformat(str(timestamp))
    except (TypeError, ValueError):
        return None
    now = datetime.now(seen.tzinfo or UTC)
    return max(0, int((now - seen).days))


# -- mis-filed listings ---------------------------------------------------
#
# The `sale` index is not only sale listings. Sorted by price ascending, the
# first page for Gheorgheni (Cluj) returns, in order: a 600 EUR "sale", an ad
# whose own title says *de inchiriat*, a 1500 RON one, and two sales of a
# *cota ideala* -- a 21% undivided share of a flat, not a flat. All are real
# ads; none is a transaction in the property at that price.
#
# They matter out of proportion to their number because of where they land: at
# the bottom of a price sort, which is the first thing a buyer is shown, and
# inside the p25 of any distribution built from the pool. So they are flagged
# rather than deleted -- the ad exists and hiding it would be its own kind of
# wrong -- and every statistic is computed with them excluded.

# Below this, a built property is not being sold at that price. Set well under
# the cheapest real stock in the country (rural flats trade in the low tens of
# thousands) so that the floor only ever catches the mis-filed.
_MIN_SALE_EUR = 15000

# Built property. Land is excluded from the floor: a 5000 EUR rural plot is an
# ordinary listing, not an anomaly.
_BUILT = {"apartment", "house", "office", "commercial_space"}

# Written by the advertiser, in a sale listing, about something that is not a
# sale of the whole property. Diacritic-free because the ads are.
_NOT_A_SALE = (
    "de inchiriat",
    "de închiriat",
    "inchiriere",
    "închiriere",
    "cota ideala",
    "cotă ideală",
    "cota-parte",
    "cota parte",
)


def _suspect(record: dict[str, Any]) -> str | None:
    """Why this record is not usable as evidence of a sale price, if it isn't.

    Deliberately narrow. A false positive removes a real comparable from the
    grid, which is a worse trade than letting an odd listing through -- so
    this catches only what the data says plainly: a price no sale could carry,
    or an advertiser stating in their own words that this is not one.
    """
    if record.get("transaction") != "sale":
        return None
    price = record.get("price_eur")
    if price is not None and price < _MIN_SALE_EUR and record.get("property_type") in _BUILT:
        return f"price of {price} EUR is below any plausible sale price"
    # Only the title: descriptions routinely mention renting out the property
    # afterwards, and matching those would throw away good comparables.
    title = (record.get("title") or "").lower()
    for marker in _NOT_A_SALE:
        if marker in title:
            return f"title says {marker!r} -- not a sale of the whole property"
    return None


# -- duplicates -----------------------------------------------------------
#
# Measured on one zone: 200 listings from `Titanul Nou` collapse to 122 once
# price, surface, rooms and address are compared -- 39% of that page is the
# same property advertised more than once. It matters far more here than it
# does on the imobiliare.ro side, because these records feed medians and a
# published supply count: a flat listed by three agencies is otherwise three
# votes for one price and three units of apparent supply.
#
# What this cannot fix is the upstream `total`. That count is the host's, and
# it is inflated by the same duplication -- which is why `supply` is reported
# as the market's *listing* count and a per-zone median is computed from the
# deduplicated sample rather than from it.

# Fields whose presence makes one record a better survivor than another.
_EVIDENCE = ("year_built", "floor", "floors_total", "rooms", "description", "seller_type")


def _completeness(record: dict[str, Any]) -> int:
    return sum(1 for f in _EVIDENCE if record.get(f) is not None) + len(
        record.get("image_urls") or []
    )


def dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse re-advertisements of the same property, keeping the fullest.

    Unlike `anevar.dedupe`, a record with no price or no surface is *kept*
    rather than dropped: this also runs over lists that are shown to a user,
    and silently deleting a listing because its surface was not published
    would be a worse error than showing it.

    Order is preserved -- it is the caller's ranking, and re-sorting here
    would quietly override the sort they asked for.
    """
    seen_ids: set[Any] = set()
    best: dict[tuple, int] = {}
    out: list[dict[str, Any]] = []
    for record in records:
        listing_id = record.get("id")
        if listing_id is not None and listing_id in seen_ids:
            continue
        if listing_id is not None:
            seen_ids.add(listing_id)

        key = (
            record.get("price_eur"),
            record.get("surface_sqm"),
            record.get("rooms"),
            (record.get("address_text") or "").strip().lower() or None,
        )
        # Too little published to tell one property from another -- keep it
        # rather than merge on an absence.
        if key[0] is None or key[1] is None:
            out.append(record)
            continue
        if (index := best.get(key)) is None:
            best[key] = len(out)
            out.append(record)
        elif _completeness(record) > _completeness(out[index]):
            out[index] = record
    return out


# -- market analytics -----------------------------------------------------

# Below this many usable-area listings, the cleaner measure is abandoned in
# favour of the larger mixed-basis pool. Ten is where the median of one of
# these zones stops moving by more than the bias it is avoiding.
_MIN_USABLE_SAMPLE = 10


# Only listings whose price per sqm was computed from *usable* area feed the
# medians. Mixing the two bases moves a zone median by more than most of the
# differences anyone would be looking for, and the mix varies by zone, so the
# bias is not even constant. Falling back to the mixed pool is allowed, but it
# is reported (`surface_basis`) rather than hidden.
def _per_sqm(records: list[dict[str, Any]], basis: str | None = None) -> tuple[list[float], str]:
    """Prices per sqm and which surface they were measured against.

    `basis` forces the choice. That matters when two pools are being compared:
    a usable-area sale median divided into a built-area rent median is a ~15%
    error dressed up as yield, so `market_snapshot` picks one basis and holds
    both sides to it rather than letting each pick its own.
    """
    usable = [
        r["price_per_sqm"]
        for r in records
        if r.get("price_per_sqm") and r.get("surface_basis") == "usable"
    ]
    mixed = [r["price_per_sqm"] for r in records if r.get("price_per_sqm")]
    if basis == "usable":
        return usable, "usable"
    if basis == "mixed":
        return mixed, "mixed"
    # Unforced: usable is the better measure, but not at any sample size --
    # a median of three is a worse number than a median of forty with a
    # documented bias in it.
    return (usable, "usable") if len(usable) >= _MIN_USABLE_SAMPLE else (mixed, "mixed")


def _quantile(values: list[float], q: float) -> float | None:
    """Nearest-rank quantile. Small samples are the norm here, so no interpolation."""
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def price_stats(records: list[dict[str, Any]], basis: str | None = None) -> dict[str, Any]:
    """Price distribution over normalised records, excluding the mis-filed ones."""
    excluded = sum(1 for r in records if r.get("suspect"))
    records = [r for r in records if not r.get("suspect")]
    prices = [r["price_eur"] for r in records if r.get("price_eur")]
    per_sqm, basis = _per_sqm(records, basis)
    surfaces = [r["surface_sqm"] for r in records if r.get("surface_sqm")]
    return {
        "listings": len(records),
        "with_price": len(prices),
        "excluded_not_a_sale": excluded,
        "price_eur": {
            "min": min(prices) if prices else None,
            "p25": _quantile(prices, 0.25),
            "median": _quantile(prices, 0.5),
            "p75": _quantile(prices, 0.75),
            "max": max(prices) if prices else None,
        },
        "price_per_sqm_eur": {
            "p25": _quantile(per_sqm, 0.25),
            "median": _quantile(per_sqm, 0.5),
            "p75": _quantile(per_sqm, 0.75),
            "sample": len(per_sqm),
            "surface_basis": basis,
        },
        "surface_sqm_median": _quantile(surfaces, 0.5),
    }


def gross_yield(
    sale_median_per_sqm: float | None, rent_median_per_sqm: float | None
) -> float | None:
    """Annual gross yield, in percent, from the two medians.

    Gross on purpose: this says nothing about vacancy, management, tax or
    maintenance, which together take a meaningful bite. It is the number the
    market quotes, and labelling it `gross` is what keeps it honest -- a net
    figure would need assumptions this data cannot supply.
    """
    if not sale_median_per_sqm or not rent_median_per_sqm:
        return None
    return round(rent_median_per_sqm * 12 / sale_median_per_sqm * 100, 2)


def market_snapshot(
    client: Imo360Client,
    *,
    zone_ids: list[int] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    property_type: str | None = "apartment",
    rooms: int | None = None,
    sample: int = 300,
) -> dict[str, Any]:
    """Sale and rental sides of one zone, and the yield between them.

    Two searches rather than one, because the rental index is what the sale
    side cannot tell you: how much the same square metre earns. Supply counts
    come from `total` and are reported only when the host says they are not
    capped -- "at least 10000" is not a market depth.
    """
    geo = {"zone_ids": zone_ids, "bbox": bbox}
    # Sampled newest-first, not best-first. The default ordering is the
    # vendor's own score, and a median computed from the top 300 of 711
    # listings by score is a median of the good ones -- which is exactly the
    # number nobody wants. Recency is a bias too, but it is the one a "what is
    # this zone worth today" question already assumes. When the zone is small
    # enough, `collect` takes the whole population and there is no bias at all.
    order = {"sort_by": "createdAt", "sort_order": "desc"}
    sale = client.collect(
        transaction="sale",
        property_type=property_type,
        rooms=rooms,
        max_results=sample,
        **order,
        **geo,
    )
    rent = client.collect(
        transaction="rent",
        property_type=property_type,
        rooms=rooms,
        max_results=sample,
        **order,
        **geo,
    )
    # Deduplicated before anything is averaged: see the note above `dedupe`.
    sale_records = dedupe([normalise(x) for x in sale.listings])
    rent_records = dedupe([normalise(x) for x in rent.listings])

    # One surface basis for both sides, chosen by whichever side has the
    # thinner usable-area pool. A yield is a ratio of the two medians, so it
    # is only meaningful when both were measured the same way -- letting each
    # side pick its own basis was producing yields off by the built-to-usable
    # ratio, in whichever direction the two pools happened to differ.
    basis = "mixed"
    if all(
        len([r for r in pool if r.get("surface_basis") == "usable"]) >= _MIN_USABLE_SAMPLE
        for pool in (sale_records, rent_records)
    ):
        basis = "usable"
    sale_stats = price_stats(sale_records, basis)
    rent_stats = price_stats(rent_records, basis)

    return {
        "supply": {
            "for_sale": sale.supply,
            "for_rent": rent.supply,
            # The ratio is the liquidity read: a zone with 109 flats for sale
            # and 94 for rent behaves very differently from one with 400 and 8.
            "rent_share_pct": (
                round(rent.supply / (sale.supply + rent.supply) * 100, 1)
                if sale.supply and rent.supply
                else None
            ),
            "capped": sale.total_is_capped or rent.total_is_capped,
        },
        "sale": sale_stats,
        "rent": rent_stats,
        "gross_yield_pct": gross_yield(
            sale_stats["price_per_sqm_eur"]["median"],
            rent_stats["price_per_sqm_eur"]["median"],
        ),
        # Named so a reader can tell a yield drawn from forty comparables from
        # one drawn from four, which the number itself does not say.
        "basis": {
            "surface": basis,
            "sale_sample": sale_stats["price_per_sqm_eur"]["sample"],
            "rent_sample": rent_stats["price_per_sqm_eur"]["sample"],
        },
        "sample": {
            # `complete` says whether the statistics are of the whole market
            # in that zone or of a newest-first sample of it.
            "complete": not (sale.total_is_capped or rent.total_is_capped)
            and sale.total <= sample
            and rent.total <= sample,
            "sale": len(sale_records),
            "rent": len(rent_records),
            # How much of the raw pull was re-advertisement. A zone where this
            # runs high is one where the supply count above is least reliable.
            "duplicates_removed": (len(sale.listings) - len(sale_records))
            + (len(rent.listings) - len(rent_records)),
        },
    }
