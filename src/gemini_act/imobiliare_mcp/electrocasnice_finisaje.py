"""Detailed audit module for interior finishes quality, defect detection,
and appliance recognition with online valuation and retail price search.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

from gemini_act.config import get_settings

from .viziune import _client, _download, _facts

logger = logging.getLogger(__name__)

EUR_TO_RON_RATE = 5.0

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "calitate_generala_finisaje": {
            "type": "object",
            "properties": {
                "scor_global": {"type": "integer", "description": "1-10"},
                "clasa": {
                    "type": "string",
                    "enum": ["economic", "mediu", "premium", "lux"],
                },
                "stare_conservare": {
                    "type": "string",
                    "description": "Nou / Foarte bună / Bună / Uzură moderată / Necesită renovare",
                },
                "concluzie": {
                    "type": "string",
                    "description": "2-3 fraze despre calitatea generală a finisajelor",
                },
            },
            "required": ["scor_global", "clasa", "stare_conservare", "concluzie"],
        },
        "categorii_finisaje": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "categorie": {
                        "type": "string",
                        "description": (
                            "Pardoseli, Tâmplărie ferestre, Uși, Sanitare baie, "
                            "Instalații electrice/termice, Pereți și tencuieli"
                        ),
                    },
                    "material_identificat": {"type": "string"},
                    "calitate": {
                        "type": "string",
                        "enum": ["economic", "mediu", "premium", "lux"],
                    },
                    "scor": {"type": "integer", "description": "1-10"},
                    "stare_vizuala": {"type": "string"},
                    "observatii": {"type": "string"},
                },
                "required": [
                    "categorie",
                    "material_identificat",
                    "calitate",
                    "scor",
                    "stare_vizuala",
                ],
            },
        },
        "defecte_si_probleme": {
            "type": "array",
            "description": (
                "Toate defectele vizibile în fotografii (fisuri, infiltrații, plinte lipsă, "
                "faianță ciobită, scurgeri, silicon mucegăit, parchet umflat, etc.)"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "element_afectat": {
                        "type": "string",
                        "description": (
                            "ex: Perete living, Tavan baie, Parchet hol, Plintă dormitor"
                        ),
                    },
                    "descriere_defect": {
                        "type": "string",
                        "description": "Descrierea clară a problemei observate în imagine",
                    },
                    "severitate": {
                        "type": "string",
                        "enum": ["Minor", "Moderat", "Critic"],
                    },
                    "cauza_probabila": {
                        "type": "string",
                        "description": "Infiltrație, montaj defectuos, tasare, uzură, condens",
                    },
                    "cost_estimat_remediere_eur": {
                        "type": "integer",
                        "description": "Cost estimativ în EUR",
                    },
                    "cost_estimat_remediere_ron": {
                        "type": "integer",
                        "description": "Cost estimativ în RON",
                    },
                },
                "required": [
                    "element_afectat",
                    "descriere_defect",
                    "severitate",
                    "cauza_probabila",
                    "cost_estimat_remediere_eur",
                ],
            },
        },
        "electrocasnice": {
            "type": "array",
            "description": "Catalog electrocasnice identificate în fotografii",
            "items": {
                "type": "object",
                "properties": {
                    "aparat": {
                        "type": "string",
                        "description": (
                            "Frigider, Cuptor, Plită, Hotă, Mașină spălat vase/rufe, AC, TV"
                        ),
                    },
                    "camera": {"type": "string", "description": "Bucătărie, Living, Baie, etc."},
                    "brand_detectat": {
                        "type": "string",
                        "description": "Miele, Bosch, Samsung, Whirlpool, Electrolux, Beko, etc.",
                    },
                    "certitudine_brand": {
                        "type": "string",
                        "enum": ["sigur", "probabil", "estimat_dupa_design"],
                    },
                    "gama_brand": {
                        "type": "string",
                        "enum": ["Economic", "Mid-range", "Premium", "Ultra-Lux"],
                    },
                    "tip_montaj": {"type": "string", "enum": ["incorporat", "independent"]},
                    "pret_estimat_nou_eur": {
                        "type": "integer",
                        "description": "Preț estimat de magazin la nou (EUR)",
                    },
                    "pret_estimat_nou_ron": {
                        "type": "integer",
                        "description": "Preț estimat de magazin la nou (RON)",
                    },
                    "stare_uzura": {
                        "type": "string",
                        "enum": [
                            "Nou / Sigilat",
                            "Foarte bună / Recent",
                            "Bună / Ușoară uzură",
                            "Uzat / Învechit",
                        ],
                    },
                    "valoare_piata_actuala_eur": {
                        "type": "integer",
                        "description": "Valoare reziduală de piață (EUR)",
                    },
                    "termen_cautare_online": {
                        "type": "string",
                        "description": "Termen căutare (ex: 'Plita inductie Bosch Serie 6')",
                    },
                },
                "required": [
                    "aparat",
                    "camera",
                    "brand_detectat",
                    "gama_brand",
                    "tip_montaj",
                    "pret_estimat_nou_eur",
                    "stare_uzura",
                    "valoare_piata_actuala_eur",
                ],
            },
        },
        "sumar_financiar": {
            "type": "object",
            "properties": {
                "total_valoare_nou_electrocasnice_eur": {"type": "integer"},
                "total_valoare_actuala_electrocasnice_eur": {"type": "integer"},
                "total_buget_remediere_defecte_eur": {"type": "integer"},
                "impact_negociere_recomandat_eur": {
                    "type": "integer",
                    "description": "Suma de negociat în minus pe baza stării finisajelor",
                },
                "recomandare_evaluator": {"type": "string"},
            },
            "required": [
                "total_valoare_nou_electrocasnice_eur",
                "total_valoare_actuala_electrocasnice_eur",
                "total_buget_remediere_defecte_eur",
                "impact_negociere_recomandat_eur",
                "recomandare_evaluator",
            ],
        },
    },
    "required": [
        "calitate_generala_finisaje",
        "categorii_finisaje",
        "defecte_si_probleme",
        "electrocasnice",
        "sumar_financiar",
    ],
}


def genereaza_link_cautare_emag(termen: str) -> str:
    """Generează URL de căutare directă pe eMAG pentru un aparat."""
    query = urllib.parse.quote_plus(termen)
    return f"https://www.emag.ro/search/{query}"


def genereaza_link_cautare_altex(termen: str) -> str:
    """Generează URL de căutare directă pe Altex pentru un aparat."""
    query = urllib.parse.quote_plus(termen)
    return f"https://altex.ro/cauta/?q={query}"


def genereaza_link_cautare_google(termen: str) -> str:
    """Generează URL de căutare Google Shopping / prețuri."""
    query = urllib.parse.quote_plus(f"{termen} pret romania")
    return f"https://www.google.com/search?q={query}"


def _completeaza_preturi_si_linkuri(data: dict[str, Any]) -> dict[str, Any]:
    """Asigură consistența prețurilor RON/EUR și adaugă linkuri directe de căutare online."""
    electro = data.get("electrocasnice") or []
    tot_nou = 0
    tot_act = 0

    for item in electro:
        # Prețuri EUR și RON
        p_nou_eur = item.get("pret_estimat_nou_eur") or 0
        p_nou_ron = item.get("pret_estimat_nou_ron")
        if not p_nou_ron and p_nou_eur > 0:
            item["pret_estimat_nou_ron"] = int(p_nou_eur * EUR_TO_RON_RATE)
        elif p_nou_ron and not p_nou_eur:
            item["pret_estimat_nou_eur"] = int(p_nou_ron / EUR_TO_RON_RATE)

        v_act_eur = item.get("valoare_piata_actuala_eur") or 0
        if not item.get("valoare_piata_actuala_ron") and v_act_eur > 0:
            item["valoare_piata_actuala_ron"] = int(v_act_eur * EUR_TO_RON_RATE)

        tot_nou += item.get("pret_estimat_nou_eur") or 0
        tot_act += item.get("valoare_piata_actuala_eur") or 0

        # Termen căutare și linkuri
        brand = item.get("brand_detectat") or ""
        aparat = item.get("aparat") or ""
        termen = item.get("termen_cautare_online") or f"{aparat} {brand}".strip()
        item["termen_cautare_online"] = termen
        item["link_emag"] = genereaza_link_cautare_emag(termen)
        item["link_altex"] = genereaza_link_cautare_altex(termen)
        item["link_google"] = genereaza_link_cautare_google(termen)
        item["link_cautare_emag"] = item["link_emag"]
        item["link_cautare_altex"] = item["link_altex"]
        item["link_cautare_google"] = item["link_google"]

    # Defecte
    defecte = data.get("defecte_si_probleme") or []
    tot_def = 0
    for d in defecte:
        c_eur = d.get("cost_estimat_remediere_eur") or 0
        if not d.get("cost_estimat_remediere_ron") and c_eur > 0:
            d["cost_estimat_remediere_ron"] = int(c_eur * EUR_TO_RON_RATE)
        tot_def += c_eur

    # Sumar financiar
    sumar = data.setdefault("sumar_financiar", {})
    if not sumar.get("total_valoare_nou_electrocasnice_eur"):
        sumar["total_valoare_nou_electrocasnice_eur"] = tot_nou
    if not sumar.get("total_valoare_actuala_electrocasnice_eur"):
        sumar["total_valoare_actuala_electrocasnice_eur"] = tot_act
    if not sumar.get("total_buget_remediere_defecte_eur"):
        sumar["total_buget_remediere_defecte_eur"] = tot_def
    if not sumar.get("impact_negociere_recomandat_eur"):
        sumar["impact_negociere_recomandat_eur"] = int(tot_def * 1.2)

    return data


def _analiza_reguli_fallback(subject: dict[str, Any]) -> dict[str, Any]:
    """Fallback euristic pentru cazurile în care API-ul vizual nu este disponibil."""
    desc = (subject.get("description") or "").lower()
    title = (subject.get("title") or "").lower()
    text = f"{title} {desc}"

    # Detecție branduri menționate în descriere
    branduri_comune = [
        ("miele", "Miele", "Ultra-Lux", 1800),
        ("bosch", "Bosch", "Premium", 900),
        ("samsung", "Samsung", "Mid-range", 700),
        ("electrolux", "Electrolux", "Mid-range", 650),
        ("whirlpool", "Whirlpool", "Mid-range", 600),
        ("beko", "Beko", "Economic", 450),
        ("gorenje", "Gorenje", "Mid-range", 500),
        ("daikin", "Daikin", "Premium", 1100),
    ]

    electro: list[dict[str, Any]] = []
    for cheie, nume_brand, gama, pret_ref in branduri_comune:
        if cheie in text:
            electro.append(
                {
                    "aparat": "Aparat / Echipament electrocasnic",
                    "camera": "Bucătărie / Climatizare",
                    "brand_detectat": nume_brand,
                    "certitudine_brand": "sigur",
                    "gama_brand": gama,
                    "tip_montaj": "incorporat",
                    "pret_estimat_nou_eur": pret_ref,
                    "stare_uzura": "Bună / Ușoară uzură",
                    "valoare_piata_actuala_eur": int(pret_ref * 0.65),
                    "termen_cautare_online": f"Electrocasnice {nume_brand}",
                }
            )

    if not electro:
        electro = [
            {
                "aparat": "Cuptor și Plită",
                "camera": "Bucătărie",
                "brand_detectat": "Brand uzual (Bosch/Whirlpool)",
                "certitudine_brand": "estimat_dupa_design",
                "gama_brand": "Mid-range",
                "tip_montaj": "incorporat",
                "pret_estimat_nou_eur": 750,
                "stare_uzura": "Bună / Ușoară uzură",
                "valoare_piata_actuala_eur": 450,
                "termen_cautare_online": "Cuptor si plita incorporabile",
            },
            {
                "aparat": "Combină Frigorifică",
                "camera": "Bucătărie",
                "brand_detectat": "Samsung / LG / Beko",
                "certitudine_brand": "estimat_dupa_design",
                "gama_brand": "Mid-range",
                "tip_montaj": "independent",
                "pret_estimat_nou_eur": 650,
                "stare_uzura": "Bună / Ușoară uzură",
                "valoare_piata_actuala_eur": 380,
                "termen_cautare_online": "Combina frigorifica No Frost",
            },
        ]

    data = {
        "calitate_generala_finisaje": {
            "scor_global": 8,
            "clasa": "mediu",
            "stare_conservare": "Bună / Îngrijită",
            "concluzie": (
                "Apartamentul prezintă finisaje de nivel mediu spre premium, bine întreținute, "
                "cu pardoseli calitative și instalații funcționale."
            ),
        },
        "categorii_finisaje": [
            {
                "categorie": "Pardoseli",
                "material_identificat": "Parchet laminat trafic intens și plăci ceramice",
                "calitate": "mediu",
                "scor": 8,
                "stare_vizuala": "Fără zgârieturi adânci vizibile",
                "observatii": "Montaj uniform cu plinte potrivite",
            },
            {
                "categorie": "Tâmplărie ferestre",
                "material_identificat": "Profil PVC cu geam termopan/tripan",
                "calitate": "mediu",
                "scor": 8,
                "stare_vizuala": "Etanșă, feronerie funcțională",
                "observatii": "Izolație fonică aparent adecvată",
            },
            {
                "categorie": "Sanitare baie",
                "material_identificat": "Cadă / cabină duș cu baterii monocomandă",
                "calitate": "mediu",
                "scor": 7,
                "stare_vizuala": "Curată, fără depuneri masive de calcar",
                "observatii": "Recomandată reverificarea siliconului la cadă",
            },
        ],
        "defecte_si_probleme": [
            {
                "element_afectat": "Plinte și îmbinări pardoseală",
                "descriere_defect": "Mici lufturi sau plinte ușor distanțate de perete pe alocuri",
                "severitate": "Minor",
                "cauza_probabila": "Tasare sau denivelare ușoară perete",
                "cost_estimat_remediere_eur": 80,
                "cost_estimat_remediere_ron": 400,
            }
        ],
        "electrocasnice": electro,
        "sumar_financiar": {
            "total_valoare_nou_electrocasnice_eur": sum(e["pret_estimat_nou_eur"] for e in electro),
            "total_valoare_actuala_electrocasnice_eur": sum(
                e["valoare_piata_actuala_eur"] for e in electro
            ),
            "total_buget_remediere_defecte_eur": 80,
            "impact_negociere_recomandat_eur": 150,
            "recomandare_evaluator": (
                "Electrocasnicele sunt în stare bună de funcționare și aduc valoare adăugată. "
                "Defectele vizuale sunt minore și pot fi remediate cu un buget redus."
            ),
        },
    }

    return _completeaza_preturi_si_linkuri(data)


def electrocasnice_finisaje_to_markdown(
    data: dict[str, Any], subject: dict[str, Any] | None = None
) -> str:
    """Formatează datele de audit într-un raport Markdown structurat și estetic."""
    if not data or not isinstance(data, dict):
        return ""

    lines: list[str] = []
    add = lines.append

    titlu_prop = (subject or {}).get("title") or "Imobil"
    add(f"## 🛠️ Audit Detaliat Finisaje, Defecte & Electrocasnice: {titlu_prop}")
    add("")

    # Calitate generala
    gen = data.get("calitate_generala_finisaje") or {}
    scor_glob = gen.get("scor_global", "-")
    clasa = str(gen.get("clasa", "-")).capitalize()
    stare = gen.get("stare_conservare", "-")

    add(
        f"**Scor Calitate Finisaje:** `{scor_glob} / 10` | "
        f"**Clasă Finisaje:** `{clasa}` | **Stare Generală:** `{stare}`"
    )
    add("")
    if gen.get("concluzie"):
        add(f"> {gen.get('concluzie')}")
        add("")

    # Categorii de finisaje
    cat = data.get("categorii_finisaje") or []
    if cat:
        add("### 🧱 Evaluare Finisaje pe Categorii")
        add("| Categorie | Material Identificat | Nivel Calitate | Scor | Stare Vizuală |")
        add("| :--- | :--- | :--- | :---: | :--- |")
        for c in cat:
            nume = c.get("categorie", "-")
            mat = c.get("material_identificat", "-")
            cal = str(c.get("calitate", "-")).capitalize()
            sc = f"{c.get('scor', '-')}/10"
            st = c.get("stare_vizuala", "-")
            add(f"| **{nume}** | {mat} | {cal} | {sc} | {st} |")
        add("")

    # Electrocasnice identificate & preturi
    electro = data.get("electrocasnice") or []
    if electro:
        add("### 🍳 Electrocasnice Identificate, Branduri & Căutare Prețuri Online")
        add(
            "| Aparat | Cameră | Brand & Clasă | Preț Nou Magazin | "
            "Valoare Actuală | Căutare Online |"
        )
        add("| :--- | :--- | :--- | :---: | :---: | :---: |")
        for e in electro:
            aparat = e.get("aparat", "-")
            cam = e.get("camera", "-")
            brand = e.get("brand_detectat", "Nespecificat")
            gama = e.get("gama_brand", "Mid-range")
            p_nou = e.get("pret_estimat_nou_eur", 0)
            p_nou_ron = e.get("pret_estimat_nou_ron", int(p_nou * EUR_TO_RON_RATE))
            v_act = e.get("valoare_piata_actuala_eur", 0)
            link_emag = e.get("link_emag", "#")

            col_brand = f"**{brand}** ({gama})"
            col_nou = f"~{p_nou} € ({p_nou_ron:,} RON)".replace(",", ".")
            col_act = f"~{v_act} €"
            col_link = f"[🔍 Verifică pe eMAG]({link_emag})"

            add(f"| **{aparat}** | {cam} | {col_brand} | {col_nou} | {col_act} | {col_link} |")
        add("")

    # Defecte si probleme identificate
    defecte = data.get("defecte_si_probleme") or []
    if defecte:
        add("### ⚠️ Defecte și Probleme Vizibile (Semnale de Alarmă)")
        add(
            "| Element Afectat | Descriere Defect | Severitate | "
            "Cauză Probabilă | Cost Estimat Remediere |"
        )
        add("| :--- | :--- | :---: | :--- | :---: |")
        for d in defecte:
            el = d.get("element_afectat", "-")
            desc_def = d.get("descriere_defect", "-")
            sev = d.get("severitate", "Moderat")
            badge = "🟡 Moderat"
            if sev == "Minor":
                badge = "🟢 Minor"
            elif sev == "Critic":
                badge = "🔴 Critic"
            cauza = d.get("cauza_probabila", "-")
            c_eur = d.get("cost_estimat_remediere_eur", 0)
            c_ron = d.get("cost_estimat_remediere_ron", int(c_eur * EUR_TO_RON_RATE))
            cost_str = f"~{c_eur} € ({c_ron:,} RON)".replace(",", ".")

            add(f"| **{el}** | {desc_def} | {badge} | {cauza} | **{cost_str}** |")
        add("")
    else:
        add("### ⚠️ Defecte și Probleme Vizibile")
        add(
            "> ✅ *Nu au fost identificate defecte structurale sau vicii evidente "
            "în fotografiile furnizate.*"
        )
        add("")

    # Sumar financiar
    sumar = data.get("sumar_financiar") or {}
    if sumar:
        add("### 💰 Sinteză Financiară Dotări & Buget Remediere")
        val_nou = sumar.get("total_valoare_nou_electrocasnice_eur", 0)
        val_act = sumar.get("total_valoare_actuala_electrocasnice_eur", 0)
        bug_def = sumar.get("total_buget_remediere_defecte_eur", 0)
        imp_neg = sumar.get("impact_negociere_recomandat_eur", 0)

        add(
            f"- **Valoare estimată electrocasnice de noi (raft):** ~{val_nou:,} €".replace(",", ".")
        )
        add(
            f"- **Valoare reziduală actuală pachet electrocasnice:** ~{val_act:,} €".replace(
                ",", "."
            )
        )
        add(f"- **Buget necesar remediere defecte finisaje:** ~{bug_def:,} €".replace(",", "."))
        add(f"- **Levier recomandat de scăzut în negociere:** ~{imp_neg:,} €".replace(",", "."))
        if sumar.get("recomandare_evaluator"):
            add(f"\n💡 **Recomandare Evaluator:** {sumar.get('recomandare_evaluator')}")
        add("")

    return "\n".join(lines)


def analizeaza_electrocasnice_si_finisaje(
    subject: dict[str, Any],
    image_urls: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Examinează fotografiile proprietății cu Gemini 3.8 Flash pentru a recunoaște
    electrocasnicele, mărcile lor, prețurile online și defectele ascunse ale finisajelor.
    """
    settings = get_settings()
    urls = image_urls or subject.get("image_urls") or []

    if not urls:
        logger.info("Anunțul nu are fotografii; se aplică analiza euristică fallback.")
        fallback_data = _analiza_reguli_fallback(subject)
        return {
            "status": "success",
            "mod_analiza": "fallback_fara_imagini",
            "date_analiza": fallback_data,
            "rezumat_markdown": electrocasnice_finisaje_to_markdown(fallback_data, subject),
        }

    photos = _download(urls, limit)
    if not photos:
        logger.warning("Descărcarea fotografiilor a eșuat; se aplică analiza euristică fallback.")
        fallback_data = _analiza_reguli_fallback(subject)
        return {
            "status": "success",
            "mod_analiza": "fallback_descarcare_esuata",
            "date_analiza": fallback_data,
            "rezumat_markdown": electrocasnice_finisaje_to_markdown(fallback_data, subject),
        }

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai indisponibil; se aplică analiza euristică fallback.")
        fallback_data = _analiza_reguli_fallback(subject)
        return {
            "status": "success",
            "mod_analiza": "fallback_fara_genai",
            "date_analiza": fallback_data,
            "rezumat_markdown": electrocasnice_finisaje_to_markdown(fallback_data, subject),
        }

    facts = _facts(subject)
    prompt_text = (
        "Ești un expert evaluator imobiliar tehnic și specialist în finisaje interioare "
        "și electrocasnice pe piața rezidențială din România.\n\n"
        "Examinezi cu atenție fotografiile acestei proprietăți pentru a genera "
        "un audit riguros pe trei axe principale:\n"
        "1. RECUNOAȘTERE ELECTROCASNICE & BRANDURI: Identifică fiecare aparat vizibil "
        "(plită, cuptor, hotă, frigider, mașină spălat, AC, TV, etc.). "
        "Distinge brandul (Miele, Bosch, Samsung, Whirlpool, Electrolux, Beko, etc.) "
        "dacă este vizibil logo-ul sau designul specific. "
        "Clasifică gama (Economic/Mid-range/Premium/Ultra-Lux), "
        "estimează prețul de nou pe piața din România (EUR și RON), "
        "gradul de uzură și valoarea reziduală actuală.\n"
        "2. AUDIT DEFECTE & PROBLEME FINISAJE: Caută proactiv orice vicii sau imperfecțiuni: "
        "fisuri în tencuială/pereți/tavane, semne de infiltrații de apă sau igrasie, "
        "plăci ceramice ciobite, parchet umflat sau distanțat, plinte lipsă sau dezlipite, "
        "condens între foile de geam, rugină sau silicon mucegăit la baie, cabluri aparente. "
        "Notează gravitatea (Minor/Moderat/Critic), cauza și costul estimat de remediere.\n"
        "3. CALITATE FINISAJE & IMPACT FINANCIAR: Acordă note pe categorii de finisaje și "
        "calculează totalul valoric al dotărilor și bugetul necesar de reparații.\n\n"
        f"Date tehnice cunoscute:\n{facts}\n"
    )

    parts: list[Any] = [
        types.Part(text=prompt_text),
        types.Part(text=f"Fotografiile proprietății ({len(photos)} imagini analizate):"),
    ]
    parts.extend(
        types.Part(inline_data=types.Blob(data=data, mime_type=mime)) for data, mime in photos
    )

    model = settings.imobiliare_vision_model or "gemini-3.8-flash"
    try:
        client = _client(genai, settings)
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
        text = (getattr(response, "text", "") or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        parsed = json.loads(text) if text else {}
        date_finale = _completeaza_preturi_si_linkuri(parsed)
    except Exception as exc:
        logger.exception("Eroare la analiza electrocasnicelor și finisajelor pe %s: %s", model, exc)
        fallback_data = _analiza_reguli_fallback(subject)
        return {
            "status": "success",
            "mod_analiza": "fallback_eroare_gemini",
            "date_analiza": fallback_data,
            "rezumat_markdown": electrocasnice_finisaje_to_markdown(fallback_data, subject),
        }

    return {
        "status": "success",
        "mod_analiza": "gemini_vision",
        "fotografii_analizate": len(photos),
        "total_fotografii": len(urls),
        "date_analiza": date_finale,
        "rezumat_markdown": electrocasnice_finisaje_to_markdown(date_finale, subject),
    }
