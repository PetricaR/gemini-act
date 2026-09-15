"""HTTP client for the imobiliare.ro AI search ("Homi") backend.

Two hosts are involved:

* ``api.ai-search.ringier.tech`` -- the AI layer. Turns a natural-language
  query into a ranked set of listing ids plus per-listing match explanations.
  Requires a browser-originated ``session_id``.
* ``www.imobiliare.ro/api/ai-search/hydrate`` -- turns listing ids into full
  listing records. Unauthenticated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from . import throttle

AI_BASE = "https://api.ai-search.ringier.tech"
HYDRATE_URL = "https://www.imobiliare.ro/api/ai-search/hydrate"
TENANT_ID = "imobiliare"

# The AI host rejects requests that don't look like they came from the portal.
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.imobiliare.ro",
    "Referer": "https://www.imobiliare.ro/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

# Page size the portal itself uses when paging the AI result set.
PAGE_SIZE = 60


class SessionError(RuntimeError):
    """Raised when the AI host refuses the configured session."""


@dataclass
class SearchResult:
    """One AI search turn: the assistant's reply plus the resolved listings."""

    title: str | None
    reply: str
    total_hits: int
    listings: list[dict[str, Any]]
    # Keyed by the listing id as a *string*: hydrate has been seen returning
    # `id` both as an int and as a string, and an int-keyed dict silently
    # matches nothing in the second case.
    explanations: dict[str, dict[str, str]]
    # Result tokens outlive the session that produced them, so keeping this
    # lets a caller page further into the same result set after the session
    # has expired -- no new query, no new session needed.
    token: str | None = None


class ImobiliareClient:
    def __init__(self, session_id: str | None = None, timeout: float = 60.0):
        self.session_id = session_id or os.environ.get("IMOBILIARE_SESSION_ID") or ""
        self._http = httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ImobiliareClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _post(self, url: str, payload: dict[str, Any]) -> Any:
        # Through `throttle` rather than straight at `self._http`: it paces the
        # call, and it recognises the anti-bot interstitial, which the portal
        # serves as a 200 with an HTML body. Without that check this would
        # cheerfully try to parse the block page as JSON.
        r = throttle.request("POST", url, http=self._http, json=payload)
        # A valid-looking but no-longer-authorised session comes back as 403.
        # Sessions expire after a few minutes, so this is the common failure
        # and deserves a better message than a raw transport error.
        if r.status_code == 403:
            raise SessionError(
                "Session rejected (403). imobiliare.ro sessions expire after a "
                "few minutes -- capture a fresh session_id from the browser."
            )
        r.raise_for_status()
        return r.json()

    # -- AI layer ---------------------------------------------------------

    def new_session(self) -> str:
        """Mint a session id.

        Note: sessions created this way are currently rejected by ``search``
        with ``Forbidden`` -- only browser-originated sessions are accepted.
        Kept because it is the documented handshake and may start working.
        """
        data = self._post(f"{AI_BASE}/api/conversation", {"tenant_id": TENANT_ID})
        return data["session_id"]

    def search(self, query: str, max_results: int = 120) -> SearchResult:
        """Run one natural-language search turn and resolve the listings."""
        if not self.session_id:
            raise SessionError(
                "No session_id configured. Set IMOBILIARE_SESSION_ID to a value "
                "captured from a browser (DevTools > Network > /api/search > "
                "request body > session_id)."
            )

        data = self._post(
            f"{AI_BASE}/api/search",
            {"query": query, "session_id": self.session_id, "tenant_id": TENANT_ID},
        )
        if "error" in data:
            raise SessionError(f"AI search refused the request: {data['error']}")

        # The host rotates the session id on every turn; follow it.
        meta = data.get("meta") or {}
        self.session_id = meta.get("session_id", self.session_id)

        reply = "\n\n".join(
            b["payload"]["text"] for b in data.get("blocks", []) if b.get("type") == "text"
        )

        search = data.get("search") or {}
        ids: list[str] = []
        total = 0
        if search.get("token"):
            ids, total = self._collect_ids(search["url"], search["token"], max_results)

        return SearchResult(
            title=meta.get("title"),
            reply=reply,
            total_hits=total,
            listings=self.hydrate(ids) if ids else [],
            explanations=self._explanations(data.get("explanations")),
            token=search.get("token"),
        )

    def resume(self, token: str, max_results: int = 240) -> SearchResult:
        """Re-read a previous result set from its token, without a session."""
        ids, total = self._collect_ids(f"{AI_BASE}/api/listings", token, max_results)
        return SearchResult(
            title=None,
            reply="",
            total_hits=total,
            listings=self.hydrate(ids) if ids else [],
            explanations={},
            token=token,
        )

    def _collect_ids(self, url: str, token: str, max_results: int) -> tuple[list[str], int]:
        ids: list[str] = []
        total = 0
        for page in range(1, (max_results + PAGE_SIZE - 1) // PAGE_SIZE + 1):
            data = self._post(url, {"token": token, "page": page, "size": PAGE_SIZE})
            total = data.get("totalHits", total)
            items = data.get("items") or []
            if not items:
                break
            ids.extend(str(i["listingId"]) for i in items if i.get("listingId"))
        # Preserve AI ranking while dropping duplicates.
        return list(dict.fromkeys(ids))[:max_results], total

    def _explanations(self, spec: dict[str, Any] | None) -> dict[str, dict[str, str]]:
        """Fetch per-listing match reasoning. Best-effort: never fatal."""
        if not spec or not spec.get("url") or not spec.get("token"):
            return {}
        try:
            raw = self._post(spec["url"], {"token": spec["token"]})
        # Match reasoning is a nicety; an expired session (SessionError) or a
        # non-JSON body must not take down the search that already succeeded.
        except (httpx.HTTPError, SessionError, ValueError):
            return {}

        out: dict[str, dict[str, str]] = {}
        for item in _as_list(raw):
            if not isinstance(item, dict):
                continue
            raw_id = item.get("listingId") or item.get("listing_id") or item.get("id")
            # int() first so "275969177" and 275969177 land on the same key.
            try:
                lid = str(int(raw_id))
            except (TypeError, ValueError):
                continue
            entry = {}
            if text := item.get("explanation") or item.get("reasoning") or item.get("reason"):
                entry["explanation"] = str(text).strip()
            if grade := item.get("grade") or item.get("matchGrade") or item.get("match_grade"):
                entry["grade"] = str(grade).strip()
            if entry:
                out[lid] = entry
        return out

    # -- Portal layer -----------------------------------------------------

    def hydrate(self, ids: list[str], chunk: int = 120) -> list[dict[str, Any]]:
        """Resolve listing ids to full records. No authentication required.

        Memoised per id, which matters more than it looks: a valuation asks
        ten different tools about one listing, and each used to open its own
        client and POST for the same record. That repetition -- not the total
        number of listings -- is what the portal's anti-bot page was
        complaining about. An id that resolves to nothing is remembered as
        nothing, so a delisted property is asked about once too.
        """
        wanted = list(dict.fromkeys(_key(i) for i in ids if _key(i)))
        known: dict[str, dict[str, Any] | None] = {}
        missing: list[str] = []
        for listing_id in wanted:
            hit = throttle.cached(f"hydrate:{listing_id}")
            if hit is _MISSING:
                known[listing_id] = None
            elif hit is not None:
                known[listing_id] = hit
            else:
                missing.append(listing_id)

        for i in range(0, len(missing), chunk):
            batch = missing[i : i + chunk]
            data = self._post(HYDRATE_URL, {"ids": batch, "card_format": "data"})
            for record in data.get("listings") or []:
                if listing_id := _key(record.get("id")):
                    known[listing_id] = throttle.remember(f"hydrate:{listing_id}", record)
            for listing_id in batch:
                if listing_id not in known:
                    throttle.remember(f"hydrate:{listing_id}", _MISSING)
                    known[listing_id] = None

        # Caller order is the AI ranking; preserve it.
        return [record for lid in wanted if (record := known.get(lid)) is not None]


# Sentinel for "asked, and this id resolves to nothing", so that a remembered
# absence is distinguishable from a cache miss.
_MISSING = object()


def _key(raw: Any) -> str:
    """Normalise a listing id: hydrate returns them as both int and str."""
    try:
        return str(int(raw))
    except (TypeError, ValueError):
        return ""


def _as_list(raw: Any) -> list[Any]:
    """The explanations payload has been seen as a list and as several dict shapes."""
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []
    for key in ("items", "explanations", "results", "data"):
        inner = raw.get(key)
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            return _as_list(inner)
    return [
        {"listingId": k, **v} if isinstance(v, dict) else {"listingId": k, "explanation": v}
        for k, v in raw.items()
    ]
