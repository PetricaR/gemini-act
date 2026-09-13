"""`imobiliare_mcp.throttle` -- pacing, memoisation and block detection.

The bug these guard against: imobiliare.ro answers an over-eager client with
an anti-bot interstitial served as a *200 with an HTML body*, so a client that
only checks the status code parses the block page as data and keeps going.
"""

from __future__ import annotations

import threading
import time

import httpx
import pytest

from gemini_act.imobiliare_mcp import throttle

INTERSTITIAL = (
    "<html><body><h1>Am detectat o anomalie în comportamentul browserului "
    "dumneavoastră.</h1><p>frecvența de vizualizare a anunțurilor este mai "
    "ridicată decât a majorității utilizatorilor noștri</p>"
    "<p>ID: 55e7bc49-4462-39c0-25ed-467ec78ebdfb</p></body></html>"
)


def _responder(monkeypatch, make_response):
    """Answer every request from `make_response(method, url)`, no network."""
    calls: list[str] = []

    def fake_request(self, method, url, **kwargs):
        calls.append(str(url))
        return make_response(method, str(url))

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    return calls


def _html(status: int = 200, body: str = INTERSTITIAL) -> httpx.Response:
    return httpx.Response(
        status,
        content=body.encode(),
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", "https://www.imobiliare.ro/x"),
    )


def _json(status: int = 200, payload: str = '{"listings": []}') -> httpx.Response:
    return httpx.Response(
        status,
        content=payload.encode(),
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "https://www.imobiliare.ro/x"),
    )


def test_the_interstitial_raises_rather_than_being_parsed_as_data(monkeypatch):
    """It arrives as HTTP 200. Returning it would hand the caller a block page
    to parse, which is how this failed silently in the first place."""
    monkeypatch.setattr(throttle, "RETRIES", 1)
    calls = _responder(monkeypatch, lambda method, url: _html())

    with pytest.raises(throttle.Blocked, match="anti-bot"):
        throttle.request("GET", "https://www.imobiliare.ro/api/x")

    # One initial attempt plus RETRIES: bounded, no storm.
    assert len(calls) == 2


def test_429_is_a_block(monkeypatch):
    monkeypatch.setattr(throttle, "RETRIES", 0)
    _responder(monkeypatch, lambda method, url: _json(429, "{}"))
    with pytest.raises(throttle.Blocked):
        throttle.request("GET", "https://www.imobiliare.ro/api/x")


def test_a_json_403_is_not_a_block(monkeypatch):
    """The AI host returns a JSON 403 for an expired session, and
    `client._post` turns that into a far more useful SessionError. Treating
    every 403 as a block would swallow that message."""
    _responder(monkeypatch, lambda method, url: _json(403, '{"error": "Forbidden"}'))
    response = throttle.request("POST", "https://api.ai-search.ringier.tech/api/search")
    assert response.status_code == 403


def test_a_403_carrying_the_interstitial_is_a_block(monkeypatch):
    monkeypatch.setattr(throttle, "RETRIES", 0)
    _responder(monkeypatch, lambda method, url: _html(403))
    with pytest.raises(throttle.Blocked):
        throttle.request("GET", "https://www.imobiliare.ro/api/x")


def test_requests_to_one_host_are_spaced_out(monkeypatch):
    monkeypatch.setattr(throttle, "MIN_INTERVAL", 0.05)
    monkeypatch.setattr(throttle, "JITTER", 0.0)
    _responder(monkeypatch, lambda method, url: _json())

    started = time.monotonic()
    for _ in range(4):
        throttle.request("GET", "https://www.imobiliare.ro/api/x")
    elapsed = time.monotonic() - started

    # Four requests means three gaps; the first one leaves immediately.
    assert elapsed >= 0.05 * 3


def test_no_more_than_max_parallel_requests_are_ever_in_flight(monkeypatch):
    monkeypatch.setattr(throttle, "MIN_INTERVAL", 0.0)
    monkeypatch.setattr(throttle, "JITTER", 0.0)
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def fake_request(self, method, url, **kwargs):
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(0.02)
        with lock:
            live["now"] -= 1
        return _json()

    monkeypatch.setattr(httpx.Client, "request", fake_request)

    threads = [
        threading.Thread(target=throttle.request, args=("GET", f"https://www.imobiliare.ro/{i}"))
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert live["peak"] <= throttle.MAX_PARALLEL


def test_a_photograph_is_fetched_once_however_often_it_is_wanted(monkeypatch):
    """The vision pass, the contact sheet and the PDF all want the same
    gallery. They used to fetch a copy each."""
    jpeg = httpx.Response(
        200,
        content=b"\xff\xd8\xff-not-really-but-bytes",
        headers={"content-type": "image/jpeg"},
        request=httpx.Request("GET", "https://i.roamcdn.net/a.jpg"),
    )
    calls = _responder(monkeypatch, lambda method, url: jpeg)

    first = throttle.fetch_image("https://i.roamcdn.net/a.jpg")
    second = throttle.fetch_image("https://i.roamcdn.net/a.jpg")

    assert first == second
    assert first is not None and first[1] == "image/jpeg"
    assert len(calls) == 1


def test_a_non_image_response_is_remembered_as_unusable(monkeypatch):
    """Not just "not cached": re-asking for a URL that serves HTML is exactly
    the behaviour that got the address flagged."""
    calls = _responder(monkeypatch, lambda method, url: _html(200, "<html>nope</html>"))

    assert throttle.fetch_image("https://i.roamcdn.net/b.jpg") is None
    assert throttle.fetch_image("https://i.roamcdn.net/b.jpg") is None
    assert len(calls) == 1


def test_a_block_while_fetching_an_image_is_not_fatal(monkeypatch):
    """One refused photograph must not take down the valuation around it."""
    monkeypatch.setattr(throttle, "RETRIES", 0)
    _responder(monkeypatch, lambda method, url: _html())
    assert throttle.fetch_image("https://i.roamcdn.net/c.jpg") is None


def test_the_pdf_builders_short_timeout_reaches_the_request(monkeypatch):
    """It is assembling a document someone is waiting on; a slow photograph
    should be dropped, not waited for."""
    seen: dict[str, object] = {}

    def fake_request(self, method, url, **kwargs):
        seen.update(kwargs)
        return httpx.Response(
            200,
            content=b"bytes",
            headers={"content-type": "image/jpeg"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    throttle.fetch_image("https://i.roamcdn.net/d.jpg", {"User-Agent": "x"}, timeout=3)
    assert seen["timeout"] == 3
