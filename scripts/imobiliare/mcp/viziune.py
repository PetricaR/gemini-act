"""Letting the model actually look at the property.

A valuation done at a distance has no inspection. Under SEV 106 that is a
stated limitation, not a detail — and the photographs are the only evidence
left about condition, finishes, light and layout, which is exactly what
separates two flats with identical surface, floor and year.

`galerie.py` already folded the gallery into one contact sheet, and `evaluare`
already had an `observatii_vizuale` parameter for what that sheet showed. But
nothing ever looked: the tool returned a *file path*, and a file path is not
something a model can see. The parameter only ever held text a caller had
written by hand, so in an automated run the report's visual section was empty
and every conclusion rested on the numbers alone.

This closes that loop. The images are sent to Gemini as inline image parts —
the real bytes, not a path — with a valuation-specific brief, and come back as
structured findings that the report files under "Caracteristicile fizice".

Three sources, in descending order of how much the seller controls them:

* the listing gallery — the rooms, chosen and framed by the seller;
* Street View — the facade, the block and the street, which the seller did not
  choose and often would not have photographed;
* the static map — what actually surrounds the building.

The findings are advisory. They are written into the report as observations
with their own confidence attached, and they never silently move the estimated
value: an adjustment a buyer cannot audit is worth less than no adjustment.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from imobiliare.config import get_settings

from . import throttle

logger = logging.getLogger(__name__)

# The gallery is served from the portal's CDN, which refuses requests that do
# not look like they came from the site — same reason `galerie.py` sets these.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.imobiliare.ro/",
}

# Condition grades, coarsest first. Deliberately the vocabulary a Romanian
# listing uses, so the model is choosing a label the market already means
# something by rather than inventing a scale.
CONDITION_GRADES = (
    "lux",
    "renovat recent",
    "bun",
    "mediu",
    "necesita renovare",
    "la rosu",
    "nedeterminat",
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stare_generala": {"type": "string", "enum": list(CONDITION_GRADES)},
        "scor_stare": {
            "type": "integer",
            "description": "1 = la roșu / degradat, 10 = lux, finisaje noi",
        },
        "finisaje": {"type": "string", "description": "Pardoseli, uși, tâmplărie, băi, bucătărie"},
        "lumina": {"type": "string", "description": "Orientare aparentă, câtă lumină naturală"},
        "compartimentare": {"type": "string", "description": "Decomandat/semidecomandat, fluxuri"},
        "fatada_bloc": {
            "type": "string",
            "description": "Din Street View: starea faţadei, anvelopare, curte, parcare, stradă",
        },
        "semne_ingrijorare": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Igrasie, fisuri, instalaţii vechi, tâmplărie degradată, altele vizibile"
            ),
        },
        "cost_renovare_estimat_eur": {
            "type": "integer",
            "description": "0 dacă nu e nevoie de lucrări. Estimare grosieră, doar din fotografii.",
        },
        "incredere": {"type": "string", "enum": ["ridicata", "medie", "scazuta"]},
        "observatii": {
            "type": "string",
            "description": "2-5 propoziţii în română, ce contează pentru valoare. Fără markdown.",
        },
    },
    "required": [
        "stare_generala",
        "scor_stare",
        "finisaje",
        "semne_ingrijorare",
        "incredere",
        "observatii",
    ],
}

_FURNITURE_FINISHES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mobilier_pe_camere": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "camera": {
                        "type": "string",
                        "description": "Ex: Bucătărie, Living, Dormitor, Hol, Baie",
                    },
                    "elemente": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "piesa": {
                                    "type": "string",
                                    "description": "Denumirea piesei de mobilier",
                                },
                                "stare": {
                                    "type": "string",
                                    "description": "Ex: nou, foarte buna, uzura normala, degradat",
                                },
                                "stil": {
                                    "type": "string",
                                    "description": "Ex: modern, minimalist, clasic, rustic",
                                },
                                "calitate": {
                                    "type": "string",
                                    "description": "Ex: buget/PAL, mediu/MDF, premium/lemn masiv",
                                },
                            },
                            "required": ["piesa", "stare", "stil", "calitate"],
                        },
                    },
                },
                "required": ["camera", "elemente"],
            },
        },
        "electrocasnice": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "aparat": {
                        "type": "string",
                        "description": "Ex: Plită, Cuptor, Hotă, Frigider, Mașină spălat rufe, AC",
                    },
                    "camera": {"type": "string"},
                    "brand_vizibil": {
                        "type": "string",
                        "description": "Brandul dacă e lizibil, altfel 'nespecificat'",
                    },
                    "tip": {"type": "string", "description": "incorporat sau independent"},
                    "stare": {
                        "type": "string",
                        "description": "nou/recent, bun/functional, invechit/uzat",
                    },
                },
                "required": ["aparat", "camera", "tip", "stare"],
            },
        },
        "finisaje": {
            "type": "object",
            "properties": {
                "pardoseli": {
                    "type": "object",
                    "properties": {
                        "tip_dominant": {
                            "type": "string",
                            "description": "Parchet laminat, parchet lemn masiv, gresie etc.",
                        },
                        "stare": {"type": "string"},
                        "calitate": {
                            "type": "string",
                            "description": "economic, mediu, premium, lux",
                        },
                        "observatii": {"type": "string"},
                    },
                    "required": ["tip_dominant", "stare", "calitate", "observatii"],
                },
                "tamplarie_ferestre": {
                    "type": "object",
                    "properties": {
                        "material": {
                            "type": "string",
                            "description": "PVC, aluminiu, lemn stratificat, lemn clasic vechi",
                        },
                        "geam": {
                            "type": "string",
                            "description": "termopan, tripan, clasic",
                        },
                        "stare": {"type": "string"},
                    },
                    "required": ["material", "geam", "stare"],
                },
                "usi": {
                    "type": "object",
                    "properties": {
                        "usa_intrare": {
                            "type": "string",
                            "description": "Tip ușă intrare (ex: metalică antiefracție, lemn)",
                        },
                        "usi_interioare": {
                            "type": "string",
                            "description": "Tip uși interioare (ex: MDF pline, celulare, sticlă)",
                        },
                        "stare": {"type": "string"},
                    },
                    "required": ["usa_intrare", "usi_interioare", "stare"],
                },
                "baie_sanitare": {
                    "type": "object",
                    "properties": {
                        "tip_dus_cada": {
                            "type": "string",
                            "description": "Cadă, cabină duș, duș walk-in etc.",
                        },
                        "obiecte_sanitare": {
                            "type": "string",
                            "description": "Vas WC suspendat / clasic, lavoar etc.",
                        },
                        "baterii": {
                            "type": "string",
                            "description": "Modern/încastrat, cromat standard, uzat",
                        },
                        "placari_ceramice": {
                            "type": "string",
                            "description": "Gresie/faianță modernă rectificată, clasică, învechită",
                        },
                        "stare": {"type": "string"},
                    },
                    "required": [
                        "tip_dus_cada",
                        "obiecte_sanitare",
                        "baterii",
                        "placari_ceramice",
                        "stare",
                    ],
                },
                "climatizare_si_incalzire": {
                    "type": "object",
                    "properties": {
                        "sursa_incalzire": {
                            "type": "string",
                            "description": "Centrală proprie, termoficare cu calorifere etc.",
                        },
                        "aer_conditionat": {
                            "type": "string",
                            "description": "Aparate AC vizibile sau absență",
                        },
                        "stare": {"type": "string"},
                    },
                    "required": ["sursa_incalzire", "aer_conditionat", "stare"],
                },
            },
            "required": [
                "pardoseli",
                "tamplarie_ferestre",
                "usi",
                "baie_sanitare",
                "climatizare_si_incalzire",
            ],
        },
        "evaluare_globala": {
            "type": "object",
            "properties": {
                "nivel_calitate_global": {
                    "type": "string",
                    "description": "economic, mediu, premium, lux",
                },
                "scor_calitate_finisaje": {
                    "type": "integer",
                    "description": "Nota 1-10 pentru finisaje",
                },
                "scor_calitate_mobilier": {
                    "type": "integer",
                    "description": "Nota 1-10 pentru mobilier",
                },
                "stare_conservare": {
                    "type": "string",
                    "description": "nou/neutilizat, foarte buna, uzura normala, necesita renovare",
                },
                "plusvaloare_mobilier": {
                    "type": "string",
                    "description": "aduce plusvaloare, neutru/utilizabil, necesita debarasare",
                },
                "estimare_valoare_mobilier_eur": {
                    "type": "integer",
                    "description": "Valoare estimată aproximativă a dotărilor în EUR",
                },
                "buget_recomandat_renovare_eur": {
                    "type": "integer",
                    "description": "Buget estimat necesar pentru reparații/modernizare în EUR",
                },
                "puncte_forte": {"type": "array", "items": {"type": "string"}},
                "puncte_slabe": {"type": "array", "items": {"type": "string"}},
                "concluzie_analiza": {
                    "type": "string",
                    "description": "3-5 propoziții rezumat pentru cumpărător",
                },
            },
            "required": [
                "nivel_calitate_global",
                "scor_calitate_finisaje",
                "scor_calitate_mobilier",
                "stare_conservare",
                "plusvaloare_mobilier",
                "estimare_valoare_mobilier_eur",
                "buget_recomandat_renovare_eur",
                "puncte_forte",
                "puncte_slabe",
                "concluzie_analiza",
            ],
        },
    },
    "required": ["mobilier_pe_camere", "electrocasnice", "finisaje", "evaluare_globala"],
}

PROMPT = """\
Ești asistentul unui evaluator imobiliar din București. Analizezi fotografiile
unui apartament scos la vânzare, pentru un raport de evaluare întocmit conform
metodologiei ANEVAR (SEV 2025), fără inspecţie la faţa locului.

Fotografiile sunt, în ordine: imaginile din anunţ (alese de vânzător), apoi —
dacă există — o imagine Street View cu blocul şi strada, apoi o hartă a zonei.
Îţi spun explicit înainte de fiecare grup care este.

Ce contează pentru valoare, şi doar asta:
- starea reală a finisajelor, nu impresia de "amenajat frumos";
- vechimea vizibilă a instalaţiilor, tâmplăriei, băilor şi bucătăriei;
- semne de probleme: igrasie, fisuri, pete de infiltraţie, mucegai, pardoseli
  denivelate, instalaţii improvizate;
- lumina naturală şi compartimentarea, cât se pot deduce;
- din Street View: starea blocului, anveloparea, strada, parcarea.

Reguli:
- Raportează doar ce se vede. Dacă o cameră nu apare în poze, nu presupune
  nimic despre ea; scrie asta în observaţii.
- Fotografiile sunt selectate de vânzător: ce lipseşte lipseşte adesea
  intenţionat. O galerie fără baie sau fără bucătărie este ea însăşi un semnal
  şi merită trecută la `semne_ingrijorare`.
- Nu inventa suprafeţe, preţuri sau ani. Ai deja datele anunţului mai jos.
- `incredere` = "scazuta" dacă sunt sub 5 poze utile sau dacă sunt randări,
  nu fotografii.

Datele anunţului:
{facts}
"""


@dataclass
class VisualFindings:
    """What the model saw. Every field is advisory and carries its confidence."""

    stare_generala: str = "nedeterminat"
    scor_stare: int | None = None
    finisaje: str = ""
    lumina: str = ""
    compartimentare: str = ""
    fatada_bloc: str = ""
    semne_ingrijorare: list[str] = field(default_factory=list)
    cost_renovare_estimat_eur: int | None = None
    incredere: str = "scazuta"
    observatii: str = ""
    # Provenance, so the report can say what the verdict was actually based on.
    photos_seen: int = 0
    had_street_view: bool = False
    model: str = ""
    photo_urls: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """The report's visual section, as the model's own observations."""
        lines: list[str] = []
        add = lines.append

        grade = self.stare_generala
        score = f" (scor {self.scor_stare}/10)" if self.scor_stare is not None else ""
        add(f"**Stare generală apreciată vizual:** {grade}{score}")
        add("")

        rows = [
            ("Finisaje", self.finisaje),
            ("Lumină naturală", self.lumina),
            ("Compartimentare", self.compartimentare),
            ("Bloc și stradă (Street View)", self.fatada_bloc),
        ]
        present = [(label, value) for label, value in rows if value]
        if present:
            add("| Element | Observație |")
            add("|---|---|")
            for label, value in present:
                add(f"| {label} | {value} |")
            add("")

        if self.semne_ingrijorare:
            add("**Semne care merită verificate la inspecție:**")
            add("")
            for item in self.semne_ingrijorare:
                add(f"- {item}")
            add("")

        if self.cost_renovare_estimat_eur:
            cost = f"{self.cost_renovare_estimat_eur:,}".replace(",", ".")
            add(f"**Lucrări estimate din fotografii:** ~{cost} €")
            add("")

        if self.observatii:
            add(self.observatii)
            add("")

        if self.photo_urls:
            add("**Fotografii analizate din anunț:**")
            add("")
            add(" · ".join(f"[Foto {i+1}]({u})" for i, u in enumerate(self.photo_urls[:10])))
            add("")

        basis = f"{self.photos_seen} fotografii din anunț"
        if self.had_street_view:
            basis += " + imagine Street View"
        add(
            f"> Analiză vizuală automată ({self.model}), pe baza a {basis}. "
            f"Încredere declarată: {self.incredere}. Fotografiile sunt selectate de vânzător "
            "și nu înlocuiesc inspecția — nu arată instalațiile, structura sau viciile ascunse. "
            "Aceste observații nu au fost folosite pentru a ajusta valoarea estimată."
        )
        return "\n".join(lines)


def _download(urls: list[str], limit: int) -> list[tuple[bytes, str]]:
    """Fetch the gallery. One unreachable photo must not lose the set.

    Through `throttle`, which paces and memoises: the same photographs are
    wanted again by the contact sheet and by the PDF, and each used to fetch
    its own copy -- eight connections at a time, a fresh TLS handshake per
    photograph. That is what the portal's anti-bot page objected to. The pool
    here now only overlaps the waiting; `throttle` caps how many calls are
    actually in flight across the whole process.
    """
    wanted = urls[:limit]
    if not wanted:
        return []

    def one(url: str) -> tuple[bytes, str] | None:
        return throttle.fetch_image(url, HEADERS)

    with concurrent.futures.ThreadPoolExecutor(max_workers=throttle.MAX_PARALLEL) as pool:
        return [result for result in pool.map(one, wanted) if result is not None]


def _facts(subject: dict[str, Any]) -> str:
    """The listing's own numbers, so the model does not re-derive them from pixels."""
    interesting = (
        ("Titlu", subject.get("title")),
        ("Suprafață utilă", subject.get("surface_sqm")),
        ("Camere", subject.get("rooms")),
        ("Etaj", subject.get("floor")),
        ("An construcție", subject.get("year_built")),
        ("Zonă", subject.get("area")),
        ("Preț cerut (€)", subject.get("price_eur")),
    )
    return "\n".join(f"- {label}: {value}" for label, value in interesting if value is not None)


def analyse(
    subject: dict[str, Any],
    image_urls: list[str],
    street_view: bytes | None = None,
    static_map: bytes | None = None,
) -> VisualFindings | None:
    """Look at a property's photographs and report what bears on its value.

    Returns None when the pass is disabled, when there are no images to look
    at, or when the model call fails — in every one of those cases the report
    renders exactly as it did before, without a visual section.
    """
    settings = get_settings()
    if not settings.imobiliare_vision_enabled:
        return None

    photos = _download(image_urls or [], settings.imobiliare_max_photos)
    if not photos and street_view is None:
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai unavailable; skipping the visual analysis")
        return None

    parts: list[Any] = [types.Part(text=PROMPT.format(facts=_facts(subject)))]
    if photos:
        parts.append(types.Part(text=f"Fotografiile din anunț ({len(photos)}):"))
        parts.extend(
            types.Part(inline_data=types.Blob(data=data, mime_type=mime)) for data, mime in photos
        )
    if street_view is not None:
        parts.append(types.Part(text="Imagine Street View — blocul și strada:"))
        parts.append(types.Part(inline_data=types.Blob(data=street_view, mime_type="image/jpeg")))
    if static_map is not None:
        parts.append(types.Part(text="Harta zonei, proprietatea marcată cu roșu:"))
        parts.append(types.Part(inline_data=types.Blob(data=static_map, mime_type="image/png")))

    model = settings.imobiliare_vision_model
    try:
        client = _client(genai, settings)
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                # This is one stateless look at a set of images, not a task that
                # benefits from planning — and it sits on the critical path of a
                # tool call the user is waiting on.
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
    except Exception:
        logger.exception("Visual analysis failed on %s", model)
        return None

    findings = _parse(response, photos, street_view, model)
    if findings is not None:
        findings.photo_urls = [u for u in (image_urls or [])[:len(photos)]]
    return findings


def _client(genai: Any, settings: Any) -> Any:
    """A genai client configured the way the rest of the service is.

    `genai.Client()` with no arguments reads GOOGLE_GENAI_USE_VERTEXAI,
    GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION from the *process*
    environment. That is how ADK resolves the conversational model too, and it
    is correct on Cloud Run where those are real environment variables — but
    this service also reads them through `Settings`, which loads `.env` without
    exporting anything. A process configured only by `.env` would therefore
    build the agent fine and fail here alone, with "No API key was provided".

    So the project and location are passed explicitly when settings carry them,
    and the argument-free form is kept as the fallback for a deployment
    configured purely through the environment (including a Gemini API key
    rather than Vertex).
    """
    if settings.project:
        return genai.Client(
            vertexai=True, project=settings.project, location=settings.location or "global"
        )
    return genai.Client()


def _parse(
    response: Any, photos: list[tuple[bytes, str]], street_view: bytes | None, model: str
) -> VisualFindings | None:
    """Turn the structured response into findings. Malformed output is dropped,
    never partially trusted."""
    import json

    text = getattr(response, "text", None)
    if not text:
        logger.warning("Visual analysis returned no text")
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Visual analysis returned unparseable JSON: %s", text[:300])
        return None
    if not isinstance(data, dict):
        return None

    def as_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    signs = data.get("semne_ingrijorare")
    return VisualFindings(
        stare_generala=str(data.get("stare_generala") or "nedeterminat"),
        scor_stare=as_int(data.get("scor_stare")),
        finisaje=str(data.get("finisaje") or ""),
        lumina=str(data.get("lumina") or ""),
        compartimentare=str(data.get("compartimentare") or ""),
        fatada_bloc=str(data.get("fatada_bloc") or ""),
        semne_ingrijorare=[str(x) for x in signs] if isinstance(signs, list) else [],
        cost_renovare_estimat_eur=as_int(data.get("cost_renovare_estimat_eur")),
        incredere=str(data.get("incredere") or "scazuta"),
        observatii=str(data.get("observatii") or ""),
        photos_seen=len(photos),
        had_street_view=street_view is not None,
        model=model,
    )


def inspect(
    subject: dict[str, Any],
    query: str,
    image_urls: list[str] | None = None,
    limit: int = 15,
) -> dict[str, Any]:
    """Inspect property photographs with a custom question using Gemini 3.8 Flash."""
    settings = get_settings()
    urls = image_urls or subject.get("image_urls") or []
    if not urls:
        return {"error": "Anunțul nu are fotografii disponibile pentru analiză."}

    photos = _download(urls, limit)
    if not photos:
        return {"error": "Nu s-au putut descărca fotografiile anunțului."}

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {"error": "google-genai indisponibil; inspecția vizuală a fost omisă"}

    facts = _facts(subject)
    prompt_text = (
        "Ești asistentul unui evaluator imobiliar și analizezi fotografiile unui apartament.\n"
        f"Datele anunțului:\n{facts}\n\n"
        f"Întrebarea sau cerința utilizatorului:\n\"{query}\"\n\n"
        "Instrucțiuni:\n"
        "1. Răspunde direct, obiectiv și concis în limba română pe baza a ceea "
        "ce se vede în fotografii.\n"
        "2. Menționează starea finisajelor, a instalațiilor sau a camerelor "
        "relevante pentru întrebare.\n"
        "3. Dacă ceva nu apare în poze, menționează explicit această absență.\n"
        "4. Nu inventa detalii care nu sunt vizibile.\n"
    )

    parts: list[Any] = [
        types.Part(text=prompt_text),
        types.Part(text=f"Fotografiile din anunț ({len(photos)} imagini):"),
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
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
        answer = getattr(response, "text", "") or ""
    except Exception as e:
        logger.exception("Ad-hoc visual inspection failed on %s", model)
        return {"error": f"Eroare analiză vizuală: {e}"}

    return {
        "status": "success",
        "raspuns_vizual": answer.strip(),
        "fotografii_analizate": len(photos),
        "total_fotografii": len(urls),
        "model": model,
        "fotografii_reprezentative": urls[:6],
    }


def furniture_finishes_to_markdown(
    data: dict[str, Any], subject: dict[str, Any] | None = None
) -> str:
    """Format the structured furniture & finishes JSON into human-readable Markdown."""
    if not data or not isinstance(data, dict):
        return ""
    lines: list[str] = []
    add = lines.append

    title = (subject or {}).get("title") or "Proprietate"
    add(f"## 🛋️ Raport Mobilier & Finisaje: {title}")
    add("")

    eval_glob = data.get("evaluare_globala") or {}
    nivel = str(eval_glob.get("nivel_calitate_global", "nedeterminat")).capitalize()
    add(
        f"**Nivel global de calitate:** `{nivel}` | "
        f"**Scor finisaje:** `{eval_glob.get('scor_calitate_finisaje', '-')}/10` | "
        f"**Scor mobilier:** `{eval_glob.get('scor_calitate_mobilier', '-')}/10`"
    )
    add("")

    if eval_glob.get("concluzie_analiza"):
        add(f"> {eval_glob.get('concluzie_analiza')}")
        add("")

    # Financial estimates & condition
    add("### 📊 Estimări & Stare de Conservare")
    add(f"- **Stare conservare:** {eval_glob.get('stare_conservare', '-')}")
    add(f"- **Impact valoare mobilier:** {eval_glob.get('plusvaloare_mobilier', '-')}")
    val_mob = eval_glob.get("estimare_valoare_mobilier_eur")
    if val_mob is not None:
        add(f"- **Valoare estimată dotări incluse:** ~{val_mob:,} €".replace(",", "."))
    bug_ren = eval_glob.get("buget_recomandat_renovare_eur")
    if bug_ren is not None:
        add(f"- **Buget orientativ renovare/modernizare:** ~{bug_ren:,} €".replace(",", "."))
    add("")

    # Strengths & Weaknesses
    forte = eval_glob.get("puncte_forte") or []
    slabe = eval_glob.get("puncte_slabe") or []
    if forte or slabe:
        add("### ⚖️ Puncte Forte & Puncte Slabe (Vizual)")
        if forte:
            add("**Puncte forte:**")
            for pf in forte:
                add(f"- ✅ {pf}")
        if slabe:
            add("**Puncte slabe / Necesită atenție:**")
            for ps in slabe:
                add(f"- ⚠️ {ps}")
        add("")

    # Furniture by room
    camere = data.get("mobilier_pe_camere") or []
    if camere:
        add("### 🛏️ Inventar Mobilier pe Camere")
        for c in camere:
            nume_cam = c.get("camera", "Cameră")
            add(f"#### 📍 {nume_cam}")
            elemente = c.get("elemente") or []
            if not elemente:
                add("*Fără piese de mobilier identificate distinct în imagini.*")
            else:
                add("| Piesă | Calitate / Material | Stil | Stare de uzură |")
                add("|---|---|---|---|")
                for el in elemente:
                    piesa = el.get("piesa", "-")
                    calit = el.get("calitate", "-")
                    stil = el.get("stil", "-")
                    stare = el.get("stare", "-")
                    add(f"| {piesa} | {calit} | {stil} | {stare} |")
            add("")

    # Appliances
    electro = data.get("electrocasnice") or []
    if electro:
        add("### 🍳 Electrocasnice & Echipamente Identificate")
        add("| Aparat | Cameră | Brand | Tip montaj | Stare |")
        add("|---|---|---|---|---|")
        for e in electro:
            aparat = e.get("aparat", "-")
            cam = e.get("camera", "-")
            brand = e.get("brand_vizibil", "nespecificat")
            tip = e.get("tip", "-")
            stare = e.get("stare", "-")
            add(f"| {aparat} | {cam} | {brand} | {tip} | {stare} |")
        add("")

    # Finishes details
    fin = data.get("finisaje") or {}
    if fin:
        add("### 🪵 Catalog Finisaje & Instalații")
        pardo = fin.get("pardoseli") or {}
        if pardo:
            add(
                f"- **Pardoseli:** {pardo.get('tip_dominant', '-')} "
                f"(Calitate: {pardo.get('calitate', '-')}, Stare: {pardo.get('stare', '-')})"
            )
            if pardo.get("observatii"):
                add(f"  - *Detalii:* {pardo.get('observatii')}")
        tamp = fin.get("tamplarie_ferestre") or {}
        if tamp:
            add(
                f"- **Tâmplărie & Geamuri:** Profil {tamp.get('material', '-')} "
                f"cu geam {tamp.get('geam', '-')} (Stare: {tamp.get('stare', '-')})"
            )
        usi = fin.get("usi") or {}
        if usi:
            add(
                f"- **Uși:** Intrare `{usi.get('usa_intrare', '-')}` | "
                f"Interioare `{usi.get('usi_interioare', '-')}` (Stare: {usi.get('stare', '-')})"
            )
        baie = fin.get("baie_sanitare") or {}
        if baie:
            add(
                f"- **Baie & Sanitare:** {baie.get('tip_dus_cada', '-')}, "
                f"{baie.get('obiecte_sanitare', '-')}, baterii {baie.get('baterii', '-')}, "
                f"faianță {baie.get('placari_ceramice', '-')} (Stare: {baie.get('stare', '-')})"
            )
        clim = fin.get("climatizare_si_incalzire") or {}
        if clim:
            add(
                f"- **Încălzire & Climatizare:** {clim.get('sursa_incalzire', '-')} | "
                f"AC: {clim.get('aer_conditionat', '-')} (Stare: {clim.get('stare', '-')})"
            )
        add("")

    return "\n".join(lines)


def analyse_furniture_and_finishes(
    subject: dict[str, Any],
    image_urls: list[str] | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Inspect photographs and produce a structured inventory of furniture,
    appliances and finishes, with qualitative ratings and estimated budgets.
    """
    settings = get_settings()
    urls = image_urls or subject.get("image_urls") or []
    if not urls:
        return {"error": "Anunțul nu are fotografii disponibile pentru analiză."}

    photos = _download(urls, limit)
    if not photos:
        return {"error": "Nu s-au putut descărca fotografiile anunțului."}

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {"error": "google-genai indisponibil; inspecția vizuală a fost omisă"}

    facts = _facts(subject)
    prompt_text = (
        "Ești un expert evaluator imobiliar și designer de interior specializat pe "
        "piața din România.\n"
        "Examinezi cu atenție fotografiile acestui apartament pentru a întocmi un inventar "
        "complet și obiectiv al mobilierului, electrocasnicelor și finisajelor, precum "
        "și o evaluare a calității lor.\n\n"
        f"Datele tehnice ale proprietății:\n{facts}\n\n"
        "Instrucțiuni specifice de analiză:\n"
        "1. Identifică fiecare piesă de mobilier vizibilă, grupate pe camere "
        "(Bucătărie, Living, Dormitor, Baie, Hol).\n"
        "2. Identifică electrocasnicele și echipamentele vizibile "
        "(incorporate vs independente, brand dacă se vede, stare).\n"
        "3. Evaluează finisajele: pardoseli (parchet laminat/masiv, gresie), tâmplărie ferestre, "
        "uși interioare și intrare, obiecte sanitare baie, încălzire și climatizare.\n"
        "4. Notează calitatea finisajelor și a mobilierului pe o scală de la 1 la 10 și clasifică "
        "nivelul general (economic, mediu, premium, lux).\n"
        "5. Estimează dacă mobilierul aduce plusvaloare sau necesită debarasare, și estimează un "
        "buget orientativ de renovare/înlocuiri dacă este cazul.\n"
        "6. Bazează-te STRICT pe ceea ce este vizibil în imagini. Nu inventa elemente invizibile.\n"
    )

    parts: list[Any] = [
        types.Part(text=prompt_text),
        types.Part(text=f"Fotografiile anunțului ({len(photos)} imagini):"),
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
                response_schema=_FURNITURE_FINISHES_SCHEMA,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
        text = getattr(response, "text", "") or ""
        data = json.loads(text) if text else {}
    except Exception as e:
        logger.exception("Furniture and finishes analysis failed on %s", model)
        return {"error": f"Eroare analiză mobilier și finisaje: {e}"}

    markdown_report = furniture_finishes_to_markdown(data, subject)

    return {
        "status": "success",
        "fotografii_analizate": len(photos),
        "total_fotografii": len(urls),
        "model": model,
        "inventar": data,
        "rezumat_markdown": markdown_report,
        "fotografii_reprezentative": urls[:6],
    }


