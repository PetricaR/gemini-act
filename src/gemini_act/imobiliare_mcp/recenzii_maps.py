"""Modul pentru citirea și analiza recenziilor Google Maps pentru dezvoltatori și imobile."""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from typing import Any

import httpx
from google import genai
from google.genai import types

from gemini_act.config import get_settings

logger = logging.getLogger(__name__)

PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACE_DETAILS_URL = "https://places.googleapis.com/v1/places"
TIMEOUT = 12.0

_SCHEMA_RECENZII = {
    "type": "OBJECT",
    "properties": {
        "scor_reputatie": {
            "type": "NUMBER",
            "description": "Scor de reputație de la 1.0 la 10.0 pe baza satisfacției clienților.",
        },
        "calificativ_reputatie": {
            "type": "STRING",
            "description": "Calificativ: Excelentă, Bună, Moderată, Problematică, Risc Ridicat.",
        },
        "puncte_forte_apreciate": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "Aspecte pozitive remarcate de clienți sau locatari.",
        },
        "probleme_reclamate_frecvent": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": (
                "Reclamații sau vicii raportate: întârzieri recepție, infiltrații, "
                "izolație fonică slabă, locuri de parcare, atitudine administrație etc."
            ),
        },
        "recomandare_cumparator": {
            "type": "STRING",
            "description": "Sfat concret pentru un potențial cumpărător la vizionare.",
        },
    },
    "required": [
        "scor_reputatie",
        "calificativ_reputatie",
        "puncte_forte_apreciate",
        "probleme_reclamate_frecvent",
        "recomandare_cumparator",
    ],
}


def _key() -> str:
    """Returnează cheia Google Maps Platform."""
    return get_settings().maps_api_key or ""


def cauta_place_id(query: str) -> dict[str, Any] | None:
    """Caută un loc după denumire sau adresă și returnează datele de identificare."""
    api_key = _key()
    if not api_key:
        return None

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.rating,places.userRatingCount,places.googleMapsUri"
        ),
    }
    payload = {"textQuery": query, "languageCode": "ro"}

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(PLACES_TEXT_SEARCH_URL, headers=headers, json=payload)
            if resp.status_code == 200:
                places = resp.json().get("places", [])
                if places:
                    first = places[0]
                    return {
                        "place_id": first.get("id"),
                        "nume": (first.get("displayName") or {}).get("text"),
                        "adresa": first.get("formattedAddress"),
                        "rating": first.get("rating"),
                        "numar_recenzii": first.get("userRatingCount"),
                        "link_maps": first.get("googleMapsUri"),
                    }
    except Exception as exc:
        logger.warning("Eroare căutare Google Places pentru '%s': %s", query, exc)
    return None


def obtine_recenzii_place(place_id: str) -> dict[str, Any] | None:
    """Extrage recenziile complete pentru un loc dat prin ID-ul său Google Maps."""
    api_key = _key()
    if not api_key:
        return None

    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "id,displayName,formattedAddress,rating,userRatingCount,"
            "googleMapsUri,reviews"
        ),
    }
    url = f"{PLACE_DETAILS_URL}/{place_id}"

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, headers=headers, params={"languageCode": "ro"})
            if resp.status_code == 200:
                data = resp.json()
                raw_reviews = data.get("reviews", [])
                curate = []
                for r in raw_reviews:
                    text_obj = r.get("text") or {}
                    text_content = (
                        text_obj.get("text")
                        if isinstance(text_obj, dict)
                        else str(text_obj)
                    )
                    author_obj = r.get("authorAttribution") or {}
                    curate.append({
                        "autor": author_obj.get("displayName", "Anonim"),
                        "rating": r.get("rating", 0),
                        "timp_relativ": r.get("relativePublishTimeDescription", ""),
                        "text": text_content,
                    })

                return {
                    "place_id": place_id,
                    "nume": (data.get("displayName") or {}).get("text"),
                    "adresa": data.get("formattedAddress"),
                    "rating_global": data.get("rating"),
                    "total_recenzii": data.get("userRatingCount"),
                    "link_maps": data.get("googleMapsUri"),
                    "recenzii": curate,
                }
    except Exception as exc:
        logger.warning("Eroare detalii recenzii Google Places pentru '%s': %s", place_id, exc)
    return None


def _normalizeaza(text: str) -> str:
    """Lowercase and strip diacritics, so keyword lists need only one spelling.

    Reviews are written both ways ("întârziere" / "intarziere"); matching the
    raw text meant half the keyword list could never fire.
    """
    lowered = (text or "").lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Romanian ș/ț sometimes arrive as the pre-composed comma-below letters,
    # which NFKD does not decompose on every platform.
    return folded.replace("ș", "s").replace("ş", "s").replace("ț", "t").replace("ţ", "t")


def _contine(text: str, *keywords: str) -> bool:
    """Whole-word keyword match against already-normalised text.

    Substring matching is wrong here: "apa" is inside "apartament", the most
    common word in these reviews, and produced a water-damage red flag on
    every positive review. Multi-word keywords match as phrases.
    """
    return any(re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text) for k in keywords)


def _analiza_reguli_fallback(date_recenzii: dict[str, Any]) -> dict[str, Any]:
    """Generare analiză pe bază de reguli dacă modelul LLM nu este disponibil."""
    rating = float(date_recenzii.get("rating_global") or 0.0)
    recenzii = date_recenzii.get("recenzii", [])
    puncte_forte: list[str] = []
    probleme: list[str] = []

    text_unificat = _normalizeaza(" ".join(r.get("text", "") for r in recenzii))

    # Detecție probleme comune. Keywords are diacritic-free: the text is folded
    # to match. Prefer specific stems over short ones that hide inside
    # unrelated words.
    if _contine(text_unificat, "intarziere", "intarzieri", "intarziat", "intarziata",
                "amanat", "amanata", "depasit termenul", "peste termen"):
        probleme.append("Întârzieri raportate la finalizarea sau predarea proiectului")
    if _contine(text_unificat, "infiltratii", "infiltratie", "igrasie", "mucegai",
                "hidroizolatie", "inundat", "scurgeri", "umezeala"):
        probleme.append("Probleme de hidroizolație, umezeală sau infiltrații semnalate")
    if _contine(text_unificat, "zgomot", "zgomotos", "fonic", "fonica",
                "pereti subtiri", "se aude"):
        probleme.append("Izolație fonică slabă între apartamente menționată de locatari")
    if _contine(text_unificat, "parcare", "parcari", "locuri de parcare", "aglomerat"):
        probleme.append("Dificultăți legate de locurile de parcare sau aglomerația auto")
    if _contine(text_unificat, "greu de contactat", "nu raspund", "nu raspunde",
                "arogant", "aroganti", "comunicare proasta", "comunicare dificila"):
        probleme.append("Comunicare anevoioasă cu dezvoltatorul sau echipa post-vânzare")

    # Detecție aspecte pozitive
    if _contine(text_unificat, "serios", "seriosi", "profesionist", "profesionisti",
                "recomand", "calitate"):
        puncte_forte.append("Apreciat pentru seriozitate și profesionalism")
    if _contine(text_unificat, "finisaje bune", "finisaje de calitate", "curat",
                "frumos", "design", "spatios"):
        puncte_forte.append("Finisaje de calitate și spații bine compartimentate")
    if _contine(text_unificat, "la timp", "fara intarziere", "punctual", "punctuali"):
        puncte_forte.append("Predare conform termenelor asumate")

    if not puncte_forte and rating >= 4.0:
        puncte_forte.append("Evaluare medie pozitivă pe Google Maps")
    if not puncte_forte:
        puncte_forte.append("Nu sunt suficiente detalii pozitive evidențiate")

    if not probleme and rating < 4.0:
        probleme.append("Rating global modest fără detalieri specifice în text")
    if not probleme:
        probleme.append("Nu există reclamații grave sau recurente în eșantionul curent")

    # No rating means no reputation measurement. A placeholder score would be
    # rendered as if it had been read off Google Maps.
    if rating <= 0:
        return {
            "status": "indisponibil",
            "disponibil": False,
            "provenienta": "indisponibil",
            "motiv": "Locația nu are un rating Google Maps public din care să se derive un scor.",
            "scor_reputatie": None,
            "calificativ_reputatie": None,
            "puncte_forte_apreciate": puncte_forte,
            "probleme_reclamate_frecvent": probleme,
            "recomandare_cumparator": None,
        }

    scor = round(rating * 2.0, 1)
    if scor >= 8.5:
        calificativ = "Excelentă"
        sfat = "Dezvoltatorul/complexul beneficiază de recenzii foarte favorabile."
    elif scor >= 7.0:
        calificativ = "Bună"
        sfat = "Reputație bună pe piață, verificați doar micile detalii de finisaj."
    elif scor >= 5.0:
        calificativ = "Moderată"
        sfat = "Verificați riguros izolația fonică și istoricul respectării termenelor."
    else:
        calificativ = "Problematică"
        sfat = "Risc de disconfort post-vânzare; solicitați garanții contractuale ferme."

    return {
        "status": "success",
        "disponibil": True,
        "provenienta": "reguli",
        "scor_reputatie": scor,
        "calificativ_reputatie": calificativ,
        "puncte_forte_apreciate": puncte_forte,
        "probleme_reclamate_frecvent": probleme,
        "recomandare_cumparator": sfat,
    }


def analizeaza_recenzii_gemini(date_locatie: dict[str, Any]) -> dict[str, Any]:
    """Analizează sentimentul și extrage riscurile din recenzii folosind gemini-3.8-flash."""
    recenzii = date_locatie.get("recenzii", [])
    if not recenzii:
        return _analiza_reguli_fallback(date_locatie)

    text_recenzii = "\n---\n".join([
        f"Rating: {r.get('rating')}★ | Data: {r.get('timp_relativ')}\nRecenzie: {r.get('text')}"
        for r in recenzii[:10]
    ])

    nume_loc = date_locatie.get("nume")
    adr_loc = date_locatie.get("adresa")
    rating_loc = date_locatie.get("rating_global")
    tot_rec = date_locatie.get("total_recenzii")
    prompt = f"""Ești un expert în audit imobiliar și protecția cumpărătorului de locuințe.
Analizează următoarele recenzii Google Maps pentru:
Nume: {nume_loc}
Adresă: {adr_loc}
Rating mediu: {rating_loc}★ din {tot_rec} recenzii.

Recenzii disponibile:
{text_recenzii}

Instrucțiuni:
1. Evaluează reputația reală a dezvoltatorului / complexului rezidențial.
2. Identifică probleme recurente din prisma unui viitor locatar (infiltrații, izolație fonică slabă,
   întârzieri la intabulare/branșamente, costuri ascunse, probleme cu parcarea).
3. Evidențiază punctele forte confirmate de rezidenți.
4. Oferă o recomandare pragmatică pentru cumpărător înainte de a semna antecontractul.
"""

    try:
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCHEMA_RECENZII,
                temperature=0.2,
            ),
        )
        if response.text:
            return json.loads(response.text)
    except Exception as exc:
        logger.warning("Eroare analiză recenzii cu Gemini: %s. Se folosește fallback.", exc)

    return _analiza_reguli_fallback(date_locatie)


def citeste_si_analizeaza_recenzii_google(query_sau_place_id: str) -> dict[str, Any]:
    """Extrage și analizează recenziile Google Maps pentru un dezvoltator, complex sau adresă."""
    termen = query_sau_place_id.strip()
    date_locatie = None

    # Dacă pare un place_id (începe cu ChIJ...)
    if termen.startswith("ChIJ"):
        date_locatie = obtine_recenzii_place(termen)
    else:
        info_cautare = cauta_place_id(termen)
        if info_cautare and info_cautare.get("place_id"):
            date_locatie = obtine_recenzii_place(info_cautare["place_id"])
            if not date_locatie:
                date_locatie = {
                    "place_id": info_cautare["place_id"],
                    "nume": info_cautare.get("nume"),
                    "adresa": info_cautare.get("adresa"),
                    "rating_global": info_cautare.get("rating"),
                    "total_recenzii": info_cautare.get("numar_recenzii"),
                    "link_maps": info_cautare.get("link_maps"),
                    "recenzii": [],
                }

    if not date_locatie:
        return {
            "status": "not_found",
            "mesaj": f"Nu s-a găsit locația sau profilul Google Maps pentru '{termen}'.",
        }

    analiza = analizeaza_recenzii_gemini(date_locatie)
    date_locatie["analiza_sentiment"] = analiza

    return {
        "status": "success",
        "locatie": date_locatie,
        "markdown": recenzii_to_markdown(date_locatie),
    }


def recenzii_to_markdown(data: dict[str, Any]) -> str:
    """Formatează datele și analiza recenziilor Google Maps în Markdown."""
    nume = data.get("nume") or "Locație / Dezvoltator"
    rating = data.get("rating_global") or "N/A"
    total = data.get("total_recenzii") or 0
    analiza = data.get("analiza_sentiment") or {}

    linii = [
        f"### ⭐ Recenzii & Reputație Google Maps: {nume}",
        "",
        f"- **Rating Mediu:** **{rating} ★** ({total} recenzii înregistrate)",
        f"- **Adresă:** {data.get('adresa', 'N/A')}",
    ]
    if data.get("link_maps"):
        linii.append(f"- **Link Google Maps:** [Vezi profilul complet]({data['link_maps']})")
    linii.append("")

    if analiza:
        scor = analiza.get("scor_reputatie")
        calificativ = analiza.get("calificativ_reputatie")
        if scor is None:
            linii.extend([
                "#### 🔍 Scor Reputație Comunitate: indisponibil",
                "",
                "> ⚠️ " + (analiza.get("motiv")
                           or "Nu există un rating public pentru această locație."),
                "",
            ])
        else:
            linii.extend([
                f"#### 🔍 Scor Reputație Comunitate: **{scor} / 10** ({calificativ})",
                "",
            ])

        if analiza.get("puncte_forte_apreciate"):
            linii.append("**Puncte forte confirmate de locatari / cumpărători:**")
            for pf in analiza["puncte_forte_apreciate"]:
                linii.append(f"- 🟢 {pf}")
            linii.append("")

        if analiza.get("probleme_reclamate_frecvent"):
            linii.append("**Reclamații și semnale de alarmă identificate:**")
            for pr in analiza["probleme_reclamate_frecvent"]:
                linii.append(f"- ⚠️ {pr}")
            linii.append("")

        sfat = analiza.get("recomandare_cumparator")
        if sfat:
            linii.extend([
                f"**Recomandare pentru vizionare:** {sfat}",
                "",
            ])

    recenzii = data.get("recenzii", [])
    if recenzii:
        linii.extend([
            "#### 💬 Exemple Recenzii Recente",
            "",
        ])
        for r in recenzii[:3]:
            autor = r.get("autor", "Anonim")
            stele = "★" * int(r.get("rating", 0))
            timp = r.get("timp_relativ", "")
            text = (r.get("text") or "").strip()
            if text:
                linii.append(f"> **{autor}** ({stele}, {timp}):\n> \"{text[:300]}\"\n")

    return "\n".join(linii)


# Alias de compatibilitate
obtine_si_analizeaza_recenzii = citeste_si_analizeaza_recenzii_google
