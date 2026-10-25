"""Reports, kept somewhere the caller can actually reach them.

`paths.reports_dir()` stages a report on local disk, which is the right place
for it right up until someone else has to read it. On Cloud Run that path is
`/tmp` — instance-local, in-memory, and gone when the instance recycles — and
an MCP client is in a different process on a different machine anyway, so
handing it `/tmp/imobiliare-rapoarte/evaluare-275807510.md` tells it nothing it
can open. This module uploads the file to a bucket and returns a link.

Four decisions worth stating:

**A signed URL, not a public object.** A valuation names a property, its
address, what is being asked for it and what we think it is worth — including
the walk-away price. That is a document you hand to one person, not one you
leave on a public URL for as long as the bucket exists. A V4 signed URL can be
pasted into a chat, opened without a Google account, and stops working on its
own. Seven days is both the default and the ceiling, because V4 does not permit
longer.

**Signing works without a private key.** The runtime account's credentials come
from the metadata server and have no key to sign with, so `generate_signed_url`
is given the account's own email and access token and signs through the IAM
`signBlob` API instead. That needs `roles/iam.serviceAccountTokenCreator` on
itself, which `deploy/setup_gcp.sh` already grants for the Drive scope — the
same binding, reused. On a developer's machine ADC is usually a *user* account,
which cannot sign at all; that degrades to the `gs://` URI rather than failing.

**Every failure here is soft.** A valuation spends minutes of wall clock and
real money on vision calls. Losing it because a bucket name is wrong, or the
role was never granted, would be a much worse bug than not having a link — so
an upload that fails is reported as a note beside the report, never raised. The
local path stays in the answer either way.

**Off by default.** With no bucket configured nothing here runs and the tools
behave exactly as they did before.
"""

from __future__ import annotations

import datetime as dt
import logging
import mimetypes
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Bare `IMOBILIARE_`, not `GEMINI_ACT_`, to sit beside `IMOBILIARE_REPORTS_DIR`
# and `IMOBILIARE_CACHE_DIR` in `paths.py`: this is the same concern those are
# — where output goes — and the deploy script passes all three together.
BUCKET_ENV = "IMOBILIARE_REPORTS_BUCKET"
PREFIX_ENV = "IMOBILIARE_REPORTS_PREFIX"
TTL_ENV = "IMOBILIARE_REPORTS_URL_TTL_DAYS"

# Google caps a V4 signed URL at seven days. Asking for more is a 400 at
# signing time, so the value is clamped rather than passed through.
MAX_TTL_DAYS = 7
DEFAULT_TTL_DAYS = 7

# `mimetypes` guesses `text/markdown` inconsistently across Python builds, and
# a report served as `application/octet-stream` downloads instead of opening.
_CONTENT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".html": "text/html; charset=utf-8",
}


@dataclass(frozen=True)
class Stored:
    """Where a report went, and how to open it."""

    bucket: str
    object_name: str
    uri: str
    url: str | None
    expires_at: str | None
    note: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "url": self.url,
            "uri": self.uri,
            "expira": self.expires_at,
            "nota": self.note,
        }


def bucket_name() -> str:
    return (os.environ.get(BUCKET_ENV) or "").strip()


def enabled() -> bool:
    """Whether a bucket is configured. Nothing here runs when it is not."""
    return bool(bucket_name())


def _ttl_days() -> int:
    try:
        days = int(os.environ.get(TTL_ENV) or DEFAULT_TTL_DAYS)
    except ValueError:
        days = DEFAULT_TTL_DAYS
    return max(1, min(days, MAX_TTL_DAYS))


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _CONTENT_TYPES:
        return _CONTENT_TYPES[suffix]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def object_name(path: Path, listing_id: str | None = None) -> str:
    """A path in the bucket that no second run can collide with.

    Dated so the bucket stays browsable, and suffixed with a random token so
    re-valuing the same listing writes a new object. Overwriting would silently
    change what an already-issued link resolves to, which for a document
    someone is negotiating against is worse than keeping both.
    """
    prefix = (os.environ.get(PREFIX_ENV) or "rapoarte").strip("/")
    today = dt.datetime.now(dt.UTC).strftime("%Y/%m/%d")
    parts = [prefix, today]
    if listing_id:
        parts.append(str(listing_id))
    folder = "/".join(parts)
    return f"{folder}/{path.stem}-{secrets.token_urlsafe(6)}{path.suffix}"


def _signed_url(blob, expiry: dt.timedelta) -> tuple[str | None, str | None]:
    """A V4 signed URL, or the reason there isn't one.

    Returns `(url, note)`. The note is what the caller shows instead of the
    link, so it has to name the fix rather than the exception.
    """
    import google.auth
    import google.auth.transport.requests

    try:
        credentials, _ = google.auth.default()
        # Needed for the token; also what populates `service_account_email`
        # on the metadata-server credentials.
        credentials.refresh(google.auth.transport.requests.Request())
        email = getattr(credentials, "service_account_email", None)
        if not email or email == "default":
            email = os.environ.get("IMOBILIARE_SIGNER_EMAIL") or email
        if not email:
            return None, (
                "Raportul este încărcat, dar linkul semnat nu a putut fi creat: "
                "credențialele locale sunt ale unui utilizator, nu ale unui cont "
                "de serviciu. Deschide obiectul prin gs:// sau rulează cu un cont "
                "de serviciu."
            )
        url = blob.generate_signed_url(
            version="v4",
            expiration=expiry,
            method="GET",
            service_account_email=email,
            access_token=credentials.token,
        )
        return url, None
    except Exception as exc:  # noqa: BLE001 - a missing link is not a failed report
        logger.warning("Could not sign a URL for %s: %s", blob.name, exc)
        return None, (
            f"Raportul este încărcat, dar linkul semnat nu a putut fi creat "
            f"({type(exc).__name__}). Contul de serviciu are nevoie de "
            f"roles/iam.serviceAccountTokenCreator pe el însuși."
        )


def upload(path: Path, listing_id: str | None = None) -> Stored | None:
    """Put a report in the bucket and return how to reach it.

    Args:
        path: The file just written to local disk.
        listing_id: Folded into the object name so the bucket is browsable by
            property.

    Returns:
        A `Stored`, or `None` when no bucket is configured or the file is not
        there. Never raises: an upload that fails is a note on a report that
        still exists, not a failed valuation.
    """
    bucket = bucket_name()
    if not bucket:
        return None
    if not path.is_file():
        logger.warning("Nothing to upload at %s", path)
        return None

    name = object_name(path, listing_id)
    uri = f"gs://{bucket}/{name}"
    try:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(bucket).blob(name)
        blob.upload_from_filename(str(path), content_type=_content_type(path))
    except Exception as exc:  # noqa: BLE001 - see the module docstring
        logger.warning("Could not upload %s to %s: %s", path, uri, exc)
        return Stored(
            bucket=bucket,
            object_name=name,
            uri=uri,
            url=None,
            expires_at=None,
            note=(
                f"Raportul a fost generat local ({path}), dar încărcarea în "
                f"gs://{bucket} a eșuat: {type(exc).__name__}: {exc}"
            ),
        )

    days = _ttl_days()
    url, note = _signed_url(blob, dt.timedelta(days=days))
    expires = (
        (dt.datetime.now(dt.UTC) + dt.timedelta(days=days)).replace(microsecond=0).isoformat()
        if url
        else None
    )
    return Stored(
        bucket=bucket,
        object_name=name,
        uri=uri,
        url=url,
        expires_at=expires,
        note=note,
    )


def attach(result: dict, path: Path, listing_id: str | None = None, *, key: str = "raport") -> None:
    """Upload `path` and record the link on `result`, in place.

    Writes `<key>_url`, `<key>_uri` and `<key>_expira`, plus `<key>_nota` when
    something went wrong. The keys are namespaced by `key` so a tool returning
    both a markdown report and a PDF can carry both links unambiguously.
    """
    stored = upload(path, listing_id)
    if stored is None:
        return
    result[f"{key}_url"] = stored.url
    result[f"{key}_uri"] = stored.uri
    if stored.expires_at:
        result[f"{key}_expira"] = stored.expires_at
    if stored.note:
        result[f"{key}_nota"] = stored.note
