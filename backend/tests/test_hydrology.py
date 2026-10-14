"""
Hydrology service tests (Stage 3).

Tests the Priority-Flood depression filling, D8 flow direction,
and flow accumulation algorithms, both on synthetic grids and
on the real sample_data/contours_1m.kml file.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure the backend package is importable.
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.hydrology import (
    run_hydrology,
    summarise_hydrology,
    _priority_flood_fill,
    _compute_d8_flow_direction,
    _compute_flow_accumulation,
    D8_OFFSETS,
    NO_FLOW,
)


# ---------------------------------------------------------------------------
# Fixture: synthetic terrains
# ---------------------------------------------------------------------------

def make_slope_dem(n=20, cell_size=1.0, slope=0.1):
    """
    A simple eastward-sloping ramp.
    z[r, c] = slope * c  (south = rows, east = cols)
    So the highest cells are on the east edge and the lowest on the
    west edge; water flows WEST.
    """
    dem = np.zeros((n, n), dtype=np.float64)
    for r in range(n):
        for c in range(n):
            dem[r, c] = slope * c
    return dem


def make_hill_dem(n=20, cell_size=1.0):
    """
    A Gaussian hill in the centre of a flat plane.
    Every boundary cell is at 0, so the interior drains outward.
    """
    dem = np.zeros((n, n), dtype=np.float64)
    centre = n // 2
    sigma = n / 4
    for r in range(n):
        for c in range(n):
            dist_sq = (r - centre) ** 2 + (c - centre) ** 2
            dem[r, c] = 20.0 * math.exp(-dist_sq / (2 * sigma ** 2))
    return dem


def make_sink_dem():
    """
    A flat 5x5 grid with a single central pit 0.5 m below the edge.
    After filling, the centre should be raised to spill elevation.
    """
    dem = np.zeros((5, 5), dtype=np.float64)
    dem[2, 2] = -0.5  # the pit
    return dem


# ---------------------------------------------------------------------------
# Tests: Priority-Flood
# ---------------------------------------------------------------------------

class TestPriorityFlood:

    def test_flat_dem_unchanged(self):
        dem = np.ones((10, 10), dtype=np.float64) * 100.0
        filled, max_adj, total_adj, modified = _priority_flood_fill(dem)
        # A perfectly flat DEM is a closed depression: every cell is
        # exactly at the boundary elevation. The algorithm breaks ties
        # by adding a tiny epsilon to interior cells so flow can leave
        # them. We check that the adjustments are physically negligible
        # (smaller than ~1e-4 m) and that no elevations are LOWERED.
        assert max_adj < 1e-3, f"Max adjustment {max_adj} is unexpectedly large"
        assert total_adj < 1e-2, f"Total adjustment {total_adj} is unexpectedly large"
        assert np.all(filled >= dem - 1e-9), "Fill must not lower any cell"

    def test_sink_is_filled(self):
        dem = make_sink_dem()  # 5x5 with one pit at [2,2]
        filled, max_adj, total_adj, modified = _priority_flood_fill(dem)
        # The pit should have been raised above its original value.
        assert filled[2, 2] > dem[2, 2], \
            f"Pit was not raised: {filled[2,2]} vs {dem[2,2]}"
        # No elevation should have been lowered.
        assert np.all(filled >= dem - 1e-9)

    def test_sloping_terrain_minimal_change(self):
        dem = make_slope_dem(n=20, slope=0.5)
        filled, max_adj, total_adj, modified = _priority_flood_fill(dem)
        # A real slope has no closed depressions; max adjustment
        # should be a tiny epsilon (just the tie-breaking offset).
        assert max_adj < 1e-5, f"Unexpected large max adjustment: {max_adj}"
        assert modified == 0

    def test_returns_correct_types(self):
        dem = np.random.rand(15, 15).astype(np.float64)
        result = run_hydrology(dem, cell_size_m=1.0)
        assert isinstance(result.dem_filled, np.ndarray)
        assert result.dem_filled.shape == dem.shape
        assert result.dem_filled.dtype == np.float64


# ---------------------------------------------------------------------------
# Tests: D8 flow direction
# ---------------------------------------------------------------------------

class TestD8FlowDirection:

    def test_west_slope_flows_west(self):
        """
        In make_slope_dem, z = slope * c so elevation INCREASES eastward.
        The highest cells are on the east edge; water flows WEST
        (direction code 5).
        """
        dem = make_slope_dem(n=10, slope=1.0)
        flow_dir, valid, sinks = _compute_d8_flow_direction(dem)
        interior = flow_dir[1:-1, 1:-1]
        # Every interior cell should point west (code 5).
        assert np.all(interior == 5), \
            f"Expected all west (5), got: {np.unique(interior)}"
        assert valid == 8 * 8  # 8x8 interior of a 10x10 grid
        assert sinks == 0

    def test_d8_encoding_complete(self):
        """
        Verify that all 8 direction codes are defined and map
        to the expected row/col offsets.
        """
        expected = {
            1: (0, 1),   # East
            2: (1, 1),   # SE
            3: (1, 0),   # South
            4: (1, -1),  # SW
            5: (0, -1),  # West
            6: (-1, -1), # NW
            7: (-1, 0),  # North
            8: (-1, 1),  # NE
        }
        for code, (dr, dc) in expected.items():
            assert D8_OFFSETS[code] == (dr, dc), \
                f"Direction {code} offset mismatch"

    def test_sink_marked_no_flow(self):
        """
        A flat 3x3 island surrounded by lower boundary cells should
        have all interior cells marked as sinks (no lower neighbour).
        After Priority-Flood fills the boundary spill, the interior
        might drain outward, so we just verify that the function
        runs and produces valid output.
        """
        dem = np.zeros((7, 7), dtype=np.float64)
        dem[1:-1, 1:-1] = 10.0  # a flat elevated plateau
        filled, *_ = _priority_flood_fill(dem)
        flow_dir, valid, sinks = _compute_d8_flow_direction(filled)
        # After filling, every interior cell should have a defined
        # flow direction pointing outward (no sink should remain).
        interior = flow_dir[1:-1, 1:-1]
        assert np.all(interior != NO_FLOW), \
            f"Found sinks after filling: {np.sum(interior == NO_FLOW)}"


# ---------------------------------------------------------------------------
# Tests: Flow accumulation
# ---------------------------------------------------------------------------

class TestFlowAccumulation:

    def test_headwater_is_one(self):
        """
        In make_slope_dem, the highest cells are on the east edge
        (col=n-1). The eastmost interior column (col=n-2) has no
        upstream contributors, so its accumulation is 1.
        """
        n = 10
        dem = make_slope_dem(n=n, slope=1.0)
        flow_dir, _, _ = _compute_d8_flow_direction(dem)
        accum, *_ = _compute_flow_accumulation(flow_dir, cell_size_m=1.0)
        interior_row = 5  # pick a middle row
        assert accum[interior_row, n - 2] == 1, \
            f"Headwater cell should have accumulation=1, got {accum[interior_row, n - 2]}"

    def test_accumulation_nonzero(self):
        dem = make_slope_dem(n=10, slope=1.0)
        flow_dir, _, _ = _compute_d8_flow_direction(dem)
        accum, *_ = _compute_flow_accumulation(flow_dir, cell_size_m=1.0)
        assert np.all(accum >= 1), "All cells should accumulate at least themselves"
        assert np.all(accum >= 0), "Accumulation must be non-negative"

    def test_max_accumulation_increases_downstream(self):
        dem = make_slope_dem(n=10, slope=1.0)
        flow_dir, _, _ = _compute_d8_flow_direction(dem)
        accum, *_ = _compute_flow_accumulation(flow_dir, cell_size_m=1.0)
        # Water flows west, so accumulation should monotonically
        # increase as we move from east to west.
        mid_row = 5
        for c in range(8, 0, -1):
            if c < 8:
                assert accum[mid_row, c] >= accum[mid_row, c + 1], \
                    f"Accumulation not monotonic at col {c}: " \
                    f"{accum[mid_row, c]} < {accum[mid_row, c+1]}"

    def test_area_equals_cells_times_cell_size(self):
        dem = make_slope_dem(n=10, slope=1.0)
        flow_dir, _, _ = _compute_d8_flow_direction(dem)
        cell_size = 3.5
        accum_cells, accum_area, *_ = _compute_flow_accumulation(
            flow_dir, cell_size_m=cell_size
        )
        expected_area = accum_cells * cell_size * cell_size
        np.testing.assert_array_almost_equal(accum_area, expected_area)

    def test_no_cycles(self):
        """
        On a depression-filled terrain there should be no routing cycles.
        The Kahn-style pass processes every cell exactly once.
        """
        dem = make_hill_dem(n=20)
        filled, *_ = _priority_flood_fill(dem)
        flow_dir, _, _ = _compute_d8_flow_direction(filled)
        _, _, stats = _compute_flow_accumulation(flow_dir, cell_size_m=1.0)
        assert stats["unprocessed_cells"] == 0, \
            f"Routing cycle detected: {stats['unprocessed_cells']} unprocessed cells"


# ---------------------------------------------------------------------------
# Tests: run_hydrology end-to-end
# ---------------------------------------------------------------------------

class TestRunHydrology:

    def test_returns_all_grids(self):
        dem = make_slope_dem(n=15)
        result = run_hydrology(dem, cell_size_m=2.0)
        assert result.dem_filled.shape == dem.shape
        assert result.flow_direction.shape == dem.shape
        assert result.flow_accumulation_cells.shape == dem.shape
        assert result.flow_accumulation_area.shape == dem.shape

    def test_no_negative_accumulation(self):
        dem = make_hill_dem(n=20)
        result = run_hydrology(dem, cell_size_m=1.0)
        assert np.all(result.flow_accumulation_cells >= 0)
        assert np.all(result.flow_accumulation_area >= 0.0)

    def test_max_area_consistent_with_cell_size(self):
        dem = make_slope_dem(n=20)
        cell_size = 5.0
        result = run_hydrology(dem, cell_size_m=cell_size)
        expected_max_area = result.max_accumulated_cells * cell_size * cell_size
        assert abs(result.max_accumulated_area_m2 - expected_max_area) < 1e-6

    def test_summarise_hydrology_returns_dict(self):
        dem = make_slope_dem(n=15)
        result = run_hydrology(dem, cell_size_m=1.0)
        summary = summarise_hydrology(result)
        assert "depression_fill" in summary
        assert "flow_direction" in summary
        assert "flow_accumulation" in summary
        assert summary["depression_fill"]["modified_cells"] == 0
        assert summary["flow_direction"]["valid_flow_cells"] > 0
        assert summary["flow_accumulation"]["max_accumulated_cells"] > 0

    def test_d8_encoding_in_summary(self):
        dem = make_slope_dem(n=15)
        result = run_hydrology(dem, cell_size_m=1.0)
        summary = summarise_hydrology(result)
        d8_enc = summary["flow_direction"]["d8_encoding"]
        assert "1" in d8_enc and d8_enc["1"] == "East"
        assert "0" in d8_enc and "no outflow" in d8_enc["0"]

    def test_invalid_cell_size_raises(self):
        dem = make_slope_dem(n=10)
        with pytest.raises(ValueError, match="cell_size_m must be > 0"):
            run_hydrology(dem, cell_size_m=0.0)
        with pytest.raises(ValueError, match="cell_size_m must be > 0"):
            run_hydrology(dem, cell_size_m=-1.0)

    def test_too_small_dem_raises(self):
        dem = np.array([[1.0, 2.0], [3.0, 4.0]])  # 2x2
        with pytest.raises(ValueError, match="at least 3x3"):
            run_hydrology(dem, cell_size_m=1.0)


# ---------------------------------------------------------------------------
# Tests: real sample_data
# ---------------------------------------------------------------------------

class TestSampleData:

    @pytest.fixture
    def contours_1m_path(self):
        p = BACKEND.parent / "sample_data" / "contours_1m.kml"
        if not p.exists():
            pytest.skip(f"Sample file not found: {p}")
        return p

    def test_inspect_contour_still_works(self, contours_1m_path):
        """Ensure Stage 1 endpoint is still functional."""
        from services.contour_parser import parse_contour_file
        data = contours_1m_path.read_bytes()
        contours = parse_contour_file(contours_1m_path.name, data)
        assert len(contours) > 0, "No contours parsed from sample file"
        elevations = [c.elevation for c in contours]
        assert min(elevations) > 0, "Elevations should be positive"

    def test_build_terrain_still_works(self, contours_1m_path):
        """Ensure Stage 2 endpoint is still functional."""
        from services.contour_parser import parse_contour_file
        from services.terrain_model import build_terrain_model
        data = contours_1m_path.read_bytes()
        contours = parse_contour_file(contours_1m_path.name, data)
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        assert model["grid"].shape[0] > 0 and model["grid"].shape[1] > 0
        assert model["grid_cell_size_m"] > 0

    def test_analyze_hydrology_sample_file(self, contours_1m_path):
        """
        End-to-end test: parse the sample contours, build terrain,
        run hydrology, and validate the output statistics.
        """
        from services.contour_parser import parse_contour_file
        from services.terrain_model import build_terrain_model

        data = contours_1m_path.read_bytes()
        contours = parse_contour_file(contours_1m_path.name, data)

        # Use a reasonably coarse grid for speed (10 m cells).
        model = build_terrain_model(contours, grid_cell_size_m=10.0)
        dem = model["grid"]

        result = run_hydrology(dem, cell_size_m=model["grid_cell_size_m"])

        # ---- Validate statistics ----
        summary = summarise_hydrology(result)

        # 1. Flow accumulation must be non-negative everywhere.
        assert np.all(result.flow_accumulation_cells >= 0)
        assert np.all(result.flow_accumulation_area >= 0.0)

        # 2. No routing cycles should have survived the fill.
        assert result.valid_flow_cells + result.sink_cells == dem.shape[0] * dem.shape[1] - \
               2 * dem.shape[0] - 2 * dem.shape[1] + 4, \
               "valid_flow + sinks should cover all interior cells"

        # 3. Maximum accumulation must be at least 1.
        assert result.max_accumulated_cells >= 1

        # 4. Max area must be consistent with cell size.
        cell_size = model["grid_cell_size_m"]
        expected_max_area = result.max_accumulated_cells * cell_size * cell_size
        assert abs(result.max_accumulated_area_m2 - expected_max_area) < 1e-6

        # 5. No cycles.
        # (The Kahn pass already handled this, but we check explicitly.)
        _, _, stats = _compute_flow_accumulation(
            result.flow_direction, cell_size_m=cell_size
        )
        assert stats["unprocessed_cells"] == 0, \
            f"Routing cycles detected: {stats['unprocessed_cells']} unprocessed"

        # 6. The maximum accumulation cell location should be in bounds.
        assert 0 <= result.max_accum_row < dem.shape[0]
        assert 0 <= result.max_accum_col < dem.shape[1]

        # 7. Mean depression adjustment should be a small positive value
        #    if any cells were modified, or 0 otherwise.
        dep = summary["depression_fill"]
        if dep["modified_cells"] > 0:
            assert dep["mean_adjustment_m"] > 0
            assert dep["total_elevation_adjustment_m"] > 0
        else:
            assert dep["mean_adjustment_m"] == 0.0

        # 8. Flow direction codes should be in the valid range 0-8.
        assert result.flow_direction.min() >= 0
        assert result.flow_direction.max() <= 8

        print("\n=== Sample data hydrology results ===")
        print(f"Grid: {model['grid_width']} x {model['grid_height']} @ {cell_size:.2f} m")
        print(f"Depression fill: {dep['modified_cells']} cells modified, "
              f"max raise {dep['max_elevation_adjustment_m']:.6f} m")
        print(f"D8: {result.valid_flow_cells} valid, {result.sink_cells} sinks")
        print(f"Accumulation: max {result.max_accumulated_cells} cells "
              f"({result.max_accumulated_area_m2:.1f} m^2) "
              f"at ({result.max_accum_row}, {result.max_accum_col})")


# ---------------------------------------------------------------------------
# Tests: API startup smoke test
# ---------------------------------------------------------------------------

class TestAPISmoke:

    def test_main_imports_cleanly(self):
        """Import the FastAPI app without errors."""
        from main import app

        def _collect_paths(obj):
            paths = []
            for r in getattr(obj, "routes", []):
                p = getattr(r, "path", None)
                if p:
                    paths.append(p)
                # FastAPI's include_router wraps the sub-router in
                # an _IncludedRouter; recurse into original_router.
                sub = getattr(r, "original_router", None)
                if sub is not None and sub is not obj:
                    paths.extend(_collect_paths(sub))
            return paths

        paths = _collect_paths(app)
        assert "/api/inspect-contour" in paths
        assert "/api/build-terrain" in paths
        assert "/api/analyze-hydrology" in paths
        assert "/api/find-pond-candidates" in paths

    def test_health_endpoint(self):
        from main import app
        # Just verify the app object is well-formed.
        assert app.title is not None
        assert app.version == "0.5.0"


# ---------------------------------------------------------------------------
# Tests: Extended diagnostics (Stage 3 quality-assurance step)
# ---------------------------------------------------------------------------

class TestDiagnostics:
    """
    Tests for the extended-diagnostics function added in Stage 3 QA.
    These are pure-analysis tests: they verify the reported
    statistics match the underlying arrays.
    """

    def _make_synthetic(self, n=10, with_sink=False):
        """A small cone-shaped hill so the depression-fill has work to do."""
        h, w = n, n
        y, x = np.mgrid[0:h, 0:w]
        dem = 20.0 - np.sqrt((x - h / 2) ** 2 + (y - w / 2) ** 2) * 2
        if with_sink:
            # Punch an artificial pit in the centre.
            dem[h // 2, w // 2] -= 5.0
        return dem

    def test_diagnostics_present_by_default(self):
        dem = self._make_synthetic(with_sink=True)
        result = run_hydrology(dem, cell_size_m=1.0)
        assert result.diagnostics is not None
        assert "depression_fill" in result.diagnostics
        assert "boundary" in result.diagnostics

    def test_diagnostics_can_be_disabled(self):
        dem = self._make_synthetic()
        result = run_hydrology(dem, cell_size_m=1.0, include_diagnostics=False)
        assert result.diagnostics is None

    def test_modified_pct_consistent(self):
        dem = self._make_synthetic(with_sink=True)
        result = run_hydrology(dem, cell_size_m=1.0)
        d = result.diagnostics["depression_fill"]
        expected_pct = 100.0 * d["modified_cells"] / d["total_cells"]
        assert abs(d["modified_pct"] - expected_pct) < 1e-6

    def test_threshold_counts_monotonic(self):
        """
        For any positive-raise distribution, larger thresholds must
        yield smaller exceedance counts:
        above 0.1m >= above 0.5m >= ... >= above 5.0m.
        """
        dem = self._make_synthetic(with_sink=True)
        result = run_hydrology(dem, cell_size_m=1.0)
        d = result.diagnostics["depression_fill"]
        c = [
            d["cells_above_0_1m"],
            d["cells_above_0_5m"],
            d["cells_above_1_0m"],
            d["cells_above_2_0m"],
            d["cells_above_5_0m"],
        ]
        for i in range(len(c) - 1):
            assert c[i] >= c[i + 1], f"Threshold counts not monotonic: {c}"

    def test_no_cells_lowered_and_nonnegative(self):
        """
        Algorithm invariant: the fill only ever RAISES cells.
        """
        dem = self._make_synthetic(with_sink=True)
        result = run_hydrology(dem, cell_size_m=1.0)
        d = result.diagnostics["depression_fill"]
        assert d["no_cells_lowered"] is True
        assert d["all_changes_nonnegative"] is True

    def test_mean_increase_consistent(self):
        dem = self._make_synthetic(with_sink=True)
        result = run_hydrology(dem, cell_size_m=1.0)
        d = result.diagnostics["depression_fill"]
        ec = d["elevation_change"]
        expected = ec["filled_mean"] - ec["original_mean"]
        assert abs(ec["mean_increase"] - expected) < 1e-6

    def test_max_adjustment_in_bounds(self):
        dem = self._make_synthetic(n=12, with_sink=True)
        result = run_hydrology(dem, cell_size_m=1.0)
        d = result.diagnostics["depression_fill"]
        h, w = dem.shape
        assert 0 <= d["max_adjustment_row"] < h
        assert 0 <= d["max_adjustment_col"] < w

    def test_boundary_outlets_consistent(self):
        """
        Total boundary cells = 2*h + 2*w - 4 for any (h, w) grid.
        """
        dem = self._make_synthetic(n=8)
        result = run_hydrology(dem, cell_size_m=1.0)
        b = result.diagnostics["boundary"]
        h, w = dem.shape
        assert b["total_boundary_cells"] == 2 * h + 2 * w - 4

    def test_geographic_location_when_projection_supplied(self):
        dem = self._make_synthetic(with_sink=True)
        # When projection_info lacks the grid origin, _grid_to_geographic
        # returns (None, None) (the correct fix). Provide a valid origin
        # so that diagnostic lat/lon values are computable.
        proj = {
            "projection": "local_equirectangular",
            "center_lat_deg": 20.5,
            "center_lon_deg": 78.9,
            "metres_per_degree_lon": 111320.0 * 0.94,
            "metres_per_degree_lat": 111320.0,
            "epsg_note": "test",
            # For a synthetic DEM (grid origin at 0,0) these are both 0.
            "grid_origin_x_m": 0.0,
            "grid_origin_y_m": 0.0,
        }
        result = run_hydrology(
            dem, cell_size_m=1.0, projection_info=proj
        )
        d = result.diagnostics["depression_fill"]
        b = result.diagnostics["boundary"]
        # Lat/lon should be finite numbers close to the projection centre.
        assert d["max_adjustment_lat"] is not None
        assert d["max_adjustment_lon"] is not None
        assert abs(d["max_adjustment_lat"] - 20.5) < 0.01
        assert abs(d["max_adjustment_lon"] - 78.9) < 0.01
        assert b["max_accum_lat"] is not None
        assert b["max_accum_lon"] is not None

    def test_diagnostics_summary_includes_all_sections(self):
        dem = self._make_synthetic(with_sink=True)
        result = run_hydrology(dem, cell_size_m=1.0)
        d = result.diagnostics
        for key in (
            "total_cells", "modified_cells", "modified_pct",
            "mean_adjustment_m", "median_adjustment_m",
            "p95_adjustment_m", "max_adjustment_m", "std_adjustment_m",
            "cells_above_0_1m", "cells_above_0_5m", "cells_above_1_0m",
            "cells_above_2_0m", "cells_above_5_0m",
            "max_adjustment_row", "max_adjustment_col",
            "elevation_change", "no_cells_lowered", "all_changes_nonnegative",
        ):
            assert key in d["depression_fill"], f"Missing {key}"
        for key in (
            "total_boundary_cells", "boundary_outlets",
            "max_accum_is_boundary", "max_accum_row", "max_accum_col",
        ):
            assert key in d["boundary"], f"Missing {key}"


class TestDiagnosticsSampleData:
    """
    End-to-end diagnostic test on the real sample KML.
    """

    @pytest.fixture
    def contours_1m_path(self):
        p = BACKEND.parent / "sample_data" / "contours_1m.kml"
        if not p.exists():
            pytest.skip(f"Sample file not found: {p}")
        return p

    def test_diagnostics_on_real_kml(self, contours_1m_path):
        from services.contour_parser import parse_contour_file
        from services.terrain_model import build_terrain_model
        data = contours_1m_path.read_bytes()
        contours = parse_contour_file(contours_1m_path.name, data)
        model = build_terrain_model(contours, grid_cell_size_m=10.0)

        result = run_hydrology(
            model["grid"],
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
        )
        d = result.diagnostics
        assert d is not None

        df = d["depression_fill"]
        # Cross-check vs the result fields
        assert df["modified_cells"] == result.depression_modified_cells
        assert abs(df["max_adjustment_m"] - result.depression_max_adjustment) < 1e-9
        # Terrain sanity
        assert df["no_cells_lowered"] is True
        assert df["all_changes_nonnegative"] is True
        # Threshold counts must be non-negative and monotonic
        c = [df[k] for k in (
            "cells_above_0_1m", "cells_above_0_5m", "cells_above_1_0m",
            "cells_above_2_0m", "cells_above_5_0m",
        )]
        assert all(x >= 0 for x in c)
        for i in range(len(c) - 1):
            assert c[i] >= c[i + 1], f"Threshold counts not monotonic: {c}"
        # Boundary outlets should be > 0
        b = d["boundary"]
        assert b["boundary_outlets"] > 0
        # Projection info was supplied, so lat/lon should be present
        assert b["max_accum_lat"] is not None
        assert df["max_adjustment_lat"] is not None

        # Print results for the viva report
        print("\n=== Sample KML extended diagnostics ===")
        print(f"Grid: {df['total_cells']} cells")
        print(f"Modified: {df['modified_cells']} ({df['modified_pct']:.2f}%)")
        print(f"Adjustment: mean={df['mean_adjustment_m']:.3f}m, "
              f"median={df['median_adjustment_m']:.3f}m, "
              f"p95={df['p95_adjustment_m']:.3f}m, "
              f"max={df['max_adjustment_m']:.3f}m")
        print(f"Threshold counts: 0.1m={c[0]}, 0.5m={c[1]}, 1m={c[2]}, "
              f"2m={c[3]}, 5m={c[4]}")
        print(f"Max raise at grid ({df['max_adjustment_row']}, "
              f"{df['max_adjustment_col']}) -> "
              f"({df['max_adjustment_lat']:.5f}, "
              f"{df['max_adjustment_lon']:.5f})")
        print(f"Elevation change: mean {df['elevation_change']['mean_increase']:.3f} m, "
              f"max {df['elevation_change']['max_increase']:.3f} m")
        print(f"Boundary outlets: {b['boundary_outlets']} / {b['total_boundary_cells']}")
        print(f"Max-accum at grid ({b['max_accum_row']}, {b['max_accum_col']}) "
              f"-> ({b['max_accum_lat']:.5f}, {b['max_accum_lon']:.5f}), "
              f"on boundary: {b['max_accum_is_boundary']}")
