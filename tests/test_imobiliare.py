"""Property tools: the adapter, the Maps layer, and the vision pass.

Nothing here touches the network. The point of these tests is the behaviour at
the seams — that a missing Maps key degrades instead of failing, that a failed
call is reported rather than raised, and that the report never travels through
the conversation as text.
"""

from __future__ import annotations

import pytest

from gemini_act.config import Settings
from imobiliare import artifacts
from imobiliare.agent_tools import imobiliare as tools
from imobiliare.mcp import maps, viziune


def _settings(**overrides) -> Settings:
    return Settings(**{"token_store": "memory", **overrides})


@pytest.fixture
def no_maps_key(monkeypatch):
    monkeypatch.setattr(maps, "get_settings", lambda: _settings(maps_api_key=""))


@pytest.fixture
def with_maps_key(monkeypatch):
    monkeypatch.setattr(maps, "get_settings", lambda: _settings(maps_api_key="test-key"))


# -- Maps degrades rather than breaking -----------------------------------


def test_maps_is_unavailable_without_a_key(no_maps_key):
    assert maps.available() is False


def test_every_maps_entry_point_returns_none_without_a_key(no_maps_key):
    """An unconfigured key is a supported deployment, not a broken one — the
    caller falls back to OpenStreetMap."""
    assert maps.geocode("Strada Fabrica de Glucoza 5") is None
    assert maps.nearby(44.43, 26.10) is None
    assert maps.walking_times(44.43, 26.10, [(44.44, 26.11)]) is None
    assert maps.static_map(44.43, 26.10) is None
    assert maps.street_view(44.43, 26.10) is None


def test_maps_becomes_available_with_a_key(with_maps_key):
    assert maps.available() is True


def test_walking_times_short_circuits_on_no_destinations(with_maps_key):
    assert maps.walking_times(44.43, 26.10, []) is None


def test_geocode_reads_googles_own_precision_verdict(with_maps_key, monkeypatch):
    """ROOFTOP means the building; APPROXIMATE means a centroid, and the report
    warns differently for each."""
    import httpx

    def response_for(location_type):
        payload = {
            "status": "OK",
            "results": [
                {
                    "formatted_address": "Strada Test 5, București",
                    "geometry": {
                        "location": {"lat": 44.43, "lng": 26.10},
                        "location_type": location_type,
                    },
                    "place_id": "abc",
                }
            ],
        }

        class FakeClient:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def get(self, url, params=None):
                return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

        return FakeClient

    monkeypatch.setattr(httpx, "Client", lambda **kw: response_for("ROOFTOP")())
    assert maps.geocode("Strada Test 5").precision == "adresa"

    monkeypatch.setattr(httpx, "Client", lambda **kw: response_for("APPROXIMATE")())
    assert maps.geocode("Strada Test 5").precision == "zona"


def test_every_amenity_category_maps_to_a_place_type():
    """`raport.py` renders the OSM category list, so a category with no Google
    equivalent would silently be an always-empty row."""
    from imobiliare.mcp.locatie import CATEGORIES

    assert set(maps.PLACE_TYPES) == set(CATEGORIES)


# -- the vision pass ------------------------------------------------------


def test_vision_is_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(viziune, "get_settings", lambda: _settings(imobiliare_vision_enabled=False))
    assert viziune.analyse({}, ["https://example.invalid/a.jpg"]) is None


def test_vision_is_skipped_with_nothing_to_look_at(monkeypatch):
    monkeypatch.setattr(viziune, "get_settings", lambda: _settings())
    assert viziune.analyse({}, []) is None


def test_findings_render_the_evidence_they_rest_on():
    findings = viziune.VisualFindings(
        stare_generala="bun",
        scor_stare=7,
        finisaje="parchet laminat, tâmplărie PVC",
        semne_ingrijorare=["baie nefotografiată"],
        incredere="medie",
        observatii="Apartament întreținut.",
        photos_seen=18,
        had_street_view=True,
        model="gemini-3.8-flash",
    )
    text = findings.to_markdown()
    assert "bun" in text and "7/10" in text
    assert "baie nefotografiată" in text
    assert "18 fotografii" in text and "Street View" in text
    assert "gemini-3.8-flash" in text
    # The caveat is load-bearing: without an inspection this is an opinion
    # about photographs, and the report must not let it read as a finding.
    assert "nu înlocuiesc inspecția" in text
    assert "nu au fost folosite pentru a ajusta valoarea" in text


def test_malformed_model_output_is_dropped_not_half_trusted():
    class FakeResponse:
        text = "this is not json"

    assert viziune._parse(FakeResponse(), [], None, "m") is None


def test_empty_model_output_is_dropped():
    class FakeResponse:
        text = ""

    assert viziune._parse(FakeResponse(), [], None, "m") is None


def test_findings_survive_a_partial_payload():
    """The schema marks some fields optional; a response using that must still
    produce findings rather than being thrown away."""

    class FakeResponse:
        text = '{"stare_generala": "mediu", "semne_ingrijorare": [], "incredere": "scazuta"}'

    findings = viziune._parse(FakeResponse(), [], None, "gemini-3.8-flash")
    assert findings is not None
    assert findings.stare_generala == "mediu"
    assert findings.scor_stare is None


# -- the adapter ----------------------------------------------------------


async def test_tools_report_being_disabled(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: _settings(imobiliare_enabled=False))
    for result in (
        await tools.cauta_proprietati("orice"),
        await tools.detalii_proprietate(["1"]),
        await tools.statistici_piata("t"),
        await tools.evalueaza_proprietate("1"),
    ):
        assert result["status"] == "error"
        assert "disabled" in result["error_message"]


async def test_a_raised_exception_becomes_a_reported_failure(monkeypatch):
    """The prompt tells the agent to quote tool errors verbatim, which only
    works if the tool returns them instead of raising."""
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())

    def boom(*a, **k):
        raise RuntimeError("upstream is down")

    monkeypatch.setattr("imobiliare.mcp.server.evaluare", boom)
    result = await tools.evalueaza_proprietate("275807510")
    assert result["status"] == "error"
    assert "upstream is down" in result["error_message"]


async def test_a_session_failure_falls_back_to_obscura(monkeypatch):
    """When server.cauta reports a session error, cauta_proprietati
    seamlessly falls back to Obscura search."""
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "imobiliare.mcp.server.cauta",
        lambda **k: {"error": "No session_id configured."},
    )
    monkeypatch.setattr(
        "imobiliare.mcp.obscura.search_imobiliare_obscura",
        lambda **k: {
            "engine": "obscura",
            "matched": 1,
            "listings": [{"id": "123", "title": "Listing Obscura"}],
        },
    )
    result = await tools.cauta_proprietati("apartament 3 camere")
    assert result["status"] == "success"
    assert result["engine"] == "obscura"
    assert len(result["listings"]) == 1


async def test_a_search_failure_when_both_engines_fail(monkeypatch):
    """When both legacy search and Obscura fail, an error status is returned."""
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "imobiliare.mcp.server.cauta",
        lambda **k: {"error": "No session_id configured."},
    )
    monkeypatch.setattr(
        "imobiliare.mcp.obscura.search_imobiliare_obscura",
        lambda **k: {"error": "Obscura failed to fetch sitemap"},
    )
    result = await tools.cauta_proprietati("apartament 3 camere")
    assert result["status"] == "error"
    assert "Obscura failed to fetch sitemap" in result["error_message"]


async def test_the_report_is_staged_not_returned_as_text(monkeypatch, tmp_path):
    """Tens of KB of markdown must not enter the conversation — the tool
    returns a token, and the bytes go to the artifact store."""
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    artifacts._store.clear()

    report = tmp_path / "evaluare-275807510.md"
    body = "# Analiză de evaluare\n" + ("text ipotetic " * 2000)
    report.write_text(body, encoding="utf-8")

    monkeypatch.setattr(
        "imobiliare.mcp.server.evaluare",
        lambda **k: {
            "raport": str(report),
            "id": "275807510",
            "valoare_estimata_eur": 118000,
            "pret_cerut_eur": 125000,
            "stare_vizuala": "bun",
        },
    )

    result = await tools.evalueaza_proprietate("275807510")
    assert result["status"] == "success"
    assert result["valoare_estimata_eur"] == 118000
    # The path is not handed back — a path is useless to a Chat user — and
    # neither is the body.
    assert "raport" not in result
    assert body not in str(result)

    stored = artifacts.take(result["raport_atasament"])
    assert stored is not None
    assert stored.data.decode() == body
    assert stored.filename == "evaluare-275807510.md"


async def test_an_unreadable_report_still_returns_the_figures(monkeypatch):
    """The valuation succeeding and the file being unreadable are different
    failures; the numbers are worth having either way."""
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "imobiliare.mcp.server.evaluare",
        lambda **k: {"raport": "/nonexistent/nope.md", "id": "1", "valoare_estimata_eur": 100000},
    )
    result = await tools.evalueaza_proprietate("1")
    assert result["status"] == "success"
    assert result["valoare_estimata_eur"] == 100000
    assert result["raport_atasament"] is None
    assert "could not be read back" in result["nota_raport"]


async def test_a_valuation_error_is_passed_through(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "imobiliare.mcp.server.evaluare",
        lambda **k: {"error": "Nicio comparabilă în zona 'x' cu 3 camere."},
    )
    result = await tools.evalueaza_proprietate("1")
    assert result["status"] == "error"
    assert "Nicio comparabilă" in result["error_message"]


async def test_listings_are_trimmed_before_reaching_the_model(monkeypatch):
    """A hydrate record carries a large tracking block the model has no use for."""
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "imobiliare.mcp.server.detalii",
        lambda ids: {
            "count": 1,
            "listings": [
                {
                    "id": "1",
                    "title": "Apartament",
                    "price_eur": 100000,
                    "tracking": {"huge": "x" * 5000},
                }
            ],
        },
    )
    result = await tools.detalii_proprietate(["275807510"])
    assert result["status"] == "success"
    assert result["listings"][0] == {"id": "1", "title": "Apartament", "price_eur": 100000}


async def test_reia_cautare_success(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "imobiliare.mcp.server.reia",
        lambda token, filtre, sort, limit: {
            "total_hits": 100,
            "matched": 5,
            "returned": 1,
            "listings": [{"id": "2759", "title": "Apt", "price_eur": 95000}],
        },
    )
    result = await tools.reia_cautare("token-123", pret_max=100000, sort="metro")
    assert result["status"] == "success"
    assert result["total_hits"] == 100
    assert result["matched"] == 5
    assert len(result["listings"]) == 1
    assert result["listings"][0]["id"] == "2759"


async def test_inspecteaza_vizual_proprietate_success(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    monkeypatch.setattr(
        "imobiliare.mcp.server.inspecteaza_poze",
        lambda identificator, intrebare: {
            "listing_id": "2759",
            "titlu": "Apt 2 camere",
            "intrebare": intrebare,
            "raspuns_analiza_vizuala": "Finisaje moderne, gresie nouă.",
            "fotografii_inspectate": 4,
            "fotografii_urls": ["https://img.test/1.jpg"],
        },
    )
    result = await tools.inspecteaza_vizual_proprietate("2759", "Cum sunt finisajele?")
    assert result["status"] == "success"
    assert result["listing_id"] == "2759"
    assert "Finisaje moderne" in result["raspuns_analiza_vizuala"]
    assert result["fotografii_inspectate"] == 4


def test_raport_renders_image_links_and_accessibility_score():
    from imobiliare.mcp import raport
    from imobiliare.mcp.anevar import Params, evaluate

    subject = {
        "id": "12345",
        "title": "Apartament Test",
        "price_eur": 120000,
        "price_per_sqm": 2000,
        "surface_sqm": 60,
        "rooms": 2,
        "floor": 2,
        "floors_total": 4,
        "year_built": 1985,
        "area": "Titan",
        "city": "București",
        "image_urls": ["https://img.test/1.jpg", "https://img.test/2.jpg"],
    }
    comps = [
        {
            "id": f"comp-{i}",
            "title": f"Comp {i}",
            "price_eur": 115000 + i * 1000,
            "price_per_sqm": 1950,
            "surface_sqm": 58 + i,
            "rooms": 2,
            "floor": 2,
            "floors_total": 4,
            "year_built": 1985,
        }
        for i in range(5)
    ]
    valuation = evaluate(subject, comps, [], Params())

    md = raport.render(
        valuation,
        comps_source="sitemap test",
        rents_source="sitemap rent",
        street_view_file="streetview-12345.jpg",
        static_map_file="harta-12345.png",
        sheet="galerie-12345.jpg",
        scor_accesibilitate=88.5,
    )

    assert "![Harta zonei](harta-12345.png)" in md
    assert "![Street View fațadă și stradă](streetview-12345.jpg)" in md
    assert "![Galerie compusă](galerie-12345.jpg)" in md
    assert "88.5/100" in md
    assert "[Foto 1](https://img.test/1.jpg)" in md


async def test_analizeaza_mobilier_si_finisaje_disabled(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: _settings(imobiliare_enabled=False))
    res = await tools.analizeaza_mobilier_si_finisaje("12345")
    assert res["status"] == "error"
    assert "disabled" in res["error_message"]


async def test_analizeaza_mobilier_si_finisaje_success(monkeypatch):
    monkeypatch.setattr(tools, "get_settings", lambda: _settings())
    mock_inventar = {
        "mobilier_pe_camere": [
            {
                "camera": "Living",
                "elemente": [
                    {
                        "piesa": "Canapea extensibilă",
                        "stare": "foarte buna",
                        "stil": "modern",
                        "calitate": "mediu/MDF",
                    }
                ],
            }
        ],
        "electrocasnice": [
            {
                "aparat": "Plită cu inducție",
                "camera": "Bucătărie",
                "brand_vizibil": "Bosch",
                "tip": "incorporat",
                "stare": "nou/recent",
            }
        ],
        "finisaje": {
            "pardoseli": {
                "tip_dominant": "Parchet triplustratificat",
                "stare": "impecabil",
                "calitate": "premium",
                "observatii": "fara zgarieturi",
            },
            "tamplarie_ferestre": {
                "material": "PVC",
                "geam": "tripan",
                "stare": "nou",
            },
            "usi": {
                "usa_intrare": "Metalică antiefracție",
                "usi_interioare": "MDF pline",
                "stare": "foarte buna",
            },
            "baie_sanitare": {
                "tip_dus_cada": "dus_walk_in",
                "obiecte_sanitare": "Vas WC suspendat",
                "baterii": "Modern/încastrat",
                "placari_ceramice": "Gresie porțelanată rectificată",
                "stare": "nou",
            },
            "climatizare_si_incalzire": {
                "sursa_incalzire": "Centrală proprie de apartament",
                "aer_conditionat": "AC prezent în living",
                "stare": "nou",
            },
        },
        "evaluare_globala": {
            "nivel_calitate_global": "premium",
            "scor_calitate_finisaje": 9,
            "scor_calitate_mobilier": 8,
            "stare_conservare": "foarte_buna",
            "plusvaloare_mobilier": "aduce_plusvaloare",
            "estimare_valoare_mobilier_eur": 12000,
            "buget_recomandat_renovare_eur": 0,
            "puncte_forte": ["Finisaje premium", "Electrocasnice incorporate"],
            "puncte_slabe": [],
            "concluzie_analiza": "Apartament gata de locuit, investiție excelentă.",
        },
    }

    monkeypatch.setattr(
        "imobiliare.mcp.server.analizeaza_mobilier_si_finisaje",
        lambda identificator, limita_fotografii: {
            "status": "success",
            "inventar": mock_inventar,
            "rezumat_markdown": "# Raport Mobilier & Finisaje",
            "fotografii_analizate": 10,
            "total_fotografii": 15,
            "model": "gemini-3.8-flash",
            "fotografii_reprezentative": ["https://img.test/1.jpg"],
        },
    )

    res = await tools.analizeaza_mobilier_si_finisaje("275807510")
    assert res["status"] == "success"
    assert "inventar" in res
    assert res["inventar"]["evaluare_globala"]["nivel_calitate_global"] == "premium"
    assert res["inventar"]["evaluare_globala"]["scor_calitate_finisaje"] == 9
    assert res["rezumat_markdown"] == "# Raport Mobilier & Finisaje"
    assert res["fotografii_analizate"] == 10


def test_viziune_furniture_finishes_markdown_rendering():
    from imobiliare.mcp.viziune import furniture_finishes_to_markdown

    data = {
        "mobilier_pe_camere": [
            {
                "camera": "Bucătărie",
                "elemente": [
                    {
                        "piesa": "Mobilier pe comandă",
                        "stare": "nou",
                        "stil": "modern",
                        "calitate": "mediu/MDF",
                    }
                ],
            }
        ],
        "electrocasnice": [
            {
                "aparat": "Cuptor electric",
                "camera": "Bucătărie",
                "brand_vizibil": "Electrolux",
                "tip": "incorporat",
                "stare": "nou/recent",
            }
        ],
        "finisaje": {
            "pardoseli": {
                "tip_dominant": "Parchet laminat 10mm",
                "stare": "buna",
                "calitate": "mediu",
                "observatii": "montaj curat",
            },
            "tamplarie_ferestre": {
                "material": "PVC",
                "geam": "termopan",
                "stare": "buna",
            },
            "usi": {
                "usa_intrare": "Metalica",
                "usi_interioare": "MDF",
                "stare": "buna",
            },
            "baie_sanitare": {
                "tip_dus_cada": "cada",
                "obiecte_sanitare": "Standard",
                "baterii": "Cromate",
                "placari_ceramice": "Faianță clasică",
                "stare": "buna",
            },
            "climatizare_si_incalzire": {
                "sursa_incalzire": "Centrală termică",
                "aer_conditionat": "Invertor 12000 BTU",
                "stare": "buna",
            },
        },
        "evaluare_globala": {
            "nivel_calitate_global": "mediu",
            "scor_calitate_finisaje": 7,
            "scor_calitate_mobilier": 7,
            "stare_conservare": "uzura_normala",
            "plusvaloare_mobilier": "neutru_utilizabil",
            "estimare_valoare_mobilier_eur": 5000,
            "buget_recomandat_renovare_eur": 1500,
            "puncte_forte": ["Bucătărie echipată complet"],
            "puncte_slabe": ["Baia necesită reîmprospătare"],
            "concluzie_analiza": "Apartament curat și funcțional.",
        },
    }

    md = furniture_finishes_to_markdown(data, {"title": "Apartament 2 Camere Titan"})
    assert "## 🛋️ Raport Mobilier & Finisaje: Apartament 2 Camere Titan" in md
    assert "Nivel global de calitate:** `Mediu`" in md
    assert "Scor finisaje:** `7/10`" in md
    assert "Mobilier pe comandă" in md
    assert "Cuptor electric" in md
    assert "Electrolux" in md
    assert "Parchet laminat 10mm" in md
    assert "✅ Bucătărie echipată complet" in md
    assert "⚠️ Baia necesită reîmprospătare" in md
