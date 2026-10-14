"""
Catchment Terrain Diagnostics tests (Phase 11A).

Tests the slope, elevation, and longest D8 flow path computations
on synthetic grids.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure the backend package is importable.
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.catchment_diagnostics import (
    CatchmentTerrainDiagnosticsResult,
    compute_catchment_elevation_statistics,
    compute_catchment_slope_statistics,
    compute_catchment_terrain_diagnostics,
    compute_longest_d8_flow_path,
    summarise_terrain_diagnostics,
)
from services.hydrology import NO_FLOW


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ramp_dem(n=20, cell_size=1.0, slope=0.1):
    """
    Eastward-sloping ramp: z[r, c] = slope * c.
    Water flows WEST (col decreases) to the left edge.
    """
    dem = np.zeros((n, n), dtype=np.float64)
    for r in range(n):
        for c in range(n):
            dem[r, c] = slope * c
    return dem


def make_north_flowing_dem(n=10, cell_size=10.0, slope=1.0):
    """
    Northward-sloping ramp: z[r, c] = slope * (n - 1 - r).
    Lowest row is at the top (r=0) -> outlet there.
    """
    dem = np.zeros((n, n), dtype=np.float64)
    for r in range(n):
        for c in range(n):
            dem[r, c] = slope * (n - 1 - r)
    return dem


def make_d8_north(dem):
    """D8 grid where every cell points NORTH (direction 7).
    Outlet at row 0 also points north (off-grid), breaking the trace.
    """
    h, w = dem.shape
    fd = np.zeros((h, w), dtype=np.int32)
    for r in range(h):
        for c in range(w):
            fd[r, c] = 7  # every cell points north
    return fd


def make_d8_west(dem):
    """Build a D8 grid where every cell points WEST (direction 5)."""
    h, w = dem.shape
    fd = np.zeros((h, w), dtype=np.int32)
    for r in range(h):
        for c in range(1, w):
            fd[r, c] = 5
    return fd


# ---------------------------------------------------------------------------
# Tests: slope statistics
# ---------------------------------------------------------------------------


def test_slope_stats_eastward_ramp():
    """A constant eastward ramp gives uniform slope."""
    dem = make_ramp_dem(n=20, cell_size=1.0, slope=0.1)
    mask = np.ones_like(dem, dtype=bool)
    mean_d, mean_m, max_d, max_m, min_d, min_m = (
        compute_catchment_slope_statistics(dem, mask, cell_size_m=1.0)
    )
    assert mean_m == pytest.approx(0.1, rel=1e-3)
    assert max_m == pytest.approx(0.1, rel=1e-3)
    assert min_m == pytest.approx(0.1, rel=1e-3)
    expected_deg = math.degrees(math.atan(0.1))
    assert mean_d == pytest.approx(expected_deg, rel=1e-3)


def test_slope_stats_flat_terrain():
    """Flat DEM gives zero slope."""
    dem = np.full((10, 10), 100.0)
    mask = np.ones_like(dem, dtype=bool)
    mean_d, mean_m, max_d, max_m, min_d, min_m = (
        compute_catchment_slope_statistics(dem, mask, cell_size_m=10.0)
    )
    assert mean_m == 0.0
    assert max_m == 0.0
    assert min_m == 0.0
    assert mean_d == 0.0


def test_slope_stats_cell_size_scaling():
    """Doubling cell size halves gradient magnitude."""
    dem = make_ramp_dem(n=20, cell_size=1.0, slope=0.1)
    mask = np.ones_like(dem, dtype=bool)
    _, mean_m_1, _, _, _, _ = compute_catchment_slope_statistics(
        dem, mask, cell_size_m=1.0
    )
    _, mean_m_2, _, _, _, _ = compute_catchment_slope_statistics(
        dem, mask, cell_size_m=2.0
    )
    assert mean_m_2 == pytest.approx(mean_m_1 / 2.0, rel=1e-3)


def test_slope_stats_invalid_cell_size():
    """Non-positive cell size returns zeros."""
    dem = make_ramp_dem(n=10, cell_size=1.0, slope=0.1)
    mask = np.ones_like(dem, dtype=bool)
    result = compute_catchment_slope_statistics(dem, mask, cell_size_m=0.0)
    assert result == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def test_slope_stats_partial_mask():
    """Only masked cells contribute to statistics."""
    dem = make_ramp_dem(n=10, cell_size=1.0, slope=0.1)
    mask = np.zeros_like(dem, dtype=bool)
    mask[:, :5] = True
    _, mean_m, _, _, _, _ = compute_catchment_slope_statistics(
        dem, mask, cell_size_m=1.0
    )
    assert mean_m == pytest.approx(0.1, rel=1e-3)


# ---------------------------------------------------------------------------
# Tests: elevation statistics
# ---------------------------------------------------------------------------


def test_elevation_stats_ramp():
    """Ramp from 0 to 9: min=0, max=9, relief=9, mean=4.5."""
    dem = np.zeros((10, 10), dtype=np.float64)
    for r in range(10):
        dem[r, :] = float(r)
    mask = np.ones_like(dem, dtype=bool)
    min_e, max_e, relief, mean_e = compute_catchment_elevation_statistics(
        dem, mask
    )
    assert min_e == 0.0
    assert max_e == 9.0
    assert relief == 9.0
    assert mean_e == 4.5


def test_elevation_stats_partial_mask():
    """Partial mask restricts statistics correctly."""
    dem = np.zeros((10, 10), dtype=np.float64)
    for r in range(10):
        dem[r, :] = float(r)
    mask = np.zeros_like(dem, dtype=bool)
    mask[3:7, :] = True
    min_e, max_e, relief, mean_e = compute_catchment_elevation_statistics(
        dem, mask
    )
    assert min_e == 3.0
    assert max_e == 6.0
    assert relief == 3.0
    assert mean_e == 4.5


# ---------------------------------------------------------------------------
# Tests: master function and integration
# ---------------------------------------------------------------------------


def test_master_function_returns_dataclass():
    """Master function returns a CatchmentTerrainDiagnosticsResult."""
    n = 5
    dem = make_north_flowing_dem(n=n, cell_size=2.0, slope=0.5)
    mask = np.ones_like(dem, dtype=bool)
    fd = make_d8_north(dem)
    result = compute_catchment_terrain_diagnostics(
        dem=dem, flow_direction=fd, catchment_mask=mask,
        outlet_row=0, outlet_col=0, cell_size_m=2.0,
    )
    assert isinstance(result, CatchmentTerrainDiagnosticsResult)


def test_master_function_elevation_values():
    """Elevation values are correct for a known ramp."""
    n = 5
    dem = make_north_flowing_dem(n=n, cell_size=2.0, slope=0.5)
    mask = np.ones_like(dem, dtype=bool)
    fd = make_d8_north(dem)
    result = compute_catchment_terrain_diagnostics(
        dem=dem, flow_direction=fd, catchment_mask=mask,
        outlet_row=0, outlet_col=0, cell_size_m=2.0,
    )
    # dem[r, c] = 0.5*(5-1-r) -> rows: 2, 1.5, 1, 0.5, 0
    assert result.min_elevation_m == pytest.approx(0.0, abs=1e-4)
    assert result.max_elevation_m == pytest.approx(2.0, abs=1e-4)
    assert result.relief_m == pytest.approx(2.0, abs=1e-4)
    assert result.mean_elevation_m == pytest.approx(1.0, abs=1e-4)


def test_master_function_slope_values():
    """Slope values are correct for a known ramp."""
    n = 5
    dem = make_north_flowing_dem(n=n, cell_size=2.0, slope=0.5)
    mask = np.ones_like(dem, dtype=bool)
    fd = make_d8_north(dem)
    result = compute_catchment_terrain_diagnostics(
        dem=dem, flow_direction=fd, catchment_mask=mask,
        outlet_row=0, outlet_col=0, cell_size_m=2.0,
    )
    # dy = -slope/cell_size = -0.5/2 = -0.25
    # slope = sqrt(0.25^2 + 0^2) = 0.25
    assert result.mean_slope_m_per_m == pytest.approx(0.25, rel=1e-2)


def test_master_function_flow_path_values():
    """Longest flow path is correct for a linear chain."""
    n = 5
    cell_size = 2.0
    dem = make_north_flowing_dem(n=n, cell_size=cell_size, slope=1.0)
    mask = np.ones_like(dem, dtype=bool)
    fd = make_d8_north(dem)
    result = compute_catchment_terrain_diagnostics(
        dem=dem, flow_direction=fd, catchment_mask=mask,
        outlet_row=0, outlet_col=0, cell_size_m=cell_size,
    )
    assert result.longest_flow_path_cells == n
    assert result.longest_flow_path_m == pytest.approx(
        (n - 1) * cell_size, rel=1e-4
    )
    assert result.number_of_headwater_cells == n


def test_master_function_warnings_on_degenerate():
    """A 1x1 catchment produces a warning about zero path."""
    dem = np.array([[100.0]])
    mask = np.array([[True]])
    fd = np.array([[0]], dtype=np.int32)
    result = compute_catchment_terrain_diagnostics(
        dem=dem, flow_direction=fd, catchment_mask=mask,
        outlet_row=0, outlet_col=0, cell_size_m=1.0,
    )
    assert result.min_elevation_m == 100.0
    assert result.max_elevation_m == 100.0
    assert result.relief_m == 0.0
    assert any(
        "degenerate" in w.lower() or "zero" in w.lower()
        for w in result.warnings
    )


def test_summarise_returns_all_keys():
    """summarise_terrain_diagnostics produces all expected keys."""
    n = 4
    dem = make_north_flowing_dem(n=n, cell_size=1.0, slope=1.0)
    mask = np.ones_like(dem, dtype=bool)
    fd = make_d8_north(dem)
    result = compute_catchment_terrain_diagnostics(
        dem=dem, flow_direction=fd, catchment_mask=mask,
        outlet_row=0, outlet_col=0, cell_size_m=1.0,
    )
    summary = summarise_terrain_diagnostics(result)
    expected_keys = {
        "mean_slope_deg", "mean_slope_m_per_m",
        "max_slope_deg", "max_slope_m_per_m",
        "min_slope_deg", "min_slope_m_per_m",
        "min_elevation_m", "max_elevation_m", "relief_m", "mean_elevation_m",
        "longest_flow_path_m", "longest_flow_path_cells",
        "longest_flow_path_outlet_row", "longest_flow_path_outlet_col",
        "number_of_headwater_cells",
        "method", "warnings",
    }
    assert expected_keys.issubset(set(summary.keys()))
    assert isinstance(summary["warnings"], list)
    assert isinstance(summary["method"], str)


def test_pydantic_model_instantiation():
    """The Pydantic model accepts the summary dict without errors."""
    n = 4
    dem = make_north_flowing_dem(n=n, cell_size=1.0, slope=1.0)
    mask = np.ones_like(dem, dtype=bool)
    fd = make_d8_north(dem)
    result = compute_catchment_terrain_diagnostics(
        dem=dem, flow_direction=fd, catchment_mask=mask,
        outlet_row=0, outlet_col=0, cell_size_m=1.0,
    )
    summary = summarise_terrain_diagnostics(result)
    from models import CatchmentTerrainDiagnostics
    model = CatchmentTerrainDiagnostics(**summary)
    assert model.method == summary["method"]
    assert model.longest_flow_path_m == summary["longest_flow_path_m"]
    assert model.number_of_headwater_cells == summary["number_of_headwater_cells"]


def test_elevation_stats_empty_mask_raises():
    """Empty mask raises ValueError."""
    dem = np.zeros((10, 10), dtype=np.float64)
    mask = np.zeros_like(dem, dtype=bool)
    with pytest.raises(ValueError, match="empty"):
        compute_catchment_elevation_statistics(dem, mask)


# ---------------------------------------------------------------------------
# Tests: longest D8 flow path
# ---------------------------------------------------------------------------


def test_longest_path_linear_chain():
    """Linear chain flowing north: n cells, n-1 steps * cell_size.
    Path includes both headwater (start) and outlet (end)."""
    n = 10
    cell_size = 10.0
    dem = make_north_flowing_dem(n=n, cell_size=cell_size, slope=1.0)
    mask = np.ones_like(dem, dtype=bool)
    fd = make_d8_north(dem)
    path_m, path_cells, num_hw, _, _ = compute_longest_d8_flow_path(
        fd, mask, outlet_row=0, outlet_col=0, cell_size_m=cell_size
    )
    # n cells from row n-1 to row 0 inclusive
    assert path_cells == n
    # n-1 cardinal north steps
    assert path_m == pytest.approx((n - 1) * cell_size, rel=1e-6)
    # All cells in column 0 are headwaters (each flows into the cell above)
    assert num_hw == n


def test_longest_path_outside_catchment_raises():
    """Outlet outside mask raises ValueError."""
    n = 5
    # Mask only the left half
    mask = np.zeros((n, n), dtype=bool)
    mask[:, : n // 2] = True
    fd = np.zeros((n, n), dtype=np.int32)
    # Outlet at (0, 4) is outside the mask
    with pytest.raises(ValueError, match="not in catchment"):
        compute_longest_d8_flow_path(
            fd, mask, outlet_row=0, outlet_col=4, cell_size_m=1.0
        )
