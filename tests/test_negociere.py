from __future__ import annotations

from itertools import pairwise

import pytest

from gemini_act.imobiliare_mcp import negociere


def _listing(**overrides):
    base = {
        "price_eur": 179_000,
        "surface_sqm": 71.5,
        "rooms": 3,
        "year_built": 1982,
        "floor": 4,
        "floors_total": 8,
        "seller_type": "individual",
        "days_on_market": 30,
        "address_text": "Baba Novac, Sector 3",
    }
    base.update(overrides)
    return base


# -- The ladder -----------------------------------------------------------

def test_ladder_is_monotonic():
    """Opening < target < ceiling < walk-away, or the ladder is not a ladder."""
    scara = negociere.construieste_scara(179_000, 154_000)
    assert scara is not None
    assert scara.oferta_initiala < scara.pret_tinta
    assert scara.pret_tinta <= scara.pret_maxim < scara.walk_away


def test_target_equals_the_valuation_even_with_a_repair_estimate():
    """The repair estimate argues the opening offer; it must not move the target.

    The comparables behind the estimate are themselves unrenovated, so deducting
    a renovation budget from the value counts the same defect twice.
    """
    fara = negociere.construieste_scara(179_000, 154_000)
    cu_deviz = negociere.construieste_scara(179_000, 154_000, deviz_renovare=25_000)
    assert cu_deviz.pret_tinta == fara.pret_tinta == 154_000
    assert cu_deviz.walk_away == fara.walk_away


def test_overpriced_listing_is_anchored_on_the_asking_price():
    """12-16% under the asking price when overpriced, not 7% under the value."""
    scara = negociere.construieste_scara(179_000, 154_000)
    assert scara.context == "sever_supraevaluat"
    assert scara.oferta_initiala <= 154_000 * 0.94


def test_correctly_priced_listing_is_anchored_on_the_value():
    scara = negociere.construieste_scara(156_000, 154_000)
    assert scara.context == "corect"
    assert 154_000 * 0.92 <= scara.oferta_initiala <= 154_000 * 0.94


def test_no_valuation_means_no_ladder():
    """A strategy invented without a valuation is the failure mode, not a feature."""
    assert negociere.construieste_scara(179_000, None) is None
    plan = negociere.plan(_listing(), None)
    assert plan["disponibil"] is False
    assert "motiv" in plan


def test_budget_caps_the_walk_away_below_the_value():
    scara = negociere.construieste_scara(
        179_000, 154_000, buget_total_max=170_000, costuri_conexe=12_000,
        deviz_renovare=20_000,
    )
    assert scara.limitat_de_buget is True
    assert scara.walk_away == 138_000
    assert scara.pret_maxim <= scara.walk_away


def test_concessions_shrink():
    scara = negociere.construieste_scara(179_000, 154_000)
    pasi = [scara.oferta_initiala, *scara.concesii]
    incremente = [b - a for a, b in pairwise(pasi)]
    assert incremente == sorted(incremente, reverse=True)
    assert scara.concesii[-1] == scara.pret_tinta


# -- Seller profile -------------------------------------------------------

@pytest.mark.parametrize(
    ("suprascrieri", "cod"),
    [
        ({"seller_type": "developer"}, "dezvoltator"),
        ({"price_dropped": True}, "corectie_fortata"),
        ({"vacant": True}, "presiune_costuri"),
        ({"days_on_market": 150}, "testeaza_piata"),
        ({"seller_type": "agency"}, "agentie"),
        ({"seller_type": "individual"}, "particular"),
    ],
)
def test_profile_is_read_from_the_listing_signals(suprascrieri, cod):
    assert negociere.profil_vanzator(_listing(**suprascrieri)).cod == cod


def test_profile_without_signals_is_not_the_most_exploitable_one():
    """Absence of evidence is not evidence of a distressed seller."""
    profil = negociere.profil_vanzator({"price_eur": 100_000})
    assert profil.cod == "particular"
    assert profil.agresivitate_pct[0] == 0.0


# -- Levers and red flags -------------------------------------------------

def test_levers_match_findings_regardless_of_diacritics():
    cu_diacritice = negociere.parghii_din_constatari(["Instalație electrică pe aluminiu"])
    fara = negociere.parghii_din_constatari(["instalatie electrica pe aluminiu"])
    assert [x.nume for x in cu_diacritice] == [x.nume for x in fara]
    assert len(cu_diacritice) == 1


def test_each_lever_fires_once():
    """Three remarks about damp are one hydro-insulation job."""
    gasite = negociere.parghii_din_constatari(
        ["urme de igrasie", "mucegai în baie", "infiltrații la colț"]
    )
    assert len(gasite) == 1


def test_seismic_flag_asks_for_a_check_and_never_asserts_a_class():
    steaguri = negociere.steaguri_rosii(_listing(year_built=1972))
    seismic = [x for x in steaguri if "1978" in x.problema]
    assert seismic and seismic[0].abandon is False
    assert "AMCCRS" in seismic[0].masura


def test_post_1978_building_raises_no_seismic_flag():
    steaguri = negociere.steaguri_rosii(_listing(year_built=1985, floor=3))
    assert not any("1978" in x.problema for x in steaguri)


def test_no_findings_means_no_invented_defects():
    plan = negociere.plan(_listing(), 154_000, constatari=[])
    assert plan["parghii"] == []
    assert plan["scara"]["deviz_aplicat_eur"] is None


# -- Provenance -----------------------------------------------------------

def test_every_figure_carries_its_qualification():
    """A market convention rendered like a measurement is worse than no number."""
    plan = negociere.plan(_listing(), 154_000, constatari=["instalatie electrica pe aluminiu"])
    assert plan["scara"]["calificare"] in negociere.CALIFICARI
    assert plan["scara"]["provenienta"] in {"masurat", "estimat", "anunt"}
    assert "nu o măsurătoare a acestui imobil" in plan["sursa"]
    for parghie in plan["parghii"]:
        assert parghie["calificare"] in negociere.CALIFICARI


def test_checklists_branch_on_the_construction_era():
    vechi = negociere.verificari(_listing(year_built=1982))
    nou = negociere.verificari(_listing(year_built=2022, is_new_build=True))
    assert any("AMCCRS" in x for x in vechi["structurale"])
    assert any("ISC" in x for x in nou["structurale"])
    assert vechi["juridice"] == nou["juridice"]


def test_scripts_are_returned_as_text_and_never_sent():
    plan = negociere.plan(_listing(), 154_000)
    assert set(plan["scripturi"]) == {"proprietar", "agent", "dezvoltator"}
    for text in plan["scripturi"].values():
        assert "{" not in text  # every placeholder filled
        assert isinstance(text, str)


def test_decision_rule_quotes_the_ladder():
    plan = negociere.plan(_listing(), 154_000)
    regula = plan["regula_decizionala"]
    for cheie in ("pret_listat_eur", "oferta_initiala_eur", "walk_away_eur"):
        valoare = plan["scara"][cheie]
        assert f"{valoare:,.0f}".replace(",", ".") in regula


# -- What reaches the model's context -------------------------------------

def test_compact_strategy_drops_the_prose_but_keeps_the_numbers():
    """Three draft offers and three checklists belong in the report, not in every
    valuation's return value."""
    from gemini_act.imobiliare_mcp.server import _strategie_pe_scurt

    plan = negociere.plan(_listing(), 154_000, constatari=["instalatie electrica pe aluminiu"])
    scurt = _strategie_pe_scurt(plan)

    assert scurt["scara"] == plan["scara"]
    assert scurt["regula_decizionala"] == plan["regula_decizionala"]
    assert "scripturi" not in scurt
    assert "verificari" not in scurt
    assert "reguli_de_aur" not in scurt
    assert scurt["parghii"] == ["Instalație electrică pe conductori de aluminiu"]
    assert len(repr(scurt)) < len(repr(plan)) / 2


def test_compact_strategy_passes_an_unavailable_plan_through_unchanged():
    from gemini_act.imobiliare_mcp.server import _strategie_pe_scurt

    plan = negociere.plan(_listing(), None)
    assert _strategie_pe_scurt(plan) == plan
