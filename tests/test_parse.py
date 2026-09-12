"""`parse.normalise` and `parse.filter_and_rank`.

The invariants under test are the ones CLAUDE.md calls expensive: the ga4 price
placeholder, and "a missing value fails a constraint".
"""

from __future__ import annotations

import pytest

from gemini_act.imobiliare_mcp.parse import filter_and_rank, normalise


def listing(**kw):
    base = {
        "id": "275807510",
        "heading": "Apartament 3 camere",
        "url": "/oferta/apartament-de-vanzare-sector-3-titan-3-camere-275807510",
        "price": "215.000 €",
        "location": "Titan, Sector 3",
        "highlights": [
            {"key": "usable_surface", "label": "75 mp"},
            {"key": "bedroom_count", "label": "3 camere"},
            {"key": "floor_number", "label": "Etaj 2 / 4"},
        ],
        "tracking": {"ga4Item": {}},
    }
    base.update(kw)
    return base


# -- price ----------------------------------------------------------------

def test_displayed_price_wins_over_ga4_placeholder():
    """The 0.2 placeholder appears on ~7% of listings; the display string rules."""
    r = normalise(listing(tracking={"ga4Item": {"price": 0.2}}))
    assert r["price_eur"] == 215000


def test_ga4_price_used_only_above_the_plausibility_floor():
    no_display = listing(price="")
    assert normalise(no_display)["price_eur"] is None

    placeholder = listing(price="", tracking={"ga4Item": {"price": 0.2}})
    assert normalise(placeholder)["price_eur"] is None

    real = listing(price="", tracking={"ga4Item": {"price": 199000}})
    assert normalise(real)["price_eur"] == 199000


def test_thousands_separator_is_a_dot():
    assert normalise(listing(price="1.250.000 €"))["price_eur"] == 1250000


# -- floors ---------------------------------------------------------------

@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Etaj 2 / 4", (2, 4)),
        ("Parter / 4", (0, 4)),
        ("Demisol / 3", (-1, 3)),
        ("Mansardă / 5", (99, 5)),
        ("Etaj 2", (2, None)),
    ],
)
def test_floor_normalisation(label, expected):
    r = normalise(listing(highlights=[{"key": "floor_number", "label": label}]))
    assert (r["floor"], r["floors_total"]) == expected


# -- "a missing value fails a constraint" ---------------------------------

def test_missing_price_fails_a_price_constraint():
    records = [normalise(listing(price="", tracking={"ga4Item": {}}))]
    assert records[0]["price_eur"] is None
    assert filter_and_rank(records, max_price=220000) == []


def test_missing_floor_fails_the_ground_floor_exclusion():
    """A listing that does not say what floor it is on has not been shown to
    satisfy "not ground floor"."""
    unknown = normalise(listing(highlights=[]))
    assert unknown["floor"] is None
    assert filter_and_rank([unknown], exclude_ground_floor=True) == []
    assert filter_and_rank([unknown], exclude_top_floor=True) == []


def test_ground_and_top_floor_exclusions_on_known_floors():
    parter = normalise(listing(highlights=[{"key": "floor_number", "label": "Parter / 4"}]))
    mijloc = normalise(listing(highlights=[{"key": "floor_number", "label": "Etaj 2 / 4"}]))
    ultim = normalise(listing(highlights=[{"key": "floor_number", "label": "Etaj 4 / 4"}]))
    mansarda = normalise(listing(highlights=[{"key": "floor_number", "label": "Mansardă / 4"}]))

    pool = [parter, mijloc, ultim, mansarda]
    assert filter_and_rank(pool, exclude_ground_floor=True) == [mijloc, ultim, mansarda]
    assert filter_and_rank(pool, exclude_top_floor=True) == [parter, mijloc]


# -- sorting --------------------------------------------------------------

def test_missing_values_sort_last_not_first():
    with_price = normalise(listing(price="100.000 €"))
    without = normalise(listing(price="", tracking={"ga4Item": {}}))
    ordered = filter_and_rank([without, with_price], sort_by="price")
    assert ordered[0]["price_eur"] == 100000
    assert ordered[-1]["price_eur"] is None


def test_descending_sorts_also_put_missing_last():
    new = normalise(listing(tracking={"ga4Item": {"propertyYear": 2020}}))
    unknown = normalise(listing(highlights=[]))
    ordered = filter_and_rank([unknown, new], sort_by="year_built")
    assert ordered[0]["year_built"] == 2020


def test_unknown_sort_is_rejected():
    with pytest.raises(ValueError, match="unknown sort_by"):
        filter_and_rank([], sort_by="nope")
