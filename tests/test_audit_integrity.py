from __future__ import annotations

import ast
import inspect

import pytest

from gemini_act.imobiliare_mcp import (
    anevar,
    costuri,
    dezvoltator,
    electrocasnice_finisaje,
    generator_pdf,
    negociere,
    recenzii_maps,
    server,
    targetare,
)


def test_no_hardcoded_cui_or_developer_in_server():
    """Asigură că nu mai există CUI-uri sau companii inventate hardcodate în server.py."""
    source = inspect.getsource(server)
    assert "RO32158490" not in source
    assert "HABITAT GROUP ESTATE" not in source
    assert "t_fallback" not in source
    assert "rec_fallback" not in source
    assert "ef_fallback" not in source


# -- No invented values anywhere in the dossier pipeline -------------------

def _cod_fara_comentarii(modul) -> str:
    """Executable source only -- comments and docstrings removed.

    The forbidden strings below are named in the comments and docstrings that
    explain why they were removed, and in the model prompts that list example
    brands for *recognition*. None of that is the code asserting them about a
    property, so only what actually runs is searched.
    """
    tree = ast.parse(inspect.getsource(modul))
    for nod in ast.walk(tree):
        if not isinstance(nod, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        corp = nod.body
        if (corp and isinstance(corp[0], ast.Expr)
                and isinstance(corp[0].value, ast.Constant)
                and isinstance(corp[0].value.value, str)):
            corp.pop(0)
            if not corp:
                corp.append(ast.Pass())
    # ast.unparse drops comments for free.
    return ast.unparse(tree)


@pytest.mark.parametrize(
    "modul",
    [server, generator_pdf, dezvoltator, targetare, recenzii_maps, negociere, costuri],
)
def test_no_fabricated_constants_in_the_dossier_pipeline(modul):
    """A grep for the invented values that used to be emitted as findings.

    Only the ones that can never be legitimate: a headline verdict, a company
    name that fed the solvency lookup, an invented price and an invented
    address. Numeric and brand stand-ins are covered by the behaviour tests
    below instead, because those strings do appear legitimately in the model
    prompts that ask the model to *recognise* such brands.
    """
    source = _cod_fara_comentarii(modul)
    interzise = [
        "FOARTE BUN - INVESTIȚIE SIGURĂ",   # headline verdict for every property
        "oportunitate validată",            # unconditional closing recommendation
        "Habitat Group Estate",             # invented developer -> fed the CUI lookup
        "Habitat Construct",
        "136488",                           # invented asking price
        "Theodor Pallady",                  # invented address
    ]
    for termen in interzise:
        assert termen not in source, (
            f"{modul.__name__} conține din nou valoarea inventată {termen!r}"
        )


def test_missing_score_is_never_rendered_as_a_mid_range_default():
    """`.get(key, 7.0)` reads a company nobody could look up as "stable"."""
    for modul in (generator_pdf, targetare, recenzii_maps):
        source = inspect.getsource(modul)
        assert ", 7.0)" not in source, f"{modul.__name__}: scor implicit 7.0 reintrodus"


def test_company_without_financials_gets_no_score():
    """Absence of data is not evidence of health."""
    analiza = targetare.analizeaza_sanatate_financiara({})
    assert analiza["status"] == "indisponibil"
    assert analiza["disponibil"] is False
    assert analiza["scor_sanatate_financiara"] is None
    assert analiza["nivel_risc_insolventa"] is None
    assert analiza["motiv"]


def test_listing_without_developer_info_reports_unavailable():
    """An invented developer name feeds the Targetare lookup and the reviews
    query, producing a due-diligence section about an unrelated company."""
    res = dezvoltator.extract_developer_and_constructor_info(
        descriere="Apartament luminos, zonă liniștită.", titlu="Apartament 2 camere"
    )
    analiza = res["analiza_dezvoltator"]
    assert analiza["dezvoltator"] is None
    assert analiza["constructor"] is None
    assert analiza["structura_rezistenta"] is None
    assert analiza["tamplarie"] is None


def test_overall_score_is_none_when_nothing_was_measured():
    scor, calificativ, baza = server._scor_general({})
    assert scor is None
    assert "INDISPONIBIL" in calificativ
    assert baza == []

    scor, calificativ, baza = server._scor_general({
        "evaluare_anevar": {"status": "indisponibil", "disponibil": False},
        "audit_targetare": {"status": "indisponibil", "disponibil": False},
        "recenzii_google": {"status": "indisponibil", "disponibil": False},
        "audit_electrocasnice_finisaje": {"status": "indisponibil", "disponibil": False},
    })
    assert scor is None
    assert baza == []


def test_overall_score_follows_the_sections_that_did_measure():
    scor, calificativ, baza = server._scor_general({
        "evaluare_anevar": {"status": "disponibil", "ajustare_recomandata_procent": -6.0},
        "audit_electrocasnice_finisaje": {
            "status": "success", "calitate_generala_finisaje": {"scor_global": 8},
        },
    })
    assert scor is not None
    assert baza == ["evaluare ANEVAR", "audit finisaje"]


def test_overpriced_listing_is_not_described_as_aligned_with_the_market():
    assert "supraevaluat" in server._verdict_piata(25.0)
    assert "peste valoarea" in server._verdict_piata(6.0)
    assert "aliniat" in server._verdict_piata(-1.0)
    assert "oportunitate" in server._verdict_piata(-12.0)


# -- The PDF must survive every "unavailable" combination ------------------

@pytest.mark.parametrize(
    ("nume", "date"),
    [
        ("gol", {}),
        ("evaluare indisponibilă", {
            "id": "x", "titlu": "t", "adresa": "a", "moneda": "EUR",
            "evaluare_anevar": {"status": "indisponibil", "disponibil": False, "motiv": "m"},
        }),
        ("ajustare nulă", {
            "id": "y", "titlu": "t", "adresa": "a", "moneda": "EUR",
            "evaluare_anevar": {
                "status": "disponibil", "disponibil": True,
                "valoare_estimata_piata": 100000, "ajustare_recomandata_procent": None,
            },
        }),
        ("toate secțiunile indisponibile", {
            "id": "z", "titlu": "t", "adresa": "a", "moneda": "EUR",
            "evaluare_anevar": {"status": "indisponibil", "disponibil": False, "motiv": "m"},
            "audit_targetare": {"status": "indisponibil", "disponibil": False, "motiv": "m"},
            "recenzii_google": {"status": "indisponibil", "disponibil": False, "motiv": "m"},
            "audit_exterior": {"status": "indisponibil", "disponibil": False, "motiv": "m"},
            "specificatii_dezvoltator": {},
        }),
    ],
)
def test_pdf_generates_for_every_unavailable_combination(tmp_path, nume, date):
    """The unavailable path used to be the one input that crashed the renderer
    (UnboundLocalError on val_min / TypeError on a null adjustment)."""
    cale = generator_pdf.genereaza_raport_complet_pdf(
        date, cale_iesire=str(tmp_path / f"{abs(hash(nume))}.pdf")
    )
    assert cale
    assert (tmp_path / cale.rsplit("/", 1)[-1]).stat().st_size > 1000


def test_anevar_requires_minimum_3_comparables():
    """Standardul GEV 630 cere cel puțin 3 comparabile.

    Sub 3, valoarea trebuie să fie None / indisponibilă.
    """
    subject = {
        "title": "Apartament test",
        "rooms": 2,
        "surface_sqm": 50.0,
        "price_eur": 100000.0,
        "price_per_sqm": 2000.0,
        "year_built": 2020,
        "floor": 3,
        "total_floors": 8,
    }
    # Doar 2 comparabile (sub minimul de 3 cerut de GEV 630)
    comps = [
        {
            "id": "c1",
            "title": "Comp 1",
            "price_eur": 105000.0,
            "surface_sqm": 52.0,
            "rooms": 2,
            "year_built": 2020,
            "floor": 2,
            "total_floors": 8,
        },
        {
            "id": "c2",
            "title": "Comp 2",
            "price_eur": 98000.0,
            "surface_sqm": 48.0,
            "rooms": 2,
            "year_built": 2019,
            "floor": 4,
            "total_floors": 8,
        },
    ]

    p = anevar.Params()
    val = anevar.evaluate(subject, comps, [], p)
    assert val.sufficient_comps is False
    assert val.market_value is None
    assert val.final_value is None
    assert val.reliability == "insuficienta"


def test_certitudine_brand_mentionat_in_anunt():
    """Brandurile extrase din textul anunțului primesc strict
    'mentionat_in_anunt', niciodată 'sigur'.
    """
    subject = {
        "title": "Apartament cu electrocasnice Bosch",
        "description": "Bucătărie complet mobilată și utilată Bosch.",
    }
    res = electrocasnice_finisaje._analiza_reguli_fallback(subject)
    assert len(res["electrocasnice"]) == 1
    item = res["electrocasnice"][0]
    assert item["certitudine_brand"] == "mentionat_in_anunt"
    assert item["certitudine_brand"] != "sigur"


def test_fallback_no_silent_defect_fabrication():
    """Dacă nu sunt menționate defecte în text și nu există poze, defectele
    sunt goale (nu se inventează plinte dezlipite).
    """
    subject = {
        "title": "Apartament curat",
        "description": "Apartament renovat, luminos, zonă liniștită.",
    }
    res = electrocasnice_finisaje._analiza_reguli_fallback(subject)
    assert res["defecte_si_probleme"] == []
    assert res["electrocasnice"] == []
    assert res["calitate_generala_finisaje"]["concluzie"].startswith("Analiză bazată exclusiv")


# -- The dossier no longer substitutes defaults for unmeasured sections ----

def test_pdf_does_not_fabricate_market_esg_or_risk_defaults():
    """Every one of these was printed for properties nobody had data for.

    A generated dossier asserted a BREEAM certification, an energy class, a
    yearly price trend and three risks with probabilities attached -- next to
    figures that were real, which is what made them credible.
    """
    source = _cod_fara_comentarii(generator_pdf)
    interzise = [
        "BREEAM Excellent / NZEB",              # certification nobody holds a certificate for
        "115.4",                                 # specific energy consumption
        "Stabilă / Creștere moderată",          # market trend with no time series behind it
        "Vicii ascunse la instalațiile îngropate",   # risk with an invented probability
        "Conform cod seismic P100-1; absență risc inundație.",
    ]
    for termen in interzise:
        assert termen not in source, (
            f"generator_pdf conține din nou valoarea inventată {termen!r}"
        )


def test_unmeasured_market_indicators_are_marked_not_guessed():
    """No time series means no annual variation -- and the block has to say so."""
    piata = server._analiza_piata("titan", [
        {"price_per_sqm": 2000, "days_on_market": 40},
        {"price_per_sqm": 2100, "days_on_market": 80},
    ])
    assert piata["pret_mediu_zona_eur_mp"] == 2050
    assert piata["variatie_anuala_procent"] is None
    assert piata["tendinta"] is None
    assert piata["motiv_tendinta"]


def test_market_block_without_prices_is_unavailable_not_empty():
    piata = server._analiza_piata("titan", [])
    assert piata["disponibil"] is False
    assert piata["provenienta"] == "indisponibil"


# -- The sample and a generated dossier have the same shape ---------------

# Sections every dossier must carry a value for.
SECTIUNI_DOSAR = (
    "strategie_negociere",
    "buget_consolidat",
    "costuri_tranzactionare",
    "costuri_detinere",
    "rezumat_executiv",
    "metodologie",
    "ipoteze_limitative",
)

# Sections that must exist but may legitimately be empty: a property with no
# measured advantage has no strengths, and inventing one is the failure mode.
SECTIUNI_POT_FI_GOALE = ("puncte_forte", "puncte_slabe")


def test_generated_dossier_carries_every_section_the_renderers_read():
    """The sample used to be the only dossier that looked complete.

    Its market, cost and summary blocks were authored by hand and nothing
    produced them for a real listing, so the PDF filled those sections with
    defaults and the web UI left them blank.
    """
    date = {
        "titlu": "Apartament 3 camere",
        "pret_total": 179_000,
        "suprafata_utila": 71.5,
        "camere": 3,
        "an_constructie": 1982,
        "etaj": "Etaj 4 din 8",
        "evaluare_anevar": {
            "disponibil": True,
            "valoare_estimata_piata": 154_000,
            "ajustare_recomandata_procent": 16.2,
        },
    }
    server._completeaza_strategie(date, None)
    for cheie in SECTIUNI_DOSAR:
        assert date.get(cheie), f"dosarul generat nu conține secțiunea {cheie!r}"
    for cheie in SECTIUNI_POT_FI_GOALE:
        assert cheie in date, f"dosarul generat nu conține secțiunea {cheie!r}"
    assert date["strategie_negociere"]["scara"]["walk_away_eur"]
    # Overpriced, so the weakness is stated and no strength is invented.
    assert date["puncte_slabe"]
    assert date["puncte_forte"] == []


def test_demo_and_generated_dossiers_expose_the_same_sections():
    from gemini_act.api.demo_data import DEMO_AUDIT_DATA

    demo = dict(DEMO_AUDIT_DATA)
    server._completeaza_strategie(demo, None)
    for cheie in SECTIUNI_DOSAR + SECTIUNI_POT_FI_GOALE:
        assert demo.get(cheie), f"setul demo nu conține secțiunea {cheie!r}"


def test_dossier_without_a_valuation_says_so_instead_of_offering_a_price():
    date = {
        "titlu": "Apartament",
        "pret_total": 179_000,
        "evaluare_anevar": {"disponibil": False, "motiv": "eșantion insuficient"},
    }
    server._completeaza_strategie(date, None)
    assert date["strategie_negociere"]["disponibil"] is False
    assert "nu se poate calibra" in date["strategie_negociere"]["motiv"]


# -- What the PDF actually renders ----------------------------------------

def _povestea_pdf(date, tmp_path):
    """The flowables the PDF is built from, flattened to text.

    Cheaper and far more legible than parsing the rendered PDF back, and it
    asserts on the same content the reader sees.
    """
    from reportlab.platypus import SimpleDocTemplate

    capturat: list[list] = []

    class Spion(SimpleDocTemplate):
        def build(self, story, *args, **kwargs):
            capturat.append(list(story))
            return super().build(story, *args, **kwargs)

    original = generator_pdf.SimpleDocTemplate
    generator_pdf.SimpleDocTemplate = Spion
    try:
        generator_pdf.genereaza_raport_complet_pdf(
            date, cale_iesire=str(tmp_path / "raport.pdf")
        )
    finally:
        generator_pdf.SimpleDocTemplate = original

    bucati: list[str] = []

    def parcurge(obiect):
        if obiect is None:
            return
        if isinstance(obiect, str):
            bucati.append(obiect)
            return
        if isinstance(obiect, list | tuple):
            for element in obiect:
                parcurge(element)
            return
        if isinstance(text := getattr(obiect, "text", None), str):
            bucati.append(text)
        for atribut in ("_cellvalues", "_content", "_flowables"):
            parcurge(getattr(obiect, atribut, None))

    parcurge(capturat[0])
    return " ".join(bucati)


def test_pdf_renders_the_negotiation_section(tmp_path):
    date = {
        "titlu": "Apartament 3 camere",
        "pret_total": 179_000,
        "suprafata_utila": 71.5,
        "camere": 3,
        "an_constructie": 1982,
        "adresa": "Titan, București",
        "evaluare_anevar": {
            "disponibil": True,
            "valoare_estimata_piata": 154_000,
            "ajustare_recomandata_procent": 16.2,
            "comparabile_utilizate": [{}, {}, {}],
        },
    }
    server._completeaza_strategie(date, None)
    text = _povestea_pdf(date, tmp_path)

    for titlu in ("Scara de Ofertare", "Prag de abandon", "Profilul Vânzătorului",
                  "Bugetul Consolidat"):
        assert titlu in text, f"PDF-ul nu conține {titlu!r}"


def test_pdf_without_an_energy_certificate_says_so(tmp_path):
    date = {
        "titlu": "Apartament",
        "pret_total": 179_000,
        "suprafata_utila": 71.5,
        "camere": 3,
        "an_constructie": 1982,
        "evaluare_anevar": {"disponibil": False, "motiv": "eșantion insuficient"},
    }
    server._completeaza_strategie(date, None)
    text = _povestea_pdf(date, tmp_path)

    assert "Nedeclarat în anunț" in text
    assert "BREEAM" not in text
    assert "115.4" not in text


def test_levers_fire_on_the_shape_the_finishes_audit_actually_emits():
    """`defecte_si_probleme`, objects with `descriere_defect` — not a flat list.

    Reading the wrong key meant the price levers were silently always empty on a
    real listing while the tests on synthetic phrases passed.
    """
    from gemini_act.imobiliare_mcp import negociere

    audit = {
        "calitate_generala_finisaje": {"stare_conservare": "Necesită renovare"},
        "defecte_si_probleme": [
            {
                "element_afectat": "Tablou electric",
                "descriere_defect": "Conductori de aluminiu vizibili",
                "severitate": "Critic",
            },
            {
                "element_afectat": "Tavan baie",
                "descriere_defect": "Urme de infiltrații și mucegai",
                "cauza_probabila": "Infiltrație",
            },
        ],
        "sumar_financiar": {"total_buget_remediere_defecte_eur": 9000},
    }
    constatari = server._constatari_din_audit(audit, {})
    parghii = negociere.parghii_din_constatari(constatari)
    nume = [x.nume for x in parghii]
    assert any("aluminiu" in x for x in nume)
    assert any("Umezeală" in x for x in nume)


def test_dossier_carries_the_repair_estimate_into_the_budget():
    date = {
        "titlu": "Apartament",
        "pret_total": 179_000,
        "suprafata_utila": 71.5,
        "camere": 3,
        "an_constructie": 1982,
        "evaluare_anevar": {"disponibil": True, "valoare_estimata_piata": 154_000},
        "audit_electrocasnice_finisaje": {
            "sumar_financiar": {"total_buget_remediere_defecte_eur": 9000},
            "defecte_si_probleme": [
                {"descriere_defect": "Conductori de aluminiu în tabloul electric"}
            ],
        },
    }
    server._completeaza_strategie(date, None)
    etichete = [p["componenta"] for p in date["buget_consolidat"]["posturi"]]
    assert "Renovare (deviz aplicat)" in etichete
    assert date["strategie_negociere"]["parghii"]
