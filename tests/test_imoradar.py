"""The imoradar24 aggregator source (`imoradar`).

Everything runs offline against the payload shapes captured from the live
portal. What is tested is the *interpretation*: how long a property has really
been on the market, whether a price spread means anything, what counts as an
exact address -- the places where this source means something different by a
field that looks identical to imobiliare.ro's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gemini_act.imobiliare_mcp import imoradar


def _ago(days: int) -> str:
    """A `postedOn` value that is exactly `days` old, in the portal's format."""
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%d-%m-%Y")


# Shaped on listing 2292972 as the portal returned it.
RAW = {
    "id": 2292972,
    "url": "/oferta/apartament-de-vanzare-sector-3-titan-4-camere-2292972",
    "heading": "Apartament cu 4 camere semidecomandat în Titan",
    "location": "Titan, Sector 3",
    "address": "6, Aleea Barajul Rovinari, Titan, Sector 3",
    "createdAt": "Azi",
    "price": "179.000 €",
    "priceChange": None,
    "sourceName": "Imobiliare.ro",
    "multipleSources": False,
    "agencyName": "Cristian ",
    "descriptionPreview": "Particular, ofer spre vanzare apartament...",
    "images": [{"src": "https://i.roamcdn.net/prop/rad/x.jpg", "alt": ""}],
    "hasVideo": False,
    "hasVirtualTour": False,
    "hasPlans": False,
    "highlights": [
        {"key": "bedroom_count", "label": "4 camere"},
        {"key": "usable_surface", "label": "76 mp"},
        {"key": "floor_number", "label": "Etaj 2 / 4"},
        {"key": "year_built", "label": "1968"},
    ],
    "metroDistance": "854 m (11 min)",
    "extraFeatures": [{"title": "Comision 0%"}],
    "sellerSources": [
        {
            "sellerName": "Cristian ",
            "sourceName": "Imobiliare.ro",
            "price": "179.000 €",
            "postedOn": _ago(3),
            "updatedOn": _ago(1),
            "sellerType": "individual",
            "viewAdUrl": "https://www.imobiliare.ro/oferta/x-275971506",
        }
    ],
    "tracking": {
        "ga4Item": {
            "price": 179000,
            "propertyYear": "1968",
            "sellerType": "proprietar",
            "propertyAvailability": "available",
            "propertyCounty": "Bucuresti",
            "propertyCity": "Sector 3",
            "propertyArea": "Titan",
            "propertySurface": "76",
            "propertyDaysInMarket": "3",
            "item_category4": "established",
        }
    },
}


def raw(**kw):
    return {**RAW, **kw}


def source(**kw):
    base = {
        "sellerName": "Agent A",
        "sourceName": "Imobiliare.ro",
        "price": "150.000 €",
        "postedOn": _ago(5),
        "updatedOn": _ago(5),
        "sellerType": "agency",
        "viewAdUrl": "https://www.imobiliare.ro/oferta/y",
    }
    return {**base, **kw}


# -- the shared record shape ----------------------------------------------


def test_the_base_record_is_parsed_by_the_shared_normaliser():
    r = imoradar.normalise(raw())
    assert r["price_eur"] == 179000
    assert r["surface_sqm"] == 76
    assert r["rooms"] == 4
    assert (r["floor"], r["floors_total"]) == (2, 4)
    assert r["year_built"] == 1968
    assert r["metro_distance_m"] == 854
    assert r["commission_zero"] is True
    assert r["price_per_sqm"] == round(179000 / 76)
    assert r["source"] == "imoradar24"


def test_a_relative_url_gets_this_portal_not_imobiliare_ro():
    assert imoradar.normalise(raw())["url"] == imoradar.BASE + RAW["url"]


def test_an_already_absolute_url_is_left_alone():
    # Aggregated ads arrive with a full https://www.imoradar24.ro/link-extern/…
    # url; prefixing the host again produced a doubled, dead link.
    absolute = "https://www.imoradar24.ro/link-extern/2290922"
    assert imoradar.normalise(raw(url=absolute))["url"] == absolute


def test_the_ga4_price_placeholder_is_still_guarded():
    # Same 0.2 placeholder as imobiliare.ro, on ~9% of listings here.
    r = imoradar.normalise(raw(price="", tracking={"ga4Item": {"price": 0.2}}))
    assert r["price_eur"] is None


# -- seller vocabulary ----------------------------------------------------


@pytest.mark.parametrize(
    "upstream, expected",
    [("proprietar", "individual"), ("agency", "agency"), ("dezvoltator", "developer")],
)
def test_the_romanian_seller_vocabulary_is_mapped_to_the_shared_one(upstream, expected):
    # Unmapped, `tip_vanzator="individual"` matches nothing at all here.
    r = imoradar.normalise(raw(tracking={"ga4Item": {"sellerType": upstream}}))
    assert r["seller_type"] == expected


def test_an_unknown_seller_type_falls_back_to_the_source_ad():
    r = imoradar.normalise(
        raw(
            tracking={"ga4Item": {"sellerType": "not applicable"}},
            sellerSources=[source(sellerType="individual")],
        )
    )
    assert r["seller_type"] == "individual"


# -- time on the market ---------------------------------------------------


def test_days_on_market_follows_the_source_ad_when_this_portal_indexed_it_late():
    # Listing 2287996: indexed 2 days ago, but its Imobiliare.ro ad was posted
    # six months earlier. The ga4 number alone turns a stale flat into a fresh
    # one, which inverts the negotiation signal it is read for.
    r = imoradar.normalise(
        raw(
            tracking={"ga4Item": {"propertyDaysInMarket": "2"}},
            sellerSources=[source(postedOn=_ago(190))],
        )
    )
    assert r["days_on_imoradar"] == 2
    assert r["days_on_market"] == 190


def test_days_on_market_keeps_this_portals_number_when_the_surviving_ads_are_newer():
    # Listing 2249080: in the index for 6 days, but the oldest ad still
    # standing was posted 3 days ago -- the one that brought it in is gone.
    # Reading only the ads would make it younger than it is known to be.
    r = imoradar.normalise(
        raw(
            tracking={"ga4Item": {"propertyDaysInMarket": "6"}},
            sellerSources=[source(postedOn=_ago(3)), source(postedOn=_ago(2))],
        )
    )
    assert r["days_on_market"] == 6
    assert r["first_posted"] == (datetime.now(UTC) - timedelta(days=3)).date().isoformat()


def test_days_on_market_is_missing_when_neither_side_published_one():
    r = imoradar.normalise(raw(tracking={"ga4Item": {}}, sellerSources=[]))
    assert r["days_on_market"] is None


# -- cross-portal prices --------------------------------------------------


def test_two_sellers_at_two_prices_is_a_spread_worth_arguing_from():
    r = imoradar.normalise(
        raw(
            sellerSources=[
                source(sellerName="Daniela Rogoz", price="144.900 €"),
                source(sellerName="Anamaria Sarbusca", price="149.900 €"),
            ]
        )
    )
    assert r["source_count"] == 2
    assert (r["price_min_eur"], r["price_max_eur"]) == (144900, 149900)
    assert r["price_spread_pct"] == 3.5
    assert r["price_spread_scope"] == "cross_seller"


def test_one_seller_at_four_prices_is_a_project_not_a_divergence():
    # Listing 2147878: one agent, same day, 175.450 -> 193.479 €. Reported as
    # a 10% spread it reads as leverage; it is several units of one project.
    prices = ("175.450 €", "179.080 €", "180.895 €", "193.479 €")
    r = imoradar.normalise(
        raw(sellerSources=[source(sellerName="Cristian Panait", price=p) for p in prices])
    )
    assert r["price_spread_pct"] == 10.3
    assert r["price_spread_scope"] == "same_seller"


def test_the_same_ad_listed_twice_is_not_two_offers():
    r = imoradar.normalise(raw(sellerSources=[source(), source()]))
    assert r["source_count"] == 1
    assert r["price_spread_pct"] is None


def test_two_ads_at_the_same_price_are_still_scoped():
    # 0.0 is a real measurement -- advertised twice, same price -- and has to
    # arrive with the scope that says who by, not as an unexplained zero.
    r = imoradar.normalise(
        raw(sellerSources=[source(sellerName="A", postedOn=_ago(9)), source(sellerName="B")])
    )
    assert r["price_spread_pct"] == 0.0
    assert r["price_spread_scope"] == "cross_seller"


def test_sources_are_ordered_cheapest_first():
    r = imoradar.normalise(
        raw(
            sellerSources=[
                source(sellerName="B", price="160.000 €"),
                source(sellerName="A", price="140.000 €"),
            ]
        )
    )
    assert [s["price_eur"] for s in r["sources"]] == [140000, 160000]


def test_a_published_reduction_is_measured_against_the_old_price():
    r = imoradar.normalise(
        raw(price="115.000 €", priceChange={"oldPrice": "124.990 €", "direction": "down"})
    )
    assert r["price_dropped"] is True
    assert (r["old_price_eur"], r["price_drop_pct"]) == (124990, 8.0)


# -- location and availability --------------------------------------------


def test_a_street_address_counts_as_an_exact_location():
    r = imoradar.normalise(raw())
    assert r["exact_location"] is True
    assert r["address_text"] == RAW["address"]


def test_an_address_that_only_repeats_the_neighbourhood_is_not_one():
    # This portal publishes no "Locație exactă" badge, and falls back to the
    # neighbourhood in `address`. Kept, a geocoder would report a street-level
    # fix it never had.
    r = imoradar.normalise(raw(address="Titan, Sector 3"))
    assert r["exact_location"] is False
    assert r["address_text"] is None


def test_an_expired_ad_is_flagged_rather_than_hidden():
    r = imoradar.normalise(raw(tracking={"ga4Item": {"propertyAvailability": "expired"}}))
    assert r["expired"] is True


def test_a_price_no_sale_could_be_at_is_flagged():
    # 476 € for a 62 mp flat: a monthly rent filed as a sale price, which is
    # what 1,9% of the owner-advertised segment turned out to be.
    assert "476" in imoradar.normalise(raw(price="476 €"))["suspect"]


def test_an_ordinary_price_is_not_flagged():
    assert "suspect" not in imoradar.normalise(raw())


# -- urls and the gazetteer -----------------------------------------------


def test_filters_are_built_into_the_url_path():
    url = imoradar._search_url("bucuresti/sector-3/titan", 3, False, 1)
    assert url == f"{imoradar.BASE}/apartamente-de-vanzare/bucuresti/sector-3/titan/3-camere"


def test_the_owner_segment_is_its_own_path_segment():
    assert imoradar._search_url("bucuresti", 2, True, 1).endswith("/bucuresti/2-camere/proprietar")


def test_paging_never_goes_past_what_robots_txt_allows():
    # robots.txt disallows `?page=*` and then allows exactly pages 2..10.
    assert "?" not in imoradar._search_url(None, None, False, 1)
    assert imoradar._search_url(None, None, False, 4).endswith("?page=4")
    assert imoradar._search_url(None, None, False, 99).endswith(f"?page={imoradar.MAX_PAGES}")


SITEMAP = """<urlset>
<url><loc>https://www.imoradar24.ro/apartamente-de-vanzare</loc></url>
<url><loc>https://www.imoradar24.ro/apartamente-de-vanzare/bucuresti/sector-3/titan</loc></url>
<url><loc>https://www.imoradar24.ro/apartamente-de-vanzare/bucuresti/sector-3/titan/3-camere</loc></url>
<url><loc>https://www.imoradar24.ro/apartamente-de-vanzare/bucuresti/2-camere/proprietar</loc></url>
<url><loc>https://www.imoradar24.ro/apartamente-de-vanzare/judetul-cluj/cluj-napoca/manastur</loc></url>
<url><loc>https://www.imoradar24.ro/case-de-vanzare/bucuresti/sector-3/titan</loc></url>
</urlset>"""


def test_the_gazetteer_keeps_places_and_drops_the_filter_variants():
    paths = imoradar._place_paths(SITEMAP)
    assert paths == {
        "bucuresti/sector-3/titan",
        "bucuresti",
        "judetul-cluj/cluj-napoca/manastur",
    }


def test_a_place_reads_its_city_and_county_out_of_its_path():
    bucharest = imoradar.Place("bucuresti/sector-3/titan")
    assert (bucharest.name, bucharest.city, bucharest.county) == ("Titan", "Sector 3", "Bucuresti")
    cluj = imoradar.Place("judetul-cluj/cluj-napoca/manastur")
    assert (cluj.name, cluj.city, cluj.county) == ("Manastur", "Cluj Napoca", "Cluj")


# -- the payload and the page ---------------------------------------------


def test_the_inertia_payload_is_read_out_of_the_rendered_page():
    payload = "{&quot;props&quot;:{&quot;a&quot;:1},&quot;version&quot;:&quot;v1&quot;}"
    html = f'<div id="app" data-page="{payload}"></div>'
    assert imoradar._page_from_html(html) == {"props": {"a": 1}, "version": "v1"}


def test_a_page_without_the_payload_is_an_error_not_an_empty_result():
    with pytest.raises(imoradar.ImoradarError):
        imoradar._page_from_html("<html><body>challenge</body></html>")


def props(listings, total=479, last_page=16, owners=56):
    return {
        "searchMeta": {"totalCount": total, "lastPage": last_page, "currentPage": 1},
        "sections": [
            {"type": "results-stats", "data": {"ownerListingsCount": owners}},
            {"type": "results-list", "data": {"listings": listings}},
        ],
    }


def test_the_page_carries_the_deduplicated_property_count_and_the_owner_share():
    page = imoradar._page(props([raw()]))
    assert (page.total, page.owner_total, page.last_page) == (479, 56, 16)
    assert page.truncated is True


class _FakeClient(imoradar.ImoradarClient):
    """A client whose transport is a dict of url -> props."""

    def __init__(self, pages, places=("bucuresti/sector-3/titan",)):
        self._pages = pages
        self._places = [imoradar.Place(p) for p in places]
        self.requested: list[str] = []

    def _props(self, url):
        self.requested.append(url)
        return self._pages.get(url, props([], total=0, last_page=1))

    def places(self):
        return self._places

    def close(self):
        pass


def test_collect_pages_until_it_has_what_was_asked_for():
    root = f"{imoradar.BASE}/apartamente-de-vanzare/bucuresti"
    pages = {
        root: props([raw(id=i) for i in range(30)], last_page=5),
        f"{root}?page=2": props([raw(id=100 + i) for i in range(30)], last_page=5),
    }
    client = _FakeClient(pages)
    page = client.collect(place="bucuresti", max_results=45)
    assert len(page.listings) == 45
    assert page.pages_read == 2
    assert client.requested == [root, f"{root}?page=2"]


def test_collect_stops_when_the_results_do():
    root = f"{imoradar.BASE}/apartamente-de-vanzare/bucuresti"
    client = _FakeClient({root: props([raw()], last_page=3)})
    page = client.collect(place="bucuresti", max_results=200)
    assert len(page.listings) == 1


def test_a_name_resolves_to_the_published_paths_that_carry_it():
    client = _FakeClient({}, places=("bucuresti/sector-6/militari", "judetul-cluj/cluj-napoca"))
    assert [p.path for p in client.find_places("Militari")] == ["bucuresti/sector-6/militari"]
    # Diacritics and spaces are slugified the way the portal writes them.
    assert client.find_places("Cluj-Napoca", city="cluj")[0].path == "judetul-cluj/cluj-napoca"


def test_an_unresolvable_name_returns_nothing_rather_than_the_wrong_place():
    client = _FakeClient({}, places=("bucuresti/sector-6/militari",))
    assert client.find_places("Nicăieri") == []


# -- asking-price history -------------------------------------------------


def point(date, low, high=None):
    return {"date": date, "minPrice": low, "maxPrice": high if high is not None else low}


def test_a_real_reduction_is_measured_from_the_opening_price():
    # Listing 2226030, verbatim: the opening `minPrice` is a 0 and the drop is
    # 125.000 -> 115.000, which the card's own `priceChange` corroborates.
    h = imoradar.summarise_history([point("31.08.2026", 0, 125000), point("10.09.2026", 115000)])
    assert h["observed"] is True
    assert (h["price_first_eur"], h["price_last_eur"]) == (125000, 115000)
    assert h["change_pct"] == -8.0
    assert h["drops"] == 1
    assert h["ambiguous_points"] == 0


def test_a_zero_is_a_missing_price_not_a_collapse():
    h = imoradar.summarise_history([point("01.09.2026", 0, 0), point("10.09.2026", 115000)])
    # The zero day is kept as an observation -- it still dates the listing --
    # but contributes no price, so nothing reads as a 100% fall.
    assert h["points"] == 2
    assert h["first_seen"] == "2026-09-01"
    assert h["price_first_eur"] == 115000
    assert h["change_pct"] is None


def test_a_closing_range_is_not_a_price_cut():
    # Listing 2103212: 154.000-178.500 twice, then 154.000. That is the dearer
    # of two agency ads ending, not the seller conceding 13,7%.
    h = imoradar.summarise_history(
        [
            point("10.08.2026", 154000, 178500),
            point("10.08.2026", 154000, 178500),
            point("10.08.2026", 154000),
        ]
    )
    assert h["change_pct"] is None
    assert h["drops"] == 0
    assert h["ambiguous_points"] == 2


def test_a_narrowing_range_is_not_a_cut_either():
    # Listing 2282113: (36.900-38.000) then 36.900. Reading the day's max as
    # the asking price would report a 2,9% reduction that never happened.
    h = imoradar.summarise_history([point("10.09.2026", 36900, 38000), point("11.09.2026", 36900)])
    assert h["change_pct"] is None
    assert h["drops"] == 0


def test_the_first_sighting_outruns_every_other_age_signal():
    # Listing 1686071: first seen 23.09.2025, still advertised a year later.
    h = imoradar.summarise_history([point("23.09.2025", 45000, 45004), point("12.09.2026", 45004)])
    assert h["first_seen"] == "2025-09-23"
    assert h["days_since_first_seen"] > 300


def test_prices_with_decimals_survive_and_whole_ones_stay_whole():
    h = imoradar.summarise_history([point("10.08.2026", 180449.72), point("11.08.2026", 180449)])
    assert h["price_first_eur"] == 180449.72
    assert h["price_last_eur"] == 180449
    assert isinstance(h["price_last_eur"], int)


def test_an_unreadable_date_drops_the_observation():
    # The feed writes DD.MM.YYYY here and DD-MM-YYYY in sellerSources; a point
    # that parses as neither is not silently dated today.
    h = imoradar.summarise_history([point("nu se stie", 100000), point("11.08.2026", 100000)])
    assert h["points"] == 1


def test_an_empty_history_is_reported_as_unobserved():
    h = imoradar.summarise_history([])
    assert h["observed"] is False
    assert h["points"] == 0


def test_a_rise_counts_as_no_reduction():
    h = imoradar.summarise_history([point("01.09.2026", 100000), point("10.09.2026", 110000)])
    assert h["change_pct"] == 10.0
    assert h["drops"] == 0


# -- the tool -------------------------------------------------------------


def test_the_search_tool_drops_the_mis_filed_by_default_and_counts_them(monkeypatch):
    from gemini_act.imobiliare_mcp import server

    root = f"{imoradar.BASE}/apartamente-de-vanzare/bucuresti/sector-3/titan"
    listings = [
        raw(id=1, price="476 €"),
        raw(id=2, price="150.000 €"),
        raw(id=3, price="160.000 €", address="Strada Alta 2, Titan, Sector 3"),
    ]
    monkeypatch.setattr(
        imoradar,
        "ImoradarClient",
        lambda *a, **kw: _FakeClient({root: props(listings, last_page=1)}),
    )
    out = server.cauta_imoradar(zona="Titan", oras="bucuresti")
    assert out["status"] == "success"
    assert out["excluse_neconforme"] == 1
    # The 476 € ad would otherwise lead a price-per-sqm sort.
    assert [x["price_eur"] for x in out["listings"]] == [150000, 160000]
    assert out["oferta_totala"] == 479
    assert out["portaluri"] == {"Imobiliare.ro": 2}


def test_the_search_tool_can_be_asked_for_the_mis_filed_back(monkeypatch):
    from gemini_act.imobiliare_mcp import server

    root = f"{imoradar.BASE}/apartamente-de-vanzare/bucuresti/sector-3/titan"
    listings = [raw(id=1, price="476 €"), raw(id=2, price="150.000 €")]
    monkeypatch.setattr(
        imoradar,
        "ImoradarClient",
        lambda *a, **kw: _FakeClient({root: props(listings, last_page=1)}),
    )
    out = server.cauta_imoradar(zona="Titan", include_neconforme=True)
    assert out["excluse_neconforme"] == 0
    flagged = [x for x in out["listings"] if x["price_eur"] == 476]
    assert flagged and "suspect" in flagged[0]


def test_the_search_tool_reports_an_unknown_zone_as_an_error(monkeypatch):
    from gemini_act.imobiliare_mcp import server

    monkeypatch.setattr(imoradar, "ImoradarClient", lambda *a, **kw: _FakeClient({}, places=()))
    out = server.cauta_imoradar(zona="Nicăieri", oras="bucuresti")
    assert out["status"] == "error"
    assert "Nicăieri" in out["error_message"]


def test_the_search_tool_narrows_the_room_count_through_the_url(monkeypatch):
    from gemini_act.imobiliare_mcp import server

    client = _FakeClient({})
    monkeypatch.setattr(imoradar, "ImoradarClient", lambda *a, **kw: client)
    server.cauta_imoradar(zona="Titan", filtre=server.Filters(camere=3))
    assert client.requested[0].endswith("/bucuresti/sector-3/titan/3-camere")


def test_the_search_tool_asks_for_the_owner_segment_by_path(monkeypatch):
    from gemini_act.imobiliare_mcp import server

    client = _FakeClient({})
    monkeypatch.setattr(imoradar, "ImoradarClient", lambda *a, **kw: client)
    server.cauta_imoradar(zona="Titan", doar_proprietar=True)
    assert client.requested[0].endswith("/titan/proprietar")


def test_the_history_tool_never_calls_an_empty_history_a_stable_price(monkeypatch):
    from gemini_act.imobiliare_mcp import server

    class _NoHistory(_FakeClient):
        def price_history(self, listing_id):
            return []

    monkeypatch.setattr(imoradar, "ImoradarClient", lambda *a, **kw: _NoHistory({}))
    out = server.istoric_pret_imoradar(id_anunt="999999999")
    assert out["status"] == "success"
    assert out["observat"] is False
    # An unknown id and an untracked listing look identical from this endpoint,
    # so the wording has to rule out "the price held steady".
    assert "NU înseamnă" in out["nota"]


def test_the_history_tool_reports_the_reduction_and_the_age(monkeypatch):
    from gemini_act.imobiliare_mcp import server

    class _History(_FakeClient):
        def price_history(self, listing_id):
            assert listing_id == "2226030"
            return [point("31.08.2026", 0, 125000), point("10.09.2026", 115000)]

    monkeypatch.setattr(imoradar, "ImoradarClient", lambda *a, **kw: _History({}))
    # Accepts a listing url as well as a bare id.
    out = server.istoric_pret_imoradar(id_anunt="https://www.imoradar24.ro/oferta/x-2226030")
    assert out["observat"] is True
    assert (out["pret_initial"], out["pret_curent"]) == (125000, 115000)
    assert out["schimbare_pct"] == -8.0
    assert out["reduceri"] == 1
    assert out["prima_aparitie"] == "2026-08-31"


def test_the_history_tool_surfaces_a_refusal_as_an_error(monkeypatch):
    from gemini_act.imobiliare_mcp import server

    class _Refused(_FakeClient):
        def price_history(self, listing_id):
            raise imoradar.ImoradarError("price-history -> HTTP 403")

    monkeypatch.setattr(imoradar, "ImoradarClient", lambda *a, **kw: _Refused({}))
    out = server.istoric_pret_imoradar(id_anunt="2226030")
    assert out["status"] == "error"
    assert "403" in out["error_message"]
