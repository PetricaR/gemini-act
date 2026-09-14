"""Reading the Drive folder of reference documents (`drive_docs`).

Nothing here touches Drive: the folder listing and the download are the two
seams, and both are stubbed. What is *not* stubbed is the extraction — the PDFs
below are built with reportlab and read back with pypdf, because the failure
this module exists to avoid (a scanned PDF quietly extracting as "") is only
visible through the real reader.
"""

from __future__ import annotations

import io

import pytest
from reportlab.pdfgen import canvas

from gemini_act.imobiliare_mcp import drive_docs as dd


@pytest.fixture(autouse=True)
def _cache_izolat(tmp_path, monkeypatch):
    """Each test gets its own cache, and no test inherits a live ADC lookup."""
    monkeypatch.setenv("IMOBILIARE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(dd, "_service_si_credentiale", lambda: (None, None))
    yield


def fisier(nume, mime="application/pdf", **kw):
    return {
        "id": kw.get("id", f"id-{nume}"),
        "name": nume,
        "mimeType": mime,
        "size": kw.get("size", "1024"),
        "modifiedTime": kw.get("modificat", "2026-09-01T10:00:00.000Z"),
    }


def folder(nume, fid):
    return {"id": fid, "name": nume, "mimeType": dd._FOLDER_MIME}


@pytest.fixture
def drive(monkeypatch):
    """Install a folder tree: {folder_id: [children]}."""

    def _instaleaza(arbore):
        monkeypatch.setattr(dd, "_copii", lambda fid: arbore.get(fid, []))
        return arbore

    return _instaleaza


def pdf_cu_text(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def pdf_scanat() -> bytes:
    """A page with no text layer at all — what a scan produces."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.rect(72, 600, 200, 100, fill=0)
    c.showPage()
    c.save()
    return buf.getvalue()


# -- Folder id -------------------------------------------------------------


def test_folder_id_accepta_url_sau_id_gol(monkeypatch):
    monkeypatch.delenv("IMOBILIARE_DRIVE_FOLDER_ID", raising=False)
    url = "https://drive.google.com/drive/folders/1G0SLX9clxcGnxgljBs3l7__nwMIMRenQ"
    assert dd.folder_id(url) == "1G0SLX9clxcGnxgljBs3l7__nwMIMRenQ"
    assert dd.folder_id("1G0SLX9clxcGnxgljBs3l7__nwMIMRenQ") == "1G0SLX9clxcGnxgljBs3l7__nwMIMRenQ"
    assert dd.folder_id() == dd.FOLDER_DEFAULT


def test_folder_id_urmeaza_variabila_de_mediu(monkeypatch):
    monkeypatch.setenv(
        "IMOBILIARE_DRIVE_FOLDER_ID", "https://drive.google.com/drive/folders/0BxALTFOLDER123"
    )
    assert dd.folder_id() == "0BxALTFOLDER123"


# -- Listing ---------------------------------------------------------------


def test_listeaza_parcurge_subfolderele(drive):
    drive(
        {
            "radacina": [fisier("ghid.pdf"), folder("costuri", "sub")],
            "sub": [fisier("catalog-2026.xlsx", "application/vnd.google-apps.spreadsheet")],
        }
    )
    documente = dd.listeaza("radacina")
    assert sorted(d.cale for d in documente) == ["costuri/catalog-2026.xlsx", "ghid.pdf"]


def test_listeaza_citeste_prin_shortcut(drive):
    scurtatura = {
        "id": "sc1",
        "name": "link catre ghid",
        "mimeType": dd._SHORTCUT_MIME,
        "shortcutDetails": {"targetId": "tinta", "targetMimeType": "application/pdf"},
    }
    drive({"radacina": [scurtatura]})
    (doc,) = dd.listeaza("radacina")
    assert doc.id == "tinta"
    assert doc.mime == "application/pdf"


def test_listeaza_nu_intra_in_ciclu(drive):
    # A shortcut pointing back at an ancestor would otherwise walk forever.
    drive({"a": [folder("b", "b")], "b": [folder("a", "a"), fisier("x.pdf")]})
    assert [d.cale for d in dd.listeaza("a")] == ["b/x.pdf"]


def test_listarea_e_refolosita_din_cache(drive, monkeypatch):
    apeluri = []

    def numara(fid):
        apeluri.append(fid)
        return [fisier("ghid.pdf")]

    monkeypatch.setattr(dd, "_copii", numara)
    dd.listeaza("radacina")
    dd.listeaza("radacina")
    assert len(apeluri) == 1
    dd.listeaza("radacina", reincarca=True)
    assert len(apeluri) == 2


# -- Formats ---------------------------------------------------------------


@pytest.mark.parametrize(
    "nume,mime,asteptat",
    [
        ("ghid.pdf", "application/pdf", "PDF"),
        ("nota", "application/vnd.google-apps.document", "document Google"),
        ("fisa.docx", "application/octet-stream", "Word (.docx)"),
        ("date.csv", "text/csv", "text"),
        ("plan.dwg", "application/acad", "application/acad"),
    ],
)
def test_tipul_vine_din_mime_apoi_din_extensie(nume, mime, asteptat):
    doc = dd.Document(id="x", nume=nume, mime=mime, cale=nume)
    assert doc.tip == asteptat


def test_un_format_necitit_nu_e_raportat_ca_gol(drive):
    drive({"radacina": [fisier("plan.dwg", "application/acad")]})
    with pytest.raises(dd.DriveIndisponibil, match="formatele citite"):
        dd.citeste("plan.dwg", folder="radacina")


# -- Extraction ------------------------------------------------------------


def test_pdf_cu_text_este_extras(drive, monkeypatch):
    drive({"radacina": [fisier("ghid.pdf")]})
    monkeypatch.setattr(dd, "_descarca", lambda doc: pdf_cu_text("coeficient de uzura 0,85"))
    doc, text = dd.citeste("ghid.pdf", folder="radacina")
    assert "coeficient de uzura 0,85" in text
    assert doc.cale == "ghid.pdf"


def test_pdf_scanat_se_raporteaza_ca_scanat(drive, monkeypatch):
    """The failure this module exists for: "" would read as an empty document."""
    drive({"radacina": [fisier("scan.pdf")]})
    monkeypatch.setattr(dd, "_descarca", lambda doc: pdf_scanat())
    with pytest.raises(dd.DriveIndisponibil, match="scanat"):
        dd.citeste("scan.pdf", folder="radacina")


def test_textul_extras_se_cacheaza_pe_modifiedtime(drive, monkeypatch):
    drive({"radacina": [fisier("ghid.pdf")]})
    descarcari = []

    def descarca(doc):
        descarcari.append(doc.id)
        return pdf_cu_text("valoarea de piata")

    monkeypatch.setattr(dd, "_descarca", descarca)
    dd.citeste("ghid.pdf", folder="radacina")
    dd.citeste("ghid.pdf", folder="radacina")
    assert len(descarcari) == 1

    # A re-upload changes modifiedTime, and that alone must invalidate.
    drive({"radacina": [fisier("ghid.pdf", modificat="2026-09-10T08:00:00.000Z")]})
    dd.listeaza("radacina", reincarca=True)
    dd.citeste("ghid.pdf", folder="radacina")
    assert len(descarcari) == 2


def test_google_sheet_spune_ca_exporta_doar_prima_fila(drive, monkeypatch):
    drive({"radacina": [fisier("costuri", "application/vnd.google-apps.spreadsheet")]})
    monkeypatch.setattr(dd, "_descarca", lambda doc: b"material,pret\ngresie,120\n")
    _, text = dd.citeste("costuri", folder="radacina")
    assert "prima fil" in text
    assert "gresie,120" in text


def test_text_in_codare_veche_nu_esueaza():
    assert "Bucuresti" in dd._text_simplu("Bucuresti".encode("cp1250"), "x.txt")


# -- Resolving -------------------------------------------------------------


def test_gaseste_dupa_bucata_din_nume(drive):
    drive({"radacina": [fisier("Catalog costuri constructii 2026.pdf")]})
    assert dd.gaseste("catalog costuri", folder="radacina").nume.startswith("Catalog")


def test_un_nume_ambiguu_nu_alege_in_tacere(drive):
    drive({"radacina": [fisier("catalog 2025.pdf"), fisier("catalog 2026.pdf")]})
    with pytest.raises(dd.DriveIndisponibil, match="mai multe documente"):
        dd.gaseste("catalog", folder="radacina")


def test_un_nume_negasit_enumera_ce_exista(drive):
    drive({"radacina": [fisier("ghid.pdf")]})
    with pytest.raises(dd.DriveIndisponibil) as exc:
        dd.gaseste("inexistent", folder="radacina")
    assert "ghid.pdf" in str(exc.value)


# -- Search ----------------------------------------------------------------


def test_cauta_raporteaza_documentele_pe_care_nu_le_a_putut_citi(drive, monkeypatch):
    drive(
        {
            "radacina": [
                fisier("ghid.pdf"),
                fisier("scan.pdf"),
                fisier("plan.dwg", "application/acad"),
            ]
        }
    )
    monkeypatch.setattr(
        dd,
        "_descarca",
        lambda doc: pdf_scanat() if doc.nume == "scan.pdf" else pdf_cu_text("coeficient seismic"),
    )
    rezultate = dd.cauta("coeficient", folder="radacina")
    gasite = [r for r in rezultate if "document" in r]
    necitite = next(r["documente_necitite"] for r in rezultate if "documente_necitite" in r)
    assert [r["document"] for r in gasite] == ["ghid.pdf"]
    assert {n["document"] for n in necitite} == {"scan.pdf", "plan.dwg"}


def test_cauta_intoarce_fragmentul_din_jurul_potrivirii(drive, monkeypatch):
    drive({"radacina": [fisier("ghid.pdf")]})
    monkeypatch.setattr(
        dd, "_descarca", lambda doc: pdf_cu_text("uzura fizica estimata 22 la suta")
    )
    (rezultat,) = [r for r in dd.cauta("uzura", folder="radacina") if "document" in r]
    assert "22 la suta" in rezultat["fragmente"][0]


# -- Errors ----------------------------------------------------------------


class _Raspuns:
    def __init__(self, status):
        self.status = status
        self.reason = "Not Found" if status == 404 else "Forbidden"


def eroare(status):
    from googleapiclient.errors import HttpError

    return HttpError(_Raspuns(status), b"{}")


def test_404_explica_ca_folderul_nu_e_partajat(monkeypatch):
    monkeypatch.setattr(dd, "identitate", lambda: "sa@proiect.iam.gserviceaccount.com")
    mesaj = str(dd._indisponibil(eroare(404), "folderul X"))
    assert "Share" in mesaj
    assert "sa@proiect.iam.gserviceaccount.com" in mesaj


def test_403_fara_alta_explicatie_trimite_la_politica_de_domeniu(monkeypatch):
    """The fallback branch: not a scope problem, not a disabled API."""
    monkeypatch.setattr(dd, "identitate", lambda: "sa@proiect.iam.gserviceaccount.com")
    mesaj = str(dd._indisponibil(eroare(403), "folderul X"))
    assert "Shared Drive" in mesaj
    assert "domain-wide delegation" in mesaj


# -- Auth ------------------------------------------------------------------


class _Cred:
    """Stand-in for end-user ADC: re-scopable in name only, like the real thing."""

    def __init__(self, quota=None):
        self.quota = quota

    def with_quota_project(self, proiect):
        return _Cred(quota=proiect)


def test_proiectul_de_cota_vine_din_mediu_nu_din_gcloud(monkeypatch):
    """ADC carries whatever `gcloud` last set — routinely an unrelated project."""
    monkeypatch.setattr(dd, "_adc", lambda: _Cred(quota="alt-proiect-de-pe-masina"))
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "website-formare-ai")
    monkeypatch.delenv("IMOBILIARE_DRIVE_IMPERSONATE", raising=False)
    assert dd._credentiale_drive().quota == "website-formare-ai"


def test_impersonarea_explicita_e_respectata(monkeypatch):
    monkeypatch.setattr(dd, "_adc", lambda: _Cred())
    monkeypatch.setenv("IMOBILIARE_DRIVE_IMPERSONATE", "sa@proiect.iam.gserviceaccount.com")
    monkeypatch.setattr(dd, "_impersoneaza", lambda sursa, tinta: ("impersonat", tinta))
    assert dd._credentiale_drive() == ("impersonat", "sa@proiect.iam.gserviceaccount.com")


def test_pe_metadata_server_se_auto_impersoneaza(monkeypatch):
    """Cloud Run's token is cloud-platform, which does not cover Drive."""
    from google.auth import compute_engine

    cred = compute_engine.Credentials(service_account_email="runtime@p.iam.gserviceaccount.com")
    monkeypatch.setattr(dd, "_adc", lambda: cred)
    monkeypatch.delenv("IMOBILIARE_DRIVE_IMPERSONATE", raising=False)
    monkeypatch.setattr(dd, "_impersoneaza", lambda sursa, tinta: ("impersonat", tinta))
    assert dd._credentiale_drive() == ("impersonat", "runtime@p.iam.gserviceaccount.com")


def test_adc_de_utilizator_e_folosit_ca_atare(monkeypatch):
    cred = _Cred()
    monkeypatch.setattr(dd, "_adc", lambda: cred)
    monkeypatch.delenv("IMOBILIARE_DRIVE_IMPERSONATE", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    assert dd._credentiale_drive() is cred


def test_403_de_scope_da_comanda_de_relogin(monkeypatch):
    monkeypatch.setattr(dd, "identitate", lambda: "eu@example.com")
    exc = eroare(403)
    exc.reason = "Insufficient Permission"
    mesaj = str(dd._indisponibil(exc, "folderul X"))
    assert "--scopes=" in mesaj
    assert "drive.readonly" in mesaj
    assert "serviceAccountTokenCreator" in mesaj


def test_403_de_api_dezactivat_trimite_la_proiectul_de_cota(monkeypatch):
    monkeypatch.setattr(dd, "identitate", lambda: "eu@example.com")
    exc = eroare(403)
    exc.reason = "Drive API has not been used in project 12345 before or it is disabled"
    mesaj = str(dd._indisponibil(exc, "folderul X"))
    assert "proiectul de cotă" in mesaj
    assert "GOOGLE_CLOUD_PROJECT" in mesaj
