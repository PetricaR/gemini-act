"""Unit tests for professional PDF report generator module."""

import os
from pathlib import Path

from gemini_act.imobiliare_mcp.generator_pdf import genereaza_raport_complet_pdf


def test_genereaza_raport_complet_pdf(tmp_path: Path) -> None:
    dest_pdf = str(tmp_path / "test_raport_complet.pdf")
    date_proprietate = {
        "id": "imobil-test-99",
        "titlu": "Penthouse Aviatiei Park",
        "pret_total": 350000,
        "moneda": "EUR",
        "suprafata_utila": 120,
        "adresa": "Soseaua Pipera 4, Bucuresti",
        "url": "https://www.imobiliare.ro/oferta/test-99",
        "evaluare_anevar": {
            "valoare_estimata_piata": 340000,
            "interval_valoare_min": 325000,
            "interval_valoare_max": 355000,
            "ajustare_recomandata_procent": -2.8,
            "comparabile_utilizate": [
                {
                    "id": "comp-1",
                    "pret": 330000,
                    "suprafata": 115,
                    "pret_mp": 2869,
                    "ajustare_neta_procent": 1.2,
                },
            ],
        },
        "audit_mobilier": {
            "scor_calitate_finisaje": 9.2,
            "valoare_estimata_mobilier_eur": 25000,
            "durabilitate_estimata_ani": 15,
            "sumar_calitate": "Mobilier custom din lemn masiv și MDF vopsit mat.",
            "elemente_identificate": [
                {
                    "camera": "Living",
                    "element": "Canapea piele",
                    "material": "Piele naturala",
                    "nivel_calitate": "Lux",
                },
            ],
        },
        "audit_exterior": {
            "scor_fatada": 9.5,
            "scor_strada": 9.0,
            "stare_fatada": "Nouă / Fără degradări",
            "concluzie_generala_exterior": "Zonă rezidențială aerisită, securizată.",
        },
        "specificatii_dezvoltator": {
            "dezvoltator": "Forte Partners",
            "constructor": "Strabag",
            "structura_rezistenta": "Diafragme beton armat",
        },
        "audit_targetare": {
            "status": "success",
            "date_firma": {
                "denumire": "FORTE PARTNERS SRL",
                "cui": "87654321",
                "stare": "ACTIVĂ",
                "adresa_completa": "Bucuresti",
                "cifra_afaceri": 80000000,
                "profit_net": 12000000,
                "datorii": 25000000,
                "angajati": 45,
                "analiza_financiara": {
                    "scor_sanatate_financiara": 9.1,
                    "nivel_risc_insolventa": "Scăzut",
                    "grad_indatorare_procent": 31.2,
                },
            },
        },
        "recenzii_google": {
            "status": "success",
            "locatie": {
                "nume": "Aviatiei Park",
                "rating_global": 4.7,
                "total_recenzii": 110,
                "analiza_sentiment": {
                    "scor_reputatie": 9.0,
                    "calificativ_reputatie": "Excelentă",
                    "puncte_forte_apreciate": ["Spații verzi generoase", "Pază 24/7"],
                    "probleme_reclamate_frecvent": ["Costuri mentenanță ridicate"],
                    "recomandare_cumparator": "Recomandat pentru segmentul premium.",
                },
            },
        },
    }

    cale_rezultat = genereaza_raport_complet_pdf(date_proprietate, cale_iesire=dest_pdf)
    assert os.path.exists(cale_rezultat)
    assert os.path.getsize(cale_rezultat) > 2000


def test_genereaza_raport_complet_pdf_minimal(tmp_path: Path) -> None:
    dest_pdf = str(tmp_path / "test_raport_minimal.pdf")
    minimal_data = {
        "id": "min-1",
        "titlu": "Garsoniera Titan",
        "pret_total": 55000,
        "moneda": "EUR",
        "suprafata_utila": 32,
    }
    cale_rezultat = genereaza_raport_complet_pdf(minimal_data, cale_iesire=dest_pdf)
    assert os.path.exists(cale_rezultat)
    assert os.path.getsize(cale_rezultat) > 1000
