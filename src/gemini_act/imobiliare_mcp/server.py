"""MCP server exposing imobiliare.ro's AI property search.

Run with:  imobiliare-mcp     (or: python -m imobiliare_mcp.server)
"""

from __future__ import annotations

import json
import logging
import os
import re
import statistics
from pathlib import Path
from typing import Annotated, Any, Literal

# The class was renamed between MCP SDK majors: `FastMCP` on 1.x,
# `MCPServer` on 2.x. This package was written against 2.x, but google-adk
# pins 1.x, and both are in the wild — so accept either rather than forcing a
# resolution that would fight the ADK dependency.
#
# What matters for `agent/tools/imobiliare.py` is unaffected by the rename:
# on both SDKs `@mcp.tool()` returns the *plain function*, so every tool below
# stays directly callable as itself and does not need unwrapping. (Verified on
# 1.29.0; older 1.x wrapped it in an object exposing `.fn`.)
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover - depends on which SDK major is installed
    from mcp.server.fastmcp import FastMCP as MCPServer
from pydantic import BaseModel, Field

from . import (
    comps,
    costuri,
    drive_docs,
    imo360,
    imoradar,
    locatie,
    maps,
    negociere,
    paths,
    viziune,
)
from .anevar import Params, dedupe, evaluate, is_furnished
from .client import ImobiliareClient, SessionError
from .galerie import contact_sheet
from .parse import filter_and_rank, normalise
from .raport import render

logger = logging.getLogger(__name__)

mcp = MCPServer("imobiliare")

SellerType = Literal["agency", "individual", "developer"]
SortBy = Literal[
    "metro", "price", "price_desc", "price_per_sqm", "surface", "newest", "year_built", "relevance"
]


class Filters(BaseModel):
    """Hard constraints applied locally to the real listing data.

    The AI layer handles intent; these enforce the numbers. A listing whose
    value for a constrained field is missing is dropped, not kept.
    """

    # money
    pret_max: int | None = Field(None, description="Maximum price in EUR")
    pret_min: int | None = Field(None, description="Minimum price in EUR")
    pret_mp_max: int | None = Field(None, description="Maximum price per usable sqm, in EUR")
    pret_redus: bool | None = Field(
        None, description="Only listings whose price was recently reduced"
    )

    # size and layout
    camere: int | None = Field(None, description="Exact number of rooms")
    camere_min: int | None = Field(None, description="Minimum number of rooms")
    camere_max: int | None = Field(None, description="Maximum number of rooms")
    suprafata_min: float | None = Field(None, description="Minimum usable surface, sqm")
    suprafata_max: float | None = Field(None, description="Maximum usable surface, sqm")
    etaj_min: int | None = Field(None, description="Minimum floor (0 = parter, -1 = demisol)")
    etaj_max: int | None = Field(None, description="Maximum floor")
    fara_parter: bool = Field(False, description="Exclude ground floor and below")
    fara_ultim_etaj: bool = Field(False, description="Exclude top-floor apartments")
    an_min: int | None = Field(None, description="Built no earlier than this year")
    an_max: int | None = Field(None, description="Built no later than this year")

    # location
    metrou_max_m: float | None = Field(
        None,
        description="Max walking distance to a metro station, in metres. The AI cannot resolve 'near the metro' itself, so use this.",
    )
    zona: str | None = Field(
        None, description="Neighbourhood substring, e.g. 'Drumul Taberei', 'Dristor'"
    )
    oras: str | None = Field(None, description="City or sector substring, e.g. 'Sector 3'")
    doar_locatie_exacta: bool = Field(
        False, description="Only listings with an exact (not approximate) map location"
    )

    # seller and offer
    tip_vanzator: SellerType | None = Field(
        None, description="'individual' = direct from owner, 'agency', 'developer'"
    )
    comision_zero: bool | None = Field(None, description="Only listings with zero buyer commission")
    exclusivitate: bool | None = Field(None, description="Only exclusive listings")
    constructie_noua: bool | None = Field(
        None, description="Only new builds (True) or only established (False)"
    )

    # freshness and media
    zile_pe_piata_max: int | None = Field(
        None, description="Max days the listing has been on the market"
    )
    cu_video: bool | None = Field(None, description="Only listings with video")
    cu_tur_virtual: bool | None = Field(None, description="Only listings with a virtual tour")
    cu_plan: bool | None = Field(None, description="Only listings with a floor plan")
    poze_min: int | None = Field(None, description="Minimum number of photos")

    def as_kwargs(self) -> dict[str, Any]:
        return {
            "max_price": self.pret_max,
            "min_price": self.pret_min,
            "max_price_per_sqm": self.pret_mp_max,
            "price_dropped": self.pret_redus,
            "rooms_exact": self.camere,
            "min_rooms": self.camere_min,
            "max_rooms": self.camere_max,
            "min_sqm": self.suprafata_min,
            "max_sqm": self.suprafata_max,
            "min_floor": self.etaj_min,
            "max_floor": self.etaj_max,
            "exclude_ground_floor": self.fara_parter,
            "exclude_top_floor": self.fara_ultim_etaj,
            "min_year_built": self.an_min,
            "max_year_built": self.an_max,
            "max_metro_m": self.metrou_max_m,
            "area": self.zona,
            "city": self.oras,
            "exact_location_only": self.doar_locatie_exacta,
            "seller_type": self.tip_vanzator,
            "commission_zero": self.comision_zero,
            "exclusive": self.exclusivitate,
            "new_build": self.constructie_noua,
            "max_days_on_market": self.zile_pe_piata_max,
            "has_video": self.cu_video,
            "has_virtual_tour": self.cu_tur_virtual,
            "has_floor_plan": self.cu_plan,
            "min_photos": self.poze_min,
        }


def _client() -> ImobiliareClient:
    """A client carrying whatever session is configured.

    Read through `Settings` so the value is configured the same way as
    everything else in this service (GEMINI_ACT_IMOBILIARE_SESSION_ID), while
    the bare IMOBILIARE_SESSION_ID still works for running this package
    standalone as an MCP server.
    """
    session = os.environ.get("IMOBILIARE_SESSION_ID")
    if not session:
        try:
            from gemini_act.config import get_settings

            session = get_settings().imobiliare_session_id or None
        except Exception:  # noqa: BLE001 - standalone use has no gemini_act settings
            session = None
    return ImobiliareClient(session_id=session)


def _apply(records, filters, sort, limit):
    matches = filter_and_rank(records, sort_by=sort, **filters.as_kwargs())
    return matches, [dict(r) for r in matches[:limit]]


@mcp.tool()
def cauta_obscura(
    query: Annotated[
        str,
        Field(
            description="Natural-language query, Romanian or English, e.g. 'apartament 2 camere Titan sub 90000 euro'. Describe intent here; put numeric limits in `filtre`."
        ),
    ],
    filtre: Filters | None = None,
    sort: Annotated[SortBy, Field(description="Ordering of the results")] = "metro",
    limit: Annotated[int, Field(description="Maximum listings to return", ge=1, le=200)] = 20,
) -> dict[str, Any]:
    """Search imobiliare.ro autonomously using Obscura headless browser and sitemap hydration.

    Does NOT require an expired browser session or session_id token.
    """
    from .obscura import search_imobiliare_obscura

    return search_imobiliare_obscura(query=query, filters=filtre, sort=sort, limit=limit)


@mcp.tool()
def cauta(
    query: Annotated[
        str,
        Field(
            description="Natural-language query, Romanian or English, e.g. 'apartament 3 camere Bucuresti'. Describe intent here; put numeric limits in `filtre`."
        ),
    ],
    filtre: Filters | None = None,
    sort: Annotated[SortBy, Field(description="Ordering of the results")] = "metro",
    limit: Annotated[int, Field(description="Maximum listings to return", ge=1, le=200)] = 20,
    pool: Annotated[
        int,
        Field(
            description="How many AI-ranked results to pull before filtering. Raise it when strict filters leave too few matches.",
            ge=60,
            le=600,
        ),
    ] = 240,
) -> dict[str, Any]:
    """Search imobiliare.ro by description and return matching properties.

    Returns a `resume_token` when AI search succeeds, and falls back to
    autonomous Obscura search if the browser session is expired or missing.
    """
    filters = filtre or Filters()
    with _client() as client:
        try:
            result = client.search(query, max_results=pool)
        except SessionError as e:
            # Fall back to autonomous Obscura search when browser session is expired/missing
            from .obscura import search_imobiliare_obscura

            logger.info("SessionError in cauta (%s). Falling back to Obscura search.", e)
            fallback = search_imobiliare_obscura(
                query=query, filters=filters, sort=sort, limit=limit
            )
            fallback["session_warning"] = (
                f"Sesiunea AI search a expirat ({e}). Rezultatele au fost obținute autonom via Obscura."
            )
            return fallback

    records = [
        normalise(listing, result.explanations.get(str(listing.get("id"))))
        for listing in result.listings
    ]
    matches, page = _apply(records, filters, sort, limit)
    return {
        "title": result.title,
        "assistant_reply": result.reply,
        "total_hits_before_filters": result.total_hits,
        "retrieved": len(records),
        "matched": len(matches),
        "returned": len(page),
        "resume_token": result.token,
        "listings": page,
    }


@mcp.tool()
def reia(
    token: Annotated[str, Field(description="A resume_token from an earlier cauta() call")],
    filtre: Filters | None = None,
    sort: Annotated[SortBy, Field(description="Ordering of the results")] = "metro",
    limit: Annotated[int, Field(description="Maximum listings to return", ge=1, le=200)] = 20,
    pool: Annotated[
        int, Field(description="How many results to pull before filtering", ge=60, le=600)
    ] = 240,
) -> dict[str, Any]:
    """Re-read an earlier search's results and re-filter them.

    Result tokens outlive the session that created them, so this keeps working
    after the session expires. Use it to change filters or page deeper without
    spending a fresh session on a repeat query.
    """
    filters = filtre or Filters()
    with _client() as client:
        result = client.resume(token, max_results=pool)

    records = [normalise(listing) for listing in result.listings]
    matches, page = _apply(records, filters, sort, limit)
    return {
        "total_hits": result.total_hits,
        "retrieved": len(records),
        "matched": len(matches),
        "returned": len(page),
        "listings": page,
    }


@mcp.tool()
def detalii(
    ids: Annotated[
        list[str],
        Field(
            description="Listing ids, e.g. ['275966742']. The trailing number of an imobiliare.ro offer URL is the id."
        ),
    ],
) -> dict[str, Any]:
    """Fetch full details for specific listing ids. Needs no session."""
    with _client() as client:
        listings = client.hydrate(ids)
    return {"count": len(listings), "listings": [normalise(listing) for listing in listings]}


@mcp.tool()
def statistici(
    token: Annotated[str, Field(description="A resume_token from an earlier cauta() call")],
    filtre: Filters | None = None,
    pool: Annotated[int, Field(description="How many results to analyse", ge=60, le=600)] = 240,
) -> dict[str, Any]:
    """Summarise a result set: price distribution, and breakdown by area,
    seller type and building age.

    Use this to understand a market segment before looking at individual
    listings -- what a fair price per sqm is, where the supply actually is.
    """
    import statistics

    filters = filtre or Filters()
    with _client() as client:
        result = client.resume(token, max_results=pool)
    records = filter_and_rank(
        [normalise(listing) for listing in result.listings],
        sort_by="relevance",
        **filters.as_kwargs(),
    )
    if not records:
        return {"matched": 0, "note": "No listings matched; loosen the filters."}

    def spread(field: str) -> dict[str, Any] | None:
        vals = sorted(r[field] for r in records if r[field] is not None)
        if not vals:
            return None
        return {
            "min": vals[0],
            "max": vals[-1],
            "median": statistics.median(vals),
            "mean": round(statistics.fmean(vals), 1),
            "n": len(vals),
        }

    def tally(field: str, top: int = 8) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in records:
            if (v := r[field]) is not None:
                counts[str(v)] = counts.get(str(v), 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1])[:top])

    return {
        "matched": len(records),
        "price_eur": spread("price_eur"),
        "price_per_sqm": spread("price_per_sqm"),
        "surface_sqm": spread("surface_sqm"),
        "year_built": spread("year_built"),
        "metro_distance_m": spread("metro_distance_m"),
        "days_on_market": spread("days_on_market"),
        "by_area": tally("area"),
        "by_city": tally("city"),
        "by_seller_type": tally("seller_type"),
        "with_commission_zero": sum(1 for r in records if r["commission_zero"]),
        "new_builds": sum(1 for r in records if r["is_new_build"]),
    }


@mcp.tool()
def sesiune_noua() -> dict[str, Any]:
    """Mint a fresh session id from the AI host.

    Currently of limited use: /api/search rejects self-minted sessions with
    'Forbidden' and accepts only browser-originated ones. Exposed so you can
    check whether that restriction still holds.
    """
    with _client() as client:
        try:
            return {"session_id": client.new_session(), "usable_for_search": "unverified"}
        except Exception as e:  # noqa: BLE001 - surface transport errors to the caller
            return {"error": f"{type(e).__name__}: {e}"}


# -- imo360: the session-free source --------------------------------------
#
# Everything above this point depends on imobiliare.ro: `cauta` on a browser
# session that expires in minutes, `cauta_obscura` on a headless browser,
# `comps` on a daily sitemap. The tools below answer from imo360's explorer
# API, which needs no credential of any kind -- so they are the ones that
# still work unattended, and they reach data the other source does not
# publish at all: rentals, and therefore yield.


def _imo360_geo(
    zona: str | None, oras: str | None, client: imo360.Imo360Client
) -> tuple[list[int], list[dict[str, Any]]]:
    """Resolve a neighbourhood name to zone ids, plus what was resolved.

    The resolution is returned, not just used: "Militari" is two zones in two
    different sectors, and a caller told only the numbers cannot tell whether
    the answer covers the neighbourhood they meant.
    """
    zones = client.find_zones(zona or "", city=oras)
    return (
        [z.id for z in zones],
        [{"id": z.id, "name": z.name, "city": z.city, "county": z.county} for z in zones],
    )


@mcp.tool()
def cauta_imo360(
    zona: Annotated[
        str,
        Field(
            description="Neighbourhood or zone name, e.g. 'Titan', 'Militari', 'Gheorgheni'. Resolved against imo360's published gazetteer of 1588 Romanian zones."
        ),
    ],
    oras: Annotated[
        str | None,
        Field(
            description="City or county, to disambiguate a name used in several places, e.g. 'bucuresti', 'cluj'."
        ),
    ] = None,
    tranzactie: Annotated[
        Literal["sale", "rent"], Field(description="Sale or rental listings")
    ] = "sale",
    tip: Annotated[
        Literal["apartment", "house", "land", "commercial_space", "office"] | None,
        Field(description="Property type. Leave unset for every type."),
    ] = None,
    filtre: Filters | None = None,
    sort: Annotated[SortBy, Field(description="Ordering of the results")] = "price_per_sqm",
    limit: Annotated[int, Field(description="Maximum listings to return", ge=1, le=100)] = 20,
    include_neconforme: Annotated[
        bool,
        Field(
            description="Include listings filed under `sale` that are not sales of the whole property -- rental ads, undivided shares, swaps. Off by default."
        ),
    ] = False,
    pool: Annotated[
        int,
        Field(description="How many listings to pull before filtering locally", ge=50, le=500),
    ] = 200,
) -> dict[str, Any]:
    """Search Romanian property listings via imo360, without any session.

    Use this rather than `cauta` when there is no browser session to spend, and
    whenever the question is about a *zone* rather than a description -- this
    source selects geographically, so "everything in Titan" is exact rather
    than a slug match.

    Returns the real number of listings on the market in that zone
    (`oferta_totala`) whenever the upstream count is not capped, which is what
    makes it usable as a measure of supply and not just a page of results.
    """
    filters = filtre or Filters()
    with imo360.Imo360Client() as client:
        zone_ids, resolved = _imo360_geo(zona, oras, client)
        if not zone_ids:
            return {
                "status": "error",
                "error_message": (
                    f"Zona '{zona}' nu a fost găsită în nomenclatorul imo360"
                    + (f" pentru '{oras}'" if oras else "")
                    + ". Încearcă un nume de cartier mai exact."
                ),
            }
        # The price bounds are pushed server-side as well as being enforced
        # locally by `filter_and_rank`. Not redundant: the upstream count is
        # capped at 10000, so a filter applied there is also what turns
        # `oferta_totala` back into a real number.
        page = client.collect(
            transaction=tranzactie,
            zone_ids=zone_ids,
            property_type=tip,
            rooms=filters.camere,
            price_min=filters.pret_min,
            price_max=filters.pret_max,
            max_results=pool,
        )

    # Deduplicated before filtering: this source re-advertises heavily (a
    # measured 39% on one zone), and a page of the same flat three times is
    # worse than a shorter honest one.
    records = imo360.dedupe([imo360.normalise(listing) for listing in page.listings])
    # The mis-filed ones are dropped from the *list* as well as from the
    # statistics, and by default. Sorting by price per sqm ascending -- the
    # default, and what anyone hunting a bargain asks for -- otherwise puts an
    # 800 EUR rental ad at the top of a search for flats in Floreasca, which
    # reads as the find of the year. Counted in the answer rather than
    # vanishing, and `include_neconforme` brings them back.
    neconforme = [r for r in records if r.get("suspect")]
    if not include_neconforme:
        records = [r for r in records if not r.get("suspect")]
    matches, listings = _apply(records, filters, sort, limit)
    return {
        "status": "success",
        "sursa": "imo360",
        "zone_rezolvate": resolved,
        "oferta_totala": page.supply,
        "oferta_totala_plafonata": page.total_is_capped,
        "retrieved": len(records),
        "duplicate_removed": len(page.listings)
        - len(records)
        - len(neconforme) * (not include_neconforme),
        "excluse_neconforme": 0 if include_neconforme else len(neconforme),
        "matched": len(matches),
        "returned": len(listings),
        "listings": listings,
    }


@mcp.tool()
def puls_piata(
    zona: Annotated[str, Field(description="Neighbourhood or zone name, e.g. 'Titan'")],
    oras: Annotated[
        str | None, Field(description="City or county, to disambiguate the name")
    ] = None,
    tip: Annotated[
        Literal["apartment", "house", "land", "commercial_space", "office"],
        Field(description="Property type the snapshot is about"),
    ] = "apartment",
    camere: Annotated[
        int | None, Field(description="Restrict to a room count, e.g. 2", ge=0, le=20)
    ] = None,
    toate_zonele: Annotated[
        bool,
        Field(
            description="Include every zone matching the name (e.g. Militari in both Sector 5 and 6) rather than only the best match."
        ),
    ] = True,
) -> dict[str, Any]:
    """Sale and rental sides of one zone, and the gross yield between them.

    The only tool here that can answer "what does this zone earn": rentals are
    in imo360's index, so asking price per sqm and rent per sqm come from the
    same geography on the same day. Reports how many properties are actually
    on the market for sale and for rent.

    The yield is **gross** -- before vacancy, management, tax and maintenance.
    """
    with imo360.Imo360Client() as client:
        zone_ids, resolved = _imo360_geo(zona, oras, client)
        if not zone_ids:
            return {
                "status": "error",
                "error_message": f"Zona '{zona}' nu a fost găsită în nomenclatorul imo360.",
            }
        if not toate_zonele:
            zone_ids, resolved = zone_ids[:1], resolved[:1]
        snapshot = imo360.market_snapshot(
            client, zone_ids=zone_ids, property_type=tip, rooms=camere
        )

    return {
        "status": "success",
        "sursa": "imo360",
        "zone_rezolvate": resolved,
        **snapshot,
        "nota": (
            "Randamentul este brut: înainte de neocupare, administrare, impozit și "
            "întreținere. Prețurile pe mp sunt calculate pe baza suprafeței "
            f"'{snapshot['basis']['surface']}'."
        ),
    }


@mcp.tool()
def detalii_imo360(
    id_anunt: Annotated[str, Field(description="An imo360 listing id, from a cauta_imo360 result")],
) -> dict[str, Any]:
    """Full record for one imo360 listing, including the whole photo gallery.

    The search results carry a single thumbnail; this is what returns the rest,
    which is what the visual inspection tools need to look at a property.
    """
    with imo360.Imo360Client() as client:
        try:
            raw = client.listing(id_anunt)
        except imo360.Imo360Error as e:
            return {"status": "error", "error_message": str(e)}
    record = imo360.normalise(raw)
    # The source ad's own attributes -- heating, building material, windows,
    # lift, advertiser type, primary vs secondary market. Not normalised into
    # the record because the vocabulary is the upstream portal's and varies by
    # provider; passed through so the model can read what is there.
    if caracteristici := _imo360_attributes(raw):
        record["caracteristici_sursa"] = caracteristici
    return {"status": "success", "sursa": "imo360", "listing": record}


def _imo360_attributes(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten the source portal's attribute block, when there is one."""
    features = raw.get("features")
    if not isinstance(features, dict):
        return {}
    out: dict[str, Any] = {}
    storia = features.get("storia")
    if isinstance(storia, dict):
        for item in storia.get("characteristics") or []:
            if isinstance(item, dict) and item.get("key"):
                out[str(item["key"])] = item.get("localizedValue") or item.get("value")
        for item in storia.get("additional_information") or []:
            if not isinstance(item, dict) or not item.get("label"):
                continue
            # Values arrive namespaced -- "heating::gas", "::n" -- and the
            # namespace is noise once the label is already the key.
            values = [str(v).split("::")[-1] for v in item.get("values") or []]
            if values:
                out[str(item["label"])] = values if len(values) > 1 else values[0]
    return out


@mcp.tool()
def cauta_imoradar(
    zona: Annotated[
        str | None,
        Field(
            description="Neighbourhood, town or county, e.g. 'Titan', 'Cluj-Napoca', 'Brasov'. Resolved against the 2367 locations imoradar24 publishes. Leave unset to search the whole country."
        ),
    ] = None,
    oras: Annotated[
        str | None,
        Field(
            description="City or county, to disambiguate a name used in several places, e.g. 'bucuresti', 'cluj'."
        ),
    ] = None,
    doar_proprietar: Annotated[
        bool,
        Field(
            description="Only listings advertised directly by owners, no agencies. This source is the one that actually reaches that segment (OLX, Publi24)."
        ),
    ] = False,
    filtre: Filters | None = None,
    sort: Annotated[SortBy, Field(description="Ordering of the results")] = "price_per_sqm",
    limit: Annotated[int, Field(description="Maximum listings to return", ge=1, le=100)] = 20,
    include_neconforme: Annotated[
        bool,
        Field(
            description="Include listings whose price is below any plausible sale price -- rents filed as sales, typos. Off by default."
        ),
    ] = False,
    pool: Annotated[
        int,
        Field(description="How many listings to pull before filtering locally", ge=30, le=300),
    ] = 120,
) -> dict[str, Any]:
    """Search apartments for sale across every major Romanian portal at once.

    imoradar24 aggregates imobiliare.ro, storia.ro, olx.ro, publi24.ro,
    homezz.ro and others into one de-duplicated index, so this is the tool for
    two questions the other two sources cannot answer:

    * **"what is for sale from owners directly"** -- that segment lives on OLX
      and Publi24, which nothing else here indexes (`doar_proprietar`);
    * **"is this flat advertised at more than one price"** -- where a property
      is on several portals or with several agencies, every ad is returned in
      `sources`, with `price_spread_pct` between them.

    Needs no session, unlike `cauta`. `oferta_totala` is a de-duplicated count
    of properties, not of ads, so it can be quoted as supply directly --
    unlike `portaluri`, which breaks down only the pool that was read and is
    not the market's split across portals. `zona_rezolvata` says which
    published location the name resolved to, and lists the alternatives when
    it was ambiguous.
    """
    filters = filtre or Filters()
    with imoradar.ImoradarClient() as client:
        resolved = None
        place = None
        if zona:
            hits = client.find_places(zona, city=oras)
            if not hits:
                return {
                    "status": "error",
                    "error_message": (
                        f"Zona '{zona}' nu are o pagină publicată pe imoradar24"
                        + (f" pentru '{oras}'" if oras else "")
                        + ". Încearcă un nume de cartier, oraș sau județ mai exact."
                    ),
                }
            place = hits[0].path
            resolved = {
                "path": hits[0].path,
                "name": hits[0].name,
                "city": hits[0].city,
                "county": hits[0].county,
                "url": hits[0].url,
                # Kept so a caller can tell "Central" resolved to the wrong
                # town before reading 20 listings from it.
                "alternative": [p.path for p in hits[1:4]],
            }
        page = client.collect(
            place=place,
            # The portal publishes an exact-room-count URL but no range, so
            # only an exact `camere` narrows server-side; everything else is
            # enforced locally by `filter_and_rank` like on every other source.
            rooms=filters.camere,
            owner_only=doar_proprietar,
            max_results=pool,
        )

    # `imoradar.dedupe`, deliberately not `imo360.dedupe`: this portal already
    # merges an ad's copies upstream, and its listings mostly publish no street
    # address, so imo360's key degenerates to price + surface + rooms and
    # merges different flats. See the note above `imoradar.dedupe`.
    records = imoradar.dedupe([imoradar.normalise(listing) for listing in page.listings])
    # Dropped by default and counted, exactly as `cauta_imo360` does it: the
    # default sort is price per sqm ascending, so a 476 EUR rent filed as a
    # sale would otherwise lead every search of the owner segment.
    neconforme = [r for r in records if r.get("suspect")]
    if not include_neconforme:
        records = [r for r in records if not r.get("suspect")]
    matches, listings = _apply(records, filters, sort, limit)
    portals: dict[str, int] = {}
    for record in records:
        portals[record["source_portal"] or "necunoscut"] = (
            portals.get(record["source_portal"] or "necunoscut", 0) + 1
        )
    return {
        "status": "success",
        "sursa": "imoradar24",
        "zona_rezolvata": resolved,
        "oferta_totala": page.total,
        "oferta_proprietari": page.owner_total,
        "portaluri": dict(sorted(portals.items(), key=lambda kv: -kv[1])),
        "retrieved": len(records),
        "duplicate_removed": len(page.listings)
        - len(records)
        - len(neconforme) * (not include_neconforme),
        "excluse_neconforme": 0 if include_neconforme else len(neconforme),
        "matched": len(matches),
        "returned": len(listings),
        "pagini_ramase": page.truncated,
        "listings": listings,
    }


@mcp.tool()
def istoric_pret_imoradar(
    id_anunt: Annotated[
        str, Field(description="An imoradar24 listing id, from a cauta_imoradar result")
    ],
) -> dict[str, Any]:
    """How one listing's asking price has moved since the portal first saw it.

    The single strongest input to a negotiation available here: what the
    seller has already conceded, how long they have been trying, and how many
    times they have cut. `zile_de_la_prima_aparitie` reaches back a year on
    old listings -- past both the ad's own posting date and this portal's
    indexing date -- so it is the firmest lower bound on time on the market.

    Two things must be carried into whatever is said about the result:

    * **An empty history is not a stable price.** The endpoint answers the
      same way for a listing it has never tracked and for one that does not
      exist, so `observat: false` means "nothing to read", never "unchanged".
    * **`schimbare_pct` is only computed between unambiguous observations.**
      Where a property is advertised by several agencies at once, a day's
      entry is a price *range*; the range closing as the dearest ad ends is
      not the seller dropping their price. Those days are counted in
      `puncte_ambigue` and excluded from the change.
    """
    listing_id = _resolve_id(id_anunt)
    try:
        with imoradar.ImoradarClient() as client:
            raw = client.price_history(listing_id)
    except imoradar.ImoradarError as exc:
        return {"status": "error", "error_message": str(exc)}

    history = imoradar.summarise_history(raw)
    if not history["observed"]:
        return {
            "status": "success",
            "sursa": "imoradar24",
            "id": listing_id,
            "observat": False,
            "nota": (
                "imoradar24 nu are istoric de preț pentru acest anunț. Endpointul "
                "răspunde identic pentru un anunț netrackat și pentru unul inexistent, "
                "deci asta NU înseamnă că prețul a rămas neschimbat."
            ),
        }
    return {
        "status": "success",
        "sursa": "imoradar24",
        "id": listing_id,
        "observat": True,
        "prima_aparitie": history["first_seen"],
        "ultima_aparitie": history["last_seen"],
        "zile_de_la_prima_aparitie": history["days_since_first_seen"],
        "pret_initial": history["price_first_eur"],
        "pret_curent": history["price_last_eur"],
        "pret_minim": history["price_min_eur"],
        "pret_maxim": history["price_max_eur"],
        "schimbare_pct": history["change_pct"],
        "reduceri": history["drops"],
        "puncte_ambigue": history["ambiguous_points"],
        "observatii": history["points"],
        "serie": history["series"],
    }


class ParametriEvaluare(BaseModel):
    """Valuation inputs. Every one is argued in the report (GEV 630 §71), and
    every one can be overridden -- these are market conventions, not laws."""

    marja_negociere_baza: float = Field(
        3.0, description="Base discount from asking to transaction price, %", ge=0, le=25
    )
    marja_negociere_per_30_zile: float = Field(
        0.5, description="Extra negotiation margin per 30 days of exposure, %", ge=0, le=5
    )
    marja_negociere_plafon: float = Field(
        12.0, description="Cap on the negotiation margin, %", ge=0, le=30
    )
    valoare_parcare: float = Field(
        12000.0, description="Market value of a parking space, EUR", ge=0
    )
    valoare_mobilier: float = Field(8000.0, description="Market value of furnishing, EUR", ge=0)
    grad_neocupare: float = Field(
        8.0,
        description="Vacancy and collection loss, % of potential gross income (GEV 630 §69)",
        ge=0,
        le=50,
    )
    cheltuieli_operare: float = Field(
        18.0,
        description="Owner's non-recoverable expenses, % of effective gross income (GEV 630 §70)",
        ge=0,
        le=60,
    )
    rata_capitalizare: float = Field(6.0, description="Capitalisation rate, %", gt=0, le=20)
    spor_an_pe_an: float = Field(
        0.45, description="Value premium per year of newness, %", ge=0, le=3
    )
    plafon_spor_an: float = Field(20.0, description="Cap on the age adjustment, %", ge=0, le=60)
    discount_metrou_max: float = Field(
        8.0, description="Discount at 1500 m from a metro station, %", ge=0, le=30
    )
    spor_bloc_nou: float = Field(4.0, description="New-build premium, %", ge=0, le=30)
    prag_descalificare: float = Field(
        35.0,
        description="Gross adjustment above which a comparable is disqualified, % (GEV 630 §57)",
        ge=10,
        le=100,
    )
    pondere_piata: float = Field(
        80.0, description="Weight of the sales-comparison approach, %", ge=0, le=100
    )
    pondere_venit: float = Field(20.0, description="Weight of the income approach, %", ge=0, le=100)

    def to_params(self) -> Params:
        return Params(
            negotiation_base_pct=self.marja_negociere_baza,
            negotiation_per_30_days_pct=self.marja_negociere_per_30_zile,
            negotiation_cap_pct=self.marja_negociere_plafon,
            parking_value_eur=self.valoare_parcare,
            furniture_value_eur=self.valoare_mobilier,
            vacancy_rate_pct=self.grad_neocupare,
            operating_expense_pct=self.cheltuieli_operare,
            capitalisation_rate_pct=self.rata_capitalizare,
            age_premium_per_year_pct=self.spor_an_pe_an,
            age_premium_cap_pct=self.plafon_spor_an,
            metro_discount_max_pct=self.discount_metrou_max,
            new_build_premium_pct=self.spor_bloc_nou,
            disqualify_gross_pct=self.prag_descalificare,
            market_weight_pct=self.pondere_piata,
            income_weight_pct=self.pondere_venit,
        )


_ID_IN_URL = re.compile(r"(\d{6,})\s*/?$")


def _resolve_id(identificator: str) -> str:
    """Accept a bare id or any imobiliare.ro offer URL."""
    text = (identificator or "").strip()
    if text.isdigit():
        return text
    if m := _ID_IN_URL.search(text.split("?")[0]):
        return m.group(1)
    raise ValueError(
        f"Nu pot extrage un id din {identificator!r}. Dă-mi fie id-ul (275807510), "
        "fie linkul complet al anunțului."
    )


def _verdict_piata(dif_pct: float | None) -> str:
    """How the asking price sits against the estimate.

    `dif_pct` is (asking - estimate) / estimate: positive means the listing is
    asking *above* what the comparables support.
    """
    if dif_pct is None:
        return "Evaluare efectuată pe baza eșantionului de comparabile"
    if dif_pct <= -5:
        return f"Preț sub valoarea estimată ({dif_pct:+.1f}%) — oportunitate"
    if dif_pct < 3:
        return f"Preț aliniat cu valoarea estimată ({dif_pct:+.1f}%)"
    if dif_pct < 10:
        return f"Preț peste valoarea estimată ({dif_pct:+.1f}%) — există marjă de negociere"
    return f"Preț semnificativ peste valoarea estimată ({dif_pct:+.1f}%) — supraevaluat"


def _scor_general(date: dict[str, Any]) -> tuple[float | None, str, list[str]]:
    """The dossier's headline verdict, derived from the sections that produced one.

    Returns (score out of 10, label, which sections it was built from). When
    nothing measurable came back the score is None and the label says so --
    the previous constant 8.7 / "FOARTE BUN - INVESTIȚIE SIGURĂ" was emitted
    for every property regardless of any finding, including ones where every
    section was unavailable.
    """
    componente: list[tuple[float, float]] = []  # (score, weight)
    baza: list[str] = []

    def disponibil(sectiune: Any) -> dict[str, Any] | None:
        if not isinstance(sectiune, dict):
            return None
        if sectiune.get("disponibil") is False or sectiune.get("status") in {
            "indisponibil",
            "error",
        }:
            return None
        return sectiune

    if ev := disponibil(date.get("evaluare_anevar")):
        # Asking price under the estimate is the good direction.
        ajustare = ev.get("ajustare_recomandata_procent")
        if ajustare is not None:
            componente.append((max(1.0, min(10.0, 7.0 - float(ajustare) / 3.0)), 3.0))
            baza.append("evaluare ANEVAR")

    if fin := disponibil(date.get("audit_electrocasnice_finisaje")):
        calitate = fin.get("calitate_generala_finisaje") or {}
        if (scor := calitate.get("scor_global")) is not None:
            componente.append((float(scor), 2.0))
            baza.append("audit finisaje")

    if tgt := disponibil(date.get("audit_targetare")):
        analiza = (
            tgt.get("analiza_financiara")
            or tgt.get("date_firma", {}).get("analiza_financiara")
            or {}
        )
        if (scor := analiza.get("scor_sanatate_financiara")) is not None:
            componente.append((float(scor), 1.5))
            baza.append("bonitate dezvoltator")

    if rec := disponibil(date.get("recenzii_google")):
        analiza = rec.get("analiza_sentiment") or {}
        if (scor := analiza.get("scor_reputatie")) is not None:
            componente.append((float(scor), 1.0))
            baza.append("recenzii Google")

    if not componente:
        return None, "INDISPONIBIL - date insuficiente pentru un scor global", []

    total_w = sum(w for _, w in componente)
    scor = round(sum(s * w for s, w in componente) / total_w, 1)

    if scor >= 8.5:
        calificativ = "FOARTE BUN"
    elif scor >= 7.0:
        calificativ = "BUN"
    elif scor >= 5.5:
        calificativ = "ACCEPTABIL - verificări suplimentare recomandate"
    else:
        calificativ = "SLAB - risc ridicat"
    return scor, calificativ, baza


def _evaluare_indisponibila(
    motiv: str,
    subject: dict[str, Any] | None = None,
    comparabile: list[Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A valuation that could not be produced, and why.

    Each caller passes its own `motiv`: "listing not found", "zone not
    derivable" and "too few comparables" need three different fixes, and a
    single canned reason for all of them sends the user after the wrong one.
    """
    out: dict[str, Any] = {
        "status": "indisponibil",
        "disponibil": False,
        "provenienta": "indisponibil",
        "motiv": motiv,
        "error": motiv,
        # Same shape as the success path, so a UI that renders one renders both.
        "comparabile": [_comparabila_dict(c) for c in (comparabile or [])],
    }
    if subject is not None:
        out["subject"] = subject
    out.update(extra)
    return out


def _comparabila_dict(c: Any) -> dict[str, Any]:
    """One comparable in the shape the report and the web UI both read.

    `c` is an `AdjustedComp` when it comes from the grid, and a bare normalised
    record on the paths that never got that far -- both must produce the same
    keys, or a table that renders one silently comes out blank for the other.
    """
    rec = getattr(c, "record", None)
    if rec is None:
        rec = c if isinstance(c, dict) else {}

    metro_m = rec.get("metro_distance_m")
    price, surface = rec.get("price_eur"), rec.get("surface_sqm")
    net_pct = getattr(c, "net_pct", None)
    gross_pct = getattr(c, "gross_pct", None)

    return {
        "id": str(rec.get("id")) if rec.get("id") is not None else None,
        "adresa": rec.get("location") or rec.get("address_text") or rec.get("title"),
        "url": rec.get("url"),
        "pret_total": price,
        "pret": price,
        "suprafata_utila": surface,
        "suprafata": surface,
        "pret_mp": rec.get("price_per_sqm"),
        "pret_mp_eur": rec.get("price_per_sqm"),
        "an_constructie": rec.get("year_built"),
        "etaj": rec.get("floor"),
        # None, not a stand-in distance: an unpublished metro distance is not
        # evidence that the flat is 500 m from a station.
        "distanta_km": round(metro_m / 1000, 2) if metro_m is not None else None,
        "ponderi_ajustare": (
            f"{round(net_pct, 1):+}% ajustare netă"
            if net_pct is not None
            else "fără ajustări aplicate"
        ),
        "ajustare_neta_procent": round(net_pct, 1) if net_pct is not None else None,
        # Gross, not net: §57's "total" is the sum of absolute adjustments, and
        # the two differ whenever corrections have opposite signs.
        "ajustare_totala_procent": round(gross_pct, 1) if gross_pct is not None else None,
    }


def _analiza_piata(area: str, pool: list[dict[str, Any]]) -> dict[str, Any]:
    """The micro-market, measured from the active offers actually pulled.

    Only what the pool can prove. A yearly price trend and a direction of
    travel need a time series this pipeline does not keep, so they come back
    `None` with the reason -- the dossier used to print an invented +6,2%/an
    next to figures that were real.
    """
    unitare = [r["price_per_sqm"] for r in pool if r.get("price_per_sqm")]
    zile = [r["days_on_market"] for r in pool if r.get("days_on_market") is not None]
    if not unitare:
        return {
            "status": "indisponibil",
            "disponibil": False,
            "zona": area,
            "motiv": "Nicio ofertă activă cu preț unitar publicat în această arie.",
            "provenienta": "indisponibil",
        }
    return {
        "status": "disponibil",
        "disponibil": True,
        "provenienta": "masurat",
        "zona": area,
        "pret_mediu_zona_eur_mp": round(statistics.median(unitare)),
        "pret_minim_zona_eur_mp": round(min(unitare)),
        "pret_maxim_zona_eur_mp": round(max(unitare)),
        "oferta_activa_similara": len(pool),
        "timp_mediu_expunere_luni": (round(statistics.median(zile) / 30, 1) if zile else None),
        "timp_mediu_expunere_zile": round(statistics.median(zile)) if zile else None,
        # Not derivable from a single snapshot of active offers.
        "variatie_anuala_procent": None,
        "tendinta": None,
        "motiv_tendinta": (
            "Evoluția anuală și tendința cer o serie de timp; raportul se construiește "
            "dintr-un singur instantaneu al ofertei active."
        ),
        "comentariu": (
            f"{len(pool)} oferte active comparabile în aria '{area}', cu un preț unitar "
            f"median de {round(statistics.median(unitare)):,} EUR/mp.".replace(",", ".")
        ),
    }


def _constatari_vizuale(findings: Any) -> list[str]:
    """Flatten what the vision pass saw into the phrases the levers match on."""
    if findings is None:
        return []
    bucati: list[str] = []
    for atribut in ("stare_generala", "finisaje", "observatii", "fatada_bloc"):
        if valoare := getattr(findings, atribut, None):
            bucati.append(str(valoare))
    semne = getattr(findings, "semne_ingrijorare", None) or []
    bucati.extend(str(x) for x in semne)
    return bucati


def _risc_seismic(subject: dict[str, Any]) -> dict[str, Any] | None:
    """The AMCCRS finding for a listing, or None when it cannot be established.

    Only for Bucharest: the register is the capital's, and running a Cluj
    address against it would answer "not in the register" about a list that was
    never going to contain it -- a reassuring sentence with nothing behind it.

    Never raises. A register that is unreachable has to leave a valuation
    slightly less informed, not fail it.
    """
    oras = f"{subject.get('city') or ''} {subject.get('area') or ''}".lower()
    adresa = subject.get("address_text") or ""
    if "bucure" not in oras and "bucure" not in adresa.lower() and "sector" not in oras:
        return None
    try:
        from . import risc_seismic

        return risc_seismic.constatare(adresa)
    except Exception as exc:  # noqa: BLE001 - an informative extra, never a blocker
        logger.debug("Verificarea AMCCRS nu a reușit: %s", exc)
        return None


def _reports_dir() -> Path:
    """Where reports are staged. See `paths` for the Cloud Run constraints."""
    return paths.reports_dir()


@mcp.tool()
def evaluare(
    identificator: Annotated[
        str, Field(description="Listing id or full imobiliare.ro offer URL, e.g. '275807510'")
    ],
    comparabile: Annotated[
        int, Field(description="How many comparables to carry into the grid", ge=3, le=30)
    ] = 12,
    parametri: ParametriEvaluare | None = None,
    fisier: Annotated[
        str | None,
        Field(
            description="Where to write the markdown report. Defaults to $IMOBILIARE_REPORTS_DIR/evaluare-<id>.md"
        ),
    ] = None,
    cu_localizare: Annotated[
        bool,
        Field(
            description="Geocode the address and list nearby schools, shops, parks and transport"
        ),
    ] = True,
    raza_facilitati: Annotated[
        int, Field(description="Radius for the amenity search, metres", ge=300, le=3000)
    ] = 1200,
    cu_galerie: Annotated[
        bool,
        Field(description="Download the listing photos into one contact sheet next to the report"),
    ] = True,
    observatii_vizuale: Annotated[
        str | None,
        Field(
            description="Your own findings from looking at the photos, in markdown, filed alongside the automated analysis rather than replacing it. Usually unnecessary — leave it empty and let `cu_viziune` do the looking."
        ),
    ] = None,
    cu_viziune: Annotated[
        bool,
        Field(
            description="Have a vision model look at the listing photos, the Street View image of the block and the area map, and file what it sees in the report. This is what makes the report's visual section real rather than empty."
        ),
    ] = True,
) -> dict[str, Any]:
    """Value one apartment under the Romanian valuation standards (SEV 2025).

    Give it a listing id or URL. It pulls the subject and a comparable set from
    the published sitemaps -- no session needed, so this does not depend on
    `cauta` -- then runs the sales-comparison grid of GEV 630 §54-58 with the
    size and floor adjustments regressed out of the comparable set itself, a
    direct-capitalisation cross-check per §59-71, and writes a markdown report
    structured on the minimum content of SEV 106 §30.6.

    It never claims SEV conformity: with no inspection, no title check and no
    ANEVAR-authorised evaluator, SEV 106 §30.8 forbids that claim. Use it to
    decide what to offer, not as a valuation report.
    """
    p = (parametri or ParametriEvaluare()).to_params()
    listing_id = _resolve_id(identificator)

    with _client() as client:
        raw = client.hydrate([listing_id])
        if not raw:
            motiv = f"Anunțul {listing_id} nu a putut fi găsit sau nu mai este activ."
            return _evaluare_indisponibila(motiv)
        subject = normalise(raw[0])

        area = comps.area_slug_of(subject.get("url") or "")
        if not area:
            return _evaluare_indisponibila(
                "Nu pot deduce zona din URL-ul anunțului, deci nu pot selecta comparabile.",
                subject=subject,
            )
        scope = comps.scope_for(subject.get("county"), subject.get("city"))
        rooms = subject.get("rooms")

        sale_pool = comps.candidates(area, rooms, scope, "sale", exclude=listing_id)
        rent_pool = comps.candidates(area, rooms, scope, "rent")
        if not sale_pool:
            return _evaluare_indisponibila(
                f"Nicio ofertă activă în zona '{area}' cu {rooms} camere din care să "
                "se construiască un set de comparabile.",
                subject=subject,
            )

        sale_records = [
            normalise(listing) for listing in client.hydrate([o.id for o in sale_pool[:120]])
        ]
        rent_records = (
            [normalise(listing) for listing in client.hydrate([o.id for o in rent_pool[:60]])]
            if rent_pool
            else []
        )

    usable = [r for r in sale_records if r.get("price_eur") and r.get("surface_sqm")]
    # Deduplicate before ranking, not after. `evaluate` dedupes too, but by then
    # the top-N slice has already been taken -- so a flat listed twice used to
    # consume two of the twelve places and the grid came back one comparable
    # short, without saying why.
    usable = dedupe(usable)
    chosen = comps.rank_by_similarity(subject, usable)[:comparabile]
    piata = _analiza_piata(area, usable)
    if len(chosen) < 3:
        return _evaluare_indisponibila(
            f"Eșantion insuficient: doar {len(chosen)} comparabile reale cu preț și "
            "suprafață publicate, sub minimul de 3 (GEV 630).",
            subject=subject,
            comparabile=chosen,
        )

    subject_furnished = is_furnished(subject, slug_hint="-mobilat-" in (subject.get("url") or ""))
    valuation = evaluate(
        subject, chosen, rent_records, p, subject_furnished=subject_furnished, rate_pool=usable
    )
    if not valuation.sufficient_comps or not valuation.comps or len(valuation.comps) < 3:
        return _evaluare_indisponibila(
            f"Sub 3 comparabile calificate după ajustări: {len(valuation.comps)} reținute, "
            f"{len(valuation.excluded)} descalificate prin ajustări brute peste "
            f"{p.disqualify_gross_pct:.0f}% (GEV 630 §57).",
            subject=subject,
            comparabile=valuation.comps,
            fiabilitate=valuation.reliability,
            comparabile_retinute=len(valuation.comps),
            comparabile_excluse=len(valuation.excluded),
        )

    place = vecinatati = None
    if cu_localizare:
        place = locatie.geocode(
            subject.get("address_text") or subject.get("location"), subject.get("location")
        )
        if place:
            vecinatati = locatie.nearby(place, raza_facilitati)

    path = Path(fisier) if fisier else _reports_dir() / f"evaluare-{listing_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    sheet = None
    if cu_galerie and subject.get("image_urls"):
        sheet = contact_sheet(subject["image_urls"], path.with_name(f"galerie-{listing_id}.jpg"))

    # The two views the seller did not choose. Both are best-effort: no Maps key,
    # no coordinates, or no coverage at this point all mean None, and the vision
    # pass then runs on the gallery alone.
    street_view = static_map = None
    if place is not None and maps.available():
        street_view = maps.street_view(place.lat, place.lon)
        static_map = maps.static_map(place.lat, place.lon)
        if street_view:
            path.with_name(f"streetview-{listing_id}.jpg").write_bytes(street_view)
        if static_map:
            path.with_name(f"harta-{listing_id}.png").write_bytes(static_map)

    scor_acces = None
    if place is not None and maps.available():
        try:
            from gemini_act.agent.tools.maps import calculeaza_scor_accesibilitate

            res = calculeaza_scor_accesibilitate(f"{place.lat},{place.lon}")
            if res.get("status") == "success":
                scor_acces = res.get("scor_accesibilitate")
        except Exception:
            pass

    findings = None
    if cu_viziune:
        findings = viziune.analyse(
            subject,
            subject.get("image_urls") or [],
            street_view=street_view,
            static_map=static_map,
        )

    sheet_file = f"galerie-{listing_id}.jpg" if sheet else None
    sv_file = f"streetview-{listing_id}.jpg" if street_view else None
    map_file = f"harta-{listing_id}.png" if static_map else None

    risc_seismic_constatare = _risc_seismic(subject)
    strategie = negociere.plan(
        subject,
        valuation.final_value,
        constatari=_constatari_vizuale(findings),
        deviz_renovare=(findings.cost_renovare_estimat_eur if findings else None),
        risc_seismic=risc_seismic_constatare,
    )
    buget = costuri.buget_consolidat(
        subject.get("price_eur"),
        subject.get("surface_sqm"),
        subject.get("rooms"),
        deviz_renovare_eur=(findings.cost_renovare_estimat_eur if findings else None),
        # Already established above for the valuation grid; the budget needs it
        # for the opposite reason. A flat advertised furnished carries its
        # furniture in the asking price, so budgeting to furnish it again
        # inflates the total by 5-7k per room.
        include_mobilare=not subject_furnished,
        prin_agentie=(subject.get("seller_type") == "agency"),
    )

    markdown = render(
        valuation,
        comps_source=f"sitemap imobiliare.ro, aria '{area}', {len(usable)} oferte active cu preț și suprafață",
        rents_source=(
            f"sitemap închirieri, aria '{area}', {valuation.income.sample} oferte"
            if valuation.income.sample
            else "insuficiente oferte de închiriere"
        ),
        place=place,
        vecinatati=vecinatati,
        sheet=sheet_file,
        observatii_vizuale=observatii_vizuale,
        viziune=findings,
        street_view_file=sv_file,
        static_map_file=map_file,
        scor_accesibilitate=scor_acces,
        strategie=strategie,
        buget=buget,
        risc_seismic=risc_seismic_constatare,
    )
    path.write_text(markdown, encoding="utf-8")

    ask, final = subject.get("price_eur"), valuation.final_value
    return {
        "raport": str(path),
        "id": listing_id,
        "titlu": subject.get("title"),
        "url": subject.get("url"),
        "pret_cerut_eur": ask,
        "valoare_estimata_eur": round(final) if final else None,
        "diferenta_pct": round((ask - final) / final * 100, 1) if (ask and final) else None,
        "valoare_unitara_estimata_eur_mp": round(valuation.market_per_sqm)
        if valuation.market_per_sqm
        else None,
        "pret_unitar_cerut_eur_mp": subject.get("price_per_sqm"),
        "interval_valori_eur_mp": (
            [round(valuation.value_range[0]), round(valuation.value_range[1])]
            if valuation.value_range
            else None
        ),
        "abordare_piata_eur": round(valuation.market_value) if valuation.market_value else None,
        "abordare_venit_eur": round(valuation.income.value) if valuation.income.value else None,
        "randament_net_implicit_pct": round(valuation.implied_yield, 2)
        if valuation.implied_yield
        else None,
        "elasticitate_suprafata": round(valuation.rates.size_elasticity.value, 3),
        "elasticitate_derivata_din_date": valuation.rates.size_elasticity.derived,
        "galerie": str(sheet) if sheet else None,
        "imagini": len(subject.get("image_urls") or []),
        "fotografii_urls": (subject.get("image_urls") or [])[:10],
        "stare_vizuala": findings.stare_generala if findings else None,
        "scor_stare_vizuala": findings.scor_stare if findings else None,
        "finisaje": findings.finisaje if findings else None,
        "lumina": findings.lumina if findings else None,
        "compartimentare": findings.compartimentare if findings else None,
        "fatada_bloc": findings.fatada_bloc if findings else None,
        "semne_ingrijorare": findings.semne_ingrijorare if findings else None,
        "cost_renovare_estimat_eur": findings.cost_renovare_estimat_eur if findings else None,
        "incredere_analiza_vizuala": findings.incredere if findings else None,
        "observatii_vizuale": findings.observatii if findings else None,
        "fotografii_analizate": findings.photos_seen if findings else 0,
        "street_view": bool(street_view),
        "scor_accesibilitate": scor_acces,
        "coordonate": [place.lat, place.lon] if place else None,
        "precizie_locatie": place.precision if place else None,
        "harta": place.map_url if place else None,
        "facilitati": (
            {
                k: [{"nume": i.name, "m": i.distance_m} for i in v[:5]]
                for k, v in vecinatati.pois.items()
                if v
            }
            if vecinatati
            else None
        ),
        "piata": piata,
        "strategie_negociere": _strategie_pe_scurt(strategie),
        "buget_consolidat": {
            k: buget.get(k)
            for k in (
                "status",
                "disponibil",
                "total_minim_eur",
                "total_maxim_eur",
                "total_estimat_eur",
                "costuri_conexe_eur",
            )
        },
        "fiabilitate": valuation.reliability,
        "extrapolare_suprafata": valuation.extrapolated,
        "comparabile_retinute": len(valuation.comps),
        "comparabile_excluse": len(valuation.excluded),
        "comparabile": [_comparabila_dict(c) for c in valuation.comps],
        "conformitate_sev": "nu se afirmă (SEV 106 §30.8)",
    }


@mcp.tool()
def strategie_negociere(
    identificator: Annotated[str, Field(description="Listing id or full imobiliare.ro offer URL")],
    buget_total_max: Annotated[
        float | None,
        Field(
            description=(
                "Total consolidated budget in EUR -- price, fees, renovation and furnishing "
                "together. When given, it caps the walk-away threshold independently of what "
                "the flat is worth."
            )
        ),
    ] = None,
    deviz_renovare: Annotated[
        float | None,
        Field(description="Known repair estimate in EUR; otherwise derived from the defects seen"),
    ] = None,
    prin_agentie: Annotated[
        bool, Field(description="Whether an agency commission is payable by the buyer")
    ] = False,
    cu_viziune: Annotated[
        bool,
        Field(description="Look at the photos first, so the levers rest on observed defects"),
    ] = True,
) -> dict[str, Any]:
    """Turn a valuation into an offer: the ladder, the counterparty and the walk-away.

    Produces the five numbers a buyer needs before speaking to a seller --
    opening offer, probable counter, target, ceiling and the price above which
    the purchase is abandoned -- plus the seller archetype read from the
    listing's own signals, the defects that justify a reduction in euros, the
    checks that are due, and three paste-ready written offers.

    The ranges are market practice for the Bucharest residential segment, not
    measurements of this property, and each one says so. Nothing here changes
    the estimated value: the valuation stays what `evaluare` computed.
    """
    ev = evaluare(identificator, cu_viziune=cu_viziune, cu_galerie=False, cu_localizare=False)
    if ev.get("disponibil") is False or not ev.get("valoare_estimata_eur"):
        return {
            "status": "indisponibil",
            "disponibil": False,
            "motiv": ev.get("motiv")
            or "Evaluarea nu a produs o valoare pe care să se calibreze o ofertă.",
        }

    listing_id = _resolve_id(identificator)
    with _client() as client:
        raw = client.hydrate([listing_id])
    subject = normalise(raw[0]) if raw else {}

    # `if ... is not None` rather than `or`, for the same reason as in
    # `costuri.buget_consolidat`: a caller passing a deviz of 0 is stating the
    # property needs no work, and `or` would discard that and fall through.
    deviz = deviz_renovare if deviz_renovare is not None else ev.get("cost_renovare_estimat_eur")
    buget = costuri.buget_consolidat(
        subject.get("price_eur"),
        subject.get("surface_sqm"),
        subject.get("rooms"),
        deviz_renovare_eur=deviz,
        include_mobilare=not is_furnished(
            subject, slug_hint="-mobilat-" in (subject.get("url") or "")
        ),
        prin_agentie=prin_agentie,
    )
    constatari = [
        str(x)
        for x in (
            ev.get("stare_vizuala"),
            ev.get("finisaje"),
            ev.get("observatii_vizuale"),
            *(ev.get("semne_ingrijorare") or []),
        )
        if x
    ]

    plan = negociere.plan(
        subject,
        ev.get("valoare_estimata_eur"),
        constatari=constatari,
        deviz_renovare=deviz_renovare or ev.get("cost_renovare_estimat_eur"),
        buget_total_max=buget_total_max,
        costuri_conexe=buget.get("costuri_conexe_eur"),
        risc_seismic=_risc_seismic(subject),
    )
    return {
        "status": "success",
        "id": listing_id,
        "titlu": subject.get("title"),
        "url": subject.get("url"),
        "pret_cerut_eur": subject.get("price_eur"),
        "valoare_estimata_eur": ev.get("valoare_estimata_eur"),
        "fiabilitate_evaluare": ev.get("fiabilitate"),
        "buget_consolidat": buget,
        **plan,
    }


@mcp.tool()
def inspecteaza_poze(
    identificator: Annotated[str, Field(description="Listing ID or imobiliare.ro URL")],
    intrebare: Annotated[str, Field(description="Question about the property's photos")],
) -> dict[str, Any]:
    """Inspect photographs of a listing using Gemini 3.8 Flash multimodal vision.

    Ask questions about finishes, natural lighting, layout, views, facade, or
    renovation needs based on the property photos.
    """
    try:
        listing_id = _resolve_id(identificator)
    except ValueError as e:
        return {"error": str(e)}

    with _client() as client:
        raw = client.hydrate([listing_id])
        if not raw:
            return {"error": f"Anunțul {listing_id} nu a putut fi găsit sau nu mai este activ."}
        subject = normalise(raw[0])

    from . import viziune

    return viziune.inspect(subject, intrebare)


@mcp.tool()
def analizeaza_mobilier_si_finisaje(
    identificator: Annotated[str, Field(description="Listing ID or imobiliare.ro URL")],
    limita_fotografii: Annotated[
        int, Field(description="Maximum photos to analyze (default 20)")
    ] = 20,
) -> dict[str, Any]:
    """Inspect photographs of a listing using Gemini 3.8 Flash multimodal vision
    to identify furniture, appliances and finishes, evaluate their quality tier,
    and estimate condition and renovation budget.
    """
    try:
        listing_id = _resolve_id(identificator)
    except ValueError as e:
        return {"error": str(e)}

    with _client() as client:
        raw = client.hydrate([listing_id])
        if not raw:
            return {"error": f"Anunțul {listing_id} nu a putut fi găsit sau nu mai este activ."}
        subject = normalise(raw[0])

    from . import viziune

    return viziune.analyse_furniture_and_finishes(
        subject=subject,
        limit=limita_fotografii,
    )


@mcp.tool()
def analizeaza_dezvoltator_si_constructor(
    identificator_sau_nume: Annotated[
        str,
        Field(
            description=(
                "Listing ID (275807510), imobiliare.ro URL, or residential project / "
                "developer name (e.g. 'One Floreasca Towers', 'Nusco City', 'HILS Development')"
            )
        ),
    ],
    context_suplimentar: Annotated[
        str | None,
        Field(description="Optional additional context, known developer name or questions"),
    ] = None,
) -> dict[str, Any]:
    """Analyze developer and general contractor / builder track record, completed
    projects, reputation, delivery delay history, utility status and risks for new builds.
    """
    from . import dezvoltator

    target: dict[str, Any] | str = identificator_sau_nume
    try:
        lid = _resolve_id(identificator_sau_nume)
        with _client() as client:
            raw = client.hydrate([lid])
            if raw:
                target = normalise(raw[0])
    except Exception:
        target = identificator_sau_nume.strip()

    return dezvoltator.analyse_developer_and_builder(
        subject_or_name=target,
        context_text=context_suplimentar,
    )


@mcp.tool()
def analizeaza_materiale_si_specificatii_tehnice(
    identificator_sau_nume: Annotated[
        str,
        Field(
            description=("Listing ID, imobiliare.ro URL, or residential complex name / description")
        ),
    ],
    include_fotografii: Annotated[
        bool,
        Field(description="Whether to inspect listing photos for construction materials"),
    ] = True,
    limita_fotografii: Annotated[
        int, Field(description="Maximum photos to analyze (default 15)")
    ] = 15,
) -> dict[str, Any]:
    """Perform a technical audit of construction materials used in a new build:
    reinforced concrete structure, masonry, facade insulation (mineral wool vs EPS, nZEB),
    triple glazing, underfloor heating, heat pumps/boilers, elevators and technical score.
    """
    from . import dezvoltator

    target: dict[str, Any] | str = identificator_sau_nume
    try:
        lid = _resolve_id(identificator_sau_nume)
        with _client() as client:
            raw = client.hydrate([lid])
            if raw:
                target = normalise(raw[0])
    except Exception:
        target = identificator_sau_nume.strip()

    return dezvoltator.analyse_construction_materials(
        subject_or_name=target,
        include_photos=include_fotografii,
        limit=limita_fotografii,
    )


@mcp.tool()
def checklist_receptie_imobil_nou(
    etapa: Annotated[
        str,
        Field(
            description=(
                "Stage of purchase: 'antecontract' (legal checks, building permit, clauses), "
                "'stadiu_constructie' (hidden works, conduit routes), or "
                "'receptie_finala' (handover, screed plumbness, glazing, utilities, warranties)"
            )
        ),
    ] = "receptie_finala",
    detalii_proiect: Annotated[
        str | None,
        Field(description="Optional specific complex or apartment features to customize checklist"),
    ] = None,
) -> dict[str, Any]:
    """Generate an actionable inspection and reception checklist for buyers of new
    properties, including legal warranties under Romanian Law 10/1995 and common pitfalls.
    """
    from . import dezvoltator

    return dezvoltator.generate_new_build_handover_checklist(
        stage=etapa,
        project_details=detalii_proiect,
    )


@mcp.tool()
def analizeaza_strada_si_imprejurimi_street_view(
    adresa_sau_identificator: Annotated[
        str,
        Field(
            description=(
                "Address (e.g. 'Calea Floreasca 160, Bucuresti'), coordinates ('44.46, 26.10'), "
                "listing ID (e.g. '275807510') or full imobiliare.ro URL."
            )
        ),
    ],
    include_satelit: Annotated[
        bool,
        Field(
            description=(
                "Whether to also retrieve and analyze high-resolution satellite aerial imagery."
            )
        ),
    ] = True,
) -> dict[str, Any]:
    """Capture and analyze 360-degree multi-angle Google Street View photographs
    and high-resolution satellite imagery for an address or listing with Gemini 3.8 Flash.

    Evaluates actual facade condition, insulation, enclosed balconies, AC units,
    sidewalk quality, overhead wiring vs buried cables, on-street/sidewalk parking,
    emergency vehicle clearance, roof condition, and privacy distance to neighbors.
    """
    from . import maps, viziune_strada

    lat: float | None = None
    lon: float | None = None
    address: str = adresa_sau_identificator.strip()

    # 1. Try resolving listing ID or URL. A non-id input is the normal case
    # (this tool also takes a plain address), so only that is silent -- a real
    # hydration failure is logged rather than swallowed.
    try:
        lid = _resolve_id(address)
    except ValueError:
        lid = None
    if lid:
        try:
            with _client() as client:
                raw = client.hydrate([lid])
            if raw:
                r_item = raw[0]
                sub = normalise(r_item)
                address = (
                    sub.get("address_text")
                    or r_item.get("address")
                    or sub.get("location")
                    or sub.get("title")
                    or address
                )
                # Only the raw record can carry coordinates; normalise() does
                # not produce latitude/longitude keys.
                if r_item.get("latitude") and r_item.get("longitude"):
                    lat, lon = float(r_item["latitude"]), float(r_item["longitude"])
        except Exception as exc:  # noqa: BLE001 - fall through to geocoding
            logger.warning("Nu s-a putut hidrata anunțul %s: %s", lid, exc)

    # 2. Check if coordinates were passed directly: "44.4325, 26.1038"
    if lat is None or lon is None:
        parts = [p.strip() for p in address.split(",")]
        if len(parts) == 2:
            try:
                c_lat, c_lon = float(parts[0]), float(parts[1])
                if -90 <= c_lat <= 90 and -180 <= c_lon <= 180:
                    lat, lon = c_lat, c_lon
            except ValueError:
                pass

    # 3. Geocode address if still no coordinates
    if lat is None or lon is None:
        place = maps.geocode(address)
        if place:
            lat, lon = place.lat, place.lon
            # MapsPlace calls this `display`; there is no `formatted_address`.
            address = place.display or address

    if lat is None or lon is None:
        return {
            "status": "error",
            "message": f"Nu s-au putut determina coordonatele geografice pentru: '{address}'.",
            "rezumat_markdown": f"> ⚠️ Nu s-a putut localiza pe hartă adresa: `{address}`.",
        }

    return viziune_strada.analyse_street_and_surroundings(
        lat=lat,
        lon=lon,
        address=address,
        include_satellite=include_satelit,
    )


@mcp.tool()
def analizeaza_bonitate_dezvoltator_targetare(
    cui_sau_nume: Annotated[
        str,
        Field(
            description=(
                "Tax identification code (CUI / CIF, e.g. '12345678' or 'RO12345678') "
                "or full/partial company name of the developer or general contractor."
            )
        ),
    ],
) -> dict[str, Any]:
    """Perform financial due diligence and solvency risk analysis on a real estate developer
    or contractor using Targetare.ro financial database.

    Retrieves balance sheet metrics: turnover, net profit/loss, total debt, equity,
    employee count, CAEN code, VAT status, active/insolvent state, and computes a financial
    health score (1-10) with buyer recommendations.
    """
    from . import targetare

    return targetare.analizeaza_firma_targetare(cui_sau_nume)


@mcp.tool()
def recenzii_reputatie_google_maps(
    nume_sau_adresa_sau_place_id: Annotated[
        str,
        Field(
            description=(
                "Complex name (e.g. 'One Cotroceni Park'), developer brand, full address, "
                "or Google Place ID to inspect customer and resident reviews."
            )
        ),
    ],
) -> dict[str, Any]:
    """Retrieve Google Maps reviews for a residential complex, developer showroom, or location
    and perform an AI sentiment and red-flag audit using Gemini 3.8 Flash.

    Extracts overall rating, review volume, resident complaints (construction delays, water leaks,
    poor acoustic isolation, lack of parking, developer post-sales unresponsive), and positive aspects.
    """
    from . import recenzii_maps

    return recenzii_maps.obtine_si_analizeaza_recenzii(nume_sau_adresa_sau_place_id)


@mcp.tool()
def analizeaza_electrocasnice_si_defecte_finisaje(
    identificator_proprietate: Annotated[
        str,
        Field(
            description=(
                "Listing ID (e.g. '275807510') or full URL from imobiliare.ro. "
                "Performs an in-depth audit with Gemini 3.8 Flash Vision to detect visible "
                "appliances, identify their brands (Miele, Bosch, Samsung, etc.), determine "
                "market grade, estimate new retail prices and depreciated values, generate "
                "online price search links, and audit finish defects (cracks, water stains, "
                "damaged skirtings/flooring, faulty caulking) with estimated remediation costs."
            )
        ),
    ],
    limita_fotografii: Annotated[
        int, Field(description="Maximum photos to analyze (default 20)")
    ] = 20,
) -> dict[str, Any]:
    """Audit interior finishes quality, detect defects/issues with repair costs,
    recognize kitchen/home appliances, identify brands and search online prices.
    """
    from . import electrocasnice_finisaje

    subject: dict[str, Any] = {"title": identificator_proprietate}
    image_urls: list[str] = []

    try:
        lid = _resolve_id(identificator_proprietate)
        with _client() as client:
            raw = client.hydrate([lid])
            if raw:
                subject = normalise(raw[0])
                image_urls = subject.get("image_urls") or []
    except Exception as exc:
        logger.debug("Nu s-a putut hidrata proprietatea direct: %s", exc)

    return electrocasnice_finisaje.analizeaza_electrocasnice_si_finisaje(
        subject=subject,
        image_urls=image_urls,
        limit=limita_fotografii,
    )


@mcp.tool()
def verifica_risc_seismic(
    adresa_sau_identificator: Annotated[
        str,
        Field(
            description=(
                "Street address in Bucharest ('Strada Academiei 15, Sector 1'), or an "
                "imobiliare.ro listing id / URL, in which case the address is taken from "
                "the listing."
            )
        ),
    ],
    numar: Annotated[
        str | None,
        Field(description="House number, when it is not already part of the address."),
    ] = None,
    sector: Annotated[
        str | None, Field(description="Bucharest sector ('Sector 3'), to disambiguate.")
    ] = None,
    limita: Annotated[int, Field(description="Maximum matches to return (default 5).")] = 5,
) -> dict[str, Any]:
    """Check a Bucharest building against the AMCCRS seismic-risk register (bulina rosie).

    Answers whether the building has been classified RsI-RsIV or in an urgency category
    U1-U3, whether it has already been consolidated, when it was expertised and by whom,
    and what that means for price, mortgage eligibility and insurance.

    A class RsI building ("bulina rosie") is the single largest hidden discount on a
    Bucharest flat: most banks will not lend against it and the owner carries a legal
    obligation to consolidate -- none of which a listing discloses.

    Absence from the register is not a clean bill of health: it only covers buildings that
    have been through a technical expertise, so the result says so explicitly.
    """
    from . import risc_seismic

    text = (adresa_sau_identificator or "").strip()
    adresa = text
    sursa_adresei = "utilizator"

    # A listing id resolves to the portal's own address line, which is usually
    # street-level only -- sellers omit the number. That is worth saying in the
    # answer rather than letting a street-level match read as a building-level one.
    if text.isdigit() or "imobiliare.ro" in text.lower():
        try:
            lid = _resolve_id(text)
            with _client() as client:
                raw = client.hydrate([lid])
            if raw:
                record = normalise(raw[0])
                adresa = (record.get("address_text") or record.get("title") or "").strip() or text
                sursa_adresei = f"anunt {lid}"
        except Exception as exc:  # noqa: BLE001 - fall back to the raw text as an address
            logger.debug("Nu am putut prelua adresa din anunt: %s", exc)

    rezultat = risc_seismic.cauta(adresa, numar=numar, sector=sector, limita=limita)
    rezultat["adresa_folosita"] = adresa
    rezultat["sursa_adresei"] = sursa_adresei
    if sursa_adresei != "utilizator" and not rezultat.get("interogare", {}).get("numere_cautate"):
        rezultat["avertisment"] = (
            "Anuntul nu publica numarul postal, asa ca verificarea e la nivel de strada. "
            "Cere adresa exacta inainte de a folosi rezultatul in negociere. "
        ) + str(rezultat.get("avertisment") or "")
    return rezultat


# The finishes audit reports defects as `defecte_si_probleme`, each an object
# with `element_afectat` / `descriere_defect` -- not the flat list of strings the
# levers first looked for, which meant no lever ever fired on a real listing.
_CHEI_TEXT = ("concluzie", "observatii", "stare_generala", "rezumat", "stare_conservare")
_CHEI_LISTE = ("defecte_si_probleme", "defecte_identificate", "semne_ingrijorare", "probleme")
_CHEI_DEFECT = ("descriere_defect", "descriere", "element_afectat", "cauza_probabila")


def _constatari_din_audit(*surse: dict[str, Any]) -> list[str]:
    """Everything an audit said about condition, flattened into matchable phrases."""
    constatari: list[str] = []
    for sursa in surse:
        if not isinstance(sursa, dict):
            continue
        calitate = sursa.get("calitate_generala_finisaje")
        for bloc in (sursa, calitate if isinstance(calitate, dict) else {}):
            for cheie in _CHEI_TEXT:
                if valoare := bloc.get(cheie):
                    constatari.append(str(valoare))
        for cheie in _CHEI_LISTE:
            for item in sursa.get(cheie) or []:
                if isinstance(item, dict):
                    constatari.extend(str(item[k]) for k in _CHEI_DEFECT if item.get(k))
                else:
                    constatari.append(str(item))
    return constatari


def _strategie_pe_scurt(plan: dict[str, Any]) -> dict[str, Any]:
    """The ladder and the verdict, without the prose.

    The full plan carries three draft offers and three checklists -- several KB
    of text that belong in the report, not in the model's context on every
    valuation. `strategie_negociere` returns all of it when it is actually
    wanted.
    """
    if not plan.get("disponibil"):
        return plan
    profil = plan.get("profil_vanzator") or {}
    return {
        "status": plan.get("status"),
        "disponibil": True,
        "scara": plan.get("scara"),
        "regula_decizionala": plan.get("regula_decizionala"),
        "profil_vanzator": profil.get("profil"),
        "semnale_vanzator": profil.get("semnale_detectate"),
        "parghii": [x.get("problema") for x in plan.get("parghii") or []],
        "verificari_impuse": [x.get("risc") for x in plan.get("steaguri_rosii") or []],
        "detalii_complete": (
            "Apelează strategie_negociere pentru scripturi, checklist-uri și argumentele "
            "complete; raportul atașat le conține deja."
        ),
        "sursa": plan.get("sursa"),
    }


def _record_din_dosar(date: dict[str, Any]) -> dict[str, Any]:
    """The handful of listing fields the strategy reads, recovered from a dossier."""
    etaj = date.get("etaj")
    numar_etaj = None
    if isinstance(etaj, str) and (gasit := re.search(r"\d+", etaj)):
        numar_etaj = int(gasit.group())
    an = date.get("an_constructie")
    return {
        "price_eur": date.get("pret_total"),
        "surface_sqm": date.get("suprafata_utila"),
        "rooms": date.get("camere"),
        "year_built": an,
        "floor": numar_etaj,
        "is_new_build": bool(an and an >= 2018),
        "address_text": date.get("adresa"),
        "seller_type": "developer" if date.get("dezvoltator") else None,
    }


def _completeaza_strategie(date: dict[str, Any], sub: dict[str, Any] | None) -> None:
    """Fill the negotiation, cost and summary blocks of a dossier, in place.

    Every block is best-effort and self-describing: when the evidence is not
    there it is written as `status: "indisponibil"` with a reason, never left
    absent for a renderer to paper over with a default.
    """
    ev = date.get("evaluare_anevar") or {}
    evaluare_ok = ev.get("disponibil") is not False and ev.get("valoare_estimata_piata")
    pret = date.get("pret_total")
    suprafata = date.get("suprafata_utila")
    camere = date.get("camere")
    # The demo dossier has no normalised listing behind it. Reconstructing the
    # few fields the strategy reads from the dossier itself is what keeps the
    # sample report and a generated one structurally identical -- they used to
    # diverge, and the sample was the only one that looked complete.
    record = sub or _record_din_dosar(date)

    nou = bool(record.get("is_new_build")) or (date.get("an_constructie") or 0) >= 2018

    # -- Costuri ----------------------------------------------------------
    if "costuri_tranzactionare" not in date:
        date["costuri_tranzactionare"] = costuri.costuri_tranzactionare(
            pret, prin_agentie=(record.get("seller_type") == "agency")
        )
    if "costuri_detinere" not in date:
        date["costuri_detinere"] = costuri.costuri_detinere(suprafata, bloc_nou=nou)

    deviz = None
    audit = date.get("audit_electrocasnice_finisaje") or date.get("audit_electrocasnice") or {}
    if isinstance(audit, dict):
        sumar = audit.get("sumar_financiar") or {}
        # A remediation budget of 0 is an audit that found nothing, and it has
        # to survive as 0 rather than fall through to the next candidate.
        for candidate in (
            sumar.get("total_buget_remediere_defecte_eur"),
            audit.get("cost_renovare_estimat_eur"),
        ):
            if candidate is not None:
                deviz = candidate
                break

    if "buget_consolidat" not in date:
        date["buget_consolidat"] = costuri.buget_consolidat(
            pret,
            suprafata,
            camere,
            deviz_renovare_eur=deviz,
            include_mobilare=not is_furnished(
                record, slug_hint="-mobilat-" in (record.get("url") or "")
            ),
            prin_agentie=(record.get("seller_type") == "agency"),
        )

    # -- Risc seismic (AMCCRS) ---------------------------------------------
    # Before the strategy, which consumes it: a confirmed RsI changes which red
    # flags the plan raises, and it is the one finding that can make the
    # purchase the wrong decision rather than merely the wrong price.
    if "risc_seismic" not in date:
        if constatare_rs := _risc_seismic(record):
            date["risc_seismic"] = constatare_rs

    # -- Strategia de negociere -------------------------------------------
    if "strategie_negociere" not in date:
        constatari = _constatari_din_audit(audit, date.get("audit_exterior") or {})

        sanatate = None
        tgt = date.get("audit_targetare") or date.get("targetare_financiar") or {}
        if isinstance(tgt, dict) and tgt.get("disponibil") is not False:
            analiza = tgt.get("analiza_financiara") or {}
            scor = analiza.get("scor_sanatate_financiara")
            if scor is not None:
                sanatate = float(scor) >= 5.0

        conexe = (date.get("buget_consolidat") or {}).get("costuri_conexe_eur")
        date["strategie_negociere"] = negociere.plan(
            {**record, "price_eur": pret},
            ev.get("valoare_estimata_piata") if evaluare_ok else None,
            constatari=constatari,
            deviz_renovare=deviz,
            costuri_conexe=conexe,
            dezvoltator_sanatos=sanatate,
            risc_seismic=date.get("risc_seismic"),
        )

    # -- Riscuri: the red flags the evidence supports, not a generic list ---
    strategie = date.get("strategie_negociere") or {}
    if not date.get("riscuri") and strategie.get("steaguri_rosii"):
        date["riscuri"] = strategie["steaguri_rosii"]

    # -- Sinteza executivă --------------------------------------------------
    if not date.get("rezumat_executiv"):
        date["rezumat_executiv"] = _rezumat_executiv(date, strategie)
    forte, slabe = _puncte_forte_slabe(date, strategie)
    date.setdefault("puncte_forte", forte)
    date.setdefault("puncte_slabe", slabe)

    if not date.get("metodologie"):
        date["metodologie"] = {
            "abordare_principala": (
                "Comparația directă a vânzărilor, cu ajustări regresate din setul de "
                "comparabile (GEV 630 §54–58)."
            ),
            "abordare_secundara": (
                "Capitalizarea directă a venitului net din chirii comparabile (GEV 630 §59–71)."
            ),
            "sursa_comparabile": "Oferte active publicate pe imobiliare.ro, în aceeași arie.",
            "strategie_negociere": (
                "Scara de ofertare este calibrată pe practica de piață a segmentului "
                "rezidențial bucureștean; este un parametru al modelului, nu o măsurătoare "
                "a acestui imobil."
            ),
            "standard": "SEV 2025",
        }
    if not date.get("ipoteze_limitative"):
        date["ipoteze_limitative"] = [
            "Lucrarea NU este un raport de evaluare și nu se afirmă conformitatea cu SEV "
            "(SEV 106 §30.8): nu există inspecție la fața locului, verificare a titlului sau "
            "semnătura unui evaluator autorizat.",
            "Comparabilele sunt oferte active, nu prețuri de tranzacționare; corecția de la "
            "preț cerut la preț probabil este estimată, nu observată.",
            "Suprafețele, anul construcției și dotările sunt cele declarate de vânzător.",
            "Strategia de negociere este orientativă și nu constituie consultanță juridică.",
        ]


def _rezumat_executiv(date: dict[str, Any], strategie: dict[str, Any]) -> str:
    """Two or three sentences that say only what the sections actually produced."""
    ev = date.get("evaluare_anevar") or {}
    titlu = date.get("titlu") or "Proprietatea analizată"
    bucati = [f"{titlu}."]

    if ev.get("disponibil") is not False and ev.get("valoare_estimata_piata"):
        verdict = ev.get("verdict_piata") or ""
        bucati.append(
            f"Valoarea estimată prin comparație directă este de "
            f"{ev['valoare_estimata_piata']:,.0f} EUR. {verdict}.".replace(",", ".")
        )
    else:
        bucati.append(
            "Evaluarea de piață nu a putut fi calculată: "
            f"{ev.get('motiv') or 'eșantion de comparabile insuficient'}."
        )

    if strategie.get("disponibil"):
        bucati.append(strategie.get("regula_decizionala", ""))

    scor = date.get("scor_general")
    if scor is not None:
        bucati.append(
            f"Scor global {scor}/10 ({date.get('calificativ_general')}), calculat din "
            f"secțiunile care au produs o măsurătoare."
        )
    return " ".join(x for x in bucati if x)


def _puncte_forte_slabe(
    date: dict[str, Any], strategie: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Strengths and weaknesses, each traceable to a section that measured one."""
    forte: list[str] = []
    slabe: list[str] = []

    ev = date.get("evaluare_anevar") or {}
    ajustare = ev.get("ajustare_recomandata_procent")
    if ajustare is not None:
        if ajustare <= -3:
            forte.append(f"Preț cerut sub valoarea estimată ({ajustare:+.1f}%).")
        elif ajustare >= 5:
            slabe.append(f"Preț cerut peste valoarea estimată ({ajustare:+.1f}%).")

    loc = date.get("locatie") or {}
    if loc.get("status") == "success":
        facilitati = loc.get("facilitati") or loc.get("pois") or {}
        if isinstance(facilitati, dict) and facilitati.get("metrou"):
            forte.append("Stație de metrou în raza analizată.")

    audit = date.get("audit_electrocasnice_finisaje") or date.get("audit_electrocasnice") or {}
    calitate = (audit or {}).get("calitate_generala_finisaje") or {}
    if (scor := calitate.get("scor_global")) is not None:
        (forte if float(scor) >= 7 else slabe).append(
            f"Finisaje evaluate la {scor}/10 ({calitate.get('stare_conservare') or 'stare'})."
        )

    for steag in strategie.get("steaguri_rosii") or []:
        slabe.append(steag.get("risc") or "")

    return [x for x in forte if x], [x for x in slabe if x]


@mcp.tool()
def genereaza_raport_complet_pdf(
    adresa_sau_identificator: Annotated[
        str,
        Field(
            description=(
                "Listing ID, URL or property address to compile the full dossier for. "
                "Orchestrates ANEVAR valuation, finishes audit, Street View 360°, developer specs, "
                "Targetare financials, and Google reviews into a single professional PDF."
            )
        ),
    ],
    date_suplimentare_json: Annotated[
        str,
        Field(
            description=(
                "Optional JSON string containing pre-collected tool results "
                "(evaluare_anevar, audit_mobilier, audit_electrocasnice_finisaje, "
                "audit_exterior, specificatii_dezvoltator, audit_targetare, recenzii_google, etc.)"
            )
        ),
    ] = "",
    cale_salvare: Annotated[
        str,
        Field(description="Optional custom destination path for the PDF report"),
    ] = "",
) -> dict[str, Any]:
    """Generate a comprehensive property audit and valuation dossier in PDF format,
    designed strictly according to Google Docs professional documentation guidelines.

    Includes ANEVAR GEV 630 valuation, interior finishes vision audit, 360° Street View &
    satellite imagery, developer/contractor specs, Targetare.ro financial solvency due diligence,
    Google Maps community reviews, and a handover inspection checklist.
    """
    from . import generator_pdf, recenzii_maps, targetare

    # Extract listing data if possible
    date_proprietate: dict[str, Any] = {}

    if date_suplimentare_json:
        try:
            extra = json.loads(date_suplimentare_json)
            if isinstance(extra, dict):
                date_proprietate.update(extra)
        except Exception as err:
            logger.warning("Could not parse date_suplimentare_json: %s", err)

    sub: dict[str, Any] | None = None
    try:
        lid = _resolve_id(adresa_sau_identificator)
        with _client() as client:
            raw = client.hydrate([lid])
            if raw:
                r_item = raw[0]
                sub = normalise(r_item)
                date_proprietate["id"] = str(lid)
                titlu_str = sub.get("title") or r_item.get("heading") or f"Apartament {lid}"
                date_proprietate["titlu"] = titlu_str
                date_proprietate["moneda"] = "EUR"
                # No stand-in values here. An invented surface is multiplied
                # into the ANEVAR interval below, so a guess at this point
                # comes back out as a valuation.
                date_proprietate["pret_total"] = sub.get("price_eur")
                date_proprietate["suprafata_utila"] = sub.get("surface_sqm")
                date_proprietate["camere"] = sub.get("rooms")
                fl_num = sub.get("floor")
                fl_tot = sub.get("floors_total")
                date_proprietate["etaj"] = (
                    f"Etaj {fl_num} din {fl_tot}"
                    if (fl_num is not None and fl_tot)
                    else f"Etaj {fl_num}"
                    if fl_num is not None
                    else None
                )
                date_proprietate["an_constructie"] = sub.get("year_built")
                date_proprietate["url"] = (
                    sub.get("url") or r_item.get("url") or adresa_sau_identificator
                )

                # The city comes from the listing or not at all -- appending
                # ", București" unconditionally relabelled every Cluj, Brașov
                # and Timișoara property as being in Bucharest, and that
                # address then drove geocoding, Street View and the reviews.
                loc_txt = sub.get("address_text") or r_item.get("address") or sub.get("location")
                oras = sub.get("city") or sub.get("county")
                if loc_txt and oras and oras.lower() not in loc_txt.lower():
                    loc_txt = f"{loc_txt}, {oras}"
                date_proprietate["adresa"] = loc_txt
                date_proprietate["imagini"] = sub.get("image_urls") or []

                # Generare foaie de contact galerie dacă sunt poze
                if "cale_galerie" not in date_proprietate and sub.get("image_urls"):
                    try:
                        destinatie = paths.reports_dir() / f"galerie-{lid}.jpg"
                        if paths.ensure_dir(destinatie.parent):
                            cale_gal = contact_sheet(sub["image_urls"], destinatie)
                            if cale_gal:
                                date_proprietate["cale_galerie"] = str(cale_gal)
                    except Exception as e:
                        logger.warning("Nu s-a putut genera foaia de contact: %s", e)

                # Evaluare ANEVAR sumară
                if "evaluare_anevar" not in date_proprietate:
                    try:
                        eval_res = evaluare(
                            lid, cu_viziune=False, cu_galerie=False, cu_localizare=False
                        )
                        if (
                            eval_res
                            and eval_res.get("disponibil") is not False
                            and eval_res.get("valoare_estimata_eur")
                        ):
                            val_est = eval_res.get("valoare_estimata_eur") or eval_res.get(
                                "abordare_piata_eur"
                            )
                            sqm = date_proprietate.get("suprafata_utila")
                            pret_cerut = date_proprietate.get("pret_total") or eval_res.get(
                                "pret_cerut_eur"
                            )
                            dif_pct = eval_res.get("diferenta_pct")
                            if dif_pct is None and pret_cerut and val_est:
                                dif_pct = round((pret_cerut - val_est) / val_est * 100, 1)

                            # The interval comes from the grid's own spread of
                            # adjusted unit values, or not at all -- a ±10%
                            # band around the point estimate is a decoration,
                            # not a range the comparables support.
                            range_val = eval_res.get("interval_valori_eur_mp")
                            v_min = round(range_val[0] * sqm) if (range_val and sqm) else None
                            v_max = round(range_val[1] * sqm) if (range_val and sqm) else None
                            pret_mp_est = eval_res.get("valoare_unitara_estimata_eur_mp") or (
                                round(val_est / sqm) if (val_est and sqm) else None
                            )
                            pret_mp_cerut = eval_res.get("pret_unitar_cerut_eur_mp") or (
                                round(pret_cerut / sqm) if (pret_cerut and sqm) else None
                            )
                            marja = (
                                (pret_cerut - val_est)
                                if (pret_cerut and val_est and pret_cerut > val_est)
                                else 0
                            )

                            comps_data = eval_res.get("comparabile") or []
                            if len(comps_data) >= 3:
                                date_proprietate["evaluare_anevar"] = {
                                    "status": "disponibil",
                                    "disponibil": True,
                                    "valoare_estimata_piata": val_est,
                                    "interval_valoare_min": v_min,
                                    "interval_valoare_max": v_max,
                                    "pret_pe_mp_estimat": pret_mp_est,
                                    "pret_pe_mp_cerut": pret_mp_cerut,
                                    "ajustare_recomandata_procent": dif_pct,
                                    "marja_negociere_eur": marja,
                                    # dif_pct > 0 means the asking price is
                                    # *above* the estimate, i.e. overpriced --
                                    # it was previously reported as "aligned
                                    # with the market" whatever its size.
                                    "verdict_piata": _verdict_piata(dif_pct),
                                    "comparabile_utilizate": comps_data,
                                    "provenienta": "estimat",
                                }
                                if eval_res.get("piata"):
                                    date_proprietate.setdefault("analiza_piata", eval_res["piata"])
                            else:
                                date_proprietate["evaluare_anevar"] = {
                                    "status": "indisponibil",
                                    "disponibil": False,
                                    "motiv": "Eșantion insuficient: sub 3 comparabile reale calificate conform standardului ANEVAR GEV 630.",
                                    "provenienta": "indisponibil",
                                    "comparabile_utilizate": comps_data,
                                }
                        else:
                            date_proprietate["evaluare_anevar"] = {
                                "status": "indisponibil",
                                "disponibil": False,
                                "motiv": (eval_res or {}).get("motiv")
                                or "Eșantion insuficient: sub 3 comparabile reale identificate conform standardului ANEVAR GEV 630.",
                                "provenienta": "indisponibil",
                                "comparabile_utilizate": (eval_res or {}).get("comparabile") or [],
                            }
                    except Exception as err:
                        logger.warning("Eroare evaluare ANEVAR: %s", err)
                        date_proprietate["evaluare_anevar"] = {
                            "status": "indisponibil",
                            "disponibil": False,
                            "motiv": f"Eroare evaluare ANEVAR: {err}",
                            "provenienta": "indisponibil",
                        }

                # Audit interior mobilier & electrocasnice
                if (
                    "audit_electrocasnice_finisaje" not in date_proprietate
                    and "audit_electrocasnice" not in date_proprietate
                ):
                    try:
                        from . import electrocasnice_finisaje

                        ef_res = electrocasnice_finisaje.analizeaza_electrocasnice_si_finisaje(
                            sub, limit=15
                        )
                        if (
                            ef_res
                            and ef_res.get("status") == "success"
                            and ef_res.get("disponibil") is not False
                        ):
                            ef_data = ef_res.get("date_analiza", {})
                            ef_data["mod_analiza"] = ef_res.get(
                                "mod_analiza", ef_data.get("mod_analiza", "necunoscut")
                            )
                            ef_data["provenienta"] = ef_res.get(
                                "provenienta", ef_data.get("provenienta", "model")
                            )
                            date_proprietate["audit_electrocasnice_finisaje"] = ef_data
                            date_proprietate["audit_electrocasnice"] = ef_data
                    except Exception as err:
                        logger.warning("Eroare audit electrocasnice: %s", err)
    except Exception as exc:
        logger.debug("Eroare hidratare listing: %s", exc)

    # Asigurare valori implicite obligatorii (fără date inventate)
    date_proprietate.setdefault("id", "imobil")
    date_proprietate.setdefault("adresa", adresa_sau_identificator)
    date_proprietate.setdefault("titlu", f"Raport Evaluare - {adresa_sau_identificator}")
    date_proprietate.setdefault("moneda", "EUR")

    # Fallback finisaje & electrocasnice când lipsesc datele
    if not date_proprietate.get("audit_electrocasnice") and not date_proprietate.get(
        "audit_electrocasnice_finisaje"
    ):
        ef_indisponibil = {
            "status": "indisponibil",
            "disponibil": False,
            "motiv": "Nu au fost furnizate fotografii sau specificații suficiente pentru analiza electrocasnicelor și finisajelor.",
            "provenienta": "indisponibil",
            "calitate_generala_finisaje": None,
            "categorii_finisaje": [],
            "defecte_si_probleme": [],
            "electrocasnice": [],
            "sumar_financiar": None,
        }
        date_proprietate["audit_electrocasnice"] = ef_indisponibil
        date_proprietate["audit_electrocasnice_finisaje"] = ef_indisponibil

    # Street View & Satelit
    if "audit_exterior" not in date_proprietate:
        try:
            target_strada = (
                str(date_proprietate.get("id"))
                if date_proprietate.get("id") != "imobil"
                else (date_proprietate.get("adresa") or adresa_sau_identificator)
            )
            ext_res = analizeaza_strada_si_imprejurimi_street_view(
                target_strada, include_satelit=True
            )
            # The street-view tool returns its analysis under "audit".
            # Reading a key it never sets yielded {} on every run, which the
            # lines below then stamped as available and model-sourced.
            audit = (ext_res or {}).get("audit") if ext_res else None
            if ext_res and ext_res.get("status") == "success" and audit:
                date_proprietate["audit_exterior"] = {
                    **audit,
                    "imagini_salvate": ext_res.get("imagini_salvate", []),
                    "metadata_street_view": ext_res.get("metadata_street_view"),
                    "status": "disponibil",
                    "disponibil": True,
                    "provenienta": "model",
                }
        except Exception as e:
            logger.warning("Nu s-a putut realiza auditul exterior: %s", e)

    ext = date_proprietate.get("audit_exterior") or {}
    if not ext or ext.get("status") == "error":
        date_proprietate["audit_exterior"] = {
            "status": "indisponibil",
            "disponibil": False,
            "motiv": "Google Street View nu are acoperire pentru această adresă sau imaginile lipsesc.",
            "provenienta": "indisponibil",
            # Empty, not the listing's interior photos: this section is about
            # the street and the facade, and captioning interior shots as
            # Street View imagery is worse than showing nothing.
            "imagini_salvate": [],
        }

    # Dezvoltator & Constructor
    if "specificatii_dezvoltator" not in date_proprietate:
        from . import dezvoltator

        dev_res = dezvoltator.extract_developer_and_constructor_info(
            descriere=(sub or {}).get("description") or "",
            titlu=(sub or {}).get("title") or date_proprietate.get("titlu") or "",
            agentie=(sub or {}).get("agency") or (sub or {}).get("agency_name") or "",
            complex_name=(sub or {}).get("complex_name") or "",
        )
        date_proprietate["specificatii_dezvoltator"] = dev_res.get("analiza_dezvoltator", {})

    dev_name = date_proprietate.get("specificatii_dezvoltator", {}).get(
        "dezvoltator"
    ) or date_proprietate.get("dezvoltator")
    if dev_name:
        date_proprietate["dezvoltator"] = dev_name
    constructor_name = date_proprietate.get("specificatii_dezvoltator", {}).get(
        "constructor"
    ) or date_proprietate.get("constructor")
    if constructor_name:
        date_proprietate["constructor"] = constructor_name

    # Audit Targetare.ro
    if "audit_targetare" not in date_proprietate and "targetare_financiar" not in date_proprietate:
        if dev_name:
            try:
                t_res = targetare.analizeaza_firma_targetare(dev_name)
                if t_res and t_res.get("status") == "success":
                    t_res["provenienta"] = "masurat"
                    t_res["disponibil"] = True
                    date_proprietate["audit_targetare"] = t_res
                    date_proprietate["targetare_financiar"] = t_res
            except Exception as e:
                logger.debug("Targetare error: %s", e)

    if not date_proprietate.get("audit_targetare") and not date_proprietate.get(
        "targetare_financiar"
    ):
        t_unavailable = {
            "status": "indisponibil",
            "disponibil": False,
            "motiv": "Dezvoltatorul sau constructorul nu a fost menționat în anunț sau datele fiscale/bilanțiere nu sunt disponibile.",
            "provenienta": "indisponibil",
        }
        date_proprietate["audit_targetare"] = t_unavailable
        date_proprietate["targetare_financiar"] = t_unavailable

    # Recenzii Google Maps
    if "recenzii_google" not in date_proprietate:
        query_parts = [
            p
            for p in [
                dev_name,
                date_proprietate.get("complex_name"),
                date_proprietate.get("adresa"),
            ]
            if p
        ]
        if query_parts:
            try:
                search_query = " ".join(query_parts)
                r_res = recenzii_maps.citeste_si_analizeaza_recenzii_google(search_query)
                if r_res and r_res.get("status") == "success":
                    r_res["provenienta"] = "masurat"
                    r_res["disponibil"] = True
                    date_proprietate["recenzii_google"] = r_res
            except Exception as e:
                logger.debug("Recenzii error: %s", e)

    if not date_proprietate.get("recenzii_google"):
        rec_unavailable = {
            "status": "indisponibil",
            "disponibil": False,
            "motiv": "Nu au fost identificate recenzii Google Maps pentru acest imobil sau dezvoltator.",
            "provenienta": "indisponibil",
        }
        date_proprietate["recenzii_google"] = rec_unavailable

    # Locație & Facilități 500m
    if "locatie" not in date_proprietate:
        try:
            from gemini_act.api import imagery

            date_proprietate["locatie"] = imagery.build_location_block(
                date_proprietate.get("adresa") or "",
                fallback=date_proprietate.get("complex_name"),
                radius_m=500,
                lat=date_proprietate.get("lat"),
                lon=date_proprietate.get("lon"),
            )
        except Exception as e:
            logger.debug("Eroare generare locatie in server: %s", e)

    # Checklist Recepție Tehnică. Generic by design: these are checks that
    # apply to any purchase. Naming a specific joinery brand or boiler type
    # here asserted equipment nobody had looked at.
    if not date_proprietate.get("checklist_receptie") and not date_proprietate.get(
        "receptie_checklist"
    ):
        chk_items = [
            "Verificare Carte Tehnică a Construcției (disponibilă la dezvoltator/proiectant)",
            "Solicitare Proces Verbal de Recepție la Terminarea Lucrărilor (conform Legii 10/1995)",
            "Testare presiune circuite apă rece/caldă și verificare termică instalație",
            "Certificat de Performanță Energetică și verificarea clasei energetice declarate",
            "Garanții scrise pentru tâmplărie, centrala termică și celelalte dotări incluse",
            "Verificare lipsă sarcini în Extrasul de Carte Funciară pentru autentificare",
            "Probe funcționale pentru disjunctoarele diferențiale din tabloul electric",
            "Inspecție planeitate șape și verticalitate pereți înainte de montaj parchet/gresie",
        ]
        date_proprietate["checklist_receptie"] = chk_items
        date_proprietate["receptie_checklist"] = chk_items

    # Strategie de negociere, costuri consolidate și sinteza executivă.
    #
    # These are the sections the web UI and the PDF have always rendered but
    # nothing ever filled on a real listing -- the PDF substituted defaults for
    # them, so a generated dossier showed invented market and ESG figures while
    # the demo showed authored ones. They are computed here, from the listing
    # and the valuation, or they are marked unavailable.
    _completeaza_strategie(date_proprietate, sub)

    # Coordonatele, urcate din blocul de locație: PDF-ul și interfața le citesc
    # de la rădăcină, iar fără ele harta din raport rămâne goală.
    loc_block = date_proprietate.get("locatie") or {}
    if loc_block.get("status") == "success":
        date_proprietate.setdefault("lat", loc_block.get("lat"))
        date_proprietate.setdefault("lon", loc_block.get("lon"))

    # Scor general, derivat din secțiunile care chiar au produs o măsurătoare.
    scor, calificativ, baza = _scor_general(date_proprietate)
    date_proprietate["scor_general"] = date_proprietate.get("scor_general") or scor
    date_proprietate["calificativ_general"] = (
        date_proprietate.get("calificativ_general") or calificativ
    )
    date_proprietate["scor_general_baza"] = baza

    # Generare PDF prin generator_pdf
    cale_finala = generator_pdf.genereaza_raport_complet_pdf(
        date_proprietate,
        cale_iesire=cale_salvare,
    )

    return {
        "status": "success",
        "cale_pdf": cale_finala,
        "proprietate_id": date_proprietate.get("id"),
        "titlu": date_proprietate.get("titlu"),
        "date_audit": date_proprietate,
        "mesaj": f"Raportul complet a fost compilat și exportat în: {cale_finala}",
        "rezumat_markdown": (
            f"### 📄 Raport de Evaluare și Audit Imobiliar Generat cu Succes\n\n"
            f"- **Fișier PDF:** `{cale_finala}`\n"
            f"- **Standard de Prezentare:** Ghidul Oficial de Tehnoredactare Google Docs\n"
            f"- **Secțiuni Incluse:** Fișă tehnică, Evaluare ANEVAR (GEV 630), Audit Vizual "
            f"Mobilier & Finisaje, Inspecție Fațadă & Stradă 360° Google Street View, "
            f"Specificații Tehnice Dezvoltator, Due Diligence Financiar Targetare.ro, "
            f"Recenzii Google Maps și Checklist Tehnic de Recepție."
        ),
    }


# -- Documente de referință din Google Drive -------------------------------
#
# Folderul este citit cu identitatea procesului (ADC — pe Cloud Run, contul de
# serviciu al serviciului), deci trebuie partajat cu acel cont ca Viewer.
# `drive_docs` explică de ce un folder nepartajat raportează 404 și nu 403.


@mcp.tool()
def documente_drive(
    reincarca: Annotated[
        bool, Field(description="Ignoră listarea din cache și interoghează Drive din nou")
    ] = False,
) -> dict[str, Any]:
    """Listează documentele de referință din folderul Google Drive configurat.

    Subfolderele sunt parcurse. Folosește asta întâi, ca să afli ce documente
    există, apoi `citeste_document_drive` pentru unul anume sau
    `cauta_in_documente_drive` ca să găsești un pasaj fără a citi tot.
    """
    try:
        documente = drive_docs.listeaza(reincarca=reincarca)
    except drive_docs.DriveIndisponibil as exc:
        return {"status": "error", "error_message": str(exc)}
    return {
        "status": "success",
        "folder_id": drive_docs.folder_id(),
        "citit_ca": drive_docs.identitate(),
        "count": len(documente),
        "documente": [d.dict() for d in documente],
    }


@mcp.tool()
def citeste_document_drive(
    identificator: Annotated[
        str,
        Field(
            description=(
                "Numele documentului așa cum apare în listare (sau o parte din el), "
                "calea lui, ori id-ul Drive"
            )
        ),
    ],
    de_la: Annotated[int, Field(description="Caracterul de la care se continuă citirea", ge=0)] = 0,
    max_caractere: Annotated[
        int,
        Field(description="Cât text să se întoarcă într-un singur apel", ge=500, le=200_000),
    ] = 20_000,
) -> dict[str, Any]:
    """Citește textul unui document din folderul de referință Drive.

    Merge pe PDF, Google Docs/Sheets/Slides, .docx și text simplu. Un document
    lung se citește pe bucăți: dacă răspunsul are `trunchiat: true`, reia cu
    `de_la` = `urmatorul_offset`.
    """
    try:
        doc, text = drive_docs.citeste(identificator)
    except drive_docs.DriveIndisponibil as exc:
        return {"status": "error", "error_message": str(exc)}
    bucata = text[de_la : de_la + max_caractere]
    sfarsit = de_la + len(bucata)
    return {
        "status": "success",
        "document": doc.cale,
        "id": doc.id,
        "tip": doc.tip,
        "caractere_total": len(text),
        "trunchiat": sfarsit < len(text),
        "urmatorul_offset": sfarsit if sfarsit < len(text) else None,
        "text": bucata,
    }


@mcp.tool()
def cauta_in_documente_drive(
    termen: Annotated[
        str, Field(description="Textul căutat, literal, fără diacritice obligatorii")
    ],
) -> dict[str, Any]:
    """Caută un termen în toate documentele din folderul de referință Drive.

    Întoarce fragmentele din jurul fiecărei apariții, ca să poți răspunde fără
    să citești documentul întreg. Documentele care nu au putut fi citite sunt
    raportate explicit, nu sărite în tăcere.
    """
    try:
        rezultate = drive_docs.cauta(termen)
    except drive_docs.DriveIndisponibil as exc:
        return {"status": "error", "error_message": str(exc)}
    gasite = [r for r in rezultate if "document" in r]
    necitite = next((r["documente_necitite"] for r in rezultate if "documente_necitite" in r), [])
    return {
        "status": "success",
        "termen": termen,
        "documente_cu_potrivire": len(gasite),
        "rezultate": gasite,
        "documente_necitite": necitite,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
