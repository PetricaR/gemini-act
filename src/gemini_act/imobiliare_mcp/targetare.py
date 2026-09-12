"""Integrare Targetare.ro API pentru verificarea dezvoltatorilor și constructorilor."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

TARGETARE_API_BASE = "https://api.targetare.ro/v1"
TIMEOUT = 15.0


def validate_tax_id(tax_id: str) -> str:
    """Validează și normalizează un cod fiscal românesc (CUI/CIF).

    Elimină prefixul RO, spațiile și caracterele non-numerice.
    """
    cleaned = tax_id.strip().upper()
    cleaned = cleaned.replace("RO", "").replace("CUI", "").replace("CIF", "").strip()
    cleaned = "".join(filter(str.isdigit, cleaned))

    if not cleaned:
        raise ValueError(f"Cod fiscal invalid: '{tax_id}'. Trebuie să conțină cifre.")
    if len(cleaned) < 2 or len(cleaned) > 10:
        raise ValueError(
            f"Lungime cod fiscal invalidă ({len(cleaned)} cifre pentru '{tax_id}'). "
            "Un CUI românesc are între 2 și 10 cifre."
        )
    return cleaned


def _get_targetare_key() -> str:
    """Returnează cheia API Targetare din mediu sau setări."""
    return (
        os.getenv("API_KEY_TARGETARE")
        or os.getenv("TARGETARE_API_KEY")
        or os.getenv("GEMINI_ACT_TARGETARE_API_KEY")
        or ""
    )


def creeaza_slug_companie(nume: str) -> str:
    """Transformă numele companiei într-un slug URL."""
    curat = nume.lower().strip()
    for sufix in (" srl", " sa", " scs", " pfa", " ii", " sprl"):
        curat = curat.replace(sufix, "")
    curat = re.sub(r"[^a-z0-9]+", "-", curat).strip("-")
    return curat or "companie"


def interogheaza_targetare_oficial(endpoint: str, params: dict | None = None) -> dict | None:
    """Apelează API-ul oficial Targetare.ro cu token de autorizare."""
    api_key = _get_targetare_key()
    if not api_key:
        return None

    url = f"{TARGETARE_API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                return resp.json()
            logger.warning(
                "Targetare API status %d pentru %s: %s",
                resp.status_code,
                endpoint,
                resp.text[:200],
            )
            return None
    except Exception as exc:
        logger.warning("Eroare cerere Targetare API oficial: %s", exc)
        return None


def obtine_date_targetare_public(cui: str, nume_slug: str = "") -> dict | None:
    """Încearcă extragerea datelor publice Targetare.ro via endpoint Next.js."""
    slug = nume_slug or f"companie-{cui}"
    # Folosește build_id cunoscut sau căutare directă
    build_id = "liBdp1D4vMJ4nAZqxiWkg"
    url = f"https://targetare.ro/_next/data/{build_id}/{cui}/{slug}.json"
    params = {"taxId": cui, "companyName": slug}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "x-nextjs-data": "1",
    }
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return extrage_info_apollo(data)
    except Exception as exc:
        logger.debug("Eroare endpoint public Targetare: %s", exc)
    return None


def extrage_info_apollo(raw_data: dict) -> dict | None:
    """Extrage informațiile despre companie din starea Apollo/Next.js."""
    if not raw_data or "pageProps" not in raw_data:
        return None

    apollo_state = raw_data.get("pageProps", {}).get("__APOLLO_STATE__", {})
    root_query = apollo_state.get("ROOT_QUERY", {})

    company_data = None
    for key, value in root_query.items():
        if key.startswith("company(") and isinstance(value, dict):
            company_data = value
            break

    if not company_data:
        return None

    financial_data = company_data.get("financialData", [])
    latest_year = max(financial_data, key=lambda x: x.get("year", 0)) if financial_data else {}

    return {
        "denumire": company_data.get("companyName"),
        "cui": company_data.get("taxId"),
        "stare": company_data.get("status", "ACTIVĂ"),
        "nr_inreg": company_data.get("companyId"),
        "localitate": company_data.get("locality"),
        "adresa_completa": company_data.get("fullAddress"),
        "telefon": company_data.get("primaryPhone"),
        "cod_caen": company_data.get("caenCode"),
        "descriere_caen": company_data.get("caenDescription"),
        "an_ultim": latest_year.get("year"),
        "cifra_afaceri": latest_year.get("turnover"),
        "profit_net": latest_year.get("netProfit"),
        "angajati": latest_year.get("employee"),
        "active_imobilizate": latest_year.get("fixedAssets"),
        "datorii": latest_year.get("debts"),
        "capitaluri_proprii": latest_year.get("equity"),
        "istoric_financiar": [
            {
                "an": fd.get("year"),
                "cifra_afaceri": fd.get("turnover"),
                "profit_net": fd.get("netProfit"),
                "angajati": fd.get("employee"),
            }
            for fd in sorted(financial_data, key=lambda x: x.get("year", 0), reverse=True)
        ],
    }


def analizeaza_sanatate_financiara(date_firma: dict) -> dict[str, Any]:
    """Evaluează sănătatea financiară, solvabilitatea și riscul de insolvență.

    A company with no published financials scores nothing at all: absence of
    data is not evidence of health, and the caller must render it as
    unavailable rather than as a mid-range score.
    """
    # `or 0` would collapse "not reported" into "reported as zero" -- the two
    # mean opposite things here, so keep them distinct.
    ca = date_firma.get("cifra_afaceri")
    profit = date_firma.get("profit_net")
    datorii = date_firma.get("datorii")
    angajati = date_firma.get("angajati")
    capitaluri = date_firma.get("capitaluri_proprii")

    masurate = [v for v in (ca, profit, datorii, capitaluri) if v is not None]
    if not masurate:
        return {
            "status": "indisponibil",
            "disponibil": False,
            "provenienta": "indisponibil",
            "motiv": (
                "Nu există date financiare publicate pentru această companie "
                "(bilanț nedepus sau firmă nou înființată)."
            ),
            "scor_sanatate_financiara": None,
            "nivel_risc_insolventa": None,
            "marja_profit_procent": None,
            "grad_indatorare_procent": None,
            "este_spv_activ": None,
            "puncte_forte": [],
            "riscuri_semnalate": [],
            "avertismente_risc": [],
        }

    ca = ca or 0
    profit = profit or 0
    datorii = datorii or 0
    angajati = angajati or 0
    capitaluri = capitaluri or 0

    marja_profit = round((profit / ca) * 100, 2) if ca > 0 else 0.0
    grad_indatorare = round((datorii / ca) * 100, 2) if ca > 0 else 0.0

    puncte_forte: list[str] = []
    riscuri: list[str] = []

    # Evaluare profitabilitate
    if profit > 0:
        if marja_profit >= 15.0:
            puncte_forte.append(f"Profitabilitate ridicată: marjă netă de {marja_profit}%")
        else:
            puncte_forte.append(f"Companie pe profit (marjă netă {marja_profit}%)")
    elif profit < 0:
        riscuri.append(f"Compania a înregistrat pierdere netă de {abs(profit):,} RON în ultimul an")

    # Evaluare grad îndatorare
    if ca > 0:
        if grad_indatorare > 150.0:
            riscuri.append(
                f"Grad ridicat de îndatorare: datoriile depășesc CA ({grad_indatorare}%)"
            )
        elif grad_indatorare <= 60.0:
            puncte_forte.append(
                f"Grad redus de îndatorare ({grad_indatorare}% din cifra de afaceri)"
            )

    # Evaluare forță de muncă
    if angajati == 0:
        riscuri.append(
            "0 angajați raportați – dezvoltatorul funcționează ca SPV (vehicul investițional) "
            "sau externalizează integral execuția către antreprenori generali"
        )
    elif angajati >= 50:
        puncte_forte.append(
            f"Organizație stabilă cu capacitate proprie de execuție ({angajati} angajați)"
        )
    else:
        puncte_forte.append(f"Echipă activă de {angajati} angajați")

    # Capitaluri proprii
    if capitaluri < 0:
        riscuri.append(
            "Capitaluri proprii negative: semnal de dezechilibru patrimonial conform legislației"
        )
    elif capitaluri > 0:
        puncte_forte.append("Capitaluri proprii pozitive (echilibru financiar solid)")

    # Scor general (1 - 10)
    scor = 7.0
    if profit > 0 and marja_profit > 10:
        scor += 1.5
    if profit < 0:
        scor -= 2.5
    if grad_indatorare > 120:
        scor -= 1.5
    if capitaluri < 0:
        scor -= 2.0
    if angajati > 10:
        scor += 1.0

    scor_final = max(1.0, min(10.0, round(scor, 1)))

    if scor_final >= 8.0:
        nivel_risc = "Scăzut (Solvabilitate Ridicată)"
    elif scor_final >= 5.5:
        nivel_risc = "Moderat (Stabil financiar)"
    else:
        nivel_risc = "Ridicat (Atenție la avansuri și garanții de bună execuție)"

    return {
        "status": "success",
        "disponibil": True,
        "provenienta": "masurat",
        "scor_sanatate_financiara": scor_final,
        "nivel_risc_insolventa": nivel_risc,
        "marja_profit_procent": marja_profit,
        "grad_indatorare_procent": grad_indatorare,
        "este_spv_activ": bool(angajati == 0),
        "puncte_forte": puncte_forte,
        "riscuri_semnalate": riscuri,
        "avertismente_risc": riscuri,
    }


def analizeaza_firma_targetare(cui_sau_nume: str) -> dict[str, Any]:
    """Analizează o companie (dezvoltator/constructor) prin Targetare.ro.

    Suportă CUI numeric sau denumire comercială.
    """
    termen = cui_sau_nume.strip()
    cui_curat = ""

    # Verifică dacă utilizatorul a introdus direct un CUI
    try:
        cui_curat = validate_tax_id(termen)
    except ValueError:
        cui_curat = ""

    # Dacă avem CUI, încercăm interogarea directă
    date_profil = None
    date_financiare = None

    if cui_curat:
        # 1. Încercare API oficial
        date_profil = interogheaza_targetare_oficial(f"/companies/{cui_curat}")
        if date_profil:
            date_financiare = interogheaza_targetare_oficial(f"/companies/{cui_curat}/financial")

        # 2. Dacă nu este cheie oficială sau nu a returnat, încercare endpoint public
        if not date_profil:
            slug = creeaza_slug_companie(termen)
            date_publice = obtine_date_targetare_public(cui_curat, slug)
            if date_publice:
                audit = analizeaza_sanatate_financiara(date_publice)
                date_publice["analiza_financiara"] = audit
                date_publice["sursa"] = "targetare.ro (public)"
                return {
                    "status": "success",
                    "cui": cui_curat,
                    "date_firma": date_publice,
                    "markdown": targetare_to_markdown(date_publice),
                }

    if not cui_curat and not date_profil:
        # Căutare după nume companie
        # Putem apela endpoint-ul de căutare oficial dacă există
        date_cautare = interogheaza_targetare_oficial("/companies", params={"search": termen})
        if date_cautare and isinstance(date_cautare, list) and len(date_cautare) > 0:
            prima_firma = date_cautare[0]
            cui_curat = str(prima_firma.get("tax_id") or prima_firma.get("cui") or "")
            if cui_curat:
                return analizeaza_firma_targetare(cui_curat)

    # Dacă am obținut date oficiale
    if date_profil:
        fin_list = (date_financiare or {}).get("financial", [])
        an_recent = max(fin_list, key=lambda x: x.get("year", 0)) if fin_list else {}

        date_sintetizate = {
            "denumire": date_profil.get("company_name") or date_profil.get("name"),
            "cui": cui_curat,
            "stare": date_profil.get("status", "ACTIVĂ"),
            "nr_inreg": date_profil.get("registration_id") or date_profil.get("trade_register_id"),
            "localitate": date_profil.get("locality") or date_profil.get("city"),
            "adresa_completa": date_profil.get("full_address") or date_profil.get("address"),
            "telefon": date_profil.get("phone"),
            "cod_caen": date_profil.get("caen_code"),
            "descriere_caen": date_profil.get("caen_description"),
            "an_ultim": an_recent.get("year"),
            "cifra_afaceri": an_recent.get("turnover"),
            "profit_net": an_recent.get("net_profit"),
            "angajati": an_recent.get("employees"),
            "active_imobilizate": an_recent.get("fixed_assets"),
            "datorii": an_recent.get("debts"),
            "capitaluri_proprii": an_recent.get("equity"),
            "istoric_financiar": [
                {
                    "an": row.get("year"),
                    "cifra_afaceri": row.get("turnover"),
                    "profit_net": row.get("net_profit"),
                    "angajati": row.get("employees"),
                }
                for row in sorted(fin_list, key=lambda x: x.get("year", 0), reverse=True)
            ],
        }
        audit = analizeaza_sanatate_financiara(date_sintetizate)
        date_sintetizate["analiza_financiara"] = audit
        date_sintetizate["sursa"] = "api.targetare.ro (oficial)"
        return {
            "status": "success",
            "cui": cui_curat,
            "date_firma": date_sintetizate,
            "markdown": targetare_to_markdown(date_sintetizate),
        }

    # Dacă firma nu a putut fi extrasă automat
    return {
        "status": "not_found",
        "mesaj": (
            f"Nu s-au putut prelua automat date din Targetare.ro pentru '{termen}'. "
            "Verificați dacă CUI-ul introdus este corect sau configurați API_KEY_TARGETARE."
        ),
        "cui_cautat": cui_curat or termen,
    }


def targetare_to_markdown(data: dict[str, Any]) -> str:
    """Generează un raport structurat Markdown cu datele din Targetare.ro."""
    caen_cod = data.get("cod_caen", "N/A")
    caen_desc = data.get("descriere_caen", "Construcții / Dezvoltare Imobiliară")
    linii = [
        f"### 🏢 Audit Financiar Dezvoltator / Constructor: {data.get('denumire', 'N/A')}",
        "",
        f"- **CUI / CIF:** `{data.get('cui', 'N/A')}`",
        f"- **Nr. Înreg. Reg. Comerțului:** {data.get('nr_inreg', 'N/A')}",
        f"- **Stare Juridică:** {data.get('stare', 'ACTIVĂ')}",
        f"- **Sediu Social:** {data.get('adresa_completa', 'N/A')}",
        f"- **Activitate Principală CAEN:** {caen_cod} - {caen_desc}",
        "",
        "#### 📊 Indicatori Financiari Cheie (Ultimul an raportat)",
        "",
    ]

    ca = data.get("cifra_afaceri")
    profit = data.get("profit_net")
    datorii = data.get("datorii")
    angajati = data.get("angajati")
    capitaluri = data.get("capitaluri_proprii")

    ca_str = f"{ca:,.0f} RON" if ca is not None else "N/A"
    profit_str = f"{profit:,.0f} RON" if profit is not None else "N/A"
    datorii_str = f"{datorii:,.0f} RON" if datorii is not None else "N/A"
    cap_str = f"{capitaluri:,.0f} RON" if capitaluri is not None else "N/A"
    ang_str = str(angajati) if angajati is not None else "N/A"

    linii.extend([
        "| Indicator | Valoare Raportată |",
        "| :--- | :--- |",
        f"| **Cifră de Afaceri** | {ca_str} |",
        f"| **Profit Net / Pierdere** | {profit_str} |",
        f"| **Datorii Totale** | {datorii_str} |",
        f"| **Capitaluri Proprii** | {cap_str} |",
        f"| **Număr Angajați** | {ang_str} |",
        "",
    ])

    analiza = data.get("analiza_financiara", {})
    if analiza:
        scor_val = analiza.get("scor_sanatate_financiara")
        risc_val = analiza.get("nivel_risc_insolventa")
        marja_val = analiza.get("marja_profit_procent")
        grad_val = analiza.get("grad_indatorare_procent")
        linii.extend([
            "#### 🛡️ Evaluare Solvabilitate & Risc Dezvoltator",
            "",
        ])
        if scor_val is None:
            # No published financials: say so. A placeholder score here reads
            # as a measurement and is the one thing this section must not do.
            linii.extend([
                "> ⚠️ **Indisponibil.** " + (analiza.get("motiv")
                                            or "Nu există date financiare publicate."),
                "",
            ])
        else:
            linii.extend([
                f"- **Scor Sănătate Financiară:** **{scor_val} / 10**",
                f"- **Nivel Risc:** `{risc_val}`",
                f"- **Marjă Profit Net:** {marja_val}%",
                f"- **Grad de Îndatorare (Datorii / CA):** {grad_val}%",
                "",
            ])

        if analiza.get("puncte_forte"):
            linii.append("**Puncte forte identificate:**")
            for pf in analiza["puncte_forte"]:
                linii.append(f"- ✅ {pf}")
            linii.append("")

        if analiza.get("riscuri_semnalate"):
            linii.append("**Semnale de atenție / Riscuri pentru cumpărător:**")
            for risc in analiza["riscuri_semnalate"]:
                linii.append(f"- ⚠️ {risc}")
            linii.append("")

    istoric = data.get("istoric_financiar", [])
    if istoric and len(istoric) > 1:
        linii.extend([
            "#### 📈 Evoluție Multianuală",
            "",
            "| An | Cifră Afaceri (RON) | Profit Net (RON) | Angajați |",
            "| :---: | :---: | :---: | :---: |",
        ])
        for row in istoric[:5]:
            an = row.get("an")
            ca_val = f"{row.get('cifra_afaceri', 0):,.0f}" if row.get("cifra_afaceri") else "-"
            pr_val = f"{row.get('profit_net', 0):,.0f}" if row.get("profit_net") else "-"
            ang_val = row.get("angajati", "-")
            linii.append(f"| {an} | {ca_val} | {pr_val} | {ang_val} |")
        linii.append("")

    return "\n".join(linii)
