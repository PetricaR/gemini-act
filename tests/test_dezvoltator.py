"""Tests for new builds, developer, materials, and reception checklist tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from gemini_act.config import Settings
from imobiliare.agent_tools import imobiliare as agent_tools
from imobiliare.mcp import dezvoltator, server


def _settings(**overrides) -> Settings:
    return Settings(**{"token_store": "memory", **overrides})


# ---------------------------------------------------------------------------
# Handover & Reception Checklist
# ---------------------------------------------------------------------------


def test_handover_checklist_antecontract():
    res = dezvoltator.generate_new_build_handover_checklist("antecontract")
    assert res["etapa_selectata"] == "antecontract"
    assert "Autorizație de Construire" in res["rezumat_markdown"]
    assert "Extras de Carte Funciară" in res["rezumat_markdown"]
    assert "Penalități de întârziere simetrice" in res["rezumat_markdown"]
    assert "Legea 10/1995" in res["rezumat_markdown"]


def test_handover_checklist_stadiu_constructie():
    res = dezvoltator.generate_new_build_handover_checklist("stadiu_constructie")
    assert res["etapa_selectata"] == "stadiu_constructie"
    assert "Fotografierea și cartografierea traseelor de instalații" in res["rezumat_markdown"]
    assert "Procese verbale de lucrări ascunse (PVLA)" in res["rezumat_markdown"]


def test_handover_checklist_receptie_finala():
    res = dezvoltator.generate_new_build_handover_checklist("receptie_finala")
    assert res["etapa_selectata"] == "receptie_finala"
    assert "Contor individual definitiv de energie electrică" in res["rezumat_markdown"]
    assert "Planeitate șape și pardoseli" in res["rezumat_markdown"]
    assert "Verticalitate pereți și unghiuri de 90°" in res["rezumat_markdown"]
    assert "Etanșeitate tâmplărie ferestre și uși balcon" in res["rezumat_markdown"]
    assert "Testare tablou electric și disjunctor diferențial (RCD)" in res["rezumat_markdown"]
    assert "Alimentare provizorie pe organizare de șantier" in res["rezumat_markdown"]
    assert "Rezistență și Stabilitate Structură" in res["rezumat_markdown"]


def test_handover_checklist_invalid_stage_fallback():
    res = dezvoltator.generate_new_build_handover_checklist("etapa_necunoscuta")
    assert res["etapa_selectata"] == "receptie_finala"
    assert "Recepție Finală" in res["rezumat_markdown"]


def test_handover_checklist_markdown_empty():
    assert dezvoltator.handover_checklist_to_markdown({}) == ""


# ---------------------------------------------------------------------------
# Developer & Builder Markdown
# ---------------------------------------------------------------------------


def test_developer_builder_markdown():
    sample_data = {
        "dezvoltator": {
            "nume": "One United Properties",
            "grup_sau_companie_mama": "One Group",
            "ani_experienta_piata": 15,
            "segment_piata": "premium",
            "proiecte_notabile_finalizate": ["One Floreasca City", "One Herastrau Park"],
            "istoric_si_reputatie": (
                "Dezvoltator cotat la BVB cu reputație solidă în segmentul premium."
            ),
        },
        "constructor_antreprenor_general": {
            "nume": "Bog'Art",
            "tip_executant": "antreprenor general extern licențiat",
            "reputatie_lucrari_executate": "Constructor tier-1 cu experiență vastă.",
            "calitate_structura_istorica": "Foarte bună, standarde seismice ridicate.",
        },
        "stadiu_si_conformitate": {
            "stadiu_proiect": "finalizat",
            "termen_estimat_finalizare": "Q4 2024",
            "autorizatie_construire_status": "emisă și recepționată",
            "situatie_utilitati_definitive": "branșamente individuale definitive active",
        },
        "analiza_riscuri_si_atentie": {
            "scor_incredere_dezvoltator": 9,
            "istoric_intarzieri_livrare": "Fără întârzieri majore cunoscute",
            "puncte_forte": ["Calitate superioară a execuției", "Localizare de top"],
            "riscuri_sau_semnale_alarma": ["Costuri ridicate de mentenanță"],
            "costuri_mentenanta_complex": "1.5 - 2.5 EUR/mp util lunar",
            "recomandari_specifice_cumparator": ["Verifică regulamentul de ordine interioară."],
        },
    }

    md = dezvoltator.developer_builder_to_markdown(sample_data, "One Floreasca Towers")
    assert "## 🏗️ Profil Dezvoltator & Constructor: One Floreasca Towers" in md
    assert "Scor încredere dezvoltator:** `9/10`" in md
    assert "Segment de piață:** `Premium`" in md
    assert "One United Properties" in md
    assert "Bog'Art" in md
    assert "antreprenor general extern licențiat" in md
    assert "✅ Calitate superioară a execuției" in md
    assert "⚠️ Costuri ridicate de mentenanță" in md
    assert "🔍 Verifică regulamentul de ordine interioară." in md


def test_developer_builder_markdown_empty():
    assert dezvoltator.developer_builder_to_markdown({}) == ""


# ---------------------------------------------------------------------------
# Materials & Technical Specs Markdown
# ---------------------------------------------------------------------------


def test_materials_specs_markdown():
    sample_data = {
        "structura_si_fundatie": {
            "tip_structura": "Cadre și diafragme din beton armat",
            "fundatie": "Radier general hidroizolat",
            "clasa_beton_si_otel": "C30/37, oțel BST 500S",
            "conformitate_seismica": "Conform normativ P100-1/2013",
            "evaluare": "Structură robustă cu ductilitate înaltă.",
        },
        "zidarie_si_compartimentare": {
            "pereti_exteriori": "Cărămidă cu goluri verticale Porotherm 30cm",
            "pereti_intre_apartamente": "Cărămidă fonoizolantă Porotherm 25cm",
            "compartimentari_interioare": "Cărămidă 11.5cm tencuită",
            "izolatie_fonica_evaluare": "Excelentă, atenuare >52dB",
        },
        "fatada_si_termoizolatie": {
            "tip_fatada": "Fațadă ventilată cu plăci ceramice",
            "material_izolatie": "Vată minerală bazaltică Rockwool 15cm",
            "grosime_izolatie_cm": 15,
            "standard_energetic": "nZEB (nearly Zero-Energy Building)",
            "evaluare_protectie_foc": "Clasa A1 incombustibil",
        },
        "tamplarie_si_vitraje": {
            "material_profil": "Aluminiu Schuco",
            "brand_profil": "Schüco AWS 75",
            "numar_camere_profil": 7,
            "pachet_sticla": "Tripan 44mm",
            "tratamente_sticla": "Low-E, 4 Seasons, Argon",
            "izolatie_termica_fonica": "Ug = 0.6 W/m²K, izolație fonică 42dB",
        },
        "instalatii_si_echipamente": {
            "sistem_incalzire": "Încălzire în pardoseală Rehau",
            "sursa_caldura": "Pompă de căldură geotermală + centrală imobil",
            "climatizare": "Sistem VRF ascuns în plafon",
            "instalatie_electrica": "Cupru, tablou Gewiss, protecții diferențiale",
            "energii_regenerabile": "Panouri fotovoltaice pe acoperiș",
        },
        "spatii_comune_si_ascensoare": {
            "brand_ascensor": "Schindler 5500 de viteză mare",
            "finisaje_holuri_si_casa_scarii": "Marmură și placaje compozit",
            "adapost_protectie_civila_ala": "Prezent la subsol -2 conform normelor IGSU",
            "parcare_subterana_detalii": "Sprinklere, ventilație cu desfumare jet-fans",
        },
        "evaluare_globala_tehnica": {
            "scor_calitate_materiale": 9,
            "nivel_clasificare": "premium",
            "puncte_forte_tehnice": [
                "Fațadă ventilată cu vată bazaltică",
                "Tâmplărie aluminiu Schuco tripan",
            ],
            "potentiale_compromisuri_sau_cost_cutting": [
                "Compartimentările secundare fără barieră acustică dublă"
            ],
            "durabilitate_estimata": "Peste 50 de ani fără intervenții majore",
            "concluzie_audit_tehnic": "Calitate tehnică peste media pieței din zonă.",
        },
    }

    md = dezvoltator.materials_specs_to_markdown(sample_data, "Nusco City")
    assert "## 🧱 Fișă Tehnică & Materiale de Construcție: Nusco City" in md
    assert "Scor calitate materiale:** `9/10`" in md
    assert "Nivel tehnic:** `Premium`" in md
    assert "Cadre și diafragme din beton armat" in md
    assert "Fațadă ventilată cu plăci ceramice" in md
    assert "nZEB" in md
    assert "Aluminiu Schuco" in md
    assert "Schindler 5500" in md
    assert "Adăpost protecție civilă (ALA)" in md
    assert "✅ Fațadă ventilată cu vată bazaltică" in md
    assert "⚠️ Compartimentările secundare fără barieră acustică dublă" in md


def test_materials_specs_markdown_empty():
    assert dezvoltator.materials_specs_to_markdown({}) == ""


# ---------------------------------------------------------------------------
# analyse_developer_and_builder with Mock GenAI
# ---------------------------------------------------------------------------


def test_analyse_developer_and_builder_success(monkeypatch):
    mock_payload = {
        "dezvoltator": {
            "nume": "One United Properties",
            "segment_piata": "premium",
            "istoric_si_reputatie": "Reputație excelentă.",
        },
        "constructor_antreprenor_general": {
            "nume": "Bog'Art",
            "tip_executant": "antreprenor general extern licențiat",
        },
        "stadiu_si_conformitate": {
            "stadiu_proiect": "finalizat",
            "situatie_utilitati_definitive": "branșamente active",
        },
        "analiza_riscuri_si_atentie": {
            "scor_incredere_dezvoltator": 9,
            "puncte_forte": ["Soliditate financiară"],
            "riscuri_sau_semnale_alarma": ["Prețuri mari"],
            "recomandari_specifice_cumparator": ["Negociază locul de parcare"],
        },
    }

    fake_response = MagicMock()
    fake_response.text = json.dumps(mock_payload)

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    monkeypatch.setattr(dezvoltator.viziune, "_client", lambda genai, settings: fake_client)

    res = dezvoltator.analyse_developer_and_builder(
        "One Floreasca Towers", context_text="Ansamblu finalizat în 2024"
    )
    assert res["status"] == "success"
    assert res["proiect"] == "One Floreasca Towers"
    assert res["analiza_structurata"]["dezvoltator"]["nume"] == "One United Properties"
    assert "One United Properties" in res["rezumat_markdown"]


def test_analyse_developer_and_builder_error(monkeypatch):
    fake_client = MagicMock()
    fake_client.models.generate_content.side_effect = RuntimeError("API quota exceeded")

    monkeypatch.setattr(dezvoltator.viziune, "_client", lambda genai, settings: fake_client)

    res = dezvoltator.analyse_developer_and_builder("Proiect Test")
    assert "error" in res
    assert "API quota exceeded" in res["error"]


# ---------------------------------------------------------------------------
# analyse_construction_materials with Mock GenAI
# ---------------------------------------------------------------------------


def test_analyse_construction_materials_success(monkeypatch):
    mock_payload = {
        "structura_si_fundatie": {
            "tip_structura": "Cadre beton armat",
            "evaluare": "Structură sigură",
        },
        "zidarie_si_compartimentare": {
            "pereti_exteriori": "Cărămidă 30cm",
            "pereti_intre_apartamente": "Cărămidă fonică 25cm",
            "compartimentari_interioare": "Cărămidă 11.5cm",
            "izolatie_fonica_evaluare": "Bună",
        },
        "fatada_si_termoizolatie": {
            "tip_fatada": "Termosistem",
            "material_izolatie": "Vată bazaltică",
            "standard_energetic": "nZEB",
        },
        "tamplarie_si_vitraje": {
            "material_profil": "PVC Salamander",
            "pachet_sticla": "Tripan",
            "izolatie_termica_fonica": "Bună",
        },
        "instalatii_si_echipamente": {
            "sistem_incalzire": "Pardoseală",
            "sursa_caldura": "Pompă de căldură",
            "climatizare": "Preinstalare",
        },
        "spatii_comune_si_ascensoare": {
            "brand_ascensor": "Otis",
            "finisaje_holuri_si_casa_scarii": "Granit",
        },
        "evaluare_globala_tehnica": {
            "scor_calitate_materiale": 8,
            "nivel_clasificare": "mediu-standard",
            "puncte_forte_tehnice": ["Vată bazaltică"],
            "potentiale_compromisuri_sau_cost_cutting": ["Tâmplărie PVC în loc de aluminiu"],
            "concluzie_audit_tehnic": "Echilibru bun între cost și calitate.",
        },
    }

    fake_response = MagicMock()
    fake_response.text = json.dumps(mock_payload)

    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    monkeypatch.setattr(dezvoltator.viziune, "_client", lambda genai, settings: fake_client)
    monkeypatch.setattr(
        dezvoltator.viziune, "_download", lambda urls, limit: [(b"fake_bytes", "image/jpeg")]
    )

    subject = {
        "title": "Apartament 2 camere New Point",
        "agency": "New Point Development",
        "image_urls": ["https://img.imobiliare.ro/1.jpg"],
    }

    res = dezvoltator.analyse_construction_materials(subject, include_photos=True)
    assert res["status"] == "success"
    assert res["fotografii_analizate"] == 1
    assert res["fisa_tehnica"]["evaluare_globala_tehnica"]["scor_calitate_materiale"] == 8
    assert "Fișă Tehnică & Materiale de Construcție" in res["rezumat_markdown"]


# ---------------------------------------------------------------------------
# Server MCP tools
# ---------------------------------------------------------------------------


def test_server_tools_resolution(monkeypatch):
    # Test checklist tool
    chk = server.checklist_receptie_imobil_nou("receptie_finala")
    assert chk["etapa_selectata"] == "receptie_finala"

    # Mock client and hydrate
    mock_subject = {
        "id": "275807510",
        "title": "Apartament One Floreasca",
        "agency": "One United",
        "image_urls": [],
    }

    fake_client_ctx = MagicMock()
    fake_client_instance = MagicMock()
    fake_client_instance.hydrate.return_value = [{"id": 275807510, "titlu": "Apartament One"}]
    fake_client_ctx.__enter__.return_value = fake_client_instance
    fake_client_ctx.__exit__.return_value = None

    monkeypatch.setattr(server, "_client", lambda: fake_client_ctx)
    monkeypatch.setattr(server, "normalise", lambda raw: mock_subject)

    with patch("imobiliare.mcp.dezvoltator.analyse_developer_and_builder") as mock_dev:
        mock_dev.return_value = {"status": "success", "proiect": "Apartament One Floreasca"}
        # Pass numeric ID
        res = server.analizeaza_dezvoltator_si_constructor("275807510")
        assert res["status"] == "success"
        mock_dev.assert_called_once()

    with patch(
        "imobiliare.mcp.dezvoltator.analyse_construction_materials"
    ) as mock_mat:
        mock_mat.return_value = {"status": "success"}
        res2 = server.analizeaza_materiale_si_specificatii_tehnice("275807510")
        assert res2["status"] == "success"
        mock_mat.assert_called_once()


# ---------------------------------------------------------------------------
# Agent wrapper tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_tools_disabled(monkeypatch):
    monkeypatch.setattr(
        agent_tools, "get_settings", lambda: _settings(imobiliare_enabled=False)
    )

    res_dev = await agent_tools.analizeaza_dezvoltator_si_constructor("One")
    assert res_dev["status"] == "error"
    assert "Property tools are disabled" in res_dev["error_message"]

    res_mat = await agent_tools.analizeaza_materiale_si_specificatii_tehnice("One")
    assert res_mat["status"] == "error"
    assert "Property tools are disabled" in res_mat["error_message"]

    res_chk = await agent_tools.checklist_receptie_imobil_nou("receptie_finala")
    assert res_chk["status"] == "error"
    assert "Property tools are disabled" in res_chk["error_message"]


@pytest.mark.asyncio
async def test_agent_tools_execution(monkeypatch):
    monkeypatch.setattr(agent_tools, "get_settings", lambda: _settings(imobiliare_enabled=True))

    res_chk = await agent_tools.checklist_receptie_imobil_nou("antecontract")
    assert res_chk["status"] == "success"
    assert res_chk["etapa_selectata"] == "antecontract"
