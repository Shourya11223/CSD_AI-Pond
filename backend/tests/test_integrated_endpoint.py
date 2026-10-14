"""
Tests for the /api/analyze-contour integrated endpoint.
"""
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SAMPLE_KML = Path(__file__).resolve().parents[1].parent / "sample_data" / "contours_1m.kml"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

REQUIRED_TOPLEVEL = [
    "filename", "grid_width", "grid_height", "grid_cell_size_m",
    "contour_count", "selected_pond", "catchment_cells",
    "catchment_area_m2", "catchment_area_ha", "catchment_area_km2",
    "catchment_pct_of_grid", "flow_accum_at_outlet",
    "flow_accum_consistent", "boundary", "diagnostics", "error",
    "time_elapsed_s",
]

REQUIRED_POND_FIELDS = [
    "rank", "row", "col", "lat", "lon", "elevation_m",
    "suitability_score", "flow_accumulation_cells",
]


def _upload(pond_rank=None):
    """Upload the sample KML via the integrated endpoint and return the response."""
    assert SAMPLE_KML.exists(), f"Sample KML not found at {SAMPLE_KML}"
    with open(SAMPLE_KML, "rb") as f:
        url = "/api/analyze-contour"
        if pond_rank is not None:
            url += f"?pond_rank={pond_rank}"
        return client.post(
            url,
            files={"file": ("contours_1m.kml", f, "application/vnd.google-earth.kml+xml")},
        )


class TestAnalyzeContourEndpoint:
    """Tests for POST /api/analyze-contour."""

    def test_health_check(self):
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_returns_200(self):
        response = _upload()
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_all_required_toplevel_fields_present(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        for field in REQUIRED_TOPLEVEL:
            assert field in data, f"Missing top-level field: {field}"

    def test_time_elapsed_s_is_positive_number(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["time_elapsed_s"], (int, float))
        assert data["time_elapsed_s"] > 0

    def test_error_is_null_on_success(self):
        response = _upload()
        assert response.status_code == 200
        assert response.json()["error"] is None

    def test_selected_pond_required_fields(self):
        response = _upload()
        assert response.status_code == 200
        pond = response.json()["selected_pond"]
        for field in REQUIRED_POND_FIELDS:
            assert field in pond, f"Missing field in selected_pond: {field}"
        assert pond["rank"] == 1  # default pond_rank=1

    def test_selected_pond_reasonable_coordinates(self):
        response = _upload()
        assert response.status_code == 200
        pond = response.json()["selected_pond"]
        assert -90 <= pond["lat"] <= 90
        assert -180 <= pond["lon"] <= 180

    def test_catchment_cells_and_areas_positive(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        assert data["catchment_cells"] > 0
        assert data["catchment_area_m2"] > 0
        assert data["catchment_area_ha"] > 0
        assert data["catchment_area_km2"] > 0
        assert 0 <= data["catchment_pct_of_grid"] <= 100

    def test_flow_accum_consistent_flag_is_true(self):
        response = _upload()
        assert response.status_code == 200
        assert response.json()["flow_accum_consistent"] is True

    def test_boundary_has_coordinate_list(self):
        response = _upload()
        assert response.status_code == 200
        boundary = response.json()["boundary"]
        coords = boundary["boundary_coordinates"]
        assert isinstance(coords, list)
        for coord in coords:
            assert isinstance(coord, list) and len(coord) == 2

    def test_diagnostics_all_pass(self):
        response = _upload()
        assert response.status_code == 200
        d = response.json()["diagnostics"]
        assert d["outlet_in_catchment"] is True
        assert d["no_duplicate_cells"] is True
        assert d["traversal_terminated_safely"] is True
        assert d["flow_accum_consistent"] is True
        assert d["area_consistent"] is True
        assert d["area_within_grid"] is True

    def test_pond_rank_parameter(self):
        response = client.post(
            "/api/analyze-contour?pond_rank=2",
            files={"file": ("contours_1m.kml", open(SAMPLE_KML, "rb"), "application/vnd.google-earth.kml+xml")},
        )
        assert response.status_code == 200
        assert response.json()["selected_pond"]["rank"] == 2


# =============================================================================
# Phase 3: Multiple Pond Candidates Tests
# =============================================================================

# Required fields for each candidate in the pond_candidates list
REQUIRED_CANDIDATE_FIELDS = [
    "rank", "row", "col", "lat", "lon", "elevation_m",
    "suitability_score", "flow_accumulation_cells",
    "local_slope_deg", "relative_elevation_m", "factor_scores",
]

REQUIRED_FACTOR_FIELDS = [
    "accumulation", "low_slope", "low_relative_elevation", "drainage_concentration",
]


class TestPondCandidatesList:
    """Tests for the multiple-pond-candidates feature (Phase 3)."""

    def test_multiple_candidates_returned(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        assert "pond_candidates" in data
        assert isinstance(data["pond_candidates"], list)
        assert len(data["pond_candidates"]) >= 2

    def test_num_candidates_matches_list_length(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        assert data["num_candidates"] == len(data["pond_candidates"])

    def test_candidates_are_ranked(self):
        response = _upload()
        assert response.status_code == 200
        ranks = [c["rank"] for c in response.json()["pond_candidates"]]
        assert ranks == sorted(ranks)

    def test_ranks_are_sequential(self):
        response = _upload()
        assert response.status_code == 200
        candidates = response.json()["pond_candidates"]
        ranks = [c["rank"] for c in candidates]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_rank_1_in_candidate_list(self):
        response = _upload()
        assert response.status_code == 200
        candidates = response.json()["pond_candidates"]
        assert any(c["rank"] == 1 for c in candidates)

    def test_all_candidates_have_required_fields(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        for i, candidate in enumerate(data["pond_candidates"]):
            for field in REQUIRED_CANDIDATE_FIELDS:
                assert field in candidate, f"Candidate {i} missing: {field}"
            for field in REQUIRED_FACTOR_FIELDS:
                assert field in candidate["factor_scores"], (
                    f"Candidate {i} factor_scores missing: {field}"
                )

    def test_scores_in_valid_range(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        for i, c in enumerate(data["pond_candidates"]):
            assert 0 <= c["suitability_score"] <= 100
            for key, val in c["factor_scores"].items():
                assert 0 <= val <= 100, f"Candidate {i} factor {key}={val} out of range"

    def test_selected_pond_matches_pond_rank(self):
        # default rank 1
        response = _upload(pond_rank=None)
        assert response.status_code == 200
        assert response.json()["selected_pond"]["rank"] == 1

        # explicit rank 1
        response = _upload(pond_rank=1)
        assert response.status_code == 200
        assert response.json()["selected_pond"]["rank"] == 1

        # rank 2 if available
        if response.json()["num_candidates"] >= 2:
            response = _upload(pond_rank=2)
            assert response.status_code == 200
            data = response.json()
            assert data["selected_pond"]["rank"] == 2
            assert any(c["rank"] == 2 for c in data["pond_candidates"])

    def test_invalid_rank_returns_error(self):
        response = client.post(
            "/api/analyze-contour?pond_rank=999",
            files={"file": ("contours_1m.kml", open(SAMPLE_KML, "rb"), "application/vnd.google-earth.kml+xml")},
        )
        assert response.status_code in (404, 422)

    def test_selected_pond_in_candidates_list(self):
        for rank in [1, 2]:
            response = _upload(pond_rank=rank)
            if response.status_code != 200:
                break
            data = response.json()
            selected_rank = data["selected_pond"]["rank"]
            assert any(c["rank"] == selected_rank for c in data["pond_candidates"])

    def test_water_exclusion_field_present(self):
        response = _upload()
        assert response.status_code == 200
        we = response.json()["water_exclusion"]
        assert isinstance(we, dict)
        for field in ("applied", "fallback_used", "features_found",
                      "feature_types", "cells_excluded", "buffer_metres",
                      "error_message"):
            assert field in we

    def test_water_exclusion_types_valid(self):
        response = _upload()
        assert response.status_code == 200
        we = response.json()["water_exclusion"]
        assert isinstance(we["applied"], bool)
        assert isinstance(we["fallback_used"], bool)
        assert isinstance(we["features_found"], int)
        assert isinstance(we["feature_types"], list)
        assert isinstance(we["cells_excluded"], int)
        assert isinstance(we["buffer_metres"], (int, float))
        assert we["error_message"] is None or isinstance(we["error_message"], str)

    def test_backward_compat_selected_pond_fields(self):
        response = _upload()
        assert response.status_code == 200
        pond = response.json()["selected_pond"]
        for field in REQUIRED_POND_FIELDS:
            assert field in pond, f"Missing backward-compat field: {field}"

    def test_candidates_sorted_by_score(self):
        response = _upload()
        assert response.status_code == 200
        scores = [c["suitability_score"] for c in response.json()["pond_candidates"]]
        assert scores == sorted(scores, reverse=True)

    def test_candidate_coords_reasonable(self):
        response = _upload()
        assert response.status_code == 200
        for c in response.json()["pond_candidates"]:
            assert -90 <= c["lat"] <= 90
            assert -180 <= c["lon"] <= 180

    def test_pond_candidates_not_empty(self):
        response = _upload()
        assert response.status_code == 200
        assert len(response.json()["pond_candidates"]) > 0

# ---------------------------------------------------------------------------
# Phase 4: Pond depth and storage volume tests
# ---------------------------------------------------------------------------


REQUIRED_POND_CAPACITY_FIELDS = [
    "usable_depth_m", "max_depth_m",
    "usable_spill_elevation_m", "spill_elevation_m",
    "cell_area_m2", "surface_area_m2",
    "storage_volume_m3", "storage_volume_litres",
    "method", "assumptions", "warnings",
    "num_slices", "neighbourhood_radius_cells", "freeboard_m",
    "candidate_elevation_m", "min_neighbour_elevation_m",
    "max_neighbour_elevation_m", "mean_neighbour_elevation_m",
    "cells_flooded_at_design_level",
]


class TestPondCapacity:
    """Tests for the Phase 4 pond capacity response field."""

    def test_pond_capacity_field_present(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        assert "pond_capacity" in data
        assert data["pond_capacity"] is not None

    def test_pond_capacity_has_all_required_fields(self):
        response = _upload()
        assert response.status_code == 200
        cap = response.json()["pond_capacity"]
        for field in REQUIRED_POND_CAPACITY_FIELDS:
            assert field in cap, f"Missing pond_capacity field: {field}"

    def test_pond_capacity_depths_positive(self):
        response = _upload()
        assert response.status_code == 200
        cap = response.json()["pond_capacity"]
        # Max depth must be >= usable depth
        assert cap["max_depth_m"] >= 0
        assert cap["usable_depth_m"] >= 0
        # If the basin is at all deep, usable depth should be positive
        # (we don't assert non-zero because terrain can be locally flat).
        if cap["max_depth_m"] > 0.5:
            assert cap["usable_depth_m"] > 0

    def test_pond_capacity_volume_positive_when_deep(self):
        response = _upload()
        assert response.status_code == 200
        cap = response.json()["pond_capacity"]
        if cap["max_depth_m"] > 0.5:
            # For a real basin on real terrain, volume should be positive
            assert cap["storage_volume_m3"] > 0
            assert cap["storage_volume_litres"] > 0

    def test_pond_capacity_litres_equal_m3_times_1000(self):
        response = _upload()
        assert response.status_code == 200
        cap = response.json()["pond_capacity"]
        assert cap["storage_volume_litres"] == pytest.approx(
            cap["storage_volume_m3"] * 1000.0, abs=1e-3
        )

    def test_pond_capacity_surface_area_not_catchment_area(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        cap = data["pond_capacity"]
        # Surface area is the local water-surface footprint of the pond
        # itself, NOT the upstream catchment area.
        # They should be very different numbers in general.
        catchment = data["catchment_area_m2"]
        if cap["usable_depth_m"] > 0:
            # Real basin: surface area must be positive and != catchment
            assert cap["surface_area_m2"] > 0
            assert cap["surface_area_m2"] != catchment
        else:
            # Flat terrain: surface_area_m2 is legitimately 0 (early-return)
            assert cap["surface_area_m2"] == 0.0

    def test_pond_capacity_candidate_elevation_matches_selected_pond(self):
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        cap = data["pond_capacity"]
        # candidate_elevation_m should match the elevation in selected_pond
        assert cap["candidate_elevation_m"] == pytest.approx(
            data["selected_pond"]["elevation_m"], abs=1e-6
        )

    def test_pond_capacity_method_described(self):
        response = _upload()
        assert response.status_code == 200
        cap = response.json()["pond_capacity"]
        assert isinstance(cap["method"], str)
        assert len(cap["method"]) > 20
        if cap["usable_depth_m"] > 0:
            # Real basin: method must describe the trapezoidal approach
            assert "trapezoidal" in cap["method"].lower()
        else:
            # Flat terrain: method must describe the no-usable-depth case
            assert "no usable depth" in cap["method"].lower()

    def test_pond_capacity_assumptions_and_warnings_are_lists(self):
        response = _upload()
        assert response.status_code == 200
        cap = response.json()["pond_capacity"]
        assert isinstance(cap["assumptions"], list)
        assert isinstance(cap["warnings"], list)
        if cap["usable_depth_m"] > 0:
            # Real basin: at least 3 assumptions recorded
            assert len(cap["assumptions"]) >= 3
            assert len(cap["warnings"]) >= 0  # warnings can be empty
        else:
            # Flat terrain: assumptions may be empty, but warnings must
            # explain the unreliability of the estimate.
            assert any("flat" in w.lower() for w in cap["warnings"])

    def test_pond_capacity_changes_with_pond_rank(self):
        # Get the default (rank 1) and a different rank
        r1 = _upload(pond_rank=1)
        r2 = _upload(pond_rank=2)
        assert r1.status_code == 200
        assert r2.status_code == 200
        d1 = r1.json()
        d2 = r2.json()
        # The selected_pond should differ between ranks
        if d2.get("error") is None and d2.get("pond_capacity") is not None:
            # pond_capacity may still match or differ depending on
            # whether the terrain is similar at the two locations.
            # We check that the candidate elevation differs when the
            # selected pond itself differs.
            if (
                d1["selected_pond"]["row"] != d2["selected_pond"]["row"]
                or d1["selected_pond"]["col"] != d2["selected_pond"]["col"]
            ):
                assert (
                    d1["pond_capacity"]["candidate_elevation_m"]
                    != d2["pond_capacity"]["candidate_elevation_m"]
                )

    def test_pond_capacity_no_hardcoded_constant_depth(self):
        # Verify that the depth is terrain-derived:
        #   max_depth = spill_elevation - candidate_elevation
        #   usable_depth = max(0, max_depth - freeboard)
        # No constant values are used.
        r = _upload()
        assert r.status_code == 200
        cap = r.json()["pond_capacity"]
        # max_depth is always non-negative and reflects the terrain
        assert cap["max_depth_m"] >= 0
        # usable_depth = max_depth - freeboard (clipped to 0)
        assert cap["usable_depth_m"] == pytest.approx(
            max(0.0, cap["max_depth_m"] - cap["freeboard_m"]), abs=1e-6
        )
        # When usable_depth > 0, max_depth must equal spill - candidate
        if cap["usable_depth_m"] > 0:
            implied_max = (
                cap["spill_elevation_m"] - cap["candidate_elevation_m"]
            )
            assert cap["max_depth_m"] == pytest.approx(implied_max, abs=1e-6)

    def test_pond_capacity_backward_compat(self):
        # The Phase 1-3 fields must still be present and correct
        response = _upload()
        assert response.status_code == 200
        data = response.json()
        # Original fields still present
        for field in [
            "selected_pond", "pond_candidates", "catchment_area_m2",
            "water_exclusion", "num_candidates",
        ]:
            assert field in data, f"Missing backward-compat field: {field}"
        # And the new pond_capacity is there too
        assert "pond_capacity" in data
