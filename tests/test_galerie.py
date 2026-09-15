"""`galerie.contact_sheet` -- tiling a listing's gallery into one image."""

from __future__ import annotations

import io

import httpx
import pytest

from imobiliare.mcp.galerie import contact_sheet

PIL = pytest.importorskip("PIL", reason="contact_sheet is a no-op without Pillow")


def _jpeg(width: int = 800, height: int = 600, colour: str = "red") -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def serve(monkeypatch):
    """Serve a fixed body for every gallery URL, without touching the network."""

    def _serve(body: bytes | None, status: int = 200):
        # `.request`, not `.get`: contact_sheet fetches through
        # `throttle.fetch_image` now, so that is where the network is.
        def fake_request(self, method, url, **kwargs):
            if body is None:
                raise httpx.ConnectError("unreachable")
            return httpx.Response(status, content=body, request=httpx.Request(method, url))

        monkeypatch.setattr(httpx.Client, "request", fake_request)

    return _serve


def test_empty_url_list_returns_none(tmp_path):
    assert contact_sheet([], tmp_path / "sheet.jpg") is None


def test_tiles_downloaded_photos_into_one_sheet(serve, tmp_path):
    serve(_jpeg())
    dest = tmp_path / "sheet.jpg"

    out = contact_sheet([f"https://img/{i}.jpg" for i in range(5)], dest, columns=3)

    assert out == dest
    assert dest.exists()
    from PIL import Image

    with Image.open(dest) as im:
        # 5 photos at 3 per row -> 2 rows of the default 420x315 cell.
        assert im.size == (3 * 420, 2 * 315)


def test_destination_directory_is_created(serve, tmp_path):
    serve(_jpeg())
    dest = tmp_path / "nested" / "deeper" / "sheet.jpg"
    assert contact_sheet(["https://img/0.jpg"], dest) == dest
    assert dest.exists()


def test_one_unreachable_photo_does_not_lose_the_sheet(monkeypatch, tmp_path):
    calls = {"n": 0}

    def flaky_request(self, method, url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise httpx.ConnectError("unreachable")
        return httpx.Response(200, content=_jpeg(), request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.Client, "request", flaky_request)
    dest = tmp_path / "sheet.jpg"
    assert contact_sheet([f"https://img/{i}.jpg" for i in range(3)], dest) == dest


def test_all_photos_unreachable_returns_none(serve, tmp_path):
    serve(None)
    assert contact_sheet(["https://img/0.jpg"], tmp_path / "sheet.jpg") is None


def test_non_200_responses_are_skipped(serve, tmp_path):
    serve(b"not an image", status=404)
    assert contact_sheet(["https://img/0.jpg"], tmp_path / "sheet.jpg") is None
