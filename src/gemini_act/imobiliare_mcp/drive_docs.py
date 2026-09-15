"""Read-only access to a Google Drive folder of reference documents.

The folder holds the paperwork a valuation leans on but cannot derive: cost
catalogues, ANEVAR guidance, developer specification sheets, negotiation
playbooks. `docx/` in this package is the same idea checked into the repo —
this module is the version that can be updated by dropping a file in Drive
instead of committing one.

Auth is Application Default Credentials scoped to `drive.readonly` — on Cloud
Run that is the runtime service account, with no key file involved, exactly as
`chat/client.py` does for the Chat API. Three consequences that are not
obvious:

* **ADC alone does not carry a Drive scope**, and the way it fails to is
  silent: `google.auth.default(scopes=...)` applies scopes only to credentials
  that can be re-scoped, so a developer's user ADC and Cloud Run's metadata
  token both come back happily without Drive and fail later at the API with
  403 `insufficientPermissions`. `_credentiale_drive` is where both cases are
  handled — read it before debugging a 403.
* **Drive access is not IAM.** No role on the GCP project grants it. The folder
  has to be *shared* with the service account's email the same way it would be
  shared with a colleague; until it is, the API reports the folder as
  **404 Not Found**, never 403. A "wrong folder id" error is therefore the
  expected symptom of a folder that was simply never shared, which is why
  `_indisponibil` names the principal that needs the share rather than quoting
  the raw error.
* **The service account is not a member of anyone's Workspace domain.** If the
  folder lives in a domain that blocks external sharing, that share is refused
  and the fix is a Shared Drive with the service account added as a member (or
  domain-wide delegation), not a retry.
* **A service account has no Drive storage quota of its own.** Everything here
  is therefore read-only by construction: `drive.readonly`, no copies, no
  conversions performed server-side.

Extraction is per format and each one has a floor it fails through rather than
guessing: a PDF with no text layer (a scan) reports itself as scanned instead
of returning an empty string that reads like an empty document, and a format
nothing here can read says so by name. Same rule the rest of this package
follows — a missing value must not render as a measured one.

Extracted text is cached on disk keyed by the file's `modifiedTime`, so a
re-uploaded document invalidates its own cache without a TTL, and the cache
degrades to "no cache" rather than failing when the filesystem is read-only
(Cloud Run) — see `paths.py`.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import google.auth
import google.auth.transport.requests
import google_auth_httplib2
import httplib2
from google.auth import compute_engine, impersonated_credentials
from google.auth.exceptions import DefaultCredentialsError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import paths

logger = logging.getLogger(__name__)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

# The reference folder this deployment reads. Overridable so a different
# deployment (or a test) can point somewhere else without a code change; a full
# Drive URL is accepted because that is what a browser hands you.
FOLDER_DEFAULT = "1G0SLX9clxcGnxgljBs3l7__nwMIMRenQ"

# How long a listing is reused before Drive is asked again. The folder changes
# when someone uploads to it — minutes of staleness are fine, and an agent turn
# that lists then reads three documents should not pay four round trips.
LISTING_TTL = 600.0

# Documents are read into an LLM context. Anything this large is a data file,
# not a document, and downloading it would cost more than it can possibly be
# worth here.
MAX_BYTES = 50 * 1024 * 1024

# Folder nesting is followed, but a cycle (a shortcut pointing at an ancestor)
# would otherwise walk forever.
MAX_DEPTH = 5

_FOLDER_MIME = "application/vnd.google-apps.folder"
_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

# Google-native formats have no bytes to download; Drive renders them on
# export. Markdown for Docs keeps headings and tables legible to the model;
# a spreadsheet exports only its *first* sheet as CSV, which is a real limit
# and is reported as one by `citeste`.
EXPORTURI: dict[str, tuple[str, ...]] = {
    "application/vnd.google-apps.document": ("text/markdown", "text/plain"),
    "application/vnd.google-apps.spreadsheet": ("text/csv",),
    "application/vnd.google-apps.presentation": ("text/plain",),
}

# What the model will accept as an image. Deliberately not `image/*`: GIF and
# SVG are not among them, and sending one back fails at the API rather than
# here, where the reason can be said out loud.
IMAGINI_GEMINI = (
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/heic",
    "image/heif",
)

_FIELDS = "id,name,mimeType,size,modifiedTime,md5Checksum,shortcutDetails"


class DriveIndisponibil(RuntimeError):
    """Drive could not serve the folder or the file — with the reason."""


class PdfFaraText(DriveIndisponibil):
    """A PDF whose pages carry no text layer — a scan.

    Carries the page count because that is what decides what to do next:
    Gemini can read the pages as images, but a full transcription only fits in
    one answer for a short document.
    """

    def __init__(self, cale: str, pagini: int) -> None:
        self.cale = cale
        self.pagini = pagini
        super().__init__(f"„{cale}” are {pagini} pagini fără strat de text — e un PDF scanat.")


@dataclass(frozen=True)
class Document:
    """One file in the folder, as listed — not yet read."""

    id: str
    nume: str
    mime: str
    cale: str
    modificat: str = ""
    marime: int | None = None
    subfolder: str = ""

    @property
    def citibil(self) -> bool:
        """Whether `citeste` can turn this file into text at all."""
        return _extractor_pentru(self.mime, self.nume) is not None

    @property
    def tip(self) -> str:
        """The format, named the way a person would name it."""
        return _tip_lizibil(self.mime, self.nume)

    def dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "nume": self.nume,
            "cale": self.cale,
            "tip": self.tip,
            "mime": self.mime,
            "marime_bytes": self.marime,
            "modificat": self.modificat,
            "citibil": self.citibil,
        }


# -- Auth and transport ----------------------------------------------------


LOGIN_CU_SCOPE = (
    "gcloud auth application-default login --scopes="
    "https://www.googleapis.com/auth/cloud-platform,"
    "https://www.googleapis.com/auth/drive.readonly"
)


def _adc() -> Any:
    """Application Default Credentials, asked for the Drive scope."""
    try:
        credentiale, _ = google.auth.default(scopes=[DRIVE_SCOPE])
    except DefaultCredentialsError as exc:
        raise DriveIndisponibil(
            "Nu există Application Default Credentials pentru Google Drive. "
            f"Local: `{LOGIN_CU_SCOPE}`. Pe Cloud Run: contul de serviciu al serviciului."
        ) from exc
    return credentiale


def _impersoneaza(sursa: Any, tinta: str) -> Any:
    """A Drive-scoped token minted for `tinta`, via the IAM Credentials API.

    This is the only way a service account without a key file gets a token
    carrying a Workspace scope: `generateAccessToken` will mint any scope for a
    service account, while the metadata server will not. Needs
    `roles/iam.serviceAccountTokenCreator` on the target — for the self-
    impersonation case below, the runtime account on itself, which
    `deploy/setup_gcp.sh` grants.
    """
    return impersonated_credentials.Credentials(
        source_credentials=sursa,
        target_principal=tinta,
        target_scopes=[DRIVE_SCOPE],
    )


def _email_metadata(credentiale: Any) -> str | None:
    """The runtime service account's real email, not the `default` alias."""
    email = getattr(credentiale, "service_account_email", None)
    if email in (None, "default"):
        try:
            credentiale.refresh(google.auth.transport.requests.Request())
        except Exception:  # noqa: BLE001
            return None
        email = getattr(credentiale, "service_account_email", None)
    return None if email in (None, "default") else str(email)


def _credentiale_drive() -> Any:
    """ADC turned into something that can actually call Drive.

    Two traps, and between them they are every "403 insufficientPermissions"
    this module can produce:

    * **`scopes=` is silently ignored for end-user credentials.** A developer's
      ADC is an `authorized_user` whose scopes are fixed in the refresh token at
      `gcloud auth application-default login` time; `google.auth.default(scopes=
      ...)` applies scopes only to credential types that can be re-scoped, and
      quietly returns the user's own token otherwise. The default gcloud login
      does not include a Drive scope, so the call fails at Drive with 403 rather
      than anywhere near the mistake. `LOGIN_CU_SCOPE` is the fix.
    * **The metadata server will not mint a Workspace scope.** On Cloud Run the
      runtime account's token is `cloud-platform`, which does not cover Drive,
      and the instance's scopes cannot be changed. So when the credentials come
      from the metadata server this self-impersonates through the IAM
      Credentials API, which *can* mint `drive.readonly`. That is a deliberate
      default rather than configuration: without it the deployed service 403s
      and the local one works, which is the worst of both.

    `IMOBILIARE_DRIVE_IMPERSONATE` forces the same path for any account — the
    way to read the folder locally as the deployed service reads it.
    """
    brut = _adc()

    # The quota project decides *which* project must have drive.googleapis.com
    # enabled and gets billed. ADC carries whatever `gcloud` last set, which on
    # a machine that works on several projects is routinely an unrelated one —
    # and that reads as a 403 about the wrong project entirely.
    if (proiect := os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()) and hasattr(
        brut, "with_quota_project"
    ):
        brut = brut.with_quota_project(proiect)

    if tinta := os.environ.get("IMOBILIARE_DRIVE_IMPERSONATE", "").strip():
        return _impersoneaza(brut, tinta)
    if isinstance(brut, compute_engine.Credentials):
        if email := _email_metadata(brut):
            return _impersoneaza(brut, email)
        raise DriveIndisponibil(
            "Rulez pe metadata server, dar nu am putut afla emailul contului de "
            "serviciu ca să cer un token cu scope de Drive. Pune "
            "IMOBILIARE_DRIVE_IMPERSONATE=<cont-de-serviciu> explicit."
        )
    return brut


@lru_cache(maxsize=1)
def _service_si_credentiale() -> tuple[Any, Any]:
    """The Drive service plus the credentials, built once for the process.

    The service object is metadata and safe to share; the credentials are the
    expensive part (an ADC lookup, then a token fetch) and google-auth is built
    to be reused. What is *not* shareable is the transport — see `_http`.
    """
    credentiale = _credentiale_drive()
    service = build("drive", "v3", credentials=credentiale, cache_discovery=False)
    return service, credentiale


def _http() -> Any:
    """A transport for exactly one request.

    `googleapiclient` runs on `httplib2`, whose `Http` object is explicitly not
    thread-safe, and these tools are called from a worker thread per agent turn
    with several turns in flight at once. Same reasoning, same shape as
    `chat/client.py::_new_http`.
    """
    _, credentiale = _service_si_credentiale()
    return google_auth_httplib2.AuthorizedHttp(credentiale, http=httplib2.Http())


def identitate() -> str:
    """Whoever this process is to Drive — the email that needs the share."""
    try:
        _, credentiale = _service_si_credentiale()
    except DriveIndisponibil:
        return "contul configurat"
    for atribut in ("service_account_email", "_service_account_email", "signer_email"):
        if email := getattr(credentiale, atribut, None):
            return str(email)
    return "contul ADC curent"


def _indisponibil(exc: HttpError, ce: str) -> DriveIndisponibil:
    """An `HttpError` turned into the sentence that says what to actually do."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    cine = identitate()
    if status == 404:
        return DriveIndisponibil(
            f"{ce} nu este vizibil pentru {cine}. În Drive, dă Share pe folder "
            f"către {cine} (rol Viewer). Drive răspunde 404, nu 403, pentru ceva "
            "ce nu ți-a fost partajat — deci „not found” aici înseamnă de regulă "
            "„nepartajat”, nu „id greșit”."
        )
    if status == 403:
        # A 403 from Drive is three different bugs wearing one status code, and
        # the three fixes have nothing to do with each other.
        detaliu = f"{getattr(exc, 'reason', '') or ''} {exc}"
        if "nsufficient" in detaliu:
            return DriveIndisponibil(
                f"Tokenul cu care rulez ({cine}) nu poartă scope-ul {DRIVE_SCOPE}; "
                "Drive răspunde 403 insufficientPermissions. Local, rulează:\n"
                f"  {LOGIN_CU_SCOPE}\n"
                "(`google.auth.default(scopes=...)` ignoră în tăcere scope-urile "
                "pentru credențiale de utilizator — ele sunt fixate în refresh token "
                "la login, iar loginul implicit nu include Drive.) Pe Cloud Run "
                "tokenul se obține prin impersonare, care are nevoie de "
                "roles/iam.serviceAccountTokenCreator pe contul de serviciu — vezi "
                "deploy/setup_gcp.sh."
            )
        if "SERVICE_DISABLED" in detaliu or "has not been used in project" in detaliu:
            return DriveIndisponibil(
                "drive.googleapis.com nu este activat pe proiectul de cotă cu care "
                f"merge acest token: {exc}. Proiectul de cotă vine din "
                "GOOGLE_CLOUD_PROJECT, iar dacă lipsește, din ce a scris ultima dată "
                "`gcloud auth application-default set-quota-project`."
            )
        return DriveIndisponibil(
            f"Drive a refuzat accesul la {ce} pentru {cine}: {exc}. Cel mai probabil "
            "politica Workspace a domeniului blochează partajarea către un cont de "
            "serviciu extern — atunci soluția e un Shared Drive cu contul adăugat ca "
            "membru, sau domain-wide delegation."
        )
    return DriveIndisponibil(f"Drive nu a putut servi {ce}: {exc}")


# -- Folder id -------------------------------------------------------------

_ID_DIN_URL = re.compile(r"/(?:folders|file/d|d)/([A-Za-z0-9_-]{10,})")


def folder_id(valoare: str | None = None) -> str:
    """The configured folder, accepting either a bare id or a Drive URL."""
    brut = (valoare or os.environ.get("IMOBILIARE_DRIVE_FOLDER_ID") or FOLDER_DEFAULT).strip()
    if m := _ID_DIN_URL.search(brut):
        return m.group(1)
    if "id=" in brut and (m := re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", brut)):
        return m.group(1)
    return brut


# -- Listing ---------------------------------------------------------------


def _cache_listare(fid: str):
    director = paths.ensure_dir(paths.cache_dir("drive"))
    return None if director is None else director / f"listare-{fid}.json"


def _copii(fid: str) -> list[dict[str, Any]]:
    """Every non-trashed child of one folder, following pagination."""
    service, _ = _service_si_credentiale()
    http = _http()
    iesire: list[dict[str, Any]] = []
    token = None
    while True:
        try:
            raspuns = (
                service.files()
                .list(
                    q=f"'{fid}' in parents and trashed = false",
                    # Both flags are required for a folder on a Shared Drive;
                    # without them the call succeeds and returns nothing, which
                    # is indistinguishable from an empty folder.
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    fields=f"nextPageToken, files({_FIELDS})",
                    pageSize=200,
                    orderBy="folder,name",
                    pageToken=token,
                )
                .execute(http=http)
            )
        except HttpError as exc:
            raise _indisponibil(exc, f"folderul {fid}") from exc
        iesire.extend(raspuns.get("files", []))
        if not (token := raspuns.get("nextPageToken")):
            return iesire


def _parcurge(fid: str, prefix: str, adancime: int, vazute: set[str]) -> list[Document]:
    if adancime > MAX_DEPTH or fid in vazute:
        return []
    vazute.add(fid)
    documente: list[Document] = []
    for brut in _copii(fid):
        mime = brut.get("mimeType", "")
        nume = brut.get("name", "")
        # A shortcut is a pointer, not a file: read through it to the target so
        # a folder organised with shortcuts behaves like one organised with
        # copies.
        if mime == _SHORTCUT_MIME:
            tinta = brut.get("shortcutDetails") or {}
            if not (tinta_id := tinta.get("targetId")):
                continue
            mime = tinta.get("targetMimeType", "")
            brut = {**brut, "id": tinta_id, "mimeType": mime}
        if mime == _FOLDER_MIME:
            documente.extend(_parcurge(brut["id"], f"{prefix}{nume}/", adancime + 1, vazute))
            continue
        marime = brut.get("size")
        documente.append(
            Document(
                id=brut["id"],
                nume=nume,
                mime=mime,
                cale=f"{prefix}{nume}",
                modificat=brut.get("modifiedTime", ""),
                marime=int(marime) if marime is not None else None,
                subfolder=prefix.rstrip("/"),
            )
        )
    return documente


def listeaza(folder: str | None = None, reincarca: bool = False) -> list[Document]:
    """Every readable file in the folder, subfolders included.

    Cached for `LISTING_TTL` so a turn that lists and then reads pays one round
    trip rather than one per tool call.
    """
    fid = folder_id(folder)
    cache = _cache_listare(fid)
    if cache is not None and not reincarca and cache.exists():
        if time.time() - cache.stat().st_mtime < LISTING_TTL:
            try:
                brut = json.loads(cache.read_text(encoding="utf-8"))
                return [Document(**d) for d in brut]
            except (OSError, ValueError, TypeError):
                pass
    documente = _parcurge(fid, "", 0, set())
    if cache is not None:
        try:
            cache.write_text(
                json.dumps([d.__dict__ for d in documente], ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
    return documente


# -- Resolving a document by whatever the caller typed ----------------------


def _normalizeaza(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def gaseste(identificator: str, folder: str | None = None) -> Document:
    """Resolve a file id, a full path, or part of a name to one document.

    The model quotes a document by the name it saw in a listing far more often
    than by id, and an ambiguous name must not silently pick the first match —
    it raises and names the candidates instead.
    """
    cautat = identificator.strip()
    documente = listeaza(folder)
    for d in documente:
        if d.id == cautat or d.cale == cautat or d.nume == cautat:
            return d
    tinta = _normalizeaza(cautat)
    if not tinta:
        raise DriveIndisponibil("Nu s-a dat niciun nume sau id de document.")
    potriviri = [d for d in documente if tinta in _normalizeaza(d.cale)]
    if len(potriviri) == 1:
        return potriviri[0]
    if not potriviri:
        # A bare Drive id for a file outside the folder is still legitimate.
        if re.fullmatch(r"[A-Za-z0-9_-]{25,}", cautat):
            return _metadate(cautat)
        disponibile = ", ".join(sorted(d.cale for d in documente)[:20]) or "(folder gol)"
        raise DriveIndisponibil(
            f"Niciun document nu se potrivește cu „{identificator}”. În folder: {disponibile}"
        )
    nume = ", ".join(sorted(d.cale for d in potriviri)[:10])
    raise DriveIndisponibil(
        f"„{identificator}” se potrivește cu mai multe documente: {nume}. Alege unul."
    )


def _metadate(file_id: str) -> Document:
    service, _ = _service_si_credentiale()
    try:
        brut = (
            service.files()
            .get(fileId=file_id, fields=_FIELDS, supportsAllDrives=True)
            .execute(http=_http())
        )
    except HttpError as exc:
        raise _indisponibil(exc, f"fișierul {file_id}") from exc
    marime = brut.get("size")
    return Document(
        id=brut["id"],
        nume=brut.get("name", file_id),
        mime=brut.get("mimeType", ""),
        cale=brut.get("name", file_id),
        modificat=brut.get("modifiedTime", ""),
        marime=int(marime) if marime is not None else None,
    )


# -- Extraction ------------------------------------------------------------


def _extractor_pentru(mime: str, nume: str) -> str | None:
    """Which reader handles this file, by mime type then by extension.

    Drive's mime type is authoritative when it is specific, but files uploaded
    by a browser routinely arrive as `application/octet-stream`, so the
    extension is the fallback rather than the other way round.
    """
    if mime in EXPORTURI:
        return "export"
    if mime == "application/pdf":
        return "pdf"
    if mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",):
        return "docx"
    if mime.startswith("text/") or mime in ("application/json", "application/xml"):
        return "text"
    if mime in IMAGINI_GEMINI:
        return "imagine"
    sufix = nume.rsplit(".", 1)[-1].lower() if "." in nume else ""
    return {
        "pdf": "pdf",
        "docx": "docx",
        "txt": "text",
        "md": "text",
        "csv": "text",
        "json": "text",
        "xml": "text",
        "html": "text",
        "png": "imagine",
        "jpg": "imagine",
        "jpeg": "imagine",
        "webp": "imagine",
        "heic": "imagine",
        "heif": "imagine",
    }.get(sufix)


def _tip_lizibil(mime: str, nume: str) -> str:
    return {
        "export": "document Google",
        "pdf": "PDF",
        "docx": "Word (.docx)",
        "text": "text",
        "imagine": "imagine",
    }.get(_extractor_pentru(mime, nume) or "", mime or "necunoscut")


def _descarca(doc: Document) -> bytes:
    service, _ = _service_si_credentiale()
    http = _http()
    if doc.marime is not None and doc.marime > MAX_BYTES:
        raise DriveIndisponibil(
            f"„{doc.cale}” are {doc.marime / 1e6:.0f} MB, peste limita de "
            f"{MAX_BYTES / 1e6:.0f} MB pentru citire."
        )
    try:
        if doc.mime in EXPORTURI:
            ultima: HttpError | None = None
            for format_export in EXPORTURI[doc.mime]:
                try:
                    return (
                        service.files()
                        .export_media(fileId=doc.id, mimeType=format_export)
                        .execute(http=http)
                    )
                except HttpError as exc:
                    # Not every Docs export format is available for every
                    # document (text/markdown is the newest); fall through to
                    # the next one rather than failing the read.
                    ultima = exc
            raise ultima if ultima else DriveIndisponibil(f"Export eșuat pentru „{doc.cale}”.")
        return service.files().get_media(fileId=doc.id, supportsAllDrives=True).execute(http=http)
    except HttpError as exc:
        raise _indisponibil(exc, f"documentul „{doc.cale}”") from exc


def _text_pdf(date: bytes, cale: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise DriveIndisponibil("pypdf nu este instalat; rulează `uv sync`.") from exc

    try:
        reader = PdfReader(io.BytesIO(date))
        if reader.is_encrypted:
            # An owner password with an empty user password is common for
            # documents published as "no printing"; a real password is not
            # something this tool can invent.
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise DriveIndisponibil(f"„{cale}” este criptat cu parolă.") from exc
        pagini = [(p.extract_text() or "").strip() for p in reader.pages]
    except DriveIndisponibil:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DriveIndisponibil(f"„{cale}” nu a putut fi citit ca PDF: {exc}") from exc

    text = "\n\n".join(f"--- pagina {i} ---\n{p}" for i, p in enumerate(pagini, 1) if p)
    if not text.strip():
        # An empty string here would read as an empty document. It is almost
        # always a scan: pages of images with no text layer. `citeste` catches
        # this and hands the pages to Gemini, which reads them as images.
        raise PdfFaraText(cale, len(pagini))
    return text


def _text_docx(date: bytes, cale: str) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise DriveIndisponibil("python-docx nu este instalat; rulează `uv sync`.") from exc

    try:
        document = docx.Document(io.BytesIO(date))
    except Exception as exc:  # noqa: BLE001
        raise DriveIndisponibil(f"„{cale}” nu a putut fi citit ca .docx: {exc}") from exc
    bucati = [p.text for p in document.paragraphs if p.text.strip()]
    for tabel in document.tables:
        for rand in tabel.rows:
            celule = [c.text.strip() for c in rand.cells]
            if any(celule):
                bucati.append(" | ".join(celule))
    return "\n".join(bucati)


def _text_simplu(date: bytes, cale: str) -> str:
    for codare in ("utf-8", "utf-8-sig", "cp1250", "latin-1"):
        try:
            return date.decode(codare)
        except UnicodeDecodeError:
            continue
    raise DriveIndisponibil(f"„{cale}” nu este text într-o codare cunoscută.")


# -- Gemini reads the pages itself -----------------------------------------
#
# `pypdf` extracts a PDF's *text layer*. Gemini does not need one: it takes the
# document as pages and reads them the way a person does — text, tables,
# charts, diagrams, and scans with no text layer at all. For the documents this
# folder holds (cost catalogues, valuation guidance) that difference is not
# marginal: a table flattened into a line of text loses which number belongs to
# which column, and a chart disappears entirely.
#
# It is used in two places: as the floor under `citeste` when a PDF turns out
# to be a scan, and as `intreaba`, where the model is asked a question about
# the document directly and never produces a transcription at all.

# Vertex refuses a document larger than this inline; past it the file has to go
# through a Cloud Storage URI, which is a deployment decision this module does
# not get to make on its own.
MAX_INLINE_GEMINI = 15 * 1024 * 1024

# The model's own ceiling, quoted so the failure names it rather than arriving
# as an opaque 400.
MAX_PAGINI_GEMINI = 1000

# How long a scan may be before `citeste` refuses to transcribe it. The binding
# constraint is the *answer*, not the document: a page costs ~258 input tokens,
# which is cheap, but a transcription has to fit in one response, and past a
# few dozen pages it does not — it truncates, and a truncated transcription
# that reads as a whole document is worse than a refusal. Long documents are
# what `intreaba` is for: the answer stays short however long the source is.
MAX_PAGINI_TRANSCRIERE = int(os.environ.get("IMOBILIARE_DRIVE_MAX_PAGINI_OCR") or 30)

TRANSCRIERE = (
    "Transcrie integral acest document în Markdown, în ordinea paginilor. "
    "Păstrează tabelele ca tabele Markdown și titlurile ca titluri. Nu rezuma, "
    "nu comenta, nu adăuga nimic de la tine: doar conținutul documentului. "
    "Marchează fiecare pagină cu o linie `--- pagina N ---`."
)


TRANSCRIERE_IMAGINE = (
    "Descrie ce conține această imagine și transcrie integral orice text vizibil "
    "în ea, păstrând tabelele ca tabele Markdown. Nu rezuma și nu adăuga nimic "
    "de la tine."
)


def _gemini(date: bytes, doc: Document, intrebare: str) -> str:
    """Ask Gemini about one document, handing it the file as pages."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise DriveIndisponibil(
            "google-genai nu este disponibil, deci documentul nu poate fi citit vizual."
        ) from exc

    from gemini_act.config import get_settings

    from . import viziune

    if len(date) > MAX_INLINE_GEMINI:
        raise DriveIndisponibil(
            f"„{doc.cale}” are {len(date) / 1e6:.0f} MB; Vertex acceptă inline cel mult "
            f"{MAX_INLINE_GEMINI / 1e6:.0f} MB. Peste atât fișierul trebuie trecut printr-un "
            "URI de Cloud Storage."
        )

    settings = get_settings()
    # Deliberately the same client builder as the visual analysis: it is the one
    # place that knows this service configures Vertex through `.env` without
    # exporting it, and solving that twice, differently, is how the two drift.
    client = viziune._client(genai, settings)
    parts = [
        types.Part(inline_data=types.Blob(data=date, mime_type=doc.mime or "application/pdf")),
        types.Part(text=intrebare),
    ]
    try:
        response = client.models.generate_content(
            model=settings.imobiliare_vision_model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
            ),
        )
    except Exception as exc:  # noqa: BLE001
        raise DriveIndisponibil(f"Gemini nu a putut citi „{doc.cale}”: {exc}") from exc

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        # An empty answer is a refusal or a safety block, not an empty document.
        raise DriveIndisponibil(
            f"Gemini a întors un răspuns gol pentru „{doc.cale}” "
            f"({getattr(response, 'prompt_feedback', None) or 'fără motiv raportat'})."
        )
    return text


def intreaba(identificator: str | Document, intrebare: str, folder: str | None = None) -> str:
    """Put a question to the document itself, with the model looking at the pages.

    Better than reading the extracted text and asking the question over it
    whenever the answer lives in a table, a chart or a layout — and the only
    thing that works at all on a document too long to transcribe.
    """
    if not intrebare.strip():
        raise DriveIndisponibil("Întrebarea este goală.")
    doc = identificator if isinstance(identificator, Document) else gaseste(identificator, folder)
    if _extractor_pentru(doc.mime, doc.nume) == "export":
        # A Google-native document has no bytes to hand over; its exported text
        # is the whole document anyway.
        _, text = citeste(doc, folder)
        raise DriveIndisponibil(
            f"„{doc.cale}” este un document Google, nu un fișier — citește-l cu "
            f"citeste_document_drive ({len(text)} caractere) și răspunde din text."
        )
    return _gemini(_descarca(doc), doc, intrebare)


# -- Reading, with the cache in front --------------------------------------


def _cheie_cache(doc: Document) -> str:
    """A cache name that changes exactly when the document does.

    `modifiedTime` is what makes this a cache rather than a copy: re-uploading
    a file invalidates it without anyone remembering to, and no TTL can be
    wrong.
    """
    stamp = re.sub(r"[^0-9]", "", doc.modificat) or "0"
    return f"{doc.id}-{stamp}.txt"


def citeste(identificator: str | Document, folder: str | None = None) -> tuple[Document, str]:
    """One document's full text. Returns the document it resolved to and the text."""
    doc = identificator if isinstance(identificator, Document) else gaseste(identificator, folder)

    director = paths.ensure_dir(paths.cache_dir("drive"))
    cache = director / _cheie_cache(doc) if director else None
    if cache is not None and cache.exists():
        try:
            return doc, cache.read_text(encoding="utf-8")
        except OSError:
            pass

    tip = _extractor_pentru(doc.mime, doc.nume)
    if tip is None:
        raise DriveIndisponibil(
            f"„{doc.cale}” este {doc.mime or 'de tip necunoscut'} — formatele citite aici "
            "sunt PDF, Google Docs/Sheets/Slides, .docx, text (txt/md/csv/json/xml/html) "
            "și imagini (png/jpeg/webp/heic)."
        )

    date = _descarca(doc)
    if tip == "pdf":
        try:
            text = _text_pdf(date, doc.cale)
        except PdfFaraText as scan:
            # No text layer. Gemini can still read the pages as images — within
            # the length a single transcription can honestly cover.
            if scan.pagini > MAX_PAGINI_TRANSCRIERE:
                raise DriveIndisponibil(
                    f"{scan} Are prea multe pagini ({scan.pagini}) pentru o transcriere "
                    f"într-un singur răspuns (limita e {MAX_PAGINI_TRANSCRIERE}). Pune o "
                    "întrebare punctuală despre el cu intreaba_document_drive, care îl "
                    "citește vizual fără să-l transcrie."
                ) from scan
            text = (
                f"[Document scanat, {scan.pagini} pagini: fără strat de text. "
                "Textul de mai jos este transcris vizual de model, nu extras din "
                "fișier — citește-l ca pe o transcriere, nu ca pe original.]\n\n"
            ) + _gemini(date, doc, TRANSCRIERE)
    elif tip == "imagine":
        # An image has no text to extract at all; the model is the only reader.
        text = (
            "[Imagine: textul de mai jos este citit vizual de model, nu extras "
            "dintr-un fișier de text.]\n\n"
        ) + _gemini(date, doc, TRANSCRIERE_IMAGINE)
    elif tip == "docx":
        text = _text_docx(date, doc.cale)
    else:
        text = _text_simplu(date, doc.cale)
    if doc.mime == "application/vnd.google-apps.spreadsheet":
        text = (
            "[Export CSV: Drive exportă doar prima filă a unui Google Sheet. "
            "Dacă documentul are mai multe file, restul nu sunt aici.]\n\n" + text
        )

    if cache is not None:
        try:
            # Drop the previous version of this same document, so the cache
            # tracks the folder instead of accumulating every revision.
            for vechi in director.glob(f"{doc.id}-*.txt"):
                if vechi.name != cache.name:
                    vechi.unlink(missing_ok=True)
            cache.write_text(text, encoding="utf-8")
        except OSError:
            pass
    return doc, text


def cauta(termen: str, folder: str | None = None, context: int = 320) -> list[dict[str, Any]]:
    """Grep across every readable document, with a snippet per hit.

    The point is to avoid pulling whole PDFs into the model's context to answer
    a question one paragraph settles. Documents that cannot be read are
    reported rather than skipped silently — a corpus that is quietly half
    searched is worse than one that says which half.
    """
    tinta = termen.strip().lower()
    if not tinta:
        raise DriveIndisponibil("Termenul de căutare este gol.")
    rezultate: list[dict[str, Any]] = []
    necitite: list[dict[str, str]] = []
    for doc in listeaza(folder):
        if not doc.citibil:
            necitite.append({"document": doc.cale, "motiv": f"format {doc.mime}"})
            continue
        try:
            _, text = citeste(doc)
        except DriveIndisponibil as exc:
            necitite.append({"document": doc.cale, "motiv": str(exc)})
            continue
        jos = text.lower()
        pozitii: list[int] = []
        start = jos.find(tinta)
        while start != -1 and len(pozitii) < 5:
            pozitii.append(start)
            start = jos.find(tinta, start + len(tinta))
        if not pozitii:
            continue
        fragmente = [
            " ".join(text[max(0, p - context // 2) : p + context].split()) for p in pozitii
        ]
        rezultate.append(
            {"document": doc.cale, "id": doc.id, "aparitii": len(pozitii), "fragmente": fragmente}
        )
    if necitite:
        rezultate.append({"documente_necitite": necitite})
    return rezultate
