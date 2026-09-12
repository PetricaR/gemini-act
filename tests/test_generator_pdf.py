import asyncio
import json
import os
from pathlib import Path

from gemini_act.agent.tools.imobiliare import (
    genereaza_raport_complet_pdf as agent_genereaza_pdf,
)
from gemini_act.imobiliare_mcp.generator_pdf import genereaza_raport_complet_pdf
from gemini_act.imobiliare_mcp.server import (
    genereaza_raport_complet_pdf as server_genereaza_pdf,
)


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


def test_server_genereaza_raport_complet_pdf_cu_date_suplimentare(tmp_path: Path) -> None:
    dest_pdf = str(tmp_path / "test_server_pdf.pdf")
    extra_data = {
        "titlu": "Apartament Lux Floreasca",
        "pret_total": 220000,
        "suprafata_utila": 75,
        "evaluare_anevar": {
            "valoare_estimata_piata": 215000,
            "interval_valoare_min": 205000,
            "interval_valoare_max": 225000,
            "ajustare_recomandata_procent": -2.2,
        },
    }
    res = server_genereaza_pdf(
        adresa_sau_identificator="Calea Floreasca 10, Bucuresti",
        date_suplimentare_json=json.dumps(extra_data),
        cale_salvare=dest_pdf,
    )
    assert res["status"] == "success"
    assert os.path.exists(res["cale_pdf"])
    assert os.path.getsize(res["cale_pdf"]) > 1000


def test_agent_tool_genereaza_raport_complet_pdf(tmp_path: Path) -> None:
    dest_pdf = str(tmp_path / "test_agent_pdf.pdf")
    extra_data = {
        "titlu": "Apartament 3 Camere Aviatiei",
        "pret_total": 185000,
        "suprafata_utila": 68,
    }

    res = asyncio.run(
        agent_genereaza_pdf(
            adresa_sau_identificator="Strada Nicolae Caramfil 20, Bucuresti",
            date_suplimentare_json=json.dumps(extra_data),
            cale_salvare=dest_pdf,
        )
    )
    assert res["status"] == "success"
    assert os.path.exists(res["cale_pdf"])


def test_genereaza_raport_complet_pdf_cu_poze_street_dict(tmp_path: Path) -> None:
    """Verifică generarea PDF când imagini_salvate este dict (formatul returnat de viziune_strada)."""
    # Create fake image files to verify image inclusion
    img1 = tmp_path / "streetview_h0.jpg"
    # Minimal 1x1 JPEG bytes
    img1.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4"
        b"\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00"
        b"\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
    )

    dest_pdf = str(tmp_path / "test_raport_streetview_dict.pdf")
    date_proprietate = {
        "id": "imobil-sv-dict",
        "titlu": "Apartament Unirii",
        "pret_total": 200000,
        "moneda": "EUR",
        "suprafata_utila": 80,
        "audit_exterior": {
            "status": "disponibil",
            "disponibil": True,
            "evaluare_globala_exterior": {
                "scor_calitate_cladire_si_fatada": 8,
                "scor_ambient_strada_si_zona": 7,
                "concluzie_audit_exterior": "Zonă urbană bine conectată.",
            },
            "cladire_si_fatada": {
                "stare_generala_fatada": "Bună, anvelopat recent",
            },
            "imagini_salvate": {
                "Fațadă și Vedere Nord": str(img1),
                "În lungul străzii (Est)": "fisier_inexistent.jpg",
            },
        },
    }

    cale_rezultat = genereaza_raport_complet_pdf(date_proprietate, cale_iesire=dest_pdf)
    assert os.path.exists(cale_rezultat)
    assert os.path.getsize(cale_rezultat) > 1000


def test_genereaza_raport_complet_pdf_cu_colectii_dict(tmp_path: Path) -> None:
    """Verifică că secțiunile nu crapă când liste precum comps sau elemente sunt dict-uri."""
    dest_pdf = str(tmp_path / "test_raport_dict_collections.pdf")
    date_proprietate = {
        "id": "imobil-dict-colls",
        "titlu": "Apartament Dict Collections",
        "pret_total": 150000,
        "moneda": "EUR",
        "suprafata_utila": 60,
        "evaluare_anevar": {
            "comparabile_utilizate": {
                "c1": {"id": "c1", "pret": 140000, "suprafata": 58, "pret_mp": 2413, "ajustare_neta_procent": 1.0},
            },
        },
        "audit_mobilier": {
            "elemente_identificate": {
                "e1": {"camera": "Living", "element": "Canapea", "material": "Textil", "nivel_calitate": "Medie"},
            },
        },
        "audit_electrocasnice": {
            "electrocasnice": {
                "el1": {"aparat": "Frigider", "camera": "Bucătărie", "pret_estimat_nou_eur": 600, "valoare_piata_actuala_eur": 300},
            },
            "defecte_si_probleme": {
                "d1": {"element_afectat": "Perete", "descriere_defect": "Fisură", "severitate": "Minoră", "cost_estimat_remediere_eur": 50},
            },
        },
        "audit_exterior": {
            "status": "disponibil",
            "disponibil": True,
            "imagini_salvate": {
                "cale": "imagine_fara_eticheta.jpg",
            },
        },
    }

    cale_rezultat = genereaza_raport_complet_pdf(date_proprietate, cale_iesire=dest_pdf)
    assert os.path.exists(cale_rezultat)
    assert os.path.getsize(cale_rezultat) > 1000


def _extrage_text_pdf_streams(cale_pdf: str) -> str:
    import base64
    import zlib
    with open(cale_pdf, "rb") as fp:
        raw = fp.read()
    parts = raw.split(b"endstream")
    all_txt = []
    for p in parts[:-1]:
        if b"stream" in p:
            s = p.split(b"stream")[1].strip()
            if not s.endswith(b"~>"):
                s += b"~>"
            if not s.startswith(b"<~"):
                s = b"<~" + s
            try:
                fl = zlib.decompress(base64.a85decode(s, adobe=True))
                all_txt.append(fl.decode("latin1", errors="ignore"))
            except Exception:
                pass
    return "\n".join(all_txt)


def test_genereaza_raport_complet_pdf_toate_cele_12_capitole(tmp_path: Path) -> None:
    """Verifică generarea completă a raportului cu DEMO_AUDIT_DATA și prezența tuturor celor 12 capitole numerotate."""
    from gemini_act.api.demo_data import DEMO_AUDIT_DATA

    dest_pdf = str(tmp_path / "test_raport_complet_12_capitole.pdf")
    cale_rezultat = genereaza_raport_complet_pdf(DEMO_AUDIT_DATA, cale_iesire=dest_pdf)
    assert os.path.exists(cale_rezultat)
    assert os.path.getsize(cale_rezultat) > 10000

    text_pdf = _extrage_text_pdf_streams(cale_rezultat)
    capitole_asteptate = [
        "1. Sintez",
        "2. Evaluare de Pia",
        "3. Localizare Urban",
        "4. Audit Exterior",
        "5. Audit Finisaje",
        "6. Catalog Electrocasnice",
        "7. Profil Dezvoltator",
        "8. Reputa",
        "9. Contextul Pie",
        "10. Checklist Tehnic",
        "11. Metodologie",
        "12. Concluzie Final",
    ]
    for ch in capitole_asteptate:
        num = ch.split(".")[0]
        kw = ch.split(".")[1].strip()
        assert (f"({num}." in text_pdf) or (f"{num}. " in text_pdf and kw in text_pdf), f"Capitolul {ch} nu a fost găsit în PDF!"


def test_genereaza_raport_complet_pdf_minimal_toate_cele_12_capitole(tmp_path: Path) -> None:
    """Verifică că un payload minim generează fără excepție toate cele 12 capitole cu carduri/tabele de fallback."""
    dest_pdf = str(tmp_path / "test_raport_minimal_12_capitole.pdf")
    minimal_data = {
        "id": "min-fallback-test",
        "titlu": "Garsonieră Centrală",
        "pret_total": 75000,
        "moneda": "EUR",
        "suprafata_utila": 38,
    }
    cale_rezultat = genereaza_raport_complet_pdf(minimal_data, cale_iesire=dest_pdf)
    assert os.path.exists(cale_rezultat)

    text_pdf = _extrage_text_pdf_streams(cale_rezultat)
    capitole_asteptate = [
        "1. Sintez",
        "2. Evaluare de Pia",
        "3. Localizare Urban",
        "4. Audit Exterior",
        "5. Audit Finisaje",
        "6. Catalog Electrocasnice",
        "7. Profil Dezvoltator",
        "8. Reputa",
        "9. Contextul Pie",
        "10. Checklist Tehnic",
        "11. Metodologie",
        "12. Concluzie Final",
    ]
    for ch in capitole_asteptate:
        num = ch.split(".")[0]
        kw = ch.split(".")[1].strip()
        assert (f"({num}." in text_pdf) or (f"{num}. " in text_pdf and kw in text_pdf), f"Capitolul {ch} lipsește din PDF-ul minimal!"

