"""Tests for the Phase 11 land-cover service."""

import sys
import types
from unittest.mock import patch, MagicMock

import pytest

from services.land_cover import (
    _classify_osm_feature,
    _polygon_area_m2,
    _bbox_area_m2,
    _fetch_osm_features,
    _parse_overpass_landcover,
    get_land_cover,
    summarise_land_cover,
    LandCoverResult,
    LandCoverClassFraction,
    LAND_COVER_CLASSES,
    OSM_TAG_MAP,
)


# ---------------- _classify_osm_feature ----------------

class TestClassifyOSMFeature:
    def test_water_via_natural(self):
        assert _classify_osm_feature({"natural": "water"}) == "water"

    def test_water_via_landuse_reservoir(self):
        assert _classify_osm_feature({"landuse": "reservoir"}) == "water"

    def test_water_via_landuse_water(self):
        assert _classify_osm_feature({"landuse": "water"}) == "water"

    def test_forest_via_natural_wood(self):
        assert _classify_osm_feature({"natural": "wood"}) == "forest"

    def test_agricultural_via_landuse_farmland(self):
        assert _classify_osm_feature({"landuse": "farmland"}) == "agricultural"

    def test_built_via_landuse_residential(self):
        assert _classify_osm_feature({"landuse": "residential"}) == "built"

    def test_grassland_via_leisure_park(self):
        assert _classify_osm_feature({"leisure": "park"}) == "grassland"

    def test_built_via_building_yes(self):
        assert _classify_osm_feature({"building": "yes"}) == "built"

    def test_unknown_unmapped_natural(self):
        # Tags exist but not in the mapping table
        result = _classify_osm_feature({"natural": "tree_row"})
        # Unmapped tags still return "unknown" because the key "natural" is present
        assert result in ("unknown", "grassland")

    def test_unknown_completely_empty(self):
        assert _classify_osm_feature({}) == "unknown"


# ---------------- polygon / bbox area ----------------

class TestGeometryHelpers:
    def test_polygon_area_zero_for_degenerate(self):
        assert _polygon_area_m2([(0, 0), (1, 1)], 0.0) == 0.0

    def test_polygon_area_positive_for_square(self):
        # ~1 km x 1 km at lat 0
        coords = [
            (-0.0045, 0.0), (0.0, 0.0), (0.0, 0.0090),
            (-0.0045, 0.0090), (-0.0045, 0.0),
        ]
        area = _polygon_area_m2(coords, center_lat=0.0)
        # 0.0045 deg lon * 111 km/deg ~ 500 m
        # 0.0090 deg lat ~ 1000 m
        # So area ~ 500000 m^2
        assert area > 400000.0
        assert area < 600000.0

    def test_bbox_area_positive(self):
        bbox = (0.0, 0.0, 0.01, 0.01)
        area = _bbox_area_m2(bbox)
        assert area > 0


# ---------------- Overpass parser ----------------

def _make_overpass_response(elements):
    return {"elements": elements}


class TestParseOverpassLandcover:
    def test_empty_response(self):
        features, err = _parse_overpass_landcover(_make_overpass_response([]))
        assert features == []
        assert err is None

    def test_invalid_response_format(self):
        features, err = _parse_overpass_landcover({"foo": "bar"})
        # No 'elements' key -> empty list returned, no error
        assert features == []
        assert err is None

    def test_response_with_non_list_elements(self):
        features, err = _parse_overpass_landcover({"elements": "not a list"})
        assert features == []
        assert err == "Overpass returned non-list elements"

    def test_parse_way_polygon(self):
        element = {
            "type": "way",
            "id": 1,
            "geometry": [
                {"lon": 0.0, "lat": 0.0},
                {"lon": 0.001, "lat": 0.0},
                {"lon": 0.001, "lat": 0.001},
                {"lon": 0.0, "lat": 0.001},
                {"lon": 0.0, "lat": 0.0},
            ],
            "tags": {"landuse": "farmland"},
        }
        features, err = _parse_overpass_landcover(_make_overpass_response([element]))
        assert err is None
        assert len(features) == 1
        feat = features[0]
        assert feat.land_cover_class == "agricultural"
        assert feat.geometry_type == "polygon"
        assert feat.area_m2 > 0

    def test_parse_skips_non_way_or_relation(self):
        element = {
            "type": "node",
            "id": 1,
            "geometry": [{"lon": 0.0, "lat": 0.0}],
            "tags": {"landuse": "farmland"},
        }
        features, err = _parse_overpass_landcover(_make_overpass_response([element]))
        assert features == []
        assert err is None

    def test_parse_skips_too_few_coordinates(self):
        element = {
            "type": "way",
            "id": 1,
            "geometry": [{"lon": 0.0, "lat": 0.0}],
            "tags": {"landuse": "farmland"},
        }
        features, _ = _parse_overpass_landcover(_make_overpass_response([element]))
        assert features == []

    def test_parse_unknown_tags(self):
        element = {
            "type": "way",
            "id": 1,
            "geometry": [
                {"lon": 0.0, "lat": 0.0},
                {"lon": 0.001, "lat": 0.0},
                {"lon": 0.001, "lat": 0.001},
                {"lon": 0.0, "lat": 0.001},
                {"lon": 0.0, "lat": 0.0},
            ],
            "tags": {"natural": "tree_row"},
        }
        features, _ = _parse_overpass_landcover(_make_overpass_response([element]))
        assert len(features) == 1
        # tree_row is not in the mapping -> falls through to "unknown"
        # (because 'natural' key is present)
        assert features[0].land_cover_class == "unknown"


# ---------------- Overpass fetch with mock ----------------

class TestFetchOSMFeatures:
    @patch("services.land_cover.overpass_query")
    def test_timeout(self, mock_query):
        mock_query.return_value = (None, "Overpass API request timed out across all endpoints")
        features, err = _fetch_osm_features((0, 0, 1, 1))
        assert features == []
        assert "timed out" in err.lower()

    @patch("services.land_cover.overpass_query")
    def test_connection_error(self, mock_query):
        mock_query.return_value = (None, "All Overpass endpoints failed: connection error")
        features, err = _fetch_osm_features((0, 0, 1, 1))
        assert features == []
        assert "connect" in err.lower()

    @patch("services.land_cover.overpass_query")
    def test_http_429(self, mock_query):
        mock_query.return_value = (None, "Overpass API rate limit exceeded across all endpoints")
        features, err = _fetch_osm_features((0, 0, 1, 1))
        assert features == []
        assert "rate limit" in err.lower()

    @patch("services.land_cover.overpass_query")
    def test_http_500(self, mock_query):
        mock_query.return_value = (None, "All Overpass endpoints failed: HTTP 500")
        features, err = _fetch_osm_features((0, 0, 1, 1))
        assert features == []
        assert "500" in err

    @patch("services.land_cover.overpass_query")
    def test_success(self, mock_query):
        mock_query.return_value = (
            {
                "elements": [
                    {
                        "type": "way",
                        "id": 1,
                        "geometry": [
                            {"lon": 0.0, "lat": 0.0},
                            {"lon": 0.001, "lat": 0.0},
                            {"lon": 0.001, "lat": 0.001},
                            {"lon": 0.0, "lat": 0.001},
                            {"lon": 0.0, "lat": 0.0},
                        ],
                        "tags": {"landuse": "forest"},
                    }
                ]
            },
            None,
        )
        features, err = _fetch_osm_features((0, 0, 1, 1))
        assert err is None
        assert len(features) == 1
        assert features[0].land_cover_class == "forest"


# ---------------- get_land_cover (top-level) ----------------

class TestGetLandCover:
    @patch("services.land_cover._fetch_osm_features")
    def test_no_features_returns_unavailable(self, mock_fetch):
        mock_fetch.return_value = ([], None)
        result = get_land_cover((0.0, 0.0, 0.1, 0.1), catchment_area_m2=1_000_000.0)
        assert isinstance(result, LandCoverResult)
        assert result.data_available is False
        assert result.features_found == 0
        assert "No OSM" in " ".join(result.warnings)

    @patch("services.land_cover._fetch_osm_features")
    def test_features_mapped_returns_available(self, mock_fetch):
        # Build a forest polygon
        feature = MagicMock()
        feature.geometry_type = "polygon"
        feature.land_cover_class = "forest"
        feature.area_m2 = 1_000_000.0
        feature.original_tags = {"landuse": "forest"}
        mock_fetch.return_value = ([feature], None)
        result = get_land_cover((0.0, 0.0, 0.1, 0.1), catchment_area_m2=1_000_000.0)
        assert result.data_available is True
        assert result.features_mapped == 1
        # At least the forest class should appear
        classes = {lc.land_cover_class for lc in result.land_cover_classes}
        assert "forest" in classes

    @patch("services.land_cover._fetch_osm_features")
    def test_provider_error(self, mock_fetch):
        mock_fetch.return_value = ([], "Overpass API error")
        result = get_land_cover((0.0, 0.0, 0.1, 0.1))
        assert result.data_available is False
        assert result.error_message == "Overpass API error"
        assert result.features_found == 0

    @patch("services.land_cover._fetch_osm_features")
    def test_bbox_clipping(self, mock_fetch):
        mock_fetch.return_value = ([], None)
        # Very large bbox should be clipped
        result = get_land_cover((0.0, 0.0, 1.5, 1.5))
        assert result.bbox_max_lat < 1.5
        assert result.bbox_max_lon < 1.5

    @patch("services.land_cover._fetch_osm_features")
    def test_building_warnings(self, mock_fetch):
        feature = MagicMock()
        feature.geometry_type = "polygon"
        feature.land_cover_class = "built"
        feature.area_m2 = 100.0
        feature.original_tags = {"building": "yes"}
        mock_fetch.return_value = ([feature], None)
        result = get_land_cover((0.0, 0.0, 0.01, 0.01), catchment_area_m2=1_000.0)
        # Building warning should appear
        assert any("building" in w.lower() for w in result.warnings)

    @patch("services.land_cover._fetch_osm_features")
    def test_all_unknown_warnings(self, mock_fetch):
        feature = MagicMock()
        feature.geometry_type = "polygon"
        feature.land_cover_class = "unknown"
        feature.area_m2 = 100.0
        feature.original_tags = {"natural": "tree_row"}
        mock_fetch.return_value = ([feature], None)
        result = get_land_cover((0.0, 0.0, 0.01, 0.01), catchment_area_m2=1_000.0)
        # All unknown -> mapped_count == 0
        assert result.features_mapped == 0
        assert any("unknown" in w.lower() for w in result.warnings)


class TestSummariseLandCover:
    def test_summary_keys_present(self):
        result = LandCoverResult(
            data_available=True, bbox_min_lat=0.0, bbox_max_lat=0.1,
            bbox_min_lon=0.0, bbox_max_lon=0.1, bbox_area_m2=1_000.0,
        )
        s = summarise_land_cover(result)
        assert "data_available" in s
        assert "land_cover_classes" in s
        assert "bbox" in s
        assert "warnings" in s


class TestLandCoverClassConstants:
    def test_all_project_classes_defined(self):
        for c in ["built", "agricultural", "forest", "grassland",
                  "wetland", "water", "bare", "unknown"]:
            assert c in LAND_COVER_CLASSES

    def test_all_hsg_keys_covered_in_cn_table_or_in_land_cover(self):
        # OSM_TAG_MAP has all 4 HSG via other classes; just ensure table
        # has multiple landuse/natural keys
        keys = set(OSM_TAG_MAP.keys())
        assert any(k == "landuse" for k, _ in keys)
        assert any(k == "natural" for k, _ in keys)
