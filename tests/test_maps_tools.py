"""Tests for Google Maps tools and agent integration.

Tests edge cases, missing API key degradation, and response parsing with
mocked HTTP responses (no network access required).
"""

from __future__ import annotations

from typing import Any

import httpx

from gemini_act.agent.factory import build_agent
from gemini_act.config import Settings
from imobiliare.agent_tools.maps import (
    MAPS_TOOLS,
    calculeaza_scor_accesibilitate,
    calculeaza_traseu,
    cauta_locuri_in_apropiere,
    detalii_locatie,
    geocodare_adresa,
    matrice_distante,
)


def _test_settings(**overrides: Any) -> Settings:
    return Settings(token_store="memory", **overrides)


# ---------------------------------------------------------------------------
# Missing API key behavior
# ---------------------------------------------------------------------------


def test_maps_tools_fail_gracefully_without_api_key(monkeypatch):
    monkeypatch.setattr(
        "imobiliare.agent_tools.maps.get_settings",
        lambda: _test_settings(maps_api_key=""),
    )
    # `calculeaza_scor_accesibilitate` deleagă în pachetul `imobiliare`, care își
    # citește propriile setări — altfel testul ar trece din întâmplare.
    monkeypatch.setattr(
        "imobiliare.mcp.accesibilitate.get_settings",
        lambda: _test_settings(maps_api_key=""),
    )

    res_geo = geocodare_adresa("Piata Unirii, Bucuresti")
    assert res_geo["status"] == "error"
    assert "Google Maps API Key nu este configurat" in res_geo["mesaj"]

    res_scor = calculeaza_scor_accesibilitate("44.43,26.10")
    assert res_scor["status"] == "error"
    assert "Google Maps API Key nu este configurat" in res_scor["mesaj"]

    res_route = calculeaza_traseu("Piata Romana", "Piata Unirii")
    assert res_route["status"] == "error"
    assert "Google Maps API Key nu este configurat" in res_route["mesaj"]

    res_mat = matrice_distante(["Piata Romana"], ["Piata Unirii"])
    assert res_mat["status"] == "error"
    assert "Google Maps API Key nu este configurat" in res_mat["mesaj"]

    res_near = cauta_locuri_in_apropiere("44.43,26.10")
    assert res_near["status"] == "error"
    assert "Google Maps API Key nu este configurat" in res_near["mesaj"]

    res_det = detalii_locatie("place_123")
    assert res_det["status"] == "error"
    assert "Google Maps API Key nu este configurat" in res_det["mesaj"]


# ---------------------------------------------------------------------------
# Success scenarios with mocked HTTP responses
# ---------------------------------------------------------------------------


def test_geocodare_adresa_success(monkeypatch):
    monkeypatch.setattr(
        "imobiliare.agent_tools.maps.get_settings",
        lambda: _test_settings(maps_api_key="mock-key"),
    )

    def mock_get(self, url: str, params: dict[str, Any] | None = None, **kwargs: Any):
        payload = {
            "status": "OK",
            "results": [
                {
                    "formatted_address": "Piața Victoriei, București, România",
                    "geometry": {
                        "location": {"lat": 44.4532, "lng": 26.0844},
                        "location_type": "ROOFTOP",
                    },
                    "place_id": "ChIJ12345",
                    "types": ["transit_station", "point_of_interest"],
                }
            ],
        }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    res = geocodare_adresa("Piata Victoriei, Bucuresti")
    assert res["status"] == "success"
    assert res["latitudine"] == 44.4532
    assert res["longitudine"] == 26.0844
    assert "Piața Victoriei" in res["adresa_formatata"]
    assert res["place_id"] == "ChIJ12345"


def test_calculeaza_traseu_success(monkeypatch):
    monkeypatch.setattr(
        "imobiliare.agent_tools.maps.get_settings",
        lambda: _test_settings(maps_api_key="mock-key"),
    )

    def mock_get(self, url: str, params: dict[str, Any] | None = None, **kwargs: Any):
        payload = {
            "status": "OK",
            "routes": [
                {
                    "summary": "Bulevardul Lascăr Catargiu",
                    "legs": [
                        {
                            "distance": {"text": "2.5 km", "value": 2500},
                            "duration": {"text": "8 mins", "value": 480},
                            "start_address": "Piața Romană",
                            "end_address": "Piața Victoriei",
                            "steps": [
                                {
                                    "html_instructions": "Mergeți spre <b>nord</b>",
                                    "distance": {"text": "500 m", "value": 500},
                                    "duration": {"text": "2 mins", "value": 120},
                                    "travel_mode": "DRIVING",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    res = calculeaza_traseu("Piața Romană", "Piața Victoriei", mod="driving")
    assert res["status"] == "success"
    assert res["distanta"] == "2.5 km"
    assert res["durata"] == "8 mins"
    assert len(res["instructiuni_principale"]) == 1
    assert "Mergeți spre nord" in res["instructiuni_principale"][0]


def test_matrice_distante_success(monkeypatch):
    monkeypatch.setattr(
        "imobiliare.agent_tools.maps.get_settings",
        lambda: _test_settings(maps_api_key="mock-key"),
    )

    def mock_get(self, url: str, params: dict[str, Any] | None = None, **kwargs: Any):
        payload = {
            "status": "OK",
            "origin_addresses": ["Piața Romană, București"],
            "destination_addresses": ["Aeroport Otopeni"],
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "distance": {"text": "15.0 km", "value": 15000},
                            "duration": {"text": "25 mins", "value": 1500},
                        }
                    ]
                }
            ],
        }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    res = matrice_distante(["Piața Romană"], ["Aeroport Otopeni"])
    assert res["status"] == "success"
    assert len(res["matrice"]) == 1
    assert res["matrice"][0]["rezultate"][0]["distanta"] == "15.0 km"
    assert res["matrice"][0]["rezultate"][0]["durata"] == "25 mins"


def test_cauta_locuri_in_apropiere_success(monkeypatch):
    monkeypatch.setattr(
        "imobiliare.agent_tools.maps.get_settings",
        lambda: _test_settings(maps_api_key="mock-key"),
    )

    def mock_post(self, url: str, json: dict[str, Any] | None = None, **kwargs: Any):
        payload = {
            "places": [
                {
                    "displayName": {"text": "Supermarket Mega Image"},
                    "shortFormattedAddress": "Strada George Enescu 10",
                    "rating": 4.5,
                    "userRatingCount": 350,
                    "id": "place_mega",
                }
            ],
        }
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    res = cauta_locuri_in_apropiere("44.43,26.10", tip_facilitate="supermarket", raza_m=1000)
    assert res["status"] == "success"
    assert res["total_gasite"] == 1
    assert res["locuri"][0]["nume"] == "Supermarket Mega Image"
    assert res["locuri"][0]["rating"] == 4.5


def test_detalii_locatie_success(monkeypatch):
    monkeypatch.setattr(
        "imobiliare.agent_tools.maps.get_settings",
        lambda: _test_settings(maps_api_key="mock-key"),
    )

    def mock_get(self, url: str, params: dict[str, Any] | None = None, **kwargs: Any):
        payload = {
            "displayName": {"text": "Metrou Piața Unirii"},
            "formattedAddress": "Piața Unirii, București",
            "rating": 4.3,
            "userRatingCount": 1200,
            "websiteUri": "https://metrorex.ro",
            "googleMapsUri": "https://maps.google.com/?cid=123",
            "regularOpeningHours": {
                "weekdayDescriptions": ["Luni: 05:00 - 23:00"]
            },
        }
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    res = detalii_locatie("place_unirii")
    assert res["status"] == "success"
    assert res["nume"] == "Metrou Piața Unirii"
    assert res["rating"] == 4.3
    assert len(res["program_lucru"]) == 1


def test_calculeaza_scor_accesibilitate_composite(monkeypatch):
    # Implementarea trăiește în `imobiliare.mcp.accesibilitate`; tool-ul din agent
    # e doar wrapper-ul din care ADK derivă schema.
    monkeypatch.setattr(
        "imobiliare.mcp.accesibilitate.get_settings",
        lambda: _test_settings(maps_api_key="mock-key"),
    )

    def mock_post(self, url: str, json: dict[str, Any] | None = None, **kwargs: Any):
        payload = {"places": [{"id": f"p{i}"} for i in range(3)]}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    res = calculeaza_scor_accesibilitate("44.43,26.10")
    assert res["status"] == "success"
    assert "scor_accesibilitate" in res
    assert 0 <= res["scor_accesibilitate"] <= 100
    assert "detalii_categorii" in res
    assert "metrou_si_tranzit" in res["detalii_categorii"]
    assert "supermarket" in res["detalii_categorii"]


# ---------------------------------------------------------------------------
# Agent factory integration
# ---------------------------------------------------------------------------


def test_factory_registers_maps_tools_when_api_key_configured():
    settings = _test_settings(maps_api_key="test-api-key")
    agent = build_agent(settings=settings, token_service=None, mcp_registry=None)

    agent_tool_names = [getattr(t, "__name__", str(t)) for t in agent.tools]
    for maps_tool in MAPS_TOOLS:
        assert maps_tool.__name__ in agent_tool_names


def test_factory_omits_maps_tools_when_api_key_empty():
    settings = _test_settings(maps_api_key="")
    agent = build_agent(settings=settings, token_service=None, mcp_registry=None)

    agent_tool_names = [getattr(t, "__name__", str(t)) for t in agent.tools]
    for maps_tool in MAPS_TOOLS:
        assert maps_tool.__name__ not in agent_tool_names
