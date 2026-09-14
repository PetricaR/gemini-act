"""Generator de rapoarte PDF profesionale conform standardelor de design Google Docs."""

from __future__ import annotations

import itertools
import logging
import os
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as TTFontFile
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import paths, throttle

logger = logging.getLogger(__name__)

# Paletă Cromatică Google Professional Docs
GOOGLE_BLUE = HexColor("#1A73E8")
GOOGLE_NAVY = HexColor("#0D47A1")
GOOGLE_CHARCOAL = HexColor("#202124")
GOOGLE_GREY_MUTED = HexColor("#5F6368")
GOOGLE_MUTED = GOOGLE_GREY_MUTED
GOOGLE_SURFACE = HexColor("#F8F9FA")
GOOGLE_CARD_BG = GOOGLE_SURFACE
GOOGLE_BORDER = HexColor("#DADCE0")
GOOGLE_GREEN = HexColor("#188038")
GOOGLE_AMBER = HexColor("#E37400")
GOOGLE_RED = HexColor("#D93025")

TINT_BLUE = HexColor("#E8F0FE")
TINT_GREEN = HexColor("#E6F4EA")
TINT_AMBER = HexColor("#FEF7E0")
TINT_RED = HexColor("#FCE8E6")


# =============================================================================
# Unicode typography
# =============================================================================
# The standard PDF fonts (Helvetica & co.) are Type1 with WinAnsi encoding,
# i.e. Latin-1. Of the Romanian alphabet, Latin-1 covers a-circumflex and
# i-circumflex but NOT a-breve (U+0103), s-comma (U+0219) or t-comma (U+021B)
# -- those drew as black boxes in every heading, table cell and paragraph of
# the report. An embedded TTF is the only fix, and it has to be shipped rather
# than discovered: the deploy image is `python:3.12-slim`, which carries no
# fonts at all.

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# Names the rest of the module builds its styles from. These stay "Helvetica"
# only if registration fails -- the report still renders, with broken
# diacritics, rather than not rendering.
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"

# Codepoints the registered font can actually draw; consulted by `_txt`.
_GLYPHS_AVAILABLE: set[int] | None = None

# Roboto covers Romanian completely but carries none of the decorative glyphs
# the report reached for (star, check, arrow, warning), so those map to
# characters it does have instead of being left as black boxes. The same table
# normalises s/t written with a cedilla (U+015F/U+0163) -- the wrong form for
# Romanian, and common in scraped text -- to the comma-below letters.
_GLYPH_SUBSTITUTIONS = {
    "\u2605": "*", "\u2606": "*", "\u2713": "-", "\u2714": "-",
    "\u2717": "x", "\u2718": "x",
    "\u2192": "\u00bb", "\u2190": "\u00ab", "\u21d2": "\u00bb",
    "\u25b6": "\u00bb", "\u25ba": "\u00bb",
    "\u25cf": "\u2022", "\u25aa": "\u2022", "\u25a0": "\u2022",
    "\u25b2": "^", "\u2026": "...",
    "\u015f": "\u0219", "\u015e": "\u0218",
    "\u0163": "\u021b", "\u0162": "\u021a",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\ufe0f": "",
}


def _register_fonts() -> None:
    """Load the bundled Roboto family; degrade to Helvetica if it is missing."""
    global FONT_REGULAR, FONT_BOLD, FONT_ITALIC, _GLYPHS_AVAILABLE

    if "Roboto" in pdfmetrics.getRegisteredFontNames():
        return

    variants = {
        "Roboto": "Roboto-Regular.ttf",
        "Roboto-Bold": "Roboto-Bold.ttf",
        "Roboto-Italic": "Roboto-Italic.ttf",
        "Roboto-BoldItalic": "Roboto-BoldItalic.ttf",
    }
    try:
        for name, filename in variants.items():
            path = FONTS_DIR / filename
            if not path.exists():
                raise FileNotFoundError(path)
            pdfmetrics.registerFont(TTFontFile(name, str(path)))
        # Without this, <b> and <i> in Paragraph markup cannot find the faces.
        pdfmetrics.registerFontFamily(
            "Roboto",
            normal="Roboto",
            bold="Roboto-Bold",
            italic="Roboto-Italic",
            boldItalic="Roboto-BoldItalic",
        )
    except Exception as exc:
        logger.warning(
            "Roboto could not be registered (%s); the report falls back to Helvetica "
            "and Romanian diacritics will render incorrectly.",
            exc,
        )
        return

    FONT_REGULAR, FONT_BOLD, FONT_ITALIC = "Roboto", "Roboto-Bold", "Roboto-Italic"
    try:
        _GLYPHS_AVAILABLE = set(pdfmetrics.getFont("Roboto").face.charToGlyph)
    except Exception:
        _GLYPHS_AVAILABLE = None


def _txt(value: Any) -> str:
    """Normalise any text on its way into a Paragraph.

    Most of the report's prose comes from the model or from scraped listings,
    so it can contain any character at all. Anything the font cannot draw would
    print as a black box, so substitute what has an equivalent and drop the
    rest -- one stray emoji should not leave a hole in a valuation report.
    """
    text = "" if value is None else str(value)
    for source, target in _GLYPH_SUBSTITUTIONS.items():
        if source in text:
            text = text.replace(source, target)
    if _GLYPHS_AVAILABLE is None:
        return text
    if all(ord(ch) in _GLYPHS_AVAILABLE or ch in "\n\r\t" for ch in text):
        return text
    return "".join(
        ch if (ord(ch) in _GLYPHS_AVAILABLE or ch in "\n\r\t") else "" for ch in text
    )


_register_fonts()


class NumberedCanvas(canvas.Canvas):
    """Canvas cu două treceri pentru calculul numărului total de pagini și antet/subsol."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages: int) -> None:
        self.saveState()
        self.setFont(FONT_REGULAR, 8)
        self.setFillColor(GOOGLE_GREY_MUTED)

        # Header pe paginile 2+
        if self._pageNumber > 1:
            self.drawString(
                54,
                800,
                "RAPORT DE AUDIT & EVALUARE IMOBILIARĂ • GEMINI ACT AI",
            )
            self.setStrokeColor(GOOGLE_BORDER)
            self.setLineWidth(0.5)
            self.line(54, 794, 541, 794)

        # Footer pe toate paginile
        self.setStrokeColor(GOOGLE_BORDER)
        self.setLineWidth(0.5)
        self.line(54, 45, 541, 45)

        self.drawString(
            54,
            32,
            "Document generat automat • Conformitate metodologică ANEVAR GEV 630 & SEV 106",
        )
        page_str = f"Pagina {self._pageNumber} din {total_pages}"
        self.setFont(FONT_BOLD, 8)
        self.setFillColor(GOOGLE_CHARCOAL)
        self.drawRightString(541, 32, page_str)

        self.restoreState()


def _construieste_stiluri() -> dict[str, ParagraphStyle]:
    """Inițializează stilurile tipografice conforme Google Documentation."""
    base_styles = getSampleStyleSheet()

    stiluri = {
        "TitluDocument": ParagraphStyle(
            "TitluDocument",
            parent=base_styles["Heading1"],
            fontName=FONT_BOLD,
            fontSize=18,
            leading=22,
            textColor=GOOGLE_BLUE,
            spaceAfter=3,
        ),
        "Subtitlu": ParagraphStyle(
            "Subtitlu",
            parent=base_styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=9.5,
            leading=13,
            textColor=GOOGLE_GREY_MUTED,
            spaceAfter=10,
        ),
        "SectiuneH2": ParagraphStyle(
            "SectiuneH2",
            parent=base_styles["Heading2"],
            fontName=FONT_BOLD,
            fontSize=12,
            leading=16,
            textColor=GOOGLE_CHARCOAL,
            spaceBefore=12,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "SectiuneH3": ParagraphStyle(
            "SectiuneH3",
            parent=base_styles["Heading3"],
            fontName=FONT_BOLD,
            fontSize=10,
            leading=13,
            textColor=GOOGLE_BLUE,
            spaceBefore=8,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "Corp": ParagraphStyle(
            "Corp",
            parent=base_styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=8.5,
            leading=12,
            textColor=GOOGLE_CHARCOAL,
            spaceAfter=4,
        ),
        "CorpBold": ParagraphStyle(
            "CorpBold",
            parent=base_styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=8.5,
            leading=12,
            textColor=GOOGLE_CHARCOAL,
        ),
        "CorpMuted": ParagraphStyle(
            "CorpMuted",
            parent=base_styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=8,
            leading=11,
            textColor=GOOGLE_GREY_MUTED,
        ),
        "TabelHeader": ParagraphStyle(
            "TabelHeader",
            parent=base_styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=8,
            leading=10.5,
            textColor=white,
        ),
        "TabelCelula": ParagraphStyle(
            "TabelCelula",
            parent=base_styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=8,
            leading=10.5,
            textColor=GOOGLE_CHARCOAL,
        ),
        "TabelCelulaBold": ParagraphStyle(
            "TabelCelulaBold",
            parent=base_styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=8,
            leading=10.5,
            textColor=GOOGLE_CHARCOAL,
        ),
        "TabelCelulaMuted": ParagraphStyle(
            "TabelCelulaMuted",
            parent=base_styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=7.5,
            leading=10,
            textColor=GOOGLE_GREY_MUTED,
        ),
        "CalloutText": ParagraphStyle(
            "CalloutText",
            parent=base_styles["Normal"],
            fontName=FONT_REGULAR,
            fontSize=8.5,
            leading=12,
            textColor=GOOGLE_CHARCOAL,
        ),
        "BadgeText": ParagraphStyle(
            "BadgeText",
            parent=base_styles["Normal"],
            fontName=FONT_BOLD,
            fontSize=9.5,
            leading=12.5,
            textColor=white,
            alignment=1,
        ),
    }
    return stiluri


def _obtine_cale_imagine_locala(cale_sau_url: str | Any) -> str | None:
    """Validează sau descarcă defensiv o imagine fără a bloca sau crăpa dacă rețeaua lipsește."""
    if not cale_sau_url or not isinstance(cale_sau_url, str):
        return None

    # Fișier local direct
    if os.path.exists(cale_sau_url):
        return os.path.abspath(cale_sau_url)

    # Verificare în folderele cunoscute ale aplicației
    try:
        rep_dir = paths.reports_dir()
        if rep_dir and (rep_dir / cale_sau_url).exists():
            return str((rep_dir / cale_sau_url).resolve())
        c_dir = paths.cache_dir()
        if c_dir and (c_dir / cale_sau_url).exists():
            return str((c_dir / cale_sau_url).resolve())
    except Exception:
        pass

    # Verificare URL remote HTTP / HTTPS
    if cale_sau_url.startswith(("http://", "https://")):
        try:
            import hashlib

            h = hashlib.md5(cale_sau_url.encode("utf-8")).hexdigest()
            ext = ".jpg" if ("jpg" in cale_sau_url or "jpeg" in cale_sau_url) else (".png" if "png" in cale_sau_url else ".jpg")
            target_dir = paths.cache_dir() or paths.reports_dir()
            dest = target_dir / f"img_cache_{h}{ext}"
            if dest.exists() and dest.stat().st_size > 0:
                return str(dest.resolve())

            # Through `throttle`, not urllib: by the time the PDF is built the
            # vision pass has usually already fetched these photographs, and
            # this returns its copy without a request. What is left is paced
            # with everything else rather than racing it.
            fetched = throttle.fetch_image(
                cale_sau_url, {"User-Agent": "Mozilla/5.0 (GeminiAct/1.0)"}, timeout=3
            )
            if fetched and fetched[0]:
                dest.write_bytes(fetched[0])
                return str(dest.resolve())
        except Exception as exc:
            logger.debug("Nu s-a putut descărca imaginea remote %s: %s", cale_sau_url, exc)
            return None

    return None


def _imagine_incadrata(cale: str, latime_max: float, inaltime_max: float) -> Image | None:
    """Scale an image to fit a box without distorting it.

    `Image(path, width=W, height=H)` stretches whatever it is given to exactly
    W x H. Photographs here arrive in whatever shape the seller uploaded and a
    Street View capture is 4:3, so forcing one ratio squashed faces of
    buildings and made the contact sheet unreadable. Fit inside the box on the
    tighter of the two axes and keep the rest of the ratio.
    """
    try:
        latime_nativa, inaltime_nativa = ImageReader(cale).getSize()
        if not latime_nativa or not inaltime_nativa:
            return None
        scara = min(latime_max / latime_nativa, inaltime_max / inaltime_nativa)
        img = Image(cale, width=latime_nativa * scara, height=inaltime_nativa * scara)
        img.hAlign = "CENTER"
        return img
    except Exception as exc:
        logger.debug("Nu s-a putut încadra imaginea %s: %s", cale, exc)
        return None


def _creeaza_card_apel(
    text: str,
    stiluri: dict[str, ParagraphStyle],
    titlu: str = "",
    culoare_accent: HexColor = GOOGLE_BLUE,
    culoare_fundal: HexColor = TINT_BLUE,
) -> Table:
    """Creează o casetă de evidențiere (callout card) cu bordură stânga groasă."""
    continut = []
    if titlu:
        continut.append(
            Paragraph(
                f"<b>{_txt(titlu)}</b>",
                ParagraphStyle(
                    "CalloutTitle",
                    parent=stiluri["CorpBold"],
                    textColor=culoare_accent,
                    fontSize=9.5,
                    leading=13,
                    spaceAfter=3,
                ),
            )
        )
    continut.append(Paragraph(_txt(text), stiluri["CalloutText"]))

    tabel_card = Table(
        [[continut]],
        colWidths=[487],
    )
    tabel_card.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), culoare_fundal),
            ("LINELEFT", (0, 0), (0, -1), 3.5, culoare_accent),
            ("BOX", (0, 0), (-1, -1), 0.5, GOOGLE_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ])
    )
    return tabel_card


_CELULE_GOALE = {"", "-", "—", "–", "n/a", "N/A", "None", "nan"}


def _elimina_coloane_goale(
    randuri: list[list[Any]], latimi_coloane: list[float]
) -> tuple[list[list[Any]], list[float]]:
    """Drop columns in which no row carries a value, and re-spread their width.

    A column whose every cell is a dash is not a missing value the reader can
    act on, it is a column the data never filled -- the comparables grid used
    to print an empty "Dată" column and the sensitivity grid an empty
    "Parametru Modificat" one. Removing them and giving the space back to the
    columns that do carry text is what keeps the remaining cells from wrapping
    one character per line.
    """
    if len(randuri) < 2 or len(latimi_coloane) != len(randuri[0]):
        return randuri, latimi_coloane

    def _goala(celula: Any) -> bool:
        if isinstance(celula, (Paragraph, Table, Image)):
            return False
        return str(celula).strip() in _CELULE_GOALE

    pastrate = [
        idx
        for idx in range(len(randuri[0]))
        if not all(_goala(rand[idx]) for rand in randuri[1:] if idx < len(rand))
    ]
    if len(pastrate) == len(randuri[0]) or not pastrate:
        return randuri, latimi_coloane

    recuperat = sum(latimi_coloane) - sum(latimi_coloane[i] for i in pastrate)
    bonus = recuperat / len(pastrate)
    return (
        [[rand[i] for i in pastrate if i < len(rand)] for rand in randuri],
        [latimi_coloane[i] + bonus for i in pastrate],
    )


def _formateaza_tabel(
    randuri: list[list[Any]],
    stiluri: dict[str, ParagraphStyle],
    latimi_coloane: list[float],
    col_header_bg: HexColor = GOOGLE_BLUE,
    aliniere_stanga: bool = True,
) -> Table:
    """Construiește un tabel profesional cu rânduri alternante și antet Google Blue."""
    randuri, latimi_coloane = _elimina_coloane_goale(randuri, latimi_coloane)

    date_tabel = []
    # Header
    date_tabel.append([
        celula if isinstance(celula, (Paragraph, Table, Image)) else Paragraph(_txt(celula), stiluri["TabelHeader"])
        for celula in randuri[0]
    ])
    # Body
    for rand in randuri[1:]:
        date_tabel.append([
            celula if isinstance(celula, (Paragraph, Table, Image)) else Paragraph(_txt(celula), stiluri["TabelCelula"])
            for celula in rand
        ])

    # `repeatRows` plus a splittable table: a long grid used to be pushed whole
    # onto the next page, leaving a third of the previous one blank. It now
    # flows, and carries its header onto each page it continues on.
    tab = Table(date_tabel, colWidths=latimi_coloane, repeatRows=1, splitByRow=True)
    stil_tabel = [
        ("BACKGROUND", (0, 0), (-1, 0), col_header_bg),
        ("ALIGN", (0, 0), (-1, -1), "LEFT" if aliniere_stanga else "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, GOOGLE_BORDER),
    ]

    # Rânduri alternante
    for idx in range(1, len(randuri)):
        bg = GOOGLE_SURFACE if idx % 2 == 1 else white
        stil_tabel.append(("BACKGROUND", (0, idx), (-1, idx), bg))

    tab.setStyle(TableStyle(stil_tabel))
    return tab


def genereaza_raport_complet_pdf(
    date_proprietate: dict[str, Any],
    cale_iesire: str = "",
) -> str:
    """Generează raportul complet de audit și evaluare în format PDF conform Google Docs."""
    prop_id = str(date_proprietate.get("id") or "imobil")
    if not cale_iesire:
        cale_iesire = str(paths.reports_dir() / f"raport-complet-{prop_id}.pdf")

    os.makedirs(os.path.dirname(os.path.abspath(cale_iesire)), exist_ok=True)

    # Document A4 cu margini de 54 pt (0.75 in), lățime utilă = 487 pt
    doc = SimpleDocTemplate(
        cale_iesire,
        pagesize=A4,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    stiluri = _construieste_stiluri()
    poveste = []

    # Contor capitole numerotate dinamic (Capitolele 1 .. 12)
    _nr = itertools.count(1)

    def _titlu_sectiune(text: str) -> Paragraph:
        return Paragraph(f"{next(_nr)}. {text}", stiluri["SectiuneH2"])

    # =========================================================================
    # 1. COPERTA & SINTEZĂ PROPRIETATE (PROPERTY SUMMARY)
    # =========================================================================
    titlu_proprietate = date_proprietate.get("titlu") or f"Apartament {prop_id}"
    pret = date_proprietate.get("pret_total") or date_proprietate.get("pret") or 0
    moneda = date_proprietate.get("moneda") or "EUR"
    suprafata = date_proprietate.get("suprafata_utila") or date_proprietate.get("suprafata") or 0
    pret_mp = (
        date_proprietate.get("pret_pe_mp")
        or (round(pret / suprafata, 1) if suprafata > 0 else 0)
    )
    adresa = date_proprietate.get("adresa") or date_proprietate.get("oras") or "N/A"
    complex_name = date_proprietate.get("complex_name") or ""
    url_anunt = date_proprietate.get("url") or "N/A"

    camere = date_proprietate.get("camere")
    etaj = date_proprietate.get("etaj")
    an_c = date_proprietate.get("an_constructie")

    eval_anevar = date_proprietate.get("evaluare_anevar") or {}
    val_piata = eval_anevar.get("valoare_estimata_piata") or eval_anevar.get("valoare_estimata_eur")
    val_min = eval_anevar.get("interval_valoare_min")
    val_max = eval_anevar.get("interval_valoare_max")
    ajustare_pct = eval_anevar.get("ajustare_recomandata_procent") or eval_anevar.get("diferenta_pct")
    marja_eur = eval_anevar.get("marja_negociere_eur") or (
        (pret - val_piata) if (pret and val_piata and pret > val_piata) else 0
    )

    scor_gen = date_proprietate.get("scor_general")
    calif_gen = date_proprietate.get("calificativ_general") or ""

    poveste.append(Paragraph(_txt(titlu_proprietate), stiluri["TitluDocument"]))

    subtitlu_parts = [f"Adresă: <b>{adresa}</b>"]
    if complex_name:
        subtitlu_parts.append(f"Ansamblu: <b>{complex_name}</b>")
    if an_c:
        subtitlu_parts.append(f"An: <b>{an_c}</b>")
    if etaj:
        subtitlu_parts.append(f"Etaj: <b>{etaj}</b>")
    if camere:
        subtitlu_parts.append(f"Camere: <b>{camere}</b>")
    poveste.append(Paragraph(_txt(" • ".join(subtitlu_parts)), stiluri["Subtitlu"]))

    # 1. Sinteză Executivă & Fișă Tehnică Proprietate
    poveste.append(HRFlowable(width="100%", thickness=1, color=GOOGLE_BLUE, spaceBefore=4, spaceAfter=8))
    poveste.append(_titlu_sectiune("Sinteză Executivă & Fișă Tehnică Proprietate"))

    # Card mare de sinteză metrici (Grilă 2 rânduri x 3 coloane)
    val_piata_txt = f"{val_piata:,.0f} {moneda}" if val_piata else "N/A"
    # `ajustare_pct` is the correction recommended against the asking price, a
    # negative number when the flat is dear. Labelling it "ecart față de piață"
    # made the badge read "-4,9% above the market" -- the sign of one quantity
    # under the name of the other. Both are shown, each under its own name.
    ecart_pct = (
        (pret / val_piata - 1) * 100 if (pret and val_piata) else None
    )
    ecart_txt = (
        f"{ecart_pct:+.1f}% (~{abs(pret - val_piata):,.0f} {moneda})"
        if ecart_pct is not None
        else "N/A"
    )
    scor_txt = f"{scor_gen}/10 • {calif_gen}" if scor_gen else "Analiză Automată AI"

    badge_data = [
        [
            Paragraph(f"<b>PREȚ SOLICITAT</b><br/>{pret:,.0f} {moneda}", stiluri["BadgeText"]),
            Paragraph(f"<b>VALOARE ESTIMATĂ DE PIAȚĂ</b><br/>{val_piata_txt}", stiluri["BadgeText"]),
            Paragraph(
                f"<b>PREȚ CERUT FAȚĂ DE PIAȚĂ</b><br/>{ecart_txt}", stiluri["BadgeText"]
            ),
        ],
        [
            Paragraph(f"<b>SUPRAFAȚĂ UTILĂ</b><br/>{suprafata} mp", stiluri["BadgeText"]),
            Paragraph(f"<b>PREȚ / MP UTIL</b><br/>{pret_mp:,.0f} {moneda}/mp", stiluri["BadgeText"]),
            Paragraph(f"<b>SCOR TEHNIC & RISC GLOBAL</b><br/>{_txt(scor_txt)}", stiluri["BadgeText"]),
        ],
    ]
    tabel_badge = Table(badge_data, colWidths=[162, 162, 163])
    tabel_badge.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GOOGLE_BLUE),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("BOX", (0, 0), (-1, -1), 1, GOOGLE_NAVY),
            ("INNERGRID", (0, 0), (-1, -1), 1, white),
        ])
    )
    poveste.append(tabel_badge)
    poveste.append(Spacer(1, 10))

    # Rezumat Executiv
    rez_exec = date_proprietate.get("rezumat_executiv")
    if rez_exec:
        poveste.append(
            _creeaza_card_apel(
                rez_exec,
                stiluri,
                titlu="REZUMAT EXECUTIV & VERDICT GLOBAL",
                culoare_accent=GOOGLE_BLUE,
                culoare_fundal=TINT_BLUE,
            )
        )
        poveste.append(Spacer(1, 8))

    # Puncte Forte vs Puncte Slabe (Tabel 2 coloane)
    pf_lista = date_proprietate.get("puncte_forte") or []
    ps_lista = date_proprietate.get("puncte_slabe") or []
    if pf_lista or ps_lista:
        # The green and amber headers already carry the distinction; the check
        # and warning marks that used to lead them were glyphs the font has no
        # drawing for, so they printed as black boxes.
        linii_pf_ps = [[
            Paragraph("<b>PUNCTE FORTE (AVANTAJE IDENTIFICATE)</b>", stiluri["TabelHeader"]),
            Paragraph("<b>PUNCTE SLABE (FACTORI DE ATENȚIE & RISC)</b>", stiluri["TabelHeader"]),
        ]]
        max_rows = max(len(pf_lista), len(ps_lista))
        for i in range(max_rows):
            f_txt = f"• {_txt(pf_lista[i])}" if i < len(pf_lista) else ""
            s_txt = f"• {_txt(ps_lista[i])}" if i < len(ps_lista) else ""
            linii_pf_ps.append([
                Paragraph(f_txt, stiluri["TabelCelula"]),
                Paragraph(s_txt, stiluri["TabelCelula"]),
            ])
        tab_pf_ps = Table(linii_pf_ps, colWidths=[243, 244])
        tab_pf_ps.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), GOOGLE_GREEN),
                ("BACKGROUND", (1, 0), (1, 0), GOOGLE_AMBER),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, GOOGLE_BORDER),
            ])
        )
        poveste.append(tab_pf_ps)
        poveste.append(Spacer(1, 10))

    # Inserare Foaie de Contact Galerie dacă există
    cale_galerie = date_proprietate.get("cale_galerie")
    if cale_galerie and os.path.exists(cale_galerie):
        # The contact sheet is a tall grid of the seller's photographs. Forcing
        # it into 487x200 squashed every frame in it; fitted to the text width
        # and a half-page ceiling, it stays readable and the rows stay square.
        img_galerie = _imagine_incadrata(cale_galerie, 487, 330)
        if img_galerie is not None:
            poveste.append(
                KeepTogether([
                    Paragraph("<b>Foaie de Contact Foto Ofertă</b>", stiluri["SectiuneH3"]),
                    img_galerie,
                ])
            )
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # 2. EVALUARE DE PIAȚĂ ANEVAR (GEV 630) & TOATE ABORDĂRILE
    # =========================================================================
    poveste.append(HRFlowable(width="100%", thickness=1, color=GOOGLE_BLUE, spaceBefore=4, spaceAfter=8))
    poveste.append(_titlu_sectiune("Evaluare de Piață ANEVAR (GEV 630) & Abordările Valorii"))

    evaluare_disponibila = not (
        eval_anevar.get("status") == "indisponibil" or eval_anevar.get("disponibil") is False
    )

    if not evaluare_disponibila:
        motiv = eval_anevar.get("motiv") or (
            "Eșantion insuficient: sub 3 comparabile conforme identificate (GEV 630)."
        )
        card_anevar_text = (
            f"<b>Evaluare de piață indisponibilă:</b> {motiv}<br/>"
            f"<i>Conform standardului ANEVAR GEV 630 (Metoda Comparației Directe), "
            f"estimarea valorii de piață necesită un eșantion minim de 3 "
            f"oferte/tranzacții comparabile relevante și calificate.</i>"
        )
        poveste.append(
            _creeaza_card_apel(
                card_anevar_text,
                stiluri,
                titlu="EVALUARE ANEVAR INDISPONIBILĂ",
                culoare_accent=GOOGLE_MUTED,
                culoare_fundal=GOOGLE_CARD_BG,
            )
        )
        poveste.append(Spacer(1, 8))
    else:
        val_piata = val_piata or pret or 0
        if val_min is not None and val_max is not None:
            interval_txt = f" (interval credibil <b>{val_min:,.0f} - {val_max:,.0f} {moneda}</b>)"
        else:
            interval_txt = " (interval de dispersie în curs de consolidare)"

        # Two quantities that are easy to confuse and were being confused: the
        # correction recommended against the asking price, and the gap by which
        # the asking price stands above (or below) the estimate. Each is named
        # explicitly, because -4,9% and +5,2% describe the same property.
        if ajustare_pct is None:
            ajustare_txt = "Ajustarea față de prețul cerut nu a putut fi calculată."
        else:
            ajustare_txt = f"Ajustare recomandată față de prețul cerut: <b>{ajustare_pct:+.1f}%</b>."
            if ecart_pct is not None:
                pozitie = "peste" if ecart_pct >= 0 else "sub"
                ajustare_txt += (
                    f" Prețul solicitat se află cu <b>{abs(ecart_pct):.1f}%</b> "
                    f"{pozitie} valoarea estimată."
                )

        fiabilitate = eval_anevar.get("fiabilitate", "medie")
        motiv_fiabilitate = eval_anevar.get("motiv_fiabilitate", "")
        fiab_text = f" • Fiabilitate: <b>{str(fiabilitate).upper()}</b> ({_txt(motiv_fiabilitate)})" if motiv_fiabilitate else ""

        card_anevar_text = (
            f"Conform standardului ANEVAR GEV 630 (Metoda Comparației Directe), "
            f"valoarea de piață estimată este de <b>{val_piata:,.0f} {moneda}</b>"
            f"{interval_txt}. {ajustare_txt}{fiab_text}"
        )
        favorabil = ajustare_pct is None or ajustare_pct >= -3.0
        accent_anevar = GOOGLE_GREEN if favorabil else GOOGLE_AMBER
        tint_anevar = TINT_GREEN if favorabil else TINT_AMBER
        poveste.append(
            _creeaza_card_apel(
                card_anevar_text,
                stiluri,
                titlu="VERDICT EVALUARE & CONCLUZIE VALOARE DE PIAȚĂ",
                culoare_accent=accent_anevar,
                culoare_fundal=tint_anevar,
            )
        )
        poveste.append(Spacer(1, 8))

        # 2.1 Grilă comparabile utilizate
        comps = eval_anevar.get("comparabile_utilizate", [])
        if isinstance(comps, dict):
            comps = list(comps.values())
        elif not isinstance(comps, (list, tuple)):
            comps = []

        if comps:
            poveste.append(Paragraph("<b>Grilă de Comparație Directă (Proprietăți Comparabile Calificate)</b>", stiluri["SectiuneH3"]))
            linii_comps = [[
                "Anunț (link) / Adresă",
                "Dist.",
                "Dată",
                "Preț Solicitat",
                "Supr.",
                "Preț / mp",
                "Ajustare",
                "Val. Corectată/mp",
            ]]
            # Every comparable, not the first six: the grid is the evidence for
            # the conclusion, and a reader who cannot see all of it cannot check
            # it. Each row links to the listing it came from.
            for c in comps:
                cid = str(c.get("id") or c.get("adresa") or "Comp")
                eticheta = _txt(c.get("adresa") or cid)
                if url := c.get("url"):
                    eticheta = (
                        f'<link href="{url}" color="#1A73E8">{eticheta}</link>'
                        f'<br/><font size="6" color="#5F6368">{_txt(cid)}</font>'
                    )
                dist = f"{c.get('distanta_km')} km" if c.get("distanta_km") is not None else "-"
                dt = str(
                    c.get("data_tranzactiei")
                    or c.get("data_tranzactie")
                    or c.get("data")
                    or "-"
                )
                c_pret = c.get("pret_total") or c.get("pret") or 0
                c_sup = c.get("suprafata_utila") or c.get("suprafata") or 0
                c_pmp = c.get("pret_mp") or c.get("pret_mp_eur") or (round(c_pret / c_sup) if c_sup else 0)
                aj_net = c.get("ajustare_neta_procent")
                # "0.0%" claimed a comparable needed no adjustment; None means
                # nobody computed one.
                aj_str = f"{aj_net:+.1f}%" if aj_net is not None else "n/a"
                val_cor = c.get("valoare_corectata_eur_mp")
                val_cor_str = f"{val_cor:,.0f} €/mp" if val_cor else "-"

                linii_comps.append([
                    eticheta,
                    dist,
                    dt,
                    f"{c_pret:,.0f} {moneda}",
                    f"{c_sup} mp",
                    f"{c_pmp:,.0f} €",
                    aj_str,
                    val_cor_str,
                ])
            poveste.append(
                _formateaza_tabel(linii_comps, stiluri, [110, 34, 54, 60, 40, 48, 44, 97])
            )
            poveste.append(Spacer(1, 8))

        # 2.2 Abordarea prin Venit
        ap_venit = eval_anevar.get("abordare_venit") or date_proprietate.get("abordare_venit")
        if ap_venit and isinstance(ap_venit, dict):
            poveste.append(Paragraph("<b>Abordarea prin Venit (Metoda Capitalizării Directe)</b>", stiluri["SectiuneH3"]))
            chirie_m = ap_venit.get("chirie_lunara_estimata_eur") or ap_venit.get("chirie_lunara_eur") or 0
            chirie_mp_v = (
                ap_venit.get("chirie_eur_mp_luna")
                or ap_venit.get("chirie_mp_eur")
                or (round(chirie_m / suprafata, 1) if suprafata else 0)
            )
            neocupare = ap_venit.get("grad_neocupare_procent") or ap_venit.get("neocupare_procent") or 0
            opex = ap_venit.get("cheltuieli_operationale_procent") or 0
            noi = (
                ap_venit.get("venit_net_anual_noi_eur")
                or ap_venit.get("venit_net_anual_eur")
                or ap_venit.get("noi_eur")
                or 0
            )
            cap_rate = ap_venit.get("rata_capitalizare_procent") or ap_venit.get("cap_rate") or 0
            rand_brut = ap_venit.get("randament_brut_procent") or 0
            val_venit = ap_venit.get("valoare_prin_venit_eur") or ap_venit.get("valoare_rezultata_eur") or 0
            com_venit = ap_venit.get("comentariu") or "Valoarea prin capitalizare reflectă potențialul de randament investițional."

            # NOI is the one line of this table a reader recomputes by hand, so
            # when the source did not carry it, derive it from the three rows
            # above rather than printing "0 EUR/an" under a real rent.
            noi_derivat = False
            if not noi and chirie_m:
                noi = chirie_m * 12 * (1 - neocupare / 100) * (1 - opex / 100)
                noi_derivat = True
            noi_txt = f"{noi:,.0f} EUR/an" if noi else "Nedeterminat"
            noi_nota = (
                "Chirie anuală, minus neocuparea și cheltuielile de exploatare de mai sus"
                if noi_derivat
                else "Venit net generat după cheltuieli"
            )

            randuri_venit = [
                ["Indicator Financiar Investițional", "Valoare Parametru", "Observații Metodologice"],
                ["Chirie Lunară Estimată", f"{chirie_m:,.0f} EUR/lună", f"{chirie_mp_v:.1f} EUR/mp/lună conform pieței"],
                ["Grad de Neocupare & Risc Vacanță", f"{neocupare}%", "Timp mediu de tranziție între chiriași"],
                ["Cheltuieli Operaționale (Opex)", f"{opex}%", "Mentenanță, fond rulment, taxe locale"],
                ["Venit Net Anual din Exploatare (NOI)", noi_txt, noi_nota],
                ["Rată de Capitalizare (Cap Rate)", f"{cap_rate:.2f}%", "Rata de referință a pieței rezidențiale"],
                ["Randament Brut Estimativ", f"{rand_brut:.2f}%", "Chirie anuală brută raportată la prețul cerut"],
                ["Valoare Rezultată prin Venit", f"{val_venit:,.0f} EUR", "Valoare obținută prin capitalizare NOI / CapRate"],
            ]
            poveste.append(_formateaza_tabel(randuri_venit, stiluri, [160, 110, 217]))
            poveste.append(Paragraph(f"<i>{_txt(com_venit)}</i>", stiluri["CorpMuted"]))
            poveste.append(Spacer(1, 8))

        # 2.3 Abordarea prin Cost
        ap_cost = eval_anevar.get("abordare_cost") or date_proprietate.get("abordare_cost")
        if ap_cost and isinstance(ap_cost, dict):
            poveste.append(Paragraph("<b>Abordarea prin Cost (Costul de Înlocuire Net de Depreciere)</b>", stiluri["SectiuneH3"]))
            teren = ap_cost.get("valoare_teren_alocata_eur") or ap_cost.get("valoare_teren_cota_indiviza_eur") or ap_cost.get("valoare_teren_eur") or 0
            rcn = ap_cost.get("cost_reconstructie_nou_eur") or ap_cost.get("rcn_eur") or 0
            depr_fiz = ap_cost.get("depreciere_fizica_procent") or ap_cost.get("deprecierea_fizica_procent") or 0
            depr_func = ap_cost.get("depreciere_functionala_procent") or ap_cost.get("deprecierea_functionala_procent") or 0
            val_cost = ap_cost.get("valoare_prin_cost_eur") or ap_cost.get("valoare_rezultata_eur") or 0
            com_cost = ap_cost.get("comentariu") or "Calculat conform standardelor de cost de înlocuire net."

            randuri_cost = [
                ["Componentă Cost Înlocuire", "Valoare Parametru", "Detalii & Fundamentare"],
                ["Cota Alocată din Valoarea Terenului", f"{teren:,.0f} EUR", "Cota indiviză aferentă apartamentului"],
                ["Cost Reconstrucție de Nou (RCN)", f"{rcn:,.0f} EUR", "Cost estimativ manoperă și materiale moderne"],
                ["Depreciere Fizică Cumulată", f"{depr_fiz:.1f}%", "Uzură fizică în funcție de vechimea imobilului"],
                ["Depreciere Funcțională & Externă", f"{depr_func:.1f}%", "Factori de configurare și ambient"],
                ["Valoare Rezultată prin Cost", f"{val_cost:,.0f} EUR", "Teren + RCN diminuat cu deprecierile totale"],
            ]
            poveste.append(_formateaza_tabel(randuri_cost, stiluri, [160, 110, 217]))
            poveste.append(Paragraph(f"<i>{_txt(com_cost)}</i>", stiluri["CorpMuted"]))
            poveste.append(Spacer(1, 8))

        # 2.4 Reconcilierea Abordărilor
        reconciliere = eval_anevar.get("reconciliere") or date_proprietate.get("reconciliere")
        if reconciliere and isinstance(reconciliere, dict):
            poveste.append(Paragraph("<b>Reconcilierea Abordărilor de Evaluare & Concluzia Valorii</b>", stiluri["SectiuneH3"]))
            pond_comp = reconciliere.get("pondere_comparatie_procent") or reconciliere.get("pondere_comparatii_procent") or reconciliere.get("pondere_piata_procent") or 0
            pond_venit = reconciliere.get("pondere_venit_procent") or 0
            pond_cost = reconciliere.get("pondere_cost_procent") or 0
            val_rec = reconciliere.get("valoare_reconciliata_eur") or val_piata
            justif = reconciliere.get("justificare_ponderi") or reconciliere.get("concluzie") or ""

            val_venit_disp = val_venit if "val_venit" in locals() and val_venit else val_piata
            val_cost_disp = val_cost if "val_cost" in locals() and val_cost else val_piata

            # The column is headed "Contribuție în Valoarea Finală", so the last
            # row has to be the sum of the three above it. It used to print the
            # reconciled value instead, and the two differ -- 326.258 against a
            # stated 328.000 on the demo dossier -- which reads as an
            # arithmetic error in the one table meant to show the arithmetic.
            contributii = [
                val_piata * pond_comp / 100,
                val_venit_disp * pond_venit / 100,
                val_cost_disp * pond_cost / 100,
            ]
            suma_ponderata = sum(contributii)
            pondere_totala = pond_comp + pond_venit + pond_cost

            randuri_rec = [
                ["Metodă de Evaluare ANEVAR", "Pondere Alocată", "Valoare Metodă", "Contribuție în Valoarea Finală"],
                ["Metoda Comparației Directe", f"{pond_comp}%", f"{val_piata:,.0f} EUR", f"{contributii[0]:,.0f} EUR"],
                ["Abordarea prin Venit (Capitalizare)", f"{pond_venit}%", f"{val_venit_disp:,.0f} EUR", f"{contributii[1]:,.0f} EUR"],
                ["Abordarea prin Cost (Înlocuire Netă)", f"{pond_cost}%", f"{val_cost_disp:,.0f} EUR", f"{contributii[2]:,.0f} EUR"],
                [
                    "Valoare Ponderată a Abordărilor",
                    f"{pondere_totala:,.0f}%",
                    "—",
                    f"{suma_ponderata:,.0f} EUR",
                ],
                [
                    "<b>Valoare Finală Reconciliată</b>",
                    "",
                    "",
                    f"<b>{val_rec:,.0f} EUR</b>",
                ],
            ]
            poveste.append(_formateaza_tabel(randuri_rec, stiluri, [150, 85, 112, 140]))
            # A valuer is allowed to round the weighted result to a round
            # number, but the reader should be told that is what happened
            # rather than left to spot the gap.
            if val_rec and abs(val_rec - suma_ponderata) >= 1:
                poveste.append(Paragraph(
                    f"<i>Valoarea finală este rezultatul ponderat de "
                    f"{suma_ponderata:,.0f} {moneda}, rotunjit la {val_rec:,.0f} {moneda} "
                    f"(diferență de {abs(val_rec - suma_ponderata):,.0f} {moneda}).</i>",
                    stiluri["CorpMuted"],
                ))
            if justif:
                poveste.append(Paragraph(f"<b>Justificare Reconciliere:</b> {_txt(justif)}", stiluri["CorpMuted"]))
            poveste.append(Spacer(1, 8))

        # 2.5 Analiză de Senzitivitate
        senz = eval_anevar.get("senzitivitate") or date_proprietate.get("senzitivitate")
        scenarii = []
        com_senz = ""
        if isinstance(senz, dict):
            scenarii = senz.get("scenarii", [])
            com_senz = senz.get("comentariu_cel_mai_defavorabil") or senz.get("comentariu") or ""
        elif isinstance(senz, (list, tuple)):
            scenarii = list(senz)

        if scenarii:
            poveste.append(Paragraph("<b>Analiză de Senzitivitate la Șocuri de Piață</b>", stiluri["SectiuneH3"]))
            randuri_senz = [["Scenariu / Factor de Stres", "Parametru Modificat", "Valoare Rezultată (€)", "Variație față de Bază"]]
            for sc in scenarii:
                if isinstance(sc, dict):
                    randuri_senz.append([
                        str(sc.get("scenariu") or sc.get("nume") or "-"),
                        str(sc.get("parametru") or "-"),
                        f"{sc.get('valoare_eur', 0):,.0f} €",
                        f"{sc.get('delta_procent', 0):+.1f}%",
                    ])
            poveste.append(_formateaza_tabel(randuri_senz, stiluri, [140, 120, 110, 117]))
            if com_senz:
                poveste.append(Paragraph(f"<i>Reziliență: {_txt(com_senz)}</i>", stiluri["CorpMuted"]))
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # 3. LOCALIZARE URBANĂ & INFRASTRUCTURĂ POI (RAZĂ DE 500M)
    # =========================================================================
    locatie = date_proprietate.get("locatie") or {}
    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Localizare Urbană & Infrastructură POI (Rază de 500m)"),
    ]))

    locatie_ok = (
        isinstance(locatie, dict)
        and (
            locatie.get("status") == "success"
            or bool(locatie.get("facilitati"))
            or bool(locatie.get("scor_accesibilitate"))
        )
    )

    if not locatie_ok:
        motiv_loc = (
            locatie.get("motiv")
            if isinstance(locatie, dict)
            else "Informațiile de localizare și cartografiere a facilităților pe raza de 500 m nu sunt disponibile."
        ) or "Datele de localizare nu au putut fi obținute pentru această adresă (serviciul Google Maps indisponibil)."
        poveste.append(
            _creeaza_card_apel(
                f"<b>Informații de proximitate și facilități indisponibile:</b> {motiv_loc}<br/>"
                f"<i>Recomandăm verificarea pe teren a distanțelor reale către stațiile de transport public, magazine și unități de învățământ.</i>",
                stiluri,
                titlu="LOCALIZARE URBANĂ & FACILITĂȚI INDISPONIBILE",
                culoare_accent=GOOGLE_MUTED,
                culoare_fundal=GOOGLE_CARD_BG,
            )
        )
        poveste.append(Spacer(1, 10))
    else:
        scor_acc = locatie.get("scor_accesibilitate")
        scor_acc_txt = f"{scor_acc}/10" if scor_acc is not None else "N/A"
        adresa_f = locatie.get("adresa_formatata") or adresa
        coordonate = locatie.get("coordonate") or {}
        lat_c = locatie.get("lat") or coordonate.get("lat") or date_proprietate.get("lat")
        lon_c = locatie.get("lon") or coordonate.get("lon") or date_proprietate.get("lon")
        lat_txt = f"{lat_c:.5f}" if lat_c else "-"
        lon_txt = f"{lon_c:.5f}" if lon_c else "-"

        fac_list = []
        fac_raw = locatie.get("facilitati") or []
        if isinstance(fac_raw, dict):
            for cat_key, items in fac_raw.items():
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict):
                            it_copy = dict(it)
                            it_copy.setdefault("categorie", cat_key)
                            fac_list.append(it_copy)
                elif isinstance(items, dict):
                    it_copy = dict(items)
                    it_copy.setdefault("categorie", cat_key)
                    fac_list.append(it_copy)
        elif isinstance(fac_raw, (list, tuple)):
            fac_list = [f for f in fac_raw if isinstance(f, dict)]

        fac_list.sort(key=lambda x: x.get("distanta_m") or x.get("distanta_metri") or 999999)
        tot_fac = locatie.get("total_facilitati") or len(fac_list)

        text_loc = (
            f"<b>Adresă Formatată:</b> {adresa_f} • <b>Coordonate GPS:</b> {lat_txt}, {lon_txt}<br/>"
            f"<b>Scor Accesibilitate Urbană:</b> <b>{scor_acc_txt}</b> • "
            f"<b>Total Facilități Esențiale Identificate:</b> <b>{tot_fac} obiective</b> pe o rază de 500m.<br/>"
            f"<i>Amplasament conectat la rețeaua de transport public subteran/suprateran, școli și centre comerciale.</i>"
        )
        poveste.append(_creeaza_card_apel(text_loc, stiluri, titlu="ANALIZĂ ACCESIBILITATE & CONECTIVITATE URBANĂ", culoare_accent=GOOGLE_BLUE))
        poveste.append(Spacer(1, 8))

        if fac_list:
            poveste.append(Paragraph("<b>Facilități și Puncte de Interes Măsurate pe Teren (Google Places)</b>", stiluri["SectiuneH3"]))
            randuri_fac = [["Categorie POI", "Denumire Facilitate / Obiectiv", "Distanță", "Timp Mers", "Rating"]]
            for f in fac_list[:12]:
                cat = str(f.get("categorie") or f.get("tip") or "General").capitalize()
                nume_f = str(f.get("nume") or f.get("denumire") or "-")
                dist_m = f.get("distanta_m") or f.get("distanta_metri") or 0
                timp_min = f.get("minute_mers") or f.get("timp_mers_pe_jos_minute") or f.get("timp_minute") or (round(dist_m / 80) if dist_m else 1)
                rat = f.get("rating_google") or f.get("rating")
                rat_txt = f"{rat:.1f}/5" if rat else "-"
                randuri_fac.append([
                    cat,
                    nume_f,
                    f"{dist_m} m",
                    f"~{timp_min} min",
                    rat_txt,
                ])
            poveste.append(_formateaza_tabel(randuri_fac, stiluri, [100, 197, 65, 65, 60]))
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # 4. AUDIT EXTERIOR & INSPECȚIE 360° GOOGLE STREET VIEW
    # =========================================================================
    audit_ext = date_proprietate.get("audit_exterior") or {}
    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Audit Exterior & Inspecție 360° Google Street View"),
    ]))

    ext_indisponibil = (
        not audit_ext
        or audit_ext.get("status") == "indisponibil"
        or audit_ext.get("disponibil") is False
    )

    if ext_indisponibil:
        motiv_ext = (
            audit_ext.get("motiv")
            if isinstance(audit_ext, dict)
            else "Inspecția vizuală exterioară Google Street View nu este disponibilă pentru această adresă."
        ) or "Google Street View nu are acoperire 360° înregistrată pentru această locație."
        poveste.append(
            _creeaza_card_apel(
                f"<b>Inspecție exterioară indisponibilă:</b> {motiv_ext}<br/>"
                f"<i>Recomandăm inspectarea directă pe teren a fațadei, trotuarelor, parcărilor și stării drumului de acces.</i>",
                stiluri,
                titlu="AUDIT VIZUAL EXTERIOR INDISPONIBIL",
                culoare_accent=GOOGLE_MUTED,
                culoare_fundal=GOOGLE_CARD_BG,
            )
        )
        poveste.append(Spacer(1, 10))
    else:
        glob_ext = audit_ext.get("evaluare_globala_exterior") or {}
        scor_fatada = audit_ext.get("scor_fatada") or audit_ext.get("scor_exterior") or glob_ext.get("scor_calitate_cladire_si_fatada")
        scor_strada = audit_ext.get("scor_strada") or glob_ext.get("scor_ambient_strada_si_zona")
        clasa_fatada = audit_ext.get("clasa_fatada") or "Neclasificat"
        stare_fatada = audit_ext.get("stare_fatada") or (audit_ext.get("cladire_si_fatada", {}) or {}).get("stare_generala_fatada")
        concluzie_ext = audit_ext.get("concluzie_generala_exterior") or glob_ext.get("concluzie_audit_exterior")

        # A missing score printed as "N/A/10", which reads like a score.
        def _scor(valoare: Any) -> str:
            return f"Scor {valoare}/10" if valoare is not None else "Nepunctat"

        linii_ext = [
            f"<b>Clasă & Stare Fațadă:</b> {clasa_fatada} ({_scor(scor_fatada)}) • "
            f"<b>Infrastructură Stradă:</b> {_scor(scor_strada)}."
        ]
        if stare_fatada:
            linii_ext.append(f"<b>Constatare Tehnică Fațadă:</b> {stare_fatada}")
        if concluzie_ext:
            linii_ext.append(f"<b>Concluzie Exterior:</b> {concluzie_ext}")
        text_ext = "<br/>".join(linii_ext)
        poveste.append(_creeaza_card_apel(text_ext, stiluri, titlu="AUDIT VIZUAL STRADĂ & FAȚADĂ", culoare_accent=GOOGLE_BLUE))
        poveste.append(Spacer(1, 8))

        # Detaliere pe componente exterioare. Fiecare rând raportează ce s-a
        # observat sau spune explicit că nu s-a observat nimic -- valorile
        # implicite anterioare afirmau trotuare conforme și hidroizolație bună
        # pentru imobile pe care nimeni nu le inspectase.
        _NEOBSERVAT = "Neevaluat din imaginile disponibile"
        randuri_ext_comp = [
            ["Componentă Exterioară Analizată", "Constatare Tehnică & Stare Constatată"],
            ["Fațadă & Finisaje", str(audit_ext.get("stare_fatada") or _NEOBSERVAT)],
            ["Trotuare & Căi de Acces", str(audit_ext.get("trotuare_si_acces") or _NEOBSERVAT)],
            ["Cabluri Aeriene & Utilități", str(audit_ext.get("cabluri_aeriene") or _NEOBSERVAT)],
            ["Parcare & Căi Rutiere", str(audit_ext.get("parcare_si_strazi") or _NEOBSERVAT)],
            ["Acoperiș & Terasă", str(audit_ext.get("acoperis_terasa") or _NEOBSERVAT)],
        ]
        poveste.append(_formateaza_tabel(randuri_ext_comp, stiluri, [150, 337]))
        poveste.append(Spacer(1, 8))

        # Imagini Street View / Satelit
        poze_raw = audit_ext.get("imagini_salvate", [])
        if isinstance(poze_raw, dict):
            lista_poze = [poze_raw] if ("cale" in poze_raw or "url" in poze_raw or "path" in poze_raw) else list(poze_raw.values())
        elif isinstance(poze_raw, (list, tuple)):
            lista_poze = list(poze_raw)
        else:
            lista_poze = []

        rand_poze_flux = []
        for item in lista_poze[:4]:
            cale_cand = item.get("cale") or item.get("path") or item.get("url") if isinstance(item, dict) else str(item)
            cale_reala = _obtine_cale_imagine_locala(cale_cand)
            if not (cale_reala and os.path.exists(cale_reala)):
                continue
            # Fitted, not forced to 238x135: a Street View capture is 4:3 and a
            # seller's photograph is whatever they uploaded, so a fixed 16:9 box
            # was visibly stretching both.
            img = _imagine_incadrata(cale_reala, 231, 150)
            if img is None:
                continue
            eticheta = item.get("eticheta") or item.get("descriere") if isinstance(item, dict) else None
            if eticheta:
                celula = [img, Spacer(1, 2), Paragraph(_txt(eticheta), stiluri["CorpMuted"])]
            else:
                celula = img
            rand_poze_flux.append(celula)

        if rand_poze_flux:
            for i in range(0, len(rand_poze_flux), 2):
                grup = rand_poze_flux[i : i + 2]
                col_w = [243, 244] if len(grup) == 2 else [487]
                tab_img = Table([grup], colWidths=col_w)
                tab_img.setStyle(TableStyle([
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("BOX", (0, 0), (-1, -1), 0.5, GOOGLE_BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, GOOGLE_BORDER),
                ]))
                poveste.append(tab_img)
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # 5. AUDIT FINISAJE, CALITATE EXECUȚIE & ESTIMARE DEFICIENȚE
    # =========================================================================
    audit_ef = date_proprietate.get("audit_electrocasnice_finisaje") or date_proprietate.get("audit_electrocasnice") or {}
    audit_mob = date_proprietate.get("audit_mobilier") or {}

    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Audit Finisaje, Calitate Execuție & Estimare Deficiențe"),
    ]))

    fin_indisponibil = not (audit_ef or audit_mob) or (
        isinstance(audit_ef, dict) and (audit_ef.get("status") == "indisponibil" or audit_ef.get("disponibil") is False)
    )

    if fin_indisponibil:
        poveste.append(
            _creeaza_card_apel(
                "<b>Audit vizual interior neefectuat:</b> Nu au fost furnizate fotografii detaliate ale interiorului "
                "sau finisajelor. Recomandăm inspecția amănunțită a suprafețelor (planeitate șape, îmbinări, rosturi gresie) "
                "la vizionarea directă.",
                stiluri,
                titlu="AUDIT FINISAJE INDISPONIBIL",
                culoare_accent=GOOGLE_MUTED,
                culoare_fundal=GOOGLE_CARD_BG,
            )
        )
        poveste.append(Spacer(1, 10))
    else:
        # Calitate finisaje & Sumar financiar defecte
        sumar_ef = audit_ef.get("sumar_financiar") or {}
        bug_rep = (
            sumar_ef.get("total_buget_remediere_defecte_eur")
            or audit_ef.get("buget_total_reparatii_eur")
            or audit_ef.get("total_buget_remediere_defecte_eur")
            or 0
        )
        bug_rep_ron = sumar_ef.get("total_buget_remediere_defecte_ron") or (round(bug_rep * 4.97) if bug_rep else 0)
        levier_neg = (
            sumar_ef.get("impact_negociere_recomandat_eur")
            or audit_ef.get("levier_negociere_recomandat_eur")
            or audit_ef.get("impact_negociere_recomandat_eur")
            or 0
        )

        cal_gen = audit_ef.get("calitate_generala_finisaje") or {}
        scor_fin = cal_gen.get("scor_global") or audit_ef.get("scor_finisaje") or audit_mob.get("scor_calitate_finisaje", "N/A")
        clasa_fin = str(cal_gen.get("clasa") or audit_ef.get("clasa_finisaje", "Standard")).capitalize()
        recom_eval = sumar_ef.get("recomandare_evaluator") or audit_ef.get("recomandare_generala") or ""

        card_fin_text = (
            f"<b>Scor Global Finisaje:</b> <b>{scor_fin}/10</b> ({clasa_fin}) • "
            f"<b>Buget Necesar Remediere Defecte:</b> <b>~{bug_rep:,.0f} EUR</b> (~{bug_rep_ron:,.0f} RON)<br/>"
            f"<b>Levier de Negociere Recomandat:</b> <b>-{levier_neg:,.0f} EUR</b> față de prețul cerut.<br/>"
            f"<i>{recom_eval}</i>"
        )
        accent_fin = GOOGLE_AMBER if bug_rep > 300 else GOOGLE_GREEN
        tint_fin = TINT_AMBER if bug_rep > 300 else TINT_GREEN
        poveste.append(_creeaza_card_apel(card_fin_text, stiluri, titlu="SUMAR EVALUARE FINISAJE & DEFECTE", culoare_accent=accent_fin, culoare_fundal=tint_fin))
        poveste.append(Spacer(1, 8))

        # Categorii de finisaje detaliate
        cat_fin = audit_ef.get("categorii_finisaje") or []
        if isinstance(cat_fin, dict):
            cat_fin = list(cat_fin.values())
        if cat_fin:
            poveste.append(Paragraph("<b>Inspecție pe Categorii de Finisaje Interioare</b>", stiluri["SectiuneH3"]))
            randuri_cf = [["Categorie Finisaj", "Nivel Calitate / Clasă", "Notă", "Observații Tehnice & Materiale"]]
            for cf in cat_fin:
                c_nume = cf.get("categorie") or cf.get("nume") or "Finisaj"
                c_cal = cf.get("nivel_calitate") or cf.get("calitate") or cf.get("clasa") or "-"
                c_nota = str(cf.get("scor") or cf.get("nota") or cf.get("stare") or "Bună")
                c_obs = cf.get("observatii") or cf.get("detalii") or "-"
                randuri_cf.append([c_nume, c_cal, c_nota, c_obs])
            poveste.append(_formateaza_tabel(randuri_cf, stiluri, [100, 95, 65, 227]))
            poveste.append(Spacer(1, 8))

        # Defecte identificate & probleme
        defecte = audit_ef.get("defecte_si_probleme") or audit_ef.get("defecte_identificate") or []
        if isinstance(defecte, dict):
            defecte = list(defecte.values())
        if defecte:
            poveste.append(Paragraph("<b>Defecte Vizibile Identificate & Acțiuni Recomandate</b>", stiluri["SectiuneH3"]))
            randuri_def = [["Element Afectat", "Descriere Defect", "Severitate", "Cost Estimat", "Recomandare Remediere"]]
            for d in defecte[:8]:
                elem = d.get("element_afectat") or d.get("element") or "-"
                desc = d.get("descriere_defect") or d.get("defect") or "-"
                sev = d.get("severitate") or "Moderat"
                cost_e = d.get("cost_estimat_remediere_eur") or d.get("cost_estimat_eur", 0)
                cost_r = d.get("cost_estimat_remediere_ron") or (round(cost_e * 4.97) if cost_e else 0)
                sol = d.get("remediere_recomandata") or d.get("remediere") or d.get("solutie") or "Reparație locală"
                randuri_def.append([
                    elem,
                    desc,
                    sev,
                    f"~{cost_e:,.0f} € ({cost_r:,.0f} RON)",
                    sol,
                ])
            poveste.append(_formateaza_tabel(randuri_def, stiluri, [90, 140, 60, 77, 120]))
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # 6. CATALOG ELECTROCASNICE & DOTĂRI INCLUSE ÎN TRANZACȚIE
    # =========================================================================
    electro = (audit_ef.get("electrocasnice") or date_proprietate.get("electrocasnice") or [])
    if isinstance(electro, dict):
        electro = list(electro.values())

    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Catalog Electrocasnice & Dotări Incluse în Tranzacție"),
    ]))

    if not electro:
        poveste.append(
            _creeaza_card_apel(
                "<b>Nu au fost identificate electrocasnice incluse:</b> Oferta nu specifică aparatură electrocasnică "
                "sau imobilul se tranzacționează nemobilat/neutilat.",
                stiluri,
                titlu="DOTĂRI ELECTROCASNICE NESPECIFICATE",
                culoare_accent=GOOGLE_MUTED,
                culoare_fundal=GOOGLE_CARD_BG,
            )
        )
        poveste.append(Spacer(1, 10))
    else:
        val_nou = (
            sumar_ef.get("total_valoare_nou_electrocasnice_eur")
            or audit_ef.get("total_valoare_nou_eur")
            or sum(e.get("pret_estimat_nou_eur", 0) or e.get("pret_nou_estimat_eur", 0) for e in electro if isinstance(e, dict))
        )
        val_act = (
            sumar_ef.get("total_valoare_actuala_electrocasnice_eur")
            or audit_ef.get("total_valoare_actuala_eur")
            or sum(e.get("valoare_piata_actuala_eur", 0) or e.get("valoare_actuala_eur", 0) for e in electro if isinstance(e, dict))
        )
        depr_el = round((1 - val_act / val_nou) * 100, 1) if val_nou > 0 else 0

        card_el_txt = (
            f"<b>Valoare Pachet Echipamente de Nou:</b> ~{val_nou:,.0f} EUR • "
            f"<b>Valoare Actuală Amortizată de Piață:</b> <b>~{val_act:,.0f} EUR</b><br/>"
            f"<b>Grad de Amortizare / Uzură Pachet:</b> {depr_el}% • "
            f"Pachetul de electrocasnice este inclus în prețul de listare al proprietății."
        )
        poveste.append(_creeaza_card_apel(card_el_txt, stiluri, titlu="EVALUARE PACHET ELECTROCASNICE & ECHIPAMENTE", culoare_accent=GOOGLE_BLUE))
        poveste.append(Spacer(1, 8))

        randuri_cat_el = [["Aparat", "Cameră", "Brand & Model / Gamă", "Nivel", "Preț Nou", "Val. Act.", "Stare"]]
        for e in electro[:10]:
            ap = e.get("aparat") or e.get("denumire") or "-"
            cam = e.get("camera") or "-"
            brand = e.get("brand_detectat") or e.get("brand") or "-"
            model = e.get("model_sau_serie") or e.get("gama_brand") or e.get("model") or ""
            brand_full = f"{brand} ({model})" if model else brand
            # "Premium" and "Excelentă" as defaults graded appliances nobody had
            # looked at; an unknown grade is now shown as unknown.
            nivel = e.get("clasa_pret") or e.get("nivel_pret") or "-"
            p_n = e.get("pret_estimat_nou_eur") or e.get("pret_nou_estimat_eur") or 0
            p_a = e.get("valoare_piata_actuala_eur") or e.get("valoare_actuala_eur") or 0
            stare = e.get("stare") or e.get("uzura") or "-"

            randuri_cat_el.append([
                ap,
                cam,
                brand_full,
                nivel,
                f"~{p_n:,.0f} €",
                f"~{p_a:,.0f} €",
                stare,
            ])
        # "Stare" is a sentence, not a word: at 45 pt it wrapped one syllable
        # per line ("im / pecabile"). The money columns are the narrow ones --
        # they hold six characters and never wrap.
        poveste.append(_formateaza_tabel(randuri_cat_el, stiluri, [88, 52, 105, 48, 48, 48, 98]))
        poveste.append(Spacer(1, 10))

    # =========================================================================
    # 7. PROFIL DEZVOLTATOR, CONSTRUCTOR & DUE DILIGENCE FINANCIAR
    # =========================================================================
    dev_specs = date_proprietate.get("specificatii_dezvoltator") or {}
    targetare_data = date_proprietate.get("audit_targetare") or date_proprietate.get("targetare_financiar") or {}

    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Profil Dezvoltator, Constructor & Due Diligence Financiar"),
    ]))

    dezvoltator_nume = dev_specs.get("dezvoltator") or date_proprietate.get("dezvoltator")
    constructor_nume = dev_specs.get("constructor") or date_proprietate.get("constructor")

    if dev_specs or dezvoltator_nume or constructor_nume:
        poveste.append(Paragraph("<b>Specificații Tehnice Clădire & Materiale de Construcție</b>", stiluri["SectiuneH3"]))
        randuri_dev_specs = [
            ["Element Tehnic Proiectat", "Specificație Execuție & Calitate"],
            ["Dezvoltator Imobiliar", str(dezvoltator_nume or "Nespecificat în anunț")],
            ["Antreprenor General (Constructor)", str(constructor_nume or "Nespecificat în anunț")],
            ["Regim de Înălțime", str(dev_specs.get("regim_inaltime") or date_proprietate.get("etaj") or "Nespecificat")],
            ["Structură de Rezistență", str(dev_specs.get("structura_rezistenta") or "Cadre beton armat")],
            ["Închideri & Compartimentări", str(dev_specs.get("inchideri_pereti") or dev_specs.get("zidarie") or "Cărămidă / Ytong")],
            ["Certificare Ecologică & Energetică", str(dev_specs.get("certificare_verde") or dev_specs.get("certificare_energetica") or "Clasa A")],
            ["Termen Recepție Lucrări", str(dev_specs.get("termen_finalizare") or date_proprietate.get("an_constructie") or "Recepționat la termen")],
        ]
        poveste.append(_formateaza_tabel(randuri_dev_specs, stiluri, [160, 327]))
        poveste.append(Spacer(1, 8))

    # Date Targetare.ro polimorfice (suportă date directe sau imbricate sub date_firma)
    firma = targetare_data.get("date_firma") or {}
    analiza_f = firma.get("analiza_financiara") or {}

    cui = targetare_data.get("cui") or firma.get("cui") or "N/A"
    denumire = targetare_data.get("denumire") or firma.get("denumire") or dezvoltator_nume or "Companie Nespecificată"
    an_inf = targetare_data.get("an_infiintare") or firma.get("an_infiintare") or "-"
    stare_f = targetare_data.get("stare") or firma.get("stare") or "ACTIV"
    scor_bon = (
        targetare_data.get("scor_bonitate")
        or analiza_f.get("scor_sanatate_financiara")
        or targetare_data.get("scor_sanatate_financiara")
    )
    risc_insolv = (
        targetare_data.get("calificativ_risc")
        or analiza_f.get("nivel_risc_insolventa")
        or "Risc Scăzut"
    )
    alerta_spv = targetare_data.get("alerta_spv") or "Fără profil critic SPV identificat."
    ang = targetare_data.get("numar_angajati") or firma.get("angajati") or 0
    grad_indat = targetare_data.get("grad_indatorare") or analiza_f.get("grad_indatorare_procent") or 0
    if isinstance(grad_indat, float) and grad_indat <= 1.0:
        grad_indat = round(grad_indat * 100, 1)

    ca_ron = targetare_data.get("cifra_afaceri_ron") or firma.get("cifra_afaceri") or 0
    profit_ron = targetare_data.get("profit_net_ron") or firma.get("profit_net") or 0
    datorii_ron = targetare_data.get("datorii_totale_ron") or firma.get("datorii") or 0
    capitaluri_ron = targetare_data.get("capitaluri_proprii_ron") or firma.get("capitaluri_proprii") or 0

    targetare_ok = (
        targetare_data.get("status") == "success"
        and targetare_data.get("disponibil") is not False
        and (scor_bon is not None or ca_ron > 0)
    )

    if not targetare_ok:
        poveste.append(
            _creeaza_card_apel(
                "<b>Due diligence financiar indisponibil:</b> "
                + (targetare_data.get("motiv") or "Dezvoltatorul nu a fost menționat în anunț sau datele fiscale nu sunt publice."),
                stiluri,
                titlu="DATE FINANCIARE INDISPONIBILE",
                culoare_accent=GOOGLE_MUTED,
                culoare_fundal=GOOGLE_CARD_BG,
            )
        )
        poveste.append(Spacer(1, 10))
    else:
        accent_t = GOOGLE_GREEN if (scor_bon and scor_bon >= 7.5) else (GOOGLE_AMBER if (scor_bon and scor_bon >= 5.0) else GOOGLE_RED)
        tint_t = TINT_GREEN if (scor_bon and scor_bon >= 7.5) else (TINT_AMBER if (scor_bon and scor_bon >= 5.0) else TINT_RED)

        text_t = (
            f"<b>Companie:</b> {denumire} (CUI: {cui}, Înființare: {an_inf}) • <b>Stare:</b> {stare_f}<br/>"
            f"<b>Scor Bonitate Financiară:</b> <b>{scor_bon}/10</b> ({risc_insolv}) • "
            f"<b>Grad de Îndatorare:</b> {grad_indat}% • <b>Angajați:</b> {ang}<br/>"
            f"<b>Analiză SPV & Soliditate:</b> {alerta_spv}"
        )
        poveste.append(_creeaza_card_apel(text_t, stiluri, titlu="DUE DILIGENCE BONITATE FINANCIARĂ (TARGETARE.RO / ANAF)", culoare_accent=accent_t, culoare_fundal=tint_t))
        poveste.append(Spacer(1, 8))

        randuri_fin = [
            ["Indicator Financiar Cheie", "Valoare Înregistrată (Ultimul Bilanț)"],
            ["Cifră de Afaceri Anuală", f"{ca_ron:,.0f} RON" if ca_ron else "N/A"],
            ["Profit Net Anual", f"{profit_ron:,.0f} RON" if profit_ron else "N/A"],
            ["Datorii Totale Bilanțiere", f"{datorii_ron:,.0f} RON" if datorii_ron else "N/A"],
            ["Capitaluri Proprii", f"{capitaluri_ron:,.0f} RON" if capitaluri_ron else "N/A"],
            ["Număr Mediu de Angajați", str(ang) if ang is not None else "N/A"],
            ["Grad de Îndatorare Bilanțier", f"{grad_indat}%"],
        ]
        poveste.append(_formateaza_tabel(randuri_fin, stiluri, [237, 250]))
        poveste.append(Spacer(1, 10))

    # =========================================================================
    # 8. REPUTAȚIE REZIDENȚIALĂ & RECENZII GOOGLE MAPS
    # =========================================================================
    recenzii_data = date_proprietate.get("recenzii_google") or {}
    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Reputație Rezidențială & Recenzii Google Maps"),
    ]))

    loc_rec = recenzii_data.get("locatie") or {}
    analiza_r = loc_rec.get("analiza_sentiment") or {}

    rating_g = recenzii_data.get("rating_mediu") or loc_rec.get("rating_global")
    tot_rec = recenzii_data.get("numar_recenzii") or loc_rec.get("total_recenzii")
    scor_rep = analiza_r.get("scor_reputatie") or (round(rating_g * 2, 1) if rating_g else None)
    calif_rep = analiza_r.get("calificativ_reputatie") or ("Pozitivă" if (rating_g and rating_g >= 4.0) else "Moderat")
    sfat_c = (
        recenzii_data.get("recomandare_cumparator")
        or analiza_r.get("recomandare_cumparator")
        or "Verificați aspectele contractuale și de administrare la vizionare."
    )

    recenzii_ok = (
        isinstance(recenzii_data, dict)
        and recenzii_data.get("status") == "success"
        and recenzii_data.get("disponibil") is not False
        and (rating_g is not None or tot_rec is not None)
    )

    if not recenzii_ok:
        poveste.append(
            _creeaza_card_apel(
                "<b>Recenzii indisponibile:</b> "
                + (recenzii_data.get("motiv") or "Nu au fost identificate recenzii Google Maps pentru acest imobil."),
                stiluri,
                titlu="REPUTAȚIE INDISPONIBILĂ",
                culoare_accent=GOOGLE_MUTED,
                culoare_fundal=GOOGLE_CARD_BG,
            )
        )
        poveste.append(Spacer(1, 10))
    else:
        text_rec = (
            f"<b>Scor Comunitate & Reputație:</b> <b>{scor_rep}/10</b> ({calif_rep}) • "
            f"<b>Rating Google Maps:</b> <b>{rating_g}/5</b> din <b>{tot_rec} recenzii</b> validate.<br/>"
            f"<b>Sfat & Recomandare pentru Cumpărător:</b> {sfat_c}"
        )
        poveste.append(_creeaza_card_apel(text_rec, stiluri, titlu="SENTIMENT COMUNITATE & FEEDBACK REZIDENȚI", culoare_accent=GOOGLE_BLUE))
        poveste.append(Spacer(1, 8))

        pf_rec = recenzii_data.get("puncte_forte") or analiza_r.get("puncte_forte_apreciate") or []
        pr_rec = recenzii_data.get("probleme_recurente") or analiza_r.get("probleme_reclamate_frecvent") or []
        if pf_rec or pr_rec:
            linii_rev = [[
                Paragraph("<b>Ce Apreciază Vecinii (Puncte Forte)</b>", stiluri["TabelHeader"]),
                Paragraph("<b>Probleme Semnalate Recurent (Semnale de Atenție)</b>", stiluri["TabelHeader"]),
            ]]
            m_len = max(len(pf_rec), len(pr_rec))
            for i in range(m_len):
                p1 = f"• {_txt(pf_rec[i])}" if i < len(pf_rec) else ""
                p2 = f"• {_txt(pr_rec[i])}" if i < len(pr_rec) else ""
                linii_rev.append([
                    Paragraph(p1, stiluri["TabelCelula"]),
                    Paragraph(p2, stiluri["TabelCelula"]),
                ])
            tab_rev = Table(linii_rev, colWidths=[243, 244])
            tab_rev.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (0, 0), GOOGLE_BLUE),
                ("BACKGROUND", (1, 0), (1, 0), GOOGLE_AMBER),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, GOOGLE_BORDER),
            ]))
            poveste.append(tab_rev)
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # 9. CONTEXTUL PIEȚEI, COSTURI DE DEȚINERE & REGISTRU DE RISCURI
    # =========================================================================
    an_piata = date_proprietate.get("analiza_piata") or {}
    cost_det = date_proprietate.get("costuri_detinere") or {}
    cost_tranz = date_proprietate.get("costuri_tranzactionare") or {}
    esg_data = date_proprietate.get("esg") or {}
    riscuri_lista = date_proprietate.get("riscuri") or []

    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Contextul Pieței, Costuri de Deținere & Registru de Riscuri"),
    ]))

    # 9.1 Dinamica Pieței & Cea mai bună utilizare
    poveste.append(Paragraph("<b>Dinamica Pieței Rezidențiale & Analiza Micro-Zonei</b>", stiluri["SectiuneH3"]))
    # Nothing here is substituted. The dossier used to print +6,2%/an, 3,5 luni
    # and 14 oferte for every property, next to figures that were real -- an
    # unmeasured indicator now says so instead of borrowing a plausible number.
    zona_p = an_piata.get("zona") or adresa or "Zonă Urbană"
    p_med = an_piata.get("pret_mediu_zona_eur_mp") or (round(pret_mp) if pret_mp else None)
    var_an = an_piata.get("variatie_anuala_procent")
    exp_luni = an_piata.get("timp_mediu_expunere_luni")
    oferta_sim = an_piata.get("oferta_activa_similara")
    tendinta = an_piata.get("tendinta")
    com_piata = an_piata.get("comentariu") or an_piata.get("motiv") or ""

    _ND = "Nedeterminat"
    randuri_piata = [
        ["Indicator de Micro-Piață", "Valoare Măsurată", "Impact Asupra Negocierii"],
        ["Zonă / Micro-Piață", str(zona_p), "Segment rezidențial de referință"],
        [
            "Preț Mediu Unitar Zonă",
            f"{p_med:,.0f} EUR/mp" if p_med else _ND,
            "Barieră de referință a cumpărătorilor",
        ],
        [
            "Variație Anuală de Preț",
            f"{var_an:+.1f}% / an" if var_an is not None else _ND,
            "Cere o serie de timp, indisponibilă dintr-un instantaneu al ofertei",
        ],
        [
            "Timp Mediu de Expunere",
            f"{exp_luni} luni" if exp_luni is not None else _ND,
            "Viteza de absorbție pe segmentul curent",
        ],
        [
            "Ofertă Activă Concurentă",
            f"{oferta_sim} proprietăți" if oferta_sim else _ND,
            "Nivelul de concurență din proximitate",
        ],
        [
            "Tendință Generală Piață",
            str(tendinta) if tendinta else _ND,
            "Poziția cumpărătorului în negociere",
        ],
    ]
    poveste.append(_formateaza_tabel(randuri_piata, stiluri, [150, 110, 227]))
    if com_piata:
        poveste.append(Paragraph(f"<i>Analiză micro-zonă: {_txt(com_piata)}</i>", stiluri["CorpMuted"]))
    poveste.append(Spacer(1, 8))

    hbu = date_proprietate.get("cea_mai_buna_utilizare") or "Utilizare rezidențială exclusivă conform destinației autorizate (Highest & Best Use - SEV 100)."
    poveste.append(_creeaza_card_apel(hbu, stiluri, titlu="CEA MAI BUNĂ UTILIZARE (HIGHEST & BEST USE - SEV 100)", culoare_accent=GOOGLE_BLUE, culoare_fundal=GOOGLE_CARD_BG))
    poveste.append(Spacer(1, 8))

    # 9.2 Costuri de deținere & Tranzacționare
    poveste.append(Paragraph("<b>Costuri Anuale de Deținere (Holding Costs) & Costuri de Tranzacție</b>", stiluri["SectiuneH3"]))

    # Each line is now a computed post with its own legal basis, or an explicit
    # "indisponibil" -- maintenance used to be the surface times a constant and
    # was printed as if it had been read off a bill.
    randuri_costuri = [["Post de Cheltuială", "Cost Estimat", "Temei / Detalii"]]

    # Two shapes reach this table. `posturi` is the itemised one the costs
    # module emits; the audit payload carries a flat dict of named amounts
    # instead, and that one used to fall straight through -- the section
    # printed its heading and a transaction total, with every holding cost it
    # promised silently missing.
    _POSTURI_PLATE = [
        ("intretinere_lunara_eur", "Întreținere & Administrare", 12, "Cotă lunară de întreținere, anualizată"),
        ("fond_reparatii_lunar_eur", "Fond de Reparații", 12, "Cotă lunară la fondul de reparații, anualizată"),
        ("impozit_anual_eur", "Impozit pe Clădire & Teren", 1, "Impozit local anual (Codul Fiscal, Titlul IX)"),
        ("asigurare_anuala_eur", "Asigurare Obligatorie & Facultativă", 1, "PAD obligatoriu (Legea 260/2008) plus poliță facultativă"),
    ]
    if not cost_det.get("posturi"):
        for cheie, eticheta, multiplicator, temei in _POSTURI_PLATE:
            suma = cost_det.get(cheie)
            if not suma:
                continue
            anual = suma * multiplicator
            detaliu = (
                f"{temei} ({suma:,.0f} EUR/lună)" if multiplicator == 12 else temei
            )
            randuri_costuri.append([eticheta, f"~{anual:,.0f} EUR/an", detaliu])
        if total_det := cost_det.get("total_anual_eur"):
            randuri_costuri.append([
                "TOTAL COSTURI ANUALE DE DEȚINERE",
                f"<b>~{total_det:,.0f} EUR/an</b>",
                "Sumă recurentă, cât timp proprietatea este deținută",
            ])

    for post in cost_det.get("posturi") or []:
        minim, maxim = post.get("minim_eur"), post.get("maxim_eur")
        if minim is None:
            valoare = "Indisponibil"
            detaliu = post.get("motiv_indisponibil") or post.get("temei") or "—"
        elif minim == maxim:
            valoare = f"~{minim:,.0f} EUR/an"
            detaliu = post.get("temei") or "—"
        else:
            valoare = f"{minim:,.0f} – {maxim:,.0f} EUR/an"
            detaliu = post.get("temei") or "—"
        randuri_costuri.append([str(post.get("componenta") or "—"), valoare, str(detaliu)])

    # The transaction side arrives flat too, as percentages of the price.
    _POSTURI_TRANZ = [
        ("onorariu_notarial_procent", "Onorariu Notarial", "Procent din prețul de achiziție, conform grilei notariale"),
        ("taxa_intabulare_procent", "Taxă de Intabulare (ANCPI)", "Tarif ANCPI pentru înscrierea în cartea funciară"),
        ("comision_agentie_procent", "Comision Agenție", "Procent din prețul de achiziție, dacă tranzacția e intermediată"),
    ]
    if not cost_tranz.get("posturi") and pret:
        for cheie, eticheta, temei in _POSTURI_TRANZ:
            procent = cost_tranz.get(cheie)
            if not procent:
                continue
            randuri_costuri.append([
                eticheta,
                f"~{pret * procent / 100:,.0f} EUR",
                f"{temei} ({procent}%)",
            ])

    for post in (cost_tranz.get("posturi") or []):
        minim, maxim = post.get("minim_eur"), post.get("maxim_eur")
        if minim is None:
            continue
        valoare = (
            f"~{minim:,.0f} EUR" if minim == maxim else f"{minim:,.0f} – {maxim:,.0f} EUR"
        )
        randuri_costuri.append(
            [str(post.get("componenta") or "—"), valoare, str(post.get("temei") or "—")]
        )

    total_tranz = cost_tranz.get("total_estimat_eur")
    if total_tranz:
        randuri_costuri.append([
            "TOTAL COSTURI DE TRANZACȚIONARE",
            f"<b>~{total_tranz:,.0f} EUR</b>",
            "Sumă unică, la semnare",
        ])
    if len(randuri_costuri) == 1:
        randuri_costuri.append([
            "Costuri conexe",
            "Indisponibil",
            "Fără un preț de referință nu se pot calcula taxele de transfer.",
        ])

    poveste.append(_formateaza_tabel(randuri_costuri, stiluri, [180, 110, 197]))
    if nota_tranz := cost_tranz.get("nota"):
        poveste.append(Paragraph(f"<i>{_txt(nota_tranz)}</i>", stiluri["CorpMuted"]))
    if motiv_det := cost_det.get("motiv"):
        poveste.append(Paragraph(f"<i>{_txt(motiv_det)}</i>", stiluri["CorpMuted"]))
    poveste.append(Spacer(1, 8))

    # Bugetul consolidat: prețul nu este bugetul.
    buget = date_proprietate.get("buget_consolidat") or {}
    if buget.get("disponibil"):
        poveste.append(
            Paragraph("<b>Bugetul Consolidat al Proiectului</b>", stiluri["SectiuneH3"])
        )
        randuri_buget = [["Componentă", "Interval Estimat", "Temei"]]
        for post in buget.get("posturi") or []:
            minim, maxim = post.get("minim_eur"), post.get("maxim_eur")
            if minim is None:
                continue
            valoare = (
                f"~{minim:,.0f} EUR" if minim == maxim else f"{minim:,.0f} – {maxim:,.0f} EUR"
            )
            randuri_buget.append(
                [str(post.get("componenta")), valoare, str(post.get("temei") or "—")]
            )
        randuri_buget.append([
            "COST TOTAL CONSOLIDAT",
            f"<b>{buget.get('total_minim_eur'):,.0f} – "
            f"{buget.get('total_maxim_eur'):,.0f} EUR</b>",
            "Prețul plus tot ce urmează după semnare",
        ])
        poveste.append(_formateaza_tabel(randuri_buget, stiluri, [170, 120, 197]))
        poveste.append(Spacer(1, 8))

    # 9.3 Profil ESG & Sustenabilitate
    poveste.append(Paragraph("<b>Profil ESG & Performanță Energetică / Climatică</b>", stiluri["SectiuneH3"]))
    # An energy class, a green certification and a seismic verdict are documents,
    # not inferences. The dossier used to assert class A, 115,4 kWh/mp/an and a
    # BREEAM certification for properties nobody had a certificate for.
    _NEDECLARAT = "Nedeclarat în anunț"
    clasa_en = esg_data.get("clasa_energetica") or date_proprietate.get("clasa_energetica")
    consum_kwh = esg_data.get("consum_specific_kwh_mp_an")
    certif_v = esg_data.get("certificare") or (
        date_proprietate.get("specificatii_dezvoltator", {}) or {}
    ).get("certificare_verde")
    risc_clim = esg_data.get("riscuri_climatice")
    # The seismic row used to be an instruction to go and check. The dossier now
    # carries the answer when the address could be resolved, so the row reports
    # it -- and still says what the register does not prove when it does not.
    rs = date_proprietate.get("risc_seismic") or {}
    if rs.get("concludent"):
        risc_seismic_txt = str(rs.get("eticheta"))
        risc_seismic_sursa = (
            f"Registrul AMCCRS — {rs.get('adresa_registru')} "
            f"(O.G. 20/1994, Legea nr. 212/2022)"
        )
    elif rs.get("verificat"):
        risc_seismic_txt = "Neconcludent"
        risc_seismic_sursa = str(rs.get("rezumat"))
    else:
        risc_seismic_txt = str(risc_clim) if risc_clim else "Neverificat"
        risc_seismic_sursa = "Evidențele AMCCRS pentru adresa exactă (Legea nr. 212/2022)"
    social_txt = esg_data.get("social")
    guvern_txt = esg_data.get("guvernanta")

    randuri_esg = [
        ["Pilon ESG", "Performanță Raportată", "Sursa / Document Necesar"],
        [
            "Mediu (Eficiență Energetică)",
            f"Clasa {clasa_en}" if clasa_en else _NEDECLARAT,
            (
                f"Consum specific: {consum_kwh} kWh/mp/an"
                if consum_kwh
                else "Certificatul de performanță energetică, obligatoriu la vânzare"
            ),
        ],
        [
            "Certificare Ecologică Verde",
            str(certif_v) if certif_v else _NEDECLARAT,
            "Certificatul emis de organismul de certificare",
        ],
        [
            "Risc Seismic",
            risc_seismic_txt,
            risc_seismic_sursa,
        ],
        [
            "Social & Comunitate",
            str(social_txt) if social_txt else _NEDECLARAT,
            "Constatare la vizionare",
        ],
        [
            "Guvernanță Asociație",
            str(guvern_txt) if guvern_txt else _NEDECLARAT,
            "Adeverință de la asociația de proprietari",
        ],
    ]
    poveste.append(_formateaza_tabel(randuri_esg, stiluri, [150, 140, 197]))
    poveste.append(Spacer(1, 8))

    # 9.4 Registru Complet de Riscuri
    poveste.append(Paragraph("<b>Registru Complet de Riscuri & Măsuri de Mitigare</b>", stiluri["SectiuneH3"]))
    if not riscuri_lista:
        # No invented probabilities. When no red flag was raised by the evidence,
        # the register says exactly that rather than listing three generic risks
        # with fabricated likelihoods next to them.
        riscuri_lista = [
            {
                "risc": "Niciun semnal de risc ridicat din datele analizate automat",
                "probabilitate": "—",
                "impact": "—",
                "mitigare": (
                    "Analiza automată nu înlocuiește inspecția: extrasul CF, adeverința "
                    "asociației și proba instalațiilor rămân obligatorii înainte de "
                    "antecontract."
                ),
            }
        ]
    randuri_risc = [["Risc Identificat", "Probabilitate", "Impact", "Măsură Concretă de Reducere / Mitigare"]]
    for r in riscuri_lista:
        randuri_risc.append([
            str(r.get("risc") or "-"),
            str(r.get("probabilitate") or "Medie"),
            str(r.get("impact") or "Mediu"),
            str(r.get("mitigare") or "-"),
        ])
    poveste.append(_formateaza_tabel(randuri_risc, stiluri, [120, 65, 65, 237]))
    poveste.append(Spacer(1, 10))

    # =========================================================================
    # 10. CHECKLIST TEHNIC DE RECEPȚIE & VERIFICARE ACTE
    # =========================================================================
    chk_data = date_proprietate.get("receptie_checklist") or date_proprietate.get("checklist_receptie") or {}
    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Checklist Tehnic pentru Recepție & Verificare Acte"),
    ]))

    if isinstance(chk_data, dict) and chk_data:
        randuri_chk = [["Etapă / Punct de Verificare", "Elemente Obligatorii / Constatare Tehnică", "Status / Acțiune"]]
        etichete_chk = {
            "conformitate_carte_tehnica": "Carte Tehnică Construcție",
            "garantie_legala_structura": "Garanție Legală Structură",
            "garantie_finisaje_echipamente": "Garanție Finisaje & Instalații",
            "cadastru_si_intabulare": "Cadastru & Extras Carte Funciară",
            "certificat_energetic": "Certificat Performanță Energetică",
        }
        for k, v in chk_data.items():
            titlu_k = etichete_chk.get(k, k.replace("_", " ").capitalize())
            randuri_chk.append([titlu_k, str(v), "De verificat"])
    elif isinstance(chk_data, (list, tuple)) and chk_data:
        randuri_chk = [["Nr.", "Element Obligatoriu de Verificare la Vizionare & Antecontract", "Status Recomandat"]]
        for idx, item in enumerate(chk_data, 1):
            randuri_chk.append([str(idx), str(item), "Obligatoriu"])
    else:
        randuri_chk = [
            ["Etapă / Punct de Verificare", "Elemente Obligatorii de Constatat", "Status"],
            ["Acte Juridice", "Extras CF de informare curat (fără sarcini)", "Obligatoriu"],
            ["Carte Tehnică", "Proiect rezistență, PV recepție la terminarea lucrărilor", "Obligatoriu"],
            ["Instalații Sanitare", "Probe presiune, contorizare apă/gaz", "La recepție"],
            ["Instalații Electrice", "Tablou siguranțe, împământare funcțională", "La recepție"],
            ["Izolație & Ferestre", "Etanșeitate garnituri ferestre tripan", "La vizionare"],
        ]

    tab_chk = _formateaza_tabel(randuri_chk, stiluri, [120, 277, 90])
    poveste.append(tab_chk)
    poveste.append(Spacer(1, 10))

    # =========================================================================
    # 11. METODOLOGIE, IPOTEZE LIMITATIVE & SURSE DE DATE
    # =========================================================================
    metodologie = date_proprietate.get("metodologie") or {}
    ipoteze = date_proprietate.get("ipoteze_limitative") or []

    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=GOOGLE_BORDER, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Metodologie, Ipoteze Limitative & Surse de Date"),
    ]))

    randuri_met = [
        ["Termen de Referință", "Definiție & Standard Aplicat"],
        ["Standard de Evaluare", str(metodologie.get("standard") or "SEV 2025 · GEV 630 · SEV 106 §30.6")],
        ["Tipul Valorii Estimate", str(metodologie.get("tip_valoare") or "Valoare de piață, conform SEV 102")],
        ["Data Evaluării", str(metodologie.get("data_evaluarii") or "La zi")],
        ["Monedă de Referință", str(metodologie.get("moneda") or moneda)],
        ["Client & Destinatar", str(metodologie.get("client") or "Beneficiarul analizei pre-achiziție")],
        ["Utilizare Desemnată", str(metodologie.get("utilizare_desemnata") or "Fundamentarea deciziei de achiziție și negociere")],
    ]
    poveste.append(_formateaza_tabel(randuri_met, stiluri, [160, 327]))
    poveste.append(Spacer(1, 8))

    evaluator_text = str(
        metodologie.get("evaluator")
        or "Analiză automată asistată de Gemini AI. Prezentul document nu înlocuiește un raport de evaluare autorizat ANEVAR."
    )
    amploare_text = str(
        metodologie.get("amploare")
        or "Fără inspecție fizică de către un membru autorizat. Analiză bazată exclusiv pe date publice și imagini."
    )
    # The label used to be "NEÎNDEPLINIT / DISCLAIMER EVALUATOR", while the
    # value it introduces already opens with "NEÎNDEPLINIT — ...". The row read
    # as a stutter; the label now just names the field.
    disclaimer_tot = (
        f"<b>CALITATEA EVALUATORULUI:</b> {evaluator_text}<br/>"
        f"<b>AMPLOAREA INVESTIGAȚIEI:</b> {amploare_text}"
    )
    poveste.append(_creeaza_card_apel(disclaimer_tot, stiluri, titlu="CLAUZĂ DE EXONERARE & NECONFORMITATE DECLARATĂ", culoare_accent=GOOGLE_AMBER, culoare_fundal=TINT_AMBER))
    poveste.append(Spacer(1, 8))

    surse = metodologie.get("surse_date") or [
        "Platforme imobiliare online (anunțuri active de vânzare și arhive)",
        "Google Maps API (Street View 360°, Places POI, Geocoding)",
        "Targetare.ro / Portalul ANAF (date fiscale de bilanț și bonitate)",
        "Standardele ANEVAR SEV 2025 (GEV 630 Evaluarea bunurilor imobiliare)",
    ]
    poveste.append(Paragraph("<b>Surse de Date Consultate în Audit</b>", stiluri["SectiuneH3"]))
    randuri_surse = [["Nr.", "Sursă de Informație și Verificare"]]
    for idx, s in enumerate(surse, 1):
        randuri_surse.append([str(idx), str(s)])
    poveste.append(_formateaza_tabel(randuri_surse, stiluri, [40, 447]))
    poveste.append(Spacer(1, 8))

    if not ipoteze:
        ipoteze = [
            "Titlul de proprietate este valabil, netransferabil și liber de sarcini sau ipoteci ascunse.",
            "Suprafețele utile declarate în anunț corespund releveului cadastral oficial.",
            "Nu există vicii structurale sau de teren nedeclarate de către vânzător.",
            "Costurile de remediere a deficiențelor sunt estimative și necesită deviz ferm de execuție.",
        ]
    poveste.append(Paragraph("<b>Ipoteze Limitative Specifice</b>", stiluri["SectiuneH3"]))
    randuri_ip = [["Nr.", "Ipoteză Limitată Luată în Calcul"]]
    for idx, ip in enumerate(ipoteze, 1):
        randuri_ip.append([str(idx), str(ip)])
    poveste.append(_formateaza_tabel(randuri_ip, stiluri, [40, 447]))
    poveste.append(Spacer(1, 10))

    # =========================================================================
    # 12. CONCLUZIE FINALĂ & STRATEGIE DE NEGOCIERE
    # =========================================================================
    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=1, color=GOOGLE_BLUE, spaceBefore=4, spaceAfter=8),
        _titlu_sectiune("Concluzie Finală & Strategie de Negociere"),
    ]))

    # Scara de ofertare. Five numbers decided before the first phone call: an
    # offer improvised at the table is the one that overpays.
    strategie = date_proprietate.get("strategie_negociere") or {}
    scara = strategie.get("scara") or {}
    if strategie.get("disponibil") and scara:
        if strategie.get("abandon_recomandat"):
            poveste.append(_creeaza_card_apel(
                strategie.get("motiv_abandon") or
                "Condițiile identificate recomandă abandonarea tranzacției.",
                stiluri,
                titlu="ABANDON RECOMANDAT",
                culoare_accent=GOOGLE_RED,
                culoare_fundal=TINT_RED,
            ))
            poveste.append(Spacer(1, 8))

        poveste.append(Paragraph("<b>Scara de Ofertare</b>", stiluri["SectiuneH3"]))

        def _eur_or_dash(valoare: Any) -> str:
            return f"{valoare:,.0f} {moneda}" if valoare else "—"

        contra = scara.get("contraoferta_probabila_eur") or []
        randuri_scara = [
            ["Parametru Financiar", "Valoare", "Rol în Negociere"],
            [
                "Preț listat",
                _eur_or_dash(scara.get("pret_listat_eur")),
                "Ancora publică a vânzătorului",
            ],
            [
                "Valoare tehnică estimată",
                _eur_or_dash(scara.get("valoare_estimata_eur")),
                "Rezultatul grilei de comparabile",
            ],
            [
                "Ofertă inițială recomandată",
                _eur_or_dash(scara.get("oferta_initiala_eur")),
                "Punct de ancorare, transmis în scris",
            ],
            [
                "Contraofertă probabilă",
                f"{contra[0]:,.0f} – {contra[1]:,.0f} {moneda}" if len(contra) == 2 else "—",
                "Reacția anticipată a vânzătorului",
            ],
            [
                "Preț țintă",
                _eur_or_dash(scara.get("pret_tinta_eur")),
                "Punctul de echilibru al tranzacției",
            ],
            [
                "Preț maxim acceptabil",
                _eur_or_dash(scara.get("pret_maxim_acceptabil_eur")),
                "Plafon admis doar cu avantaje care elimină costuri viitoare",
            ],
            [
                "Prag de abandon (walk-away)",
                _eur_or_dash(scara.get("walk_away_eur")),
                "Peste acest nivel tranzacția se abandonează",
            ],
        ]
        poveste.append(_formateaza_tabel(randuri_scara, stiluri, [160, 110, 217]))

        concesii_list = scara.get("concesii_descrescatoare_eur") or []
        if concesii_list:
            pasi = _txt(" → ".join(f"{c:,.0f}" for c in concesii_list))
            poveste.append(Paragraph(
                f"<i>Model de concesii descrescătoare, de la oferta inițială: {pasi} "
                f"{moneda}. Pași egali semnalează vânzătorului o marjă neepuizată.</i>",
                stiluri["CorpMuted"],
            ))
        if scara.get("walk_away_limitat_de_buget"):
            poveste.append(Paragraph(
                "<i>Pragul de abandon este impus de bugetul consolidat, nu de valoarea "
                "imobilului.</i>",
                stiluri["CorpMuted"],
            ))
        poveste.append(Spacer(1, 8))

        profil = strategie.get("profil_vanzator") or {}
        if profil:
            poveste.append(
                Paragraph("<b>Profilul Vânzătorului & Tactica Adaptată</b>", stiluri["SectiuneH3"])
            )
            randuri_profil = [
                ["Aspect", "Constatare"],
                ["Profil identificat", str(profil.get("profil") or "—")],
                ["Semnale din anunț", ", ".join(profil.get("semnale_detectate") or []) or "—"],
                ["Ce funcționează", str(profil.get("tactica_eficienta") or "—")],
                ["Ce nu funcționează", str(profil.get("erori_de_evitat") or "—")],
                ["Argument principal", str(profil.get("argument_principal") or "—")],
            ]
            poveste.append(_formateaza_tabel(randuri_profil, stiluri, [120, 367]))
            poveste.append(Spacer(1, 8))

        parghii = strategie.get("parghii") or []
        if parghii:
            poveste.append(Paragraph(
                "<b>Pârghii Tehnice de Reducere a Prețului</b>", stiluri["SectiuneH3"]
            ))
            randuri_parghii = [["Problemă Constatată", "Reducere Justificată", "Argument"]]
            for parghie in parghii:
                reducere = parghie.get("reducere_justificata_eur") or []
                randuri_parghii.append([
                    str(parghie.get("problema") or "—"),
                    f"{reducere[0]:,.0f} – {reducere[1]:,.0f} {moneda}"
                    if len(reducere) == 2 else "—",
                    str(parghie.get("argument") or "—"),
                ])
            poveste.append(_formateaza_tabel(randuri_parghii, stiluri, [150, 100, 237]))
            poveste.append(Spacer(1, 8))

        if regula := strategie.get("regula_decizionala"):
            poveste.append(_creeaza_card_apel(
                regula,
                stiluri,
                titlu="REGULA DECIZIONALĂ",
                culoare_accent=GOOGLE_NAVY,
                culoare_fundal=TINT_BLUE,
            ))
            poveste.append(Spacer(1, 8))

        if reguli := strategie.get("reguli_de_aur"):
            poveste.append(Paragraph(
                "<b>Reguli de Aur ale Achiziției</b>", stiluri["SectiuneH3"]
            ))
            randuri_reguli = [["Nr.", "Regulă"]]
            for index, regula in enumerate(reguli, 1):
                randuri_reguli.append([str(index), str(regula)])
            poveste.append(_formateaza_tabel(randuri_reguli, stiluri, [30, 457]))
            poveste.append(Spacer(1, 8))

        if sursa_strategie := strategie.get("sursa"):
            poveste.append(Paragraph(
                f"<i>{_txt(sursa_strategie)}</i>", stiluri["CorpMuted"]
            ))
            poveste.append(Spacer(1, 8))

    if not evaluare_disponibila or val_piata is None:
        concluzie_text = (
            "<b>Nu se poate formula o strategie de negociere bazată pe cifre:</b> "
            "evaluarea de piață nu a putut fi calculată pentru acest imobil "
            f"({eval_anevar.get('motiv') or 'eșantion de comparabile insuficient'}). "
            "Solicitați o evaluare ANEVAR autorizată înainte de a face o ofertă fermă și "
            "cereți dezvoltatorului fișa tehnică completă și garanțiile contractuale."
        )
        accent_concluzie, tint_concluzie = GOOGLE_MUTED, GOOGLE_CARD_BG
    else:
        prag_jos = (
            scara.get("oferta_initiala_eur")
            or (val_min if val_min is not None else round(val_piata * 0.95))
        )
        tinta_card = scara.get("pret_tinta_eur") or val_piata
        walk = scara.get("walk_away_eur")
        interval_negociere = (
            f"Recomandăm începerea negocierii de la <b>{prag_jos:,.0f} {moneda}</b>, "
            f"cu o țintă de achiziție la <b>{tinta_card:,.0f} {moneda}</b> "
            f"(economie argumentabilă de <b>~{marja_eur:,.0f} {moneda}</b>). "
        )
        if walk:
            interval_negociere += (
                f"Peste <b>{walk:,.0f} {moneda}</b> tranzacția se abandonează. "
            )
        if scor_gen is None:
            deschidere = "Evaluarea de piață este disponibilă pe baza comparabilelor calificate. "
            accent_concluzie, tint_concluzie = GOOGLE_BLUE, TINT_BLUE
        elif scor_gen >= 7.5:
            deschidere = f"Evaluare globală: <b>{scor_gen}/10 — {calif_gen}</b>. Proprietate cu risc tehnic și juridic controlat. "
            accent_concluzie, tint_concluzie = GOOGLE_GREEN, TINT_GREEN
        else:
            deschidere = f"Evaluare globală: <b>{scor_gen}/10 — {calif_gen}</b>. Atenție sporită la deficiențele semnalate în raport. "
            accent_concluzie, tint_concluzie = GOOGLE_AMBER, TINT_AMBER

        puncte_argumente = []
        # `ajustare_pct` is None whenever the valuation reported a margin in euros
        # but no percentage, and formatting None crashed the whole PDF build.
        if marja_eur > 0:
            if ecart_pct is not None:
                # The argument is how far the asking price sits above the
                # estimate, which is `ecart_pct`. Printing `ajustare_pct` here
                # produced "cu -4,9% peste nivelul pieței" -- a negative excess.
                puncte_argumente.append(
                    f"Preț cerut cu {abs(ecart_pct):.1f}% peste valoarea estimată de piață"
                )
            else:
                puncte_argumente.append(
                    f"Preț cerut cu ~{marja_eur:,.0f} {moneda} peste valoarea estimată"
                )
        bug_rep_val = bug_rep if "bug_rep" in locals() and bug_rep else 0
        if bug_rep_val > 0:
            puncte_argumente.append(f"Buget necesar remediere defecte (~{bug_rep_val:,.0f} €)")
        exp_luni_val = exp_luni if "exp_luni" in locals() and exp_luni else 0
        if exp_luni_val and exp_luni_val >= 4:
            puncte_argumente.append(f"Timp de absorbție ridicat pe segment ({exp_luni_val} luni)")

        arg_txt = f"<br/><b>Argumente cheie în negociere:</b> {', '.join(puncte_argumente)}." if puncte_argumente else ""

        concluzie_text = (
            deschidere + interval_negociere + arg_txt + "<br/>"
            "<i>Înainte de semnarea antecontractului, solicitați cartea tehnică, certificatul energetic și un extras CF la zi.</i>"
        )

    poveste.append(
        _creeaza_card_apel(
            concluzie_text,
            stiluri,
            titlu="RECOMANDARE STRATEGICĂ DE ACHIZIȚIE",
            culoare_accent=accent_concluzie,
            culoare_fundal=tint_concluzie,
        )
    )

    # Construire document PDF cu paginare avansată
    doc.build(poveste, canvasmaker=NumberedCanvas)
    logger.info("Raport PDF generat cu succes la %s", cale_iesire)
    return os.path.abspath(cale_iesire)
