from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock, patch

from gemini_act.imobiliare_mcp.electrocasnice_finisaje import (
    EUR_TO_RON_RATE,
    analizeaza_electrocasnice_si_finisaje,
    electrocasnice_finisaje_to_markdown,
    genereaza_link_cautare_altex,
    genereaza_link_cautare_emag,
    genereaza_link_cautare_google,
)
from gemini_act.imobiliare_mcp.generator_pdf import genereaza_raport_complet_pdf
from gemini_act.imobiliare_mcp.server import analizeaza_electrocasnice_si_defecte_finisaje


def test_generare_linkuri_cautare():
    termen = "Cuptor Bosch Seria 6"
    link_emag = genereaza_link_cautare_emag(termen)
    link_altex = genereaza_link_cautare_altex(termen)
    link_google = genereaza_link_cautare_google(termen)

    assert "emag.ro/search/Cuptor" in link_emag
    assert "Bosch" in link_emag
    assert "altex.ro/cauta/?q=Cuptor" in link_altex
    assert "google.com/search?q=Cuptor" in link_google


def test_analiza_reguli_fallback_fara_branduri():
    """Când nu există branduri specificate și nici imagini, sistemul NU
    trebuie să inventeze electrocasnice sau defecte.
    """
    subject = {
        "title": "Apartament 2 camere modern complet utilat",
        "rooms": 2,
        "usable_surface": 55.0,
        "price": 95000,
        "description": "Bucătărie utilată cu plită inducție, cuptor electric și hotă.",
    }
    res = analizeaza_electrocasnice_si_finisaje(subject, image_urls=[])

    # No photos means no photo audit: the heuristic read of the listing text is
    # still returned, but never as a success the caller could present as an
    # inspection of the images.
    assert res["status"] == "indisponibil"
    assert res["disponibil"] is False
    assert res["motiv"]
    assert res["mod_analiza"] == "fallback_fara_imagini"
    assert res["provenienta"] == "anunt"
    data = res["date_analiza"]
    assert "calitate_generala_finisaje" in data
    assert data["incredere"] == "scazuta"
    assert data["electrocasnice"] == []
    assert data["defecte_si_probleme"] == []


def test_analiza_reguli_fallback_cu_branduri_in_anunt():
    """Dacă apar branduri în textul anunțului, certitudinea trebuie să fie
    strict 'mentionat_in_anunt'.
    """
    subject = {
        "title": "Apartament 2 camere modern complet utilat",
        "rooms": 2,
        "usable_surface": 55.0,
        "price": 95000,
        "description": "Bucătărie utilată cu electrocasnice Bosch și climatizare Daikin.",
    }
    res = analizeaza_electrocasnice_si_finisaje(subject, image_urls=[])

    assert res["status"] == "indisponibil"
    assert res["disponibil"] is False
    assert res["provenienta"] == "anunt"
    data = res["date_analiza"]
    electro = data["electrocasnice"]
    assert len(electro) == 2
    for el in electro:
        assert el["certitudine_brand"] == "mentionat_in_anunt"
        assert "link_cautare_emag" in el
        assert "pret_estimat_nou_ron" in el
        assert el["pret_estimat_nou_ron"] == int(el["pret_estimat_nou_eur"] * EUR_TO_RON_RATE)

    sumar = data["sumar_financiar"]
    assert sumar["total_valoare_nou_electrocasnice_eur"] > 0
    assert sumar["total_valoare_actuala_electrocasnice_eur"] > 0
    assert "rezumat_markdown" in res


def test_electrocasnice_finisaje_to_markdown_formatting():
    data: dict[str, Any] = {
        "calitate_generala_finisaje": {
            "scor_global": 8.5,
            "clasa": "Premium",
            "concluzie": "Finisaje peste medie, bine întreținute.",
        },
        "categorii_finisaje": [
            {
                "categorie": "Pardoseli",
                "calitate": "Premium",
                "scor": 9.0,
                "stare_vizuala": "Excelentă",
                "observatii": "Parchet triplustratificat din stejar.",
            }
        ],
        "defecte_si_probleme": [
            {
                "element_afectat": "Plintă dormitor",
                "descriere_defect": "Dezlipită pe 1.5 metri",
                "severitate": "Minor",
                "cauza_probabila": "Adeziv aplicat neuniform",
                "cost_estimat_remediere_eur": 40,
                "cost_estimat_remediere_ron": 200,
            }
        ],
        "electrocasnice": [
            {
                "aparat": "Plită Inducție",
                "camera": "Bucătărie",
                "brand_detectat": "Bosch",
                "model_sau_serie": "Serie 4",
                "gama_brand": "Mid-range",
                "pret_estimat_nou_eur": 450,
                "pret_estimat_nou_ron": 2250,
                "valoare_piata_actuala_eur": 300,
                "valoare_piata_actuala_ron": 1500,
                "link_cautare_emag": "https://www.emag.ro/search/Plita+Inductie+Bosch",
                "link_cautare_altex": "https://altex.ro/cauta/?q=Plita+Inductie+Bosch",
                "link_cautare_google": "https://www.google.com/search?tbm=shop&q=Plita+Inductie+Bosch",
            }
        ],
        "sumar_financiar": {
            "total_valoare_nou_electrocasnice_eur": 450,
            "total_valoare_nou_electrocasnice_ron": 2250,
            "total_valoare_actuala_electrocasnice_eur": 300,
            "total_valoare_actuala_electrocasnice_ron": 1500,
            "total_buget_remediere_defecte_eur": 40,
            "total_buget_remediere_defecte_ron": 200,
            "impact_negociere_recomandat_eur": 40,
            "recomandare_evaluator": "Proprietatea necesită mici retușuri.",
        },
    }

    md = electrocasnice_finisaje_to_markdown(data)
    assert "## 🛠️ Audit Detaliat Finisaje, Defecte & Electrocasnice" in md
    assert "Plită Inducție" in md
    assert "Bosch" in md
    assert "eMAG" in md
    assert "🟢 Minor" in md
    assert "Plintă dormitor" in md
    assert "40 €" in md


def test_analiza_electrocasnice_gemini_vision_mock():
    import json

    mock_payload = {
        "calitate_generala_finisaje": {
            "scor_global": 9.2,
            "clasa": "Ultra-Lux",
            "concluzie": "Finisaje de lux, marmură și electrocasnice Miele.",
        },
        "categorii_finisaje": [],
        "defecte_si_probleme": [],
        "electrocasnice": [
            {
                "aparat": "Cuptor electric",
                "camera": "Bucătărie",
                "brand_detectat": "Miele",
                "model_sau_serie": "Generation 7000",
                "gama_brand": "Ultra-Lux",
                "pret_estimat_nou_eur": 2200,
                "stare_uzura": "Ca nou",
                "valoare_piata_actuala_eur": 1800,
                "observatii_vizuale": "Încorporat perfect, finisaj inox impecabil",
            }
        ],
        "sumar_financiar": {
            "total_valoare_nou_electrocasnice_eur": 2200,
            "total_valoare_actuala_electrocasnice_eur": 1800,
            "total_buget_remediere_defecte_eur": 0,
            "impact_negociere_recomandat_eur": 0,
            "recomandare_evaluator": "Echipare de excepție.",
        },
    }

    mock_response = MagicMock()
    mock_response.text = f"```json\n{json.dumps(mock_payload)}\n```"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with (
        patch(
            "gemini_act.imobiliare_mcp.electrocasnice_finisaje._client",
            return_value=mock_client,
        ),
        patch(
            "gemini_act.imobiliare_mcp.electrocasnice_finisaje._download",
            return_value=[(b"fake_jpeg", "image/jpeg")],
        ),
    ):
        res = analizeaza_electrocasnice_si_finisaje(
            subject={"title": "Penthouse de lux"},
            image_urls=["http://example.com/photo1.jpg"],
        )

        assert res["status"] == "success"
        data = res["date_analiza"]
        assert data["calitate_generala_finisaje"]["scor_global"] == 9.2
        assert data["electrocasnice"][0]["brand_detectat"] == "Miele"
        assert "link_cautare_emag" in data["electrocasnice"][0]
        assert data["electrocasnice"][0]["pret_estimat_nou_ron"] == 2200 * EUR_TO_RON_RATE


def test_mcp_server_tool_analizeaza_electrocasnice():
    with patch(
        "gemini_act.imobiliare_mcp.electrocasnice_finisaje.analizeaza_electrocasnice_si_finisaje"
    ) as mock_impl:
        mock_impl.return_value = {"status": "success", "date_analiza": {"electrocasnice": []}}
        out = analizeaza_electrocasnice_si_defecte_finisaje("apartament bucuresti")
        assert out["status"] == "success"


def test_integrare_pdf_cu_electrocasnice_si_defecte(tmp_path):
    date_test = {
        "id": "test_imobil_appliances",
        "titlu": "Apartament cu Finisaje Premium & Electrocasnice",
        "adresa": "Bulevardul Unirii 10, București",
        "pret": 175000,
        "suprafata": 82.0,
        "moneda": "EUR",
        "audit_electrocasnice_finisaje": {
            "calitate_generala_finisaje": {
                "scor_global": 8.8,
                "clasa": "Premium",
                "concluzie": "Finisaje premium, materiale rezistente.",
            },
            "electrocasnice": [
                {
                    "aparat": "Frigider Side-by-Side",
                    "camera": "Bucătărie",
                    "brand_detectat": "Samsung",
                    "gama_brand": "Premium",
                    "pret_estimat_nou_eur": 1200,
                    "valoare_piata_actuala_eur": 900,
                },
                {
                    "aparat": "Plită Inducție",
                    "camera": "Bucătărie",
                    "brand_detectat": "Electrolux",
                    "gama_brand": "Mid-range",
                    "pret_estimat_nou_eur": 400,
                    "valoare_piata_actuala_eur": 300,
                },
            ],
            "defecte_si_probleme": [
                {
                    "element_afectat": "Silicon etanșare cadă",
                    "descriere_defect": "Înegrit ușor în colțul stâng",
                    "severitate": "Minor",
                    "cost_estimat_remediere_eur": 30,
                }
            ],
            "sumar_financiar": {
                "total_valoare_nou_electrocasnice_eur": 1600,
                "total_valoare_actuala_electrocasnice_eur": 1200,
                "total_buget_remediere_defecte_eur": 30,
                "impact_negociere_recomandat_eur": 30,
                "recomandare_evaluator": "Retuș sanitar minor recomandat la predare.",
            },
        },
    }

    pdf_out = str(tmp_path / "raport_electrocasnice_test.pdf")
    cale_rezultat = genereaza_raport_complet_pdf(date_test, cale_iesire=pdf_out)

    assert os.path.exists(cale_rezultat)
    assert os.path.getsize(cale_rezultat) > 5000
