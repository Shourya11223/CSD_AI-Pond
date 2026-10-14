"""
Tests for the Stage 5 catchment delineation service.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.catchment import (
    delineate_catchment,
    summarise_catchment,
    run_integrated_analysis,
    CatchmentConfig,
)
from services.hydrology import D8_OFFSETS, NO_FLOW


def _compute_accum_from_flow(flow_dir):
    """Compute flow accumulation using topological sort (indegree-based)."""
    h, w = flow_dir.shape
    # Each cell contributes 1 to its own accumulation (hydrology convention).
    accum = np.ones((h, w), dtype=np.int64)
    indegree = np.zeros((h, w), dtype=np.int64)
    for r in range(h):
        for c in range(w):
            d = int(flow_dir[r, c])
            if d == NO_FLOW or d not in D8_OFFSETS:
                continue
            dr, dc = D8_OFFSETS[d]
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w:
                indegree[nr, nc] += 1
    from collections import deque
    queue = deque()
    for r in range(h):
        for c in range(w):
            if indegree[r, c] == 0:
                queue.append((r, c))
    while queue:
        r, c = queue.popleft()
        d = int(flow_dir[r, c])
        if d == NO_FLOW or d not in D8_OFFSETS:
            continue
        dr, dc = D8_OFFSETS[d]
        nr, nc = r + dr, c + dc
        if not (0 <= nr < h and 0 <= nc < w):
            continue
        accum[nr, nc] += accum[r, c]
        indegree[nr, nc] -= 1
        if indegree[nr, nc] == 0:
            queue.append((nr, nc))
    return accum


def _make_eastward_flow(n=5):
    """n x n grid where every cell flows east; col n-1 is the sink column."""
    fd = np.zeros((n, n), dtype=np.int64)
    for r in range(n):
        for c in range(n - 1):
            fd[r, c] = 1  # East
    return fd


def _simple_drainage_network():
    """5x5 Y-shaped network. 16 cells drain to sink at (0, 4)."""
    n = 5
    fd = np.zeros((n, n), dtype=np.int64)
    fd[0, 0] = 1; fd[0, 1] = 1; fd[0, 2] = 1; fd[0, 3] = 1
    fd[1, 4] = 7; fd[2, 4] = 7; fd[3, 4] = 7; fd[4, 4] = 7
    fd[4, 0] = 1; fd[4, 1] = 1; fd[4, 2] = 1; fd[4, 3] = 1
    fd[1, 0] = 3; fd[2, 0] = 3; fd[3, 0] = 3
    return fd, (0, 4), 16


def _branching_network():
    """7x7 branching tree to outlet (4, 3). 10 cells in catchment."""
    n = 7
    fd = np.zeros((n, n), dtype=np.int64)
    fd[0, 2] = 2
    fd[1, 1] = 3
    fd[1, 3] = 2
    fd[2, 0] = 2
    fd[2, 1] = 3
    fd[2, 4] = 3
    fd[3, 1] = 1
    fd[3, 2] = 2
    fd[3, 4] = 4
    return fd, (4, 3), 10


# -------------------------------------------------------------------------
# Tests: delineate_catchment
# -------------------------------------------------------------------------


class TestDelineateCatchment:

    def test_simple_eastward_flow(self):
        n = 5
        fd = _make_eastward_flow(n)
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((n, n), dtype=np.float64) * 100.0
        result = delineate_catchment(
            outlet_row=2, outlet_col=4,
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.catchment_cells == 5
        assert result.catchment_area_m2 == 500.0
        assert abs(result.catchment_area_ha - 0.05) < 1e-9
        assert result.diagnostics.outlet_in_catchment is True
        assert result.diagnostics.no_duplicate_cells is True
        assert result.diagnostics.traversal_terminated_safely is True

    def test_y_shaped_drainage(self):
        fd, outlet, expected = _simple_drainage_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.catchment_cells == expected
        assert result.diagnostics.outlet_in_catchment is True
        assert result.diagnostics.outlet_flow_accum_consistent is True

    def test_branching_network_correct_cells(self):
        fd, outlet, expected = _branching_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((7, 7), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.catchment_cells == expected
        expected_mask = np.zeros((7, 7), dtype=bool)
        for (r, c) in [(0, 2), (1, 1), (1, 3), (2, 0), (2, 1),
                         (2, 4), (3, 1), (3, 2), (3, 4), (4, 3)]:
            expected_mask[r, c] = True
        assert np.array_equal(result.catchment_mask, expected_mask)

    def test_cell_outside_network_excluded(self):
        fd, outlet, _ = _branching_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((7, 7), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.catchment_mask[3, 5] == False

    def test_invalid_outlet_negative_row(self):
        fd = _make_eastward_flow(5)
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        with pytest.raises(ValueError, match="outside grid bounds"):
            delineate_catchment(
                outlet_row=-1, outlet_col=2,
                flow_direction=fd, flow_accumulation=accum,
                dem=dem, cell_size_m=10.0,
            )

    def test_invalid_outlet_too_large(self):
        fd = _make_eastward_flow(5)
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        with pytest.raises(ValueError, match="outside grid bounds"):
            delineate_catchment(
                outlet_row=10, outlet_col=2,
                flow_direction=fd, flow_accumulation=accum,
                dem=dem, cell_size_m=10.0,
            )

    def test_outlet_in_own_catchment(self):
        fd, outlet, _ = _simple_drainage_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.catchment_mask[outlet[0], outlet[1]] == True
        assert result.diagnostics.outlet_in_catchment is True

    def test_no_duplicates_safe_termination(self):
        fd, outlet, _ = _simple_drainage_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.diagnostics.no_duplicate_cells is True
        assert result.diagnostics.cells_visited_count == result.catchment_cells
        assert result.diagnostics.traversal_terminated_safely is True

    def test_isolated_outlet_single_cell(self):
        n = 5
        fd = np.zeros((n, n), dtype=np.int64)
        accum = np.ones((n, n), dtype=np.int64)
        dem = np.ones((n, n), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=2, outlet_col=2,
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.catchment_cells == 1
        assert result.catchment_area_m2 == 100.0

    def test_full_grid_catchment(self):
        n = 4
        fd = np.zeros((n, n), dtype=np.int64)
        for r in range(n):
            for c in range(n - 1):
                fd[r, c] = 1
        for r in range(n - 1):
            fd[r, n - 1] = 3
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((n, n), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=n - 1, outlet_col=n - 1,
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.catchment_cells == n * n
        assert result.catchment_area_m2 == n * n * 100.0

    def test_area_within_grid(self):
        fd, outlet, _ = _simple_drainage_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.catchment_area_m2 <= result.grid_area_m2
        assert result.diagnostics.area_within_grid is True

    def test_flow_accum_consistent(self):
        fd, outlet, _ = _simple_drainage_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.diagnostics.outlet_flow_accum_consistent is True
        assert result.flow_accum_at_outlet == result.catchment_cells


# -------------------------------------------------------------------------
# Tests: summarise_catchment
# -------------------------------------------------------------------------


class TestSummariseCatchment:

    def test_summary_all_keys_present(self):
        fd, outlet, _ = _simple_drainage_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        s = summarise_catchment(result)
        for key in ("outlet", "catchment", "flow_accumulation",
                    "grid", "boundary", "diagnostics"):
            assert key in s, f"Missing key: {key}"
        assert "catchment_mask" not in s
        assert "area_m2" in s["catchment"]
        assert "area_ha" in s["catchment"]
        assert "area_km2" in s["catchment"]

    def test_boundary_type_and_bbox(self):
        fd, outlet, _ = _simple_drainage_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
        )
        assert result.boundary.boundary_type in (
            "convex_hull", "boundary_centroids", "empty"
        )
        assert result.boundary.num_boundary_cells >= 0
        assert "min_lat" in result.boundary.bounding_box

    def test_boundary_without_projection(self):
        fd, outlet, _ = _simple_drainage_network()
        accum = _compute_accum_from_flow(fd)
        dem = np.ones((5, 5), dtype=np.float64)
        result = delineate_catchment(
            outlet_row=outlet[0], outlet_col=outlet[1],
            flow_direction=fd, flow_accumulation=accum,
            dem=dem, cell_size_m=10.0,
            projection_info=None,
        )
        assert result.boundary is not None


# -------------------------------------------------------------------------
# Tests: end-to-end on sample KML
# -------------------------------------------------------------------------


class TestSampleKMLEndToEnd:

    @pytest.fixture
    def kml_path(self):
        p = BACKEND.parent / "sample_data" / "contours_1m.kml"
        if not p.exists():
            pytest.skip(f"Sample file not found: {p}")
        return p

    def test_integrated_analysis_top_ranked(self, kml_path):
        from services.contour_parser import parse_contour_file
        from services.terrain_model import build_terrain_model
        from services.hydrology import run_hydrology
        from services.pond_selection import (
            find_pond_candidates, PondSelectionConfig,
        )
        data = kml_path.read_bytes()
        contours = parse_contour_file(kml_path.name, data)
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        hydro = run_hydrology(
            model["grid"],
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            include_diagnostics=False,
        )
        pond = find_pond_candidates(
            dem=hydro.dem_original,
            flow_direction=hydro.flow_direction,
            flow_accumulation_cells=hydro.flow_accumulation_cells,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            config=PondSelectionConfig(top_k=5, nms_radius_cells=5),
        )
        assert len(pond.candidates) > 0
        catchment, integrated = run_integrated_analysis(
            pond_result=pond,
            hydro_result=hydro,
            model=model,
            rank=1,
            config=CatchmentConfig(),
        )
        assert catchment.diagnostics.outlet_flow_accum_consistent is True
        assert catchment.flow_accum_at_outlet == catchment.catchment_cells
        assert catchment.diagnostics.outlet_in_catchment is True
        assert catchment.diagnostics.no_duplicate_cells is True
        assert catchment.diagnostics.traversal_terminated_safely is True
        assert catchment.diagnostics.area_within_grid is True
        assert catchment.catchment_area_m2 > 0
        assert catchment.boundary.num_boundary_cells > 0
        assert "row" in integrated["selected_pond"]
        assert "col" in integrated["selected_pond"]

    def test_delineate_manual_outlet(self, kml_path):
        from services.contour_parser import parse_contour_file
        from services.terrain_model import build_terrain_model
        from services.hydrology import run_hydrology
        data = kml_path.read_bytes()
        contours = parse_contour_file(kml_path.name, data)
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        hydro = run_hydrology(
            model["grid"],
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            include_diagnostics=False,
        )
        h, w = hydro.dem_original.shape
        result = delineate_catchment(
            outlet_row=h // 2, outlet_col=w // 2,
            flow_direction=hydro.flow_direction,
            flow_accumulation=hydro.flow_accumulation_cells,
            dem=hydro.dem_original,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            config=CatchmentConfig(),
        )
        assert result.catchment_cells >= 1
        assert result.catchment_area_m2 <= result.grid_area_m2

    def test_invalid_outlet_rejected(self, kml_path):
        from services.contour_parser import parse_contour_file
        from services.terrain_model import build_terrain_model
        from services.hydrology import run_hydrology
        data = kml_path.read_bytes()
        contours = parse_contour_file(kml_path.name, data)
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        hydro = run_hydrology(
            model["grid"],
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            include_diagnostics=False,
        )
        with pytest.raises(ValueError, match="outside grid bounds"):
            delineate_catchment(
                outlet_row=99999, outlet_col=99999,
                flow_direction=hydro.flow_direction,
                flow_accumulation=hydro.flow_accumulation_cells,
                dem=hydro.dem_original,
                cell_size_m=model["grid_cell_size_m"],
                projection_info=model.get("projection_info"),
            )
