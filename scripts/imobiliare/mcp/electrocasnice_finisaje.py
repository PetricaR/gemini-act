"""Detailed audit module for interior finishes quality, defect detection,
and appliance recognition with online valuation and retail price search.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

from imobiliare.config import get_settings

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
                    "in_fotografie": {
                        "type": "string",
                        "description": (
                            "Numărul sau descrierea fotografiei în care este vizibil "
                            "defectul (dovadă vizuală obligatorie)"
                        ),
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
                        "enum": [
                            "sigur", "probabil", "estimat_dupa_design",
                            "mentionat_in_anunt", "nedeterminat",
                        ],
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
        "incredere": {
            "type": "string",
            "enum": ["ridicata", "medie", "scazuta"],
            "description": (
                "Nivel de încredere în analiza vizuală pe baza calității "
                "și numărului de fotografii"
            ),
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
                    "certitudine_brand": "mentionat_in_anunt",
                    "gama_brand": gama,
                    "tip_montaj": "incorporat",
                    "pret_estimat_nou_eur": pret_ref,
                    "stare_uzura": "Bună / Ușoară uzură",
                    "valoare_piata_actuala_eur": int(pret_ref * 0.65),
                    "termen_cautare_online": f"Electrocasnice {nume_brand}",
                }
            )

    has_appliances = len(electro) > 0
    concluzie_text = (
        "Analiză bazată exclusiv pe descrierea text a anunțului (fără procesare fotografii). "
        + ("Au fost identificate electrocasnice menționate în text. " if has_appliances
           else "Nu au fost specificate electrocasnice în textul anunțului. ")
        + "Se recomandă inspecție tehnică vizuală la fața locului."
    )

    data = {
        "calitate_generala_finisaje": {
            "scor_global": 7,
            "clasa": "mediu",
            "stare_conservare": "Neverificată vizual (doar descriere text)",
            "concluzie": concluzie_text,
        },
        "categorii_finisaje": [
            {
                "categorie": "Finisaje generale",
                "material_identificat": "Mențiuni sumare din descriere text",
                "calitate": "mediu",
                "scor": 7,
                "stare_vizuala": "Neverificată prin imagini",
                "observatii": "Necesită inspecție la vizionare",
            },
        ],
        "defecte_si_probleme": [],
        "electrocasnice": electro,
        "sumar_financiar": {
            "total_valoare_nou_electrocasnice_eur": sum(
                e.get("pret_estimat_nou_eur", 0) for e in electro
            ),
            "total_valoare_actuala_electrocasnice_eur": sum(
                e.get("valoare_piata_actuala_eur", 0) for e in electro
            ),
            "total_buget_remediere_defecte_eur": 0,
            "impact_negociere_recomandat_eur": 0,
            "recomandare_evaluator": (
                "Electrocasnicele identificate din textul anunțului necesită "
                "verificare vizuală și probă funcțională la vizionare. "
                "Nu au fost raportate defecte în descrierea text."
                if has_appliances
                else "Nu au fost specificate electrocasnice sau defecte în textul "
                     "anunțului. Se impune inspecție vizuală detaliată."
            ),
        },
        "incredere": "scazuta",
        "mod_analiza": "fallback_fara_imagini",
        "provenienta": "anunt",
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


def _audit_indisponibil(subject: dict[str, Any], mod: str, motiv: str) -> dict[str, Any]:
    """A photo audit that did not happen.

    The heuristic read of the listing text is still returned -- it is genuinely
    useful -- but never as `status: "success"`, because the caller uses that to
    decide whether it may present the result as an inspection of the photos.
    See the tool contract in CLAUDE.md: never report a failed action as
    successful.
    """
    fallback_data = _analiza_reguli_fallback(subject)
    fallback_data["mod_analiza"] = mod
    fallback_data["provenienta"] = "anunt"
    fallback_data["incredere"] = "scazuta"
    return {
        "status": "indisponibil",
        "disponibil": False,
        "provenienta": "anunt",
        "mod_analiza": mod,
        "motiv": motiv,
        "date_analiza": fallback_data,
        "rezumat_markdown": electrocasnice_finisaje_to_markdown(fallback_data, subject),
    }


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
        return _audit_indisponibil(
            subject, "fallback_fara_imagini",
            "Anunțul nu conține fotografii care să poată fi auditate vizual.",
        )

    photos = _download(urls, limit)
    if not photos:
        logger.warning("Descărcarea fotografiilor a eșuat; se aplică analiza euristică fallback.")
        return _audit_indisponibil(
            subject, "fallback_descarcare_esuata",
            "Fotografiile anunțului nu au putut fi descărcate pentru analiză.",
        )

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai indisponibil; se aplică analiza euristică fallback.")
        return _audit_indisponibil(
            subject, "fallback_fara_genai",
            "Componenta de analiză vizuală (google-genai) nu este disponibilă.",
        )

    facts = _facts(subject)
    prompt_text = (
        "Ești un expert evaluator imobiliar tehnic și specialist în finisaje interioare "
        "și dotări pe piața rezidențială din România.\n\n"
        "Examinezi cu atenție fotografiile acestei proprietăți pentru a genera "
        "un audit tehnic riguros și obiectiv pe trei axe principale:\n\n"
        "1. RECUNOAȘTERE ELECTROCASNICE & BRANDURI:\n"
        "- Identifică fiecare aparat vizibil (plită, cuptor, hotă, frigider, "
        "mașină de spălat, AC, TV etc.).\n"
        "- Identifică brandul DOAR dacă logo-ul sau inscripția este vizibilă pe "
        "aparat (marchează 'sigur' sau 'probabil'). "
        "Dacă logo-ul nu este clar lizibil, setează certitudine_brand: "
        "'nedeterminat' sau 'estimat_dupa_design'.\n"
        "- REGULĂ DE ABȚINERE LA SERII / MODELE: NU deduce și NU inventa serii "
        "de produs din memorie sau design "
        "(de exemplu, NU inventa serii precum 'RS68A8840B1' dacă seria nu este "
        "direct lizibilă pe aparat). "
        "Dacă seria nu se poate citi cu claritate, lasă denumirea generică "
        "(ex: 'Plită inducție', 'Cuptor încorporabil').\n"
        "- Clasifică gama (Economic/Mid-range/Premium/Ultra-Lux) și starea vizuală de uzură.\n"
        "- Prețurile de magazin sunt orientative, bazate pe categoria "
        "aparatului pe piața din România.\n\n"
        "2. AUDIT DEFECTE & PROBLEME FINISAJE:\n"
        "- REGULĂ STRICTĂ DE ABȚINERE: Raportează defecte DOAR dacă sunt cert "
        "și neîndoielnic vizibile în imagini "
        "(ex: fisură structurală vizibilă, infiltrație certă de apă, faianță "
        "spartă, parchet umflat/deteriorat vizibil). "
        "Dacă nu observi defecte evidente în fotografiile furnizate, lasă lista "
        "'defecte_si_probleme' COMPLET GOALĂ ([]). "
        "NU presupune, nu căuta 'proactiv' vicii inexistente și nu inventa probleme.\n"
        "- PENTRU FIECARE DEFECT RAPORTAT, indică obligatoriu în câmpul "
        "'in_fotografie' fotografia exactă unde este vizibil "
        "(ex: 'Foto 2 - bucătărie', 'Foto 4 - baie sub chiuvetă').\n\n"
        "3. CALITATE FINISAJE & EVALUARE ÎNCREDERE:\n"
        "- Evaluează categoriile de finisaje vizibile (Pardoseli, Tâmplărie "
        "ferestre, Pereți și tencuieli, Sanitare baie).\n"
        "- Specifică nivelul de încredere global în câmpul 'incredere' "
        "('ridicata', 'medie', 'scazuta') "
        "pe baza numărului și relevanței fotografiilor (setează 'scazuta' dacă "
        "sunt sub 5 poze utile sau sunt randări 3D).\n\n"
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
        date_finale["mod_analiza"] = "gemini_vision"
        date_finale["provenienta"] = "model"
        if not date_finale.get("incredere"):
            # The prompt's own rule: 3D renders or fewer than 5 useful photos
            # mean low confidence. Photo *count* alone cannot establish a high
            # one -- when the model declined to say, the honest answer is the
            # cautious one, not a badge the evidence does not support.
            date_finale["incredere"] = "medie" if len(photos) >= 5 else "scazuta"
    except Exception as exc:
        logger.exception("Eroare la analiza electrocasnicelor și finisajelor pe %s: %s", model, exc)
        fallback_data = _analiza_reguli_fallback(subject)
        fallback_data["mod_analiza"] = "fallback_eroare_gemini"
        fallback_data["provenienta"] = "anunt"
        fallback_data["incredere"] = "scazuta"
        # The vision audit did not happen. Reporting "success" here makes the
        # caller present keyword-matching over the listing text as if it were
        # an inspection of the photographs -- see the tool contract in
        # CLAUDE.md: never report a failed action as successful.
        return {
            "status": "error",
            "disponibil": False,
            "provenienta": "anunt",
            "mod_analiza": "fallback_eroare_gemini",
            "motiv": f"Analiza vizuală nu a putut fi efectuată: {exc}",
            "error_message": f"Analiza vizuală nu a putut fi efectuată: {exc}",
            "date_analiza": fallback_data,
            "rezumat_markdown": electrocasnice_finisaje_to_markdown(fallback_data, subject),
        }

    return {
        "status": "success",
        "mod_analiza": "gemini_vision",
        "provenienta": "model",
        "fotografii_analizate": len(photos),
        "total_fotografii": len(urls),
        "date_analiza": date_finale,
        "rezumat_markdown": electrocasnice_finisaje_to_markdown(date_finale, subject),
    }
