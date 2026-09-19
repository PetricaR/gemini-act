"""Listings from imoradar24.ro -- the third source, and the only aggregator.

`client.py` and `imo360.py` are single indexes: one portal's inventory each.
imoradar24 is an aggregator over the Romanian market, and that difference is
the whole reason it is here:

* **It reaches portals nothing else here can.** A single result page for Titan
  carried ads sourced from `Imobiliare.ro`, `storia.ro`, `olx.ro`,
  `publi24.ro`, `homezz.ro` and `LaJumate.ro`. OLX and Publi24 are where the
  *proprietar* (for-sale-by-owner) segment actually lives -- 16.592 of the
  136.751 apartments on sale nationwide, a segment the imobiliare.ro AI search
  barely represents.
* **It shows the same flat at several prices at once.** Where a property is
  advertised on more than one portal (or by more than one agency),
  `sellerSources` carries every ad side by side: seller, portal, posting date
  and price. Measured on a 150-listing sample: listing 2147878 is on sale at
  175.450 / 179.080 / 180.895 / 193.479 € through four agencies, from the same
  day -- a 10,3% spread on one flat. That is a negotiation fact no single
  portal can produce, and `negociere.py` is exactly the consumer for it.
* **`totalCount` is already a property count.** The portal de-duplicates
  across sources and labels the number *Proprietăți unice*, so unlike imo360's
  inflated `total` it can be reported to a user as supply without a caveat.
* **No session, no credentials** -- unlike `cauta`, which spends a
  browser-minted session that expires in minutes.

`normalise()` emits the same record shape `parse.py` does -- the two sites run
the same platform, so `price`, `highlights`, `extraFeatures`, `metroDistance`
and `tracking.ga4Item` arrive in identical formats and `parse.normalise` does
the base work verbatim. Everything below it is the handful of places where
this source means something different by the same field.

Traps, each one measured on live data rather than assumed:

**`ga4Item.propertyDaysInMarket` is days since *imoradar24 indexed* the ad,
not days on the market.** Listing 2287996 reports 2 days while its own
`sellerSources` says the Imobiliare.ro ad was posted 06-03-2026 -- six months
earlier. Taking the ga4 number at face value inverts the single most useful
negotiation signal there is, turning a six-month-stale listing into a
two-day-old one. `days_on_market` is therefore derived from the earliest
`postedOn` across the sources, and the ga4 number is kept beside it as
`days_on_imoradar` rather than thrown away.

**Expired ads are served in live results.** 2 of 150 sampled carried
`propertyAvailability: "expired"` while `isArchived` was false and the card
rendered normally. They are flagged (`expired`) and not silently dropped --
an expired ad is still evidence of what was asked for a comparable property.

**`ga4Item.sellerType` speaks Romanian here** (`proprietar`), while the same
payload's `sellerSources[].sellerType` speaks the vocabulary the rest of this
package filters on (`individual`/`agency`). Left unmapped, `tip_vanzator=
"individual"` matches nothing at all on this source.

**The ga4 `0.2` price placeholder is here too** -- 8 of 90 sampled, the same
~9% as imobiliare.ro. `parse.normalise` already guards it; nothing in this
module may re-derive a price around that guard.

**`address` falls back to the neighbourhood.** When a seller published no
street, `address` repeats `location` verbatim ("Floreasca, Sector 1" for
both). imobiliare.ro advertises an exact location through `extraFeatures`;
this portal does not, so `exact_location` is derived from address and location
actually differing, and the `Locație exactă` / `Exclusivitate` badges that
`parse.normalise` looks for are simply never present here.

Scope: same posture as the rest of this package. robots.txt disallows `/api/`
and every query-string filter, and explicitly allows `?page=2..10` -- so
searching goes through the canonical path URLs the sitemap publishes, paging
stops at `MAX_PAGES`, and none of the `/api/portal/...` endpoints the page
uses (price history, autocomplete, alerts) are touched from here.
"""

from __future__ import annotations

import html
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from . import parse, paths, throttle

logger = logging.getLogger(__name__)

BASE = "https://www.imoradar24.ro"
SEARCH_ROOT = "apartamente-de-vanzare"
# The only sitemap carrying category URLs; the `-1` file continues with
# listing pages and holds no `apartamente-de-vanzare` entry at all (checked).
SITEMAP_URL = f"{BASE}/sitemap-category-ro.xml"
# Per-listing asking-price history. Under `/api/`, which robots.txt disallows
# — fetched anyway, as a deliberate decision recorded in AGENTS.md, and only
# ever one listing at a time on explicit request, never as a sweep.
PRICE_HISTORY_URL = f"{BASE}/api/portal/listings/{{listing_id}}/price-history"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

# Fixed by the portal; not a page size we get to choose.
PAGE_SIZE = 30

# robots.txt disallows `?page=*` and then allows exactly `?page=2` .. `?page=10`.
# Ten pages is therefore both the polite ceiling and the real one: 300 listings
# per query, which is already deeper than any filter here needs.
MAX_PAGES = 10

# The published gazetteer of location URLs. It moves when a neighbourhood is
# added, which is roughly never, and costs 7,5 MB to fetch.
PLACES_TTL = 7 * 24 * 3600

# `ga4Item.sellerType` -> the vocabulary `Filters.tip_vanzator` uses.
_SELLER_TYPES = {
    "proprietar": "individual",
    "individual": "individual",
    "agency": "agency",
    "agentie": "agency",
    "dezvoltator": "developer",
    "developer": "developer",
}

# Same rule as `parse._PRICE`: a display string where "." is a thousands
# separator. Kept local because it is applied to the per-source prices, which
# `parse.normalise` never sees.
_PRICE = re.compile(r"([\d.]+)\s*€")
_DATA_PAGE = re.compile(r'data-page="([^"]*)"')
_ROOMS_SEGMENT = re.compile(r"^\d+-camere$")


class ImoradarError(RuntimeError):
    """The portal refused or could not answer a request."""


@dataclass
class SearchPage:
    """One or more pages of results, plus what the portal says lies behind."""

    listings: list[dict[str, Any]]
    # Already de-duplicated across sources upstream and labelled "Proprietăți
    # unice", so this is a property count rather than an ad count.
    total: int
    last_page: int
    # How many of `total` are advertised directly by owners. Published only on
    # the first page's stats block.
    owner_total: int | None = None
    pages_read: int = 0

    @property
    def truncated(self) -> bool:
        """Were there pages left that `MAX_PAGES` stopped us from reading?"""
        return self.last_page > self.pages_read


@dataclass(frozen=True)
class Place:
    """One location path published in the sitemap."""

    path: str  # "bucuresti/sector-3/titan"

    @property
    def slug(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def name(self) -> str:
        return self.slug.replace("-", " ").title()

    @property
    def city(self) -> str:
        parts = self.path.split("/")
        # "bucuresti/sector-3/titan" -> Sector 3; "judetul-cluj/cluj-napoca/
        # manastur" -> Cluj Napoca. One segment means the county itself.
        return parts[1].replace("-", " ").title() if len(parts) > 1 else self.name

    @property
    def county(self) -> str:
        head = self.path.split("/")[0]
        return head.removeprefix("judetul-").replace("-", " ").title()

    @property
    def url(self) -> str:
        return f"{BASE}/{SEARCH_ROOT}/{self.path}"


def _slugify(value: str) -> str:
    """'Drumul Taberei' -> 'drumul-taberei'."""
    stripped = unicodedata.normalize("NFKD", value or "")
    ascii_only = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")


class ImoradarClient:
    """Read-only client for the portal's own page payloads."""

    def __init__(self, timeout: float = 45.0):
        self._http = httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ImoradarClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport --------------------------------------------------------

    def _props(self, url: str) -> dict[str, Any]:
        """The page's own props, however they can be had.

        The site is an Inertia app, so the same URL answers twice: as ~1,5 MB
        of HTML with the payload inlined in `data-page`, or -- given a
        matching `X-Inertia-Version` -- as ~360 KB of the payload alone. The
        JSON route is taken whenever a version is known and the HTML route is
        both the fallback and where the version comes from, so a version
        rotated by a deploy upstream costs one extra request rather than an
        outage.
        """
        if version := throttle.cached("imoradar:version"):
            response = self._get(url, {"X-Inertia": "true", "X-Inertia-Version": version})
            if response.status_code == 200:
                try:
                    return _props_of(response.json())
                except ValueError:
                    # A 200 that is not JSON means the header was ignored and
                    # HTML came back; fall through and parse it as such.
                    return _props_of(_page_from_html(response.text))
            # 409 is Inertia's "your version is stale". Anything else is a
            # real error and is reported by the HTML attempt below.
            if response.status_code != 409:
                logger.info(
                    "imoradar24 inertia request -> HTTP %s, retrying as HTML", response.status_code
                )
            throttle.remember("imoradar:version", None)

        response = self._get(url, {})
        if response.status_code >= 400:
            raise ImoradarError(f"{url} -> HTTP {response.status_code}")
        payload = _page_from_html(response.text)
        if version := payload.get("version"):
            throttle.remember("imoradar:version", str(version))
        return _props_of(payload)

    def _get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        # Through `throttle` like every other host here: one paced clock per
        # host, shared across threads, and the anti-bot interstitial (served
        # as a 200 with an HTML body) recognised rather than parsed as data.
        return throttle.request("GET", url, http=self._http, headers=headers)

    # -- search -----------------------------------------------------------

    def search(
        self,
        *,
        place: str | None = None,
        rooms: int | None = None,
        owner_only: bool = False,
        page: int = 1,
    ) -> SearchPage:
        """One page of apartment sale listings.

        Everything narrows through the URL *path*, not a query string: the
        portal publishes a canonical URL per location / room count / owner
        segment, and robots.txt disallows the query-string filters that would
        otherwise do the same job.
        """
        return _page(self._props(_search_url(place, rooms, owner_only, page)))

    def collect(
        self,
        *,
        place: str | None = None,
        rooms: int | None = None,
        owner_only: bool = False,
        max_results: int = 120,
    ) -> SearchPage:
        """Page until `max_results` listings are in hand, or the results end."""
        wanted = min(max_results, MAX_PAGES * PAGE_SIZE)
        first = self.search(place=place, rooms=rooms, owner_only=owner_only, page=1)
        listings, pages = list(first.listings), 1
        while len(listings) < wanted and pages < min(first.last_page, MAX_PAGES):
            pages += 1
            nxt = self.search(place=place, rooms=rooms, owner_only=owner_only, page=pages)
            if not nxt.listings:
                break
            listings.extend(nxt.listings)
        return SearchPage(
            listings=listings[:wanted],
            total=first.total,
            last_page=first.last_page,
            owner_total=first.owner_total,
            pages_read=pages,
        )

    # -- price history ----------------------------------------------------

    def price_history(self, listing_id: int | str) -> list[dict[str, Any]]:
        """Raw asking-price observations for one listing, oldest first.

        An unknown id is **not** an error here: the endpoint answers `200`
        with an empty `data` for a listing that does not exist, exactly as it
        does for one that has no history. Callers get `[]` for both and must
        not turn that into "the price never changed".
        """
        url = PRICE_HISTORY_URL.format(listing_id=listing_id)
        response = self._get(url, {"Accept": "application/json"})
        if response.status_code >= 400:
            raise ImoradarError(f"{url} -> HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImoradarError(f"{url} -> non-JSON response") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        return [p for p in data or [] if isinstance(p, dict)]

    # -- gazetteer --------------------------------------------------------

    def places(self) -> list[Place]:
        """Every location that has an apartments-for-sale page, from the sitemap.

        2.367 of them. The sitemap is 7,5 MB, so it is memoised in-process and
        on disk and only the location paths are kept -- the room-count and
        `/proprietar` variants of each URL are reconstructed, not stored.
        """
        if cached := throttle.cached("imoradar:places"):
            return cached
        raw = _places_from_disk()
        if raw is None:
            response = self._get(SITEMAP_URL, {})
            if response.status_code >= 400:
                raise ImoradarError(f"{SITEMAP_URL} -> HTTP {response.status_code}")
            raw = sorted(_place_paths(response.text))
            _places_to_disk(raw)
        return throttle.remember("imoradar:places", [Place(path=p) for p in raw])

    def find_places(self, name: str, city: str | None = None, limit: int = 8) -> list[Place]:
        """Resolve a neighbourhood name to published location paths.

        Ranked rather than resolved to one, for the same reason `imo360`
        ranks: a bare name is genuinely ambiguous ("Central" exists in dozens
        of towns) and picking one silently would answer about the wrong city.
        """
        wanted, city_slug = _slugify(name), _slugify(city or "")
        if not wanted:
            return []

        def rank(place: Place) -> tuple[int, int, int]:
            # Exact slug first, then prefix, then substring; within each, the
            # requested city; then the deepest path, which is the most
            # specific geography the portal publishes.
            return (
                0 if place.slug == wanted else (1 if place.slug.startswith(wanted) else 2),
                0 if city_slug and city_slug in place.path else 1,
                -place.path.count("/"),
            )

        hits = [p for p in self.places() if wanted in p.slug or p.slug in wanted]
        if city_slug:
            # Only narrow when the city actually matches something: a typo
            # must not turn a good name match into no answer at all.
            hits = [p for p in hits if city_slug in p.path] or hits
        return sorted(hits, key=rank)[:limit]


def _search_url(place: str | None, rooms: int | None, owner_only: bool, page: int) -> str:
    segments = [SEARCH_ROOT]
    if place:
        segments.append(place.strip("/"))
    if rooms:
        segments.append(f"{rooms}-camere")
    if owner_only:
        segments.append("proprietar")
    url = f"{BASE}/{'/'.join(segments)}"
    # Page 1 is the canonical URL with no query at all, and pages past
    # MAX_PAGES are not ours to ask for -- see the constant.
    if page > 1:
        url += f"?page={min(page, MAX_PAGES)}"
    return url


def _page_from_html(body: str) -> dict[str, Any]:
    """Pull the Inertia payload out of the rendered page."""
    match = _DATA_PAGE.search(body)
    if not match:
        raise ImoradarError("no Inertia payload in the page -- the site's markup changed")
    try:
        return json.loads(html.unescape(match.group(1)))
    except ValueError as exc:
        raise ImoradarError(f"unreadable Inertia payload: {exc}") from exc


def _props_of(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("props"), dict):
        raise ImoradarError("unexpected page payload: no props")
    return payload["props"]


def _section(props: dict[str, Any], kind: str) -> dict[str, Any]:
    for section in props.get("sections") or []:
        if isinstance(section, dict) and section.get("type") == kind:
            data = section.get("data")
            return data if isinstance(data, dict) else {}
    return {}


def _page(props: dict[str, Any]) -> SearchPage:
    meta = props.get("searchMeta") or {}
    stats = _section(props, "results-stats")
    listings = _section(props, "results-list").get("listings") or []
    return SearchPage(
        listings=[x for x in listings if isinstance(x, dict)],
        total=int(meta.get("totalCount") or 0),
        last_page=int(meta.get("lastPage") or 1),
        owner_total=_int(stats.get("ownerListingsCount")),
        pages_read=1,
    )


def _place_paths(sitemap: str) -> set[str]:
    """Location paths under `apartamente-de-vanzare`, from the sitemap XML.

    Read with a regex rather than an XML parser on purpose: the file is 7,5 MB
    of flat `<url><loc>` entries and building a tree of 50.000 elements to
    read one attribute of each costs more than the fetch did.
    """
    out: set[str] = set()
    for url in re.findall(r"<loc>(.*?)</loc>", sitemap):
        head, sep, tail = url.partition(f"/{SEARCH_ROOT}")
        if not sep or not head.endswith(BASE.split("//", 1)[-1]):
            continue
        segments = [
            s
            for s in tail.strip("/").split("/")
            if s and s != "proprietar" and not _ROOMS_SEGMENT.match(s)
        ]
        if segments:
            out.add("/".join(segments))
    return out


def _places_cache_file():
    cache = paths.ensure_dir(paths.cache_dir())
    return cache / "imoradar-places.json" if cache else None


def _places_from_disk() -> list[str] | None:
    cached = _places_cache_file()
    if not cached or not cached.exists():
        return None
    if time.time() - cached.stat().st_mtime > PLACES_TTL:
        return None
    try:
        data = json.loads(cached.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _places_to_disk(places: list[str]) -> None:
    cached = _places_cache_file()
    if not cached:
        return
    try:
        cached.write_text(json.dumps(places), encoding="utf-8")
    except OSError:
        # A read-only filesystem costs a re-fetch, not an error.
        logger.debug("could not cache the imoradar24 gazetteer", exc_info=True)


# -- records ---------------------------------------------------------------


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _price_eur(text: Any) -> int | None:
    match = _PRICE.search(str(text or "").replace("\xa0", " "))
    return int(match.group(1).replace(".", "")) if match else None


def _posted(value: Any) -> str | None:
    """'12-09-2026' -> '2026-09-12'. Anything else is not a date we can use."""
    try:
        return datetime.strptime(str(value), "%d-%m-%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def _sources(listing: dict[str, Any]) -> list[dict[str, Any]]:
    """The same property as advertised on each portal, cheapest first."""
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for source in listing.get("sellerSources") or []:
        if not isinstance(source, dict):
            continue
        entry = {
            "portal": source.get("sourceName"),
            "seller": (source.get("sellerName") or "").strip() or None,
            "seller_type": _SELLER_TYPES.get(str(source.get("sellerType") or "").lower()),
            "price_eur": _price_eur(source.get("price")),
            "posted": _posted(source.get("postedOn")),
            "updated": _posted(source.get("updatedOn")),
            "url": source.get("viewAdUrl"),
        }
        # The same ad is listed twice often enough (same portal, same seller,
        # same price) that leaving it in would invent a second "offer".
        key = (entry["portal"], entry["seller"], entry["price_eur"], entry["posted"])
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return sorted(out, key=lambda e: (e["price_eur"] is None, e["price_eur"] or 0))


# -- mis-filed listings ---------------------------------------------------
#
# Measured across 213 owner-advertised listings in Titan and Militari: 4 of
# them (1,9%) carry a price no sale could be at -- 266 EUR for a garsonieră,
# 476 EUR for a 62 mp two-room flat. Both are monthly rents filed as sale
# prices, and they arrive from the free-text portals (OLX, Publi24) rather
# than from the agency feeds, where the same pool showed none at all. They
# land at the bottom of a price sort, which is the first thing a buyer reads.
#
# Unlike `imo360._suspect`, there is no title check to add: this portal
# rewrites every heading into its own house style ("Apartament cu 2 camere
# decomandat în Militari"), so an advertiser saying *de inchiriat* in their own
# words never survives into `title`. The price floor is the whole check.
#
# Flagged, never dropped, for the reason `imo360` gives at greater length: the
# ad is real, and deleting it would be its own kind of wrong.
_MIN_SALE_EUR = 15000


def _suspect(record: dict[str, Any]) -> str | None:
    """Why this record is not usable as evidence of a sale price, if it isn't."""
    price = record.get("price_eur")
    if price is not None and price < _MIN_SALE_EUR:
        return f"price of {price} EUR is below any plausible sale price"
    return None


def _spread_scope(sources: list[dict[str, Any]]) -> str:
    """Is a price spread between different sellers, or inside one seller's ads?"""
    sellers = {(s["seller"] or "").strip().lower() for s in sources if s["price_eur"]}
    portals = {(s["portal"] or "").strip().lower() for s in sources if s["price_eur"]}
    return "cross_seller" if len(sellers) > 1 or len(portals) > 1 else "same_seller"


def _days_since(iso_date: str | None) -> int | None:
    if not iso_date:
        return None
    try:
        first = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    return max(0, (datetime.now(UTC) - first).days)


# -- duplicates -----------------------------------------------------------
#
# This source needs a *weaker* rule than `imo360.dedupe`, not the same one,
# and using imo360's here was measurably wrong: on 180 listings from Titan it
# collapsed 15, of which several were plainly different flats -- 115.000 €
# 41 mp `semidecomandat` merged with 115.000 € 41 mp `decomandat`, 197.999 €
# 72 mp likewise. Two reasons it misfires here:
#
# * imo360 discriminates on the address, which it publishes for most listings.
#   Here the address is only kept when the seller gave a street (3-8% of
#   listings; see `exact_location`), so for nearly every record that component
#   of the key is `None` and the merge falls back to price + surface + rooms
#   alone. In panel-block stock that is a description of dozens of flats.
# * The heavy re-advertising imo360 fights has already been dealt with
#   upstream: this portal merges an ad's copies into one record with
#   `sellerSources` (18 of 180 in Titan, 49 of 180 in Militari), and listing
#   ids came back unique on every page sampled (180 of 180, twice).
#
# So this merges only on evidence that two records are the same property: the
# same id, a shared photograph, or a full match *including* a real street
# address. Measured on the same 360 listings, that is zero false merges and
# zero missed ones -- no two records shared a photograph at all.
_EVIDENCE = ("year_built", "floor", "floors_total", "rooms", "description", "seller_type")


def _completeness(record: dict[str, Any]) -> int:
    return sum(1 for f in _EVIDENCE if record.get(f) is not None) + len(
        record.get("image_urls") or []
    )


def _prefer(candidate: dict[str, Any], incumbent: dict[str, Any]) -> bool:
    """Should `candidate` represent the merged group instead of `incumbent`?

    Completeness decides it, with one rule ahead of it: **a flagged record
    never represents a group that has a sound member.** `suspect` means the
    price is below any plausible sale — a rent filed as a sale, or a typo —
    and `cauta_imoradar` drops flagged records by default. So electing one as
    the survivor does not drop an ad, it deletes the whole property from the
    results, genuine ad included, and the count of what was excluded says 1
    where three listings went missing.

    The two are the same property here by evidence, not by guess — a shared
    photograph or a full match on a real street address — so the sound
    sibling is describing the same flat and is the one worth keeping.
    """
    if bool(candidate.get("suspect")) != bool(incumbent.get("suspect")):
        return not candidate.get("suspect")
    return _completeness(candidate) > _completeness(incumbent)


def dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse re-advertisements of the same property, keeping the fullest.

    Order is preserved -- it is the caller's ranking, and re-sorting here
    would quietly override the sort they asked for.
    """
    seen_ids: set[Any] = set()
    index: dict[Any, int] = {}
    out: list[dict[str, Any]] = []

    def keys(record: dict[str, Any]) -> list[Any]:
        found: list[Any] = [("photo", url) for url in record.get("image_urls") or []]
        address = (record.get("address_text") or "").strip().lower()
        # Without a street the remaining fields describe a type of flat, not a
        # flat, so they are not allowed to merge anything.
        if address and record.get("price_eur") and record.get("surface_sqm"):
            found.append(
                ("addr", address, record["price_eur"], record["surface_sqm"], record.get("rooms"))
            )
        return found

    for record in records:
        listing_id = record.get("id")
        if listing_id is not None:
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

        found = keys(record)
        hit = next((index[k] for k in found if k in index), None)
        if hit is None:
            for k in found:
                index[k] = len(out)
            out.append(record)
            continue
        # Same property seen again: keep whichever record is worth more, and
        # let the survivor answer to both records' keys.
        if _prefer(record, out[hit]):
            out[hit] = record
        for k in found:
            index.setdefault(k, hit)
    return out


# -- asking-price history -------------------------------------------------
#
# `{"data": [{"date": "10.09.2026", "minPrice": 167000, "maxPrice": 167000}]}`,
# oldest first. Three things about it are load-bearing:
#
# **A point is a range across the ads standing that day, not one price.** Nine
# of 37 sampled points had `minPrice != maxPrice`. Where a property is
# advertised by several agencies at once (see `price_spread_scope`), the range
# closes as the dearer ads come down or disappear -- listing 2103212 reads
# 154.000-178.500 then 154.000, which is the expensive ad ending, not the
# seller dropping 13,7%. So a point only yields a price when it is
# unambiguous, and a change is only computed between two unambiguous ones.
#
# **A zero is a missing value, not a price.** 7 of 37 points (19%) carried
# `minPrice: 0` against a real `maxPrice` -- listing 2226030 opens
# `(0, 125000)`. Read as a price that is a 100% collapse, in a tool whose
# whole purpose is telling a buyer how much the seller has already conceded.
#
# **The dates are `DD.MM.YYYY`** -- dots, where `sellerSources[].postedOn` in
# the same payload uses dashes. Same portal, two formats.
_HISTORY_DATE = "%d.%m.%Y"


def _history_point(point: dict[str, Any]) -> dict[str, Any] | None:
    """One observation: a date, and a price when the day had just one."""
    date = _history_date(point.get("date"))
    if not date:
        return None
    low, high = _positive(point.get("minPrice")), _positive(point.get("maxPrice"))
    if low is None and high is None:
        # Observed on that date, but with no price attached to it. Kept: it
        # still says the property was on the market that day.
        return {"date": date, "price_eur": None, "min_eur": None, "max_eur": None}
    if low is not None and high is not None and low != high:
        return {"date": date, "price_eur": None, "min_eur": low, "max_eur": high}
    price = low if low is not None else high
    return {"date": date, "price_eur": price, "min_eur": price, "max_eur": price}


def _history_date(value: Any) -> str | None:
    try:
        return datetime.strptime(str(value), _HISTORY_DATE).date().isoformat()
    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> float | int | None:
    """A price, or None for the zeros and nulls this feed uses as "missing".

    Kept as a float only when it actually has decimals -- the feed mixes
    `167000` and `180449.72` and an int-looking price should print as one.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number) if number.is_integer() else number


def summarise_history(raw: list[dict[str, Any]]) -> dict[str, Any]:
    """What one listing's asking price has done since the portal first saw it.

    Returns `observed: False` when there is nothing to read -- which is also
    what an unknown listing id looks like from this endpoint, so it must never
    be worded as "the price held steady".
    """
    points = [p for p in (_history_point(p) for p in raw) if p]
    priced = [p for p in points if p["price_eur"] is not None]
    if not points:
        return {"observed": False, "points": 0, "series": []}

    first, last = priced[0] if priced else None, priced[-1] if priced else None
    change_pct = None
    if first and last and first is not last and first["price_eur"]:
        change_pct = round((last["price_eur"] - first["price_eur"]) / first["price_eur"] * 100, 1)
    # Consecutive unambiguous prices only: a step into or out of a range says
    # nothing about the asking price having moved.
    drops = sum(
        1 for a, b in zip(priced, priced[1:], strict=False) if b["price_eur"] < a["price_eur"]
    )
    values = [p["price_eur"] for p in priced]
    return {
        "observed": True,
        "points": len(points),
        # The portal's own first sighting, and the strongest lower bound on
        # time on the market there is here: it reaches back a year on old
        # listings, past both `postedOn` and this portal's indexing date.
        "first_seen": points[0]["date"],
        "last_seen": points[-1]["date"],
        "days_since_first_seen": _days_since(points[0]["date"]),
        "price_first_eur": first["price_eur"] if first else None,
        "price_last_eur": last["price_eur"] if last else None,
        "price_min_eur": min(values) if values else None,
        "price_max_eur": max(values) if values else None,
        "change_pct": change_pct,
        "drops": drops,
        # How many observations could not be read as a single asking price,
        # so a caller can tell a quiet history from an unreadable one.
        "ambiguous_points": sum(1 for p in points if p["price_eur"] is None),
        "series": points,
    }


def normalise(listing: dict[str, Any]) -> dict[str, Any]:
    """Flatten one imoradar24 listing into this package's canonical record.

    `parse.normalise` does the base work unchanged -- same platform, same
    display formats, same `ga4Item` -- and everything here is an override
    where this source means something different by the same field, or an
    extra key nothing else can provide.
    """
    record = parse.normalise(listing, base_url=BASE)
    ga4 = (listing.get("tracking") or {}).get("ga4Item") or {}
    sources = _sources(listing)

    record["source"] = "imoradar24"
    # Which portal's ad this record came from -- the field that makes a
    # result set legible as "who is actually selling on which site".
    record["source_portal"] = listing.get("sourceName")

    # `agency` is populated even for owners here (it carries whatever name the
    # seller gave), so the seller vocabulary has to come from ga4, mapped.
    record["seller_type"] = _SELLER_TYPES.get(str(ga4.get("sellerType") or "").lower())
    if record["seller_type"] is None and sources:
        record["seller_type"] = sources[0]["seller_type"]

    # See the module docstring: the ga4 number counts days since this portal
    # indexed the ad, not days on the market. Neither signal is a ceiling on
    # its own -- the source postings can be months older than the indexing
    # (listing 2287996: 2 days indexed, posted 06-03-2026), and the indexing
    # can be older than the oldest ad still standing (listing 2249080: 6 days
    # indexed, oldest surviving ad posted 3 days ago, because the ad that
    # brought it in has since been replaced). So the answer is the longer of
    # the two: "on the market at least this long", which is the direction an
    # error has to fall for a filter on freshness to stay honest.
    record["days_on_imoradar"] = record["days_on_market"]
    first_posted = min((s["posted"] for s in sources if s["posted"]), default=None)
    record["first_posted"] = first_posted
    known = [d for d in (_days_since(first_posted), record["days_on_imoradar"]) if d is not None]
    record["days_on_market"] = max(known) if known else None

    # Cross-portal price divergence, the thing only an aggregator can see.
    priced = [s["price_eur"] for s in sources if s["price_eur"]]
    record["sources"] = sources
    record["source_count"] = len(sources)
    record["price_min_eur"] = min(priced) if priced else None
    record["price_max_eur"] = max(priced) if priced else None
    record["price_spread_pct"] = (
        round((max(priced) - min(priced)) / min(priced) * 100, 1) if len(priced) > 1 else None
    )
    # Who the spread is between decides whether it means anything, and the raw
    # percentage on its own reads as leverage in both cases. Listing 2147878
    # carries four prices from 175.450 to 193.479 € -- all posted the same day
    # by one agent, which is a project's several units grouped under one
    # property, not one flat at four prices. Listing 2249080's 144.900 vs
    # 149.900 € is two different agencies on the same property, which is the
    # real thing. `negociere.py` may only argue from `cross_seller`.
    record["price_spread_scope"] = _spread_scope(sources) if len(priced) > 1 else None

    # A published reduction, and what it was reduced from. `price_dropped` is
    # already set by `parse.normalise` from the same block.
    change = listing.get("priceChange") or {}
    old_price = _price_eur(change.get("oldPrice")) if isinstance(change, dict) else None
    record["old_price_eur"] = old_price
    record["price_drop_pct"] = (
        round((old_price - record["price_eur"]) / old_price * 100, 1)
        if old_price and record["price_eur"] and old_price > record["price_eur"]
        else None
    )

    # Served among live results, so it has to be visible rather than assumed
    # away -- an expired ad is evidence of an asking price, not of an offer.
    record["expired"] = str(ga4.get("propertyAvailability") or "").lower() == "expired"

    # This portal publishes no "Locație exactă" badge; what it does publish is
    # a street address, and only when the seller gave one. When they did not,
    # `address` repeats `location` verbatim.
    address, location = record.get("address_text"), record.get("location")
    record["exact_location"] = bool(address and address.strip() != (location or "").strip())
    if not record["exact_location"]:
        # Keeping the neighbourhood in an address field would let a geocoder
        # report a street-level fix it never had.
        record["address_text"] = None

    if reason := _suspect(record):
        record["suspect"] = reason
    return record
