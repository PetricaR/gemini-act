"""Reports uploaded to a bucket, and the link handed back.

The property under test throughout is that **this layer cannot cost you a
report**. A valuation spends minutes and real money before it gets here, so
every way the upload can go wrong has to come back as a note beside a report
that still exists — never as an exception, and never as a missing local path.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from imobiliare.mcp import storage


@pytest.fixture
def report(tmp_path: Path) -> Path:
    path = tmp_path / "evaluare-275807510.md"
    path.write_text("# Raport\n", encoding="utf-8")
    return path


@pytest.fixture
def bucket(monkeypatch) -> str:
    monkeypatch.setenv(storage.BUCKET_ENV, "rapoarte-test")
    return "rapoarte-test"


class _Blob:
    def __init__(self, name: str, fail_upload: bool = False, fail_sign: bool = False):
        self.name = name
        self.uploaded: tuple[str, str] | None = None
        self._fail_upload = fail_upload
        self._fail_sign = fail_sign

    def upload_from_filename(self, filename, content_type=None):
        if self._fail_upload:
            raise OSError("bucket does not exist")
        self.uploaded = (filename, content_type)

    def generate_signed_url(self, **kw):
        if self._fail_sign:
            raise PermissionError("missing signBlob")
        self.signed_with = kw
        return f"https://storage.example.com/{self.name}?sig=abc"


def _install(monkeypatch, blob: _Blob) -> None:
    """Stand in for `google.cloud.storage` and for ADC."""

    class _Bucket:
        def blob(self, name):
            blob.name = name
            return blob

    class _Client:
        def bucket(self, name):
            return _Bucket()

    import google.auth

    monkeypatch.setattr("google.cloud.storage.Client", lambda *a, **kw: _Client())

    class _Creds:
        service_account_email = "runtime@example.iam.gserviceaccount.com"
        token = "ya29.fake"

        def refresh(self, _request):
            return None

    monkeypatch.setattr(google.auth, "default", lambda *a, **kw: (_Creds(), "proj"))


# --- the switch ----------------------------------------------------------


def test_nothing_happens_without_a_bucket(monkeypatch, report):
    """The tools behaved this way before the bucket existed and must still."""
    monkeypatch.delenv(storage.BUCKET_ENV, raising=False)
    assert storage.enabled() is False
    assert storage.upload(report) is None

    result = {"raport": str(report)}
    storage.attach(result, report, "275807510")
    assert result == {"raport": str(report)}


def test_a_configured_bucket_turns_it_on(bucket):
    assert storage.enabled() is True
    assert storage.bucket_name() == "rapoarte-test"


# --- the happy path ------------------------------------------------------


def test_a_report_is_uploaded_and_comes_back_as_a_link(monkeypatch, bucket, report):
    blob = _Blob("x")
    _install(monkeypatch, blob)

    stored = storage.upload(report, "275807510")

    assert stored is not None
    assert stored.url.startswith("https://storage.example.com/")
    assert stored.uri.startswith("gs://rapoarte-test/")
    assert stored.note is None
    assert blob.uploaded[0] == str(report)
    # Served as markdown, not octet-stream, so the link opens instead of
    # downloading.
    assert blob.uploaded[1] == "text/markdown; charset=utf-8"


def test_the_link_is_signed_for_the_service_account_and_expires(monkeypatch, bucket, report):
    blob = _Blob("x")
    _install(monkeypatch, blob)

    stored = storage.upload(report, "275807510")

    assert blob.signed_with["version"] == "v4"
    assert blob.signed_with["method"] == "GET"
    assert blob.signed_with["service_account_email"].endswith(".iam.gserviceaccount.com")
    assert blob.signed_with["access_token"] == "ya29.fake"
    assert dt.datetime.fromisoformat(stored.expires_at) > dt.datetime.now(dt.UTC)


def test_the_object_is_dated_and_filed_under_the_listing(monkeypatch, bucket, report):
    blob = _Blob("x")
    _install(monkeypatch, blob)

    name = storage.upload(report, "275807510").object_name

    assert name.startswith("rapoarte/")
    assert "/275807510/" in name
    assert name.endswith(".md")
    assert dt.datetime.now(dt.UTC).strftime("%Y/%m/%d") in name


def test_a_second_run_does_not_overwrite_the_first(monkeypatch, bucket, report):
    """An already-issued link must keep resolving to what it resolved to."""
    _install(monkeypatch, _Blob("x"))
    first = storage.upload(report, "275807510").object_name
    second = storage.upload(report, "275807510").object_name
    assert first != second


def test_attach_namespaces_its_keys(monkeypatch, bucket, report):
    _install(monkeypatch, _Blob("x"))
    result: dict = {}
    storage.attach(result, report, "275807510", key="pdf")
    assert result["pdf_url"].startswith("https://")
    assert result["pdf_uri"].startswith("gs://")
    assert "pdf_expira" in result


# --- the ways it goes wrong ----------------------------------------------


def test_a_failed_upload_is_a_note_not_an_exception(monkeypatch, bucket, report):
    _install(monkeypatch, _Blob("x", fail_upload=True))

    stored = storage.upload(report, "275807510")

    assert stored is not None
    assert stored.url is None
    assert "nu" in stored.note.lower() or "eșuat" in stored.note
    # The report is still on disk and the caller must still be told where.
    assert report.is_file()


def test_a_report_that_cannot_be_signed_still_reports_where_it_went(monkeypatch, bucket, report):
    _install(monkeypatch, _Blob("x", fail_sign=True))

    stored = storage.upload(report, "275807510")

    assert stored.url is None
    assert stored.uri.startswith("gs://rapoarte-test/")
    assert "serviceAccountTokenCreator" in stored.note


def test_user_credentials_are_explained_rather_than_retried(monkeypatch, bucket, report):
    """A developer's ADC is an authorized_user, which cannot sign at all."""
    blob = _Blob("x")
    _install(monkeypatch, blob)

    import google.auth

    class _UserCreds:
        token = "ya29.user"

        def refresh(self, _request):
            return None

    monkeypatch.setattr(google.auth, "default", lambda *a, **kw: (_UserCreds(), "proj"))
    monkeypatch.delenv("IMOBILIARE_SIGNER_EMAIL", raising=False)

    stored = storage.upload(report, "275807510")

    assert stored.url is None
    assert "cont" in stored.note  # names the fix, in the report's own language
    assert blob.uploaded is not None  # the upload itself still happened


def test_a_missing_file_is_not_an_upload(monkeypatch, bucket, tmp_path):
    _install(monkeypatch, _Blob("x"))
    assert storage.upload(tmp_path / "nope.md") is None


# --- the expiry window ---------------------------------------------------


def test_the_ttl_is_clamped_to_what_v4_allows(monkeypatch, bucket):
    """Asking for more than seven days is a 400 at signing time."""
    monkeypatch.setenv(storage.TTL_ENV, "90")
    assert storage._ttl_days() == storage.MAX_TTL_DAYS
    monkeypatch.setenv(storage.TTL_ENV, "0")
    assert storage._ttl_days() == 1
    monkeypatch.setenv(storage.TTL_ENV, "3")
    assert storage._ttl_days() == 3


def test_an_unreadable_ttl_falls_back_rather_than_crashing(monkeypatch, bucket):
    monkeypatch.setenv(storage.TTL_ENV, "next tuesday")
    assert storage._ttl_days() == storage.DEFAULT_TTL_DAYS
