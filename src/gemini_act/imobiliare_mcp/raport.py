"""Markdown rendering of a Valuation, structured on SEV 106 §30.6."""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

from .anevar import (
    COMPARISON_ELEMENTS,
    NONCONFORMITY,
    SEV_EDITION,
    Valuation,
    has_parking,
    is_furnished,
    negotiation_margin,
)


def _eur(value: float | None, dp: int = 0) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{dp}f} €".replace(",", "@").replace(".", ",").replace("@", ".")


def _num(value: Any, unit: str = "") -> str:
    return f"{value:g}{unit}" if value is not None else "n/a"


def _poi_label(poi: Any) -> str:
    """One amenity, with whatever the answering service was able to say about it.

    Rating and walking time exist only on the Google Places path; on the OSM
    path this degrades to the name and straight-line distance it always was.
    """
    bits = [f"{poi.name} — {poi.distance_m} m"]
    walk = getattr(poi, "walk_seconds", None)
    if walk:
        bits.append(f"{round(walk / 60)} min pe jos")
    rating = getattr(poi, "rating", None)
    if rating:
        count = getattr(poi, "ratings_count", None)
        bits.append(f"{rating:.1f}★" + (f"/{count}" if count else ""))
    return ", ".join(bits)


def _floor_label(rec: dict[str, Any]) -> str:
    floor, total = rec.get("floor"), rec.get("floors_total")
    if floor is None:
        return "n/a"
    name = "parter" if floor == 0 else ("demisol" if floor < 0 else
                                        ("mansardă" if floor == 99 else f"etaj {floor}"))
    return f"{name} / {total}" if total else name


def render(v: Valuation, *, comps_source: str, rents_source: str,
           place=None, vecinatati=None, sheet: str | None = None,
           observatii_vizuale: str | None = None, viziune=None,
           street_view_file: str | None = None,
           static_map_file: str | None = None,
           scor_accesibilitate: float | None = None) -> str:
    s, p, r = v.subject, v.params, v.rates
    ask, surface = s.get("price_eur"), s.get("surface_sqm")
    today = date.today().strftime("%d.%m.%Y")
    delta = ((ask - v.final_value) / v.final_value * 100) if (ask and v.final_value) else None

    L: list[str] = []
    add = L.append

    add(f"# Analiză de evaluare — {s.get('title') or 'Apartament'}")
    add("")
    add(f"Metodologie conform {SEV_EDITION} · anunț `{s.get('id')}` · data evaluării {today}")
    add("")
    add(NONCONFORMITY)
    add("")
    add("---")
    add("")

    # 1 ------------------------------------------------------------------
    add("## 1. Sinteza")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| **Valoare de piață estimată** | **{_eur(v.final_value)}** |")
    add(f"| Preț cerut | {_eur(ask)} |")
    add(f"| Diferență | {f'{delta:+.1f}%' if delta is not None else 'n/a'} |")
    add(f"| Valoare unitară estimată | {_eur(v.market_per_sqm)}/mp |")
    add(f"| Preț unitar cerut | {_eur(s.get('price_per_sqm'))}/mp |")
    if v.value_range:
        add(f"| Interval al valorilor corectate | {_eur(v.value_range[0])} – {_eur(v.value_range[1])}/mp |")
    add(f"| Comparabile reținute / excluse | {len(v.comps)} / {len(v.excluded)} |")
    add(f"| Fiabilitatea concluziei | **{v.reliability}** |")
    add("")
    if delta is not None:
        verdict = ("**supraevaluat**" if delta > 8 else
                   "**subevaluat**" if delta < -8 else "**în intervalul de piață**")
        add(f"Prețul cerut este {verdict} față de valoarea estimată.")
        add("")
        if delta > 0 and ask and v.final_value:
            add(f"Ținta de negociere: **{_eur(v.final_value)}** — o reducere de "
                f"{_eur(ask - v.final_value)}.")
            add("")

    # 2 ------------------------------------------------------------------
    add("## 2. Termenii de referință ai evaluării (SEV 101 §20.1)")
    add("")
    add("| | Cerință | Conținut |")
    add("|---|---|---|")
    tor = [
        ("a", "Activul supus evaluării",
         f"Apartament {_num(s.get('rooms'))} camere, {_num(surface, ' mp')} utili, {s.get('location') or 'n/a'}"),
        ("b", "Clientul", "Beneficiarul analizei (cumpărător potențial)"),
        ("c", "Utilizarea desemnată", "Fundamentarea deciziei de achiziție și a nivelului de ofertare"),
        ("d", "Utilizatorul desemnat", "Exclusiv clientul; nu se autorizează difuzarea către terți"),
        ("e", "Evaluatorul", "**Neîndeplinit** — analiză automată, fără evaluator autorizat ANEVAR"),
        ("f", "Moneda evaluării", "EUR"),
        ("g", "Data evaluării", f"{today} (identică cu data raportului)"),
        ("h", "Tipul valorii", "Valoare de piață, conform SEV 102 Tipuri ale valorii"),
        ("i", "Natura și amploarea activităților; limitări",
         "**Fără inspecție** a proprietății, fără verificarea actelor. Analiză exclusiv "
         "documentară, pe informații publicate de vânzători"),
        ("j", "Natura și sursa informațiilor",
         "Anunțuri publicate pe imobiliare.ro, preluate din sitemap-urile publice și din "
         "endpointul de detaliu al portalului. Informații neverificate independent"),
        ("k", "Ipoteze speciale", "Vezi secțiunea 4"),
        ("l", "Specialist", "Nu s-a recurs la un specialist sau furnizor extern"),
        ("m", "Factori de mediu, sociali și de guvernanță", "Vezi secțiunea 5"),
        ("n", "Tipul raportului", "Document sintetic în format markdown, structurat pe SEV 106 §30.6"),
        ("o", "Restricții de utilizare", "Uz intern al clientului. Nu poate fi folosit pentru "
         "garantarea împrumutului, raportare financiară, impozitare sau litigii"),
        ("p", "Conformitatea cu SEV", "**Nu se afirmă conformitatea** — vezi declarația de la început"),
    ]
    for letter, req, content in tor:
        add(f"| ({letter}) | {req} | {content} |")
    add("")

    # 3 ------------------------------------------------------------------
    add("## 3. Identificarea proprietății")
    add("")
    add("| Atribut | Valoare |")
    add("|---|---|")
    add(f"| Denumire anunț | {s.get('title') or 'n/a'} |")
    add(f"| Localizare | {s.get('location') or 'n/a'} |")
    add(f"| Compartimentare | {_num(s.get('rooms'))} camere |")
    add(f"| Suprafață utilă | {_num(surface, ' mp')} |")
    add(f"| Etaj | {_floor_label(s)} |")
    add(f"| An construcție | {_num(s.get('year_built'))} |")
    add(f"| Regim | {'construcție nouă' if s.get('is_new_build') else 'construcție existentă'} |")
    add(f"| Distanță metrou | {s.get('metro_label') or 'n/a'} |")
    add(f"| Loc de parcare | {'menționat în anunț' if has_parking(s) else 'nemenționat'} |")
    add(f"| Mobilat | {'da' if is_furnished(s) else 'nemenționat'} |")
    add(f"| Tip vânzător | {s.get('seller_type') or 'n/a'}"
        f"{' — ' + s['agency'] if s.get('agency') else ''} |")
    add(f"| Comision cumpărător | {'0%' if s.get('commission_zero') else 'aplicabil'} |")
    add(f"| Timp de expunere | {_num(s.get('days_on_market'), ' zile')} |")
    add(f"| Localizare pe hartă | {'exactă' if s.get('exact_location') else 'aproximativă'} |")
    add(f"| Sursă | {s.get('url') or 'n/a'} |")
    add("")

    # 3b -----------------------------------------------------------------
    if place or vecinatati:
        add("## 3b. Localizare și vecinătăți")
        add("")
    if place:
        claimed = (s.get("area") or "").lower()
        resolved = place.display.lower()
        add("| | |")
        add("|---|---|")
        add(f"| Adresă rezolvată | {place.display} |")
        add(f"| Coordonate | `{place.lat:.5f}, {place.lon:.5f}` |")
        add(f"| Precizia poziției | {'adresă exactă' if place.precision == 'adresa' else 'centroid de cartier — anunțul nu publică adresa'} |")
        add(f"| Hartă | [OpenStreetMap]({place.map_url}) · [Google Maps]({place.google_url}) |")
        add("")
        if place.precision == "adresa" and claimed and claimed not in resolved:
            parts = [x.strip() for x in place.display.split(",")]
            resolved_label = parts[2] if len(parts) > 2 else place.display
            add(f"> ⚠️ **Neconcordanță de zonă.** Anunțul declară cartierul „{s.get('area')}”, "
                f"dar adresa se rezolvă în `{resolved_label}`. "
                "Comparabilele au fost selectate după eticheta din anunț, deci pot proveni dintr-o "
                "arie de piață diferită de cea reală. Verifică pe hartă înainte de orice ofertă.")
            add("")
        if place.precision != "adresa":
            add("> Poziția este aproximativă: anunțul nu publică adresa exactă, iar distanțele de "
                "mai jos se măsoară de la centrul cartierului. Tratează-le ca orientative.")
            add("")
    if vecinatati and any(vecinatati.pois.values()):
        add(f"Facilități în raza de {vecinatati.radius_m} m:")
        add("")
        add("| Categorie | Cele mai apropiate |")
        add("|---|---|")
        from .locatie import CATEGORIES as _CATS
        for key, (label, _) in _CATS.items():
            items = vecinatati.pois.get(key) or []
            if not items:
                continue
            listed = "; ".join(_poi_label(i) for i in items[:4])
            more = f" *(+{len(items) - 4})*" if len(items) > 4 else ""
            add(f"| {label} | {listed}{more} |")
        add("")
        missing = [lbl for k, (lbl, _) in _CATS.items() if not (vecinatati.pois.get(k) or [])]
        if missing:
            add(f"Fără rezultate în rază: {', '.join(missing)}.")
            add("")
        # The caveat depends on who answered: OSM is volunteer-tagged and
        # genuinely incomplete, Places is neither — claiming the OSM caveat over
        # a Google answer would misdescribe the evidence.
        if "OpenStreetMap" in (vecinatati.source or ""):
            provenance = ("Datele OpenStreetMap sunt contribuite de voluntari — absența unei "
                          "facilități din listă nu dovedește că nu există.")
        else:
            provenance = ("Distanțele sunt în linie dreaptă, cu excepția celor marcate „pe jos”, "
                          "care sunt timpi de mers reali. Notele sunt cele publice de pe Google Maps.")
        add(f"*Sursa: {vecinatati.source}. {provenance}*")
        add("")

    if static_map_file:
        add(f"![Harta zonei]({static_map_file})")
        add("")
    if scor_accesibilitate is not None:
        add(f"**Scor de accesibilitate zonă (Google Maps):** {scor_accesibilitate:.1f}/100")
        add("")

    # 3c -----------------------------------------------------------------
    if sheet or observatii_vizuale or viziune or street_view_file:
        add("## 3c. Constatări din fotografii")
        add("")
        if street_view_file:
            add(f"![Street View fațadă și stradă]({street_view_file})")
            add("")
        if sheet:
            add(f"![Galerie compusă]({sheet})")
            add("")
            photo_cnt = s.get('photos') or len(s.get('image_urls') or [])
            add(f"Galerie compusă: `{sheet}` ({photo_cnt} imagini)")
            add("")
        urls = s.get("image_urls") or []
        if urls:
            add("**Fotografii din anunț:**")
            add("")
            add(" · ".join(f"[Foto {i+1}]({u})" for i, u in enumerate(urls[:12])))
            add("")
        # The automated look comes first: it saw every photograph, where
        # `observatii_vizuale` is whatever a caller chose to write by hand.
        if viziune is not None:
            add(viziune.to_markdown())
            add("")
        if observatii_vizuale:
            if viziune is not None:
                add("**Observații suplimentare ale evaluatorului:**")
                add("")
            add(observatii_vizuale)
            add("")
        add("> Fotografiile sunt selectate de vânzător și nu înlocuiesc inspecția. Nu arată "
            "igrasia, zgomotul, vecinii, starea părților comune sau istoricul de infiltrații.")
        add("")

    # 4 ------------------------------------------------------------------
    add("## 4. Ipoteze, ipoteze speciale și condiții limitative (SEV 106 §30.6 n)")
    add("")
    add("1. **Titlu de proprietate** — se presupune valabil, liber de sarcini, servituți și litigii. "
        "Neverificat; necesită extras de carte funciară actualizat.")
    add("2. **Suprafața** — se presupune conformă cu releveul cadastral. Abaterile uzuale față de "
        "suprafața declarată în anunț sunt de 2–5%.")
    add("3. **Starea tehnică** — se presupune conformă descrierii vânzătorului, fără vicii ascunse. "
        "Nu s-a efectuat inspecție.")
    add("4. **Structura de rezistență** — se presupune neîncadrată în clasă de risc seismic.")
    add("5. **Prețurile comparabilelor** sunt prețuri de ofertă, nu de tranzacție. Conform "
        "GEV 630 §53, importanța acordată lor a fost modulată în funcție de timpul de expunere "
        "pe piață al fiecărei oferte.")
    add("6. **Costurile de tranzacționare** (onorariu notarial, intabulare, comision de agenție, "
        "impozit) nu sunt incluse în valoare.")
    add("7. **Data evaluării** coincide cu data extragerii datelor; piața se poate modifica ulterior.")
    add("")

    # 5 ------------------------------------------------------------------
    add("## 5. Factori de mediu, sociali și de guvernanță (SEV 101 §20.1 m)")
    add("")
    add("| Factor | Constatare |")
    add("|---|---|")
    year = s.get("year_built")
    seismic = ("**Risc ridicat** — construcție anterioară normativului seismic din 1978. "
               "Se verifică obligatoriu lista clădirilor expertizate a PMB."
               if year and year < 1978 else
               "Construcție ulterioară normativului din 1978." if year else
               "An de construcție nepublicat — risc seismic neevaluabil.")
    add(f"| Risc seismic | {seismic} |")
    add("| Performanță energetică | Certificatul energetic nu este publicat în anunț. "
        "Clasa energetică influențează atât costul de exploatare, cât și lichiditatea la revânzare. |")
    add(f"| Accesibilitate transport public | {s.get('metro_label') or 'nepublicată'} |")
    add("| Guvernanță | Nu s-au verificat: situația datoriilor la asociația de proprietari, "
        "hotărârile adunării generale, fondul de reparații. |")
    add("")

    # 6 ------------------------------------------------------------------
    add("## 6. Analiza pieței")
    add("")
    asks = [c.record["price_per_sqm"] for c in v.comps if c.record.get("price_per_sqm")]
    if asks:
        add(f"Aria de piață analizată cuprinde **{len(v.comps)} oferte comparabile** reținute "
            f"(după eliminarea duplicatelor și a comparabilelor supra-ajustate).")
        add("")
        add("| Indicator preț unitar de ofertă | €/mp |")
        add("|---|---|")
        add(f"| Minim | {_eur(min(asks))} |")
        if len(asks) > 3:
            q = statistics.quantiles(asks, n=4)
            add(f"| Cuartila inferioară | {_eur(q[0])} |")
            add(f"| Mediană | {_eur(statistics.median(asks))} |")
            add(f"| Cuartila superioară | {_eur(q[2])} |")
        else:
            add(f"| Mediană | {_eur(statistics.median(asks))} |")
        add(f"| Maxim | {_eur(max(asks))} |")
        add("")
        if s.get("price_per_sqm"):
            below = sum(1 for a in asks if a < s["price_per_sqm"])
            add(f"Prețul unitar cerut ({_eur(s['price_per_sqm'])}/mp) depășește {below} din "
                f"{len(asks)} oferte concurente ({below / len(asks) * 100:.0f}% din segment).")
            add("")
    add(f"*Sursa: {comps_source}*")
    add("")

    # 7 ------------------------------------------------------------------
    add("## 7. Cea mai bună utilizare")
    add("")
    add("Utilizarea rezidențială actuală este permisă juridic, posibilă fizic, fezabilă financiar "
        "și maxim productivă. Nu s-a identificat o utilizare alternativă care să genereze o valoare "
        "superioară pentru un apartament în condominiu, în acest amplasament. "
        "**CMBU = continuarea utilizării rezidențiale.**")
    add("")

    # 8 ------------------------------------------------------------------
    add("## 8. Abordarea prin comparație (SEV 103, GEV 630 §54–58)")
    add("")
    add("**Unitatea de comparație:** prețul pe metru pătrat de suprafață utilă — unitatea folosită "
        "curent de participanții la această piață.")
    add("")
    add("### 8.1 Elementele de comparație (GEV 630 §56)")
    add("")
    add("Standardul cere ca toate elementele recomandate să fie analizate, inclusiv cele care nu "
        "generează ajustare.")
    add("")
    used = {c.element for comp in v.comps for c in comp.corrections}
    explain = {
        "Drepturile de proprietate transmise": "Toate ofertele transferă drept de proprietate deplin. Fără ajustare.",
        "Condițiile de finanțare": "Nu există informații despre finanțare atipică (rate la dezvoltator, preluare credit). Fără ajustare.",
        "Condițiile de vânzare": "Ajustare aplicată — trecerea de la preț de ofertă la preț probabil de tranzacție.",
        "Cheltuielile necesare imediat după cumpărare": "Necuantificabile fără inspecție (renovări, înlocuiri). Fără ajustare; vezi condițiile limitative.",
        "Condițiile de piață": "Toate ofertele sunt active la data evaluării; nu se impune ajustare temporală.",
        "Localizarea": "Ajustare aplicată prin distanța până la metrou; comparabilele provin din aceeași arie de piață.",
        "Caracteristicile fizice": "Ajustări aplicate pentru suprafață, poziție pe verticală, an de construcție și dotări.",
        "Caracteristicile economice": "Ajustare aplicată pentru regimul de construcție (nou / existent).",
        "Caracteristici juridice": "Nu s-au identificat diferențe de regim juridic (toate în intravilan, cu destinație locuință). Fără ajustare.",
        "Componentele non-imobiliare ale proprietății": "Ajustare aplicată pentru mobilier și dotări.",
    }
    add("| Element de comparație | Tratament |")
    add("|---|---|")
    for el in COMPARISON_ELEMENTS:
        mark = "✅" if el in used else "—"
        add(f"| {mark} {el} | {explain[el]} |")
    add("")

    # 8.2 --------------------------------------------------------------
    add("### 8.2 Modul de estimare a ajustărilor (GEV 630 §58)")
    add("")
    add("Standardul interzice utilizarea oricărei ajustări fără prezentarea modului de estimare.")
    add("")
    add("| Ajustare | Mărime | Mod de estimare |")
    add("|---|---|---|")
    add(f"| Suprafață | elasticitate {r.size_elasticity.value:+.3f} | {r.size_elasticity.source()} |")
    add(f"| Parter / demisol | −{r.ground_floor.value:.1f}% | {r.ground_floor.source()} |")
    add(f"| Ultim etaj | −{r.top_floor.value:.1f}% | {r.top_floor.source()} |")
    add(f"| Marjă de negociere | {p.negotiation_base_pct:.1f}% + {p.negotiation_per_30_days_pct:.1f}%/30 zile "
        f"(plafon {p.negotiation_cap_pct:.1f}%) | GEV 630 §53 — ponderea prețului de ofertă "
        f"depinde de timpul de expunere |")
    add(f"| An construcție | {p.age_premium_per_year_pct:.2f}%/an (plafon ±{p.age_premium_cap_pct:.0f}%) | parametru de piață |")
    add(f"| Distanță metrou | până la {p.metro_discount_max_pct:.0f}% la 1.500 m | parametru de piață |")
    add(f"| Loc de parcare | {_eur(p.parking_value_eur)} | parametru de piață |")
    add(f"| Mobilier | {_eur(p.furniture_value_eur)} | parametru de piață |")
    add("")
    add("> Ajustările marcate „parametru de piață\" sunt convenții, nu estimări derivate din setul "
        "de date. Un evaluator autorizat le-ar fundamenta prin analiză pe perechi de date pe "
        "tranzacții reale — informație care nu este publică. Aceasta este a doua limitare majoră "
        "a analizei, după lipsa inspecției.")
    add("")

    # 8.3 --------------------------------------------------------------
    add("### 8.3 Grila de corecții")
    add("")
    add("| # | ID | mp | An | Etaj | Metrou | €/mp ofertă | €/mp corectat | Nr. ajustări | Ajustare brută | Ajustare netă | Pondere |")
    add("|---|---|---|---|---|---|---|---|---|---|---|---|")
    total_w = sum(c.weight for c in v.comps) or 1
    for i, c in enumerate(v.comps, 1):
        rec = c.record
        add(f"| {i} | [{rec.get('id')}]({rec.get('url')}) | {_num(rec.get('surface_sqm'))} | "
            f"{_num(rec.get('year_built'))} | {_floor_label(rec)} | {_num(rec.get('metro_distance_m'), ' m')} | "
            f"{_eur(rec.get('price_per_sqm'))} | **{_eur(c.adjusted_per_sqm)}** | {c.n_adjustments} | "
            f"{c.gross_pct:.1f}% / {_eur(c.gross_eur)} | {c.net_pct:+.1f}% / {_eur(c.net_eur)} | "
            f"{c.weight / total_w * 100:.1f}% |")
    add("")
    if v.excluded:
        add(f"**Comparabile excluse (GEV 630 §57):** {len(v.excluded)} oferte au necesitat ajustări "
            f"brute peste pragul de {p.disqualify_gross_pct:.0f}%, ceea ce le descalifică drept "
            "comparabile: " + ", ".join(f"`{e.record.get('id')}` ({e.gross_pct:.0f}%)" for e in v.excluded[:12]) + ".")
        add("")

    add("### 8.4 Selectarea concluziei (GEV 630 §57)")
    add("")
    add("| Criteriu impus de standard | Rezultat |")
    add("|---|---|")
    if v.value_range:
        add(f"| Intervalul de valori rezultate | {_eur(v.value_range[0])} – {_eur(v.value_range[1])}/mp |")
    add(f"| Numărul de ajustări per comparabilă | {min((c.n_adjustments for c in v.comps), default=0)}–"
        f"{max((c.n_adjustments for c in v.comps), default=0)} |")
    add(f"| Ajustarea brută minimă | {min((c.gross_pct for c in v.comps), default=0):.1f}% |")
    add(f"| Comparabila cea mai apropiată | {_eur(v.best_comp_per_sqm)}/mp |")
    add(f"| Comparabile descalificate prin ajustare excesivă | {len(v.excluded)} |")
    add(f"| **Valoare unitară reținută** | **{_eur(v.market_per_sqm)}/mp** |")
    add("")
    add("Concluzia este media ponderată a valorilor corectate, cu ponderi invers proporționale cu "
        "ajustarea brută — comparabila care a necesitat cele mai puține corecții cântărește cel mai "
        "mult, conform §57.")
    add("")
    add(f"**{_eur(v.market_per_sqm)}/mp × {_num(surface, ' mp')} = {_eur(v.market_value)}**")
    add("")

    add("### 8.5 Detalierea corecțiilor")
    add("")
    for i, c in enumerate(v.comps[:5], 1):
        add(f"**Comparabila {i} — `{c.record.get('id')}`** (ofertă {_eur(c.record.get('price_eur'))})")
        add("")
        add("| Element (GEV 630 §56) | Corecție | Procent | Sumă | Motiv |")
        add("|---|---|---|---|---|")
        for corr in c.corrections:
            add(f"| {corr.element} | {corr.name} | {corr.pct:+.1f}% | {_eur(corr.eur) if corr.eur else '—'} | {corr.note} |")
        add("")
    if len(v.comps) > 5:
        add(f"*Restul de {len(v.comps) - 5} comparabile urmează aceeași grilă.*")
        add("")

    # 9 ------------------------------------------------------------------
    add("## 9. Abordarea prin venit (GEV 630 §59–71)")
    add("")
    inc = v.income
    if inc.value:
        add("Metoda capitalizării directe, aplicată asupra venitului net din exploatare (§66).")
        add("")
        add("| Element | Valoare | Temei |")
        add("|---|---|---|")
        add(f"| Chirie de piață | {_eur(inc.rent_per_sqm, 1)}/mp/lună | mediana a {inc.sample} oferte de închiriere din aceeași arie |")
        add(f"| Venit brut potențial anual | {_eur(inc.potential_gross)} | §68, grad de ocupare 100% |")
        add(f"| Grad de neocupare și neîncasare | {p.vacancy_rate_pct:.0f}% | §69 |")
        add(f"| Venit brut efectiv | {_eur(inc.effective_gross)} | §69 |")
        add(f"| Cheltuieli nerecuperabile ale proprietarului | {p.operating_expense_pct:.0f}% | §70 |")
        add(f"| **Venit net din exploatare (VNE)** | **{_eur(inc.noi)}** | §70 |")
        add(f"| Rată de capitalizare | {p.capitalisation_rate_pct:.2f}% | parametru de piață, §71 |")
        add(f"| **Valoare prin capitalizare directă** | **{_eur(inc.value)}** | §65 |")
        add("")
        if v.implied_yield:
            add(f"Randamentul net implicit la prețul cerut este **{v.implied_yield:.2f}%**, față de "
                f"rata de capitalizare de {p.capitalisation_rate_pct:.2f}%. "
                + ("Sub rata de piață — prețul cerut nu se susține din perspectiva unui investitor."
                   if v.implied_yield < p.capitalisation_rate_pct else
                   "Peste rata de piață — prețul cerut este susținut din perspectiva randamentului."))
            add("")
    else:
        add("**Neaplicată.** Conform §60, abordarea prin venit nu ar trebui aplicată în lipsa unor "
            "date suficiente și credibile privind închirierea unor proprietăți similare din aceeași "
            "arie de piață. Nu s-au identificat suficiente oferte de închiriere comparabile. "
            "Abordarea prin comparație primește pondere integrală.")
        add("")
    add(f"*Sursa: {rents_source}*")
    add("")

    # 10 -----------------------------------------------------------------
    add("## 10. Abordarea prin cost (GEV 630 §72–75)")
    add("")
    add("**Neaplicată.** Conform §73, abordarea prin cost este adecvată pentru construcții noi, "
        "construcții vechi cu date suficiente pentru estimarea deprecierii, construcții în fază de "
        "proiect sau proprietăți specializate. Pentru un apartament într-un condominiu existent, "
        "două condiții nu pot fi îndeplinite: cota-parte indiviză din teren nu poate fi evaluată "
        "separat pe baza datelor disponibile, iar deprecierea cumulată nu poate fi estimată fără "
        "inspecție tehnică. Piața este activă și oferă date ample de comparație, ceea ce face "
        "abordarea prin piață superioară ca fiabilitate.")
    add("")

    # 11 -----------------------------------------------------------------
    add("## 11. Reconcilierea valorilor")
    add("")
    add("| Abordare | Valoare | Pondere | Contribuție |")
    add("|---|---|---|---|")
    if v.market_value:
        add(f"| Comparația vânzărilor | {_eur(v.market_value)} | {p.market_weight_pct:.0f}% | "
            f"{_eur(v.market_value * p.market_weight_pct / 100)} |")
    if inc.value:
        add(f"| Capitalizarea venitului | {_eur(inc.value)} | {p.income_weight_pct:.0f}% | "
            f"{_eur(inc.value * p.income_weight_pct / 100)} |")
    add(f"| **Valoare de piață estimată** | | | **{_eur(v.final_value)}** |")
    add("")
    add("Ponderea dominantă revine comparației vânzărilor: segmentul are piață activă, oferte "
        "numeroase și omogene, iar cumpărătorul tipic este utilizator final, nu investitor. "
        "Abordarea prin venit rămâne verificare încrucișată, conform §62.")
    add("")

    # 12 -----------------------------------------------------------------
    add("## 12. Analiza de senzitivitate")
    add("")
    if v.market_per_sqm and surface:
        add("| Marjă de negociere presupusă | 3% | 5% | 7% | 9% |")
        add("|---|---|---|---|---|")
        cells = []
        for m in (3.0, 5.0, 7.0, 9.0):
            scaled = v.market_per_sqm * (1 - m / 100) / (1 - p.negotiation_base_pct / 100) * surface
            blended = ((scaled * p.market_weight_pct + (inc.value or scaled) * p.income_weight_pct)
                       / (p.market_weight_pct + p.income_weight_pct))
            cells.append(_eur(blended))
        add(f"| Valoare estimată | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")
        add("")

    # 13 -----------------------------------------------------------------
    add("## 13. Riscuri identificate")
    add("")
    risks = []
    if year and year < 1978:
        risks.append("**Risc seismic** — construcție anterioară normativului din 1978. Încadrarea în "
                     "clasa RsI face imobilul negreditabil și greu vandabil. Verifică lista PMB.")
    if not s.get("exact_location"):
        risks.append("Poziția pe hartă este **aproximativă**; distanța până la metrou poate diferi "
                     "de cea publicată, iar corecția de localizare odată cu ea.")
    if s.get("metro_distance_m") is None:
        risks.append("Distanța până la metrou nu este publicată; s-a folosit o ipoteză de mijloc de interval.")
    if not has_parking(s):
        risks.append(f"Parcarea nu este menționată. Achiziția separată a unui loc costă în jur de "
                     f"{_eur(p.parking_value_eur)}.")
    if (s.get("days_on_market") or 0) > 60:
        margin, _ = negotiation_margin(s, p)
        risks.append(f"Ofertă expusă de **{s['days_on_market']} zile** — indiciu de preț peste piață. "
                     f"Marja de negociere aplicabilă unei asemenea oferte este de ordinul {margin:.1f}%.")
    if s.get("floor") == 0:
        risks.append("Parter — lichiditate redusă la revânzare și discount de piață.")
    if s.get("floors_total") and s.get("floor") == s.get("floors_total"):
        risks.append("Ultim etaj — verifică hidroizolația terasei și istoricul infiltrațiilor.")
    if len(v.comps) < 5:
        risks.append(f"Doar {len(v.comps)} comparabile reținute — interval de încredere larg. "
                     "Conform GEV 630 §57, o concluzie sprijinită pe atât de puține comparabile "
                     "trebuie tratată ca orientativă.")
    if v.extrapolated:
        sizes = [c.record["surface_sqm"] for c in v.comps if c.record.get("surface_sqm")]
        risks.append(f"**Extrapolare** — suprafața subiectului ({_num(surface, ' mp')}) se află în "
                     f"afara intervalului comparabilelor ({min(sizes):g}–{max(sizes):g} mp). "
                     "Corecția de suprafață extrapolează în afara datelor observate, iar valoarea "
                     "rezultată este mai puțin sigură decât sugerează grila.")
    if not r.size_elasticity.derived:
        risks.append("Ajustarea de suprafață nu a putut fi derivată din date și s-a folosit valoarea "
                     "implicită — fundamentare mai slabă decât cere GEV 630 §58.")
    risks.append("Suprafețele din titlurile anunțurilor sunt frecvent **construite**, nu utile; "
                 "analiza folosește suprafața utilă publicată în câmpul dedicat.")
    risks.append("Prețurile sunt de **ofertă**, nu de tranzacție. Prețurile reale de tranzacție nu "
                 "sunt publice în România, ceea ce limitează structural orice evaluare pe date publicate.")
    for item in risks:
        add(f"- {item}")
    add("")

    # 14 -----------------------------------------------------------------
    add("## 14. Verificarea conținutului minim (SEV 106 §30.6)")
    add("")
    add("| | Cerință | Stare |")
    add("|---|---|---|")
    checks = [
        ("a", "Termenii de referință conveniți", "⚠️ prezentați, dar neconveniți în scris cu clientul"),
        ("b", "Activele supuse evaluării", "✅ secțiunea 3"),
        ("c", "Identitatea evaluatorului", "❌ analiză automată, fără evaluator autorizat"),
        ("d", "Clientul", "✅ secțiunea 2 (b)"),
        ("e", "Utilizarea desemnată", "✅ secțiunea 2 (c)"),
        ("f", "Utilizatorii desemnați", "✅ secțiunea 2 (d)"),
        ("g", "Moneda evaluării", "✅ EUR"),
        ("h", "Data evaluării", f"✅ {today}"),
        ("i", "Tipul valorii", "✅ valoare de piață (SEV 102)"),
        ("j", "Abordările utilizate", "✅ secțiunile 8–10"),
        ("k", "Metodele aplicate", "✅ comparația vânzărilor; capitalizarea directă"),
        ("l", "Sursele și modul de selectare a datelor", "✅ secțiunile 6 și 9"),
        ("m", "Date de intrare ESG", "✅ secțiunea 5"),
        ("n", "Ipoteze semnificative și condiții limitative", "✅ secțiunea 4"),
        ("o", "Constatările unui specialist", "✅ nu s-a recurs la specialist"),
        ("p", "Valoarea și raționamentul", "✅ secțiunile 1 și 11"),
        ("q", "Declarația de conformitate cu SEV", "❌ **nu se afirmă** — vezi SEV 106 §30.8"),
        ("r", "Data raportului", f"✅ {today}"),
    ]
    for letter, req, state in checks:
        add(f"| ({letter}) | {req} | {state} |")
    add("")
    add("Trei cerințe nu pot fi îndeplinite de o analiză automată: (a) parțial, (c) și (q). "
        "Restul de 15 sunt acoperite.")
    add("")

    add("---")
    add("")
    add(f"*Generat de `imobiliare-mcp` la {today}, în metodologia {SEV_EDITION}. "
        "Datele provin din anunțuri publicate și nu au fost verificate independent.*")
    return "\n".join(L)
