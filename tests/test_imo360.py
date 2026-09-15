"""The imo360 explorer source (`imo360`).

Everything here runs offline against captured payload shapes. The point of
these tests is the *interpretation* of that payload -- which surface a price
per sqm was measured against, what counts as a sale, what counts as the same
property twice -- because that is where being wrong is silent and expensive.
"""

from __future__ import annotations

import pytest

from imobiliare.mcp import imo360
from imobiliare.mcp.parse import filter_and_rank

# Shaped on a real response from the explorer endpoint.
RAW = {
    "id": 5194980,
    "title": "Apartament de vanzare, 46 mp, zona Carpati 1 - Satu Mare",
    "address": "Strada Ganea",
    "fullAddress": "Strada Ganea 2, 1 Mai, Sector 1, București, 010721",
    "latitude": 44.47014,
    "longitude": 26.051783,
    "price": 65000,
    "currency": "eur",
    "totalArea": 54,
    "usableArea": None,
    "rooms": 3,
    "floor": 0,
    "floorMax": 4,
    "constructionYear": None,
    "propertyType": "apartment",
    "transaction": "sale",
    "imageUrl": "https://api.imo360.ro/x.jpg",
    "locality": "Sector 1",
    "region": "București",
    "zone": "1 Mai",
    "zoneId": 20613,
    "createdAt": "2026-06-19T06:31:06+03:00",
    "description": "BLITZ vă propune spre vânzare un apartament cu 3 camere.",
    "score": {
        "total": 87.46,
        "grade": "A",
        "confidence": 0.889,
        "valueScore": 100,
        "factors": {
            "factors": ["Priced below market value"],
            "summary": "Exceptional opportunity.",
            "missing_signals": ["year_built"],
        },
        "calculatedAt": "2026-08-26T17:20:22+03:00",
    },
}


def raw(**kw):
    return {**RAW, **kw}


# -- normalisation --------------------------------------------------------


def test_price_per_sqm_falls_back_to_total_area_and_says_so():
    r = imo360.normalise(raw())
    assert r["surface_sqm"] == 54
    # The basis is the whole point: 65000/54 is not comparable with a
    # usable-area figure without knowing that is what it is.
    assert r["surface_basis"] == "total"
    assert r["price_per_sqm"] == round(65000 / 54)


def test_usable_area_wins_when_published():
    r = imo360.normalise(raw(usableArea=46))
    assert (r["surface_sqm"], r["surface_basis"]) == (46, "usable")
    assert r["price_per_sqm"] == round(65000 / 46)


def test_non_eur_price_has_no_price_eur():
    # No FX rate exists here; converting would corrupt every average built on
    # top, so the listing simply has no euro price.
    r = imo360.normalise(raw(currency="ron", price=320000))
    assert r["price_eur"] is None
    assert (r["price_raw"], r["currency"]) == (320000, "ron")
    assert r["price_per_sqm"] is None


def test_rent_price_per_sqm_keeps_decimals():
    # 9 EUR/sqm instead of 9.09 is a 1% error on the rent and the same again
    # on any yield computed from it.
    r = imo360.normalise(raw(transaction="rent", price=500, totalArea=55))
    assert r["price_per_sqm"] == pytest.approx(9.09, abs=0.01)


def test_geography_comes_from_the_resolved_fields_not_the_title():
    # The title says Satu Mare; the property is in Bucharest.
    r = imo360.normalise(raw())
    assert (r["area"], r["city"], r["county"]) == ("1 Mai", "Sector 1", "București")


def test_record_carries_every_key_the_filter_layer_indexes():
    # `filter_and_rank` subscripts these directly, so an absent key is a
    # KeyError rather than a constraint that fails.
    r = imo360.normalise(raw())
    assert filter_and_rank([r], max_metro_m=500) == []
    assert filter_and_rank([r], sort_by="price") == [r]


def test_vendor_score_is_kept_apart_from_the_record():
    r = imo360.normalise(raw())
    assert r["imo360_score"]["grade"] == "A"
    assert r["imo360_score"]["missing_signals"] == ["year_built"]
    # Not merged in: nothing downstream may mistake the vendor's opinion for a
    # value this package computed.
    assert "grade" not in r
    assert "valueScore" not in r


def test_score_absent_leaves_no_key():
    assert "imo360_score" not in imo360.normalise(raw(score=None))


# -- mis-filed listings ---------------------------------------------------


def test_rental_priced_ad_in_the_sale_index_is_flagged():
    r = imo360.normalise(raw(price=700))
    assert "below any plausible sale price" in r["suspect"]


def test_cheap_land_is_not_flagged():
    # The floor is about built property; a 5000 EUR rural plot is ordinary.
    r = imo360.normalise(raw(price=5000, propertyType="land"))
    assert "suspect" not in r


def test_share_of_a_property_is_flagged_from_its_own_title():
    r = imo360.normalise(raw(title="Vand cotă ideală 21% apartament"))
    assert "cot" in r["suspect"]


def test_a_rental_listing_is_never_suspect_for_its_price():
    r = imo360.normalise(raw(transaction="rent", price=700))
    assert "suspect" not in r


def test_statistics_exclude_the_mis_filed_and_count_them():
    records = [
        imo360.normalise(raw(id=1, price=120000)),
        imo360.normalise(raw(id=2, price=130000)),
        imo360.normalise(raw(id=3, price=700)),  # a rental ad in the sale index
    ]
    stats = imo360.price_stats(records)
    assert stats["excluded_not_a_sale"] == 1
    assert stats["price_eur"]["min"] == 120000


# -- duplicates -----------------------------------------------------------


def test_same_property_twice_collapses_to_the_fuller_record():
    thin = imo360.normalise(raw(id=1, constructionYear=None))
    full = imo360.normalise(raw(id=2, constructionYear=1969))
    out = imo360.dedupe([thin, full])
    assert len(out) == 1
    # The survivor is the record that says the most, not the first one seen.
    assert out[0]["year_built"] == 1969


def test_different_properties_at_the_same_price_are_kept():
    a = imo360.normalise(raw(id=1, fullAddress="Strada A 1"))
    b = imo360.normalise(raw(id=2, fullAddress="Strada B 2"))
    assert len(imo360.dedupe([a, b])) == 2


def test_listing_without_a_price_is_kept_rather_than_merged():
    # These also reach a user; deleting one because its price was not
    # published is a worse error than showing it.
    a = imo360.normalise(raw(id=1, price=None))
    b = imo360.normalise(raw(id=2, price=None))
    assert len(imo360.dedupe([a, b])) == 2


def test_dedupe_preserves_the_callers_order():
    records = [imo360.normalise(raw(id=i, price=100000 + i * 1000)) for i in range(4)]
    assert [r["id"] for r in imo360.dedupe(records)] == [0, 1, 2, 3]


# -- counts and yield -----------------------------------------------------


def test_capped_total_is_not_reported_as_a_supply_count():
    page = imo360.SearchPage(listings=[], total=10000, total_is_capped=True)
    assert page.supply is None
    assert imo360.SearchPage(listings=[], total=109, total_is_capped=False).supply == 109


def test_gross_yield_needs_both_sides():
    assert imo360.gross_yield(2000, 9.09) == pytest.approx(5.45, abs=0.01)
    assert imo360.gross_yield(None, 9.09) is None
    assert imo360.gross_yield(2000, None) is None


def test_per_sqm_basis_can_be_forced_so_two_pools_agree():
    mixed = [
        imo360.normalise(raw(id=1, usableArea=50)),
        imo360.normalise(raw(id=2, usableArea=None, price=70000)),
    ]
    values, basis = imo360._per_sqm(mixed, "usable")
    assert (basis, len(values)) == ("usable", 1)
    values, basis = imo360._per_sqm(mixed, "mixed")
    assert (basis, len(values)) == ("mixed", 2)


# -- gazetteer ------------------------------------------------------------


def test_degenerate_bbox_is_reported_as_no_bbox():
    # Zones without a polygon publish the same point four times; passing that
    # to a bbox search matches nothing.
    z = imo360._zone(
        {
            "id": 1,
            "name": "X",
            "slug": "x",
            "path": "romania/a/b/x",
            "bbox": [26.0, 44.4, 26.0, 44.4],
        }
    )
    assert z is not None and z.bbox is None
    z = imo360._zone(
        {
            "id": 2,
            "name": "Y",
            "slug": "y",
            "path": "romania/a/b/y",
            "bbox": [26.0, 44.4, 26.1, 44.5],
        }
    )
    assert z is not None and z.bbox == (26.0, 44.4, 26.1, 44.5)


def test_zone_reads_city_and_county_off_its_path():
    z = imo360._zone(
        {"id": 3, "name": "Titan", "slug": "titan", "path": "romania/bucuresti/sector-3/titan"}
    )
    assert (z.city, z.county) == ("Sector 3", "Bucuresti")


def test_find_zones_ranks_exact_matches_first_and_keeps_the_ambiguity(monkeypatch):
    zones = [
        imo360._zone(
            {
                "id": 1,
                "name": "Titanul Nou",
                "slug": "titanul-nou",
                "path": "romania/bucuresti/sector-3/titanul-nou",
            }
        ),
        imo360._zone(
            {"id": 2, "name": "Titan", "slug": "titan", "path": "romania/bucuresti/sector-3/titan"}
        ),
    ]
    client = imo360.Imo360Client()
    monkeypatch.setattr(client, "zones", lambda: zones)
    hits = client.find_zones("Titan", city="bucuresti")
    assert [z.id for z in hits] == [2, 1]
    client.close()


def test_find_zones_keeps_both_militari_zones(monkeypatch):
    # Two real zones share the name across two sectors. Dropping one would
    # silently halve whatever market is being measured.
    zones = [
        imo360._zone(
            {
                "id": 5,
                "name": "Militari",
                "slug": "militari",
                "path": "romania/bucuresti/sector-5/militari",
            }
        ),
        imo360._zone(
            {
                "id": 6,
                "name": "Militari",
                "slug": "militari",
                "path": "romania/bucuresti/sector-6/militari",
            }
        ),
    ]
    client = imo360.Imo360Client()
    monkeypatch.setattr(client, "zones", lambda: zones)
    assert len(client.find_zones("Militari", city="bucuresti")) == 2
    client.close()


def test_search_without_a_geography_is_refused():
    client = imo360.Imo360Client()
    with pytest.raises(imo360.Imo360Error):
        client.search()
    client.close()


# -- the search tool ------------------------------------------------------


class _FakeClient:
    """Stands in for the explorer API: one zone, one page, no network."""

    def __init__(self, listings, total=3):
        self._listings, self._total = listings, total

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def find_zones(self, name, city=None, limit=8):
        return [
            imo360._zone(
                {
                    "id": 99,
                    "name": "Floreasca",
                    "slug": "floreasca",
                    "path": "romania/bucuresti/sector-1/floreasca",
                }
            )
        ]

    def collect(self, **kwargs):
        return imo360.SearchPage(listings=self._listings, total=self._total, total_is_capped=False)


def test_search_drops_the_mis_filed_by_default_and_says_how_many(monkeypatch):
    from imobiliare.mcp import server

    listings = [raw(id=1, price=800), raw(id=2, price=180000), raw(id=3, price=190000)]
    monkeypatch.setattr(imo360, "Imo360Client", lambda *a, **kw: _FakeClient(listings))

    out = server.cauta_imo360(zona="Floreasca", oras="bucuresti")
    assert out["status"] == "success"
    assert out["excluse_neconforme"] == 1
    # The 800 EUR ad would otherwise lead a price-per-sqm sort.
    assert [x["price_eur"] for x in out["listings"]] == [180000, 190000]
    assert out["oferta_totala"] == 3


def test_search_can_be_asked_for_the_mis_filed_back(monkeypatch):
    from imobiliare.mcp import server

    listings = [raw(id=1, price=800), raw(id=2, price=180000)]
    monkeypatch.setattr(imo360, "Imo360Client", lambda *a, **kw: _FakeClient(listings, total=2))

    out = server.cauta_imo360(zona="Floreasca", include_neconforme=True)
    assert out["excluse_neconforme"] == 0
    # Present, and carrying the reason it is not an ordinary bargain.
    flagged = [x for x in out["listings"] if x["price_eur"] == 800]
    assert flagged and "suspect" in flagged[0]


def test_search_reports_an_unknown_zone_as_an_error(monkeypatch):
    from imobiliare.mcp import server

    class _NoZones(_FakeClient):
        def find_zones(self, name, city=None, limit=8):
            return []

    monkeypatch.setattr(imo360, "Imo360Client", lambda *a, **kw: _NoZones([]))
    out = server.cauta_imo360(zona="Nicăieri", oras="bucuresti")
    assert out["status"] == "error"
    assert "Nicăieri" in out["error_message"]
