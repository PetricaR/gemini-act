"""What the purchase actually costs, beyond the price on the listing.

A negotiation won on the price and lost on the budget is still lost, and the
walk-away threshold in `negociere.py` is only computable once the rest of the
project is priced: transfer taxes, the renovation estimate, furnishing, and the
reserve.

Two rules govern everything below, and they are the same rules the rest of this
package follows:

* **No stand-in values.** A cost whose basis is not documented comes back as
  `None` with a reason, never as a plausible-looking number. The dossier
  previously multiplied the surface by a constant to produce "maintenance" and
  printed the result as a measurement.
* **Every figure carries its qualification** -- FAPT for a published tariff,
  ESTIMARE for a market range -- so a convention never renders like a fact.

The legal tariffs are dated. They change by order and by budget law, and a
stale grid that still computes is worse than one that refuses to: keep the
effective dates next to the values and re-check them before trusting a total.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# -- Dated legal and fiscal constants -------------------------------------

TVA_STANDARD_PCT = 21.0
TVA_IN_VIGOARE_DIN = "2025-08-01"
TVA_TEMEI = "Legea nr. 141/2025 — cota standard de TVA"

INTABULARE_PCT = 0.15
INTABULARE_TEMEI = "Ordinul ANCPI nr. 39/2009 — tarif de intabulare, persoane fizice"

# Only the bracket the source documents is reproduced. The lower brackets of
# the grid are not, so below the threshold this returns a range and says so
# rather than inventing steps that would compute to the cent.
NOTAR_TEMEI = "Ordinul MJ nr. 177/C/2024 — onorarii notariale"
NOTAR_PRAG_LEI = 600_001.0
NOTAR_FIX_LEI = 6_405.0
NOTAR_PROCENT_SURPLUS = 0.6
NOTAR_BANDA_SUB_PRAG_PCT = (1.3, 1.6)

# An indicative conversion, not a rate of the day: the notarial grid is in lei
# and everything else in this package is in euro.
CURS_EUR_RON = 5.0

# Ranges from market practice on the Bucharest residential segment.
EXTRAS_CF_EUR = (25.0, 60.0)
COMISION_AGENTIE_PCT = (1.5, 2.0)
COSTURI_CREDIT_EUR = (400.0, 700.0)
FONDURI_ASOCIATIE_EUR = (300.0, 800.0)
RENOVARE_EUR_MP = (350.0, 500.0)
MOBILARE_EUR_PE_CAMERA = (5_000.0, 7_300.0)
ADMINISTRARE_BLOC_NOU_EUR_LUNA = (60.0, 150.0)
REZERVA_IMPLICITA_EUR = 5_000.0

# Paid by the seller, withheld by the notary. Listed because it explains what
# the other side nets, which is a negotiation input -- never added to the
# buyer's total.
IMPOZIT_TRANSFER_PCT = {"peste_3_ani": 1.0, "sub_3_ani": 3.0}

CALIFICARI = {"FAPT": "masurat", "ESTIMARE": "estimat"}


@dataclass
class Post:
    """One line of the budget, with what it rests on."""

    eticheta: str
    minim: float | None
    maxim: float | None
    temei: str
    calificare: str = "ESTIMARE"
    suportat_de: str = "Cumpărător"
    motiv_indisponibil: str | None = None

    @property
    def mediu(self) -> float | None:
        if self.minim is None or self.maxim is None:
            return None
        return (self.minim + self.maxim) / 2

    def as_dict(self) -> dict[str, Any]:
        return {
            "componenta": self.eticheta,
            "minim_eur": round(self.minim) if self.minim is not None else None,
            "maxim_eur": round(self.maxim) if self.maxim is not None else None,
            "mediu_eur": round(self.mediu) if self.mediu is not None else None,
            "temei": self.temei,
            "suportat_de": self.suportat_de,
            "calificare": self.calificare,
            "provenienta": (
                "indisponibil" if self.minim is None
                else CALIFICARI.get(self.calificare, "estimat")
            ),
            "motiv_indisponibil": self.motiv_indisponibil,
        }


def _banda(valoare: float, procente: tuple[float, float]) -> tuple[float, float]:
    return valoare * procente[0] / 100, valoare * procente[1] / 100


def onorariu_notarial(pret_eur: float, curs: float = CURS_EUR_RON) -> Post:
    """The notary's fee, from the one bracket of the grid that is documented."""
    lei = pret_eur * curs
    if lei >= NOTAR_PRAG_LEI:
        onorariu_lei = NOTAR_FIX_LEI + (lei - NOTAR_PRAG_LEI) * NOTAR_PROCENT_SURPLUS / 100
        eur = onorariu_lei / curs
        return Post(
            "Onorariu notarial de vânzare-cumpărare",
            eur,
            eur,
            f"{NOTAR_TEMEI}: {NOTAR_FIX_LEI:,.0f} lei + {NOTAR_PROCENT_SURPLUS}% din ce "
            f"depășește {NOTAR_PRAG_LEI:,.0f} lei (curs orientativ {curs} lei/EUR)".replace(
                ",", "."
            ),
            calificare="FAPT",
        )
    minim, maxim = _banda(pret_eur, NOTAR_BANDA_SUB_PRAG_PCT)
    return Post(
        "Onorariu notarial de vânzare-cumpărare",
        minim,
        maxim,
        f"{NOTAR_TEMEI}: sub pragul de {NOTAR_PRAG_LEI:,.0f} lei grila este graduală și nu "
        f"este reprodusă integral aici — bandă orientativă "
        f"{NOTAR_BANDA_SUB_PRAG_PCT[0]}–{NOTAR_BANDA_SUB_PRAG_PCT[1]}%".replace(",", "."),
        calificare="ESTIMARE",
    )


def costuri_tranzactionare(
    pret_eur: float | None,
    *,
    prin_agentie: bool = False,
    cu_credit: bool = False,
    curs: float = CURS_EUR_RON,
) -> dict[str, Any]:
    """Everything paid once, at or around the signing."""
    if not pret_eur:
        return {
            "status": "indisponibil",
            "disponibil": False,
            "motiv": "Fără un preț de referință nu se pot calcula taxele de transfer.",
            "provenienta": "indisponibil",
        }

    notar = onorariu_notarial(pret_eur, curs)
    tva_min = (notar.minim or 0) * TVA_STANDARD_PCT / 100
    tva_max = (notar.maxim or 0) * TVA_STANDARD_PCT / 100
    intabulare = pret_eur * INTABULARE_PCT / 100

    posturi = [
        notar,
        Post(
            f"TVA {TVA_STANDARD_PCT:.0f}% aplicat onorariului notarial",
            tva_min,
            tva_max,
            f"{TVA_TEMEI}, în vigoare din {TVA_IN_VIGOARE_DIN}",
            calificare="FAPT",
        ),
        Post(
            "Taxă de intabulare ANCPI",
            intabulare,
            intabulare,
            f"{INTABULARE_TEMEI}: {INTABULARE_PCT}% din valoarea tranzacției",
            calificare="FAPT",
        ),
        Post(
            "Extras CF de autentificare și arhivare notarială",
            EXTRAS_CF_EUR[0],
            EXTRAS_CF_EUR[1],
            "Tarif ANCPI fix plus tariful de gestiune a dosarului notarial",
            calificare="ESTIMARE",
            suportat_de="Extrasul: vânzător · arhivarea: cumpărător",
        ),
    ]

    if prin_agentie:
        minim, maxim = _banda(pret_eur, COMISION_AGENTIE_PCT)
        posturi.append(
            Post(
                "Comision de agenție imobiliară",
                minim * (1 + TVA_STANDARD_PCT / 100),
                maxim * (1 + TVA_STANDARD_PCT / 100),
                f"Cotă uzuală {COMISION_AGENTIE_PCT[0]}–{COMISION_AGENTIE_PCT[1]}% + TVA, "
                "datorată doar dacă s-a semnat un act de vizionare",
                calificare="ESTIMARE",
            )
        )
    if cu_credit:
        posturi.append(
            Post(
                "Costuri de finanțare bancară",
                COSTURI_CREDIT_EUR[0],
                COSTURI_CREDIT_EUR[1],
                "Raport de evaluare ANEVAR, intabularea ipotecii și onorariul aferent",
                calificare="ESTIMARE",
            )
        )

    minim = sum(x.minim or 0 for x in posturi)
    maxim = sum(x.maxim or 0 for x in posturi)
    return {
        "status": "disponibil",
        "disponibil": True,
        "provenienta": "estimat",
        "posturi": [x.as_dict() for x in posturi],
        "total_minim_eur": round(minim),
        "total_maxim_eur": round(maxim),
        "total_estimat_eur": round((minim + maxim) / 2),
        "impozit_transfer_vanzator_pct": IMPOZIT_TRANSFER_PCT,
        "nota": (
            "Impozitul pe transferul proprietății (1% peste 3 ani de deținere, 3% sub) este "
            "reținut la sursă de notar și îl suportă exclusiv vânzătorul. Este listat pentru "
            "că explică suma netă pe care o încasează, nu pentru că ar intra în bugetul "
            "cumpărătorului."
        ),
    }


def costuri_detinere(
    suprafata_mp: float | None,
    *,
    bloc_nou: bool = False,
) -> dict[str, Any]:
    """Recurring cost of living in it.

    Deliberately thin. Maintenance depends on the association's own contracts
    and the local taxable value, neither of which this pipeline has seen, so
    those lines come back unavailable instead of as a surface multiplied by a
    constant.
    """
    posturi = [
        Post(
            "Întreținere și fond de reparații",
            None,
            None,
            "Depinde de contractele asociației și de consumurile reale",
            motiv_indisponibil=(
                "Se citește din listele de plată afișate la avizier, pe lunile de iarnă. "
                "Nu poate fi dedusă din anunț."
            ),
        ),
        Post(
            "Impozit local pe clădire",
            None,
            None,
            "Cotă aplicată valorii impozabile stabilite de DITL, nu prețului de piață",
            motiv_indisponibil=(
                "Valoarea impozabilă se obține din certificatul de atestare fiscală al "
                "vânzătorului."
            ),
        ),
    ]
    if bloc_nou:
        posturi.append(
            Post(
                "Administrare privată (property management)",
                ADMINISTRARE_BLOC_NOU_EUR_LUNA[0] * 12,
                ADMINISTRARE_BLOC_NOU_EUR_LUNA[1] * 12,
                f"Contract obligatoriu în condominiile noi: "
                f"{ADMINISTRARE_BLOC_NOU_EUR_LUNA[0]:.0f}–"
                f"{ADMINISTRARE_BLOC_NOU_EUR_LUNA[1]:.0f} EUR/lună pentru pază, "
                "monitorizare și mentenanță",
                calificare="ESTIMARE",
            )
        )

    cunoscute = [x for x in posturi if x.minim is not None]
    return {
        "status": "partial" if cunoscute else "indisponibil",
        "disponibil": bool(cunoscute),
        "provenienta": "estimat" if cunoscute else "indisponibil",
        "posturi": [x.as_dict() for x in posturi],
        "total_anual_minim_eur": round(sum(x.minim or 0 for x in cunoscute)) or None,
        "total_anual_maxim_eur": round(sum(x.maxim or 0 for x in cunoscute)) or None,
        "suprafata_mp": suprafata_mp,
        "motiv": (
            None if cunoscute else
            "Costurile recurente se stabilesc din listele de plată ale asociației și din "
            "certificatul fiscal — documente care nu se pot deduce din anunț."
        ),
    }


def buget_consolidat(
    pret_eur: float | None,
    suprafata_mp: float | None,
    camere: int | None = None,
    *,
    deviz_renovare_eur: float | None = None,
    include_mobilare: bool = True,
    prin_agentie: bool = False,
    cu_credit: bool = False,
    rezerva_eur: float = REZERVA_IMPLICITA_EUR,
    curs: float = CURS_EUR_RON,
) -> dict[str, Any]:
    """Price plus everything else -- the number the walk-away is computed from."""
    if not pret_eur:
        return {
            "status": "indisponibil",
            "disponibil": False,
            "motiv": "Fără un preț de referință bugetul consolidat nu se poate calcula.",
            "provenienta": "indisponibil",
        }

    tranzactie = costuri_tranzactionare(
        pret_eur, prin_agentie=prin_agentie, cu_credit=cu_credit, curs=curs
    )
    posturi = [
        Post("Preț de achiziție", pret_eur, pret_eur, "Prețul negociat al imobilului",
             calificare="FAPT"),
        Post(
            "Taxe de transfer și notariale",
            tranzactie["total_minim_eur"],
            tranzactie["total_maxim_eur"],
            "Detaliate în structura costurilor de tranzacționare",
            calificare="ESTIMARE",
        ),
    ]

    if deviz_renovare_eur:
        posturi.append(
            Post("Renovare (deviz aplicat)", deviz_renovare_eur, deviz_renovare_eur,
                 "Deviz rezultat din defectele constatate la inspecția vizuală",
                 calificare="ESTIMARE")
        )
    elif suprafata_mp:
        posturi.append(
            Post(
                "Renovare capitală (dacă este necesară)",
                suprafata_mp * RENOVARE_EUR_MP[0],
                suprafata_mp * RENOVARE_EUR_MP[1],
                f"{RENOVARE_EUR_MP[0]:.0f}–{RENOVARE_EUR_MP[1]:.0f} EUR/mp util, manoperă "
                "și materiale de nivel mediu",
                calificare="ESTIMARE",
            )
        )

    if include_mobilare and camere:
        posturi.append(
            Post(
                "Mobilare și electrocasnice",
                camere * MOBILARE_EUR_PE_CAMERA[0],
                camere * MOBILARE_EUR_PE_CAMERA[1],
                f"{MOBILARE_EUR_PE_CAMERA[0]:.0f}–{MOBILARE_EUR_PE_CAMERA[1]:.0f} EUR pe "
                "cameră, plecând de la utilarea completă a unui apartament de 3 camere",
                calificare="ESTIMARE",
            )
        )

    posturi.append(
        Post("Fonduri de asociație și racorduri", FONDURI_ASOCIATIE_EUR[0],
             FONDURI_ASOCIATIE_EUR[1], "Fond de rulment, fond de reparații, actualizare contoare",
             calificare="ESTIMARE")
    )
    if rezerva_eur:
        posturi.append(
            Post("Fond pentru neprevăzute", rezerva_eur, rezerva_eur,
                 "Rezervă recomandată pentru cheltuieli care apar după preluare",
                 calificare="ESTIMARE")
        )

    minim = sum(x.minim or 0 for x in posturi)
    maxim = sum(x.maxim or 0 for x in posturi)
    return {
        "status": "disponibil",
        "disponibil": True,
        "provenienta": "estimat",
        "posturi": [x.as_dict() for x in posturi],
        "total_minim_eur": round(minim),
        "total_maxim_eur": round(maxim),
        "total_estimat_eur": round((minim + maxim) / 2),
        "costuri_conexe_eur": round((minim + maxim) / 2 - pret_eur),
        "tranzactionare": tranzactie,
    }
