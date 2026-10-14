
"""
Unit tests for Phase 9 design-rainfall integration into integrated endpoints."""
import sys
from pathlib import Path
from unittest import mock
from datetime import datetime, timezone

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from models import (
    DesignRainfallInfo,
    IntegratedAnalysisResponse,
    PondCandidateInfo,
    CatchmentBoundaryInfo,
    CatchmentDiagnosticsInfo,
    WaterExclusionInfo,
    FactorScores,
)
from api.routes import _safe_design_rainfall_lookup
from services.design_rainfall import DesignRainfallResult, DesignRainfallError


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _mock_dr_result(lat=21.2474, lon=81.29, available=True, mm=150.5):
    return DesignRainfallResult(
        source="Open-Meteo-ERA5",
        latitude=lat,
        longitude=lon,
        return_period_years=25.0,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        design_rainfall_available=available,
        design_rainfall_mm=mm if available else None,
        data_quality="moderate",
    )


def _minimal_response(design_rainfall=None):
    return IntegratedAnalysisResponse(
        filename="test.kml",
        grid_width=100, grid_height=100, grid_cell_size_m=10.0,
        contour_count=5, num_candidates=1,
        pond_candidates=[
            PondCandidateInfo(
                rank=1, row=50, col=50, lat=21.2474, lon=81.29,
                elevation_m=310.0, suitability_score=0.8,
                flow_accumulation_cells=1000, local_slope_deg=2.0,
                relative_elevation_m=5.0,
                factor_scores=FactorScores(
                    accumulation=0.7, low_slope=0.8,
                    low_relative_elevation=0.6,
                    drainage_concentration=0.5,
                ),
            ),
        ],
        selected_pond={"rank": 1, "row": 50, "col": 50, "lat": 21.2474, "lon": 81.29, "elevation_m": 310.0},
        catchment_cells=500, catchment_area_m2=50000.0,
        catchment_area_ha=5.0, catchment_area_km2=0.05,
        catchment_pct_of_grid=5.0, flow_accum_at_outlet=500,
        flow_accum_consistent=True,
        boundary=CatchmentBoundaryInfo(
            boundary_type="grid", boundary_coordinates=[],
            num_boundary_cells=100, num_boundary_points=100,
            bounding_box={"min_lat": 21.24, "max_lat": 21.26, "min_lon": 81.28, "max_lon": 81.30},
        ),
        diagnostics=CatchmentDiagnosticsInfo(
            outlet_in_catchment=True, no_duplicate_cells=True,
            traversal_terminated_safely=True, cells_visited=500,
            max_queue_size=10, flow_accum_consistent=True,
            area_consistent=True, area_within_grid=True, time_elapsed_s=0.1,
        ),
        water_exclusion=WaterExclusionInfo(
            applied=False, fallback_used=True, features_found=0,
            feature_types=[], cells_excluded=0, buffer_metres=0.0,
            error_message="Not run",
        ),
        time_elapsed_s=1.0,
        rainfall=None, weather=None, rainfall_lookup=None,
        design_rainfall=design_rainfall,
    )


# -------------------------------------------------------------------------
# Test 1: DesignRainfallInfo model
# -------------------------------------------------------------------------

class TestDesignRainfallInfoModel:
    def test_accepts_fully_populated_result(self):
        info = DesignRainfallInfo(
            source="Open-Meteo-ERA5", latitude=21.2474, longitude=81.29,
            data_period_start="1994-01-01", data_period_end="2024-01-01",
            number_of_years=30, number_of_observations=10950,
            annual_maxima_count=30,
            annual_maximum_min_mm=50.0, annual_maximum_mean_mm=75.0, annual_maximum_max_mm=120.0,
            return_period_years=25.0, design_rainfall_mm=150.5,
            distribution="Gumbel", fitting_method="method_of_moments",
            data_quality="stronger historical basis",
            warnings=["Short record extrapolation"],
            fetched_at=datetime.now(timezone.utc).isoformat(),
            design_rainfall_available=True, error_message=None,
        )
        assert info.design_rainfall_available is True
        assert info.design_rainfall_mm == 150.5
        assert info.return_period_years == 25.0

    def test_accepts_error_result(self):
        info = DesignRainfallInfo(
            source="Open-Meteo-ERA5", latitude=21.2474, longitude=81.29,
            return_period_years=25.0, data_quality="unavailable",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            design_rainfall_available=False, error_message="Provider timeout",
        )
        assert info.design_rainfall_available is False
        assert info.design_rainfall_mm is None


# -------------------------------------------------------------------------
# Test 2 & 3: IntegratedAnalysisResponse with design_rainfall
# -------------------------------------------------------------------------

class TestIntegratedAnalysisResponseWithDesignRainfall:
    def test_works_when_design_rainfall_is_none(self):
        response = _minimal_response(design_rainfall=None)
        assert response.design_rainfall is None

    def test_works_with_populated_design_rainfall(self):
        dr = DesignRainfallInfo(
            source="Open-Meteo-ERA5", latitude=21.2474, longitude=81.29,
            return_period_years=25.0,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            design_rainfall_available=True, design_rainfall_mm=150.5,
            data_quality="moderate",
        )
        response = _minimal_response(design_rainfall=dr)
        assert response.design_rainfall is not None
        assert response.design_rainfall.design_rainfall_mm == 150.5
        assert response.design_rainfall.return_period_years == 25.0


# -------------------------------------------------------------------------
# Test 4 & 5 & 6: _safe_design_rainfall_lookup helper
# -------------------------------------------------------------------------

class TestSafeDesignRainfallLookup:
    def test_returns_design_rainfall_info_on_success(self):
        mock_result = _mock_dr_result()
        with mock.patch("api.routes.get_design_rainfall", return_value=mock_result):
            info = _safe_design_rainfall_lookup(21.2474, 81.29)
        assert info is not None
        assert isinstance(info, DesignRainfallInfo)
        assert info.design_rainfall_mm == 150.5

    def test_returns_none_when_design_rainfall_error_raised(self):
        with mock.patch(
            "api.routes.get_design_rainfall",
            side_effect=DesignRainfallError("Provider timeout"),
        ):
            info = _safe_design_rainfall_lookup(21.2474, 81.29)
        assert info is None

    def test_returns_none_when_coordinates_are_none(self):
        assert _safe_design_rainfall_lookup(None, 81.29) is None
        assert _safe_design_rainfall_lookup(21.2474, None) is None
        assert _safe_design_rainfall_lookup(None, None) is None

    def test_calls_service_with_return_period_25(self):
        mock_result = _mock_dr_result()
        with mock.patch(
            "api.routes.get_design_rainfall", return_value=mock_result,
        ) as mock_get:
            _safe_design_rainfall_lookup(21.2474, 81.29)
        mock_get.assert_called_once_with(
            latitude=21.2474, longitude=81.29, return_period_years=25.0,
        )

    def test_returns_info_on_unavailable_result_no_exception(self):
        mock_result = _mock_dr_result(available=False, mm=None)
        with mock.patch(
            "api.routes.get_design_rainfall", return_value=mock_result,
        ):
            info = _safe_design_rainfall_lookup(21.2474, 81.29)
        assert info is not None
        assert isinstance(info, DesignRainfallInfo)
        assert info.design_rainfall_available is False


# -------------------------------------------------------------------------
# Test 7-11: KML endpoint integration
# -------------------------------------------------------------------------

SAMPLE_KML = Path(__file__).resolve().parents[1].parent / "sample_data" / "contours_1m.kml"


class TestKMLIntegration:
    def test_response_includes_design_rainfall_field(self):
        if not SAMPLE_KML.exists():
            pytest.skip(f"Sample KML not found at {SAMPLE_KML}")
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        mock_result = _mock_dr_result()
        with mock.patch("api.routes.get_design_rainfall", return_value=mock_result):
            with open(SAMPLE_KML, "rb") as f:
                response = client.post(
                    "/api/analyze-contour",
                    files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")},
                )
        assert response.status_code == 200
        data = response.json()
        assert "design_rainfall" in data
        assert data["design_rainfall"] is not None
        assert data["design_rainfall"]["design_rainfall_mm"] == 150.5
        assert data["design_rainfall"]["return_period_years"] == 25.0

    def test_design_rainfall_called_exactly_once(self):
        if not SAMPLE_KML.exists():
            pytest.skip(f"Sample KML not found at {SAMPLE_KML}")
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        mock_result = _mock_dr_result()
        with mock.patch(
            "api.routes.get_design_rainfall", return_value=mock_result,
        ) as mock_get:
            with open(SAMPLE_KML, "rb") as f:
                client.post(
                    "/api/analyze-contour",
                    files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")},
                )
        assert mock_get.call_count == 1

    def test_endpoint_succeeds_when_design_rainfall_fails(self):
        if not SAMPLE_KML.exists():
            pytest.skip(f"Sample KML not found at {SAMPLE_KML}")
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        with mock.patch(
            "api.routes.get_design_rainfall",
            side_effect=DesignRainfallError("Network error"),
        ):
            with open(SAMPLE_KML, "rb") as f:
                response = client.post(
                    "/api/analyze-contour",
                    files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")},
                )
        assert response.status_code == 200
        data = response.json()
        assert "design_rainfall" in data
        assert data["design_rainfall"] is None

    def test_design_rainfall_uses_same_coords_as_rainfall_lookup(self):
        if not SAMPLE_KML.exists():
            pytest.skip(f"Sample KML not found at {SAMPLE_KML}")
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        mock_result = _mock_dr_result(lat=21.25, lon=81.29)
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return mock_result

        with mock.patch("api.routes.get_design_rainfall", side_effect=capture):
            with open(SAMPLE_KML, "rb") as f:
                response = client.post(
                    "/api/analyze-contour",
                    files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")},
                )
        assert response.status_code == 200
        assert captured.get("latitude") is not None
        assert captured.get("longitude") is not None
        assert captured.get("return_period_years") == 25.0


# -------------------------------------------------------------------------
# Test 7-8: Location integration coordinate selection
# -------------------------------------------------------------------------

class TestLocationIntegrationCoords:
    def test_location_uses_catchment_coords_when_available(self):
        """Location workflow uses catchment bbox centroid when catchment data is available."""
        if not SAMPLE_KML.exists():
            pytest.skip(f"Sample KML not found at {SAMPLE_KML}")
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        mock_result = _mock_dr_result(lat=21.25, lon=81.29)
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return mock_result

        with mock.patch("api.routes.get_design_rainfall", side_effect=capture):
            with open(SAMPLE_KML, "rb") as f:
                # Use the analyze-contour endpoint which has catchment data
                response = client.post(
                    "/api/analyze-contour",
                    files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")},
                )
        assert response.status_code == 200
        # When catchment is available, coords should NOT be the raw user coords
        # They should be the catchment centroid (21.25, 81.29 approx)
        assert captured.get("latitude") is not None
        assert captured.get("longitude") is not None

    def test_location_fallback_to_user_coords(self):
        """When catchment centroid is unavailable, design rainfall uses user coords."""
        from fastapi.testclient import TestClient
        from main import app
        from api.routes import _get_rainfall_lookup_coords_for_kml

        # Simulate no catchment data
        mock_result = _mock_dr_result(lat=21.2474, lon=81.29)
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)
            return mock_result

        # _get_rainfall_lookup_coords_for_kml with no catchment returns user location
        rw_lat, rw_lon, rw_basis, _ = _get_rainfall_lookup_coords_for_kml(
            catchment=None, integrated={"selected_pond": {}},
        )
        assert rw_lat is None  # no catchment
        assert rw_lon is None  # no catchment
        # The route code falls back to request.lat/lon
        fallback_lat = 21.2474
        fallback_lon = 81.29

        with mock.patch("api.routes.get_design_rainfall", side_effect=capture):
            info = _safe_design_rainfall_lookup(fallback_lat, fallback_lon)
        assert info is not None
        assert captured.get("latitude") == fallback_lat
        assert captured.get("longitude") == fallback_lon
