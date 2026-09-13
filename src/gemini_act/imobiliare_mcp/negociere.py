"""From a valuation to an offer: the ladder, the counterparty, the walk-away.

`anevar.py` answers what the flat is worth. That is a different question from
what to offer for it, and it rests on different evidence: exposure time, seller
type, price-drop history and the repair estimate, not comparables.

Nothing here moves the estimated value. Same rule as `viziune.py`: an
adjustment a buyer cannot audit is worth less than no adjustment. The ladder is
built *on top of* the valuation and is reported next to it, never folded into
it.

Every range carries the qualification its source gives it -- FAPT, INFERENȚĂ,
ESTIMARE or OPINIE -- for the same reason `Derived.derived` exists in
`anevar.py`: a market convention that renders like a measurement is worse than
no number. `CALIFICARI` maps those onto the provenance badges the web UI and the
PDF already use.

Sources for the ranges are market-practice figures for the Bucharest
residential segment, not measurements taken from this listing. They are
parameters, and `Parametri` exists so a caller can replace every one of them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# -- Qualification of every figure below ----------------------------------

# The document these ranges come from grades its own claims. Carrying that
# grade through to the report is what keeps a convention from reading as a
# measurement. The values map onto `web/src/components/ProvenanceBadge.jsx`.
CALIFICARI = {
    "FAPT": "masurat",
    "INFERENTA": "estimat",
    "ESTIMARE": "estimat",
    "OPINIE": "anunt",
}

SURSA_IMPLICITA = (
    "Practică de piață pe segmentul rezidențial București; parametru al modelului, "
    "nu o măsurătoare a acestui imobil."
)


@dataclass
class Parametri:
    """Every lever of the offer ladder. Conventions, not laws -- override freely."""

    # Anchoring. A correctly priced flat is opened 6-8% under its fair value;
    # an overpriced one 12-16% under the *asking* price, because the asking
    # price is what the seller has to be moved off.
    ancora_sub_valoare_pct: float = 7.0
    ancora_sub_listare_pct: float = 14.0

    # Above this gap between asking price and estimate the listing is treated
    # as overpriced, and above the second as severely so.
    prag_supraevaluare_pct: float = 5.0
    prag_supraevaluare_severa_pct: float = 15.0

    # The ceiling is above the target only by what a buyer can justify paying
    # for certainty; the walk-away sits just above the ceiling.
    marja_pret_maxim_pct: float = 3.0
    marja_walk_away_pct: float = 1.0

    # Concessions must shrink, or the seller reads the pattern as an unexhausted
    # budget. Shares of the distance from the opening offer to the target.
    trepte_concesii: tuple[float, ...] = (0.50, 0.30, 0.20)

    # A written offer that never expires is a bidding instrument for the seller.
    valabilitate_oferta_ore: int = 48


# -- Where the asking price sits ------------------------------------------

CONTEXTE = {
    "sub_piata": ("Preț sub valoarea estimată", (0.0, 2.0), "INFERENTA"),
    "corect": ("Proprietate corect evaluată la listare", (1.5, 3.5), "FAPT"),
    "usor_supraevaluat": ("Proprietate ușor supraevaluată", (4.0, 7.5), "INFERENTA"),
    "sever_supraevaluat": ("Proprietate sever supraevaluată", (8.0, 15.0), "ESTIMARE"),
}


def context_pret(listat: float | None, estimat: float | None, p: Parametri) -> str:
    """Which negotiation regime this listing is in."""
    if not listat or not estimat:
        return "corect"
    diferenta = (listat - estimat) / estimat * 100
    if diferenta < 0:
        return "sub_piata"
    if diferenta < p.prag_supraevaluare_pct:
        return "corect"
    if diferenta < p.prag_supraevaluare_severa_pct:
        return "usor_supraevaluat"
    return "sever_supraevaluat"


# -- Who is on the other side ---------------------------------------------

@dataclass
class Profil:
    """One seller archetype and the approach it responds to."""

    cod: str
    eticheta: str
    declansator: str
    tactica: str
    greseli: str
    agresivitate_pct: tuple[float, float]
    argument: str
    calificare: str = "INFERENTA"
    semnale: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cod": self.cod,
            "profil": self.eticheta,
            "declansator": self.declansator,
            "tactica_eficienta": self.tactica,
            "erori_de_evitat": self.greseli,
            "agresivitate_oferta_pct": list(self.agresivitate_pct),
            "argument_principal": self.argument,
            "calificare": self.calificare,
            "provenienta": CALIFICARI.get(self.calificare, "estimat"),
            "semnale_detectate": self.semnale,
        }


PROFILE: dict[str, Profil] = {
    "dezvoltator": Profil(
        cod="dezvoltator",
        eticheta="Birou de vânzări al dezvoltatorului",
        declansator=(
            "Prețul unitar din contract este fixat de indicatorii de vânzare aprobați în "
            "planul de finanțare al proiectului."
        ),
        tactica=(
            "Se acceptă prețul de listă și se negociază pachetul: loc de parcare inclus sau "
            "discountat, boxă, upgrade de finisaje, preluarea taxelor conexe."
        ),
        greseli=(
            "Insistența pe reducerea prețului facial pe mp — afectează raportările bancare "
            "ale dezvoltatorului și blochează discuția."
        ),
        agresivitate_pct=(0.0, 3.0),
        argument=(
            "Acceptăm prețul de listă al apartamentului cu condiția ca locul de parcare și "
            "boxa să fie incluse fără costuri suplimentare."
        ),
        calificare="FAPT",
    ),
    "agentie": Profil(
        cod="agentie",
        eticheta="Tranzacție mediată prin agenție",
        declansator=(
            "Agentul își încasează comisionul doar la închidere și, în mandat neexclusiv, "
            "riscă să piardă tranzacția către o agenție rivală."
        ),
        tactica=(
            "Ofertă scrisă, formală, cu termen de răspuns, condiționată de prezentarea ei "
            "proprietarului — nu se lasă filtrată de intermediar."
        ),
        greseli="Negocierea exclusiv verbală, fără urmă scrisă și fără termen.",
        agresivitate_pct=(3.0, 6.0),
        argument=(
            "Suntem cumpărători solvabili, cu dosarul pregătit. Prezentați oferta "
            "proprietarului și închidem dosarul săptămâna aceasta."
        ),
        calificare="FAPT",
    ),
    "corectie_fortata": Profil(
        cod="corectie_fortata",
        eticheta="Vânzător aflat deja în corecție de preț",
        declansator=(
            "Prețul a fost redus cel puțin o dată: piața a refuzat nivelul inițial și "
            "vânzătorul a acceptat deja principiul scăderii."
        ),
        tactica=(
            "Ofertă fermă scrisă, ancorată pe devizul tehnic, care continuă traiectoria de "
            "corecție deja începută în loc să o conteste."
        ),
        greseli="Repornirea discuției de la prețul inițial, pe care vânzătorul l-a abandonat.",
        agresivitate_pct=(8.0, 14.0),
        argument=(
            "Ați ajustat deja prețul o dată. Oferta noastră aduce proprietatea exact la "
            "nivelul la care piața o absoarbe."
        ),
        calificare="ESTIMARE",
    ),
    "presiune_costuri": Profil(
        cod="presiune_costuri",
        eticheta="Proprietar cu locuință nelocuită, sub presiunea costurilor",
        declansator=(
            "Apartamentul este gol și generează întreținere pasivă lună de lună, fără niciun "
            "venit care să o acopere."
        ),
        tactica=(
            "Ofertă fermă cu termen scurt de autentificare și avans substanțial, schimbând "
            "certitudinea pe preț."
        ),
        greseli="Termene lungi de analiză și condiționări bancare nelămurite.",
        agresivitate_pct=(8.0, 12.0),
        argument=(
            "Avem fondurile disponibile și semnăm la notar în termen scurt, fără amânări și "
            "fără clauze suspensive lungi."
        ),
        calificare="INFERENTA",
    ),
    "testeaza_piata": Profil(
        cod="testeaza_piata",
        eticheta='Vânzător care testează piața ("dacă primesc prețul...")',
        declansator=(
            "Fără urgență, cu ancorare speculativă: anunțul stă de luni de zile la același "
            "preț, fără nicio ajustare."
        ),
        tactica=(
            "O singură ofertă scrisă la valoarea justă, valabilă câteva zile, apoi "
            "retragerea contactului și revenirea după 45-60 de zile."
        ),
        greseli="Negocieri mărunte succesive și insistență telefonică — întăresc ancora.",
        agresivitate_pct=(0.0, 4.0),
        argument=(
            "Aceasta este valoarea tehnică susținută de comparabile. Dacă abordarea "
            "dumneavoastră se schimbă, ne puteți contacta."
        ),
        calificare="OPINIE",
    ),
    "particular": Profil(
        cod="particular",
        eticheta="Proprietar particular, fără intermediar",
        declansator=(
            "Comportament bipolar: fie rigiditate emoțională față de preț, fie cedare rapidă "
            "din lipsă de consiliere."
        ),
        tactica=(
            "Argumente strict tehnice și verificabile — instalații, izolare, cote de "
            "întreținere pe lunile de iarnă — niciodată critica alegerilor estetice."
        ),
        greseli=(
            "Denigrarea finisajelor sau a gustului proprietarului: activează reflexul de "
            "apărare și închide discuția."
        ),
        agresivitate_pct=(0.0, 10.0),
        argument=(
            "Apreciem apartamentul. Discuția noastră este strict despre lucrările pe care "
            "trebuie să le facem înainte de a ne muta cu un copil mic."
        ),
        calificare="OPINIE",
    ),
}


def profil_vanzator(rec: dict[str, Any], zile_prag: int = 90) -> Profil:
    """Pick the archetype from signals the listing already carries.

    Everything read here is produced by `parse.normalise`, so this costs no
    request and makes no claim the record does not support. A signal that is
    absent is not evidence of its opposite -- the fallback is the neutral
    profile for the seller type, not the most exploitable one.
    """
    tip = (rec.get("seller_type") or "").lower()
    zile = rec.get("days_on_market")
    semnale: list[str] = []

    if tip == "developer":
        profil = PROFILE["dezvoltator"]
        semnale.append("anunț publicat de dezvoltator")
    elif rec.get("price_dropped"):
        profil = PROFILE["corectie_fortata"]
        semnale.append("prețul a fost redus cel puțin o dată")
    elif rec.get("vacant"):
        profil = PROFILE["presiune_costuri"]
        semnale.append("apartament nelocuit")
    elif zile is not None and zile >= zile_prag:
        profil = PROFILE["testeaza_piata"]
        semnale.append(f"{zile} zile de expunere fără ajustare de preț")
    elif tip == "agency" or rec.get("agency"):
        profil = PROFILE["agentie"]
        semnale.append("anunț intermediat de agenție")
    else:
        profil = PROFILE["particular"]
        semnale.append("anunț de la proprietar particular" if tip == "individual"
                       else "tip de vânzător nepublicat")

    if zile is not None and profil.cod != "testeaza_piata":
        semnale.append(f"{zile} zile de expunere")
    if rec.get("exclusive"):
        semnale.append("mandat exclusiv — agentul nu riscă pierderea tranzacției")

    return Profil(
        cod=profil.cod,
        eticheta=profil.eticheta,
        declansator=profil.declansator,
        tactica=profil.tactica,
        greseli=profil.greseli,
        agresivitate_pct=profil.agresivitate_pct,
        argument=profil.argument,
        calificare=profil.calificare,
        semnale=semnale,
    )


# -- Defects that are worth money at the table ----------------------------

@dataclass
class Parghie:
    """A defect, its repair estimate, and the sentence that turns it into euros."""

    nume: str
    deviz_eur: tuple[float, float]
    reducere_eur: tuple[float, float]
    argument: str
    calificare: str = "ESTIMARE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "problema": self.nume,
            "deviz_estimativ_eur": list(self.deviz_eur),
            "reducere_justificata_eur": list(self.reducere_eur),
            "argument": self.argument,
            "calificare": self.calificare,
            "provenienta": CALIFICARI.get(self.calificare, "estimat"),
        }


# Keyword -> lever. The keywords are matched against whatever the vision pass
# and the finishes audit reported, diacritics folded, so a finding phrased any
# number of ways still lands on the right lever.
PARGHII: list[tuple[tuple[str, ...], Parghie]] = [
    (
        ("aluminiu", "instalatie electrica", "tablou electric", "sigurante", "impamantare"),
        Parghie(
            "Instalație electrică pe conductori de aluminiu",
            (3500, 5500),
            (4000, 5000),
            "Instalația electrică trebuie refăcută integral de la tablou, conform "
            "normativelor actuale, înainte de mutarea unei familii cu copil mic.",
        ),
    ),
    (
        ("coloane", "sanitar", "scurgere", "fonta", "presiune apa", "tevi"),
        Parghie(
            "Coloane sanitare și scurgeri neînlocuite",
            (2500, 4000),
            (3000, 4000),
            "Conductele sanitare au depășit durata normată de viață; refacerea traseelor "
            "până la coloanele comune este obligatorie.",
        ),
    ),
    (
        ("centrala", "termoficare", "termoenergetica", "calorifere", "incalzire"),
        Parghie(
            "Lipsă centrală termică / racord precar la rețeaua centralizată",
            (3500, 5000),
            (4000, 5000),
            "Dependența de rețeaua centralizată impune instalarea unui sistem autonom de "
            "încălzire și apă caldă.",
        ),
    ),
    (
        ("anvelopa", "termoizolatie", "neanvelopat", "punte termica", "fatada neizolata"),
        Parghie(
            "Fațadă neanvelopată termic",
            (2500, 3500),
            (3000, 4000),
            "Lipsa termoizolației exterioare înseamnă facturi mai mari și o cotă viitoare "
            "de plată către asociație pentru anvelopare.",
        ),
    ),
    (
        ("tamplarie", "termopan", "geam", "ferestre"),
        Parghie(
            "Tâmplărie PVC uzată / geam termopan simplu",
            (3000, 4500),
            (3000, 4000),
            "Tâmplăria existentă este uzată moral și fizic și nu asigură protecția fonică "
            "și termică necesară.",
        ),
    ),
    (
        ("igrasie", "mucegai", "infiltratii", "umezeala", "condens", "hidroizolatie"),
        Parghie(
            "Umezeală, mucegai sau infiltrații",
            (2500, 6000),
            (4000, 7000),
            "Urmele de infiltrație presupun refacerea completă a hidroizolației și asanarea "
            "suportului — risc respirator direct pentru un copil mic.",
        ),
    ),
    (
        ("gresie", "faianta", "parchet", "sapa", "finisaje", "renovare completa", "decopertare"),
        Parghie(
            "Finisaje uzate / straturi suprapuse de gresie și faianță",
            (6000, 10000),
            (6000, 8000),
            "Apartamentul necesită decapare până la placa de beton pentru a fi adus la un "
            "nivel de locuire normal.",
        ),
    ),
]


def _fold(text: str) -> str:
    """Lowercase, diacritics removed -- findings arrive spelled both ways."""
    normal = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normal if unicodedata.category(ch) != "Mn")


def parghii_din_constatari(constatari: list[str]) -> list[Parghie]:
    """Match free-text findings onto the levers they justify.

    Each lever fires at most once: three separate remarks about damp are one
    hydro-insulation job, not three.
    """
    text = _fold(" ".join(c for c in constatari if c))
    gasite: list[Parghie] = []
    for cuvinte, parghie in PARGHII:
        if any(_fold(c) in text for c in cuvinte):
            gasite.append(parghie)
    return gasite


# -- Red flags ------------------------------------------------------------

@dataclass
class SteagRosu:
    problema: str
    risc: str
    reducere: str
    masura: str
    abandon: bool = False
    calificare: str = "ESTIMARE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "risc": self.problema,
            "probabilitate": "De verificat" if not self.abandon else "Critic",
            "impact": "Ridicat" if self.abandon else "Mediu",
            "descriere": self.risc,
            "reducere_justificata": self.reducere,
            "mitigare": self.masura,
            "abandon_recomandat": self.abandon,
            "calificare": self.calificare,
            "provenienta": CALIFICARI.get(self.calificare, "estimat"),
        }


STEAG_SEISMIC = SteagRosu(
    problema="Imobil edificat înainte de 1978 — statut seismic neverificat",
    risc=(
        "Clădirile proiectate sub codurile anterioare cutremurului din 1977 subestimau "
        "forțele seismice. Încadrarea în clasa RsI/RsII sau în categoriile U1-U3 atrage "
        "interdicția legală de închiriere și refuzul finanțării bancare."
    ),
    reducere="-25% până la -40% față de piață dacă încadrarea se confirmă",
    masura=(
        "Verificare obligatorie a adresei în evidențele AMCCRS înainte de orice ofertă. "
        "Absența blocului din liste nu înseamnă siguranță, ci lipsa unei expertize."
    ),
    abandon=False,
    calificare="FAPT",
)

STEAG_MODIFICARI = SteagRosu(
    problema="Posibile modificări interioare neautorizate",
    risc=(
        "Releveul cadastral care nu corespunde situației din teren blochează evaluarea "
        "bancară și atrage costuri de autorizare retroactivă."
    ),
    reducere="5.000 – 8.000 EUR",
    masura="Condiționarea antecontractului de actualizarea cadastrului de către vânzător.",
)

STEAG_INFILTRATII = SteagRosu(
    problema="Infiltrații / umezeală semnalate la inspecția vizuală",
    risc=(
        "Mucegaiul este un risc respirator direct, iar infiltrațiile corodează armătura "
        "și degradează finisajele refăcute peste ele."
    ),
    reducere="4.000 – 7.000 EUR",
    masura="Acceptare doar cu remediere integrală din discountul obținut.",
)

STEAG_DEZVOLTATOR = SteagRosu(
    problema="Dezvoltator cu indicatori financiari slabi sau litigii",
    risc=(
        "Risc de nefinalizare a proiectului sau de refuz al remedierii viciilor ascunse "
        "de execuție."
    ),
    reducere="Discount net suplimentar de 8–10%",
    masura="Reorientare către proiecte cu istoric de livrare verificabil.",
)

STEAG_ULTIM_ETAJ = SteagRosu(
    problema="Ultim etaj — hidroizolația terasei nu este documentată",
    risc="Infiltrațiile prin terasă sunt cel mai frecvent viciu ascuns la ultimul nivel.",
    reducere="2.500 – 6.000 EUR",
    masura="Solicitarea anului ultimei refaceri a membranei și a garanției constructorului.",
)


def steaguri_rosii(
    rec: dict[str, Any],
    constatari: list[str] | None = None,
    dezvoltator_sanatos: bool | None = None,
) -> list[SteagRosu]:
    """Only flags the available evidence actually supports.

    Nothing here asserts a seismic class, a litigation or an unauthorised wall:
    those require a register nobody has queried. What it asserts is that a
    check is *due*, which is a claim the listing does support.
    """
    gasite: list[SteagRosu] = []
    an = rec.get("year_built")
    if an and an < 1978:
        gasite.append(STEAG_SEISMIC)

    text = _fold(" ".join(c for c in (constatari or []) if c))
    if any(k in text for k in ("infiltrat", "igrasie", "mucegai", "umezeala")):
        gasite.append(STEAG_INFILTRATII)
    if any(k in text for k in ("perete demolat", "modificari", "recompartiment")):
        gasite.append(STEAG_MODIFICARI)

    etaj, etaje = rec.get("floor"), rec.get("floors_total")
    if etaj is not None and etaje and etaj >= etaje:
        gasite.append(STEAG_ULTIM_ETAJ)

    if dezvoltator_sanatos is False:
        gasite.append(STEAG_DEZVOLTATOR)

    return gasite


# -- The ladder -----------------------------------------------------------

@dataclass
class Scara:
    """The five numbers a buyer needs before saying anything to a seller."""

    pret_listat: float | None
    valoare_estimata: float | None
    oferta_initiala: float | None
    contraoferta_probabila: tuple[float, float] | None
    pret_tinta: float | None
    pret_maxim: float | None
    walk_away: float | None
    concesii: list[float]
    supraevaluare_pct: float | None
    context: str
    marja_asteptata_pct: tuple[float, float]
    agresivitate_profil_pct: tuple[float, float] | None
    calificare: str
    deviz_aplicat_eur: float | None = None
    buget_total_max: float | None = None
    limitat_de_buget: bool = False

    def as_dict(self) -> dict[str, Any]:
        eticheta, _, _ = CONTEXTE[self.context]
        return {
            "pret_listat_eur": self.pret_listat,
            "valoare_estimata_eur": self.valoare_estimata,
            "oferta_initiala_eur": self.oferta_initiala,
            "contraoferta_probabila_eur": (
                list(self.contraoferta_probabila) if self.contraoferta_probabila else None
            ),
            "pret_tinta_eur": self.pret_tinta,
            "pret_maxim_acceptabil_eur": self.pret_maxim,
            "walk_away_eur": self.walk_away,
            "concesii_descrescatoare_eur": self.concesii,
            "supraevaluare_pct": self.supraevaluare_pct,
            "context": self.context,
            "context_eticheta": eticheta,
            "marja_negociere_asteptata_pct": list(self.marja_asteptata_pct),
            "agresivitate_profil_pct": (
                list(self.agresivitate_profil_pct) if self.agresivitate_profil_pct else None
            ),
            "deviz_aplicat_eur": self.deviz_aplicat_eur,
            "buget_total_max_eur": self.buget_total_max,
            "walk_away_limitat_de_buget": self.limitat_de_buget,
            "calificare": self.calificare,
            "provenienta": CALIFICARI.get(self.calificare, "estimat"),
            "sursa": SURSA_IMPLICITA,
        }


def _rotunjeste(value: float | None, pas: int = 500) -> float | None:
    """Offers are made in round numbers; a 147.382 € offer reads as a formula."""
    if value is None:
        return None
    return float(round(value / pas) * pas)


def concesii(deschidere: float, tinta: float, p: Parametri) -> list[float]:
    """Shrinking steps from the opening offer to the target.

    Equal steps tell the seller the budget is not exhausted; a visibly
    decelerating sequence is what signals the ceiling is real.
    """
    distanta = tinta - deschidere
    if distanta <= 0:
        return []
    pasi, cumulat = [], deschidere
    for cota in p.trepte_concesii:
        cumulat += distanta * cota
        pasi.append(_rotunjeste(cumulat) or cumulat)
    # Land exactly on the target however the rounding fell.
    if pasi:
        pasi[-1] = tinta
    return pasi


def construieste_scara(
    pret_listat: float | None,
    valoare_estimata: float | None,
    p: Parametri | None = None,
    deviz_renovare: float | None = None,
    buget_total_max: float | None = None,
    costuri_conexe: float | None = None,
    profil: Profil | None = None,
) -> Scara | None:
    """The offer ladder. Returns None when there is no valuation to build on.

    `deviz_renovare` is subtracted from the estimate rather than from the offer:
    a flat that needs 18.000 € of work is worth 18.000 € less to this buyer, and
    the target price has to say so. The assumption is reported, because if the
    comparables were themselves unrenovated the deduction double-counts.
    """
    p = p or Parametri()
    if not valoare_estimata:
        return None

    context = context_pret(pret_listat, valoare_estimata, p)
    _, marja, calificare = CONTEXTE[context]

    # The repair estimate is the *argument* for the opening offer, not a second
    # deduction from the value. The comparables in the grid are overwhelmingly
    # unrenovated themselves, so subtracting a renovation budget from a value
    # already derived from them would count the same defect twice -- and it
    # moved the target price 17.000 EUR below the estimate in testing.
    candidati = [valoare_estimata * (1 - p.ancora_sub_valoare_pct / 100)]
    if pret_listat and context in ("usor_supraevaluat", "sever_supraevaluat"):
        candidati.append(pret_listat * (1 - p.ancora_sub_listare_pct / 100))
    oferta_initiala = _rotunjeste(min(candidati))

    tinta = _rotunjeste(valoare_estimata)
    maxim = _rotunjeste(valoare_estimata * (1 + p.marja_pret_maxim_pct / 100))
    walk_away = _rotunjeste(valoare_estimata * (1 + p.marja_pret_maxim_pct / 100
                                                + p.marja_walk_away_pct / 100))

    # A budget caps the walk-away independently of what the flat is worth: the
    # consolidated project has to fit, renovation and fees included.
    limitat = False
    if buget_total_max:
        plafon = buget_total_max - (costuri_conexe or 0.0) - (deviz_renovare or 0.0)
        plafon = _rotunjeste(plafon)
        if plafon is not None and walk_away is not None and plafon < walk_away:
            walk_away, limitat = plafon, True
            maxim = min(maxim, walk_away) if maxim else walk_away
            tinta = min(tinta, maxim) if tinta else maxim

    contra = None
    if pret_listat and oferta_initiala and pret_listat > oferta_initiala:
        mijloc = (pret_listat + oferta_initiala) / 2
        contra = (_rotunjeste(mijloc * 0.98) or mijloc, _rotunjeste(mijloc * 1.02) or mijloc)

    supra = None
    if pret_listat and valoare_estimata:
        supra = round((pret_listat - valoare_estimata) / valoare_estimata * 100, 1)

    return Scara(
        pret_listat=pret_listat,
        valoare_estimata=valoare_estimata,
        oferta_initiala=oferta_initiala,
        contraoferta_probabila=contra,
        pret_tinta=tinta,
        pret_maxim=maxim,
        walk_away=walk_away,
        concesii=concesii(oferta_initiala or 0, tinta or 0, p),
        supraevaluare_pct=supra,
        context=context,
        marja_asteptata_pct=marja,
        agresivitate_profil_pct=profil.agresivitate_pct if profil else None,
        calificare=calificare,
        deviz_aplicat_eur=deviz_renovare or None,
        buget_total_max=buget_total_max,
        limitat_de_buget=limitat,
    )


def regula_decizionala(s: Scara, moneda: str = "EUR") -> str:
    """The whole strategy compressed into the sentence a buyer says out loud."""
    def n(value: float | None) -> str:
        return f"{value:,.0f}".replace(",", ".") if value else "n/a"

    return (
        f"Apartamentul este listat la {n(s.pret_listat)} {moneda}; valoarea tehnică "
        f"realistă este {n(s.valoare_estimata)} {moneda}; oferta inițială recomandată este "
        f"{n(s.oferta_initiala)} {moneda}; prețul țintă este {n(s.pret_tinta)} {moneda}; "
        f"iar peste {n(s.walk_away)} {moneda} tranzacția se abandonează."
    )


# -- Written offers -------------------------------------------------------

SCRIPTURI = {
    "proprietar": """Bună ziua,

Vă mulțumim pentru vizionarea apartamentului din {adresa}. Spațiul este bine
structurat și amplasat într-o zonă potrivită pentru o familie.

În urma analizei tehnice, am identificat lucrări de remediere necesare înainte
de mutare: {lucrari}. Devizul minim estimat pentru acestea este de {deviz} EUR.

Raportat la ofertele comparabile din imediata vecinătate, oferta noastră fermă
de achiziție este de {oferta} EUR. Dispunem de fonduri disponibile, nu depindem
de vânzarea altui imobil și putem semna antecontractul în termen scurt.

Oferta este valabilă {valabilitate} de ore de la transmitere.

Cu stimă,""",
    "agent": """Bună ziua,

Am finalizat evaluarea pentru apartamentul din {adresa}. Proprietatea prezintă
interes, însă este listată la {listat} EUR, peste nivelul la care segmentul se
tranzacționează{expunere}.

Suntem cumpărători solvabili, cu dosarul pregătit, și putem semna rapid. Oferta
noastră de deschidere este de {oferta} EUR. Dacă proprietarul revine cu o
contraofertă la nivelul de {tinta} EUR, închidem dosarul prin agenția
dumneavoastră.

Vă rog să transmiteți oferta oficial și să ne confirmați în {valabilitate} de
ore dacă putem avansa.

Cu stimă,""",
    "dezvoltator": """Bună ziua,

Am analizat specificațiile apartamentului din {adresa}. Proiectul este bine
conceput, însă costul total cu toate taxele incluse depășește plafonul nostru
bugetar.

Înțelegem că grila de preț pe metru pătrat trebuie menținută pentru evaluările
bancare ale proiectului. Propunerea noastră este să semnăm la prețul
dumneavoastră de listă, cu condiția ca pachetul să includă locul de parcare și
boxa fără costuri suplimentare.

Astfel valoarea contractuală rămâne intactă în evidențele dumneavoastră, iar noi
ne încadrăm în plafonul aprobat. Dacă structura este acceptată, achităm taxa de
rezervare și autentificăm antecontractul în termen scurt.

Cu stimă,""",
}


def script_oferta(
    canal: str,
    scara: Scara,
    adresa: str | None = None,
    parghii_active: list[Parghie] | None = None,
    zile_expunere: int | None = None,
    p: Parametri | None = None,
) -> str:
    """A paste-ready written offer. Returns text -- it never sends anything."""
    p = p or Parametri()
    sablon = SCRIPTURI.get(canal) or SCRIPTURI["proprietar"]

    def n(value: float | None) -> str:
        return f"{value:,.0f}".replace(",", ".") if value else "—"

    lucrari = ", ".join(x.nume.lower() for x in (parghii_active or [])) or (
        "lucrările curente de aducere la un nivel de locuire normal"
    )
    deviz = sum((x.reducere_eur[0] + x.reducere_eur[1]) / 2 for x in (parghii_active or []))

    return sablon.format(
        adresa=adresa or "adresa indicată în anunț",
        lucrari=lucrari,
        deviz=n(scara.deviz_aplicat_eur or deviz or None),
        oferta=n(scara.oferta_initiala),
        tinta=n(scara.pret_tinta),
        listat=n(scara.pret_listat),
        expunere=f", după {zile_expunere} zile de expunere" if zile_expunere else "",
        valabilitate=p.valabilitate_oferta_ore,
    )


# -- The whole plan, in the shape the report and the UI read --------------

_CIFRE = re.compile(r"\d")


def plan(
    rec: dict[str, Any],
    valoare_estimata: float | None,
    constatari: list[str] | None = None,
    deviz_renovare: float | None = None,
    buget_total_max: float | None = None,
    costuri_conexe: float | None = None,
    dezvoltator_sanatos: bool | None = None,
    p: Parametri | None = None,
) -> dict[str, Any]:
    """Everything downstream needs: ladder, counterparty, levers, flags, scripts."""
    p = p or Parametri()
    profil = profil_vanzator(rec)
    constatari = [c for c in (constatari or []) if c]
    parghii_active = parghii_din_constatari(constatari)

    if deviz_renovare is None and parghii_active:
        deviz_renovare = sum(
            (x.reducere_eur[0] + x.reducere_eur[1]) / 2 for x in parghii_active
        )

    scara = construieste_scara(
        rec.get("price_eur"),
        valoare_estimata,
        p=p,
        deviz_renovare=deviz_renovare,
        buget_total_max=buget_total_max,
        costuri_conexe=costuri_conexe,
        profil=profil,
    )
    if scara is None:
        return {
            "status": "indisponibil",
            "disponibil": False,
            "motiv": (
                "Fără o valoare estimată din grila de comparabile nu se poate calibra o "
                "scară de ofertare. Strategia de negociere nu se poate formula pe presupuneri."
            ),
            "provenienta": "indisponibil",
        }

    steaguri = steaguri_rosii(rec, constatari, dezvoltator_sanatos)

    return {
        "status": "disponibil",
        "disponibil": True,
        "provenienta": "estimat",
        "scara": scara.as_dict(),
        "regula_decizionala": regula_decizionala(scara),
        "profil_vanzator": profil.as_dict(),
        "parghii": [x.as_dict() for x in parghii_active],
        "steaguri_rosii": [x.as_dict() for x in steaguri],
        "abandon_recomandat": any(x.abandon for x in steaguri),
        "scripturi": {
            canal: script_oferta(
                canal,
                scara,
                adresa=rec.get("address_text") or rec.get("location"),
                parghii_active=parghii_active,
                zile_expunere=rec.get("days_on_market"),
                p=p,
            )
            for canal in SCRIPTURI
        },
        "verificari": verificari(rec),
        "reguli_de_aur": REGULI_DE_AUR,
        "sursa": SURSA_IMPLICITA,
    }


REGULI_DE_AUR = [
    "Bugetul real este ecuația consolidată: preț + parcare + taxe notariale + intabulare + "
    "comision + deviz de renovare + utilare + un fond neprevăzut.",
    "Negocierea se poartă pe suprafața utilă interioară din releveu, fără balcoane și fără "
    "cote-părți comune.",
    "Comparabilele se construiesc independent; cele prezentate de agentul vânzătorului nu "
    "sunt o bază de evaluare.",
    "Oferta fermă se transmite în scris, cu deviz atașat și cu termen de expirare de 48–72 "
    "de ore.",
    "Minimum două vizionări, la ore opuse: una dimineața, una între 18:30 și 20:00.",
    "Vizitarea administratorului asociației înaintea antecontractului: listele de plată "
    "arată starea reală a imobilului.",
    "Clauză suspensivă de finanțare în antecontract, cu restituirea integrală a avansului la "
    "refuzul creditării din motive neimputabile cumpărătorului.",
    "Cumpărătorul suportă taxele de autentificare, deci cumpărătorul alege biroul notarial.",
    "Instalațiile se testează la sarcină: toate bateriile deschise simultan, ghenele "
    "inspectate.",
    "Peste pragul de walk-away calculat la rece, tranzacția se abandonează fără excepție.",
]


# -- Checks that are due before an offer and before a pre-contract ---------

VERIFICARI_TEHNICE = [
    "Tabloul electric: siguranțe automate sau patroane vechi? Conductori de cupru sau de "
    "aluminiu?",
    "Presiune și debit: toate bateriile deschise simultan, la baie și la bucătărie.",
    "Planeitatea pardoselilor și a buiandrugilor — pante care ar impune șape autonivelante.",
    "Etanșeitatea tâmplăriei: o coală de hârtie prinsă în toc trebuie să opună rezistență.",
    "Colțurile camerelor exterioare, spatele mobilierului și pereții lângă ghene — urme de "
    "condens.",
    "Coborâre obligatorie în subsolul tehnic: bălțiri, miros de canalizare, țevi corodate.",
    "La ultimul etaj: anul ultimei refaceri a hidroizolației terasei și garanția aferentă.",
    "Zgomotul camerei troliului de lift în pereții dormitoarelor adiacente.",
]

VERIFICARI_JURIDICE = [
    "Extras de Carte Funciară pentru informare, emis în ultimele 10 zile.",
    "Proprietarul tabular este chiar persoana care vinde; soțul/soția semnează dacă bunul "
    "este comun.",
    "Sarcini înscrise: ipoteci, privilegii, urmăriri silite, uzufruct viager.",
    "Notări de procese, sechestre, somații de executare sau interdicții de înstrăinare.",
    "Lanțul titlului de proprietate; la imobilele din Legea 112/1995, acțiunile în "
    "revendicare pe Legea 10/2001.",
    "Releveul cadastral corespunde 1:1 cu compartimentarea din teren.",
    "Certificat de atestare fiscală de la DITL — impozitele locale achitate la zi.",
    "Adeverință de la asociația de proprietari privind lipsa datoriilor la întreținere.",
    "Certificat de performanță energetică.",
]

VERIFICARI_STRUCTURALE_VECHI = [
    "Verificarea adresei exacte în evidențele AMCCRS: clasele RsI–RsIV și categoriile U1–U3.",
    "Tipul constructiv: panouri mari prefabricate față de cadre de beton cu zidărie.",
    "Parterul comercial: absența demolărilor de stâlpi sau diafragme pentru extinderi.",
]

VERIFICARI_STRUCTURALE_NOI = [
    "Proces-verbal de recepție la terminarea lucrărilor, semnat cu ISC și primăria.",
    "Certificat de atestare a edificării construcției și Cartea Tehnică a Construcției.",
    "Branșamente definitive la apă, canalizare și energie electrică — nu provizorii de "
    "șantier.",
]


def verificari(rec: dict[str, Any]) -> dict[str, list[str]]:
    """The checklist for this property: technical, legal, and structural by era."""
    an = rec.get("year_built")
    nou = bool(rec.get("is_new_build")) or (an is not None and an >= 2018)
    return {
        "tehnice": VERIFICARI_TEHNICE,
        "juridice": VERIFICARI_JURIDICE,
        "structurale": (
            VERIFICARI_STRUCTURALE_NOI if nou else VERIFICARI_STRUCTURALE_VECHI
        ),
    }
