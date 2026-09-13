from __future__ import annotations

from gemini_act.imobiliare_mcp import costuri


def test_notary_fee_uses_the_documented_bracket_above_the_threshold():
    """Above 600.001 lei the grid is published, so the figure is a fact."""
    post = costuri.onorariu_notarial(160_000)
    assert post.calificare == "FAPT"
    assert post.minim == post.maxim
    # 160.000 EUR * 5 = 800.000 lei -> 6.405 + 0,6% * 199.999 lei
    asteptat = (6_405 + (800_000 - 600_001) * 0.006) / 5
    assert post.minim == asteptat


def test_notary_fee_below_the_threshold_is_a_labelled_range():
    """The lower brackets are not in the source, so they are not invented."""
    post = costuri.onorariu_notarial(50_000)
    assert post.calificare == "ESTIMARE"
    assert post.minim < post.maxim
    assert "nu este reprodusă" in post.temei


def test_vat_is_applied_to_the_notary_fee_and_dated():
    tranzactie = costuri.costuri_tranzactionare(160_000)
    tva = [p for p in tranzactie["posturi"] if p["componenta"].startswith("TVA")][0]
    assert "2025-08-01" in tva["temei"]
    assert tva["calificare"] == "FAPT"


def test_agency_commission_only_when_it_applies():
    fara = costuri.costuri_tranzactionare(160_000)
    cu = costuri.costuri_tranzactionare(160_000, prin_agentie=True)
    etichete = [p["componenta"] for p in fara["posturi"]]
    assert not any("agenție" in e for e in etichete)
    assert cu["total_estimat_eur"] > fara["total_estimat_eur"]


def test_seller_transfer_tax_is_reported_but_not_added_to_the_buyer_total():
    tranzactie = costuri.costuri_tranzactionare(160_000)
    assert tranzactie["impozit_transfer_vanzator_pct"]["peste_3_ani"] == 1.0
    etichete = [p["componenta"] for p in tranzactie["posturi"]]
    assert not any("transfer" in e.lower() for e in etichete)


def test_holding_costs_refuse_to_invent_maintenance():
    """The dossier used to multiply the surface by a constant and print it."""
    detinere = costuri.costuri_detinere(71.5)
    intretinere = [p for p in detinere["posturi"] if "Întreținere" in p["componenta"]][0]
    assert intretinere["minim_eur"] is None
    assert intretinere["provenienta"] == "indisponibil"
    assert "listele de plată" in intretinere["motiv_indisponibil"]


def test_new_build_adds_the_documented_management_contract():
    vechi = costuri.costuri_detinere(71.5, bloc_nou=False)
    nou = costuri.costuri_detinere(71.5, bloc_nou=True)
    assert vechi["disponibil"] is False
    assert nou["disponibil"] is True
    assert nou["total_anual_minim_eur"] == 720


def test_consolidated_budget_exceeds_the_price():
    buget = costuri.buget_consolidat(160_000, 71.5, 3)
    assert buget["total_minim_eur"] > 160_000
    assert buget["costuri_conexe_eur"] > 0


def test_known_repair_estimate_replaces_the_generic_renovation_band():
    generic = costuri.buget_consolidat(160_000, 71.5, 3)
    cu_deviz = costuri.buget_consolidat(160_000, 71.5, 3, deviz_renovare_eur=18_000)
    etichete = [p["componenta"] for p in cu_deviz["posturi"]]
    assert "Renovare (deviz aplicat)" in etichete
    assert "Renovare capitală (dacă este necesară)" not in etichete
    assert generic["total_maxim_eur"] > cu_deviz["total_maxim_eur"]


def test_no_price_means_no_budget():
    for rezultat in (costuri.buget_consolidat(None, 70, 3), costuri.costuri_tranzactionare(None)):
        assert rezultat["disponibil"] is False
        assert rezultat["provenienta"] == "indisponibil"


def test_every_post_states_its_legal_or_market_basis():
    buget = costuri.buget_consolidat(160_000, 71.5, 3, prin_agentie=True, cu_credit=True)
    for post in buget["posturi"] + buget["tranzactionare"]["posturi"]:
        assert post["temei"], f"{post['componenta']} nu declară pe ce se bazează"
        assert post["calificare"] in {"FAPT", "ESTIMARE"}


def test_a_repair_estimate_of_zero_is_a_finding_not_a_missing_value():
    # The visual inspection concluding "nothing to repair" used to be
    # indistinguishable from having no inspection at all: both fell through to
    # the generic 350-500 EUR/mp band, which on a move-in-ready 70 sqm flat
    # added ~30.000 EUR to a budget the walk-away threshold is computed from.
    zero = costuri.buget_consolidat(209_000, 70.0, 3, deviz_renovare_eur=0)
    etichete = [p["componenta"] for p in zero["posturi"]]
    assert "Renovare capitală (dacă este necesară)" not in etichete
    linie = next(p for p in zero["posturi"] if p["componenta"] == "Renovare (deviz aplicat)")
    assert linie["mediu_eur"] == 0
    assert "nu a identificat defecte" in linie["temei"]

    fara_inspectie = costuri.buget_consolidat(209_000, 70.0, 3, deviz_renovare_eur=None)
    assert "Renovare capitală (dacă este necesară)" in [
        p["componenta"] for p in fara_inspectie["posturi"]
    ]
    assert fara_inspectie["costuri_conexe_eur"] > zero["costuri_conexe_eur"]


def test_a_furnished_flat_is_not_budgeted_to_be_furnished_again():
    # The furniture is already inside the asking price.
    mobilat = costuri.buget_consolidat(209_000, 70.0, 3, include_mobilare=False)
    assert "Mobilare și electrocasnice" not in [p["componenta"] for p in mobilat["posturi"]]
    nemobilat = costuri.buget_consolidat(209_000, 70.0, 3, include_mobilare=True)
    assert nemobilat["costuri_conexe_eur"] - mobilat["costuri_conexe_eur"] > 15_000
