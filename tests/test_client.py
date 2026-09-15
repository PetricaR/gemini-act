"""`client.ImobiliareClient` -- session handling and the explanations fetch.

No network: `_post` is stubbed, since what matters here is how the client
reacts to the shapes and failures the two upstream hosts produce.
"""

from __future__ import annotations

import httpx
import pytest

from imobiliare.mcp.client import ImobiliareClient, SessionError, _as_list


@pytest.fixture
def client():
    c = ImobiliareClient(session_id="sess-1")
    yield c
    c.close()


def test_search_without_a_session_raises_session_error():
    c = ImobiliareClient(session_id="")
    try:
        with pytest.raises(SessionError, match="No session_id configured"):
            c.search("apartament 3 camere")
    finally:
        c.close()


def test_403_surfaces_as_session_error_not_a_transport_error(client, monkeypatch):
    """CLAUDE.md: a 403 from the AI host means an expired session and must
    surface as SessionError so `cauta` can explain it."""

    def fake_post(self, url, payload):
        request = httpx.Request("POST", url)
        response = httpx.Response(403, request=request)
        raise_on = httpx.HTTPStatusError("403", request=request, response=response)
        # Mirror what the real `_post` does before raise_for_status().
        raise SessionError("Session rejected (403).") from raise_on

    monkeypatch.setattr(ImobiliareClient, "_post", fake_post)
    with pytest.raises(SessionError):
        client.search("apartament")


def test_explanations_failure_is_never_fatal(client, monkeypatch):
    """The docstring promises best-effort. An expired session (SessionError)
    and a non-JSON body both used to escape and kill the whole search."""
    for boom in (
        SessionError("expired"),
        httpx.ConnectError("no route"),
        ValueError("Expecting value: line 1 column 1"),
    ):

        def fake_post(self, url, payload, _boom=boom):
            raise _boom

        monkeypatch.setattr(ImobiliareClient, "_post", fake_post)
        assert client._explanations({"url": "u", "token": "t"}) == {}


def test_explanations_are_keyed_by_string_id(client, monkeypatch):
    """hydrate has been seen returning `id` as both int and str; an int-keyed
    dict silently matched nothing in the second case."""

    def fake_post(self, url, payload):
        return [
            {"listingId": 275807510, "explanation": "  aproape de metrou  ", "grade": "A"},
            {"listing_id": "275807511", "reasoning": "3 camere"},
            {"id": "not-a-number", "explanation": "ignored"},
        ]

    monkeypatch.setattr(ImobiliareClient, "_post", fake_post)
    out = client._explanations({"url": "u", "token": "t"})

    assert set(out) == {"275807510", "275807511"}
    assert out["275807510"] == {"explanation": "aproape de metrou", "grade": "A"}
    assert out["275807511"] == {"explanation": "3 camere"}


def test_collect_ids_preserves_ai_ranking_and_drops_duplicates(client, monkeypatch):
    pages = {
        1: {"totalHits": 3, "items": [{"listingId": 3}, {"listingId": 1}, {"listingId": 3}]},
        2: {"totalHits": 3, "items": []},
    }
    monkeypatch.setattr(
        ImobiliareClient, "_post", lambda self, url, payload: pages[payload["page"]]
    )

    ids, total = client._collect_ids("u", "t", max_results=120)
    assert ids == ["3", "1"]
    assert total == 3


def test_hydrate_chunks_large_id_lists(client, monkeypatch):
    seen: list[int] = []

    def fake_post(self, url, payload):
        seen.append(len(payload["ids"]))
        return {"listings": [{"id": i} for i in payload["ids"]]}

    monkeypatch.setattr(ImobiliareClient, "_post", fake_post)
    out = client.hydrate([str(i) for i in range(250)], chunk=120)
    assert seen == [120, 120, 10]
    assert len(out) == 250


@pytest.mark.parametrize(
    ("raw", "expected_len"),
    [
        ([{"listingId": 1}], 1),
        ({"items": [{"listingId": 1}, {"listingId": 2}]}, 2),
        ({"explanations": {"results": [{"listingId": 1}]}}, 1),
        ({"123": {"explanation": "x"}}, 1),
        ({"123": "plain string"}, 1),
        ("nonsense", 0),
    ],
)
def test_as_list_handles_the_observed_payload_shapes(raw, expected_len):
    assert len(_as_list(raw)) == expected_len


class TestHydrateIsAskedOnce:
    """The traffic that got the address flagged.

    `server.py` opens a fresh `ImobiliareClient` for each tool, and about ten
    of them want the same listing during one valuation. Each used to POST for
    it. The memo lives in `throttle`, at module scope, so a new client still
    finds the previous one's answer — which is the whole point.
    """

    @staticmethod
    def _count_posts(monkeypatch):
        posted: list[list[str]] = []

        def fake_post(self, url, payload):
            posted.append(list(payload.get("ids") or []))
            return {
                "listings": [
                    {"id": int(i), "title": f"listing {i}"} for i in payload.get("ids") or []
                ]
            }

        monkeypatch.setattr(ImobiliareClient, "_post", fake_post)
        return posted

    def test_ten_tools_asking_for_one_listing_make_one_request(self, monkeypatch):
        posted = self._count_posts(monkeypatch)

        for _ in range(10):
            with ImobiliareClient(session_id="s") as client:
                assert client.hydrate(["275917496"])[0]["title"] == "listing 275917496"

        assert posted == [["275917496"]]

    def test_only_the_ids_not_already_known_are_requested(self, monkeypatch):
        posted = self._count_posts(monkeypatch)
        with ImobiliareClient(session_id="s") as client:
            client.hydrate(["1", "2"])
            records = client.hydrate(["2", "3"])

        assert posted == [["1", "2"], ["3"]]
        assert [r["id"] for r in records] == [2, 3]

    def test_an_id_that_resolves_to_nothing_is_asked_about_once(self, monkeypatch):
        """A delisted property returns no record. Without remembering the
        absence, every tool in the run re-asks for it."""
        posted: list[list[str]] = []

        def fake_post(self, url, payload):
            posted.append(list(payload.get("ids") or []))
            return {"listings": []}

        monkeypatch.setattr(ImobiliareClient, "_post", fake_post)
        with ImobiliareClient(session_id="s") as client:
            assert client.hydrate(["404404"]) == []
            assert client.hydrate(["404404"]) == []

        assert posted == [["404404"]]

    def test_caller_order_is_preserved_because_it_is_the_ai_ranking(self, monkeypatch):
        self._count_posts(monkeypatch)
        with ImobiliareClient(session_id="s") as client:
            client.hydrate(["3"])  # warm one, out of order
            records = client.hydrate(["1", "2", "3"])

        assert [r["id"] for r in records] == [1, 2, 3]

    def test_duplicate_ids_in_one_call_are_asked_for_once(self, monkeypatch):
        posted = self._count_posts(monkeypatch)
        with ImobiliareClient(session_id="s") as client:
            records = client.hydrate(["7", "7", 7])

        assert posted == [["7"]]
        assert len(records) == 1
