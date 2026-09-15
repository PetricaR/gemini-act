import asyncio
import json
import os
from pathlib import Path

from imobiliare.agent_tools.imobiliare import (
    genereaza_raport_complet_pdf as agent_genereaza_pdf,
)
from imobiliare.mcp.generator_pdf import genereaza_raport_complet_pdf
from imobiliare.mcp.server import (
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
    from imobiliare.api.demo_data import DEMO_AUDIT_DATA

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



# ---------------------------------------------------------------------------
# Typography, images and report arithmetic
# ---------------------------------------------------------------------------


def test_fontul_acopera_alfabetul_romanesc() -> None:
    """ă, ș and ț are outside Latin-1, so the standard PDF fonts cannot draw them.

    This is the regression guard for the black boxes that used to fill every
    heading and table cell of the report.
    """
    from reportlab.pdfbase import pdfmetrics

    from imobiliare.mcp import generator_pdf

    assert generator_pdf.FONT_REGULAR != "Helvetica", "fontul Unicode nu a fost înregistrat"
    cmap = pdfmetrics.getFont(generator_pdf.FONT_REGULAR).face.charToGlyph
    lipsa = [ch for ch in "ăâîșțĂÂÎȘȚ€" if ord(ch) not in cmap]
    assert not lipsa, f"fontul nu acoperă {lipsa}"


def test_txt_inlocuieste_glifele_nedesenabile() -> None:
    """Anything the font cannot draw is substituted or dropped, never boxed."""
    from reportlab.pdfbase import pdfmetrics

    from imobiliare.mcp.generator_pdf import FONT_REGULAR, _txt

    cmap = pdfmetrics.getFont(FONT_REGULAR).face.charToGlyph
    iesire = _txt("Rating 4.6 ★ • preț → 209.000 € ⚠️ 🏠 ş/ţ")
    assert all(ord(ch) in cmap for ch in iesire), iesire
    # Cedilla forms normalise to the comma-below letters Romanian actually uses.
    assert "ș" in iesire and "ț" in iesire
    assert "€" in iesire


def test_textul_dosarului_este_integral_desenabil() -> None:
    """Every character the demo dossier carries must survive `_txt` drawable.

    Walks the real payload rather than a sample, so a new field carrying an
    emoji or a cedilla is caught here instead of as a black box in the PDF.
    """
    from reportlab.pdfbase import pdfmetrics

    from imobiliare.api.demo_data import DEMO_AUDIT_DATA
    from imobiliare.mcp.generator_pdf import FONT_REGULAR, _txt

    cmap = pdfmetrics.getFont(FONT_REGULAR).face.charToGlyph

    def siruri(valoare):
        if isinstance(valoare, str):
            yield valoare
        elif isinstance(valoare, dict):
            for cheie, sub in valoare.items():
                yield cheie
                yield from siruri(sub)
        elif isinstance(valoare, (list, tuple)):
            for sub in valoare:
                yield from siruri(sub)

    for original in siruri(DEMO_AUDIT_DATA):
        curatat = _txt(original)
        nedesenabile = [ch for ch in curatat if ord(ch) not in cmap and ch not in "\n\r\t"]
        assert not nedesenabile, f"{original!r} păstrează {nedesenabile}"


def test_imaginea_pastreaza_proportiile(tmp_path: Path) -> None:
    """A photo is fitted inside its box, never stretched to fill it."""
    from PIL import Image as PILImage

    from imobiliare.mcp.generator_pdf import _imagine_incadrata

    sursa = tmp_path / "lata.png"
    PILImage.new("RGB", (400, 100), "white").save(sursa)  # 4:1

    img = _imagine_incadrata(str(sursa), 200, 200)
    assert img is not None
    assert img.drawWidth == 200, "lățimea trebuie să atingă limita"
    assert abs(img.drawHeight - 50) < 0.01, "înălțimea trebuie să urmeze proporția 4:1"


def test_coloanele_fara_valori_sunt_eliminate() -> None:
    """A column whose every cell is a dash is dropped and its width reallocated."""
    from imobiliare.mcp.generator_pdf import _elimina_coloane_goale

    randuri = [
        ["Anunț", "Dată", "Preț"],
        ["Comp 1", "-", "325.000"],
        ["Comp 2", "-", "310.000"],
    ]
    noi_randuri, noi_latimi = _elimina_coloane_goale(randuri, [100, 50, 100])
    assert noi_randuri[0] == ["Anunț", "Preț"]
    assert sum(noi_latimi) == 250, "lățimea recuperată trebuie redistribuită"

    # A column with at least one real value stays.
    randuri[1][1] = "aprilie 2026"
    pastrate, _ = _elimina_coloane_goale(randuri, [100, 50, 100])
    assert pastrate[0] == ["Anunț", "Dată", "Preț"]


def test_noi_este_derivat_cand_lipseste_din_date(tmp_path: Path) -> None:
    """NOI used to print as 0 EUR/an under a real rent because of a key mismatch."""
    dest = str(tmp_path / "venit.pdf")
    date = {
        "id": "noi-test",
        "titlu": "Apartament Test",
        "pret_total": 300000,
        "suprafata_utila": 100,
        "evaluare_anevar": {
            "valoare_estimata_piata": 290000,
            "comparabile_utilizate": [{"id": "c1", "pret": 1, "suprafata": 1}],
            "abordare_venit": {
                "chirie_lunara_estimata_eur": 1000,
                "grad_neocupare_procent": 0.0,
                "cheltuieli_operationale_procent": 0.0,
                "venit_net_anual_eur": 12000,
            },
        },
    }
    text = _extrage_text_pdf_streams(genereaza_raport_complet_pdf(date, cale_iesire=dest))
    assert "12,000 EUR/an" in text
    assert "(0 EUR/an)" not in text and " 0 EUR/an" not in text


def test_ecartul_fata_de_piata_are_semnul_corect(tmp_path: Path) -> None:
    """An asking price above the estimate is reported as above it.

    The recommended correction (negative) used to be printed under the label of
    the excess, giving "cu -4,9% peste nivelul pieței".
    """
    dest = str(tmp_path / "ecart.pdf")
    date = {
        "id": "ecart-test",
        "titlu": "Apartament Test",
        "pret_total": 345000,
        "suprafata_utila": 100,
        "scor_general": 8.0,
        "evaluare_anevar": {
            "valoare_estimata_piata": 328000,
            "ajustare_recomandata_procent": -4.9,
            "marja_negociere_eur": 17000,
            "comparabile_utilizate": [{"id": "c1", "pret": 1, "suprafata": 1}],
        },
    }
    text = _extrage_text_pdf_streams(genereaza_raport_complet_pdf(date, cale_iesire=dest))
    assert "5.2% peste valoarea estimat" in text
    assert "-4.9% peste" not in text


def test_reconcilierea_afiseaza_suma_ponderata(tmp_path: Path) -> None:
    """The contributions column must add up to the row that totals it."""
    dest = str(tmp_path / "reconciliere.pdf")
    date = {
        "id": "rec-test",
        "titlu": "Apartament Test",
        "pret_total": 345000,
        "suprafata_utila": 100,
        "evaluare_anevar": {
            "valoare_estimata_piata": 328000,
            "comparabile_utilizate": [{"id": "c1", "pret": 1, "suprafata": 1}],
            "abordare_venit": {"valoare_prin_venit_eur": 319500},
            "abordare_cost": {"valoare_prin_cost_eur": 335660},
            "reconciliere": {
                "pondere_comparatie_procent": 70,
                "pondere_venit_procent": 25,
                "pondere_cost_procent": 5,
            },
        },
    }
    text = _extrage_text_pdf_streams(genereaza_raport_complet_pdf(date, cale_iesire=dest))
    # 328.000*0,70 + 319.500*0,25 + 335.660*0,05 = 326.258
    assert "326,258" in text, "suma ponderată a abordărilor lipsește"
