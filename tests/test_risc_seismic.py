"""AMCCRS seismic-risk register lookup (`risc_seismic`).

Every fixture row below is a verbatim shape seen in the live register -- the
messy class spellings, the `19÷21 (corp A+B)` numbers, the address column that
sometimes carries the house number itself. The point of the module is to
survive those, so the tests are written against them rather than against tidy
invented data.
"""

from __future__ import annotations

import pytest

from gemini_act.imobiliare_mcp import risc_seismic as rs


def rand(adresa, nr, sector="Sector 1", incadrare="1.Clasa de risc seismic RsI.", **kw):
    brut = {
        "adresa": adresa,
        "nr": nr,
        "sector": sector,
        "anulconstruirii": kw.get("an", "1935"),
        "regimuldeinaltime": kw.get("regim", "S+P+4E"),
        "numardeapartamente": kw.get("apartamente", "12"),
        "anulelaborariiexpertizeitehnice": kw.get("an_expertiza", "1998"),
        "expertultehnicatestatpentrucerintaesentialadecalitaterezistentamecanicasistabilitatemdrap": kw.get(  # noqa: E501
            "expert", "Ion VARSA"
        ),
        "ultimaincadrareinclasaderisc": incadrare,
        "incadrarianterioareinclasaderisc": kw.get("anterioare", ""),
        "observatii": kw.get("observatii", ""),
    }
    return rs._normalizeaza(brut)


@pytest.fixture
def registru(monkeypatch):
    """A fixed register, so nothing in these tests touches the network."""

    def _instaleaza(randuri):
        monkeypatch.setattr(rs, "index", lambda reincarca=False: randuri)
        return randuri

    return _instaleaza


# -- street keys ----------------------------------------------------------


@pytest.mark.parametrize(
    "adresa, asteptat",
    [
        ("Strada ACADEMIEI", "ACADEMIEI"),
        ("Str. Academiei", "ACADEMIEI"),
        ("Bulevardul GHEORGHE MAGHERU", "GHEORGHE MAGHERU"),
        ("B-dul Gheorghe Magheru", "GHEORGHE MAGHERU"),
        ("Șoseaua Colentina", "COLENTINA"),
        ("Soseaua COLENTINA", "COLENTINA"),
        # Diacritics arrive both as comma-below and as cedilla for the same street.
        ("Strada POTERAȘI", "POTERASI"),
        ("Strada POTERAŞI", "POTERASI"),
        # A landmark alias is not part of the street name.
        ("Bulevardul GHEORGHE MAGHERU (Cinematograful PATRIA)", "GHEORGHE MAGHERU"),
        # ~90 register rows carry number/block/sector inside the address column.
        ("Strada BIBESCU VODA NR 24 CORP A SECTOR 4", "BIBESCU VODA"),
        ("Bulevardul CAMIL RESSU nr.21; bl.56A", "CAMIL RESSU"),
        # The caller's own phrasing, in either order.
        ("Strada Academiei 15, Sector 1", "ACADEMIEI"),
        ("Sector 1, Strada Academiei 15", "ACADEMIEI"),
        ("Calea Victoriei 95, București", "VICTORIEI"),
    ],
)
def test_cheie_strada_colapseaza_variantele_de_scriere(adresa, asteptat):
    assert rs.cheie_strada(adresa) == asteptat


# -- house numbers --------------------------------------------------------


@pytest.mark.parametrize(
    "numar, asteptat",
    [
        ("15", {"15"}),
        ("5A", {"5", "5A"}),
        ("2BIS", {"2"}),
        # Ranges cover every number in them: a listing quotes one of the ends.
        ("19÷21 (corp A+B)", {"19", "20", "21"}),
        ("3÷5", {"3", "4", "5"}),
        ("3 (3-5)", {"3", "4", "5"}),
        # Bucharest streets were renumbered; the old number still identifies it.
        ("43 (fost 1)", {"1", "43"}),
        ("17 (15)", {"15", "17"}),
        # A parenthetical describing the *building* is not a number.
        ("14 (3 corpuri principale + 1 corp secundar)", {"14"}),
        ("40÷42 (sc. A+B+C+D)", {"40", "41", "42"}),
        ("33 (bloc OD42)", {"33"}),
    ],
)
def test_numere_acopera_intervale_si_numerotari_vechi(numar, asteptat):
    assert rs.numere(numar) == asteptat


def test_numere_citeste_si_numarul_lipit_in_coloana_de_adresa():
    assert "24" in rs.numere("24", "Strada BIBESCU VODA nr. 24 corp A sector 4")
    # "CORP" must not be read as the letter suffix of "24".
    assert "24C" not in rs.numere("24", "Strada BIBESCU VODA nr. 24 corp A sector 4")


@pytest.mark.parametrize(
    "adresa, asteptat",
    [
        ("Strada Academiei 15", {"15"}),
        ("Strada Academiei nr. 15", {"15"}),
        ("Calea Victoriei 95A", {"95", "95A"}),
        # The digit at the end is the sector, not the building.
        ("Strada Academiei 15, Sector 1", {"15"}),
        ("Strada Academiei 15, București, Sector 4", {"15"}),
        ("Strada Academiei", set()),
    ],
)
def test_numarul_interogarii_nu_confunda_sectorul_cu_numarul_postal(adresa, asteptat):
    assert rs._numere_interogare(None, adresa) == asteptat


def test_numarul_explicit_are_prioritate_fata_de_adresa():
    assert rs._numere_interogare("7", "Strada Academiei 15") == {"7"}


# -- classification -------------------------------------------------------


@pytest.mark.parametrize(
    "incadrare, observatii, asteptat",
    [
        ("1.Clasa de risc seismic RsI.", "", ("RsI", None)),
        ("1.Clasa de Risc Seismic RsI.", "", ("RsI", None)),
        ("1.RSI.", "", ("RsI", None)),
        ("2.Clasa de risc seismic RsII", "", ("RsII", None)),
        ("2.Clasa de Risc Seismic RSII.", "", ("RsII", None)),
        ("3.Clasa de risc Seismic RsIII.", "", ("RsIII", None)),
        # RsIV must not be read as RsI followed by junk.
        ("4.Clasa de risc seismic RsIV.", "", ("RsIV", None)),
        ("5.CONSOLIDATE", "", ("CONSOLIDAT", None)),
        ("5.Consolidate", "", ("CONSOLIDAT", None)),
        # The urgency category lives in `observatii`, not in the class column.
        (
            "INCADRARE IN CATEGORIE DE URGENTA; NEINCADRATE IN CLASE DE RISC",
            "U1",
            ("URGENTA", "U1"),
        ),
        ("INCADRARE IN CATEGORIE DE URGENTA", "U3", ("URGENTA", "U3")),
        ("ÎNCADRARE ÎN CATEGORIE DE URGENȚĂ U2.", "", ("URGENTA", "U2")),
        ("NEINCADRAT IN CATEGORIA DE URGENTA SAU CLASE de RISC SEISMIC", "", ("NEINCADRAT", None)),
        # One live row has an expert's name typed into the class column.
        ("Popescu V. Dumitru Dan", "", ("NECUNOSCUT", None)),
    ],
)
def test_clasa_normalizeaza_scrierile_din_registru(incadrare, observatii, asteptat):
    assert rs._clasa(incadrare, observatii) == asteptat


def test_fiecare_clasa_are_o_intrare_in_tabelul_de_impact():
    """`_rezumat` indexes CLASE by whatever `_clasa` returned, so they must agree."""
    produse = {"RsI", "RsII", "RsIII", "RsIV", "URGENTA", "CONSOLIDAT", "NEINCADRAT", "NECUNOSCUT"}
    assert produse <= set(rs.CLASE)


# -- search ---------------------------------------------------------------


def test_potrivirea_exacta_castiga_si_raporteaza_incredere_ridicata(registru):
    registru(
        [
            rand("Strada ACADEMIEI", "15"),
            rand("Strada ACADEMIEI", "25", incadrare="3.Clasa de risc seismic RsIII."),
        ]
    )
    r = rs.cauta("Strada Academiei 15, Sector 1")

    assert r["status"] == "success"
    assert r["gasit"] is True
    prima = r["potriviri"][0]
    assert (prima["numar"], prima["clasa_risc"], prima["incredere"]) == ("15", "RsI", "ridicata")
    assert prima["severitate"] == 5
    assert "bulină roșie" in r["concluzie"]


def test_numarul_gresit_coboara_vecinul_sub_potrivirea_reala(registru):
    """The neighbour's bulina rosie must not be reported as this building's."""
    registru(
        [
            rand("Strada ACADEMIEI", "1", incadrare="1.Clasa de risc seismic RsI."),
            rand("Strada ACADEMIEI", "15", incadrare="4.Clasa de risc seismic RsIV."),
        ]
    )
    r = rs.cauta("Strada Academiei 15")

    assert r["potriviri"][0]["numar"] == "15"
    assert r["potriviri"][0]["clasa_risc"] == "RsIV"
    assert r["potriviri"][1]["incredere"] == "scazuta"


def test_intervalul_de_numere_acopera_numarul_cerut(registru):
    registru(
        [rand("Bulevardul GHEORGHE MAGHERU", "6÷8", incadrare="2.Clasa de risc seismic RsII.")]
    )
    r = rs.cauta("Bulevardul Gheorghe Magheru 7")

    assert r["gasit"] is True
    assert r["potriviri"][0]["incredere"] == "ridicata"


def test_prenumele_lipsa_din_anunt_gaseste_strada_dar_nu_se_declara_sigur(registru):
    """Listings write "Magheru"; the register writes "Gheorghe Magheru"."""
    registru([rand("Bulevardul GHEORGHE MAGHERU", "7")])
    r = rs.cauta("Bulevardul Magheru 7")

    assert r["gasit"] is True
    assert r["potriviri"][0]["incredere"] == "medie"


def test_fara_numar_raspunsul_se_declara_doar_pe_strada(registru):
    registru([rand("Strada ACADEMIEI", "15")])
    r = rs.cauta("Strada Academiei")

    assert r["potriviri"][0]["incredere"] == "doar_strada"
    assert "numărul" in r["concluzie"]


def test_sectorul_departajeaza_doua_strazi_cu_acelasi_nume(registru):
    registru(
        [
            rand(
                "Strada GENERAL", "5", sector="Sector 2", incadrare="4.Clasa de risc seismic RsIV."
            ),
            rand(
                "Strada GENERAL", "5", sector="Sector 5", incadrare="1.Clasa de risc seismic RsI."
            ),
        ]
    )
    r = rs.cauta("Strada General 5", sector="Sector 5")

    assert r["potriviri"][0]["sector"] == "Sector 5"


def test_absenta_din_registru_nu_este_raportata_ca_siguranta(registru):
    """The single most important thing this tool must not get wrong."""
    registru([rand("Strada ACADEMIEI", "15")])
    r = rs.cauta("Strada Inexistenta 4")

    assert r["status"] == "success"
    assert r["gasit"] is False
    assert r["potriviri"] == []
    assert r["severitate_maxima"] == 0
    assert "NU înseamnă că imobilul e sigur" in r["concluzie"]
    assert "expertiz" in r["avertisment"]


def test_urgenta_u1_este_raportata_mai_grav_decat_u3(registru):
    randuri = registru(
        [
            rand("Strada A", "1", incadrare="INCADRARE IN CATEGORIE DE URGENTA", observatii="U1"),
            rand("Strada B", "1", incadrare="INCADRARE IN CATEGORIE DE URGENTA", observatii="U3"),
        ]
    )
    u1 = rs._rezumat(randuri[0])
    u3 = rs._rezumat(randuri[1])

    assert (u1["categorie_urgenta"], u3["categorie_urgenta"]) == ("U1", "U3")
    assert u1["severitate"] > u3["severitate"]


def test_consolidat_nu_penalizeaza_valoarea(registru):
    registru([rand("Strada ACADEMIEI", "15", incadrare="5.CONSOLIDATE")])
    r = rs.cauta("Strada Academiei 15")

    assert r["potriviri"][0]["discount_orientativ_pct"] == [0, 0]
    assert r["severitate_maxima"] == 0


def test_adresa_goala_este_o_eroare_nu_o_cautare(registru):
    registru([rand("Strada ACADEMIEI", "15")])
    assert rs.cauta("")["status"] == "error"
    assert rs.cauta("   42  ")["status"] == "error"


def test_raspunsul_poarta_sursa_si_cadrul_legal(registru):
    registru([rand("Strada ACADEMIEI", "15")])
    r = rs.cauta("Strada Academiei 15")

    assert r["sursa"]["url"] == rs.PAGE_URL
    assert r["sursa"]["imobile_in_registru"] == 1
    assert "212/2022" in r["cadru_legal"]


def test_registrul_indisponibil_este_raportat_ca_eroare(monkeypatch):
    def boom(reincarca=False):
        raise rs.RegistruIndisponibil("AMCCRS nu răspunde")

    monkeypatch.setattr(rs, "index", boom)
    r = rs.cauta("Strada Academiei 15")

    assert r["status"] == "error"
    assert "AMCCRS" in r["error_message"]


# -- normalisation of a whole row ----------------------------------------


def test_normalizeaza_tipizeaza_coloanele_si_curata_mojibake():
    r = rand(
        "Bulevardul GHEORGHE MAGHERU (Cinematograful \x84STUDIO\x94)",
        "6÷8",
        an="1928",
        apartamente="0",
        an_expertiza="1993",
        observatii="U2",
        incadrare="INCADRARE IN CATEGORIE DE URGENTA",
    )

    assert "\x84" not in r["adresa"] and "„STUDIO”" in r["adresa"]
    assert (r["an_constructie"], r["an_expertiza"]) == (1928, 1993)
    assert r["numar_apartamente"] == 0
    assert r["sector"] == "Sector 1"
    assert (r["clasa_risc"], r["categorie_urgenta"]) == ("URGENTA", "U2")
    assert r["_numere"] == {"6", "7", "8"}
    assert r["_cheie"] == "GHEORGHE MAGHERU"


# -- the finding a report consumes ---------------------------------------


def test_constatare_distinge_intre_nesolicitat_si_negasit(registru):
    """None means the question could not be asked; gasit=False means it was."""
    registru([rand("Strada ACADEMIEI", "15")])

    assert rs.constatare("") is None
    assert rs.constatare(None) is None

    negasit = rs.constatare("Strada Inexistenta 4")
    assert negasit is not None
    assert (negasit["verificat"], negasit["gasit"], negasit["concludent"]) == (True, False, False)
    assert "nu atestă siguranța" in negasit["rezumat"]


def test_constatare_afirma_clasa_doar_cand_potrivirea_e_la_nivel_de_imobil(registru):
    registru([rand("Strada ACADEMIEI", "15")])

    exact = rs.constatare("Strada Academiei 15")
    assert exact["concludent"] is True
    assert exact["clasa_risc"] == "RsI"
    assert exact["severitate"] == 5
    assert exact["adresa_registru"] == "Strada ACADEMIEI nr. 15"
    assert exact["explicatie"] and exact["consecinte"]

    # Same street, no number: the neighbour's class is not this building's.
    vag = rs.constatare("Strada Academiei")
    assert vag["gasit"] is True
    assert vag["concludent"] is False
    assert vag["clasa_risc"] is None
    assert vag["severitate"] == 0
    assert "Neconcludent" in vag["rezumat"]


def test_constatare_nu_propaga_o_eroare_de_registru(monkeypatch):
    def boom(reincarca=False):
        raise rs.RegistruIndisponibil("AMCCRS nu răspunde")

    monkeypatch.setattr(rs, "index", boom)
    assert rs.constatare("Strada Academiei 15") is None


@pytest.mark.parametrize(
    "adresa",
    [
        # What a listing's address line actually says most of the time.
        "Zona Universitate, Bucuresti",
        "Titan",
        "Bucuresti",
        "Sector 3",
        "",
    ],
)
def test_o_eticheta_de_cartier_nu_produce_o_constatare(registru, adresa):
    """ "Not in the register" about a neighbourhood is a finding about nothing."""
    registru([rand("Strada ACADEMIEI", "15")])
    assert rs.constatare(adresa) is None


@pytest.mark.parametrize(
    "adresa", ["Strada Academiei 15", "Academiei 15", "Str. Necunoscuta", "Calea Victoriei"]
)
def test_o_adresa_reala_produce_o_constatare(registru, adresa):
    registru([rand("Strada ACADEMIEI", "15")])
    assert rs.constatare(adresa) is not None
