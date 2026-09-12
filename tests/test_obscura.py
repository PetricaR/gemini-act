"""Tests for Obscura headless browser and autonomous imobiliare search."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gemini_act.imobiliare_mcp.obscura import (
    ObscuraBrowser,
    find_obscura_bin,
    parse_query_intent,
    search_imobiliare_obscura,
)
from gemini_act.imobiliare_mcp.server import Filters, cauta, cauta_obscura


def test_find_obscura_bin():
    """Verify that obscura binary is located."""
    bin_path = find_obscura_bin()
    assert bin_path is not None
    assert "obscura" in bin_path


def test_parse_query_intent():
    """Verify intent extraction from natural-language Romanian search queries."""
    # Rooms + Area + Max price
    i1 = parse_query_intent("apartament 2 camere Titan sub 90000 euro")
    assert i1["rooms"] == 2
    assert i1["area"] == "titan"
    assert i1["price_max"] == 90000
    assert i1["deal"] == "sale"
    assert i1["scope"] == "bucuresti"

    # Rent + Cluj + 3 rooms
    i2 = parse_query_intent("chirie 3 camere in Cluj-Napoca")
    assert i2["deal"] == "rent"
    assert i2["rooms"] == 3
    assert i2["scope"] == "judetul-cluj"

    # Studio / Garsoniera + Price range
    i3 = parse_query_intent("garsoniera Dristor peste 45000 euro pana in 60000 euro")
    assert i3["rooms"] == 1
    assert i3["area"] == "dristor"
    assert i3["price_min"] == 45000
    assert i3["price_max"] == 60000


def test_obscura_browser_availability():
    """Verify ObscuraBrowser detects the local binary."""
    browser = ObscuraBrowser()
    assert browser.is_available() is True


def test_search_imobiliare_obscura_structure():
    """Verify search_imobiliare_obscura returns proper schema and listings."""
    mock_offers = [
        MagicMock(
            id="123",
            slug="sector-3-titan-2-camere",
            area="sector-3-titan",
            rooms=2,
            furnished=False,
        ),
        MagicMock(
            id="456",
            slug="sector-3-titan-3-camere",
            area="sector-3-titan",
            rooms=3,
            furnished=False,
        ),
    ]
    mock_hydrated = [
        {
            "id": "123",
            "heading": "Apartament 2 camere Titan",
            "price": "85.000 €",
            "highlights": [
                {"key": "bedroom_count", "label": "2 camere"},
                {"key": "usable_surface", "label": "55 m²"},
            ],
            "tracking": {
                "ga4Item": {
                    "price": 85000,
                    "rooms": 2,
                    "propertyArea": "Titan",
                    "propertyCity": "București",
                    "sellerType": "individual",
                }
            },
        }
    ]

    with patch("gemini_act.imobiliare_mcp.comps.offers", return_value=mock_offers):
        with patch(
            "gemini_act.imobiliare_mcp.client.ImobiliareClient.hydrate", return_value=mock_hydrated
        ):
            res = search_imobiliare_obscura("apartament 2 camere Titan", limit=5)

            assert res["engine"] == "obscura"
            assert res["matched"] >= 1
            assert len(res["listings"]) >= 1
            assert str(res["listings"][0]["id"]) == "123"
            assert res["listings"][0]["price_eur"] == 85000


def test_cauta_obscura_mcp_tool():
    """Verify cauta_obscura MCP tool works directly."""
    mock_offers = [
        MagicMock(
            id="999",
            slug="sector-1-aviatiei-2-camere",
            area="sector-1-aviatiei",
            rooms=2,
            furnished=False,
        )
    ]
    mock_hydrated = [
        {
            "id": "999",
            "heading": "Apartament Aviatiei",
            "price": "140.000 €",
            "highlights": [{"key": "bedroom_count", "label": "2 camere"}],
            "tracking": {"ga4Item": {"price": 140000, "rooms": 2}},
        }
    ]

    with patch("gemini_act.imobiliare_mcp.comps.offers", return_value=mock_offers):
        with patch(
            "gemini_act.imobiliare_mcp.client.ImobiliareClient.hydrate", return_value=mock_hydrated
        ):
            res = cauta_obscura("apartament Aviatiei 2 camere", filtre=Filters(camere=2))
            assert res["engine"] == "obscura"
            assert len(res["listings"]) == 1
            assert str(res["listings"][0]["id"]) == "999"


def test_cauta_fallback_on_session_error():
    """Verify cauta() automatically falls back to Obscura when session is expired/missing."""
    mock_offers = [
        MagicMock(
            id="777",
            slug="sector-2-floreasca-2-camere",
            area="sector-2-floreasca",
            rooms=2,
            furnished=False,
        )
    ]
    mock_hydrated = [
        {
            "id": "777",
            "heading": "Apartament Floreasca",
            "price": "120.000 €",
            "highlights": [{"key": "bedroom_count", "label": "2 camere"}],
            "tracking": {"ga4Item": {"price": 120000, "rooms": 2}},
        }
    ]

    from gemini_act.imobiliare_mcp.client import SessionError

    with patch(
        "gemini_act.imobiliare_mcp.client.ImobiliareClient.search",
        side_effect=SessionError("Session expired"),
    ):
        with patch("gemini_act.imobiliare_mcp.comps.offers", return_value=mock_offers):
            with patch(
                "gemini_act.imobiliare_mcp.client.ImobiliareClient.hydrate",
                return_value=mock_hydrated,
            ):
                res = cauta("apartament 2 camere Floreasca")
                assert res["engine"] == "obscura"
                assert "session_warning" in res
                assert len(res["listings"]) == 1
                assert str(res["listings"][0]["id"]) == "777"


@pytest.mark.asyncio
async def test_agent_tool_cauta_imobiliare_obscura():
    """Verify the agent tool cauta_imobiliare_obscura runs successfully."""
    from gemini_act.agent.tools.imobiliare import cauta_imobiliare_obscura

    mock_offers = [
        MagicMock(
            id="888",
            slug="sector-3-dristor-2-camere",
            area="sector-3-dristor",
            rooms=2,
            furnished=False,
        )
    ]
    mock_hydrated = [
        {
            "id": "888",
            "heading": "Apartament Dristor",
            "price": "79.000 €",
            "highlights": [{"key": "bedroom_count", "label": "2 camere"}],
            "tracking": {"ga4Item": {"price": 79000, "rooms": 2}},
        }
    ]

    with patch("gemini_act.imobiliare_mcp.comps.offers", return_value=mock_offers):
        with patch(
            "gemini_act.imobiliare_mcp.client.ImobiliareClient.hydrate", return_value=mock_hydrated
        ):
            res = await cauta_imobiliare_obscura(query="apartament 2 camere Dristor", camere=2)
            assert res["status"] == "success"
            assert res["engine"] == "obscura"
            assert len(res["listings"]) == 1
            assert str(res["listings"][0]["id"]) == "888"
