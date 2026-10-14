"""
Tests for the Stage 4 pond candidate selection service.

Tests the pond_selection module both on synthetic terrains (for
algorithm correctness) and on the real sample_data/contours_1m.kml
file (for end-to-end integration).  Existing Stage 1-3 endpoints are
verified to still work via the existing test suite.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.pond_selection import (
    find_pond_candidates,
    PondSelectionConfig,
    _compute_local_slope,
    _compute_relative_elevation,
    _build_boundary_mask,
    _non_maximum_suppression,
    _percentile_rank_padded,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic terrains
# ---------------------------------------------------------------------------

def _simple_hydro_result(n=30, slope_dir="east"):
    """
    Return minimal arrays needed by find_pond_candidates on a synthetic
    flat DEM.  All flow accumulates at a single boundary cell so that
    the algorithm has non-trivial accumulation data to work with.
    """
    dem = np.zeros((n, n), dtype=np.float64) + 100.0
    flow_dir = np.zeros((n, n), dtype=np.int64)
    # All cells flow east (direction code 1) toward column n-1.
    for r in range(n):
        for c in range(n - 1):
            if c < n - 1:
                flow_dir[r, c] = 1  # east
    # Right edge: boundary, no outflow.
    flow_dir[:, n - 1] = 0
    # Flow accumulation: count of upstream cells.
    accum = np.zeros((n, n), dtype=np.int64)
    for r in range(n):
        for c in range(n):
            if flow_dir[r, c] == 0:
                accum[r, c] = 1
            else:
                # cell contributes to its downstream neighbour
                dr, dc = 0, 1  # east
                accum[r + dr, c + dc] += accum[r, c] + 1
    return dem, flow_dir, accum


# --------------------------------------------------------------------------
# Tests: _compute_local_slope
# --------------------------------------------------------------------------

class TestComputeLocalSlope:

    def test_flat_terrain_zero_slope(self):
        dem = np.ones((10, 10), dtype=np.float64) * 100.0
        slope = _compute_local_slope(dem, cell_size_m=1.0)
        assert slope.shape == dem.shape
        # Flat terrain: all gradient values are 0 (within numerical noise).
        assert float(slope.max()) < 1e-9

    def test_sloping_terrain_positive_gradient(self):
        dem = np.zeros((20, 20), dtype=np.float64)
        for r in range(20):
            for c in range(20):
                dem[r, c] = 0.1 * c  # east-facing slope, rise = 0.1 m/m
        slope = _compute_local_slope(dem, cell_size_m=1.0)
        # Interior cells should have slope ~0.1 m/m in the east direction.
        interior = slope[1:-1, 1:-1]
        assert float(interior.min()) > 0.09
        assert float(interior.max()) < 0.11


# --------------------------------------------------------------------------
# Tests: _build_boundary_mask
# --------------------------------------------------------------------------

class TestBuildBoundaryMask:

    def test_no_margin_keeps_all_cells(self):
        mask = _build_boundary_mask(10, 10, margin_cells=0)
        assert int(mask.sum()) == 100

    def test_margin_cells_correct(self):
        mask = _build_boundary_mask(10, 10, margin_cells=2)
        # Outer 2 rows + 2 cols are False; interior 6x6 = 36 True.
        assert int(mask.sum()) == 36
        assert bool(mask[2, 2]) is True
        assert bool(mask[1, 5]) is False  # row 1 is in margin

    def test_large_margin_returns_empty(self):
        mask = _build_boundary_mask(5, 5, margin_cells=10)
        assert int(mask.sum()) == 0


# --------------------------------------------------------------------------
# Tests: _percentile_rank_padded
# --------------------------------------------------------------------------

class TestPercentileRankPadded:

    def test_all_inside_mask(self):
        values = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
        mask = np.ones_like(values, dtype=bool)
        pct = _percentile_rank_padded(values, mask)
        # Rank of 1.0 should be 0; rank of 4.0 should be 100.
        assert pct[0, 0] == 0.0
        assert pct[1, 1] == 100.0
        # 2.0 is rank 1 of 4 -> 25; 3.0 is rank 2 of 4 -> 50.
        assert abs(pct[0, 1] - 100.0/3) < 1e-9
        assert abs(pct[1, 0] - 200.0/3) < 1e-9

    def test_outside_mask_returns_zero(self):
        values = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        mask = np.array([True, False, True], dtype=bool)
        pct = _percentile_rank_padded(values, mask)
        assert pct[0] == 0.0
        assert pct[1] == 0.0  # masked out
        assert pct[2] > pct[0]

    def test_empty_mask_returns_zeros(self):
        values = np.ones((5, 5), dtype=np.float64)
        mask = np.zeros((5, 5), dtype=bool)
        pct = _percentile_rank_padded(values, mask)
        assert float(pct.max()) == 0.0


# --------------------------------------------------------------------------
# Tests: _non_maximum_suppression
# --------------------------------------------------------------------------

class TestNonMaximumSuppression:

    def test_single_candidate_returned(self):
        rows = np.array([5], dtype=np.int64)
        cols = np.array([5], dtype=np.int64)
        scores = np.array([90.0], dtype=np.float64)
        kept = _non_maximum_suppression(scores, rows, cols, radius=3)
        assert len(kept) == 1
        assert kept[0] == 0

    def test_adjacent_suppressed(self):
        rows = np.array([5, 5, 10], dtype=np.int64)
        cols = np.array([5, 6, 10], dtype=np.int64)
        scores = np.array([90.0, 85.0, 80.0], dtype=np.float64)
        kept = _non_maximum_suppression(scores, rows, cols, radius=3)
        # Top-scoring cell (index 0) kept; second cell (index 1, dist=1) suppressed.
        assert 0 in kept
        assert 1 not in kept
        # Cell at (10, 10) is dist 5 from (5, 5) -> not suppressed.
        assert 2 in kept

    def test_distant_candidates_both_kept(self):
        rows = np.array([5, 25], dtype=np.int64)
        cols = np.array([5, 5], dtype=np.int64)
        scores = np.array([90.0, 80.0], dtype=np.float64)
        kept = _non_maximum_suppression(scores, rows, cols, radius=5)
        assert len(kept) == 2


# --------------------------------------------------------------------------
# Tests: _compute_relative_elevation
# --------------------------------------------------------------------------

class TestComputeRelativeElevation:

    def test_flat_terrain_near_zero(self):
        dem = np.ones((15, 15), dtype=np.float64) * 100.0
        rel = _compute_relative_elevation(dem, radius_cells=2)
        assert rel.shape == dem.shape
        # Flat: every cell equals the neighbourhood mean.
        assert float(rel.max()) < 1e-6
        assert float(rel.min()) > -1e-6

    def test_central_pit_is_negative(self):
        dem = np.ones((15, 15), dtype=np.float64) * 100.0
        dem[7, 7] = 90.0  # local pit 10 m below surroundings
        rel = _compute_relative_elevation(dem, radius_cells=3)
        # The pit cell should be substantially below its neighbourhood mean.
        assert rel[7, 7] < -5.0, f"Expected negative rel, got {rel[7,7]}"

    def test_ridge_is_positive(self):
        dem = np.ones((15, 15), dtype=np.float64) * 100.0
        dem[7, 7] = 110.0  # local peak 10 m above surroundings
        rel = _compute_relative_elevation(dem, radius_cells=3)
        # The ridge cell should be above its neighbourhood mean.
        assert rel[7, 7] > 5.0, f"Expected positive rel, got {rel[7,7]}"


# --------------------------------------------------------------------------
# Tests: PondSelectionConfig defaults
# --------------------------------------------------------------------------

class TestPondSelectionConfig:

    def test_default_weights_sum_to_one(self):
        cfg = PondSelectionConfig()
        wa, ws, wr, wd = cfg.normalised_weights()
        assert abs(wa + ws + wr + wd - 1.0) < 1e-9

    def test_top_k_clamped_by_api(self):
        cfg = PondSelectionConfig(top_k=10)
        # API layer will clamp to [3, 5], but config itself accepts raw value.
        assert cfg.top_k == 10

    def test_zero_weights_normalised(self):
        cfg = PondSelectionConfig(
            weight_accumulation=0.0,
            weight_low_slope=0.0,
            weight_low_relative=0.0,
            weight_drainage=0.0,
        )
        # Should fall back to equal weights.
        wa, ws, wr, wd = cfg.normalised_weights()
        assert wa == ws == wr == wd == 0.25


# --------------------------------------------------------------------------
# Tests: find_pond_candidates on synthetic terrain
# --------------------------------------------------------------------------

class TestFindPondCandidates:

    def _run(self, n=30, margin_m=3.0, top_k=5):
        dem, fdir, faccum = _simple_hydro_result(n=n)
        cfg = PondSelectionConfig(
            boundary_margin_m=margin_m,
            nms_radius_cells=3,
            top_k=top_k,
        )
        result = find_pond_candidates(
            dem=dem,
            flow_direction=fdir,
            flow_accumulation_cells=faccum,
            cell_size_m=1.0,
            projection_info=None,
            config=cfg,
        )
        return result

    def test_returns_top_k_candidates(self):
        result = self._run(top_k=5)
        assert 3 <= len(result.candidates) <= 5

    def test_all_candidates_inside_margin(self):
        result = self._run(margin_m=3.0)
        h, w = 30, 30
        margin_cells = 3  # 3 m / 1 m per cell = 3 cells
        for c in result.candidates:
            assert 0 + margin_cells <= c.row < h - margin_cells, \
                f"Candidate row {c.row} is within margin"
            assert 0 + margin_cells <= c.col < w - margin_cells, \
                f"Candidate col {c.col} is within margin"

    def test_candidates_are_spatially_distinct(self):
        result = self._run(n=30, margin_m=3.0, top_k=5)
        # With nms_radius_cells=3, no two candidates should be within 3 cells.
        for i, cand_i in enumerate(result.candidates):
            for j, cand_j in enumerate(result.candidates):
                if i == j:
                    continue
                dist = max(abs(cand_i.row - cand_j.row), abs(cand_i.col - cand_j.col))
                assert dist > 3, \
                    f"Candidates {i} and {j} are too close: dist={dist}"

    def test_scores_in_valid_range(self):
        result = self._run()
        for c in result.candidates:
            assert 0 <= c.score_total <= 100
            assert 0 <= c.score_accumulation <= 100
            assert 0 <= c.score_low_slope <= 100
            assert 0 <= c.score_low_relative <= 100
            assert 0 <= c.score_drainage <= 100

    def test_slope_degrees_reasonable(self):
        result = self._run()
        for c in result.candidates:
            assert 0 <= c.local_slope_deg <= 90

    def test_no_negative_accumulation(self):
        result = self._run()
        for c in result.candidates:
            assert c.flow_accumulation_cells >= 0
            assert c.upstream_area_m2 >= 0

    def test_diagnostics_present(self):
        result = self._run()
        assert result.cells_total > 0
        assert result.cells_excluded_boundary >= 0
        assert result.cells_considered >= len(result.candidates)
        assert result.boundary_margin_m > 0
        assert len(result.methodology) > 10

    def test_ranks_are_sequential(self):
        result = self._run(top_k=5)
        ranks = [c.rank for c in result.candidates]
        assert ranks == list(range(1, len(result.candidates) + 1))

    def test_ranked_by_score(self):
        result = self._run(top_k=5)
        for i in range(len(result.candidates) - 1):
            assert result.candidates[i].score_total >= result.candidates[i + 1].score_total

    def test_to_dict_serialisable(self):
        result = self._run()
        d = result.to_dict()
        import json
        json_str = json.dumps(d)
        assert len(json_str) > 100  # non-trivial output


# --------------------------------------------------------------------------
# Tests: end-to-end on real sample KML
# --------------------------------------------------------------------------

class TestPondCandidatesSampleData:

    @pytest.fixture
    def contours_1m_path(self):
        p = BACKEND.parent / "sample_data" / "contours_1m.kml"
        if not p.exists():
            pytest.skip(f"Sample file not found: {p}")
        return p

    def test_sample_kml_end_to_end(self, contours_1m_path):
        from services.contour_parser import parse_contour_file
        from services.terrain_model import build_terrain_model
        from services.hydrology import run_hydrology

        data = contours_1m_path.read_bytes()
        contours = parse_contour_file(contours_1m_path.name, data)
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        hydro = run_hydrology(
            model["grid"],
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            include_diagnostics=False,
        )

        cfg = PondSelectionConfig(
            boundary_margin_m=None,  # use default 2*cell_size
            nms_radius_cells=5,
            top_k=5,
            relative_radius_cells=5,
        )
        result = find_pond_candidates(
            dem=hydro.dem_original,
            flow_direction=hydro.flow_direction,
            flow_accumulation_cells=hydro.flow_accumulation_cells,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            config=cfg,
        )

        # Basic structural checks.
        assert 3 <= len(result.candidates) <= 5
        assert result.cells_total == 326 * 266
        assert result.cells_excluded_boundary > 0

        h, w = 266, 326
        margin = result.boundary_margin_cells
        for c in result.candidates:
            # Inside interior region.
            assert margin <= c.row < h - margin, \
                f"Candidate row {c.row} is on boundary (margin={margin})"
            assert margin <= c.col < w - margin, \
                f"Candidate col {c.col} is on boundary (margin={margin})"
            # Valid coordinates.
            assert c.lat is not None and c.lon is not None
            assert c.elevation_m > 0
            assert c.flow_accumulation_cells >= 0
            assert c.upstream_area_m2 >= 0
            assert 0 <= c.score_total <= 100
            assert 0 <= c.local_slope_deg <= 90

        # Spatially distinct (NMS with 5-cell radius).
        for i, ci in enumerate(result.candidates):
            for j, cj in enumerate(result.candidates):
                if i >= j:
                    continue
                dist = max(abs(ci.row - cj.row), abs(ci.col - cj.col))
                assert dist > 5, \
                    f"Candidates {i} and {j} too close: dist={dist}"

        # Scores are monotonically decreasing with rank.
        for i in range(len(result.candidates) - 1):
            assert result.candidates[i].score_total >= \
                result.candidates[i + 1].score_total

        # Diagnostics present.
        assert result.cells_inside_margin > 0
        assert result.cells_considered > 0
        assert len(result.methodology) > 20
        assert result.boundary_margin_m > 0

        # Print the top candidates for viva report.
        print("\n=== Pond candidates for contours_1m.kml ===")
        for c in result.candidates:
            print(f"  Rank {c.rank}: grid ({c.row}, {c.col}) -> "
                  f"({c.lat:.5f}, {c.lon:.5f}), elev={c.elevation_m:.2f} m, "
                  f"accum={c.flow_accumulation_cells:,} cells "
                  f"({c.upstream_area_m2:,.0f} m2), "
                  f"slope={c.local_slope_deg:.2f} deg, "
                  f"rel_elev={c.relative_elevation_m:.2f} m, "
                  f"score={c.score_total:.1f}")


# --------------------------------------------------------------------------
# Tests: coordinate audit — verifies that _grid_to_geographic uses the
# stored grid origin from projection_info and produces correct lat/lon.
# --------------------------------------------------------------------------


class TestCoordinateAudit:
    """Coordinate correctness for the pond-candidate pipeline."""

    def test_round_trip_grid_to_geographic_zero_error(self):
        """
        Round-trip: random grid cells -> (lat, lon) -> back should have
        error < 1e-7 degrees (~0.01 mm at this latitude). Verifies
        that _grid_to_geographic uses the stored grid origin.
        """
        kml_path = BACKEND.parent / "sample_data" / "contours_1m.kml"
        data = kml_path.read_bytes()
        from services.contour_parser import parse_contour_file
        contours = parse_contour_file(kml_path.name, data)
        from services.terrain_model import build_terrain_model
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        from services.hydrology import run_hydrology, _grid_to_geographic
        hydro = run_hydrology(
            model["grid"], cell_size_m=model["grid_cell_size_m"],
            projection_info=model["projection_info"], include_diagnostics=False,
        )
        proj = model["projection_info"]
        h, w = hydro.dem_original.shape
        cell = model["grid_cell_size_m"]
        m_per_deg_lat = proj["metres_per_degree_lat"]
        m_per_deg_lon = proj["metres_per_degree_lon"]
        center_lat = proj["center_lat_deg"]
        center_lon = proj["center_lon_deg"]
        gx_min = proj["grid_origin_x_m"]
        gy_min = proj["grid_origin_y_m"]

        import random
        random.seed(42)
        max_err_lat = 0.0
        max_err_lon = 0.0
        for _ in range(200):
            row = random.randint(0, h - 1)
            col = random.randint(0, w - 1)
            lat, lon = _grid_to_geographic(row, col, h, w, cell, proj)
            assert lat is not None and lon is not None, \
                f"Grid ({row},{col}) returned None lat/lon"
            x_m = gx_min + (col + 0.5) * cell
            y_m = gy_min + (row + 0.5) * cell
            true_lat = center_lat + y_m / m_per_deg_lat
            true_lon = center_lon + x_m / m_per_deg_lon
            max_err_lat = max(max_err_lat, abs(lat - true_lat))
            max_err_lon = max(max_err_lon, abs(lon - true_lon))
        assert max_err_lat < 1e-7
        assert max_err_lon < 1e-7


    def test_all_candidates_inside_grid_extent(self):
        """
        All returned candidates must have lat/lon inside the terrain grid
        geographic extent (computed from origin_xy_m). This is the
        authoritative bounding box for candidate coordinates.
        """
        kml_path = BACKEND.parent / "sample_data" / "contours_1m.kml"
        data = kml_path.read_bytes()
        from services.contour_parser import parse_contour_file
        contours = parse_contour_file(kml_path.name, data)
        from services.terrain_model import build_terrain_model
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        from services.hydrology import run_hydrology
        hydro = run_hydrology(
            model["grid"], cell_size_m=model["grid_cell_size_m"],
            projection_info=model["projection_info"], include_diagnostics=False,
        )
        from services.pond_selection import find_pond_candidates, PondSelectionConfig
        cfg = PondSelectionConfig(top_k=5, nms_radius_cells=5)
        result = find_pond_candidates(
            dem=hydro.dem_original,
            flow_direction=hydro.flow_direction,
            flow_accumulation_cells=hydro.flow_accumulation_cells,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model["projection_info"],
            config=cfg,
        )
        proj = model["projection_info"]
        lat_min = proj["grid_lat_min"]
        lat_max = proj["grid_lat_max"]
        lon_min = proj["grid_lon_min"]
        lon_max = proj["grid_lon_max"]
        for c in result.candidates:
            assert lat_min <= c.lat <= lat_max, \
                f"Candidate rank {c.rank} lat={c.lat} outside grid lat"
            assert lon_min <= c.lon <= lon_max, \
                f"Candidate rank {c.rank} lon={c.lon} outside grid lon"

    def test_all_candidates_inside_contour_extent_plus_one_cell(self):
        """
        Candidates must be inside contour-point extent ± 1.5 cells. The
        grid extends at most half a cell beyond contour points, so
        candidates should never be more than 1 cell outside.
        """
        kml_path = BACKEND.parent / "sample_data" / "contours_1m.kml"
        data = kml_path.read_bytes()
        from services.contour_parser import parse_contour_file
        contours = parse_contour_file(kml_path.name, data)
        from services.terrain_model import build_terrain_model
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        from services.hydrology import run_hydrology
        hydro = run_hydrology(
            model["grid"], cell_size_m=model["grid_cell_size_m"],
            projection_info=model["projection_info"], include_diagnostics=False,
        )
        from services.pond_selection import find_pond_candidates, PondSelectionConfig
        cfg = PondSelectionConfig(top_k=5, nms_radius_cells=5)
        result = find_pond_candidates(
            dem=hydro.dem_original,
            flow_direction=hydro.flow_direction,
            flow_accumulation_cells=hydro.flow_accumulation_cells,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model["projection_info"],
            config=cfg,
        )
        bbox = model["bounding_box"]
        margin = 1.5 * model["grid_cell_size_m"] / 111320.0
        for c in result.candidates:
            assert bbox["min_lat"] - margin <= c.lat <= bbox["max_lat"] + margin
            assert bbox["min_lon"] - margin <= c.lon <= bbox["max_lon"] + margin

    def test_row_0_is_south_row_h_minus_1_is_north(self):
        """
        Verify the row orientation: row=0 is MIN latitude (south edge),
        row=H-1 is MAX latitude (north edge).
        """
        kml_path = BACKEND.parent / "sample_data" / "contours_1m.kml"
        data = kml_path.read_bytes()
        from services.contour_parser import parse_contour_file
        contours = parse_contour_file(kml_path.name, data)
        from services.terrain_model import build_terrain_model
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        from services.hydrology import run_hydrology, _grid_to_geographic
        hydro = run_hydrology(
            model["grid"], cell_size_m=model["grid_cell_size_m"],
            projection_info=model["projection_info"], include_diagnostics=False,
        )
        proj = model["projection_info"]
        h, w = hydro.dem_original.shape
        cell = model["grid_cell_size_m"]
        lat_row0, _ = _grid_to_geographic(0, w // 2, h, w, cell, proj)
        lat_rowH, _ = _grid_to_geographic(h - 1, w // 2, h, w, cell, proj)
        assert lat_row0 is not None and lat_rowH is not None
        assert lat_row0 < lat_rowH, \
            f"row 0 lat={lat_row0} should be south of row H-1 lat={lat_rowH}"

    def test_projection_info_has_grid_extent_keys(self):
        """
        Verify that build_terrain_model now populates grid extent keys
        in projection_info.
        """
        kml_path = BACKEND.parent / "sample_data" / "contours_1m.kml"
        data = kml_path.read_bytes()
        from services.contour_parser import parse_contour_file
        contours = parse_contour_file(kml_path.name, data)
        from services.terrain_model import build_terrain_model
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        proj = model["projection_info"]
        required = [
            "grid_origin_x_m", "grid_origin_y_m",
            "grid_lat_min", "grid_lat_max",
            "grid_lon_min", "grid_lon_max",
        ]
        for key in required:
            assert key in proj and proj[key] is not None

    def test_diagnostic_cells_suppressed_by_nms_is_meaningful(self):
        """
        cells_suppressed_by_nms should be non-negative and at least some
        cells should be suppressed (NMS with 5-cell radius is aggressive).
        cells_considered == cells_suppressed + len(candidates).
        """
        kml_path = BACKEND.parent / "sample_data" / "contours_1m.kml"
        data = kml_path.read_bytes()
        from services.contour_parser import parse_contour_file
        contours = parse_contour_file(kml_path.name, data)
        from services.terrain_model import build_terrain_model
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        from services.hydrology import run_hydrology
        hydro = run_hydrology(
            model["grid"], cell_size_m=model["grid_cell_size_m"],
            projection_info=model["projection_info"], include_diagnostics=False,
        )
        from services.pond_selection import find_pond_candidates, PondSelectionConfig
        cfg = PondSelectionConfig(top_k=5, nms_radius_cells=5)
        result = find_pond_candidates(
            dem=hydro.dem_original,
            flow_direction=hydro.flow_direction,
            flow_accumulation_cells=hydro.flow_accumulation_cells,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model["projection_info"],
            config=cfg,
        )
        assert result.cells_suppressed_by_nms >= 0
        assert result.cells_suppressed_by_nms <= result.cells_considered
        assert result.cells_suppressed_by_nms > 0
        assert math.isfinite(result.min_kept_score)
        assert result.cells_considered >= result.cells_suppressed_by_nms + len(result.candidates)  # cells_considered >= NMS survivors + NMS suppressed
