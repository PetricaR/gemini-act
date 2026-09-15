"""Tests for the location & imagery layer behind the web report.

Nothing here touches the network: the point is the projection math the browser
overlay depends on, and the degradation path when no Maps key is configured.
"""

from __future__ import annotations

import math

import pytest

from imobiliare.api import imagery


class TestProjection:
    """Web Mercator, mirrored in `web/src/lib/mercator.js`."""

    def test_projects_null_island_to_world_centre(self) -> None:
        size = imagery.world_size(15)
        x, y = imagery.project(0.0, 0.0, 15)
        assert x == pytest.approx(size / 2)
        assert y == pytest.approx(size / 2)

    def test_longitude_increases_x_monotonically(self) -> None:
        west, _ = imagery.project(44.5, 26.0, 16)
        east, _ = imagery.project(44.5, 26.1, 16)
        assert east > west

    def test_northern_latitude_decreases_y(self) -> None:
        _, south = imagery.project(44.4, 26.0, 16)
        _, north = imagery.project(44.6, 26.0, 16)
        assert north < south

    def test_zoom_step_doubles_pixel_distance(self) -> None:
        """A pin's offset from the centre must double per zoom level, which is
        what makes the browser's percentage positioning agree with the image."""
        centre = imagery.project(44.48, 26.09, 15)
        point = imagery.project(44.48, 26.10, 15)
        centre_next = imagery.project(44.48, 26.09, 16)
        point_next = imagery.project(44.48, 26.10, 16)
        assert (point_next[0] - centre_next[0]) == pytest.approx(
            2 * (point[0] - centre[0]), rel=1e-9
        )

    def test_meters_per_pixel_matches_known_value(self) -> None:
        # 156543.034 * cos(lat) / 2^z, the standard Google/OSM scale.
        expected = 156543.03392 * math.cos(math.radians(44.4789829)) / 2**16
        assert imagery.meters_per_pixel(44.4789829, 16) == pytest.approx(expected)


class TestFitZoom:
    def test_radius_fits_inside_the_map_height(self) -> None:
        zoom = imagery.fit_zoom(44.4789829, 500, imagery.MAP_HEIGHT)
        radius_px = 500 / imagery.meters_per_pixel(44.4789829, zoom)
        assert radius_px <= imagery.MAP_HEIGHT / 2

    def test_picks_the_largest_zoom_that_still_fits(self) -> None:
        lat, radius, height = 44.4789829, 500, imagery.MAP_HEIGHT
        zoom = imagery.fit_zoom(lat, radius, height)
        one_closer = 500 / imagery.meters_per_pixel(lat, zoom + 1)
        assert one_closer > height / 2 - 22

    def test_larger_radius_zooms_out(self) -> None:
        assert imagery.fit_zoom(44.48, 2000, 640) < imagery.fit_zoom(44.48, 500, 640)


class TestAccessibilityScore:
    def test_empty_surroundings_score_zero(self) -> None:
        assert imagery._accessibility_score({}) == 0.0

    def test_closer_amenities_score_higher(self) -> None:
        near = {"metrou": [{"distanta_m": 120}], "supermarket": [{"distanta_m": 90}]}
        far = {"metrou": [{"distanta_m": 950}], "supermarket": [{"distanta_m": 980}]}
        assert imagery._accessibility_score(near) > imagery._accessibility_score(far)

    def test_score_stays_within_bounds(self) -> None:
        everything = {
            category: [{"distanta_m": 50}, {"distanta_m": 80}, {"distanta_m": 120}]
            for category in imagery.CATEGORY_META
        }
        score = imagery._accessibility_score(everything)
        assert 0.0 <= score <= 10.0
        assert score == pytest.approx(10.0, abs=0.2)


class TestCategoryMetadata:
    def test_every_searched_category_has_a_pin_definition(self) -> None:
        """A category Places is queried for but the UI has no icon or colour for
        would silently render as a generic grey pin."""
        from imobiliare.mcp import maps

        assert set(maps.PLACE_TYPES) == set(imagery.CATEGORY_META)

    def test_each_category_defines_label_icon_and_colour(self) -> None:
        for key, meta in imagery.CATEGORY_META.items():
            assert meta["eticheta"], key
            assert meta["icon"], key
            assert meta["culoare"].startswith("#"), key


class TestDegradationWithoutKey:
    def test_location_block_reports_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No Maps key must produce a labelled, renderable block — not an
        exception and not a half-built one the UI would try to draw."""
        monkeypatch.setattr(imagery.maps, "available", lambda: False)
        imagery._DATA_CACHE._data.clear()

        block = imagery.build_location_block("Strada Inexistentă 1, București")

        assert block["status"] == "indisponibil"
        assert "Google Maps" in block["motiv"]
        assert "harta" not in block

    def test_facilities_reports_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(imagery.maps, "available", lambda: False)
        monkeypatch.setattr(imagery.maps, "nearby", lambda *a, **k: None)
        imagery._DATA_CACHE._data.clear()

        result = imagery.facilities(44.48, 26.09, 500)

        assert result["status"] == "indisponibil"
        assert result["categorii"] == {}

    def test_known_coordinates_skip_geocoding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Passing lat/lon must not spend a geocode call."""
        monkeypatch.setattr(
            imagery.maps, "geocode", lambda *a, **k: pytest.fail("geocode should not be called")
        )
        monkeypatch.setattr(imagery.maps, "available", lambda: True)
        monkeypatch.setattr(imagery.maps, "nearby", lambda *a, **k: {})
        monkeypatch.setattr(imagery.maps, "street_view_metadata", lambda *a, **k: None)
        imagery._DATA_CACHE._data.clear()

        block = imagery.build_location_block("oriunde", lat=44.5, lon=26.1)

        assert block["status"] == "success"
        assert block["lat"] == 44.5
        assert block["harta"]["raza_m"] == 500


class TestTTLCache:
    def test_expired_entries_are_dropped(self) -> None:
        cache = imagery._TTLCache(ttl=-1)
        cache.set("k", "v")
        assert cache.get("k") is None

    def test_eviction_keeps_the_cache_bounded(self) -> None:
        cache = imagery._TTLCache(ttl=60, maxsize=3)
        for index in range(6):
            cache.set(f"k{index}", index)
        assert len(cache._data) <= 3
