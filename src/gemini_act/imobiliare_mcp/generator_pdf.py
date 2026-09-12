"""Generator de rapoarte PDF profesionale conform standardelor de design Google Docs."""

from __future__ import annotations

import itertools
import logging
import os
from typing import Any

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import paths

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
        self.setFont("Helvetica", 8)
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
            "Document generat automat • Conformitate metodologică ANEVAR GEV 630",
        )
        page_str = f"Pagina {self._pageNumber} din {total_pages}"
        self.setFont("Helvetica-Bold", 8)
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
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=GOOGLE_BLUE,
            spaceAfter=4,
        ),
        "Subtitlu": ParagraphStyle(
            "Subtitlu",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=GOOGLE_GREY_MUTED,
            spaceAfter=12,
        ),
        "SectiuneH2": ParagraphStyle(
            "SectiuneH2",
            parent=base_styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=GOOGLE_CHARCOAL,
            spaceBefore=14,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "SectiuneH3": ParagraphStyle(
            "SectiuneH3",
            parent=base_styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=GOOGLE_BLUE,
            spaceBefore=8,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "Corp": ParagraphStyle(
            "Corp",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=GOOGLE_CHARCOAL,
            spaceAfter=4,
        ),
        "CorpBold": ParagraphStyle(
            "CorpBold",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=13,
            textColor=GOOGLE_CHARCOAL,
        ),
        "TabelHeader": ParagraphStyle(
            "TabelHeader",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=white,
        ),
        "TabelCelula": ParagraphStyle(
            "TabelCelula",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=GOOGLE_CHARCOAL,
        ),
        "TabelCelulaBold": ParagraphStyle(
            "TabelCelulaBold",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=GOOGLE_CHARCOAL,
        ),
        "CalloutText": ParagraphStyle(
            "CalloutText",
            parent=base_styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=GOOGLE_CHARCOAL,
        ),
        "BadgeText": ParagraphStyle(
            "BadgeText",
            parent=base_styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=white,
            alignment=1,
        ),
    }
    return stiluri


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
            Paragraph(f"<b>{titlu}</b>", ParagraphStyle(
                "CalloutTitle",
                parent=stiluri["CorpBold"],
                textColor=culoare_accent,
                fontSize=9.5,
                leading=13,
                spaceAfter=2,
            ))
        )
    continut.append(Paragraph(text, stiluri["CalloutText"]))

    tabel_card = Table(
        [[continut]],
        colWidths=[487],
    )
    tabel_card.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), culoare_fundal),
            ("LINELEFT", (0, 0), (0, -1), 3.5, culoare_accent),
            ("BOX", (0, 0), (-1, -1), 0.5, GOOGLE_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    return tabel_card


def _formateaza_tabel(
    randuri: list[list[str]],
    stiluri: dict[str, ParagraphStyle],
    latimi_coloane: list[float],
) -> Table:
    """Construiește un tabel profesional cu rânduri alternante și antet Google Blue."""
    date_tabel = []
    # Header
    date_tabel.append([
        Paragraph(celula, stiluri["TabelHeader"]) for celula in randuri[0]
    ])
    # Body
    for rand in randuri[1:]:
        date_tabel.append([
            Paragraph(celula, stiluri["TabelCelula"]) for celula in rand
        ])

    tab = Table(date_tabel, colWidths=latimi_coloane)
    stil_tabel = [
        ("BACKGROUND", (0, 0), (-1, 0), GOOGLE_BLUE),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
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
        # Not Path("reports"): that is relative to the process working
        # directory, which is read-only on Cloud Run.
        cale_iesire = str(paths.reports_dir() / f"raport-complet-{prop_id}.pdf")

    os.makedirs(os.path.dirname(os.path.abspath(cale_iesire)), exist_ok=True)

    # Document A4 cu margini de 0.75 in (54 pt)
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

    # =========================================================================
    # 1. COPERTA & ANTET DE PREZENTARE
    # =========================================================================
    titlu = date_proprietate.get("titlu") or f"Apartament {prop_id}"
    pret = date_proprietate.get("pret_total") or date_proprietate.get("pret") or 0
    moneda = date_proprietate.get("moneda") or "EUR"
    suprafata = date_proprietate.get("suprafata_utila") or date_proprietate.get("suprafata") or 0
    pret_mp = (
        date_proprietate.get("pret_pe_mp")
        or (round(pret / suprafata, 1) if suprafata > 0 else 0)
    )
    adresa = date_proprietate.get("adresa") or date_proprietate.get("oras") or "N/A"

    poveste.append(Paragraph(titlu, stiluri["TitluDocument"]))
    poveste.append(
        Paragraph(
            f"Adresă: <b>{adresa}</b> • Link Anunț: {date_proprietate.get('url', 'N/A')}",
            stiluri["Subtitlu"],
        )
    )

    # Badge de sinteză financiară
    badge_data = [
        [
            Paragraph(f"<b>PREȚ SOLICITAT</b><br/>{pret:,.0f} {moneda}", stiluri["BadgeText"]),
            Paragraph(f"<b>SUPRAFAȚĂ UTILĂ</b><br/>{suprafata} mp", stiluri["BadgeText"]),
            Paragraph(
                f"<b>PREȚ / MP UTIL</b><br/>{pret_mp:,.0f} {moneda}/mp",
                stiluri["BadgeText"],
            ),
        ]
    ]
    tabel_badge = Table(badge_data, colWidths=[162, 162, 163])
    tabel_badge.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), GOOGLE_BLUE),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 1, GOOGLE_NAVY),
            ("INNERGRID", (0, 0), (-1, -1), 1, white),
        ])
    )
    poveste.append(tabel_badge)
    poveste.append(Spacer(1, 12))

    # Inserare Foaie de Contact / Galerie Foto dacă este disponibilă
    cale_galerie = date_proprietate.get("cale_galerie")
    if cale_galerie and os.path.exists(cale_galerie):
        try:
            poveste.append(
                Paragraph("<b>Foaie de Contact Foto Ofertă</b>", stiluri["SectiuneH3"])
            )
            img = Image(cale_galerie, width=487, height=220)
            poveste.append(img)
            poveste.append(Spacer(1, 10))
        except Exception as exc:
            logger.debug("Nu s-a putut insera galeria în PDF: %s", exc)

    # =========================================================================
    # 2. EVALUARE DE PIAȚĂ ANEVAR (GEV 630)
    # =========================================================================
    # Sections are numbered as they are emitted, not by a hard-coded index:
    # a section that turns out to be unavailable used to vanish entirely and
    # leave the headings jumping (4 -> 7).
    _nr = itertools.count(1)

    def titlu(text: str) -> Paragraph:
        return Paragraph(f"{next(_nr)}. {text}", stiluri["SectiuneH2"])

    poveste.append(
        HRFlowable(width="100%", thickness=1, color=GOOGLE_BLUE, spaceBefore=4, spaceAfter=8)
    )
    poveste.append(titlu("Evaluare de Piață ANEVAR (GEV 630)"))

    eval_anevar = date_proprietate.get("evaluare_anevar") or {}
    # Bound on both branches: the negotiation card at the end of the document
    # formats these unconditionally, and an unavailable valuation used to
    # leave them unbound and abort the whole PDF with UnboundLocalError.
    val_piata = val_min = val_max = None
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
        val_piata = eval_anevar.get("valoare_estimata_piata") or pret or 0
        # Only a real interval, from the grid's own spread of adjusted unit
        # values. A ±5% band around the point estimate looked like a measured
        # range and was not one.
        val_min = eval_anevar.get("interval_valoare_min")
        val_max = eval_anevar.get("interval_valoare_max")
        # Present-but-null is the normal case when the asking price or the
        # estimate is missing, and `.get(k, default)` does not cover it.
        ajustare_pct = eval_anevar.get("ajustare_recomandata_procent")

        if val_min is not None and val_max is not None:
            interval_txt = f" (interval rezonabil <b>{val_min:,.0f} - {val_max:,.0f} {moneda}</b>)"
        else:
            interval_txt = (
                " (interval indisponibil: eșantion prea îngust pentru un interval credibil)"
            )
        if ajustare_pct is None:
            ajustare_txt = "Ajustarea față de prețul cerut nu a putut fi calculată."
        else:
            ajustare_txt = (
                f"Ajustare recomandată față de prețul din anunț: <b>{ajustare_pct:+.1f}%</b>."
            )

        card_anevar_text = (
            f"Conform standardului ANEVAR GEV 630 (Metoda Comparației Directe), "
            f"valoarea de piață estimată este de <b>{val_piata:,.0f} {moneda}</b>"
            f"{interval_txt}. {ajustare_txt}"
        )
        favorabil = ajustare_pct is None or ajustare_pct >= -3.0
        accent_anevar = GOOGLE_GREEN if favorabil else GOOGLE_AMBER
        tint_anevar = TINT_GREEN if favorabil else TINT_AMBER
        poveste.append(
            _creeaza_card_apel(
                card_anevar_text,
                stiluri,
                titlu="VERDICT EVALUARE ANEVAR",
                culoare_accent=accent_anevar,
                culoare_fundal=tint_anevar,
            )
        )
        poveste.append(Spacer(1, 8))

        # Grilă comparabile
        comps = eval_anevar.get("comparabile_utilizate", [])
        if comps:
            linii_comps = [["ID Ofertă", "Preț Solicitat", "Suprafață", "Preț/mp", "Ajustare Netă"]]
            for c in comps[:4]:
                linii_comps.append([
                    str(c.get("id", "Comp")),
                    f"{c.get('pret', 0):,.0f} {moneda}",
                    f"{c.get('suprafata', 0)} mp",
                    f"{c.get('pret_mp', 0):,.0f} {moneda}",
                    f"{c.get('ajustare_neta_procent', 0):+.1f}%",
                ])
            poveste.append(
                _formateaza_tabel(linii_comps, stiluri, [97, 100, 95, 95, 100])
            )
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # =========================================================================
    # 3. AUDIT MOBILIER, FINISAJE & ELECTROCASNICE
    # =========================================================================
    audit_mob = date_proprietate.get("audit_mobilier") or {}
    audit_ef = date_proprietate.get("audit_electrocasnice_finisaje") or {}
    if audit_mob or audit_ef:
        poveste.append(KeepTogether([
            HRFlowable(
                width="100%",
                thickness=0.5,
                color=GOOGLE_BORDER,
                spaceBefore=4,
                spaceAfter=8,
            ),
            titlu("Audit Vizual Interior: Finisaje, Defecte & Electrocasnice"),
        ]))

        if audit_mob:
            scor_mob = audit_mob.get("scor_calitate_finisaje", "N/A")
            val_est = audit_mob.get("valoare_estimata_mobilier_eur", 0)
            durabilitate = audit_mob.get("durabilitate_estimata_ani", "N/A")
            sumar_mob = audit_mob.get("sumar_calitate", "Mobilier și finisaje analizate.")

            text_mob = (
                f"<b>Scor Finisaje:</b> {scor_mob}/10 • "
                f"<b>Valoare Mobilier Inclus:</b> ~{val_est:,.0f} EUR • "
                f"<b>Durabilitate Estimată:</b> {durabilitate} ani.<br/>"
                f"<b>Sinteză Mobilier:</b> {sumar_mob}"
            )
            poveste.append(
                _creeaza_card_apel(
                    text_mob,
                    stiluri,
                    titlu="EVALUARE MOBILIER",
                    culoare_accent=GOOGLE_BLUE,
                )
            )
            poveste.append(Spacer(1, 8))

            elemente = audit_mob.get("elemente_identificate", [])
            if elemente:
                linii_el = [
                    ["Încăpere / Zonă", "Obiecte Identificate", "Material / Tip", "Calitate"]
                ]
                for el in elemente[:6]:
                    linii_el.append([
                        el.get("camera", "Cameră"),
                        el.get("element", "Mobilier"),
                        el.get("material", "N/A"),
                        el.get("nivel_calitate", "Medie"),
                    ])
                poveste.append(_formateaza_tabel(linii_el, stiluri, [107, 150, 130, 100]))
                poveste.append(Spacer(1, 8))

        if audit_ef:
            if audit_ef.get("status") == "indisponibil" or audit_ef.get("disponibil") is False:
                motiv = audit_ef.get("motiv") or (
                    "Nu au fost furnizate fotografii sau specificații tehnice "
                    "suficiente în anunț."
                )
                poveste.append(
                    _creeaza_card_apel(
                        f"<b>Audit Finisaje & Electrocasnice indisponibil:</b> {motiv}",
                        stiluri,
                        titlu="AUDIT ELECTROCASNICE & FINISAJE",
                        culoare_accent=GOOGLE_MUTED,
                        culoare_fundal=GOOGLE_CARD_BG,
                    )
                )
                poveste.append(Spacer(1, 8))
            else:
                sumar_ef = audit_ef.get("sumar_financiar") or {}
                val_nou_el = sumar_ef.get("total_valoare_nou_electrocasnice_eur") or audit_ef.get(
                    "total_valoare_nou_eur", 0
                )
                val_act_el = sumar_ef.get(
                    "total_valoare_actuala_electrocasnice_eur"
                ) or audit_ef.get(
                    "total_valoare_actuala_eur", 0
                )
                bug_reparatii = sumar_ef.get("total_buget_remediere_defecte_eur") or audit_ef.get(
                    "buget_total_reparatii_eur", 0
                )
                imp_neg = sumar_ef.get("impact_negociere_recomandat_eur") or audit_ef.get(
                    "levier_negociere_recomandat_eur", 0
                )

                cal_gen = audit_ef.get("calitate_generala_finisaje") or {}
                scor_fin = cal_gen.get("scor_global") or audit_ef.get("scor_finisaje", "N/A")
                clasa_fin = str(
                    cal_gen.get("clasa") or audit_ef.get("clasa_finisaje", "N/A")
                ).capitalize()

                card_ef_text = (
                    f"<b>Calitate Finisaje:</b> {scor_fin}/10 ({clasa_fin}) • "
                    f"<b>Pachet Electrocasnice (Nou/Actual):</b> "
                    f"~{val_nou_el:,.0f} € / ~{val_act_el:,.0f} €.<br/>"
                    f"<b>Buget Necesar Remediere Defecte:</b> ~{bug_reparatii:,.0f} EUR • "
                    f"<b>Levier Negociere Recomandat:</b> -{imp_neg:,.0f} EUR.<br/>"
                    f"<i>{sumar_ef.get('recomandare_evaluator', '')}</i>"
                )
                poveste.append(
                    _creeaza_card_apel(
                        card_ef_text,
                        stiluri,
                        titlu="AUDIT ELECTROCASNICE & DEFECTE FINISAJE",
                        culoare_accent=GOOGLE_AMBER if bug_reparatii > 300 else GOOGLE_GREEN,
                        culoare_fundal=TINT_AMBER if bug_reparatii > 300 else TINT_GREEN,
                    )
                )
                poveste.append(Spacer(1, 8))

            electro = audit_ef.get("electrocasnice") or []
            if electro:
                poveste.append(
                    Paragraph(
                        "<b>Catalog Electrocasnice & Branduri Identificate</b>",
                        stiluri["SectiuneH3"],
                    )
                )
                linii_el = [["Aparat", "Cameră", "Brand & Gamă", "Preț Nou", "Valoare Actuală"]]
                for e in electro[:6]:
                    brand_info = e.get("brand_detectat", "-")
                    model_info = e.get("gama_brand") or e.get("model_sau_serie")
                    if model_info:
                        brand_info = f"{brand_info} ({model_info})"
                    p_nou = e.get("pret_estimat_nou_eur") or e.get("pret_nou_estimat_eur", 0)
                    p_act = e.get("valoare_piata_actuala_eur") or e.get("valoare_actuala_eur", 0)
                    linii_el.append([
                        e.get("aparat", "-"),
                        e.get("camera", "-"),
                        brand_info,
                        f"~{p_nou:,.0f} €",
                        f"~{p_act:,.0f} €",
                    ])
                poveste.append(_formateaza_tabel(linii_el, stiluri, [110, 85, 142, 75, 75]))
                poveste.append(Spacer(1, 8))

            defecte = (
                audit_ef.get("defecte_si_probleme")
                or audit_ef.get("defecte_identificate")
                or []
            )
            if defecte:
                poveste.append(
                    Paragraph(
                        "<b>Defecte și Probleme Vizibile (Semnale de Alarmă)</b>",
                        stiluri["SectiuneH3"],
                    )
                )
                linii_def = [
                    ["Element Afectat", "Descriere Defect", "Severitate", "Cost Remediere"]
                ]
                for d in defecte[:5]:
                    elem = d.get("element_afectat") or d.get("element", "-")
                    desc = d.get("descriere_defect") or d.get("defect", "-")
                    cost = d.get("cost_estimat_remediere_eur") or d.get("cost_estimat_eur", 0)
                    linii_def.append([
                        elem,
                        desc,
                        d.get("severitate", "Moderat"),
                        f"~{cost:,.0f} €",
                    ])
                poveste.append(_formateaza_tabel(linii_def, stiluri, [115, 192, 90, 90]))
                poveste.append(Spacer(1, 10))

    # =========================================================================
    # 4. AUDIT EXTERIOR STREET VIEW 360° & SATELIT
    # =========================================================================
    audit_ext = date_proprietate.get("audit_exterior") or {}
    if audit_ext:
        poveste.append(PageBreak())  # Pagină nouă pentru vizual exterior
        poveste.append(titlu("Inspecție Exterioară Google Street View 360° & Satelit"))

        if audit_ext.get("status") == "indisponibil" or audit_ext.get("disponibil") is False:
            motiv = audit_ext.get("motiv") or (
                "Google Street View nu are acoperire pentru această adresă."
            )
            poveste.append(
                _creeaza_card_apel(
                    f"<b>Inspecție exterioară indisponibilă:</b> {motiv}",
                    stiluri,
                    titlu="AUDIT VIZUAL STRADĂ & AMPLASAMENT",
                    culoare_accent=GOOGLE_MUTED,
                    culoare_fundal=GOOGLE_CARD_BG,
                )
            )
            poveste.append(Spacer(1, 10))
        else:
            scor_fatada = audit_ext.get("scor_fatada", "N/A")
            scor_strada = audit_ext.get("scor_strada", "N/A")
            stare_str = audit_ext.get("stare_fatada", "N/A")
            concluzie_ext = audit_ext.get("concluzie_generala_exterior", "N/A")

            text_ext = (
                f"<b>Stare Fațadă:</b> {stare_str} (Scor {scor_fatada}/10) • "
                f"<b>Infrastructură Stradală:</b> Scor {scor_strada}/10.<br/>"
                f"<b>Concluzie Exterior:</b> {concluzie_ext}"
            )
            poveste.append(
                _creeaza_card_apel(
                    text_ext,
                    stiluri,
                    titlu="AUDIT VIZUAL STRADĂ & AMPLASAMENT",
                    culoare_accent=GOOGLE_BLUE,
                )
            )
            poveste.append(Spacer(1, 10))

        # Inserare imagini Street View dacă sunt prezente
        poze_street = audit_ext.get("imagini_salvate", [])
        if poze_street:
            rand_poze = []
            for p in poze_street[:2]:
                cale_p = p.get("cale") if isinstance(p, dict) else str(p)
                if cale_p and os.path.exists(cale_p):
                    try:
                        rand_poze.append(Image(cale_p, width=238, height=140))
                    except Exception:
                        pass
            if rand_poze:
                tabel_poze = Table([rand_poze], colWidths=[243, 244])
                tabel_poze.setStyle(TableStyle([
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]))
                poveste.append(tabel_poze)
                poveste.append(Spacer(1, 10))

    # =========================================================================
    # 5. DEZVOLTATOR & CONSTRUCTOR (SPECIFICAȚII TEHNICE)
    # =========================================================================
    dev_specs = date_proprietate.get("specificatii_dezvoltator") or {}
    if dev_specs:
        poveste.append(KeepTogether([
            HRFlowable(
                width="100%",
                thickness=0.5,
                color=GOOGLE_BORDER,
                spaceBefore=4,
                spaceAfter=8,
            ),
            titlu("Dezvoltator, Constructor & Specificații Tehnice"),
        ]))

        # "Nespecificat", never a plausible-looking guess: the defaults here
        # asserted a concrete class, brick type and joinery profile for
        # buildings nobody had looked at. `.get(k, default)` also does not
        # cover a present-but-None value, which is now the normal case.
        NESPECIFICAT = "Nespecificat în anunț"

        def spec(cheie: str) -> str:
            return dev_specs.get(cheie) or NESPECIFICAT

        randuri_dev = [
            ["Element Tehnic", "Specificație Proiectată / Raportată"],
            ["Dezvoltator Imobiliar", spec("dezvoltator")],
            ["Constructor (Antreprenor General)", spec("constructor")],
            ["Structură de Rezistență", spec("structura_rezistenta")],
            ["Zidărie & Compartimentare", spec("zidarie")],
            ["Izolație Termică Fațadă", spec("termoizolatie")],
            ["Tâmplărie Exterioară", spec("tamplarie")],
            ["Garanție Structură & Finisaje", spec("garantie")],
        ]
        if all(r[1] == NESPECIFICAT for r in randuri_dev[1:]):
            poveste.append(_creeaza_card_apel(
                "<b>Specificații tehnice indisponibile:</b> anunțul nu menționează "
                "dezvoltatorul, constructorul sau materialele de construcție.",
                stiluri,
                titlu="SPECIFICAȚII INDISPONIBILE",
                culoare_accent=GOOGLE_MUTED,
                culoare_fundal=GOOGLE_CARD_BG,
            ))
            poveste.append(Spacer(1, 10))
            randuri_dev = []
        if randuri_dev:
            poveste.append(_formateaza_tabel(randuri_dev, stiluri, [187, 300]))
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # 6. TARGETARE.RO: DUE DILIGENCE FINANCIAR DEZVOLTATOR / CONSTRUCTOR
    # =========================================================================
    targetare_data = date_proprietate.get("audit_targetare") or {}
    analiza_f = (targetare_data.get("date_firma", {}) or {}).get("analiza_financiara", {}) or {}
    scor_f = analiza_f.get("scor_sanatate_financiara")
    targetare_ok = (
        targetare_data.get("status") == "success"
        and targetare_data.get("disponibil") is not False
        and scor_f is not None
    )
    if targetare_data:
        poveste.append(KeepTogether([
            HRFlowable(
                width="100%",
                thickness=0.5,
                color=GOOGLE_BORDER,
                spaceBefore=4,
                spaceAfter=8,
            ),
            titlu("Due Diligence Financiar Targetare.ro"),
        ]))

    if targetare_data and not targetare_ok:
        # Say the section could not be produced rather than dropping it, and
        # never stand in a mid-range score for a company nobody could look up.
        poveste.append(_creeaza_card_apel(
            "<b>Due diligence financiar indisponibil:</b> "
            + (targetare_data.get("motiv") or analiza_f.get("motiv")
               or "Dezvoltatorul nu a fost identificat sau nu are date financiare publicate."),
            stiluri,
            titlu="DATE FINANCIARE INDISPONIBILE",
            culoare_accent=GOOGLE_MUTED,
            culoare_fundal=GOOGLE_CARD_BG,
        ))
        poveste.append(Spacer(1, 10))
    elif targetare_ok:
        firma = targetare_data.get("date_firma", {})
        risc_f = analiza_f.get("nivel_risc_insolventa") or "Nedeterminat"

        if scor_f >= 7.5:
            culoare_f, fundal_f = GOOGLE_GREEN, TINT_GREEN
        elif scor_f >= 5.0:
            culoare_f, fundal_f = GOOGLE_AMBER, TINT_AMBER
        else:
            culoare_f, fundal_f = GOOGLE_RED, TINT_RED

        text_fin = (
            f"<b>Companie:</b> {firma.get('denumire')} (CUI: {firma.get('cui')}) • "
            f"<b>Stare:</b> {firma.get('stare')} • "
            f"<b>Scor Solvabilitate:</b> <b>{scor_f}/10</b> ({risc_f}).<br/>"
            f"<b>Sediu:</b> {firma.get('adresa_completa', 'N/A')}"
        )
        poveste.append(
            _creeaza_card_apel(
                text_fin,
                stiluri,
                titlu="VERIFICARE BONITATE & RISC INSOLVENȚĂ",
                culoare_accent=culoare_f,
                culoare_fundal=fundal_f,
            )
        )
        poveste.append(Spacer(1, 8))

        ca = firma.get("cifra_afaceri", 0)
        profit = firma.get("profit_net", 0)
        datorii = firma.get("datorii", 0)
        ang = firma.get("angajati", 0)
        linii_fin = [
            ["Indicator Financiar", "Valoare (Ultimul An Raportat)"],
            ["Cifră de Afaceri", f"{ca:,.0f} RON" if ca else "N/A"],
            ["Profit Net / Pierdere", f"{profit:,.0f} RON" if profit else "N/A"],
            ["Datorii Totale", f"{datorii:,.0f} RON" if datorii else "N/A"],
            ["Număr Angajați Raportați", str(ang) if ang is not None else "N/A"],
            ["Grad de Îndatorare (Datorii/CA)", f"{analiza_f.get('grad_indatorare_procent', 0)}%"],
        ]
        poveste.append(_formateaza_tabel(linii_fin, stiluri, [237, 250]))
        poveste.append(Spacer(1, 10))

    # =========================================================================
    # 7. GOOGLE MAPS REVIEWS: REPUTAȚIE & OPINII REZIDENȚI
    # =========================================================================
    recenzii_data = date_proprietate.get("recenzii_google") or {}
    loc = recenzii_data.get("locatie", {}) or {}
    analiza_r = loc.get("analiza_sentiment", {}) or {}
    scor_r = analiza_r.get("scor_reputatie")
    recenzii_ok = (
        recenzii_data.get("status") == "success"
        and recenzii_data.get("disponibil") is not False
        and scor_r is not None
    )
    if recenzii_data:
        poveste.append(KeepTogether([
            HRFlowable(
                width="100%",
                thickness=0.5,
                color=GOOGLE_BORDER,
                spaceBefore=4,
                spaceAfter=8,
            ),
            titlu("Reputație & Recenzii Google Maps"),
        ]))

    if recenzii_data and not recenzii_ok:
        poveste.append(_creeaza_card_apel(
            "<b>Recenzii indisponibile:</b> "
            + (recenzii_data.get("motiv") or analiza_r.get("motiv")
               or "Nu au fost identificate recenzii Google Maps pentru acest "
                  "imobil sau dezvoltator."),
            stiluri,
            titlu="REPUTAȚIE INDISPONIBILĂ",
            culoare_accent=GOOGLE_MUTED,
            culoare_fundal=GOOGLE_CARD_BG,
        ))
        poveste.append(Spacer(1, 10))
    elif recenzii_ok:
        calif_r = analiza_r.get("calificativ_reputatie") or "Nedeterminat"
        sfat_r = analiza_r.get("recomandare_cumparator") or "Verificați aspectele contractuale."

        text_rec = (
            f"<b>Scor Comunitate:</b> <b>{scor_r}/10</b> ({calif_r}) bazat pe "
            f"<b>{loc.get('rating_global')} ★</b> ({loc.get('total_recenzii')} recenzii).<br/>"
            f"<b>Sfat Cumpărător:</b> {sfat_r}"
        )
        poveste.append(
            _creeaza_card_apel(
                text_rec,
                stiluri,
                titlu="FEEDBACK REZIDENȚI & CLIENȚI",
                culoare_accent=GOOGLE_BLUE,
            )
        )
        poveste.append(Spacer(1, 8))

        puncte_pr = analiza_r.get("probleme_reclamate_frecvent", [])
        puncte_pf = analiza_r.get("puncte_forte_apreciate", [])
        if puncte_pr or puncte_pf:
            linii_rev = [["Puncte Forte Recunoscute", "Semnale de Atenție / Plângeri"]]
            max_len = max(len(puncte_pf), len(puncte_pr))
            for i in range(min(max_len, 4)):
                pf_text = f"• {puncte_pf[i]}" if i < len(puncte_pf) else "-"
                pr_text = f"• {puncte_pr[i]}" if i < len(puncte_pr) else "-"
                linii_rev.append([pf_text, pr_text])
            poveste.append(_formateaza_tabel(linii_rev, stiluri, [243, 244]))
            poveste.append(Spacer(1, 10))

    # =========================================================================
    # 8. CHECKLIST DE RECEPȚIE & VERIFICARE TEHNICĂ
    # =========================================================================
    poveste.append(KeepTogether([
        HRFlowable(
            width="100%",
            thickness=0.5,
            color=GOOGLE_BORDER,
            spaceBefore=4,
            spaceAfter=8,
        ),
        titlu("Checklist Tehnic pentru Recepție & Verificare Acte"),
        _formateaza_tabel(
            [
                ["Etapă / Punct", "Elemente Obligatorii", "Status"],
                ["Acte Juridice", "Extras CF de informare curat (fără sarcini)", "Obligatoriu"],
                ["Carte Tehnică", "Proiect rezistență, PV recepție la roșu/gata", "Obligatoriu"],
                ["Instalații Sanitare", "Probe presiune, contorizare apă/gaz", "La recepție"],
                ["Instalații Electrice", "Tablou siguranțe, împământare", "La recepție"],
                ["Izolație & Ferestre", "Etanșeitate garnituri ferestre tripan", "La vizionare"],
            ],
            stiluri,
            [130, 267, 90],
        ),
        Spacer(1, 10),
    ]))

    # =========================================================================
    # 9. CONCLUZIE & RECOMANDARE DE NEGOCIERE
    # =========================================================================
    poveste.append(KeepTogether([
        HRFlowable(width="100%", thickness=1, color=GOOGLE_BLUE, spaceBefore=4, spaceAfter=8),
        titlu("Concluzie Finală & Strategie de Negociere"),
    ]))

    # The recommendation follows the evidence. It previously opened with
    # "oportunitate validată cu risc controlat" for every property, including
    # ones where every section came back unavailable.
    scor_general = date_proprietate.get("scor_general")
    calificativ_general = date_proprietate.get("calificativ_general") or ""

    if not evaluare_disponibila or val_piata is None:
        concluzie_text = (
            "<b>Nu se poate formula o strategie de negociere pe bază de cifre:</b> "
            "evaluarea de piață nu a putut fi realizată pentru acest imobil "
            f"({eval_anevar.get('motiv') or 'eșantion de comparabile insuficient'}). "
            "Solicitați o evaluare ANEVAR autorizată înainte de a face o ofertă și "
            "cereți dezvoltatorului fișa tehnică completă și garanțiile contractuale."
        )
        accent_concluzie, tint_concluzie = GOOGLE_MUTED, GOOGLE_CARD_BG
    else:
        prag_jos = val_min if val_min is not None else val_piata
        interval_negociere = (
            f"Recomandăm începerea negocierii de la <b>{prag_jos:,.0f} {moneda}</b>, "
            f"cu limită superioară la <b>{val_piata:,.0f} {moneda}</b>. "
        )
        if scor_general is None:
            deschidere = (
                "Evaluarea de piață este disponibilă, dar restul secțiunilor nu au "
                "produs suficiente date pentru un verdict global. "
            )
            accent_concluzie, tint_concluzie = GOOGLE_MUTED, GOOGLE_CARD_BG
        elif scor_general >= 7.0:
            deschidere = f"Evaluare globală: <b>{scor_general}/10 — {calificativ_general}</b>. "
            accent_concluzie, tint_concluzie = GOOGLE_BLUE, TINT_BLUE
        else:
            deschidere = (
                f"Evaluare globală: <b>{scor_general}/10 — {calificativ_general}</b>. "
                "Verificați punctele semnalate mai sus înainte de a avansa. "
            )
            accent_concluzie, tint_concluzie = GOOGLE_AMBER, TINT_AMBER
        concluzie_text = (
            deschidere + interval_negociere
            + "Solicitați fișa completă de la dezvoltator și garanția contractuală."
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

    # Construire document PDF
    doc.build(poveste, canvasmaker=NumberedCanvas)
    logger.info("Raport PDF generat cu succes la %s", cale_iesire)
    return os.path.abspath(cale_iesire)
