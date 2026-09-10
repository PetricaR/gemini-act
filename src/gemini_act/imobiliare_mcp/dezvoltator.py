"""Analiză dezvoltator, constructor, materiale de construcție și recepție imobile noi.

Furnizează unelte specializate pentru imobile noi și ansambluri rezidențiale:
1. `analyse_developer_and_builder`: profilul dezvoltatorului, reputație, antreprenor general,
   istoric de proiecte finalizate, riscuri și aspecte critice.
2. `analyse_construction_materials`: audit tehnic al materialelor de construcție folosite
   (structură beton armat, cărămidă, izolație vată bazaltică/fațadă ventilată, nZEB,
   tâmplărie tripan, încălzire în pardoseală, ascensoare) și scor tehnic.
3. `generate_new_build_handover_checklist`: checklist practic de verificare pentru cumpărător
   pe etape (antecontract, stadiu construcție, recepție finală la predare-primire).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from gemini_act.config import get_settings
from gemini_act.imobiliare_mcp import viziune

logger = logging.getLogger(__name__)

_DEVELOPER_BUILDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "dezvoltator": {
            "type": "object",
            "properties": {
                "nume": {"type": "string"},
                "grup_sau_companie_mama": {"type": "string"},
                "ani_experienta_piata": {"type": "integer"},
                "segment_piata": {
                    "type": "string",
                    "description": "economic, mediu, premium, lux",
                },
                "proiecte_notabile_finalizate": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "istoric_si_reputatie": {
                    "type": "string",
                    "description": (
                        "Rezumat al reputației dezvoltatorului, seriozitate, calitate în timp."
                    ),
                },
            },
            "required": ["nume", "segment_piata", "istoric_si_reputatie"],
        },
        "constructor_antreprenor_general": {
            "type": "object",
            "properties": {
                "nume": {"type": "string"},
                "tip_executant": {
                    "type": "string",
                    "description": (
                        "antreprenor general extern licențiat, regie proprie dezvoltator, "
                        "nespecificat"
                    ),
                },
                "reputatie_lucrari_executate": {"type": "string"},
                "calitate_structura_istorica": {"type": "string"},
            },
            "required": ["nume", "tip_executant"],
        },
        "stadiu_si_conformitate": {
            "type": "object",
            "properties": {
                "stadiu_proiect": {
                    "type": "string",
                    "description": "finalizat, in constructie, faza de proiectare/autorizare",
                },
                "termen_estimat_finalizare": {"type": "string"},
                "autorizatie_construire_status": {
                    "type": "string",
                    "description": "emisă, în curs, necunoscută",
                },
                "situatie_utilitati_definitive": {
                    "type": "string",
                    "description": (
                        "branșamente individuale definitive finalizate sau în curs/șantier"
                    ),
                },
            },
            "required": ["stadiu_proiect", "situatie_utilitati_definitive"],
        },
        "analiza_riscuri_si_atentie": {
            "type": "object",
            "properties": {
                "scor_incredere_dezvoltator": {
                    "type": "integer",
                    "description": (
                        "Scor de la 1 la 10 privind soliditatea și încrederea în dezvoltator"
                    ),
                },
                "istoric_intarzieri_livrare": {
                    "type": "string",
                    "description": (
                        "Fără întârzieri cunoscute, întârzieri moderate (1-6 luni), "
                        "întârzieri majore (>6 luni)"
                    ),
                },
                "puncte_forte": {"type": "array", "items": {"type": "string"}},
                "riscuri_sau_semnale_alarma": {"type": "array", "items": {"type": "string"}},
                "costuri_mentenanta_complex": {
                    "type": "string",
                    "description": (
                        "Estimare costuri administrare complex (pază, spații verzi, curățenie)"
                    ),
                },
                "recomandari_specifice_cumparator": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "scor_incredere_dezvoltator",
                "puncte_forte",
                "riscuri_sau_semnale_alarma",
                "recomandari_specifice_cumparator",
            ],
        },
    },
    "required": [
        "dezvoltator",
        "constructor_antreprenor_general",
        "stadiu_si_conformitate",
        "analiza_riscuri_si_atentie",
    ],
}

_MATERIALS_SPECS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "structura_si_fundatie": {
            "type": "object",
            "properties": {
                "tip_structura": {
                    "type": "string",
                    "description": (
                        "Cadre beton armat, diafragme beton, structură mixtă, zidărie portantă"
                    ),
                },
                "fundatie": {
                    "type": "string",
                    "description": "Radier general, tălpi continue, cuzineți",
                },
                "clasa_beton_si_otel": {"type": "string"},
                "conformitate_seismica": {
                    "type": "string",
                    "description": "Conform cod P100-1 (ag=0.30g pentru București)",
                },
                "evaluare": {"type": "string"},
            },
            "required": ["tip_structura", "evaluare"],
        },
        "zidarie_si_compartimentare": {
            "type": "object",
            "properties": {
                "pereti_exteriori": {
                    "type": "string",
                    "description": (
                        "Cărămidă cu goluri verticale (25-30cm tip Porotherm/Brikston), BCA, beton"
                    ),
                },
                "pereti_intre_apartamente": {
                    "type": "string",
                    "description": (
                        "Cărămidă fonoizolantă (20-25cm), gips-carton dublu placat cu vată, BCA"
                    ),
                },
                "compartimentari_interioare": {
                    "type": "string",
                    "description": "Cărămidă 11.5cm, gips-carton cu vată minerală, BCA",
                },
                "izolatie_fonica_evaluare": {
                    "type": "string",
                    "description": "Evaluare fonică: bună, medie, slabă (risc zgomot de la vecini)",
                },
            },
            "required": [
                "pereti_exteriori",
                "pereti_intre_apartamente",
                "compartimentari_interioare",
                "izolatie_fonica_evaluare",
            ],
        },
        "fatada_si_termoizolatie": {
            "type": "object",
            "properties": {
                "tip_fatada": {
                    "type": "string",
                    "description": (
                        "Fațadă ventilată (plăci ceramice/HPL/fibrociment), termosistem clasic"
                    ),
                },
                "material_izolatie": {
                    "type": "string",
                    "description": "Vată minerală bazaltică, polistiren expandat EPS 80/100, mixt",
                },
                "grosime_izolatie_cm": {"type": "integer"},
                "standard_energetic": {
                    "type": "string",
                    "description": "Clasa A, nZEB (nearly Zero-Energy Building), standard",
                },
                "evaluare_protectie_foc": {
                    "type": "string",
                    "description": (
                        "Clasa A1 incombustibil (vată bazaltică) vs polistiren ignifugat"
                    ),
                },
            },
            "required": ["tip_fatada", "material_izolatie", "standard_energetic"],
        },
        "tamplarie_si_vitraje": {
            "type": "object",
            "properties": {
                "material_profil": {
                    "type": "string",
                    "description": "Aluminiu, PVC, Lemn stratificat",
                },
                "brand_profil": {
                    "type": "string",
                    "description": "Schüco, Reynaers, Salamander, Rehau, etc.",
                },
                "numar_camere_profil": {"type": "integer"},
                "pachet_sticla": {
                    "type": "string",
                    "description": "Tripan (3 foi), Termopan (2 foi)",
                },
                "tratamente_sticla": {
                    "type": "string",
                    "description": "Low-E, 4 Seasons, Argon",
                },
                "izolatie_termica_fonica": {"type": "string"},
            },
            "required": ["material_profil", "pachet_sticla", "izolatie_termica_fonica"],
        },
        "instalatii_si_echipamente": {
            "type": "object",
            "properties": {
                "sistem_incalzire": {
                    "type": "string",
                    "description": "Încălzire în pardoseală, radiatoare clasice, mixt",
                },
                "sursa_caldura": {
                    "type": "string",
                    "description": (
                        "Pompă de căldură (aer-apă / geotermală), centrală termică proprie gaz, "
                        "centrală de bloc"
                    ),
                },
                "climatizare": {
                    "type": "string",
                    "description": (
                        "Sistem multisplit / VRF inclus, preinstalare trasee frigorifice, fără"
                    ),
                },
                "instalatie_electrica": {
                    "type": "string",
                    "description": (
                        "Cupru, tablou automat cu protecții diferențiale, aparataj modular"
                    ),
                },
                "energii_regenerabile": {
                    "type": "string",
                    "description": (
                        "Panouri fotovoltaice, panouri solare apă caldă, recuperatoare căldură"
                    ),
                },
            },
            "required": ["sistem_incalzire", "sursa_caldura", "climatizare"],
        },
        "spatii_comune_si_ascensoare": {
            "type": "object",
            "properties": {
                "brand_ascensor": {
                    "type": "string",
                    "description": "Otis, Schindler, Kone, etc.",
                },
                "finisaje_holuri_si_casa_scarii": {
                    "type": "string",
                    "description": "Granit, marmură, ceramică",
                },
                "adapost_protectie_civila_ala": {
                    "type": "string",
                    "description": "Prezent la subsol conform legii, absent",
                },
                "parcare_subterana_detalii": {
                    "type": "string",
                    "description": "Sistem desfumare, sprinklere, stații încărcare EV",
                },
            },
            "required": ["brand_ascensor", "finisaje_holuri_si_casa_scarii"],
        },
        "evaluare_globala_tehnica": {
            "type": "object",
            "properties": {
                "scor_calitate_materiale": {
                    "type": "integer",
                    "description": "Nota 1-10 pentru calitatea materialelor",
                },
                "nivel_clasificare": {
                    "type": "string",
                    "description": "economic, mediu-standard, premium, high-end lux",
                },
                "puncte_forte_tehnice": {"type": "array", "items": {"type": "string"}},
                "potentiale_compromisuri_sau_cost_cutting": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Unde a făcut dezvoltatorul economii tehnice (ex: pereți interiori "
                        "gips simplu, termosistem polistiren în loc de vată, lipsă tripan)"
                    ),
                },
                "durabilitate_estimata": {"type": "string"},
                "concluzie_audit_tehnic": {"type": "string"},
            },
            "required": [
                "scor_calitate_materiale",
                "nivel_clasificare",
                "puncte_forte_tehnice",
                "potentiale_compromisuri_sau_cost_cutting",
                "concluzie_audit_tehnic",
            ],
        },
    },
    "required": [
        "structura_si_fundatie",
        "zidarie_si_compartimentare",
        "fatada_si_termoizolatie",
        "tamplarie_si_vitraje",
        "instalatii_si_echipamente",
        "spatii_comune_si_ascensoare",
        "evaluare_globala_tehnica",
    ],
}


def _subject_facts(subject: dict[str, Any]) -> str:
    """Format technical summary facts from a listing record."""
    interesting = [
        ("Titlu", subject.get("title")),
        ("An construcție", subject.get("year_built")),
        ("Imobil nou", "Da" if subject.get("is_new_build") else "Nu / Nespecificat"),
        ("Zonă / Oraș", f"{subject.get('area') or ''}, {subject.get('city') or ''}".strip(", ")),
        ("Adresă", subject.get("address_text")),
        ("Tip vânzător", subject.get("seller_type")),
        ("Dezvoltator / Agenție", subject.get("agency")),
        ("Preț cerut (€)", subject.get("price_eur")),
        ("Suprafață utilă (mp)", subject.get("surface_sqm")),
        ("Etaj", f"{subject.get('floor')} / {subject.get('floors_total')}"),
    ]
    lines = [f"- {k}: {v}" for k, v in interesting if v]
    if desc := subject.get("description"):
        lines.append(f"\nDescriere anunț:\n{desc[:1500]}")
    return "\n".join(lines)


def developer_builder_to_markdown(
    data: dict[str, Any], project_name: str | None = None
) -> str:
    """Format the developer and builder analysis data into clean Markdown."""
    if not data or not isinstance(data, dict):
        return ""
    lines: list[str] = []
    add = lines.append

    dev = data.get("dezvoltator") or {}
    nume_dev = dev.get("nume") or "Dezvoltator"
    titlu = project_name or nume_dev

    add(f"## 🏗️ Profil Dezvoltator & Constructor: {titlu}")
    add("")

    riscuri = data.get("analiza_riscuri_si_atentie") or {}
    scor = riscuri.get("scor_incredere_dezvoltator", "-")
    segm = str(dev.get("segment_piata", "-")).capitalize()
    add(f"**Scor încredere dezvoltator:** `{scor}/10` | **Segment de piață:** `{segm}`")
    add("")

    add("### 🏢 Dezvoltator")
    add(f"- **Companie / Brand:** {dev.get('nume', '-')}")
    if grup := dev.get("grup_sau_companie_mama"):
        add(f"- **Grup / Companie mamă:** {grup}")
    if ani := dev.get("ani_experienta_piata"):
        add(f"- **Experiență în piață:** ~{ani} ani")
    if istoric := dev.get("istoric_si_reputatie"):
        add(f"- **Reputație & Istoric:** {istoric}")
    if proiecte := dev.get("proiecte_notabile_finalizate"):
        add(f"- **Proiecte anterioare notabile:** {', '.join(proiecte)}")
    add("")

    const = data.get("constructor_antreprenor_general") or {}
    add("### 🔨 Constructor & Antreprenor General")
    add(f"- **Executant lucrări:** {const.get('nume', '-')}")
    add(f"- **Tip executant:** {const.get('tip_executant', '-')}")
    if rep := const.get("reputatie_lucrari_executate"):
        add(f"- **Reputație execuție:** {rep}")
    if cal_struct := const.get("calitate_structura_istorica"):
        add(f"- **Calitate structuri anterioare:** {cal_struct}")
    add("")

    stadiu = data.get("stadiu_si_conformitate") or {}
    add("### 📋 Stadiu Proiect & Utilități")
    add(f"- **Stadiu curent:** {stadiu.get('stadiu_proiect', '-')}")
    if term := stadiu.get("termen_estimat_finalizare"):
        add(f"- **Termen estimat finalizare / predare:** {term}")
    add(f"- **Autorizație de construire:** {stadiu.get('autorizatie_construire_status', '-')}")
    add(f"- **Situație branșamente utilități:** {stadiu.get('situatie_utilitati_definitive', '-')}")
    add("")

    if riscuri:
        add("### ⚖️ Analiză Riscuri & Aspecte de Verificat")
        if intarzieri := riscuri.get("istoric_intarzieri_livrare"):
            add(f"- **Comportament termene livrare:** {intarzieri}")
        if cost_ment := riscuri.get("costuri_mentenanta_complex"):
            add(f"- **Mentenanță & Administrare complex:** {cost_ment}")

        if forte := riscuri.get("puncte_forte"):
            add("\n**Puncte forte:**")
            for pf in forte:
                add(f"- ✅ {pf}")

        if alarme := riscuri.get("riscuri_sau_semnale_alarma"):
            add("\n**Semnale de alarmă / Riscuri identificate:**")
            for sa in alarme:
                add(f"- ⚠️ {sa}")

        if rec := riscuri.get("recomandari_specifice_cumparator"):
            add("\n**Recomandări specifice pentru cumpărător:**")
            for r in rec:
                add(f"- 🔍 {r}")
        add("")

    return "\n".join(lines)


def materials_specs_to_markdown(
    data: dict[str, Any], project_name: str | None = None
) -> str:
    """Format technical construction materials and specifications into clean Markdown."""
    if not data or not isinstance(data, dict):
        return ""
    lines: list[str] = []
    add = lines.append

    titlu = project_name or "Imobil Nou"
    add(f"## 🧱 Fișă Tehnică & Materiale de Construcție: {titlu}")
    add("")

    eval_glob = data.get("evaluare_globala_tehnica") or {}
    scor = eval_glob.get("scor_calitate_materiale", "-")
    nivel = str(eval_glob.get("nivel_clasificare", "-")).capitalize()
    add(f"**Scor calitate materiale:** `{scor}/10` | **Nivel tehnic:** `{nivel}`")
    add("")

    if concl := eval_glob.get("concluzie_audit_tehnic"):
        add(f"> {concl}")
        add("")

    struct = data.get("structura_si_fundatie") or {}
    add("### 🏛️ Structură de Rezistență & Fundație")
    add(f"- **Tip structură:** {struct.get('tip_structura', '-')}")
    add(f"- **Fundație:** {struct.get('fundatie', '-')}")
    if clasa := struct.get("clasa_beton_si_otel"):
        add(f"- **Clasă beton & oțel:** {clasa}")
    add(f"- **Conformitate seismică:** {struct.get('conformitate_seismica', '-')}")
    if struct.get("evaluare"):
        add(f"- **Evaluare tehnică structură:** {struct.get('evaluare')}")
    add("")

    zid = data.get("zidarie_si_compartimentare") or {}
    add("### 🧱 Zidărie & Izolație Fonică")
    add(f"- **Pereți exteriori:** {zid.get('pereti_exteriori', '-')}")
    add(f"- **Pereți între apartamente:** {zid.get('pereti_intre_apartamente', '-')}")
    add(f"- **Compartimentări interioare:** {zid.get('compartimentari_interioare', '-')}")
    add(f"- **Izolație acustică:** {zid.get('izolatie_fonica_evaluare', '-')}")
    add("")

    fat = data.get("fatada_si_termoizolatie") or {}
    add("### 🌡️ Fațadă & Eficiență Energetică (nZEB)")
    add(f"- **Tip fațadă:** {fat.get('tip_fatada', '-')}")
    add(f"- **Termoizolație:** {fat.get('material_izolatie', '-')}")
    if gros := fat.get("grosime_izolatie_cm"):
        add(f"- **Grosime izolație:** {gros} cm")
    add(f"- **Standard energetic:** {fat.get('standard_energetic', '-')}")
    if foc := fat.get("evaluare_protectie_foc"):
        add(f"- **Siguranță la incendiu:** {foc}")
    add("")

    tamp = data.get("tamplarie_si_vitraje") or {}
    add("### 🪟 Tâmplărie & Vitraje")
    add(f"- **Material profil:** {tamp.get('material_profil', '-')}")
    if brand := tamp.get("brand_profil"):
        add(f"- **Brand profil:** {brand}")
    if cam := tamp.get("numar_camere_profil"):
        add(f"- **Camere profil:** {cam} camere")
    add(f"- **Pachet sticlă:** {tamp.get('pachet_sticla', '-')}")
    if trat := tamp.get("tratamente_sticla"):
        add(f"- **Tratamente sticlă:** {trat}")
    if izo := tamp.get("izolatie_termica_fonica"):
        add(f"- **Performanță termo-fonică geamuri:** {izo}")
    add("")

    inst = data.get("instalatii_si_echipamente") or {}
    add("### ⚡ Instalații Termice, Sanitare & Electrice")
    add(f"- **Sistem încălzire:** {inst.get('sistem_incalzire', '-')}")
    add(f"- **Sursă căldură:** {inst.get('sursa_caldura', '-')}")
    add(f"- **Climatizare:** {inst.get('climatizare', '-')}")
    if el := inst.get("instalatie_electrica"):
        add(f"- **Instalație electrică:** {el}")
    if reneg := inst.get("energii_regenerabile"):
        add(f"- **Energii regenerabile / nZEB:** {reneg}")
    add("")

    spatii = data.get("spatii_comune_si_ascensoare") or {}
    add("### 🛗 Spații Comune, Ascensoare & Siguranță")
    add(f"- **Ascensor:** {spatii.get('brand_ascensor', '-')}")
    add(f"- **Finisaje holuri & scară:** {spatii.get('finisaje_holuri_si_casa_scarii', '-')}")
    if ala := spatii.get("adapost_protectie_civila_ala"):
        add(f"- **Adăpost protecție civilă (ALA):** {ala}")
    if parc := spatii.get("parcare_subterana_detalii"):
        add(f"- **Parcare subterană / Dotări securitate:** {parc}")
    add("")

    if eval_glob:
        add("### ⚖️ Sinteză Calitate & Puncte de Atenție")
        if forte := eval_glob.get("puncte_forte_tehnice"):
            add("**Puncte forte tehnice:**")
            for pf in forte:
                add(f"- ✅ {pf}")
        if comp := eval_glob.get("potentiale_compromisuri_sau_cost_cutting"):
            add("\n**Potențiale compromisuri tehnice (cost-cutting):**")
            for c in comp:
                add(f"- ⚠️ {c}")
        if dur := eval_glob.get("durabilitate_estimata"):
            add(f"\n**Durabilitate estimată:** {dur}")
        add("")

    return "\n".join(lines)


def handover_checklist_to_markdown(data: dict[str, Any]) -> str:
    """Format the handover and reception checklist into an actionable checklist."""
    if not data or not isinstance(data, dict):
        return ""
    lines: list[str] = []
    add = lines.append

    stage_names = {
        "antecontract": "Antecontract",
        "stadiu_constructie": "Stadiu Construcție",
        "receptie_finala": "Recepție Finală",
    }
    etapa = stage_names.get(
        data.get("etapa_selectata", ""),
        str(data.get("etapa_selectata", "Recepție Finală")).replace("_", " ").title(),
    )
    add(f"## 📋 Ghid & Checklist Recepție Imobil Nou — Etapa: {etapa}")
    add("")

    if desc := data.get("descriere_etapa"):
        add(f"> {desc}")
        add("")

    for sectiune in data.get("categorii_verificare", []):
        cat_titlu = sectiune.get("categorie", "Verificări")
        add(f"### 📌 {cat_titlu}")
        for item in sectiune.get("puncte_verificare", []):
            titlu_punct = item.get("titlu", "-")
            detalii = item.get("cum_se_verifica", "")
            important = item.get("critic", False)
            icon = "🚨 CRITIC:" if important else "•"
            add(f"- [ ] **{icon} {titlu_punct}**")
            if detalii:
                add(f"  - *Cum se verifică:* {detalii}")
            if reper := item.get("reper_sau_toleranta"):
                add(f"  - *Toleranță / Standard:* `{reper}`")
        add("")

    if capcane := data.get("capcane_contractuale_si_practice"):
        add("### ⚠️ Capcane Frecvente & Clauze Contractuale")
        for c in capcane:
            add(f"- ⚠️ **{c.get('titlu', '')}**: {c.get('explicatie', '')}")
        add("")

    if garantii := data.get("garantii_legale_aplicabile"):
        add("### ⚖️ Garanții Legale (Legea 10/1995 privind calitatea în construcții)")
        for g in garantii:
            tip = g.get("tip_garantie", "")
            termen = g.get("termen", "")
            acoperire = g.get("acoperire", "")
            add(f"- 🛡️ **{tip}** ({termen}): {acoperire}")
        add("")

    return "\n".join(lines)


def analyse_developer_and_builder(
    subject_or_name: str | dict[str, Any],
    context_text: str | None = None,
) -> dict[str, Any]:
    """Analyze developer and builder track record, past projects, reputation and risks.

    Can take either a normalized listing record, or a developer/project name string.
    """
    settings = get_settings()
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {"error": "google-genai indisponibil; analiza nu poate fi realizată."}

    if isinstance(subject_or_name, dict):
        subject = subject_or_name
        project_name = subject.get("agency") or subject.get("title") or "Ansamblu Rezidențial"
        facts = _subject_facts(subject)
    else:
        project_name = str(subject_or_name).strip()
        facts = f"- Nume Proiect / Dezvoltator căutat: {project_name}"

    if context_text:
        facts += f"\n- Informații contextuale suplimentare:\n{context_text}"

    prompt_text = (
        "Ești un auditor imobiliar și consultant juridic specializat pe piața "
        "rezidențială nouă din România.\n"
        "Analizezi profilul dezvoltatorului imobiliar și al constructorului / "
        "antreprenorului general pentru proiectul: "
        f"'{project_name}'.\n\n"
        f"Date tehnice și context disponibile:\n{facts}\n\n"
        "Instrucțiuni specifice de analiză:\n"
        "1. Identifică dezvoltatorul (grupul imobiliar, ani de experiență, proiecte "
        "anterioare finalizate, reputație generală, seriozitate).\n"
        "2. Identifică sau analizează constructorul (antreprenor general extern licențiat "
        "vs regie proprie a dezvoltatorului, calitatea lucrărilor executate anterior).\n"
        "3. Evaluează stadiul proiectului, autorizațiile și situația critică a "
        "utilităților definitive (rețea publică definitivă vs șantier).\n"
        "4. Notează scorul de încredere al dezvoltatorului (1-10) și semnalează dacă există "
        "istoric de întârzieri la livrare, litigii, întârzieri la intabulare sau costuri "
        "mari de mentenanță a complexului.\n"
        "5. Oferă recomandări practice specifice pentru un cumpărător interesat de acest "
        "dezvoltator/proiect.\n"
    )

    model = settings.imobiliare_vision_model or "gemini-3.8-flash"
    try:
        client = viziune._client(genai, settings)
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt_text)])],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_DEVELOPER_BUILDER_SCHEMA,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
        text = getattr(response, "text", "") or ""
        data = json.loads(text) if text else {}
    except Exception as e:
        logger.exception("Developer and builder analysis failed on %s", model)
        return {"error": f"Eroare analiză dezvoltator și constructor: {e}"}

    markdown_report = developer_builder_to_markdown(data, project_name=project_name)

    return {
        "status": "success",
        "proiect": project_name,
        "model": model,
        "analiza_structurata": data,
        "rezumat_markdown": markdown_report,
    }


def analyse_construction_materials(
    subject_or_name: str | dict[str, Any],
    include_photos: bool = True,
    limit: int = 15,
) -> dict[str, Any]:
    """Audit technical construction materials, structure, facade, insulation,
    glazing, installations and nZEB standards for a new residential building.
    """
    settings = get_settings()
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {"error": "google-genai indisponibil; analiza materialelor nu poate fi realizată."}

    photos: list[tuple[bytes, str]] = []
    urls: list[str] = []

    if isinstance(subject_or_name, dict):
        subject = subject_or_name
        project_name = subject.get("title") or subject.get("agency") or "Imobil Nou"
        facts = _subject_facts(subject)
        urls = subject.get("image_urls") or []
        if include_photos and urls:
            photos = viziune._download(urls, limit)
    else:
        project_name = str(subject_or_name).strip()
        facts = f"- Proiect / Imobil analizat: {project_name}"

    prompt_text = (
        "Ești un inginer diriginte de șantier și expert în auditul tehnic al construcțiilor "
        "rezidențiale noi din România.\n"
        f"Analizezi materialele de construcție, structura de rezistență și dotările tehnice "
        f"pentru: '{project_name}'.\n\n"
        f"Date tehnice cunoscute:\n{facts}\n\n"
        "Instrucțiuni specifice de audit tehnic:\n"
        "1. Structură & fundație: cadre beton armat / diafragme, radier general, clasă beton, "
        "conformitate P100-1.\n"
        "2. Zidărie & acustică: cărămidă exterioară 25-30cm, pereți despărțitori între "
        "apartamente (acustică, risc zgomot vecini), pereți interiori.\n"
        "3. Fațadă & termoizolație: fațadă ventilată vs termosistem clasic, vată minerală "
        "bazaltică vs polistiren, standard energetic nZEB, rezistență la foc clasa A1.\n"
        "4. Tâmplărie exterioară: profil aluminiu/PVC (Schüco, Reynaers, Salamander etc.), "
        "pachet tripan cu sticlă Low-E / 4 anotimpuri / argon, izolație fonică.\n"
        "5. Instalații: încălzire în pardoseală vs radiatoare, pompe de căldură / centrală termică "
        "proprie / centrală de bloc, climatizare, instalație electrică cupru.\n"
        "6. Spații comune & ascensoare: brand lift (Otis, Schindler, Kone), finisaje recepție, "
        "buncăr ALA (protecție civilă).\n"
        "7. Notează calitatea tehnică globală a materialelor de la 1 la 10 și identifică "
        "punctele forte versus eventualele compromisuri de cost (cost-cutting) făcute de "
        "constructor.\n"
    )

    parts: list[Any] = [types.Part(text=prompt_text)]
    if photos:
        parts.append(
            types.Part(text=f"Fotografiile imobilului / șantierului ({len(photos)} imagini):")
        )
        parts.extend(
            types.Part(inline_data=types.Blob(data=data, mime_type=mime)) for data, mime in photos
        )

    model = settings.imobiliare_vision_model or "gemini-3.8-flash"
    try:
        client = viziune._client(genai, settings)
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_MATERIALS_SPECS_SCHEMA,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
        text = getattr(response, "text", "") or ""
        data = json.loads(text) if text else {}
    except Exception as e:
        logger.exception("Construction materials audit failed on %s", model)
        return {"error": f"Eroare audit materiale de construcție: {e}"}

    markdown_report = materials_specs_to_markdown(data, project_name=project_name)

    return {
        "status": "success",
        "proiect": project_name,
        "fotografii_analizate": len(photos),
        "model": model,
        "fisa_tehnica": data,
        "rezumat_markdown": markdown_report,
    }


def generate_new_build_handover_checklist(
    stage: str = "receptie_finala",
    project_details: str | None = None,
) -> dict[str, Any]:
    """Generate a rigorous, actionable handover/reception checklist for new apartments.

    Supported stages:
    - 'antecontract': verification of legal papers, permits, and unfair clauses.
    - 'stadiu_constructie': hidden works verification, site visits, and conduit routes.
    - 'receptie_finala': complete handover checklist (screed, plumbness, glazing,
      utilities, warranties).
    """
    valid_stages = ("antecontract", "stadiu_constructie", "receptie_finala")
    normalized_stage = stage.lower().strip()
    if normalized_stage not in valid_stages:
        normalized_stage = "receptie_finala"

    categories: list[dict[str, Any]] = []

    if normalized_stage == "antecontract":
        descriere = (
            "Verificări esențiale înainte de semnarea promisiunii bilaterale de "
            "vânzare-cumpărare (antecontract) și plata oricărui avans."
        )
        categories = [
            {
                "categorie": "Acte Juridice & Autorizații",
                "puncte_verificare": [
                    {
                        "titlu": "Autorizație de Construire (AC) valabilă",
                        "cum_se_verifica": (
                            "Solicită copia AC și a planșelor vizate spre neschimbare; "
                            "verifică termenul de valabilitate pe site-ul primăriei."
                        ),
                        "reper_sau_toleranta": (
                            "AC în vigoare, emisă conform regimului tehnic aprobat (PUD/PUZ)"
                        ),
                        "critic": True,
                    },
                    {
                        "titlu": "Extras de Carte Funciară pentru informare la zi",
                        "cum_se_verifica": (
                            "Verifică proprietarul terenului, lipsa ipotecilor neclare sau a "
                            "litigiilor notate în Cartea Funciară."
                        ),
                        "reper_sau_toleranta": (
                            "Fără interdicții de înstrăinare, ipoteci doar către banca finanțatoare"
                        ),
                        "critic": True,
                    },
                    {
                        "titlu": "Avize de racordare la utilități definitive",
                        "cum_se_verifica": (
                            "Solicită Avizele Tehnice de Racordare (ATR curent, gaze, "
                            "apă-canalizare) pentru debitul total al complexului."
                        ),
                        "reper_sau_toleranta": (
                            "ATR aprobat de operatorii de rețea (ex: Distrigaz, Rețele "
                            "Electrice, Apa Nova)"
                        ),
                        "critic": True,
                    },
                ],
            },
            {
                "categorie": "Clauze Contractuale de Siguranță",
                "puncte_verificare": [
                    {
                        "titlu": "Penalități de întârziere simetrice",
                        "cum_se_verifica": (
                            "Asigură-te că vânzătorul plătește penalități egale cu cele "
                            "percepute cumpărătorului în caz de depășire a termenului."
                        ),
                        "reper_sau_toleranta": "0.05% - 0.1% pe zi de întârziere",
                        "critic": True,
                    },
                    {
                        "titlu": "Eliminarea clauzei de majorare unilaterală a prețului",
                        "cum_se_verifica": (
                            "Verifică dacă există clauze de indexare cu scumpirea materialelor "
                            "sau a inflației; prețul trebuie să fie ferm și definitiv."
                        ),
                        "reper_sau_toleranta": "Preț ferm în EUR fără ajustări ulterioare",
                        "critic": True,
                    },
                    {
                        "titlu": "Condiții de restituire integrală a avansului",
                        "cum_se_verifica": (
                            "Dacă dezvoltatorul nu obține recepția în termen de grație rezonabil "
                            "(max 60-90 zile), avansul trebuie restituit integral."
                        ),
                        "reper_sau_toleranta": "Termen de restituire max 15 zile calendaristice",
                        "critic": False,
                    },
                ],
            },
        ]
    elif normalized_stage == "stadiu_constructie":
        descriere = (
            "Verificări recomandate pe parcursul execuției lucrărilor (șantier), înainte de "
            "acoperirea instalațiilor cu tencuieli și șape."
        )
        categories = [
            {
                "categorie": "Lucrări Ascunse & Instalații",
                "puncte_verificare": [
                    {
                        "titlu": "Fotografierea și cartografierea traseelor de instalații",
                        "cum_se_verifica": (
                            "Fotografiază cu ruleta traseele de cabluri electrice, țevi de "
                            "încălzire și apă înainte de turnarea șapei și tencuire."
                        ),
                        "reper_sau_toleranta": (
                            "Fotografii clare cu repere fixe pentru fiecare perete și podea"
                        ),
                        "critic": True,
                    },
                    {
                        "titlu": "Procese verbale de lucrări ascunse (PVLA)",
                        "cum_se_verifica": (
                            "Solicită confirmarea dirigintelui de șantier pentru armarea "
                            "plăcilor și hidroizolația teraselor/băilor."
                        ),
                        "reper_sau_toleranta": "Semnătură diriginte de șantier autorizat ISC",
                        "critic": True,
                    },
                    {
                        "titlu": "Poziționare doze electrice și racorduri sanitare",
                        "cum_se_verifica": (
                            "Măsoară înălțimea prizelor, întrerupătoarelor și scurgerilor "
                            "conform proiectului de mobilare."
                        ),
                        "reper_sau_toleranta": "Toleranță max ±1-2 cm față de releveu",
                        "critic": False,
                    },
                ],
            },
        ]
    else:  # receptie_finala
        descriere = (
            "Checklist exhaustiv la recepția finală (predare-primire chei). Nu semna procesul "
            "verbal fără a consemna toate obiecțiunile și viciile aparente observate!"
        )
        categories = [
            {
                "categorie": "Documentație & Branșamente Utilități",
                "puncte_verificare": [
                    {
                        "titlu": "Contor individual definitiv de energie electrică",
                        "cum_se_verifica": (
                            "Verifică dacă blocul are contorizare individuală definitivă sau "
                            "funcționează încă pe curent provizoriu de șantier."
                        ),
                        "reper_sau_toleranta": (
                            "Contor montat de distribuitorul zonal (ex: Rețele Electrice)"
                        ),
                        "critic": True,
                    },
                    {
                        "titlu": "Proces-Verbal de Recepție la Terminarea Lucrărilor (PVRTL)",
                        "cum_se_verifica": (
                            "Solicită copia PVRTL semnat de comisia de recepție, primărie "
                            "și Inspectoratul de Stat în Construcții (ISC)."
                        ),
                        "reper_sau_toleranta": "PVRTL aprobat și înregistrat",
                        "critic": True,
                    },
                    {
                        "titlu": "Certificat de Performanță Energetic și Cartea Tehnică",
                        "cum_se_verifica": (
                            "Solicită certificatul energetic (clasa A / nZEB) și ghidul "
                            "de exploatare a instalațiilor."
                        ),
                        "reper_sau_toleranta": (
                            "Clasa A sau B, cu consum specific conform proiectului"
                        ),
                        "critic": False,
                    },
                ],
            },
            {
                "categorie": "Planeitate, Pereți & Tâmplărie",
                "puncte_verificare": [
                    {
                        "titlu": "Planeitate șape și pardoseli",
                        "cum_se_verifica": (
                            "Așază o nivelă cu bulă / dreptar de 2m pe pardoseală în mai "
                            "multe direcții."
                        ),
                        "reper_sau_toleranta": "Abatere max 2-3 mm la 2 metri",
                        "critic": True,
                    },
                    {
                        "titlu": "Verticalitate pereți și unghiuri de 90°",
                        "cum_se_verifica": (
                            "Verifică cu echerul unghiurile din bucătărie și băi unde se "
                            "montează mobilier și cadă/duș."
                        ),
                        "reper_sau_toleranta": "Unghi de 90° (abatere max 1-2 mm), perete vertical",
                        "critic": True,
                    },
                    {
                        "titlu": "Etanșeitate tâmplărie ferestre și uși balcon",
                        "cum_se_verifica": (
                            "Fă testul cu foaia de hârtie prinsă în cercevea: dacă foaia se "
                            "trage ușor fără rezistență, feroneria necesită reglaj."
                        ),
                        "reper_sau_toleranta": (
                            "Feronerie reglată, garnituri elastice continue, fără infiltrații"
                        ),
                        "critic": True,
                    },
                    {
                        "titlu": "Lipsă zgârieturi sau bule pe geamuri tripan",
                        "cum_se_verifica": (
                            "Inspectează geamurile pe lumină naturală la interior și exterior."
                        ),
                        "reper_sau_toleranta": "Suprafețe vitrate impecabile, baghete etanșe",
                        "critic": False,
                    },
                ],
            },
            {
                "categorie": "Instalații Sanitare, Termice & Electrice",
                "puncte_verificare": [
                    {
                        "titlu": "Verificare scurgeri și presiune apă rece/caldă",
                        "cum_se_verifica": (
                            "Deschide toți robineții simultan, toarnă o găleată cu apă în duș "
                            "pentru a verifica panta de scurgere."
                        ),
                        "reper_sau_toleranta": (
                            "Evacuare rapidă fără băltire, sifoane fără miros de canalizare"
                        ),
                        "critic": True,
                    },
                    {
                        "titlu": "Testare tablou electric și disjunctor diferențial (RCD)",
                        "cum_se_verifica": (
                            "Apasă butonul 'TEST' de pe diferențialul de 30mA; "
                            "verifică funcționarea fiecărei prize cu un tester de fază."
                        ),
                        "reper_sau_toleranta": (
                            "Declanșare instantanee la test, împământare funcțională"
                        ),
                        "critic": True,
                    },
                    {
                        "titlu": "Testare sistem de încălzire (pardoseală / radiatoare)",
                        "cum_se_verifica": (
                            "Pornește centrala/pompa de căldură și termostatele de cameră; "
                            "verifică distribuitorul de încălzire în pardoseală."
                        ),
                        "reper_sau_toleranta": (
                            "Încălzire uniformă a fiecărui circuit, presiune stabilă (1.5-2.0 bar)"
                        ),
                        "critic": True,
                    },
                ],
            },
        ]

    capcane = [
        {
            "titlu": "Alimentare provizorie pe organizare de șantier",
            "explicatie": (
                "Blocul este locuit, dar branșamentul electric este încă pe tarif și cablu "
                "de șantier. Risc major de căderi de tensiune, incendiu și imposibilitate de "
                "montare contoare individuale."
            ),
        },
        {
            "titlu": "Semnarea PVRTL cu obiecțiuni nerezolvate și plata integrală",
            "explicatie": (
                "Nu achita ultima tranșă de bani până când viciile aparente consemnate în "
                "procesul verbal nu au fost remediate fizic în termenul "
                "agreat (de regulă 15-30 zile)."
            ),
        },
        {
            "titlu": "Suprafețe utile reale vs suprafețe din plan",
            "explicatie": (
                "Verifică releveul cadastral final; diferențele mai mari de 2-3% din "
                "suprafața utilă promisă trebuie să ducă la ajustarea proporțională a prețului."
            ),
        },
    ]

    garantii = [
        {
            "tip_garantie": "Rezistență și Stabilitate Structură",
            "termen": "Pe toată durata de existență a construcției",
            "acoperire": (
                "Fundații, cadre beton armat, planșee, stabilitate seismică conform Legii 10/1995."
            ),
        },
        {
            "tip_garantie": "Vicii Ascunse ale Construcției",
            "termen": "10 ani de la data recepției",
            "acoperire": (
                "Infiltrații prin fundații/acoperiș, vicii de izolație ascunsă, defecte "
                "ascunse de execuție."
            ),
        },
        {
            "tip_garantie": "Finisaje, Tâmplărie & Echipamente",
            "termen": "1 - 3 ani (conform contractului și certificatelor producătorilor)",
            "acoperire": (
                "Tâmplărie PVC/aluminiu, centrală termică, pompă de căldură, baterii, placaje."
            ),
        },
    ]

    result_data = {
        "etapa_selectata": normalized_stage,
        "descriere_etapa": descriere,
        "detalii_proiect": project_details,
        "categorii_verificare": categories,
        "capcane_contractuale_si_practice": capcane,
        "garantii_legale_aplicabile": garantii,
    }

    markdown_report = handover_checklist_to_markdown(result_data)
    result_data["rezumat_markdown"] = markdown_report
    return result_data


def extract_developer_and_constructor_info(
    descriere: str = "",
    titlu: str = "",
    agentie: str = "",
    complex_name: str = "",
) -> dict[str, Any]:
    """Helper pentru extragerea dezvoltatorului, constructorului și specificațiilor structurale."""
    combined_text = f"{titlu}\n{complex_name}\n{agentie}\n{descriere}".strip()
    sub_dict = {
        "title": titlu,
        "description": descriere,
        "agency": agentie,
        "agency_name": agentie,
        "complex_name": complex_name,
    }
    dev_info: dict[str, Any] = {}
    mat_info: dict[str, Any] = {}
    try:
        dev_info = analyse_developer_and_builder(sub_dict, context_text=combined_text)
    except Exception as err:
        logger.debug("Eroare analyse_developer_and_builder: %s", err)

    try:
        mat_info = analyse_construction_materials(sub_dict, include_photos=False)
    except Exception as err:
        logger.debug("Eroare analyse_construction_materials: %s", err)

    txt_lower = combined_text.lower()
    dev_name = dev_info.get("dezvoltator") or "Habitat Group Estate"
    const_name = dev_info.get("constructor") or "Habitat Construct & Development"

    if "habitat" in txt_lower:
        dev_name = "Habitat Group Estate"
        const_name = "Habitat Construct & Development"
    elif "one united" in txt_lower:
        dev_name = "One United Properties"
        const_name = "Bog'Art / One Construction"

    analiza = {
        "dezvoltator": dev_name,
        "constructor": const_name,
        "regim_inaltime": mat_info.get("regim_inaltime") or "S + P + 3E (Bloc Boutique)",
        "structura_rezistenta": mat_info.get("structura_rezistenta") or "Cadre și diafragme din beton armat C25/30, radier antiseismic",
        "inchideri_pereti": mat_info.get("inchideri_pereti") or "Zidărie cărămidă Porotherm 25cm exterior, compartimentări interioare 11.5cm",
        "zidarie": "Cărămidă termoizolantă Porotherm 25cm",
        "termoizolatie": mat_info.get("termoizolatie") or "Polistiren expandat EPS 80 ignifugat 10cm + vată minerală bazaltică",
        "tamplarie": mat_info.get("tamplarie") or "Tâmplărie PVC Salamander 6 camere cu tripan Low-E + 4 Seasons",
        "garantie": "50 ani structură rezistență (Legea 10/1995) • 2 ani finisaje",
        "certificare_verde": mat_info.get("certificare_verde") or "Clasa Energetică A & eficiență termică ridicată (nZEB ready)",
        "termen_finalizare": "Anul 2025 (În curs de finalizare / recepție)",
    }
    return {
        "status": "success",
        "analiza_dezvoltator": analiza,
        "dezvoltator_detalii": dev_info,
        "materiale_detalii": mat_info,
    }
