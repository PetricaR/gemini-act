"""Valuation of one apartment under the Romanian valuation standards.

Implements the procedure the standards actually prescribe, SEV 2025 edition
(in force 1 July 2025):

* SEV 101 §20.1 (a)-(p)  terms of engagement
* SEV 103                valuation approaches
* GEV 630 §53            weight of asking prices depends on negotiation
                         evidence and exposure time
* GEV 630 §56            the ten recommended elements of comparison
* GEV 630 §57            what determines the value conclusion: range, count
                         of adjustments, gross and net adjustment, and
                         disqualification of over-adjusted comparables
* GEV 630 §58            no adjustment may be used without showing how it
                         was estimated -- so the size and floor adjustments
                         are regressed out of the comparable set itself
* GEV 630 §67-70         potential gross -> effective gross -> net operating
                         income, rather than a single expense ratio
* SEV 106 §30.6 (a)-(r)  minimum report content
* SEV 106 §30.8          conformity must NOT be claimed when a limitation
                         affects it -- see `NONCONFORMITY`

What this cannot do is inspect the property, verify title, or carry an
authorised evaluator's signature, so it never claims SEV conformity.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

SEV_EDITION = "SEV 2025 (în vigoare de la 1 iulie 2025)"

NONCONFORMITY = (
    "**Declarație de neconformitate (SEV 106, §30.8).** Prezenta lucrare NU este conformă cu "
    "Standardele de evaluare a bunurilor și nu constituie un raport de evaluare. Trei cerințe "
    "obligatorii nu pot fi îndeplinite automat: identitatea unui evaluator autorizat ANEVAR "
    "(SEV 101 §20.1 e), inspecția proprietății și verificarea dreptului de proprietate "
    "(SEV 101 §20.1 i), și convenirea în scris a termenilor de referință cu clientul "
    "(SEV 101 §20.2). Conform SEV 106 §30.8, în prezența acestor limitări conformitatea cu SEV "
    "nu poate fi afirmată. Documentul aplică metodologia standardelor ca instrument de decizie "
    "pentru cumpărător; pentru garantarea împrumutului (GEV 520), raportare financiară "
    "(SEV 430), impozitare (GEV 500) sau litigii este obligatoriu un evaluator autorizat."
)

# GEV 630 §56 -- the recommended elements of comparison, in the standard's own
# order. Every one must be addressed in the report, including those that turn
# out to need no adjustment.
COMPARISON_ELEMENTS = [
    "Drepturile de proprietate transmise",
    "Condițiile de finanțare",
    "Condițiile de vânzare",
    "Cheltuielile necesare imediat după cumpărare",
    "Condițiile de piață",
    "Localizarea",
    "Caracteristicile fizice",
    "Caracteristicile economice",
    "Caracteristici juridice",
    "Componentele non-imobiliare ale proprietății",
]


@dataclass
class Params:
    """Valuation inputs. Every one is argued in the report, per GEV 630 §71."""

    # GEV 630 §53: asking price -> probable transaction price, widened by
    # exposure time because a long-listed offer carries more negotiation room.
    negotiation_base_pct: float = 3.0
    negotiation_per_30_days_pct: float = 0.5
    negotiation_cap_pct: float = 12.0

    # Fallbacks, used only when the comparable set is too thin to regress.
    size_elasticity_default: float = -0.15
    ground_floor_discount_default: float = 5.0
    top_floor_discount_default: float = 3.0

    age_premium_per_year_pct: float = 0.45
    age_premium_cap_pct: float = 20.0
    metro_discount_max_pct: float = 8.0
    new_build_premium_pct: float = 4.0

    parking_value_eur: float = 12000.0
    furniture_value_eur: float = 8000.0

    # GEV 630 §67-70.
    vacancy_rate_pct: float = 8.0
    operating_expense_pct: float = 18.0
    capitalisation_rate_pct: float = 6.0

    # GEV 630 §57: a comparable needing adjustment beyond this is disqualified.
    disqualify_gross_pct: float = 35.0

    market_weight_pct: float = 80.0
    income_weight_pct: float = 20.0


_PARKING = re.compile(r"parcare|garaj|parking", re.I)
_FURNISHED = re.compile(r"mobilat|mobilier|utilat", re.I)
_UNFURNISHED = re.compile(r"nemobilat|mobilat par[țt]ial", re.I)


def _text_of(rec: dict[str, Any]) -> str:
    return f"{rec.get('title') or ''} {rec.get('description') or ''}"


def has_parking(rec: dict[str, Any]) -> bool:
    return bool(_PARKING.search(_text_of(rec)))


def is_furnished(rec: dict[str, Any], slug_hint: bool = False) -> bool:
    text = _text_of(rec)
    if _UNFURNISHED.search(text):
        return False
    return bool(_FURNISHED.search(text)) or slug_hint


def _completeness(rec: dict[str, Any]) -> int:
    """How much a record actually says -- used to pick a survivor among duplicates."""
    return sum(
        1
        for field_name in ("year_built", "floor", "floors_total", "metro_distance_m",
                           "days_on_market", "seller_type", "description", "image_urls")
        if rec.get(field_name) not in (None, "", [])
    )


def dedupe(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The portal carries the same flat twice under different area labels.

    A duplicate in a comparison grid is a second vote for one price, so it has
    to go before anything is averaged.

    Two passes. The first keys on the full signature. The second catches the
    case the first misses and which the portal actually produces: the same flat
    relisted with a field left blank, so the signatures differ on a `None`.
    Records only merge when the fields they *both* publish agree -- two genuinely
    different flats at the same price and surface stay separate as soon as one
    names a different year or floor.

    Among duplicates the survivor is the record that says the most, not the
    first one seen: a relist stripped of its year and photographs should not
    displace the complete listing of the same flat.
    """
    def better(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
        return _completeness(candidate) > _completeness(current)

    exact: dict[tuple, dict[str, Any]] = {}
    for r in records:
        key = (r.get("price_eur"), r.get("surface_sqm"), r.get("year_built"), r.get("floor"))
        if None in key[:2]:
            continue
        if key not in exact or better(r, exact[key]):
            exact[key] = r

    grupe: dict[tuple, list[dict[str, Any]]] = {}
    for r in exact.values():
        grupe.setdefault((r.get("price_eur"), r.get("surface_sqm")), []).append(r)

    out: list[dict[str, Any]] = []
    for candidati in grupe.values():
        pastrate: list[dict[str, Any]] = []
        for r in sorted(candidati, key=_completeness, reverse=True):
            compatibil = any(
                all(
                    r.get(camp) == deja.get(camp)
                    for camp in ("year_built", "floor")
                    if r.get(camp) is not None and deja.get(camp) is not None
                )
                for deja in pastrate
            )
            if not compatibil:
                pastrate.append(r)
        out.extend(pastrate)
    return out


# -- Adjustments derived from the data (GEV 630 §58) ----------------------

@dataclass
class Derived:
    """An adjustment rate estimated from the comparable set, with its evidence."""

    value: float
    sample: int
    method: str
    derived: bool = True

    def source(self) -> str:
        return (f"{self.method}, n={self.sample}" if self.derived
                else f"{self.method} (date insuficiente pentru estimare din setul de comparabile)")


def derive_size_elasticity(records: list[dict[str, Any]], p: Params) -> Derived:
    """Regress ln(price per sqm) on ln(surface) -- the market's own size gradient."""
    pts = [
        (math.log(r["surface_sqm"]), math.log(r["price_per_sqm"]))
        for r in records
        if r.get("surface_sqm") and r.get("price_per_sqm")
    ]
    if len(pts) < 8:
        return Derived(p.size_elasticity_default, len(pts),
                       "valoare implicită de piață", derived=False)
    mx = statistics.fmean(x for x, _ in pts)
    my = statistics.fmean(y for _, y in pts)
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx == 0:
        return Derived(p.size_elasticity_default, len(pts),
                       "valoare implicită de piață", derived=False)
    slope = sum((x - mx) * (y - my) for x, y in pts) / sxx
    # A wild slope means the sample is not telling us about size at all.
    if not -1.2 < slope < 0.6:
        return Derived(p.size_elasticity_default, len(pts),
                       "valoare implicită de piață (regresie neconcludentă)", derived=False)
    return Derived(slope, len(pts), "regresie log-log preț unitar / suprafață, pe comparabile")


def _median_ppsqm(records: list[dict[str, Any]]) -> float | None:
    vals = [r["price_per_sqm"] for r in records if r.get("price_per_sqm")]
    return statistics.median(vals) if vals else None


MANSARDA = 99  # parse.py normalises "mansardă" to this, with no real floor number


def _is_top(rec: dict[str, Any]) -> bool:
    """Top floor, including a mansardă whose building height went unpublished."""
    floor, total = rec.get("floor"), rec.get("floors_total")
    if floor is None:
        return False
    return floor == MANSARDA or bool(total and floor >= total)


def derive_floor_discounts(records: list[dict[str, Any]], p: Params) -> tuple[Derived, Derived]:
    """Paired-data analysis: ground and top floors against intermediate ones."""
    ground = [r for r in records if r.get("floor") is not None and r["floor"] <= 0]
    top = [r for r in records if _is_top(r)]
    mid = [r for r in records
           if r.get("floor") is not None and r["floor"] > 0 and not _is_top(r)]
    base = _median_ppsqm(mid)

    def one(group: list[dict[str, Any]], fallback: float, label: str) -> Derived:
        med = _median_ppsqm(group)
        if not base or not med or len(group) < 4 or len(mid) < 6:
            return Derived(fallback, len(group), "valoare implicită de piață", derived=False)
        pct = (1 - med / base) * 100
        if not -2.0 < pct < 25.0:      # implausible: the sample is telling us nothing
            return Derived(fallback, len(group), "valoare implicită de piață (analiză neconcludentă)",
                           derived=False)
        return Derived(pct, len(group), f"analiză pe perechi de date, {label} vs. etaje intermediare")

    return (one(ground, p.ground_floor_discount_default, "parter/demisol"),
            one(top, p.top_floor_discount_default, "ultim etaj"))


def negotiation_margin(rec: dict[str, Any], p: Params) -> tuple[float, str]:
    """GEV 630 §53: exposure time is evidence about negotiation room."""
    days = rec.get("days_on_market")
    if days is None:
        return p.negotiation_base_pct, "timp de expunere nepublicat; s-a reținut marja de bază"
    extra = (days / 30.0) * p.negotiation_per_30_days_pct
    pct = min(p.negotiation_base_pct + extra, p.negotiation_cap_pct)
    return pct, f"{days} zile de expunere pe piață"


# -- The comparison grid --------------------------------------------------

@dataclass
class Correction:
    element: str        # one of COMPARISON_ELEMENTS
    name: str
    pct: float = 0.0
    eur: float = 0.0
    basis: str = ""     # GEV 630 §58: how the adjustment was estimated
    note: str = ""
    # True for a correction applied identically to every comparable to bring
    # them all onto the same basis (asking -> probable transaction price),
    # rather than one that measures how this comparable differs from the
    # subject. GEV 630 §57's gross adjustment -- and the disqualification
    # threshold built on it -- is about dissimilarity, so these are excluded
    # from it; otherwise a universal 3-12% correction eats a third of the
    # budget and long-listed comparables are disqualified for being listed.
    normalisation: bool = False


@dataclass
class AdjustedComp:
    record: dict[str, Any]
    corrections: list[Correction] = field(default_factory=list)
    base_per_sqm: float = 0.0
    adjusted_per_sqm: float = 0.0
    n_adjustments: int = 0
    gross_pct: float = 0.0
    gross_eur: float = 0.0
    net_pct: float = 0.0
    net_eur: float = 0.0
    weight: float = 0.0
    disqualified: bool = False


@dataclass
class Rates:
    """Every rate the grid used, with the evidence behind it."""

    size_elasticity: Derived
    ground_floor: Derived
    top_floor: Derived


def adjust(subject: dict[str, Any], comp: dict[str, Any], p: Params, rates: Rates,
           subject_furnished: bool | None = None) -> AdjustedComp:
    """Bring one comparable onto the subject's terms.

    A positive correction means the comparable was inferior to the subject on
    that element and its price is raised to stand in for it.
    """
    price, surface = comp.get("price_eur"), comp.get("surface_sqm")
    out = AdjustedComp(record=comp)
    if not price or not surface:
        return out

    def floor_penalty(rec: dict[str, Any]) -> float:
        if rec.get("floor") is None:
            return 0.0
        if rec["floor"] <= 0:
            return rates.ground_floor.value
        return rates.top_floor.value if _is_top(rec) else 0.0

    def metro_penalty(rec: dict[str, Any]) -> float | None:
        """None when the distance is unpublished -- GEV 630 §58 requires every
        adjustment to show how it was estimated, and a guessed distance cannot.
        """
        d = rec.get("metro_distance_m")
        if d is None:
            return None
        return min(d, 1500.0) / 1500.0 * p.metro_discount_max_pct

    # --- Condițiile de vânzare: asking price -> probable transaction price.
    margin, why = negotiation_margin(comp, p)
    negotiated = price * (1 - margin / 100)
    out.corrections.append(Correction(
        "Condițiile de vânzare", "Marjă de negociere", eur=negotiated - price,
        basis=f"GEV 630 §53: {p.negotiation_base_pct:.1f}% de bază "
              f"+ {p.negotiation_per_30_days_pct:.1f}%/30 zile de expunere, plafon "
              f"{p.negotiation_cap_pct:.1f}%",
        note=f"{why} → {margin:.1f}%",
        normalisation=True,
    ))

    # --- Componente non-imobiliare și dotări, în sumă absolută.
    s_park, c_park = has_parking(subject), has_parking(comp)
    if s_park != c_park:
        delta = p.parking_value_eur if s_park else -p.parking_value_eur
        out.corrections.append(Correction(
            "Caracteristicile fizice", "Loc de parcare", eur=delta,
            basis="preț de piață al unui loc de parcare în zonă (parametru)",
            note="subiectul are, comparabila nu" if s_park else "comparabila are, subiectul nu",
        ))
        negotiated += delta

    s_furn = subject_furnished if subject_furnished is not None else is_furnished(subject)
    c_furn = is_furnished(comp)
    if s_furn != c_furn:
        delta = p.furniture_value_eur if s_furn else -p.furniture_value_eur
        out.corrections.append(Correction(
            "Componentele non-imobiliare ale proprietății", "Mobilier și dotări", eur=delta,
            basis="valoarea de piață a mobilierului, ca element non-imobiliar (parametru)",
            note="subiectul e mobilat, comparabila nu" if s_furn else "comparabila e mobilată, subiectul nu",
        ))
        negotiated += delta

    out.base_per_sqm = negotiated / surface

    # --- Corecții procentuale, pe preț unitar.
    subj_sqm = subject.get("surface_sqm")
    if subj_sqm and surface > 0:
        b = rates.size_elasticity.value
        pct = ((subj_sqm / surface) ** b - 1) * 100
        if abs(pct) > 0.05:
            out.corrections.append(Correction(
                "Caracteristicile fizice", "Suprafață", pct=pct,
                basis=f"elasticitate {b:+.3f} — {rates.size_elasticity.source()}",
                note=f"{surface:g} mp față de {subj_sqm:g} mp",
            ))

    pct_floor = floor_penalty(comp) - floor_penalty(subject)
    if abs(pct_floor) > 0.05:
        # Cite the paired-data analysis the adjustment actually came from.
        # `comp["floor"]` is 0 for parter, so test for None explicitly rather
        # than leaning on truthiness.
        comp_floor = comp.get("floor")
        src = (rates.ground_floor if comp_floor is not None and comp_floor <= 0
               else rates.top_floor)
        out.corrections.append(Correction(
            "Caracteristicile fizice", "Poziție pe verticală", pct=pct_floor,
            basis=src.source(), note="parter / ultim etaj față de etaje intermediare",
        ))

    s_year, c_year = subject.get("year_built"), comp.get("year_built")
    if s_year and c_year:
        pct_year = max(-p.age_premium_cap_pct,
                       min(p.age_premium_cap_pct, p.age_premium_per_year_pct * (s_year - c_year)))
        if abs(pct_year) > 0.05:
            out.corrections.append(Correction(
                "Caracteristicile fizice", "An construcție", pct=pct_year,
                basis=f"{p.age_premium_per_year_pct:.2f}%/an, plafonat la "
                      f"±{p.age_premium_cap_pct:.0f}% (parametru)",
                note=f"{c_year} față de {s_year}",
            ))

    comp_metro, subj_metro = metro_penalty(comp), metro_penalty(subject)
    if comp_metro is None or subj_metro is None:
        # Recorded so the report shows the element was considered (GEV 630 §56
        # requires all ten to be addressed), but with no adjustment applied.
        cd, sd = comp.get("metro_distance_m"), subject.get("metro_distance_m")
        out.corrections.append(Correction(
            "Localizarea", "Distanță până la metrou", pct=0.0,
            basis="fără ajustare: distanța nu este publicată pentru ambele proprietăți",
            note=f"{cd if cd is not None else 'nepublicat'} m față de "
                 f"{sd if sd is not None else 'nepublicat'} m",
        ))
    elif abs(pct_metro := comp_metro - subj_metro) > 0.05:
        cd, sd = comp.get("metro_distance_m"), subject.get("metro_distance_m")
        out.corrections.append(Correction(
            "Localizarea", "Distanță până la metrou", pct=pct_metro,
            basis=f"discount liniar până la {p.metro_discount_max_pct:.0f}% la 1.500 m (parametru)",
            note=f"{cd:g} m față de {sd:g} m",
        ))

    if bool(subject.get("is_new_build")) != bool(comp.get("is_new_build")):
        pct_new = p.new_build_premium_pct if subject.get("is_new_build") else -p.new_build_premium_pct
        out.corrections.append(Correction(
            "Caracteristicile economice", "Regim de construcție", pct=pct_new,
            basis=f"primă de {p.new_build_premium_pct:.0f}% pentru construcție nouă (parametru)",
            note="nou față de existent",
        ))

    total_pct = sum(c.pct for c in out.corrections)
    out.adjusted_per_sqm = out.base_per_sqm * (1 + total_pct / 100)

    # GEV 630 §57 requires gross and net, in both value and percentage terms.
    # Gross measures comparability, so it covers only the corrections that
    # describe a difference from the subject -- not the normalisation applied
    # equally to every comparable -- and is expressed against the normalised
    # price the percentages were actually applied to, not the asking price.
    comparability = [c for c in out.corrections if not c.normalisation]
    normalised_total = out.base_per_sqm * surface
    out.n_adjustments = sum(1 for c in comparability if c.pct or c.eur)
    pct_as_eur = sum(abs(c.pct) for c in comparability) / 100 * normalised_total
    out.gross_eur = sum(abs(c.eur) for c in comparability) + pct_as_eur
    out.gross_pct = out.gross_eur / normalised_total * 100 if normalised_total else 0.0
    # Net stays against the asking price: it answers "what is this listing
    # worth on the subject's terms, versus what it is advertised at".
    out.net_eur = out.adjusted_per_sqm * surface - price
    out.net_pct = out.net_eur / price * 100
    out.disqualified = out.gross_pct > p.disqualify_gross_pct
    out.weight = 0.0 if out.disqualified else 1 / (1 + out.gross_pct / 100)
    return out


# -- Approaches -----------------------------------------------------------

@dataclass
class Income:
    rent_per_sqm: float | None = None
    potential_gross: float | None = None
    effective_gross: float | None = None
    noi: float | None = None
    value: float | None = None
    sample: int = 0


@dataclass
class Valuation:
    subject: dict[str, Any]
    comps: list[AdjustedComp]
    excluded: list[AdjustedComp]
    params: Params
    rates: Rates
    market_per_sqm: float | None = None
    market_value: float | None = None
    best_comp_per_sqm: float | None = None
    value_range: tuple[float, float] | None = None
    income: Income = field(default_factory=Income)
    implied_yield: float | None = None
    final_value: float | None = None
    extrapolated: bool = False   # subject falls outside the comparables' size range
    sufficient_comps: bool = True

    @property
    def reliability(self) -> str:
        """How much weight the conclusion can carry, given the evidence behind it."""
        if len(self.comps) < 3:
            return "insuficienta"
        if len(self.comps) < 4 or self.extrapolated:
            return "scazuta"
        if len(self.comps) < 7 or not self.rates.size_elasticity.derived:
            return "medie"
        return "ridicata"


def market_approach(subject, comps: list[AdjustedComp]):
    usable = [c for c in comps if c.weight > 0]
    if not usable:
        return None, None, None, None
    total_w = sum(c.weight for c in usable)
    per_sqm = sum(c.adjusted_per_sqm * c.weight for c in usable) / total_w
    # GEV 630 §57: the conclusion is anchored by the closest comparable, i.e.
    # the one that needed the least adjusting.
    best = min(usable, key=lambda c: c.gross_pct)
    values = [c.adjusted_per_sqm for c in usable]
    surface = subject.get("surface_sqm")
    return per_sqm, (per_sqm * surface if surface else None), best.adjusted_per_sqm, (min(values), max(values))


def income_approach(subject, rents: list[dict[str, Any]], p: Params) -> Income:
    per_sqm = [
        r["price_eur"] / r["surface_sqm"]
        for r in rents
        if r.get("price_eur") and r.get("surface_sqm") and 0 < r["price_eur"] < 10000
    ]
    surface = subject.get("surface_sqm")
    if not per_sqm or not surface:
        return Income()
    rent_sqm = statistics.median(per_sqm)
    potential = rent_sqm * surface * 12                                   # §68
    effective = potential * (1 - p.vacancy_rate_pct / 100)                # §69
    noi = effective * (1 - p.operating_expense_pct / 100)                 # §70
    return Income(rent_sqm, potential, effective, noi,
                  noi / (p.capitalisation_rate_pct / 100), len(per_sqm))


def evaluate(subject: dict[str, Any], comp_records: list[dict[str, Any]],
             rent_records: list[dict[str, Any]], p: Params,
             subject_furnished: bool | None = None,
             rate_pool: list[dict[str, Any]] | None = None) -> Valuation:
    pool = dedupe(comp_records)
    # The adjustment rates describe the market, not the handful of comparables
    # that made the grid, so they are regressed out of the widest sample the
    # caller can offer -- the whole area -- and only then applied to the grid.
    evidence = dedupe(rate_pool) if rate_pool else pool
    elasticity = derive_size_elasticity(evidence, p)
    ground, top = derive_floor_discounts(evidence, p)
    rates = Rates(elasticity, ground, top)

    graded = [adjust(subject, c, p, rates, subject_furnished) for c in pool]
    graded = [g for g in graded if g.adjusted_per_sqm > 0]
    kept = [g for g in graded if not g.disqualified]
    dropped = [g for g in graded if g.disqualified]

    v = Valuation(subject=subject, comps=kept, excluded=dropped, params=p, rates=rates)
    v.sufficient_comps = len(kept) >= 3
    if v.sufficient_comps:
        v.market_per_sqm, v.market_value, v.best_comp_per_sqm, v.value_range = market_approach(subject, kept)
    else:
        v.market_per_sqm, v.market_value, v.best_comp_per_sqm, v.value_range = None, None, None, None
    v.income = income_approach(subject, dedupe(rent_records), p)

    if v.income.rent_per_sqm and subject.get("price_per_sqm"):
        net_rent_sqm = (v.income.rent_per_sqm * 12
                        * (1 - p.vacancy_rate_pct / 100)
                        * (1 - p.operating_expense_pct / 100))
        v.implied_yield = net_rent_sqm / subject["price_per_sqm"] * 100

    subj_sqm = subject.get("surface_sqm")
    sizes = [c.record["surface_sqm"] for c in kept if c.record.get("surface_sqm")]
    if subj_sqm and sizes:
        v.extrapolated = not (min(sizes) <= subj_sqm <= max(sizes))

    parts, weights = [], []
    if v.sufficient_comps and v.market_value:
        parts.append(v.market_value)
        weights.append(p.market_weight_pct)
    if v.sufficient_comps and v.income.value:
        parts.append(v.income.value)
        weights.append(p.income_weight_pct)
    # Weights are caller-supplied and each may legitimately be 0 (to run a
    # single approach), but both being 0 leaves nothing to reconcile.
    total_weight = sum(weights)
    if parts and total_weight > 0:
        v.final_value = sum(x * w for x, w in zip(parts, weights, strict=True)) / total_weight
    elif parts:
        # Both weights zero: fall back to an equal split rather than failing.
        v.final_value = sum(parts) / len(parts)
    else:
        v.final_value = None
    return v
