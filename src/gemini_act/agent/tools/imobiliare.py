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


def _imo360_disabled() -> dict[str, Any]:
    return {
        "status": "error",
        "error_message": (
            "The imo360 source is disabled on this deployment (GEMINI_ACT_IMO360_ENABLED=false)."
        ),
    }


def _imoradar_disabled() -> dict[str, Any]:
    return {
        "status": "error",
        "error_message": (
            "The imoradar24 source is disabled on this deployment "
            "(GEMINI_ACT_IMORADAR_ENABLED=false)."
        ),
    }


def _disabled() -> dict[str, Any]:
    return {
        "status": "error",
        "error_message": (
            "Property tools are disabled on this deployment (GEMINI_ACT_IMOBILIARE_ENABLED=false)."
        ),
    }


async def cauta_imobiliare_obscura(
    query: str,
    pret_max: int | None = None,
    pret_min: int | None = None,
    camere: int | None = None,
    suprafata_min: float | None = None,
    metrou_max_m: float | None = None,
    zona: str | None = None,
    oras: str | None = None,
    doar_proprietari: bool = False,
    sort: str = "metro",
    limit: int = 15,
    url: str | None = None,
    eval_js: str | None = None,
) -> dict[str, Any]:
    """Search imobiliare.ro or inspect web listings using the Obscura headless browser.

    Unlike the legacy AI search, this tool does NOT rely on temporary browser
    sessions and does not expire. It can run natural language searches, filter
    listings by price/rooms/metro, or directly inspect an imobiliare.ro URL.

    Args:
        query: What the user is looking for, Romanian or English, e.g.
            "apartament 2 camere Titan sub 90000 euro".
        pret_max: Maximum price in EUR.
        pret_min: Minimum price in EUR.
        camere: Exact number of rooms.
        suprafata_min: Minimum usable surface in square metres.
        metrou_max_m: Maximum walking distance to a metro station, in metres.
        zona: Neighbourhood substring, e.g. "Titan", "Floreasca", "Dristor".
        oras: City or sector substring, e.g. "București", "Sector 3".
        doar_proprietari: Only listings posted directly by owners, no agencies.
        sort: One of "metro", "price", "price_desc", "price_per_sqm", "surface",
            "newest", "year_built", "relevance".
        limit: Maximum listings to return, 1-50.
        url: Optional direct imobiliare.ro URL to fetch and inspect via Obscura.
        eval_js: Optional JavaScript code to evaluate in page context (via Obscura --eval).

    Returns:
        A dict with status, listings, assistant reply, and metadata.
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.obscura import ObscuraBrowser, search_imobiliare_obscura
        from gemini_act.imobiliare_mcp.server import Filters

        # Direct URL inspection via Obscura
        if url:
            browser = ObscuraBrowser()
            res = browser.fetch(
                url=url,
                eval_js=eval_js or "document.title",
                stealth=True,
                wait_until="domcontentloaded",
                wait=3,
            )
            return {
                "engine": "obscura_fetch",
                "page_url": url,
                "title": res.title or res.output,
                "output": res.output,
                "success": res.success,
                "error": res.error,
                "data": res.data,
            }

        filters = Filters(
            pret_max=pret_max,
            pret_min=pret_min,
            camere=camere,
            suprafata_min=suprafata_min,
            metrou_max_m=metrou_max_m,
            zona=zona,
            oras=oras,
            tip_vanzator="individual" if doar_proprietari else None,
        )
        return search_imobiliare_obscura(
            query=query,
            filters=filters,
            sort=sort,  # type: ignore[arg-type]
            limit=max(1, min(limit, 50)),
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Obscura property search", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": str(error)}

    return {
        "status": "success",
        "engine": result.get("engine", "obscura"),
        "assistant_reply": result.get("assistant_reply"),
        "total_hits_before_filters": result.get("total_hits_before_filters"),
        "matched": result.get("matched"),
        "listings": [_trim(x) for x in result.get("listings") or []],
        "page_url": result.get("page_url"),
        "output": result.get("output"),
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

    Uses AI search when an active browser session exists, and automatically
    falls back to the autonomous Obscura search engine when temporary browser
    sessions expire.

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

    if result.get("error"):
        # Auto-fallback to Obscura search engine
        return await cauta_imobiliare_obscura(
            query=query,
            pret_max=pret_max,
            pret_min=pret_min,
            camere=camere,
            suprafata_min=suprafata_min,
            metrou_max_m=metrou_max_m,
            zona=zona,
            doar_proprietari=doar_proprietari,
            sort=sort,
            limit=limit,
        )
    return {
        "status": "success",
        "assistant_reply": result.get("assistant_reply"),
        "total_hits_before_filters": result.get("total_hits_before_filters"),
        "matched": result.get("matched"),
        "resume_token": result.get("resume_token"),
        "listings": [_trim(x) for x in result.get("listings") or []],
        "session_warning": result.get("session_warning"),
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


async def strategie_negociere(
    identificator: str,
    buget_total_max: float = 0,
    deviz_renovare: float = 0,
    prin_agentie: bool = False,
) -> dict[str, Any]:
    """Turn a valuation into an offer: what to bid, what to expect back, and when
    to walk away.

    Runs the valuation first, then builds the offer ladder on top of it: the
    opening offer and what anchors it, the counter the seller is likely to make,
    the target, the ceiling, and the price above which the purchase is abandoned.
    It also reads the seller's likely position from signals the listing already
    carries — developer or agency, how long it has been listed, whether the price
    has already been cut, whether the flat is empty — and turns the defects seen
    in the photographs into euro amounts with the sentence that argues each one.

    The ranges are market practice for the Bucharest residential segment, not
    measurements of this property, and the result says so on every figure. Present
    them that way. Nothing here changes the estimated value.

    It returns three written offers as text. They are drafts for the user to
    review and send themselves — never present one as already sent.

    Args:
        identificator: Listing id or full offer URL, e.g. "275807510".
        buget_total_max: The buyer's total budget in EUR, covering price, fees,
            renovation and furnishing. When given it caps the walk-away price
            independently of what the property is worth. 0 to leave it out.
        deviz_renovare: A known repair estimate in EUR. 0 to derive it from the
            defects the vision pass finds.
        prin_agentie: Whether the buyer would owe an agency commission.

    Returns:
        A dict with "status", and on success the ladder, the seller profile, the
        price levers, the red flags that need checking, the consolidated budget
        and the draft offers. On error an "error_message".
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import strategie_negociere as _strategie

        return _strategie(
            identificator=identificator,
            buget_total_max=buget_total_max or None,
            deviz_renovare=deviz_renovare or None,
            prin_agentie=prin_agentie,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Negotiation strategy", exc)

    if result.get("disponibil") is False:
        return {
            "status": "error",
            "error_message": result.get("motiv", "Strategia nu a putut fi calculată."),
        }
    return {"status": "success", **result}


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


async def analizeaza_dezvoltator_si_constructor(
    identificator_sau_nume: str,
    context_suplimentar: str | None = None,
) -> dict[str, Any]:
    """Analizează profilul dezvoltatorului imobiliar și al constructorului / antreprenorului
    general pentru un imobil nou sau ansamblu rezidențial.

    Evaluează istoricul de proiecte finalizate, reputația pe piață, calitatea lucrărilor
    executate, comportamentul privind termenele de predare (întârzieri), situația autorizațiilor
    și branșamentelor la utilități definitive, precum și scorul de încredere (1-10).

    Args:
        identificator_sau_nume: ID-ul anunțului (ex: '275807510'), URL-ul ofertei imobiliare.ro,
            sau numele direct al ansamblului / dezvoltatorului (ex: 'One Floreasca Towers').
        context_suplimentar: Informații sau întrebări contextuale suplimentare opționale.

    Returns:
        Date structurate despre dezvoltator, constructor, stadiu, riscuri și raport Markdown.
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            analizeaza_dezvoltator_si_constructor as server_tool,
        )

        return server_tool(
            identificator_sau_nume=identificator_sau_nume,
            context_suplimentar=context_suplimentar,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Developer and builder analysis", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


async def analizeaza_materiale_si_specificatii_tehnice(
    identificator_sau_nume: str,
    include_fotografii: bool = True,
    limita_fotografii: int = 15,
) -> dict[str, Any]:
    """Realizează un audit tehnic al materialelor de construcție folosite la un imobil nou.

    Analizează structura de rezistență (cadre beton armat, radier, P100-1), zidăria și
    izolația fonică (cărămidă termoizolantă vs BCA), fațada și termoizolația (vată bazaltică
    vs polistiren, nZEB), tâmplăria exterioară (tripan Low-E), instalațiile (încălzire în
    pardoseală, pompe de căldură) și finisajele spațiilor comune, acordând un scor tehnic (1-10).

    Args:
        identificator_sau_nume: ID-ul anunțului, URL-ul ofertei sau numele proiectului rezidențial.
        include_fotografii: Dacă să inspecteze și fotografiile disponibile pentru validarea vizuală.
        limita_fotografii: Numărul maxim de fotografii inspectate (implicit 15).

    Returns:
        Fișa tehnică structurată pe capitole de construcție, puncte forte, potențiale
        compromisuri tehnice (cost-cutting) și raport complet Markdown.
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            analizeaza_materiale_si_specificatii_tehnice as server_tool,
        )

        return server_tool(
            identificator_sau_nume=identificator_sau_nume,
            include_fotografii=include_fotografii,
            limita_fotografii=limita_fotografii,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Construction materials audit", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


async def checklist_receptie_imobil_nou(
    etapa: str = "receptie_finala",
    detalii_proiect: str | None = None,
) -> dict[str, Any]:
    """Generează un ghid și checklist practic de verificare pentru cumpărători la achiziția
    și recepția unui apartament într-un imobil nou.

    Acoperă 3 etape cheie:
    - 'antecontract': verificare acte proprietate, autorizație, utilități definitive;
    - 'stadiu_constructie': verificări pe șantier, procese verbale lucrări ascunse;
    - 'receptie_finala': predare-primire, planeitate șape, unghiuri pereți, etanșeitate tâmplărie,
      presiune instalații sanitare, tablou electric, utilități individuale și garanții legale.

    Args:
        etapa: Etapa achiziției ('antecontract', 'stadiu_constructie' sau 'receptie_finala').
        detalii_proiect: Opțional, dotări specifice ale proiectului pentru personalizare.

    Returns:
        Checklist structurat pe categorii, capcane frecvente, garanții legale și raport Markdown.
    """
    if not get_settings().imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            checklist_receptie_imobil_nou as server_tool,
        )

        return server_tool(
            etapa=etapa,
            detalii_proiect=detalii_proiect,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("New build handover checklist", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


async def analizeaza_strada_si_imprejurimi_street_view(
    adresa_sau_identificator: str,
    include_satelit: bool = True,
) -> dict[str, Any]:
    """Capturează și analizează imagini Google Street View 360° și imagini satelitare
    de înaltă rezoluție pentru o adresă sau anunț imobiliar cu Gemini 3.8 Flash.

    Evaluează fațada reală a clădirii, starea tencuielii, izolația exterioară, balcoanele,
    trotuarele, parcarea (inclusiv mașini pe trotuar), cablurile aeriene, ambientul urban
    și distanța de intimitate față de vecini din satelit.

    Args:
        adresa_sau_identificator: Adresă completă (ex: 'Calea Floreasca 160, Bucuresti'),
            coordonate ('44.46, 26.10'), ID anunț (ex: '275807510') sau URL complet imobiliare.ro.
        include_satelit: Dacă se include și analiza vederii aeriene din satelit (implicit True).
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            analizeaza_strada_si_imprejurimi_street_view as server_tool,
        )

        return server_tool(
            adresa_sau_identificator=adresa_sau_identificator,
            include_satelit=include_satelit,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Street view and surroundings analysis", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


async def analizeaza_bonitate_dezvoltator_targetare(
    cui_sau_nume: str,
) -> dict[str, Any]:
    """Efectuează due diligence financiar și analiză de bonitate/risc de insolvență
    pentru un dezvoltator imobiliar sau constructor folosind baza Targetare.ro.

    Interoghează datele oficiale de bilanț (cifră de afaceri, profit net, datorii totale,
    capitaluri proprii, număr de angajați, cod CAEN, stare activ/insolvent/radiat) și
    calculează un scor de stabilitate financiară (1-10) cu recomandări pentru cumpărător.

    Args:
        cui_sau_nume: Codul de identificare fiscală (CUI / CIF) sau denumirea companiei.
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            analizeaza_bonitate_dezvoltator_targetare as server_tool,
        )

        return server_tool(cui_sau_nume=cui_sau_nume)

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Targetare financial due diligence", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


async def recenzii_reputatie_google_maps(
    nume_sau_adresa_sau_place_id: str,
) -> dict[str, Any]:
    """Obține recenzii Google Maps pentru un ansamblu rezidențial, birou de vânzări dezvoltator
    sau adresă și realizează un audit de reputație și sentiment cu Gemini 3.8 Flash.

    Extrage ratingul mediu, volumul de recenzii, problemele reclamate frecvent de locatari
    (întârzieri la predare, infiltrații, izolație fonică deficitară, parcări insuficiente)
    și punctele forte apreciate.

    Args:
        nume_sau_adresa_sau_place_id: Nume ansamblu, brand dezvoltator, adresă sau Google Place ID.
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            recenzii_reputatie_google_maps as server_tool,
        )

        return server_tool(nume_sau_adresa_sau_place_id=nume_sau_adresa_sau_place_id)

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Google Maps reviews reputation audit", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


async def genereaza_raport_complet_pdf(
    adresa_sau_identificator: str,
    date_suplimentare_json: str = "",
    cale_salvare: str = "",
) -> dict[str, Any]:
    """Generează un dosar complet de audit și evaluare imobiliară în format PDF profesional,
    respectând cu strictețe ghidul de tehnoredactare și design Google Docs.

    Include evaluare ANEVAR (GEV 630), audit vizual mobilier și finisaje, inspecție Street View 360°
    și satelit, specificații dezvoltator, analiză financiară Targetare.ro, recenzii Google Maps
    și checklist tehnic de recepție.

    Args:
        adresa_sau_identificator: ID anunț, URL complet imobiliare.ro sau adresă proprietate.
        date_suplimentare_json: JSON opțional cu rezultatele uneltelor pre-colectate de agent.
        cale_salvare: Cale personalizată de salvare pentru fișierul PDF (opțional).
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            genereaza_raport_complet_pdf as server_tool,
        )

        return server_tool(
            adresa_sau_identificator=adresa_sau_identificator,
            date_suplimentare_json=date_suplimentare_json,
            cale_salvare=cale_salvare,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Complete PDF report generation", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    # `date_audit` is the whole dossier -- tens of KB of nested findings that the
    # PDF renders and the model has no use for. It is replaced by a list of the
    # sections that produced something, so the answer can say what the report
    # covers without carrying it.
    dosar = result.pop("date_audit", None) or {}
    sectiuni = [
        cheie
        for cheie, valoare in dosar.items()
        if isinstance(valoare, dict) and valoare.get("disponibil") is not False
    ]
    return {
        "status": "success",
        **result,
        "sectiuni_disponibile": sectiuni,
        "scor_general": dosar.get("scor_general"),
        "calificativ_general": dosar.get("calificativ_general"),
        "rezumat_executiv": dosar.get("rezumat_executiv"),
    }


async def analizeaza_electrocasnice_si_defecte_finisaje(
    identificator_proprietate: str,
    limita_fotografii: int = 20,
) -> dict[str, Any]:
    """Examinează fotografiile proprietății cu Gemini 3.8 Flash Vision pentru a:
    1. Recunoaște aparatele electrocasnice (frigider, cuptor, plită, hotă, mașină spălat, AC, TV).
    2. Identifica brandul (Miele, Bosch, etc.) și gama (Economic/Mid-range/Premium/Ultra-Lux).
    3. Estima prețul de nou pe piața din România (EUR/RON) și valoarea reziduală actuală.
    4. Genera link-uri directe de căutare online (eMAG, Altex, Google Shopping).
    5. Audita defectele finisajelor (fisuri, infiltrații, plăci ciobite, parchet umflat,
       plinte lipsă, mucegai) cu severitate și buget de remediere.

    Args:
        identificator_proprietate: ID anunț sau URL complet imobiliare.ro.
        limita_fotografii: Număr maxim de imagini analizate (implicit 20).
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import (
            analizeaza_electrocasnice_si_defecte_finisaje as server_tool,
        )

        return server_tool(
            identificator_proprietate=identificator_proprietate,
            limita_fotografii=limita_fotografii,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Electrocasnice & defecte finisaje audit", exc)

    if error := result.get("error"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


async def verifica_risc_seismic(
    adresa_sau_identificator: str,
    numar: str | None = None,
    sector: str | None = None,
    limita: int = 5,
) -> dict[str, Any]:
    """Verifică dacă un imobil din București figurează în registrul AMCCRS de risc seismic
    („bulina roșie”) și ce înseamnă încadrarea pentru preț, creditare și asigurare.

    Returnează clasa de risc (RsI–RsIV), categoria de urgență (U1–U3), dacă imobilul a fost
    deja consolidat, anul și autorul expertizei tehnice, plus impactul orientativ asupra
    prețului și consecințele practice (bancă, asigurare, obligații legale).

    Clasa RsI este cel mai mare discount ascuns al unui apartament bucureștean: majoritatea
    băncilor refuză creditul, iar proprietarul are obligația legală de a consolida — nimic
    din toate astea nu apare în anunț.

    Atenție: absența din registru NU înseamnă că imobilul e sigur — lista cuprinde doar
    clădirile expertizate tehnic.

    Args:
        adresa_sau_identificator: Adresă din București („Strada Academiei 15, Sector 1”) sau
            id/URL de anunț imobiliare.ro, caz în care adresa se ia din anunț.
        numar: Numărul poștal, dacă nu e deja în adresă.
        sector: Sectorul („Sector 3”), pentru dezambiguizare.
        limita: Număr maxim de potriviri returnate (implicit 5).
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import verifica_risc_seismic as server_tool

        return server_tool(
            adresa_sau_identificator=adresa_sau_identificator,
            numar=numar,
            sector=sector,
            limita=limita,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("AMCCRS seismic risk lookup", exc)

    if error := result.get("error") or result.get("error_message"):
        return {"status": "error", "error_message": error}

    return {"status": "success", **result}


# Extra fields the imo360 records carry that the imobiliare ones do not.
# Kept short on purpose: the whole record is thousands of tokens across twenty
# listings, and the model does not need the postcode to rank them.
_IMO360_EXTRA = (
    "surface_basis",
    "property_type",
    "zone_id",
    "county",
    "imo360_score",
    # Only ever present when the caller asked for the mis-filed listings back;
    # without it the model would show one as an ordinary bargain.
    "suspect",
)


def _trim_imo360(listing: dict[str, Any]) -> dict[str, Any]:
    trimmed = _trim(listing)
    trimmed |= {k: listing[k] for k in _IMO360_EXTRA if listing.get(k) is not None}
    return trimmed


async def cauta_imo360_zona(
    zona: str,
    oras: str | None = None,
    tranzactie: str = "sale",
    tip: str | None = None,
    pret_max: int | None = None,
    pret_min: int | None = None,
    camere: int | None = None,
    suprafata_min: float | None = None,
    sort: str = "price_per_sqm",
    limit: int = 15,
) -> dict[str, Any]:
    """Search Romanian property listings by zone, via imo360. Needs no session.

    Prefer this over cauta_proprietati when the question is about a
    neighbourhood ("what is on the market in Titan") rather than a description,
    and whenever the other search reports an expired session — this source
    needs no browser session and cannot expire. It also covers rentals, which
    the other search does not.

    Args:
        zona: Neighbourhood or zone name, e.g. "Titan", "Militari", "Gheorgheni".
        oras: City or county, when the name is used in several places, e.g.
            "bucuresti", "cluj".
        tranzactie: "sale" for properties for sale, "rent" for rentals.
        tip: Property type — "apartment", "house", "land", "commercial_space"
            or "office". Leave unset for every type.
        pret_max: Maximum price in EUR.
        pret_min: Minimum price in EUR.
        camere: Exact number of rooms.
        suprafata_min: Minimum surface in square metres.
        sort: "price_per_sqm", "price", "price_desc", "surface", "newest" or
            "year_built".
        limit: Maximum listings to return.

    Returns:
        A dict with "status", and on success "listings", the zones the name
        resolved to, "oferta_totala" — how many properties are actually on the
        market there, or null when the upstream count is capped — and
        "excluse_neconforme", how many listings filed under "sale" were dropped
        because they are not sales of the whole property (rental ads, undivided
        shares). Mention that count if it is large relative to the results.
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()
    if not settings.imo360_enabled:
        return _imo360_disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import Filters, cauta_imo360

        return cauta_imo360(
            zona=zona,
            oras=oras,
            tranzactie=tranzactie if tranzactie in ("sale", "rent") else "sale",
            tip=tip,
            filtre=Filters(
                pret_max=pret_max,
                pret_min=pret_min,
                camere=camere,
                suprafata_min=suprafata_min,
            ),
            sort=sort,
            limit=limit,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("imo360 search", exc)
    if result.get("status") == "error":
        return result
    result["listings"] = [_trim_imo360(listing) for listing in result.get("listings", [])]
    return result


async def puls_piata_zona(
    zona: str,
    oras: str | None = None,
    tip: str = "apartment",
    camere: int | None = None,
) -> dict[str, Any]:
    """Sale and rental sides of one zone, and the gross rental yield between them.

    The only tool here that can answer "what does this zone earn" or "how deep
    is this market": it reads the asking prices and the rents from the same
    geography on the same day, and reports how many properties are on the
    market for sale and for rent.

    The yield is gross — before vacancy, management, tax and maintenance. Say
    so when reporting it, and report the sample sizes with it: a median drawn
    from eight listings is not the same claim as one drawn from eighty.

    Args:
        zona: Neighbourhood or zone name, e.g. "Titan", "Gheorgheni".
        oras: City or county, to disambiguate the name.
        tip: Property type the snapshot is about — "apartment", "house",
            "land", "commercial_space" or "office".
        camere: Restrict the snapshot to a room count, e.g. 2.

    Returns:
        A dict with "status", and on success the sale and rent price
        distributions, the supply counts, "gross_yield_pct", and the sample
        sizes behind them; on error an "error_message".
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()
    if not settings.imo360_enabled:
        return _imo360_disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import puls_piata

        return puls_piata(zona=zona, oras=oras, tip=tip, camere=camere)

    try:
        return await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("Market pulse", exc)


async def detalii_imo360_anunt(id_anunt: str) -> dict[str, Any]:
    """Full record for one imo360 listing, with the whole photo gallery.

    Search results carry one thumbnail; this returns the rest, plus the source
    portal's own attributes (heating, building material, windows, lift,
    primary or secondary market) where the upstream ad published them.

    Args:
        id_anunt: An imo360 listing id, from a cauta_imo360_zona result.

    Returns:
        A dict with "status", and on success "listing"; on error an
        "error_message".
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()
    if not settings.imo360_enabled:
        return _imo360_disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import detalii_imo360

        return detalii_imo360(id_anunt=id_anunt)

    try:
        return await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("imo360 listing details", exc)


# Extra fields only the aggregator can fill. `sources` is the expensive one to
# leave out and the expensive one to include whole: it is what proves a flat is
# advertised at two prices, and it is a nested list per listing. Trimmed to the
# three fields that carry the argument.
_IMORADAR_EXTRA = (
    "source_portal",
    "source_count",
    "price_spread_pct",
    "price_spread_scope",
    "days_on_imoradar",
    "first_posted",
    "old_price_eur",
    "price_drop_pct",
    "expired",
    "suspect",
)


def _trim_imoradar(listing: dict[str, Any]) -> dict[str, Any]:
    trimmed = _trim(listing)
    trimmed |= {k: listing[k] for k in _IMORADAR_EXTRA if listing.get(k) is not None}
    # Only where there is actually a divergence to show; one ad on one portal
    # is the common case and its `sources` entry repeats the record.
    if listing.get("source_count", 0) > 1:
        trimmed["sources"] = [
            {k: s[k] for k in ("portal", "price_eur", "posted", "seller_type") if s.get(k)}
            for s in listing.get("sources") or []
        ]
    return trimmed


async def cauta_imoradar_agregat(
    zona: str | None = None,
    oras: str | None = None,
    doar_proprietar: bool = False,
    pret_max: int | None = None,
    pret_min: int | None = None,
    camere: int | None = None,
    suprafata_min: float | None = None,
    zile_pe_piata_max: int | None = None,
    sort: str = "price_per_sqm",
    limit: int = 15,
) -> dict[str, Any]:
    """Search apartments for sale across every major Romanian portal at once.

    imoradar24 aggregates imobiliare.ro, storia.ro, olx.ro, publi24.ro and
    others into one de-duplicated index, and needs no session. Use it for the
    two questions the other searches cannot answer:

    * apartments sold **directly by owners** — that segment lives on OLX and
      Publi24, which the other sources do not index (doar_proprietar=True);
    * whether a flat is **advertised at more than one price** — where it is on
      several portals or with several agencies, every ad comes back in
      "sources" with "price_spread_pct" between them.

    Only argue from a spread when "price_spread_scope" is "cross_seller".
    "same_seller" usually means several units of one project grouped together,
    not one flat at several prices.

    Args:
        zona: Neighbourhood, town or county, e.g. "Titan", "Cluj-Napoca".
            Leave unset to search the whole country.
        oras: City or county, when the name is used in several places.
        doar_proprietar: Only listings advertised directly by owners.
        pret_max: Maximum price in EUR.
        pret_min: Minimum price in EUR.
        camere: Exact number of rooms.
        suprafata_min: Minimum usable surface in square metres.
        zile_pe_piata_max: Only listings on the market at most this many days.
        sort: "price_per_sqm", "price", "price_desc", "surface", "newest" or
            "year_built".
        limit: Maximum listings to return.

    Returns:
        A dict with "status", and on success "listings", "oferta_totala" — how
        many distinct properties are on the market there — "oferta_proprietari"
        (how many of those are from owners directly), "portaluri" (the source
        breakdown) and "excluse_neconforme", listings dropped for carrying a
        price no sale could be at. Report "days_on_market" as time on the
        market and not as freshness of the ad: it is the longer of the ad's age
        on its own portal and its age in this index.
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()
    if not settings.imoradar_enabled:
        return _imoradar_disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import Filters, cauta_imoradar

        return cauta_imoradar(
            zona=zona,
            oras=oras,
            doar_proprietar=doar_proprietar,
            filtre=Filters(
                pret_max=pret_max,
                pret_min=pret_min,
                camere=camere,
                suprafata_min=suprafata_min,
                zile_pe_piata_max=zile_pe_piata_max,
            ),
            sort=sort,
            limit=limit,
        )

    try:
        result = await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("imoradar24 search", exc)
    if result.get("status") == "error":
        return result
    result["listings"] = [_trim_imoradar(listing) for listing in result.get("listings", [])]
    return result


async def istoric_pret_imoradar_anunt(id_anunt: str) -> dict[str, Any]:
    """How one listing's asking price has moved since imoradar24 first saw it.

    The strongest negotiation input available here: what the seller has
    already conceded, how long they have been trying, and how many times they
    have cut. Use it before strategie_negociere on any imoradar24 listing, and
    whenever a buyer asks "has this come down" or "how long has it been up".

    Two things you must carry into whatever you say about the answer:

    * If "observat" is false, say the history is unavailable — never that the
      price held steady. The source answers the same way for a listing it
      never tracked and for one that does not exist.
    * "schimbare_pct" is measured only between days that had a single asking
      price. Where several agencies advertise one flat, a day is a range, and
      a range narrowing is the dearest ad ending, not a price cut. Those days
      are counted in "puncte_ambigue"; if that count is most of the history,
      say the history is not readable rather than quoting a change.

    "zile_de_la_prima_aparitie" is a firmer lower bound on time on the market
    than the days_on_market of a search result — it reaches back further.

    Args:
        id_anunt: An imoradar24 listing id, from a cauta_imoradar_agregat
            result, or a listing url.

    Returns:
        A dict with "status", and on success "observat" and — when that is
        true — the first and last sighting, the opening and current asking
        price, "schimbare_pct", "reduceri" (how many cuts), and the series
        itself; on error an "error_message".
    """
    settings = get_settings()
    if not settings.imobiliare_enabled:
        return _disabled()
    if not settings.imoradar_enabled:
        return _imoradar_disabled()

    def work() -> dict[str, Any]:
        from gemini_act.imobiliare_mcp.server import istoric_pret_imoradar

        return istoric_pret_imoradar(id_anunt=id_anunt)

    try:
        return await asyncio.to_thread(work)
    except Exception as exc:  # noqa: BLE001
        return _failure("imoradar24 price history", exc)


IMOBILIARE_TOOLS = [
    cauta_proprietati,
    cauta_imobiliare_obscura,
    cauta_imo360_zona,
    cauta_imoradar_agregat,
    istoric_pret_imoradar_anunt,
    puls_piata_zona,
    detalii_imo360_anunt,
    reia_cautare,
    detalii_proprietate,
    statistici_piata,
    evalueaza_proprietate,
    strategie_negociere,
    inspecteaza_vizual_proprietate,
    analizeaza_mobilier_si_finisaje,
    analizeaza_electrocasnice_si_defecte_finisaje,
    analizeaza_dezvoltator_si_constructor,
    analizeaza_materiale_si_specificatii_tehnice,
    checklist_receptie_imobil_nou,
    analizeaza_strada_si_imprejurimi_street_view,
    analizeaza_bonitate_dezvoltator_targetare,
    recenzii_reputatie_google_maps,
    verifica_risc_seismic,
    genereaza_raport_complet_pdf,
]
