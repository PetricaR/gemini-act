"""Unit tests for Targetare.ro financial analysis module."""

import pytest

from imobiliare.mcp.targetare import (
    analizeaza_sanatate_financiara,
    targetare_to_markdown,
    validate_tax_id,
)


def test_validate_tax_id() -> None:
    assert validate_tax_id("RO12345678") == "12345678"
    assert validate_tax_id("  cui: 9876543210  ") == "9876543210"
    with pytest.raises(ValueError):
        validate_tax_id("RO")
    with pytest.raises(ValueError):
        validate_tax_id("abcde")
    with pytest.raises(ValueError):
        validate_tax_id("")


def test_analizeaza_sanatate_financiara_healthy() -> None:
    data = {
        "stare": "ACTIVĂ",
        "cifra_afaceri": 10_000_000,
        "profit_net": 2_000_000,
        "datorii": 3_000_000,
        "capitaluri_proprii": 5_000_000,
        "angajati": 25,
    }
    analiza = analizeaza_sanatate_financiara(data)
    assert "Scăzut" in analiza["nivel_risc_insolventa"]
    assert analiza["scor_sanatate_financiara"] >= 8.0
    assert analiza["marja_profit_procent"] == 20.0
    assert analiza["este_spv_activ"] is False


def test_analizeaza_sanatate_financiara_insolvent() -> None:
    data = {
        "stare": "INSOLVENȚĂ",
        "cifra_afaceri": 1_000_000,
        "profit_net": -500_000,
        "datorii": 4_000_000,
        "angajati": 2,
    }
    analiza = analizeaza_sanatate_financiara(data)
    assert "Ridicat" in analiza["nivel_risc_insolventa"]
    assert analiza["scor_sanatate_financiara"] <= 4.0
    assert len(analiza["avertismente_risc"]) > 0


def test_analizeaza_sanatate_financiara_spv() -> None:
    data = {
        "stare": "ACTIVĂ",
        "cifra_afaceri": 5_000_000,
        "profit_net": 200_000,
        "datorii": 8_000_000,
        "angajati": 0,
    }
    analiza = analizeaza_sanatate_financiara(data)
    assert analiza["este_spv_activ"] is True
    assert any("SPV" in w for w in analiza["avertismente_risc"])


def test_targetare_to_markdown() -> None:
    firma = {
        "cui": "12345678",
        "denumire": "TEST DEVELOPMENT SRL",
        "stare": "ACTIVĂ",
        "adresa_completa": "Bucuresti, Sector 1",
        "cifra_afaceri": 20_000_000,
        "profit_net": 3_000_000,
        "datorii": 8_000_000,
        "angajati": 15,
        "analiza_financiara": {
            "scor_sanatate_financiara": 8.5,
            "nivel_risc_insolventa": "Scăzut",
            "marja_profit_procent": 15.0,
            "grad_indatorare_procent": 40.0,
            "este_spv_activ": False,
            "puncte_forte": ["Profitabilitate ridicată"],
            "avertismente_risc": [],
            "recomandare_cumparator": "Companie stabilă.",
        },
    }
    md = targetare_to_markdown(firma)
    assert "TEST DEVELOPMENT SRL" in md
    assert "12345678" in md
    assert "8.5 / 10" in md
    assert "Scăzut" in md
