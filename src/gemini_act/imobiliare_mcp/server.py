"""MCP server exposing imobiliare.ro's AI property search.

Run with:  imobiliare-mcp     (or: python -m imobiliare_mcp.server)
"""

from __future__ import annotations

import os
import re
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

from . import comps, locatie, maps, viziune
from .anevar import Params, evaluate, is_furnished
from .client import ImobiliareClient, SessionError
from .galerie import contact_sheet
from .parse import filter_and_rank, normalise
from .raport import render

mcp = MCPServer("imobiliare")

SellerType = Literal["agency", "individual", "developer"]
SortBy = Literal["metro", "price", "price_desc", "price_per_sqm", "surface", "newest", "year_built", "relevance"]


class Filters(BaseModel):
    """Hard constraints applied locally to the real listing data.

    The AI layer handles intent; these enforce the numbers. A listing whose
    value for a constrained field is missing is dropped, not kept.
    """

    # money
    pret_max: int | None = Field(None, description="Maximum price in EUR")
    pret_min: int | None = Field(None, description="Minimum price in EUR")
    pret_mp_max: int | None = Field(None, description="Maximum price per usable sqm, in EUR")
    pret_redus: bool | None = Field(None, description="Only listings whose price was recently reduced")

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
    metrou_max_m: float | None = Field(None, description="Max walking distance to a metro station, in metres. The AI cannot resolve 'near the metro' itself, so use this.")
    zona: str | None = Field(None, description="Neighbourhood substring, e.g. 'Drumul Taberei', 'Dristor'")
    oras: str | None = Field(None, description="City or sector substring, e.g. 'Sector 3'")
    doar_locatie_exacta: bool = Field(False, description="Only listings with an exact (not approximate) map location")

    # seller and offer
    tip_vanzator: SellerType | None = Field(None, description="'individual' = direct from owner, 'agency', 'developer'")
    comision_zero: bool | None = Field(None, description="Only listings with zero buyer commission")
    exclusivitate: bool | None = Field(None, description="Only exclusive listings")
    constructie_noua: bool | None = Field(None, description="Only new builds (True) or only established (False)")

    # freshness and media
    zile_pe_piata_max: int | None = Field(None, description="Max days the listing has been on the market")
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
def cauta(
    query: Annotated[str, Field(description="Natural-language query, Romanian or English, e.g. 'apartament 3 camere Bucuresti'. Describe intent here; put numeric limits in `filtre`.")],
    filtre: Filters | None = None,
    sort: Annotated[SortBy, Field(description="Ordering of the results")] = "metro",
    limit: Annotated[int, Field(description="Maximum listings to return", ge=1, le=200)] = 20,
    pool: Annotated[int, Field(description="How many AI-ranked results to pull before filtering. Raise it when strict filters leave too few matches.", ge=60, le=600)] = 240,
) -> dict[str, Any]:
    """Search imobiliare.ro by description and return matching properties.

    Returns a `resume_token` -- pass it to `reia` to re-filter the same result
    set later without spending a session.
    """
    filters = filtre or Filters()
    with _client() as client:
        try:
            result = client.search(query, max_results=pool)
        except SessionError as e:
            return {"error": str(e), "hint": "See README: capturing a session_id."}

    records = [normalise(listing, result.explanations.get(listing.get("id"))) for listing in result.listings]
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
    pool: Annotated[int, Field(description="How many results to pull before filtering", ge=60, le=600)] = 240,
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
    ids: Annotated[list[str], Field(description="Listing ids, e.g. ['275966742']. The trailing number of an imobiliare.ro offer URL is the id.")],
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
        [normalise(listing) for listing in result.listings], sort_by="relevance", **filters.as_kwargs()
    )
    if not records:
        return {"matched": 0, "note": "No listings matched; loosen the filters."}

    def spread(field: str) -> dict[str, Any] | None:
        vals = sorted(r[field] for r in records if r[field] is not None)
        if not vals:
            return None
        return {
            "min": vals[0], "max": vals[-1],
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


class ParametriEvaluare(BaseModel):
    """Valuation inputs. Every one is argued in the report (GEV 630 §71), and
    every one can be overridden -- these are market conventions, not laws."""

    marja_negociere_baza: float = Field(3.0, description="Base discount from asking to transaction price, %", ge=0, le=25)
    marja_negociere_per_30_zile: float = Field(0.5, description="Extra negotiation margin per 30 days of exposure, %", ge=0, le=5)
    marja_negociere_plafon: float = Field(12.0, description="Cap on the negotiation margin, %", ge=0, le=30)
    valoare_parcare: float = Field(12000.0, description="Market value of a parking space, EUR", ge=0)
    valoare_mobilier: float = Field(8000.0, description="Market value of furnishing, EUR", ge=0)
    grad_neocupare: float = Field(8.0, description="Vacancy and collection loss, % of potential gross income (GEV 630 §69)", ge=0, le=50)
    cheltuieli_operare: float = Field(18.0, description="Owner's non-recoverable expenses, % of effective gross income (GEV 630 §70)", ge=0, le=60)
    rata_capitalizare: float = Field(6.0, description="Capitalisation rate, %", gt=0, le=20)
    spor_an_pe_an: float = Field(0.45, description="Value premium per year of newness, %", ge=0, le=3)
    plafon_spor_an: float = Field(20.0, description="Cap on the age adjustment, %", ge=0, le=60)
    discount_metrou_max: float = Field(8.0, description="Discount at 1500 m from a metro station, %", ge=0, le=30)
    spor_bloc_nou: float = Field(4.0, description="New-build premium, %", ge=0, le=30)
    prag_descalificare: float = Field(35.0, description="Gross adjustment above which a comparable is disqualified, % (GEV 630 §57)", ge=10, le=100)
    pondere_piata: float = Field(80.0, description="Weight of the sales-comparison approach, %", ge=0, le=100)
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


def _reports_dir() -> Path:
    """Where reports are written.

    Cloud Run's filesystem is read-only apart from /tmp, and `Path.home()` there
    is not writable — so an explicit override wins, then the home directory when
    it is genuinely writable (a developer's machine), then a temp directory.
    The report is delivered to the user as a Chat attachment either way; this
    path is where it is staged, not where it is kept.
    """
    if override := os.environ.get("IMOBILIARE_REPORTS_DIR"):
        return Path(override)
    home = Path.home() / "imobiliare-rapoarte"
    if os.access(Path.home(), os.W_OK):
        return home
    import tempfile

    return Path(tempfile.gettempdir()) / "imobiliare-rapoarte"


@mcp.tool()
def evaluare(
    identificator: Annotated[str, Field(description="Listing id or full imobiliare.ro offer URL, e.g. '275807510'")],
    comparabile: Annotated[int, Field(description="How many comparables to carry into the grid", ge=3, le=30)] = 12,
    parametri: ParametriEvaluare | None = None,
    fisier: Annotated[str | None, Field(description="Where to write the markdown report. Defaults to $IMOBILIARE_REPORTS_DIR/evaluare-<id>.md")] = None,
    cu_localizare: Annotated[bool, Field(description="Geocode the address and list nearby schools, shops, parks and transport")] = True,
    raza_facilitati: Annotated[int, Field(description="Radius for the amenity search, metres", ge=300, le=3000)] = 1200,
    cu_galerie: Annotated[bool, Field(description="Download the listing photos into one contact sheet next to the report")] = True,
    observatii_vizuale: Annotated[str | None, Field(description="Your own findings from looking at the photos, in markdown, filed alongside the automated analysis rather than replacing it. Usually unnecessary — leave it empty and let `cu_viziune` do the looking.")] = None,
    cu_viziune: Annotated[bool, Field(description="Have a vision model look at the listing photos, the Street View image of the block and the area map, and file what it sees in the report. This is what makes the report's visual section real rather than empty.")] = True,
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
            return {"error": f"Anunțul {listing_id} nu a putut fi găsit sau nu mai este activ."}
        subject = normalise(raw[0])

        area = comps.area_slug_of(subject.get("url") or "")
        if not area:
            return {"error": "Nu pot deduce zona din URL-ul anunțului.", "subject": subject}
        scope = comps.scope_for(subject.get("county"), subject.get("city"))
        rooms = subject.get("rooms")

        sale_pool = comps.candidates(area, rooms, scope, "sale", exclude=listing_id)
        rent_pool = comps.candidates(area, rooms, scope, "rent")
        if not sale_pool:
            return {"error": f"Nicio comparabilă în zona '{area}' cu {rooms} camere.", "subject": subject}

        sale_records = [normalise(listing) for listing in client.hydrate([o.id for o in sale_pool[:120]])]
        rent_records = [normalise(listing) for listing in client.hydrate([o.id for o in rent_pool[:60]])] if rent_pool else []

    usable = [r for r in sale_records if r.get("price_eur") and r.get("surface_sqm")]
    chosen = comps.rank_by_similarity(subject, usable)[:comparabile]
    if not chosen:
        return {"error": "Comparabilele găsite nu au preț și suprafață utilizabile.", "subject": subject}

    subject_furnished = is_furnished(subject, slug_hint="-mobilat-" in (subject.get("url") or ""))
    valuation = evaluate(subject, chosen, rent_records, p,
                         subject_furnished=subject_furnished, rate_pool=usable)
    if not valuation.comps:
        return {"error": "Toate comparabilele au fost descalificate prin ajustări excesive. "
                         "Crește `prag_descalificare` sau `comparabile`.", "subject": subject}

    place = vecinatati = None
    if cu_localizare:
        place = locatie.geocode(subject.get("address_text") or subject.get("location"),
                                subject.get("location"))
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

    markdown = render(
        valuation,
        comps_source=f"sitemap imobiliare.ro, aria '{area}', {len(usable)} oferte active cu preț și suprafață",
        rents_source=(f"sitemap închirieri, aria '{area}', {valuation.income.sample} oferte"
                      if valuation.income.sample else "insuficiente oferte de închiriere"),
        place=place, vecinatati=vecinatati,
        sheet=sheet_file,
        observatii_vizuale=observatii_vizuale,
        viziune=findings,
        street_view_file=sv_file,
        static_map_file=map_file,
        scor_accesibilitate=scor_acces,
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
        "valoare_unitara_estimata_eur_mp": round(valuation.market_per_sqm) if valuation.market_per_sqm else None,
        "pret_unitar_cerut_eur_mp": subject.get("price_per_sqm"),
        "interval_valori_eur_mp": ([round(valuation.value_range[0]), round(valuation.value_range[1])]
                                   if valuation.value_range else None),
        "abordare_piata_eur": round(valuation.market_value) if valuation.market_value else None,
        "abordare_venit_eur": round(valuation.income.value) if valuation.income.value else None,
        "randament_net_implicit_pct": round(valuation.implied_yield, 2) if valuation.implied_yield else None,
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
        "facilitati": ({k: [{"nume": i.name, "m": i.distance_m} for i in v[:5]]
                        for k, v in vecinatati.pois.items() if v} if vecinatati else None),
        "fiabilitate": valuation.reliability,
        "extrapolare_suprafata": valuation.extrapolated,
        "comparabile_retinute": len(valuation.comps),
        "comparabile_excluse": len(valuation.excluded),
        "conformitate_sev": "nu se afirmă (SEV 106 §30.8)",
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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
