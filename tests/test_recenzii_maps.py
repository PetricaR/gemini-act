"""Unit tests for Google Maps reviews analysis module."""

from imobiliare.mcp.recenzii_maps import (
    _analiza_reguli_fallback,
    recenzii_to_markdown,
)


def test_analiza_reguli_fallback_pozitiva() -> None:
    date_locatie = {
        "nume": "Ansamblu Modern",
        "rating_global": 4.8,
        "total_recenzii": 50,
        "recenzii": [
            {
                "autor": "Andrei",
                "stele": 5,
                "text": "Finisaje premium, predare exact la timp, recomand cu caldura!",
            },
            {
                "autor": "Elena",
                "stele": 5,
                "text": "Curatenie, parcare subterana spatioasa, foarte multumita.",
            },
        ],
    }
    analiza = _analiza_reguli_fallback(date_locatie)
    assert analiza["scor_reputatie"] >= 8.5
    assert analiza["calificativ_reputatie"] in ("Excelentă", "Bună")
    assert len(analiza["puncte_forte_apreciate"]) > 0


def test_analiza_reguli_fallback_probleme() -> None:
    date_locatie = {
        "nume": "Complex Neterminat",
        "rating_global": 2.5,
        "total_recenzii": 30,
        "recenzii": [
            {
                "autor": "Mihai",
                "stele": 1,
                "text": "Intarziere de 1 an de zile, pereti subtiri, se aude tot de la vecini.",
            },
            {
                "autor": "Ioana",
                "stele": 2,
                "text": "Infiltratii la subsol si lipsa locuri parcare promise.",
            },
        ],
    }
    analiza = _analiza_reguli_fallback(date_locatie)
    assert analiza["scor_reputatie"] <= 5.5
    assert len(analiza["probleme_reclamate_frecvent"]) > 0
    assert any("izolație" in p.lower() or "fonic" in p.lower() or "pereți" in p.lower()
               for p in analiza["probleme_reclamate_frecvent"])
    assert any("infiltrații" in p.lower() or "subsol" in p.lower()
               for p in analiza["probleme_reclamate_frecvent"])


def test_recenzii_to_markdown() -> None:
    data = {
        "nume": "Rezidenta Florilor",
        "adresa": "Strada Florilor 5, Bucuresti",
        "rating_global": 4.5,
        "total_recenzii": 42,
        "recenzii": [
            {"autor": "Radu", "stele": 5, "text": "Excelent!"},
        ],
        "analiza_sentiment": {
            "scor_reputatie": 8.7,
            "calificativ_reputatie": "Bună",
            "puncte_forte_apreciate": ["Calitate construcție"],
            "probleme_reclamate_frecvent": ["Trafic intens la ieșire"],
            "recomandare_cumparator": "Recomandat după verificarea locului de parcare.",
        },
    }
    md = recenzii_to_markdown(data)
    assert "Rezidenta Florilor" in md
    assert "4.5" in md
    assert "8.7 / 10" in md
    assert "Calitate construcție" in md
