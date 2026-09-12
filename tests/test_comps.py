"""Comparable sourcing and ranking (`comps`)."""

from __future__ import annotations

from gemini_act.imobiliare_mcp.comps import (
    _parse_offer,
    area_slug_of,
    rank_by_similarity,
    scope_for,
)

SUBJECT = {"surface_sqm": 60.0, "year_built": 2000, "floor": 2, "metro_distance_m": 400}


def comp(cid, **kw):
    base = {"id": cid, "surface_sqm": 60.0, "year_built": 2000,
            "floor": 2, "metro_distance_m": 400}
    base.update(kw)
    return base


# -- slug parsing ---------------------------------------------------------

def test_parse_offer_splits_area_rooms_and_furnished_marker():
    o = _parse_offer(
        "https://www.imobiliare.ro/oferta/"
        "apartament-de-vanzare-sector-3-titan-mobilat-3-camere-275807510"
    )
    assert o is not None
    assert (o.id, o.area, o.rooms, o.furnished) == ("275807510", "sector-3-titan", 3, True)


def test_parse_offer_without_furnished_marker():
    o = _parse_offer("/oferta/apartament-de-vanzare-drumul-taberei-2-camere-123456")
    assert o is not None
    assert (o.area, o.rooms, o.furnished) == ("drumul-taberei", 2, False)


def test_area_slug_of_non_offer_url_is_none():
    assert area_slug_of("https://www.imobiliare.ro/vanzare-apartamente") is None
    assert area_slug_of("") is None


def test_scope_for_maps_counties_onto_sitemap_segments():
    assert scope_for("București", None) == "bucuresti"
    assert scope_for(None, "Sector 3") == "bucuresti"
    assert scope_for("Cluj", None) == "judetul-cluj"
    assert scope_for("judetul-ilfov", None) == "judetul-ilfov"
    assert scope_for(None, None) == "bucuresti"


# -- ranking --------------------------------------------------------------

def test_documented_comparable_outranks_an_undocumented_one():
    """An attribute missing on either side is penalised, not skipped.

    Skipping it meant a listing carrying no evidence at all scored 0 on every
    term and sorted to the very top of the grid.
    """
    documented = comp("documented", surface_sqm=61.0, year_built=2001, floor=2,
                      metro_distance_m=420)
    bare = comp("bare", year_built=None, floor=None, metro_distance_m=None)

    order = [r["id"] for r in rank_by_similarity(SUBJECT, [bare, documented])]
    assert order == ["documented", "bare"]


def test_closest_on_surface_still_wins_among_documented_comparables():
    near = comp("near", surface_sqm=62.0)
    far = comp("far", surface_sqm=95.0)
    order = [r["id"] for r in rank_by_similarity(SUBJECT, [far, near])]
    assert order == ["near", "far"]


def test_a_known_mismatch_still_beats_an_unknown():
    """An unknown is worse evidence than a known difference, but the ordering
    must stay sane: a wildly different documented comp can still lose."""
    slight_mismatch = comp("slight", year_built=1995)
    unknown_year = comp("unknown", year_built=None)
    order = [r["id"] for r in rank_by_similarity(SUBJECT, [unknown_year, slight_mismatch])]
    assert order == ["slight", "unknown"]


def test_ranking_is_stable_and_total():
    pool = [comp(str(i), surface_sqm=60.0 + i) for i in range(5)]
    assert [r["id"] for r in rank_by_similarity(SUBJECT, pool)] == ["0", "1", "2", "3", "4"]
