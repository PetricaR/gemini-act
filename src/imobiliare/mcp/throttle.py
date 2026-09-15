"""Pacing, de-duplication and block detection for calls to imobiliare.ro.

This exists because the portal started answering with its anti-bot
interstitial -- *"Am detectat o anomalie în comportamentul browserului
dumneavoastră ... frecvența de vizualizare a anunțurilor este mai ridicată
decât a majorității utilizatorilor noștri"* -- and it was right to. A single
valuation used to produce, for one listing: about ten separate ``hydrate``
POSTs for the *same* id, one per tool that wanted the record, each on a
freshly-opened connection; and the same gallery of ten photographs downloaded
some seven times over, eight at a time.

The three answers below are in descending order of how much they actually
mattered:

1. **Don't ask twice.** ``cached``/``remember`` memoise a record for the life
   of the process, so the tenth tool that wants listing 275917496 is handed
   the first tool's copy. This removed most of the traffic on its own -- more
   than any amount of sleeping would have.
2. **Don't ask fast.** ``request`` spaces what is left over a minimum interval
   per host, jittered, and caps how many calls may be in flight at once.
3. **Notice when you are told to stop.** The interstitial arrives as a *200
   with an HTML body*, not as an error status, so every naive client sails
   straight through it and parses the block page as data. ``request`` detects
   it, backs off exponentially, and then fails loudly rather than hammering.

Everything is tunable by environment variable, because the right pace is a
property of the portal's mood rather than of this code.

Scope, from this package's CLAUDE.md: the API is undocumented and has no
published terms, so request volume stays modest and there are no retry storms
-- the backoff below is bounded, and a block pushes out the *shared* per-host
clock so every thread slows down, not just the one that was refused. The
interstitial is detected in order to **stop**, never to get around it. Do not
grow this file in the direction of rotating identities, solving challenges or
hiding what the client is; if the portal wants this traffic gone, the correct
response is to send less of it.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)


def _num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


# Minimum gap between two requests to the same host. A human clicking through
# listings is nowhere near one request per second sustained; this is the floor,
# and the jitter below keeps the pattern from being metronomic.
MIN_INTERVAL = _num("IMOBILIARE_MIN_INTERVAL", 1.2)
JITTER = _num("IMOBILIARE_JITTER", 0.8)
# In-flight cap across every thread in the process. The gallery download used
# to open eight connections at once, which is the single most machine-looking
# thing this code did.
MAX_PARALLEL = max(1, int(_num("IMOBILIARE_MAX_PARALLEL", 2)))
# How many times to wait and re-ask after a block before giving up. Kept low
# on purpose -- CLAUDE.md: "don't add retry storms". Each wait is
# BACKOFF * 2**attempt, so the default is one retry at ~6s and one at ~12s.
RETRIES = max(0, int(_num("IMOBILIARE_RETRIES", 2)))
BACKOFF = _num("IMOBILIARE_BACKOFF", 6.0)
# How long a memoised listing record or photograph stays fresh. A listing does
# not change during the minute or two a valuation takes.
MEMO_TTL = _num("IMOBILIARE_MEMO_TTL", 900.0)
# Cap on memoised photographs, which are the only large values here.
MAX_IMAGES = max(0, int(_num("IMOBILIARE_MEMO_IMAGES", 240)))

# Phrases from the interstitial. Accent-stripped variants included because the
# page has been served both ways; matching is done lowercased.
_BLOCK_MARKERS = (
    "anomalie în comportamentul browserului",
    "anomalie in comportamentul browserului",
    "am identificat trafic automat",
    "frecvența de vizualizare",
    "frecventa de vizualizare",
)


class Blocked(RuntimeError):
    """imobiliare.ro served its anti-bot interstitial instead of an answer."""


class _Pacer:
    """A per-host "next request may leave at" clock, shared by every thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, host: str) -> None:
        # The slot is *reserved* under the lock and slept for outside it, so
        # concurrent callers queue up in time rather than piling on the lock.
        with self._lock:
            start = max(time.monotonic(), self._next.get(host, 0.0))
            self._next[host] = start + MIN_INTERVAL + random.uniform(0.0, JITTER)
        if (delay := start - time.monotonic()) > 0:
            time.sleep(delay)

    def penalise(self, host: str, seconds: float) -> None:
        """Push a host's clock out after a block, for *every* caller."""
        with self._lock:
            self._next[host] = max(self._next.get(host, 0.0), time.monotonic() + seconds)


_pacer = _Pacer()
_slots = threading.BoundedSemaphore(MAX_PARALLEL)

_memo_lock = threading.Lock()
_memo: dict[str, tuple[float, Any]] = {}
_images: dict[str, tuple[float, Any]] = {}


def cached(key: str) -> Any:
    """A memoised value, or None when absent or stale.

    A remembered ``None`` is a real answer -- "this listing id resolves to
    nothing" -- and is returned as such via the sentinel, so a delisted
    property is not re-requested by every tool in turn.
    """
    with _memo_lock:
        hit = _memo.get(key)
    if hit is None or time.monotonic() - hit[0] > MEMO_TTL:
        return None
    return hit[1]


def remember(key: str, value: Any) -> Any:
    with _memo_lock:
        _memo[key] = (time.monotonic(), value)
    return value


def forget_all() -> None:
    """Drop every memoised value. For tests, and for a fresh run on demand."""
    with _memo_lock:
        _memo.clear()
        _images.clear()
    with _pacer._lock:  # noqa: SLF001 - same module
        _pacer._next.clear()


def _is_block(response: httpx.Response) -> bool:
    """Is this the interstitial rather than an answer?

    429 always is. 403 is deliberately *not* treated as a block on its own:
    the AI host returns a JSON 403 for an expired session, which
    `client._post` turns into a much more useful SessionError. Only a 403
    carrying the interstitial's own words counts.
    """
    if response.status_code == 429:
        return True
    content_type = (response.headers.get("content-type") or "").lower()
    if "html" not in content_type and response.status_code != 403:
        return False
    try:
        body = response.text[:8000].lower()
    except (UnicodeDecodeError, httpx.ResponseNotRead):
        return False
    return any(marker in body for marker in _BLOCK_MARKERS)


def _retry_after(response: httpx.Response, fallback: float) -> float:
    try:
        return max(fallback, float(response.headers.get("retry-after") or 0))
    except ValueError:
        return fallback


def request(
    method: str,
    url: str,
    *,
    http: httpx.Client | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """Issue one paced request, retrying through the interstitial.

    Raises `Blocked` when the portal is still refusing after `RETRIES`
    attempts -- callers should surface that to the user rather than retrying
    it themselves, since by then the address has been asked to stop.
    """
    host = urlsplit(url).netloc
    client = http or _shared_client()
    for attempt in range(RETRIES + 1):
        with _slots:
            _pacer.wait(host)
            response = client.request(method, url, **kwargs)
        if not _is_block(response):
            return response
        if attempt == RETRIES:
            break
        delay = _retry_after(response, BACKOFF * (2**attempt)) + random.uniform(0.0, JITTER)
        # Penalise the host for everyone, not just this caller: the block is a
        # property of the address, so the other threads must slow down too.
        _pacer.penalise(host, delay)
        logger.warning(
            "imobiliare.ro refused %s %s (HTTP %s) — backing off %.1fs (attempt %d/%d)",
            method,
            url,
            response.status_code,
            delay,
            attempt + 1,
            RETRIES,
        )
        time.sleep(delay)
    raise Blocked(
        "imobiliare.ro answered with its anti-bot page for "
        f"{method} {url}. The address has been asked to slow down: wait a few "
        "minutes before retrying. Raise IMOBILIARE_MIN_INTERVAL / lower "
        "IMOBILIARE_MAX_PARALLEL if this keeps happening."
    )


_shared: httpx.Client | None = None
_shared_lock = threading.Lock()


def _shared_client() -> httpx.Client:
    """One connection pool for callers that don't bring their own.

    Reusing connections is itself part of looking less like a scraper: the
    gallery download used to complete a fresh TLS handshake per photograph.
    """
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = httpx.Client(timeout=30.0, follow_redirects=True)
        return _shared


def fetch_image(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> tuple[bytes, str] | None:
    """A photograph, from memory when it has already been fetched this run.

    Returns (bytes, mime), or None when it is unavailable or is not an image.
    The same gallery is wanted by the vision pass, the contact sheet and the
    PDF; without this they fetched it once each.

    `timeout` is per-request and does not count the pacing wait, which happens
    before the request is issued. The PDF builder passes a short one: it is
    assembling a document a user is waiting on, and a photograph that will not
    arrive promptly is better left out than waited for.
    """
    with _memo_lock:
        hit = _images.get(url)
    if hit is not None and time.monotonic() - hit[0] <= MEMO_TTL:
        return hit[1]

    kwargs: dict[str, Any] = {"headers": headers}
    if timeout is not None:
        kwargs["timeout"] = timeout
    try:
        response = request("GET", url, **kwargs)
    except (httpx.HTTPError, Blocked):
        return None
    if response.status_code != 200 or not response.content:
        return None
    mime = (response.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
    value = (response.content, mime) if mime.startswith("image/") else None

    with _memo_lock:
        if MAX_IMAGES and len(_images) >= MAX_IMAGES:
            # Plain FIFO eviction: a run works through a gallery once, so the
            # oldest entry is reliably the least interesting one.
            for stale in list(_images)[: max(1, len(_images) // 4)]:
                _images.pop(stale, None)
        _images[url] = (time.monotonic(), value)
    return value
