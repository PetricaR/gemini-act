"""Property search and valuation, as agent tools.

`imobiliare_mcp/` is a complete MCP server for imobiliare.ro — search, listing
details, market statistics, and a full valuation under the Romanian standards
(SEV 2025). It is vendored into this package rather than run as a separate
process, so this module is a thin adapter rather than a client: it imports the
tool functions and calls them directly.

That choice is worth stating, because the alternative looks more natural. Run as
a real MCP server it would need its own deployment, and every call would cross a
process boundary and re-pay `tools/list` on each LLM turn — the same latency tax
`config.mcp_cache_ttl_seconds` exists to blunt for the Workspace servers. In
process, a valuation is a function call. Nothing is lost: on MCP SDK 2.x
`@mcp.tool()` returns the plain function, so `server.evaluare` is callable as
itself and the package still runs standalone as an MCP server for anyone who
wants it that way.

Three things this adapter is responsible for:

* **Not blocking the loop.** Everything underneath is synchronous `httpx`, and a
  valuation spends minutes in it. Each tool hops to a worker thread.
* **Keeping the report out of the conversation.** `evalueaza_proprietate`
  produces tens of KB of markdown. It goes to `chat/artifacts.py` and the model
  gets a token plus a summary — see that module for why.
* **Answering in the shape the prompt promises.** Always a dict with `status`,
  never a raised exception, so a failure reads as a failure rather than as an
  agent crash.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from gemini_act.config import get_settings

logger = logging.getLogger(__name__)

# Fields worth showing per listing. The hydrate record carries far more, and
# handing all of it to the model for 20 listings is thousands of tokens of
# tracking metadata it has no use for.
_LISTING_FIELDS = (
    "id",
    "title",
    "url",
    "price_eur",
    "price_per_sqm",
    "surface_sqm",
    "rooms",
    "floor",
    "floors_total",
    "year_built",
    "area",
    "city",
    "metro_distance_m",
    "seller_type",
    "days_on_market",
    "commission_zero",
    "is_new_build",
    "photos",
    "explanation",
)


def _trim(listing: dict[str, Any]) -> dict[str, Any]:
    return {k: listing.get(k) for k in _LISTING_FIELDS if listing.get(k) is not None}


def _failure(action: str, exc: BaseException) -> dict[str, Any]:
    """A raised exception, reported as the failure it is.

    The message is quoted rather than interpreted: the system instruction tells
    the agent to relay tool errors verbatim and not to guess at causes, which
    only works if what arrives here is the real error text.
    """
    logger.exception("%s failed", action)
    return {
        "status": "error",
        "error_message": f"{action} failed: {type(exc).__name__}: {exc}",
    }


def _disabled() -> dict[str, Any]:
    return {
        "status": "error",
        "error_message": (
            "Property tools are disabled on this deployment "
            "(GEMINI_ACT_IMOBILIARE_ENABLED=false)."
        ),
    }


async def cauta_proprietati(
    query: str,
    pret_max: int | None = None,
    pret_min: int | None = None,
    camere: int | None = None,
    suprafata_min: float | None = None,
    metrou_max_m: float | None = None,
    zona: str | None = None,
    doar_proprietari: bool = False,
    sort: str = "metro",
    limit: int = 15,
) -> dict[str, Any]:
    """Search imobiliare.ro listings by a natural-language description.

    Describe what the user wants in `query` and put every hard number in the
    named arguments — the search layer interprets intent but does not enforce
    limits, so a price cap written only in the query text will not be applied.

    This is the one property tool that needs a captured browser session and it
    expires within minutes, so it fails more often than it works. When it does
    fail, say so and offer `evalueaza_proprietate` on a specific listing instead,
    which needs no session at all.

    Args:
        query: What the user is looking for, Romanian or English, e.g.
            "apartament 3 camere Titan, bloc nou, aproape de metrou".
        pret_max: Maximum price in EUR.
        pret_min: Minimum price in EUR.
        camere: Exact number of rooms.
        suprafata_min: Minimum usable surface in square metres.
        metrou_max_m: Maximum walking distance to a metro station, in metres.
        zona: Neighbourhood substring, e.g. "Drumul Taberei", "Dristor".
        doar_proprietari: Only listings posted directly by owners, no agencies.
        sort: One of "metro", "price", "price_desc", "price_per_sqm", "surface",
            "newest", "year_built", "relevance".
        limit: Maximum listings to return, 1-50.

    Returns:
        A dict with "status", and on success "listings", "matched",
        "resume_token" (pass to statistici_piata) and the assistant's own reply;
        on error an "error_message".
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import Filters, cauta

        filters = Filters(
            pret_max=pret_max,
            pret_min=pret_min,
            camere=camere,
            suprafata_min=suprafata_min,
            metrou_max_m=metrou_max_m,
            zona=zona,
            tip_vanzator="individual" if doar_proprietari else None,
        )
        return cauta(query=query, filtre=filters, sort=sort, limit=max(1, min(limit, 50)))

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001 - every failure is reported, never raised
        return _failure("Property search", exc)

    if error := result.get("error"):
        return {
            "status": "error",
            "error_message": (
                f"{error} Search needs a browser-captured session that expires within "
                "minutes. Valuation and listing details do not — offer those instead."
            ),
        }
    return {
        "status": "success",
        "assistant_reply": result.get("assistant_reply"),
        "total_hits_before_filters": result.get("total_hits_before_filters"),
        "matched": result.get("matched"),
        "resume_token": result.get("resume_token"),
        "listings": [_trim(x) for x in result.get("listings") or []],
    }


async def reia_cautare(
    token: str,
    pret_max: int | None = None,
    pret_min: int | None = None,
    camere: int | None = None,
    suprafata_min: float | None = None,
    metrou_max_m: float | None = None,
    sort: str = "metro",
    limit: int = 20,
) -> dict[str, Any]:
    """Reia o căutare anterioară folosind un resume_token, aplicând noi filtre sau sortare.

    Tokenurile de căutare rămân valide chiar și după expirarea sesiunii, permițând
    rafinarea rezultatelor sau paginarea fără o nouă sesiune de căutare.

    Args:
        token: Un 'resume_token' returnat de un apel anterior cauta_proprietati.
        pret_max: Preț maxim în EUR.
        pret_min: Preț minim în EUR.
        camere: Număr exact de camere.
        suprafata_min: Suprafață utilă minimă în mp.
        metrou_max_m: Distanță maximă pe jos până la metrou (metri).
        sort: Criteriu de sortare: 'metro', 'price_asc', 'price_desc', 'surface_desc', 'relevance'.
        limit: Număr maxim de anunțuri returnate (implicit 20).

    Returns:
        Un dict cu 'status', număr de rezultate găsite și lista de anunțuri filtrate.
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import Filters, reia

        filtre = Filters(
            pret_max=pret_max,
            pret_min=pret_min,
            camere=camere,
            suprafata_min=suprafata_min,
            metrou_max_m=metrou_max_m,
        )
        return reia(token=token, filtre=filtre, sort=sort, limit=limit)  # type: ignore[arg-type]

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Resume search", exc)

    return {
        "status": "success",
        "total_hits": result.get("total_hits"),
        "matched": result.get("matched"),
        "returned": result.get("returned"),
        "listings": [_trim(x) for x in result.get("listings") or []],
    }


async def detalii_proprietate(identificatori: list[str]) -> dict[str, Any]:
    """Fetch full details for specific imobiliare.ro listings.

    Needs no session, so this always works. Accepts bare listing ids or full
    offer URLs — the trailing number of an imobiliare.ro offer URL is its id.

    Args:
        identificatori: Listing ids or offer URLs, e.g. ["275966742"] or
            ["https://www.imobiliare.ro/oferta/...-275966742"].

    Returns:
        A dict with "status", and on success "listings"; on error an
        "error_message".
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import _resolve_id, detalii

        return detalii(ids=[_resolve_id(x) for x in identificatori])

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Listing lookup", exc)
    return {
        "status": "success",
        "count": result.get("count", 0),
        "listings": [_trim(x) for x in result.get("listings") or []],
    }


async def statistici_piata(token: str, camere: int | None = None) -> dict[str, Any]:
    """Summarise a market segment from an earlier search: price distribution,
    and the breakdown by area, seller type and building age.

    Use this to establish what a fair price per square metre is before looking
    at individual listings.

    Args:
        token: A "resume_token" returned by an earlier cauta_proprietati call.
        camere: Narrow the summary to listings with exactly this many rooms.

    Returns:
        A dict with "status", and on success the price/surface/age spreads and
        the segment breakdown; on error an "error_message".
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import Filters, statistici

        return statistici(token=token, filtre=Filters(camere=camere))

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Market statistics", exc)
    return {"status": "success", **result}


async def evalueaza_proprietate(
    identificator: str,
    comparabile: int = 0,
    cu_viziune: bool = True,
    cu_localizare: bool = True,
) -> dict[str, Any]:
    """Value one apartment against the Romanian valuation standards, and write
    the full report.

    Give it a listing id or an imobiliare.ro offer URL. It pulls the subject and
    a comparable set from the published sitemaps — no session needed, so this
    works when search does not — then runs the sales-comparison grid of GEV 630
    §54-58 with size and floor adjustments regressed out of the comparable set
    itself, cross-checks it against a direct-capitalisation income approach, and
    writes a markdown report structured on SEV 106 §30.6.

    With `cu_viziune` on it also *looks at the property*: the listing gallery, a
    Street View image of the block, and a map of the area go to a vision model,
    and what it sees is filed in the report under the physical characteristics.
    That is the only evidence about condition available without an inspection.

    This is slow — one to three minutes — because it hydrates a comparable pool,
    geocodes, queries amenities and reads the photographs. Tell the user it is
    running before you call it, and do not call it speculatively on several
    listings at once.

    It never claims conformity with the standards: with no inspection, no title
    check and no ANEVAR-authorised valuer, SEV 106 §30.8 forbids that claim. Say
    so when you present the result — it is a decision aid for a buyer, not a
    valuation report.

    Args:
        identificator: Listing id or full offer URL, e.g. "275807510".
        comparabile: How many comparables to carry into the grid, 3-30. Leave 0
            for the configured default.
        cu_viziune: Have a vision model examine the photographs, the Street View
            image and the area map. Turn off only if the user asks for numbers
            alone; it is most of the value of the report.
        cu_localizare: Geocode the address and list nearby schools, shops, parks
            and transport with their distances.

    Returns:
        A dict with "status", and on success the estimated value, the gap to the
        asking price, the visual condition verdict, and "raport_atasament" — a
        token for the full report. To send that report to the user, end your
        answer with the attachment marker and the JSON
        {"artifactId": "<that token>"}; do not try to reproduce the report text
        yourself. On error an "error_message".
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import evaluare

        return evaluare(
            identificator=identificator,
            comparabile=comparabile or settings.imobiliare_comparables,
            cu_viziune=cu_viziune,
            cu_localizare=cu_localizare,
            raza_facilitati=settings.maps_amenity_radius_m,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Property valuation", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    summary = {k: v for k, v in result.items() if k != "raport"}
    summary["status"] = "success"

    # The report itself goes to the artifact store, not into this dict: it is
    # tens of KB of markdown, and the model needs to be able to *send* it, not
    # to read it back.
    path = result.get("raport")
    if path:
        try:
            data = await asyncio.to_thread(lambda: open(path, "rb").read())
            from gemini_act.chat.artifacts import put

            summary["raport_atasament"] = put(
                f"evaluare-{result.get('id')}.md", "text/markdown", data
            )
            summary["raport_marime_bytes"] = len(data)
        except OSError:
            logger.exception("Could not stage the report at %s", path)
            summary["raport_atasament"] = None
            summary["nota_raport"] = (
                "The valuation ran, but its report file could not be read back, "
                "so there is nothing to attach. The figures above still stand."
            )
    return summary


async def inspecteaza_vizual_proprietate(
    identificator: str,
    intrebare: str,
) -> dict[str, Any]:
    """Inspectează fotografiile unui anunț imobiliar și răspunde la o întrebare specifică.

    Folosește modelul multimodal Gemini 3.8 Flash pentru a analiza finisajele,
    lumina naturală, compartimentarea, vederea sau starea instalațiilor.

    Args:
        identificator: ID-ul anunțului (ex: '20235478') sau URL-ul complet al ofertei.
        intrebare: Întrebarea sau cerința analizei (ex: 'Cum arată baia și bucătăria?',
            'Există urme de igrasie sau finisaje degradate?').

    Returns:
        Răspunsul analizei vizuale, numărul de fotografii inspectate și link-uri foto.
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import inspecteaza_poze

        return inspecteaza_poze(identificator=identificator, intrebare=intrebare)

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Visual inspection", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


async def analizeaza_mobilier_si_finisaje(
    identificator: str,
    limita_fotografii: int = 20,
) -> dict[str, Any]:
    """Analizează fotografiile unui apartament cu Gemini 3.8 Flash pentru a identifica
    mobilierul, electrocasnicele și finisajele, evaluând calitatea, starea și costurile.

    Extrage un inventar structurat pe camere, evaluează clasa de calitate
    (economic, mediu, premium, lux), notează finisajele și mobilierul de la 1 la 10
    și estimează valoarea dotărilor și un buget orientativ de renovare/înlocuiri.

    Args:
        identificator: ID-ul anunțului (ex: '20235478') sau URL-ul complet al ofertei.
        limita_fotografii: Numărul maxim de fotografii descărcate și inspectate (implicit 20).

    Returns:
        Inventarul complet structurat, scorurile de calitate, punctele forte/slabe
        și rezumatul detaliat în format Markdown.
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            analizeaza_mobilier_si_finisaje as server_tool,
        )

        return server_tool(identificator=identificator, limita_fotografii=limita_fotografii)

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Furniture and finishes analysis", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


IMOBILIARE_TOOLS = [
    cauta_proprietati,
    reia_cautare,
    detalii_proprietate,
    statistici_piata,
    evalueaza_proprietate,
    inspecteaza_vizual_proprietate,
    analizeaza_mobilier_si_finisaje,
]


