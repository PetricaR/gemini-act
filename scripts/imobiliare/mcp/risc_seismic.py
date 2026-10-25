"""Bucharest's seismic-risk register (AMCCRS), looked up by street address.

For a flat in Bucharest this is the single largest non-obvious fact about the
building. A block in class **RsI** -- the *bulina rosie* -- is worth
substantially less than the same flat next door, most banks will not lend
against it, and the owner carries a legal obligation to consolidate. None of
that is visible in a listing: sellers do not volunteer it, and the portal has
no field for it. So it has to be looked up, by address, against the register
the city keeps.

Source: <https://amccrs-pmb.ro/lista-imobile-2/>, the public list published by
the Administratia Municipala pentru Consolidarea Cladirilor cu Risc Seismic.
2.796 buildings as of the 19.05.2026 revision.

Three things about that page cost time if you rediscover them by hand:

* **The table is not in the HTML.** It is a Ninja Tables widget that fetches
  its rows from `admin-ajax.php` after load, so fetching the page and parsing
  `<table>` finds an empty `<colgroup>` and nothing else. `_data_request_url`
  scrapes the widget's own config out of the inline script instead, which also
  means a change of table id upstream is followed rather than hard-coded (the
  id is only a fallback). The nonce in that URL is *not* enforced for the
  public read -- it is passed along as the page sends it, not worked around.
* **The columns are free text typed by hand over many years.** The risk class
  arrives as `1.Clasa de risc seismic RsI.`, `2.Clasa de Risc Seismic RSII.`,
  `1.RSI.` and a dozen other spellings; one row has an expert's name in the
  class column. `_clasa` normalises all of it to a single token and reports
  `NECUNOSCUT` rather than guessing. The urgency category (U1/U2/U3) lives in
  `observatii`, not in the class column, even though for 1.597 buildings it is
  the only classification there is.
* **House numbers are ranges and histories**: `19÷21 (corp A+B)`,
  `43 (fost 1)`, `3 (3-5)`, `5A`. A building is matched on the *set* of
  numbers it can legitimately be called by, former numbering included -- old
  Bucharest streets were renumbered, and a listing quotes today's number while
  the register may still carry yesterday's.

**Absence from the register is not a clean bill of health.** It lists
buildings that have *been through a technical expertise*; an un-expertised
1930s block is missing from it for the worse reason, not the better one. Every
result says so, because the agent would otherwise report "not on the list" as
if it meant "safe".
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from typing import Any

import httpx

from . import paths

logger = logging.getLogger(__name__)

PAGE_URL = "https://amccrs-pmb.ro/lista-imobile-2/"
SURSA_NUME = "AMCCRS — Administrația Municipală pentru Consolidarea Clădirilor cu Risc Seismic"
AJAX_URL = "https://amccrs-pmb.ro/wp-admin/admin-ajax.php"
# Only a fallback: the live id is read from the page (see `_data_request_url`).
TABLE_ID = "2383"

# The register is republished a few times a year, so a week-old copy is still
# the current one. This TTL is also what keeps the request volume at roughly
# one page view per week against a small public-sector site.
CACHE_TTL = 7 * 24 * 3600
TIMEOUT = 45.0

HEADERS = {
    "Accept": "application/json, text/html;q=0.9",
    "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.8",
    "Referer": PAGE_URL,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}


# --- risk classes ---------------------------------------------------------

# `discount_pct` is an indicative market range, not a valuation: what buyers in
# Bucharest have been observed to demand off an otherwise comparable flat. It
# is deliberately a range, and `evaluare` treats it as one input among several
# rather than as an adjustment to apply blindly.
CLASE: dict[str, dict[str, Any]] = {
    "RsI": {
        "eticheta": "Clasa I de risc seismic (bulină roșie)",
        "severitate": 5,
        "discount_pct": (25, 45),
        "explicatie": (
            "Construcție cu risc ridicat de prăbușire la un cutremur de intensitatea celui "
            "avut în vedere prin proiectare. Este cea mai gravă încadrare."
        ),
        "consecinte": [
            "Majoritatea băncilor refuză creditul ipotecar — cumpărătorii rămași plătesc cash, "
            "ceea ce restrânge drastic piața și prețul obtenabil.",
            "Proprietarii au obligația legală de a permite expertizarea și de a participa la "
            "consolidare; clădirea trebuie să poarte panoul „bulină roșie”.",
            "Asigurarea facultativă este dificil sau scump de obținut (polița obligatorie PAD "
            "rămâne disponibilă).",
            "Spațiile comerciale de la parter nu pot funcționa liber — restricții de exploatare.",
            "Vânzătorul are obligația de a declara încadrarea la vânzare.",
        ],
    },
    "RsII": {
        "eticheta": "Clasa II de risc seismic",
        "severitate": 4,
        "discount_pct": (10, 20),
        "explicatie": (
            "Construcție care sub efectul cutremurului de proiectare poate suferi degradări "
            "structurale majore, dar la care pierderea stabilității nu este probabilă."
        ),
        "consecinte": [
            "O parte dintre bănci refuză sau limitează finanțarea; celelalte cer expertiză.",
            "Consolidarea rămâne recomandată, cu cost suportat în general de proprietari.",
            "Lichiditate redusă la revânzare: bazinul de cumpărători e mai mic.",
        ],
    },
    "RsIII": {
        "eticheta": "Clasa III de risc seismic",
        "severitate": 2,
        "discount_pct": (3, 10),
        "explicatie": (
            "Degradări structurale care nu afectează semnificativ siguranța structurală, dar "
            "la care degradările nestructurale pot fi importante."
        ),
        "consecinte": [
            "De regulă finanțabilă bancar.",
            "Impact moderat asupra prețului, folosit ca argument de negociere.",
        ],
    },
    "RsIV": {
        "eticheta": "Clasa IV de risc seismic",
        "severitate": 1,
        "discount_pct": (0, 3),
        "explicatie": (
            "Construcție la care răspunsul seismic așteptat este similar celui obținut la "
            "construcțiile proiectate pe baza normelor în vigoare."
        ),
        "consecinte": ["Fără impact material asupra valorii sau a finanțării."],
    },
    "URGENTA": {
        "eticheta": "Încadrată în categorie de urgență (fără clasă de risc)",
        "severitate": 3,
        "discount_pct": (5, 20),
        "explicatie": (
            "Clădire evaluată înainte de generalizarea claselor Rs, încadrată în categorii de "
            "urgență U1–U3. U1 este cea mai urgentă. Nu este echivalentă formal cu o clasă de "
            "risc, dar băncile și cumpărătorii o tratează ca semnal de risc."
        ),
        "consecinte": [
            "Expertiza este veche — o reexpertizare poate muta clădirea într-o clasă Rs.",
            "U1 se apropie practic de RsI ca efect asupra finanțării și a prețului.",
            "Merită cerută copia expertizei tehnice de la AMCCRS înainte de ofertă.",
        ],
    },
    "CONSOLIDAT": {
        "eticheta": "Consolidată",
        "severitate": 0,
        "discount_pct": (0, 0),
        "explicatie": (
            "Lucrările de consolidare au fost executate. Clădirea a figurat cu risc seismic, "
            "dar a fost pusă în siguranță."
        ),
        "consecinte": [
            "Fără penalizare de valoare pentru risc seismic; poate fi chiar un argument "
            "pozitiv față de vecinii neconsolidați.",
            "Cere procesul-verbal de recepție a lucrărilor de consolidare.",
            "Verifică dacă mai există rate de rambursat către stat pentru consolidare — "
            "obligația trece asupra cumpărătorului.",
        ],
    },
    "NEINCADRAT": {
        "eticheta": "Expertizată, neîncadrată",
        "severitate": 1,
        "discount_pct": (0, 5),
        "explicatie": (
            "Clădirea figurează în evidențele AMCCRS dar nu a primit o clasă de risc sau o "
            "categorie de urgență."
        ),
        "consecinte": ["Cere expertiza tehnică pentru a ști ce s-a constatat efectiv."],
    },
    "NECUNOSCUT": {
        "eticheta": "Încadrare neinteligibilă în registru",
        "severitate": 2,
        "discount_pct": (0, 0),
        "explicatie": (
            "Rândul există în registru, dar coloana de încadrare conține altceva decât o clasă "
            "(eroare de tastare în sursă). Verifică direct la AMCCRS."
        ),
        "consecinte": ["Cere copia expertizei tehnice de la AMCCRS."],
    },
}

# U1 is materially worse than U3 and the register keeps them only in a free
# text field, so they are surfaced separately rather than folded into URGENTA.
URGENTA_DETALII = {
    "U1": ("Urgența 1 — cea mai ridicată", 5),
    "U2": ("Urgența 2 — ridicată", 3),
    "U3": ("Urgența 3 — moderată", 2),
}


# --- text normalisation ---------------------------------------------------

# The register is served as UTF-8 but parts of it were pasted from a CP1252
# document, so a few rows carry raw 0x84/0x94 where typographic quotes were.
_MOJIBAKE = {"\x84": "„", "\x93": "“", "\x94": "”", "\x96": "–", "\x92": "’"}

_TIP_ARTERA = re.compile(
    r"^(?:STRADA|STR|BULEVARDUL|B DUL|BDUL|BD|CALEA|SOSEAUA|SOS|ALEEA|INTRAREA|INTR"
    r"|SPLAIUL|SPLAIU|PIATA|PTA|DRUMUL|PRELUNGIREA)\b\s*"
)
# Everything after these words is block/staircase/sector bookkeeping, not part
# of the street name -- ~90 rows carry it inside the address column itself.
_COADA = re.compile(r"\s+(?:NR|NUMARUL|BL|BLOC|SC|SCARA|AP|SECTOR|COLT CU|FOST|FOSTA|CORP)\b.*$")
# City/sector tokens in a listing address. Removed -- wherever they sit, not
# only at the end -- before the house number is read off the end.
_COADA_ADMINISTRATIVA = re.compile(
    r"[\s,;-]*\b(?:SECTOR(?:UL)?\s*[1-6]|BUCURESTI|BUCURESTI|ROMANIA|MUN\.?)\b\.?"
)
_NUMAR = re.compile(r"(\d+)\s*([A-Z]{1,3})?(?:\s*[÷–—/-]\s*(\d+)\s*([A-Z]{1,3})?)?")
_RS = re.compile(r"\bR\s*S\s*(IV|III|II|I)\b")
_URG = re.compile(r"\bU\s*([123])\b")
_NEINCADRAT = re.compile(r"\s*NEINCADRAT")
_ROMAN = {"I": "RsI", "II": "RsII", "III": "RsIII", "IV": "RsIV"}


def _curata(text: str) -> str:
    for bad, good in _MOJIBAKE.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


def _fold(text: str) -> str:
    """Uppercase, diacritic-free form used for every comparison.

    Romanian s/t-comma (U+0219) and s/t-cedilla (U+015F) are both in the data
    for the same streets; NFKD reduces both to the bare letter.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).upper()


def cheie_strada(adresa: str) -> str:
    """Street name reduced to what two spellings of it have in common."""
    text = _fold(_curata(adresa))
    text = re.sub(r"\([^)]*\)", " ", text)  # landmark aliases: "(Cinematograful PATRIA)"
    text = re.sub(r"[^A-Z0-9]+", " ", text).strip()
    # Before the artery type, so that "Sector 1, Strada Academiei 15" reduces
    # the same way as "Strada Academiei 15, Sector 1".
    text = _COADA_ADMINISTRATIVA.sub(" ", text).strip()
    text = _TIP_ARTERA.sub("", text).strip()
    text = _COADA.sub("", text).strip()
    text = re.sub(r"\s+\d+[A-Z]?$", "", text)  # trailing house number
    return re.sub(r"\s+", " ", text).strip()


def _adauga_numere(out: set[str], text: str, interval: bool = True) -> None:
    for m in _NUMAR.finditer(_fold(text)):
        de_la, sufix, pana_la, _ = m.groups()
        if pana_la and interval and 0 < int(pana_la) - int(de_la) < 40:
            out.update(str(i) for i in range(int(de_la), int(pana_la) + 1))
            continue
        out.add(de_la)
        if sufix and sufix != "BIS":
            out.add(de_la + sufix)
        if pana_la:
            out.add(pana_la)


def numere(numar: str, adresa: str = "") -> set[str]:
    """Every house number this row can legitimately be addressed by.

    Parentheses in the register carry two different things -- an alternative
    number (`43 (fost 1)`, `17 (15)`) or a description of the building
    (`14 (3 corpuri principale)`). Only the first kind is a number, so a
    parenthetical that mentions a corp/scara/bloc is skipped rather than
    mined for digits that mean something else.
    """
    gasite: set[str] = set()
    text = _fold(_curata(numar))
    _adauga_numere(gasite, text.split("(")[0])
    for paranteza in re.findall(r"\(([^)]*)\)", text):
        continut = paranteza.strip()
        if not re.search(r"\d", continut):
            continue
        if re.search(r"\b(CORP|CORPURI|SC|SCARA|BLOC|BL)\b", continut):
            continue
        if re.fullmatch(r"(?:FOST[AĂ]?\s+)?[\d\s÷–—/A-Z-]{1,12}", continut):
            _adauga_numere(gasite, continut)
    # Rows where the number was typed into the address column instead.
    if m := re.search(
        r"\bNR\.?\s*(\d+\s*[A-Z]?(?:\s*[÷–—/-]\s*\d+\s*[A-Z]?)?)(?![A-Z])", _fold(adresa)
    ):
        _adauga_numere(gasite, m.group(1))
    return {n for n in gasite if n and n[0].isdigit()}


def _numere_interogare(numar: str | None, adresa: str) -> set[str]:
    """The number the caller is asking about, from either argument.

    Callers pass a listing's address, which usually already ends in the number
    ("Strada Academiei 15"), so requiring a separate `numar` would make the
    tool fail on its most common input. The sector and city have to come off
    the end first, though: "Strada Academiei 15, Sector 1" ends in a digit that
    is not a house number, and reading it as one searches for the wrong
    building and answers confidently about it.
    """
    if numar and (explicit := numere(numar)):
        return explicit
    text = re.sub(r"[,;]", " ", _fold(adresa)).strip()
    gasite: set[str] = set()
    if explicit_nr := re.search(r"\bNR\.?\s*(\d+\s*[A-Z]?)(?![A-Z])", text):
        _adauga_numere(gasite, explicit_nr.group(1), interval=False)
        return gasite
    text = _COADA_ADMINISTRATIVA.sub("", text).strip()
    if coada := re.search(r"(\d+\s*[A-Z]?)\s*$", text):
        _adauga_numere(gasite, coada.group(1), interval=False)
    return gasite


def _sector_din_text(text: str) -> str | None:
    """A sector only when it is actually named as one, never a bare digit."""
    if m := re.search(r"\bSECTOR(?:UL)?\s*([1-6])\b", _fold(text)):
        return f"Sector {m.group(1)}"
    return None


def _clasa(incadrare: str, observatii: str) -> tuple[str, str | None]:
    """Normalise a hand-typed classification to (clasa, categorie_urgenta)."""
    text = _fold(incadrare).replace(".", " ")
    if m := _RS.search(text):
        return _ROMAN[m.group(1)], None
    if "CONSOLIDAT" in text:
        return "CONSOLIDAT", None
    # Order matters and is not obvious. The 1.453-row majority reads "INCADRARE
    # IN CATEGORIE DE URGENTA; NEINCADRATE IN CLASE DE RISC SEISMIC" -- it
    # contains *both* words. A further 143 rows read "NEINCADRAT IN CATEGORIA DE
    # URGENTA SAU CLASE de RISC SEISMIC", which is the opposite statement. Only
    # the leading word separates them, so match on that rather than on
    # containment, which would report 143 unclassified buildings as urgent.
    if _NEINCADRAT.match(text):
        return "NEINCADRAT", None
    urgenta = _URG.search(_fold(observatii)) or _URG.search(text)
    if "URGENT" in text:
        return "URGENTA", (f"U{urgenta.group(1)}" if urgenta else None)
    if "NEINCADRAT" in text:
        return "NEINCADRAT", None
    return "NECUNOSCUT", None


def _sector(text: str) -> str | None:
    if m := re.search(r"([1-6])", _fold(text)):
        return f"Sector {m.group(1)}"
    return None


def _int(text: str) -> int | None:
    m = re.search(r"\d{1,4}", text or "")
    return int(m.group(0)) if m else None


# --- fetching -------------------------------------------------------------


class RegistruIndisponibil(RuntimeError):
    """The register could not be fetched and no cached copy exists."""


def _cache_file():
    directory = paths.ensure_dir(paths.cache_dir("risc-seismic"))
    return None if directory is None else directory / f"amccrs-{TABLE_ID}.json"


def _data_request_url(client: httpx.Client) -> str:
    """The AJAX URL the page's own table widget uses.

    Read from the page rather than hard-coded so that a new table id upstream
    is followed automatically -- the list has been republished under a new id
    before. The constructed fallback keeps the tool working if the page markup
    changes shape.
    """
    fallback = (
        f"{AJAX_URL}?action=wp_ajax_ninja_tables_public_action&table_id={TABLE_ID}"
        "&target_action=get-all-data&default_sorting=old_first&skip_rows=0&limit_rows=0"
    )
    try:
        page = client.get(PAGE_URL)
        page.raise_for_status()
        if m := re.search(r'"data_request_url"\s*:\s*"([^"]+)"', page.text):
            return m.group(1).replace("\\/", "/").replace("&#038;", "&")
        logger.warning("AMCCRS: nu am găsit data_request_url în pagină, folosesc fallback")
    except httpx.HTTPError as exc:
        logger.warning("AMCCRS: pagina nu a putut fi citită (%s), folosesc fallback", exc)
    return fallback


def _descarca() -> list[dict[str, Any]]:
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        response = client.get(_data_request_url(client))
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        raise RegistruIndisponibil("Registrul AMCCRS a răspuns într-un format neașteptat.")
    randuri = [
        r.get("value") for r in payload if isinstance(r, dict) and isinstance(r.get("value"), dict)
    ]
    if not randuri:
        raise RegistruIndisponibil("Registrul AMCCRS a răspuns fără rânduri.")
    return randuri


def _randuri_brute() -> tuple[list[dict[str, Any]], bool]:
    """The register's rows, from disk when fresh. Returns (rows, from_cache)."""
    path = _cache_file()
    if path is not None and path.exists():
        varsta = time.time() - path.stat().st_mtime
        if varsta < CACHE_TTL:
            try:
                return json.loads(path.read_text(encoding="utf-8")), True
            except (OSError, ValueError):
                pass
    try:
        randuri = _descarca()
    except (httpx.HTTPError, ValueError, RegistruIndisponibil) as exc:
        # A stale copy of a register that changes a few times a year beats no
        # answer at all -- but only as a fallback, never as the normal path.
        if path is not None and path.exists():
            try:
                logger.warning("AMCCRS indisponibil (%s) — folosesc copia locală expirată", exc)
                return json.loads(path.read_text(encoding="utf-8")), True
            except (OSError, ValueError):
                pass
        raise RegistruIndisponibil(
            f"Lista AMCCRS nu a putut fi descărcată de la {PAGE_URL}: {exc}"
        ) from exc
    if path is not None:
        try:
            path.write_text(json.dumps(randuri, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return randuri, False


def _normalizeaza(brut: dict[str, Any]) -> dict[str, Any]:
    adresa = _curata(str(brut.get("adresa") or ""))
    numar = _curata(str(brut.get("nr") or ""))
    observatii = _curata(str(brut.get("observatii") or ""))
    incadrare = _curata(str(brut.get("ultimaincadrareinclasaderisc") or ""))
    clasa, urgenta = _clasa(incadrare, observatii)
    return {
        "adresa": adresa,
        "numar": numar,
        "sector": _sector(str(brut.get("sector") or "")),
        "an_constructie": _int(str(brut.get("anulconstruirii") or "")),
        "regim_inaltime": _curata(str(brut.get("regimuldeinaltime") or "")) or None,
        "numar_apartamente": _int(str(brut.get("numardeapartamente") or "")),
        "an_expertiza": _int(str(brut.get("anulelaborariiexpertizeitehnice") or "")),
        "expert_tehnic": _curata(
            str(
                brut.get(
                    "expertultehnicatestatpentrucerintaesentialadecalitaterezistentamecanicasistabilitatemdrap"
                )
                or ""
            )
        )
        or None,
        "clasa_risc": clasa,
        "categorie_urgenta": urgenta,
        "incadrare_bruta": incadrare or None,
        "incadrari_anterioare": _curata(str(brut.get("incadrarianterioareinclasaderisc") or ""))
        or None,
        "observatii": observatii or None,
        "_cheie": cheie_strada(adresa),
        "_numere": numere(numar, adresa),
    }


_index: list[dict[str, Any]] | None = None
_index_moment = 0.0
# Tools run in worker threads (`agent/tools/imobiliare.py` hops off the event
# loop), so a cold start with several lookups in flight would otherwise
# download the same 1,6 MB register once per thread.
_index_lock = threading.Lock()


def index(reincarca: bool = False) -> list[dict[str, Any]]:
    """The whole register, normalised. Built once per process."""
    global _index, _index_moment
    with _index_lock:
        if _index is None or reincarca or time.time() - _index_moment > CACHE_TTL:
            randuri, _ = _randuri_brute()
            _index = [_normalizeaza(r) for r in randuri]
            _index_moment = time.time()
            logger.info("AMCCRS: %d imobile în registru", len(_index))
        return _index


# --- search ---------------------------------------------------------------


def _scor(rand: dict[str, Any], cheie: str, nums: set[str], sector: str | None) -> int | None:
    """How well one register row answers the query, or None for no match."""
    cheie_rand = rand["_cheie"]
    if not cheie or not cheie_rand:
        return None
    cuvinte_q, cuvinte_r = set(cheie.split()), set(cheie_rand.split())
    if cheie_rand == cheie:
        scor = 100
    elif cheie_rand.startswith(cheie) or cheie.startswith(cheie_rand):
        scor = 80
    elif cuvinte_q <= cuvinte_r or cuvinte_r <= cuvinte_q:
        # "Magheru" against "Gheorghe Magheru": listings drop the first name.
        scor = 65
    else:
        return None
    if nums:
        # A number that does not match is evidence *against* this row, not a
        # neutral absence -- otherwise every building on the street ranks equal
        # and the agent reports the neighbour's bulina rosie as this flat's.
        scor += 40 if nums & rand["_numere"] else -25
    if sector and rand.get("sector") == sector:
        scor += 10
    return scor


def _incredere(scor: int, nums: set[str], rand: dict[str, Any]) -> str:
    if scor >= 140 and nums & rand["_numere"]:
        return "ridicata"
    if nums and nums & rand["_numere"]:
        return "medie"
    if not nums:
        return "doar_strada"
    return "scazuta"


def _rezumat(rand: dict[str, Any]) -> dict[str, Any]:
    clasa = CLASE.get(rand["clasa_risc"], CLASE["NECUNOSCUT"])
    eticheta = clasa["eticheta"]
    severitate = clasa["severitate"]
    if urgenta := rand.get("categorie_urgenta"):
        text_urgenta, severitate_urgenta = URGENTA_DETALII.get(urgenta, (urgenta, severitate))
        eticheta = f"{eticheta} — {text_urgenta}"
        severitate = max(severitate, severitate_urgenta)
    return {
        "clasa_risc": rand["clasa_risc"],
        "categorie_urgenta": rand.get("categorie_urgenta"),
        "eticheta": eticheta,
        "severitate": severitate,
        "discount_orientativ_pct": list(clasa["discount_pct"]),
        "explicatie": clasa["explicatie"],
        "consecinte": clasa["consecinte"],
    }


AVERTISMENT_ABSENT = (
    "Absența din listă NU înseamnă că imobilul e sigur: registrul AMCCRS cuprinde doar "
    "clădirile care au trecut printr-o expertiză tehnică. O clădire veche neexpertizată "
    "lipsește din listă din motivul mai prost, nu din cel mai bun. Verifică anul construcției "
    "și cere vânzătorului expertiza tehnică sau depune la AMCCRS o cerere de încadrare."
)

AVERTISMENT_POTRIVIRE = (
    "Potrivirea e făcută pe text de adresă, nu pe număr cadastral. Confirmă numărul poștal și "
    "sectorul înainte de a trage concluzii — pe aceeași stradă pot exista imobile în clase "
    "diferite."
)


def cauta(
    adresa: str,
    numar: str | None = None,
    sector: str | None = None,
    limita: int = 5,
) -> dict[str, Any]:
    """Look one address up in the AMCCRS seismic-risk register.

    `adresa` may be a full listing address ("Strada Academiei 15, Sector 1");
    `numar` and `sector` only narrow it further when they are known separately.
    """
    interogare = (adresa or "").strip()
    if not interogare:
        return {"status": "error", "error_message": "Adresa este obligatorie."}

    try:
        randuri = index()
    except RegistruIndisponibil as exc:
        return {"status": "error", "error_message": str(exc)}

    cheie = cheie_strada(interogare)
    if not cheie or not any(c.isalpha() for c in cheie):
        return {
            "status": "error",
            "error_message": (
                f"Nu am putut extrage un nume de stradă din „{interogare}”. "
                "Dă adresa în forma „Strada Academiei 15”."
            ),
        }
    nums = _numere_interogare(numar, interogare)
    sector_normalizat = _sector(sector) if sector else _sector_din_text(interogare)

    potriviri = []
    for rand in randuri:
        if (scor := _scor(rand, cheie, nums, sector_normalizat)) is None:
            continue
        potriviri.append((scor, rand))
    potriviri.sort(key=lambda p: (-p[0], p[1]["adresa"], p[1]["numar"]))

    rezultate = []
    for scor, rand in potriviri[: max(1, limita)]:
        rezultate.append(
            {
                "adresa": rand["adresa"],
                "numar": rand["numar"],
                "sector": rand["sector"],
                "an_constructie": rand["an_constructie"],
                "regim_inaltime": rand["regim_inaltime"],
                "numar_apartamente": rand["numar_apartamente"],
                "an_expertiza": rand["an_expertiza"],
                "expert_tehnic": rand["expert_tehnic"],
                "incadrari_anterioare": rand["incadrari_anterioare"],
                "observatii": rand["observatii"],
                "incadrare_bruta": rand["incadrare_bruta"],
                "scor_potrivire": scor,
                "incredere": _incredere(scor, nums, rand),
                **_rezumat(rand),
            }
        )

    raspuns: dict[str, Any] = {
        "status": "success",
        "interogare": {
            "adresa": interogare,
            "strada_normalizata": cheie,
            "numere_cautate": sorted(nums),
            "sector": sector_normalizat,
        },
        "sursa": {
            "nume": SURSA_NUME,
            "url": PAGE_URL,
            "imobile_in_registru": len(randuri),
        },
        "gasit": bool(rezultate),
        "numar_potriviri": len(potriviri),
        "potriviri": rezultate,
        "avertisment": AVERTISMENT_POTRIVIRE if rezultate else AVERTISMENT_ABSENT,
        "cadru_legal": (
            "O.G. 20/1994 privind reducerea riscului seismic al construcțiilor existente și "
            "Legea 212/2022 privind unele măsuri pentru reducerea riscului seismic al clădirilor."
        ),
    }

    if rezultate:
        prima = rezultate[0]
        raspuns["concluzie"] = _concluzie(prima, nums)
        raspuns["severitate_maxima"] = max(r["severitate"] for r in rezultate)
    else:
        raspuns["concluzie"] = (
            f"„{interogare}” nu apare în registrul AMCCRS al clădirilor expertizate. "
            + AVERTISMENT_ABSENT
        )
        raspuns["severitate_maxima"] = 0
    return raspuns


def _concluzie(potrivire: dict[str, Any], nums: set[str]) -> str:
    de_la, pana_la = potrivire["discount_orientativ_pct"]
    adresa = f"{potrivire['adresa']} nr. {potrivire['numar']}".strip()
    cap = {
        "ridicata": "Potrivire sigură",
        "medie": "Potrivire probabilă",
        "doar_strada": "Potrivire doar pe stradă (nu a fost dat un număr)",
        "scazuta": "Potrivire nesigură — numărul nu coincide",
    }[potrivire["incredere"]]
    text = f"{cap}: {adresa} — {potrivire['eticheta']}."
    if de_la or pana_la:
        text += f" Impact orientativ asupra prețului: -{de_la}…-{pana_la}%."
    if potrivire["incredere"] in ("doar_strada", "scazuta"):
        text += " Confirmă numărul poștal exact înainte de a folosi asta în negociere."
    if not nums:
        text += " Dă și numărul imobilului pentru un răspuns precis."
    return text


# --- one finding, shaped for a report ------------------------------------

# Only these two are this building's class rather than the street's. A
# street-level match is still worth reporting -- as an outstanding check, not
# as a classification, because the neighbour's bulina rosie is not this flat's.
INCREDERE_CONCLUDENTA = ("ridicata", "medie")


def _pare_adresa_de_strada(adresa: str, numar: str | None = None) -> bool:
    """Is this an address at all, rather than a neighbourhood name?

    Either it names a kind of thoroughfare, or it carries a house number. A
    bare "Titan" is neither.
    """
    text = re.sub(r"[^A-Z0-9]+", " ", _fold(_curata(adresa))).strip()
    if _TIP_ARTERA.match(text) or re.search(
        r"\b(?:STRADA|STR|BULEVARDUL|BDUL|BD|CALEA|SOSEAUA"
        r"|SOS|ALEEA|INTRAREA|SPLAIUL|PIATA|DRUMUL)\b",
        text,
    ):
        return True
    return bool(numere(numar or "") or _numere_interogare(None, adresa))


def constatare(
    adresa: str | None,
    numar: str | None = None,
    sector: str | None = None,
) -> dict[str, Any] | None:
    """The register's answer about one building, shaped for a valuation report.

    Returns `None` when the question could not be *asked* -- no address, or the
    register was unreachable. A report has to tell that apart from "asked, and
    the building does not appear", which is a finding in its own right: the two
    lead to different sentences and only one of them is an outstanding task.
    """
    if not (adresa or "").strip():
        return None
    # A listing's address line is often a neighbourhood label -- "Zona
    # Universitate, Bucuresti", "Titan" -- not an address. Running one of those
    # through the register returns "not in the register", which a report would
    # print as a verified finding about a building nobody named. That is the
    # same reassuring-but-empty sentence this module exists to avoid, so the
    # question is declared unaskable instead.
    if not _pare_adresa_de_strada(adresa, numar):
        return None

    raspuns = cauta(adresa, numar=numar, sector=sector, limita=3)
    if raspuns.get("status") != "success":
        return None

    de_baza: dict[str, Any] = {
        "verificat": True,
        "adresa_interogata": adresa,
        "sursa_url": PAGE_URL,
        "sursa_nume": SURSA_NUME,
        "imobile_in_registru": raspuns["sursa"]["imobile_in_registru"],
        "avertisment": raspuns["avertisment"],
    }

    if not raspuns["gasit"]:
        return {
            **de_baza,
            "gasit": False,
            "concludent": False,
            "clasa_risc": None,
            "categorie_urgenta": None,
            "eticheta": None,
            "severitate": 0,
            "incredere": None,
            "adresa_registru": None,
            "an_expertiza": None,
            "expert_tehnic": None,
            "discount_orientativ_pct": None,
            "rezumat": (
                "Nu figurează în registrul AMCCRS al clădirilor expertizate. Absența nu "
                "atestă siguranța: registrul cuprinde doar clădirile expertizate tehnic."
            ),
        }

    prima = raspuns["potriviri"][0]
    concludent = prima["incredere"] in INCREDERE_CONCLUDENTA
    adresa_registru = f"{prima['adresa']} nr. {prima['numar']}".strip()
    if concludent:
        rezumat = f"{prima['eticheta']} — {adresa_registru}"
        if prima["an_expertiza"]:
            rezumat += f", expertiză {prima['an_expertiza']}"
    else:
        rezumat = (
            f"Neconcludent: pe {prima['adresa']} registrul are clădiri încadrate "
            f"({prima['eticheta']}), dar potrivirea nu este la nivel de imobil. "
            "Se reia verificarea cu numărul poștal exact."
        )
    return {
        **de_baza,
        "gasit": True,
        "concludent": concludent,
        "clasa_risc": prima["clasa_risc"] if concludent else None,
        "categorie_urgenta": prima["categorie_urgenta"] if concludent else None,
        "eticheta": prima["eticheta"] if concludent else None,
        "severitate": prima["severitate"] if concludent else 0,
        "incredere": prima["incredere"],
        "adresa_registru": adresa_registru,
        "an_expertiza": prima["an_expertiza"] if concludent else None,
        "expert_tehnic": prima["expert_tehnic"] if concludent else None,
        "discount_orientativ_pct": prima["discount_orientativ_pct"] if concludent else None,
        "explicatie": prima["explicatie"] if concludent else None,
        "consecinte": prima["consecinte"] if concludent else [],
        "rezumat": rezumat,
    }
