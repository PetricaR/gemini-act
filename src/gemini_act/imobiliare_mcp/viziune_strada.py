"""Audit vizual al clădirii, străzii și împrejurimilor prin Google Street View 360° și Satelit.

Utilizează Google Street View Static API (unghiuri multiple la 360°) și Google Maps
Static Satellite pentru a oferi cumpărătorului o evaluare obiectivă a exteriorului imobilului:
starea fațadei, izolația termică, balcoanele, trotuarele, locurile de parcare, cablurile
aeriene, acoperișul din satelit și distanța reală față de vecini, analizate cu gemini-3.8-flash.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from gemini_act.config import get_settings
from gemini_act.imobiliare_mcp import maps, paths

logger = logging.getLogger(__name__)

_STREET_VIEW_AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cladire_si_fatada": {
            "type": "object",
            "properties": {
                "stare_fatada": {
                    "type": "string",
                    "description": "Starea tencuielii exterioare, culori, degradări, crăpături",
                },
                "izolatie_termica_exterioara": {
                    "type": "string",
                    "description": "Aspect izolație termică (reabilitat complet, nereabilitat)",
                },
                "balcoane_si_ferestre": {
                    "type": "string",
                    "description": "Aspect balcoane (închise unitar / eterogen / improvizat)",
                },
                "unitati_ac_si_cabluri_fatada": {
                    "type": "string",
                    "description": "Unități de aer condiționat montate pe fațadă, trasee",
                },
                "parter_si_intrare": {
                    "type": "string",
                    "description": "Intrare bloc, spații comerciale la parter, barieră, rampe",
                },
            },
            "required": [
                "stare_fatada",
                "izolatie_termica_exterioara",
                "balcoane_si_ferestre",
                "parter_si_intrare",
            ],
        },
        "strada_si_infrastructura": {
            "type": "object",
            "properties": {
                "calitate_trotuare": {
                    "type": "string",
                    "description": "Lățime trotuare, borduri, accesibilitate pietonală",
                },
                "calitate_carosabil": {
                    "type": "string",
                    "description": "Starea asfaltului, denivelări, gropi, marcaje rutiere",
                },
                "iluminat_si_retele_aeriene": {
                    "type": "string",
                    "description": "Cabluri aeriene agățate pe stâlpi vs îngropate, iluminat",
                },
            },
            "required": ["calitate_trotuare", "calitate_carosabil", "iluminat_si_retele_aeriene"],
        },
        "parcare_si_accesibilitate": {
            "type": "object",
            "properties": {
                "aglomerare_parcare": {
                    "type": "string",
                    "description": "Gradul de ocupare al parcărilor (aerisit, aglomerat, critic)",
                },
                "parcare_trotuar_sau_verde": {
                    "type": "boolean",
                    "description": "Dacă se observă mașini parcate pe trotuare sau spații verzi",
                },
                "acces_autospeciale_urgenta": {
                    "type": "string",
                    "description": "Accesibilitate autospeciale pompieri și ambulanță",
                },
            },
            "required": [
                "aglomerare_parcare",
                "parcare_trotuar_sau_verde",
                "acces_autospeciale_urgenta",
            ],
        },
        "ambient_urban_si_vecinatati": {
            "type": "object",
            "properties": {
                "tipologie_vecinatati": {
                    "type": "string",
                    "description": "Tip zonă: rezidențial blocuri, case/vile, mixt, industrial",
                },
                "spatii_verzi_si_vegetatie": {
                    "type": "string",
                    "description": "Aliniamente arbori maturi, spații verzi sau lipsă vegetație",
                },
                "potentiale_surse_disconfort": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Surse disconfort: șantiere active, trafic greu, ruine",
                },
            },
            "required": [
                "tipologie_vecinatati",
                "spatii_verzi_si_vegetatie",
                "potentiale_surse_disconfort",
            ],
        },
        "analiza_satelit": {
            "type": "object",
            "properties": {
                "acoperis_si_terasa": {
                    "type": "string",
                    "description": "Tip acoperiș din satelit (terasă hidroizolată, șarpantă)",
                },
                "densitate_construita": {
                    "type": "string",
                    "description": "aerisită, medie, densă, sufocantă",
                },
                "distanta_fata_de_cladiri_vecine": {
                    "type": "string",
                    "description": "Distanță și intimitate (generoasă >30m, medie, redusă <15m)",
                },
                "curte_interioara_sau_parcare_sol": {
                    "type": "string",
                    "description": "Descriere curte interioară, alei, parcare asfaltată la sol",
                },
            },
            "required": [
                "acoperis_si_terasa",
                "densitate_construita",
                "distanta_fata_de_cladiri_vecine",
            ],
        },
        "evaluare_globala_exterior": {
            "type": "object",
            "properties": {
                "scor_calitate_cladire_si_fatada": {
                    "type": "integer",
                    "description": "Notă de la 1 la 10 pentru aspectul și integritatea clădirii",
                },
                "scor_ambient_strada_si_zona": {
                    "type": "integer",
                    "description": "Notă de la 1 la 10 pentru calitatea străzii și vecinătăților",
                },
                "nivel_siguranta_si_civilizatie": {
                    "type": "string",
                    "description": "ridicat, mediu, scăzut",
                },
                "puncte_forte_exterioare": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Puncte forte observate din stradă și satelit",
                },
                "semnale_alarma_sau_riscuri": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Semnale de alarmă, riscuri sau defecte vizibile",
                },
                "recomandari_investigatie_pe_teren": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ce trebuie să verifice cumpărătorul fizic la fața locului",
                },
                "concluzie_audit_exterior": {
                    "type": "string",
                    "description": "Verdict rezumativ pentru decizia de achiziție",
                },
            },
            "required": [
                "scor_calitate_cladire_si_fatada",
                "scor_ambient_strada_si_zona",
                "nivel_siguranta_si_civilizatie",
                "puncte_forte_exterioare",
                "semnale_alarma_sau_riscuri",
                "concluzie_audit_exterior",
            ],
        },
    },
    "required": [
        "cladire_si_fatada",
        "strada_si_infrastructura",
        "parcare_si_accesibilitate",
        "ambient_urban_si_vecinatati",
        "evaluare_globala_exterior",
    ],
}


def street_audit_to_markdown(
    data: dict[str, Any],
    address: str = "",
    metadata: dict[str, Any] | None = None,
    images_info: dict[str, str] | None = None,
) -> str:
    """Formatează rezultatele analizei Street View și satelit într-un raport Markdown complet."""
    if not data or not isinstance(data, dict):
        return ""

    lines: list[str] = []
    add = lines.append

    add(f"## 🏙️ Audit Exterior: Fațadă, Stradă & Satelit — {address or 'Locație'}")
    add("")

    if metadata:
        data_captura = metadata.get("date", "Nespecificată")
        add(
            f"> ℹ️ **Sursa Street View**: Google Maps Car | Data capturii: **{data_captura}** "
            f"| Status: `{metadata.get('status', 'OK')}`"
        )
        add("")

    if images_info:
        add("### 📸 Imagini Capturate din Satelit & Nivelul Străzii")
        for titlu, cale in images_info.items():
            add(f"![{titlu}]({cale})")
        add("")

    eg = data.get("evaluare_globala_exterior") or {}
    scor_cladire = eg.get("scor_calitate_cladire_si_fatada", "—")
    scor_strada = eg.get("scor_ambient_strada_si_zona", "—")
    nivel_sig = str(eg.get("nivel_siguranta_si_civilizatie", "Nespecificat")).upper()

    add("### 📊 Scoruri Globale Exterior")
    add(f"- 🏢 **Scor Clădire & Fațadă**: **{scor_cladire} / 10**")
    add(f"- 🛣️ **Scor Stradă & Ambient**: **{scor_strada} / 10**")
    add(f"- 🛡️ **Nivel Civilizație & Siguranță perceput**: **{nivel_sig}**")
    add("")

    if concluzie := eg.get("concluzie_audit_exterior"):
        add(f"**Concluzie audit exterior:**\n> {concluzie}\n")

    if cladire := data.get("cladire_si_fatada"):
        add("### 🏢 Clădire, Fațadă & Balcoane")
        add(f"- **Stare fațadă:** {cladire.get('stare_fatada', '—')}")
        add(f"- **Izolație termică exterioară:** {cladire.get('izolatie_termica_exterioara', '—')}")
        add(f"- **Balcoane și ferestre:** {cladire.get('balcoane_si_ferestre', '—')}")
        if ac := cladire.get("unitati_ac_si_cabluri_fatada"):
            add(f"- **Unități AC / trasee fațadă:** {ac}")
        add(f"- **Parter și acces:** {cladire.get('parter_si_intrare', '—')}")
        add("")

    if strada := data.get("strada_si_infrastructura"):
        add("### 🚶 Stradă, Trotuare & Utilități Aeriene")
        add(f"- **Calitate trotuare & pietonal:** {strada.get('calitate_trotuare', '—')}")
        add(f"- **Calitate carosabil:** {strada.get('calitate_carosabil', '—')}")
        add(f"- **Iluminat și cabluri aeriene:** {strada.get('iluminat_si_retele_aeriene', '—')}")
        add("")

    if parcare := data.get("parcare_si_accesibilitate"):
        add("### 🚗 Parcare & Accesibilitate Autospeciale")
        add(f"- **Grad de aglomerare parcare:** {parcare.get('aglomerare_parcare', '—')}")
        pe_trotuar = "DA (Risc pietonal)" if parcare.get("parcare_trotuar_sau_verde") else "NU"
        add(f"- **Mașini parcate pe trotuar/spațiu verde:** {pe_trotuar}")
        add(f"- **Acces autospeciale urgență:** {parcare.get('acces_autospeciale_urgenta', '—')}")
        add("")

    if ambient := data.get("ambient_urban_si_vecinatati"):
        add("### 🌳 Ambient Urban & Vecinătăți Imediate")
        add(f"- **Tipologie zonă:** {ambient.get('tipologie_vecinatati', '—')}")
        add(f"- **Spații verzi & arbori:** {ambient.get('spatii_verzi_si_vegetatie', '—')}")
        if disconfort := ambient.get("potentiale_surse_disconfort"):
            add("- **Potențiale surse de disconfort:**")
            for d in disconfort:
                add(f"  - ⚠️ {d}")
        add("")

    if sat := data.get("analiza_satelit"):
        add("### 🛰️ Analiză din Satelit (Vedere Aeriană)")
        add(f"- **Acoperiș & terasă:** {sat.get('acoperis_si_terasa', '—')}")
        add(f"- **Densitate construită:** {sat.get('densitate_construita', '—')}")
        add(
            f"- **Distanță față de vecini (intimitate):** "
            f"{sat.get('distanta_fata_de_cladiri_vecine', '—')}"
        )
        if curte := sat.get("curte_interioara_sau_parcare_sol"):
            add(f"- **Curte interioară / sol:** {curte}")
        add("")

    if forte := eg.get("puncte_forte_exterioare"):
        add("### ✅ Puncte Forte Identificate")
        for pf in forte:
            add(f"- ✅ {pf}")
        add("")

    if alarme := eg.get("semnale_alarma_sau_riscuri"):
        add("### ⚠️ Semnale de Alarmă & Riscuri Observate")
        for sa in alarme:
            add(f"- ⚠️ {sa}")
        add("")

    if recs := eg.get("recomandari_investigatie_pe_teren"):
        add("### 🔍 Ce Trebuie să Verificați Fizic la Fața Locului")
        for r in recs:
            add(f"- 🔍 {r}")
        add("")

    return "\n".join(lines).strip() + "\n"


def analyse_street_and_surroundings(
    lat: float,
    lon: float,
    address: str = "",
    include_satellite: bool = True,
    save_dir: Path | str | None = None,
    client: genai.Client | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capturează imagini Google Street View multi-unghi și Satelit și le analizează cu Gemini."""
    # Not Path.cwd(): read-only on Cloud Run. A directory that cannot be
    # created means the images are analysed but not kept, which is fine --
    # `_salveaza` below skips writing when target_dir is None.
    target_dir = paths.ensure_dir(Path(save_dir) if save_dir else paths.reports_dir())

    meta = maps.street_view_metadata(lat, lon)
    headings = (0, 90, 180, 270)
    sv_angles = maps.street_view_angles(lat, lon, headings=headings, pitch=12)

    sat_img: bytes | None = None
    if include_satellite:
        sat_img = maps.satellite_view(lat, lon, zoom=18)

    if not sv_angles and not sat_img:
        return {
            "status": "no_imagery",
            "message": (
                f"Nu există imagini Google Street View sau Satelit disponibile pentru "
                f"coordonatele {lat:.5f}, {lon:.5f} ({address})."
            ),
            "rezumat_markdown": (
                f"> ⚠️ **Fără imagini disponibile**: Nu există acoperire Google Street View "
                f"la adresa indicată ({address or f'{lat:.5f}, {lon:.5f}'})."
            ),
        }

    images_info: dict[str, str] = {}
    parts: list[Any] = []

    prefix = f"{lat:.4f}_{lon:.4f}".replace(".", "_")

    angle_labels = {
        0: "Fațadă și Vedere Nord",
        90: "În lungul străzii (Est)",
        180: "Vedere peste drum / Sud",
        270: "În lungul străzii (Vest)",
    }

    for h, raw_bytes in sv_angles.items():
        fname = f"streetview_{prefix}_h{h}.jpg"
        if target_dir is not None:
            try:
                (target_dir / fname).write_bytes(raw_bytes)
                images_info[angle_labels.get(h, f"Street View {h}°")] = fname
            except OSError:
                logger.debug("Failed saving streetview image %s", fname, exc_info=True)

        lbl = angle_labels.get(h, f"Street View {h}°")
        parts.append(types.Part(text=f"Fotografie Google Street View — {lbl}:"))
        parts.append(types.Part(inline_data=types.Blob(data=raw_bytes, mime_type="image/jpeg")))

    if sat_img:
        sat_fname = f"satelit_{prefix}.png"
        if target_dir is not None:
            try:
                (target_dir / sat_fname).write_bytes(sat_img)
                images_info["Vedere Aeriană Satelit"] = sat_fname
            except OSError:
                logger.debug("Failed saving satellite image %s", sat_fname, exc_info=True)

        parts.append(
            types.Part(
                text="Imagine Google Maps Satelit (vedere aeriană de sus a clădirii și zonei):"
            )
        )
        parts.append(types.Part(inline_data=types.Blob(data=sat_img, mime_type="image/png")))

    loc_str = address or f"lat={lat:.5f}, lon={lon:.5f}"
    prompt_text = (
        "Ești un expert evaluator imobiliar ANEVAR și urbanist din România. "
        "Analizează fotografiile Google Street View (nivelul solului la 360°) și imaginea satelit "
        f"pentru locația: '{loc_str}'.\n\n"
        "Fii foarte atent și critic la detalii reale pe care un cumpărător le observă pe teren:\n"
        "1. Fațada reală a clădirii: starea tencuielii, izolație termică (polistiren/vată vizibilă "
        "sau lipsă), balcoane închise pestriț, unități de AC pe fațadă, intrarea în bloc.\n"
        "2. Calitatea străzii și trotuarelor: trotuare asfaltate/pietruite, lățime, borduri, "
        "cabluri aeriene agățate haotic pe stâlpi vs cabluri îngropate.\n"
        "3. Parcarea: mașini pe trotuar, trotuare blocate, acces autospeciale pompieri.\n"
        "4. Ambientul urban: spații verzi, arbori maturi vs uscați, șantiere, clădiri în ruină.\n"
        "5. Vederea aeriană din satelit: starea terasei/acoperișului, densitatea blocurilor vecine "
        "și gradul de intimitate (distanța dintre ferestre).\n\n"
        "Răspunde exclusiv în limba română respectând structura JSON impusă."
    )
    parts.append(types.Part(text=prompt_text))

    try:
        cfg = get_settings()
        used_model = model or getattr(cfg, "model", "gemini-3.8-flash")
        c = client or genai.Client()
        response = c.models.generate_content(
            model=used_model,
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_STREET_VIEW_AUDIT_SCHEMA,
                temperature=0.2,
            ),
        )
        parsed_data = json.loads(response.text)
    except Exception as exc:
        logger.warning("Eroare generare audit street view: %s", exc)
        return {
            "status": "error",
            "message": f"Eroare la analiza imaginilor Street View: {exc}",
            "rezumat_markdown": f"> ⚠️ Eroare la analiza vizuală: {exc}",
        }

    rezumat = street_audit_to_markdown(
        data=parsed_data,
        address=address,
        metadata=meta,
        images_info=images_info,
    )

    return {
        "status": "success",
        "adresa": address,
        "coordonate": {"lat": lat, "lon": lon},
        "metadata_street_view": meta,
        "imagini_salvate": images_info,
        "audit": parsed_data,
        "rezumat_markdown": rezumat,
    }
