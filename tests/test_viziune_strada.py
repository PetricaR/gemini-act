"""Tests for Google Street View 360 and Satellite exterior visual audit tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from gemini_act.config import Settings
from imobiliare.agent_tools import imobiliare as agent_tools
from imobiliare.mcp import maps, server, viziune_strada


def _settings(**overrides) -> Settings:
    return Settings(**{"token_store": "memory", **overrides})


MOCK_AUDIT_DATA = {
    "cladire_si_fatada": {
        "stare_fatada": "Tencuială decorativă în stare bună, fără fisuri structurale vizibile.",
        "izolatie_termica_exterioara": "Bloc reabilitat termic, anvelopare completă cu polistiren.",
        "balcoane_si_ferestre": "Tâmplărie PVC albă, balcoane închise unitar în proporție de 80%.",
        "unitati_ac_si_cabluri_fatada": "Unități AC montate pe fațadă cu scurgeri individuale.",
        "parter_si_intrare": "Intrare curată, interfon funcțional, rampă de acces cărucioare.",
    },
    "strada_si_infrastructura": {
        "calitate_trotuare": "Trotuare asfaltate, lățime medie 1.8m, borduri coborâte la treceri.",
        "calitate_carosabil": "Asfalt fără gropi, două benzi de circulație cu sens unic.",
        "iluminat_si_retele_aeriene": "Stâlpi de iluminat LED, rețele de fibră optică subterane.",
    },
    "parcare_si_accesibilitate": {
        "aglomerare_parcare": "Parcare intensă, locuri trasate la bordură ocupate 90%.",
        "parcare_trotuar_sau_verde": False,
        "acces_autospeciale_urgenta": "Acces facil pentru autospeciale pompieri și ambulanță.",
    },
    "ambient_urban_si_vecinatati": {
        "tipologie_vecinatati": "Zonă rezidențială liniștită, regim de înălțime P+4.",
        "spatii_verzi_si_vegetatie": "Tei maturi, spațiu verde îngrijit în fața blocului.",
        "potentiale_surse_disconfort": ["Trafic la ore de vârf pe artera adiacentă"],
    },
    "analiza_satelit": {
        "acoperis_si_terasa": "Terasă necirculabilă cu membrană bituminoasă în stare optimă.",
        "densitate_construita": "Medie, spații aerisite între clădiri.",
        "distanta_fata_de_cladiri_vecine": "Peste 25 metri până la blocul din față (intimitate).",
        "curte_interioara_sau_parcare_sol": "Alee de acces asfaltată cu 10 locuri marcate.",
    },
    "evaluare_globala_exterior": {
        "scor_calitate_cladire_si_fatada": 8,
        "scor_ambient_strada_si_zona": 8,
        "nivel_siguranta_si_civilizatie": "ridicat",
        "puncte_forte_exterioare": [
            "Bloc anvelopat termic",
            "Trotuare libere de mașini",
            "Arbori maturi și spații verzi",
        ],
        "semnale_alarma_sau_riscuri": [
            "Locuri de parcare limitate seara",
        ],
        "recomandari_investigatie_pe_teren": [
            "Verificați presiunea apei la etajele superioare",
            "Verificați disponibilitatea unui loc de parcare ADP/nominal",
        ],
        "concluzie_audit_exterior": "Imobil bine întreținut, zonă civilizată și aerisită.",
    },
}


# ---------------------------------------------------------------------------
# 1. street_audit_to_markdown
# ---------------------------------------------------------------------------


def test_street_audit_to_markdown_empty():
    assert viziune_strada.street_audit_to_markdown({}) == ""
    assert viziune_strada.street_audit_to_markdown(None) == ""  # type: ignore


def test_street_audit_to_markdown_full():
    md = viziune_strada.street_audit_to_markdown(
        data=MOCK_AUDIT_DATA,
        address="Strada Aviatorilor 10, București",
        metadata={"date": "2024-06", "status": "OK"},
        images_info={"Fațadă Nord": "streetview_nord.jpg", "Satelit": "satelit.png"},
    )

    assert "## 🏙️ Audit Exterior: Fațadă, Stradă & Satelit" in md
    assert "Strada Aviatorilor 10" in md
    assert "2024-06" in md
    assert "![Fațadă Nord](streetview_nord.jpg)" in md
    assert "![Satelit](satelit.png)" in md
    assert "8 / 10" in md
    assert "RIDICAT" in md
    assert "Tencuială decorativă în stare bună" in md
    assert "Bloc reabilitat termic" in md
    assert "Trotuare asfaltate" in md
    assert "Acces facil pentru autospeciale" in md
    assert "Zonă rezidențială liniștită" in md
    assert "Peste 25 metri până la blocul din față" in md
    assert "Bloc anvelopat termic" in md
    assert "Locuri de parcare limitate" in md
    assert "Verificați disponibilitatea unui loc de parcare" in md
    assert "Imobil bine întreținut" in md


# ---------------------------------------------------------------------------
# 2. Maps Street View and Satellite Extensions
# ---------------------------------------------------------------------------


def test_street_view_metadata_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "OK",
        "date": "2024-05",
        "pano_id": "test_pano_123",
        "location": {"lat": 44.4325, "lng": 26.1038},
    }

    with (
        patch("imobiliare.mcp.maps.available", return_value=True),
        patch("imobiliare.mcp.maps._key", return_value="dummy_key"),
        patch.object(httpx.Client, "get", return_value=mock_resp),
    ):
        meta = maps.street_view_metadata(44.4325, 26.1038)
        assert meta is not None
        assert meta["status"] == "OK"
        assert meta["date"] == "2024-05"
        assert meta["pano_id"] == "test_pano_123"


def test_street_view_metadata_unavailable_or_error():
    with patch("imobiliare.mcp.maps.available", return_value=False):
        meta = maps.street_view_metadata(44.4325, 26.1038)
        assert meta is None

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with (
        patch("imobiliare.mcp.maps.available", return_value=True),
        patch("imobiliare.mcp.maps._key", return_value="dummy_key"),
        patch.object(httpx.Client, "get", return_value=mock_resp),
    ):
        meta = maps.street_view_metadata(44.4325, 26.1038)
        assert meta is None


def test_satellite_view_success():
    fake_png = b"\x89PNG\r\n\x1a\nfake_sat_data"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "image/png"}
    mock_resp.content = fake_png

    with (
        patch("imobiliare.mcp.maps.available", return_value=True),
        patch("imobiliare.mcp.maps._key", return_value="dummy_key"),
        patch.object(httpx.Client, "get", return_value=mock_resp),
    ):
        img = maps.satellite_view(44.4325, 26.1038, zoom=18)
        assert img == fake_png


def test_satellite_view_unavailable():
    with patch("imobiliare.mcp.maps.available", return_value=False):
        assert maps.satellite_view(44.4325, 26.1038) is None


def test_street_view_angles():
    fake_jpg = b"\xff\xd8\xff\xe0fake_jpg"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = fake_jpg

    with (
        patch("imobiliare.mcp.maps.available", return_value=True),
        patch("imobiliare.mcp.maps._key", return_value="dummy_key"),
        patch(
            "imobiliare.mcp.maps.street_view_metadata",
            return_value={"status": "OK"},
        ),
        patch.object(httpx.Client, "get", return_value=mock_resp),
    ):
        angles = maps.street_view_angles(44.4325, 26.1038, headings=(0, 90, 180, 270))
        assert len(angles) == 4
        assert 0 in angles
        assert 90 in angles
        assert 180 in angles
        assert 270 in angles
        assert angles[0] == fake_jpg


# ---------------------------------------------------------------------------
# 3. analyse_street_and_surroundings
# ---------------------------------------------------------------------------


def test_analyse_street_no_imagery(tmp_path):
    with (
        patch(
            "imobiliare.mcp.maps.street_view_metadata",
            return_value={"status": "ZERO_RESULTS"},
        ),
        patch("imobiliare.mcp.maps.street_view_angles", return_value={}),
        patch("imobiliare.mcp.maps.satellite_view", return_value=None),
    ):
        res = viziune_strada.analyse_street_and_surroundings(
            lat=44.4325,
            lon=26.1038,
            address="Câmpulung Muscel",
            save_dir=tmp_path,
        )
        assert res["status"] == "no_imagery"
        assert "Fără imagini disponibile" in res["rezumat_markdown"]


def test_analyse_street_success(tmp_path):
    fake_jpg = b"\xff\xd8fake_jpg"
    fake_png = b"\x89PNGfake_png"

    mock_response = MagicMock()
    mock_response.text = json.dumps(MOCK_AUDIT_DATA)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with (
        patch(
            "imobiliare.mcp.maps.street_view_metadata",
            return_value={"status": "OK", "date": "2024-05"},
        ),
        patch(
            "imobiliare.mcp.maps.street_view_angles",
            return_value={0: fake_jpg, 90: fake_jpg},
        ),
        patch("imobiliare.mcp.maps.satellite_view", return_value=fake_png),
    ):
        res = viziune_strada.analyse_street_and_surroundings(
            lat=44.4325,
            lon=26.1038,
            address="Bulevardul Unirii 1, București",
            save_dir=tmp_path,
            client=mock_client,
        )

        assert res["status"] == "success"
        assert res["adresa"] == "Bulevardul Unirii 1, București"
        assert res["audit"]["evaluare_globala_exterior"]["scor_calitate_cladire_si_fatada"] == 8
        assert "## 🏙️ Audit Exterior" in res["rezumat_markdown"]
        assert len(res["imagini_salvate"]) == 3  # 2 angles + 1 satellite


def test_analyse_street_gemini_exception(tmp_path):
    fake_jpg = b"\xff\xd8fake_jpg"

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = RuntimeError("API Quota exceeded")

    with (
        patch(
            "imobiliare.mcp.maps.street_view_metadata",
            return_value={"status": "OK"},
        ),
        patch(
            "imobiliare.mcp.maps.street_view_angles",
            return_value={0: fake_jpg},
        ),
        patch("imobiliare.mcp.maps.satellite_view", return_value=None),
    ):
        res = viziune_strada.analyse_street_and_surroundings(
            lat=44.4325,
            lon=26.1038,
            address="Bulevardul Unirii 1",
            save_dir=tmp_path,
            client=mock_client,
        )

        assert res["status"] == "error"
        assert "Quota exceeded" in res["message"]
        assert "Eroare la analiza vizuală" in res["rezumat_markdown"]


# ---------------------------------------------------------------------------
# 4. Server MCP Tool
# ---------------------------------------------------------------------------


def test_server_tool_with_coordinates():
    with patch(
        "imobiliare.mcp.viziune_strada.analyse_street_and_surroundings",
        return_value={"status": "success", "rezumat_markdown": "# Audit"},
    ) as mock_audit:
        res = server.analizeaza_strada_si_imprejurimi_street_view("44.4325, 26.1038")
        assert res["status"] == "success"
        mock_audit.assert_called_once()
        kwargs = mock_audit.call_args.kwargs
        assert kwargs["lat"] == pytest.approx(44.4325)
        assert kwargs["lon"] == pytest.approx(26.1038)


def test_server_tool_with_address_geocoding():
    mock_place = MagicMock()
    mock_place.lat = 44.45
    mock_place.lon = 26.08
    mock_place.formatted_address = "Calea Victoriei, București, România"

    with (
        patch("imobiliare.mcp.maps.geocode", return_value=mock_place),
        patch(
            "imobiliare.mcp.viziune_strada.analyse_street_and_surroundings",
            return_value={"status": "success", "rezumat_markdown": "# Audit"},
        ) as mock_audit,
    ):
        res = server.analizeaza_strada_si_imprejurimi_street_view("Calea Victoriei")
        assert res["status"] == "success"
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["lat"] == 44.45


def test_server_tool_with_listing_id():
    mock_raw = [{
        "id": "275807510",
        "title": "Apartament 3 camere Dorobanti",
        "adresa": "Strada Radu Beller 20, București",
        "latitude": 44.462,
        "longitude": 26.095,
    }]

    mock_client = MagicMock()
    mock_client.hydrate.return_value = mock_raw

    with (
        patch("imobiliare.mcp.server._client") as mock_c_ctx,
        patch(
            "imobiliare.mcp.viziune_strada.analyse_street_and_surroundings",
            return_value={"status": "success", "rezumat_markdown": "# Audit"},
        ) as mock_audit,
    ):
        mock_c_ctx.return_value.__enter__.return_value = mock_client
        res = server.analizeaza_strada_si_imprejurimi_street_view("275807510")
        assert res["status"] == "success"
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["lat"] == 44.462
        assert mock_audit.call_args.kwargs["lon"] == 26.095


def test_server_tool_unresolved_address():
    with patch("imobiliare.mcp.maps.geocode", return_value=None):
        res = server.analizeaza_strada_si_imprejurimi_street_view("Adresa Inexistenta 999999")
        assert res["status"] == "error"
        assert "Nu s-au putut determina coordonatele" in res["message"]


# ---------------------------------------------------------------------------
# 5. Agent Tool Wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_tool_disabled():
    with patch("imobiliare.agent_tools.imobiliare.get_settings") as mock_s:
        mock_s.return_value = _settings(imobiliare_enabled=False)
        res = await agent_tools.analizeaza_strada_si_imprejurimi_street_view("Piata Victoriei")
        assert res["status"] == "error"
        assert "disabled" in res["error_message"]


@pytest.mark.asyncio
async def test_agent_tool_success():
    with (
        patch("imobiliare.agent_tools.imobiliare.get_settings") as mock_s,
        patch(
            "imobiliare.mcp.server.analizeaza_strada_si_imprejurimi_street_view",
            return_value={"status": "success", "rezumat_markdown": "# Street View Audit"},
        ),
    ):
        mock_s.return_value = _settings(imobiliare_enabled=True)
        res = await agent_tools.analizeaza_strada_si_imprejurimi_street_view("Piata Victoriei")
        assert res["status"] == "success"
        assert "# Street View Audit" in res["rezumat_markdown"]


@pytest.mark.asyncio
async def test_agent_tool_exception():
    with (
        patch("imobiliare.agent_tools.imobiliare.get_settings") as mock_s,
        patch(
            "imobiliare.mcp.server.analizeaza_strada_si_imprejurimi_street_view",
            side_effect=RuntimeError("Connection timeout"),
        ),
    ):
        mock_s.return_value = _settings(imobiliare_enabled=True)
        res = await agent_tools.analizeaza_strada_si_imprejurimi_street_view("Piata Victoriei")
        assert res["status"] == "error"
        assert "Connection timeout" in res["error_message"]
