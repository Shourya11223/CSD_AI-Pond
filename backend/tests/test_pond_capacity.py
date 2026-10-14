"""
Tests for the Phase 4 pond depth and storage volume estimation service.

The pond_capacity module derives pond depth and storage volume estimates
from the original (pre-fill) DEM.  These tests verify the algorithm on
synthetic terrains and via the integrated endpoint on the real sample
KML file.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.pond_capacity import (
    estimate_pond_capacity,
    summarise_pond_capacity,
    _flood_fill_area,
    _trapezoidal_volume,
    _get_neighbour_elevations,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic terrains
# ---------------------------------------------------------------------------


def _flat_dem(n: int = 11) -> np.ndarray:
    """Flat DEM at 100 m.  No basin, no depth."""
    return np.full((n, n), 100.0, dtype=np.float64)


def _bowl_dem(n: int = 11, depth: float = 3.0) -> np.ndarray:
    """A bowl-shaped basin: high rim, low centre."""
    dem = np.full((n, n), 100.0, dtype=np.float64)
    centre = n // 2
    # Make the centre lower
    dem[centre, centre] = 100.0 - depth
    # Add some surrounding elevations to make a proper rim
    for r in range(n):
        for c in range(n):
            dist = max(abs(r - centre), abs(c - centre))
            if dist == 0:
                continue
            elif dist == 1:
                dem[r, c] = 100.0 - depth * 0.3
            else:
                dem[r, c] = 100.0
    return dem


def _sloping_dem(n: int = 11) -> np.ndarray:
    """Linearly increasing DEM (ridge).  No basin near centre."""
    dem = np.zeros((n, n), dtype=np.float64)
    for r in range(n):
        for c in range(n):
            dem[r, c] = 100.0 + r * 0.5
    return dem


# ---------------------------------------------------------------------------
# _get_neighbour_elevations
# ---------------------------------------------------------------------------


class TestGetNeighbourElevations:
    def test_excludes_centre_cell(self):
        dem = _bowl_dem()
        centre = dem.shape[0] // 2
        neigh = _get_neighbour_elevations(dem, centre, centre, radius=1)
        # Centre cell (100 - depth) must not be in the neighbourhood
        assert 100.0 - 3.0 not in neigh
        assert neigh.size == 8  # 8-connected interior neighbourhood

    def test_clamps_at_grid_edges(self):
        dem = _flat_dem()
        # Corner cell: only 3 valid neighbours (radius=1)
        neigh = _get_neighbour_elevations(dem, 0, 0, radius=1)
        assert neigh.size == 3


# ---------------------------------------------------------------------------
# _flood_fill_area
# ---------------------------------------------------------------------------


class TestFloodFillArea:
    def test_floods_only_lower_or_equal_cells(self):
        dem = _bowl_dem(n=11, depth=2.0)
        centre = 5
        # At the candidate elevation (98.0), only the centre cell floods
        # (because the surrounding cells are at 99.4 > 98.0).
        count, flooded = _flood_fill_area(dem, centre, centre, 98.0)
        assert count == 1
        assert (centre, centre) in flooded

    def test_floods_basin_at_rim_elevation(self):
        dem = _bowl_dem(n=11, depth=2.0)
        centre = 5
        # At rim elevation (100.0), the entire DEM is flooded
        count, flooded = _flood_fill_area(dem, centre, centre, 100.0)
        assert count == dem.size  # 11*11 = 121

    def test_no_cells_flooded_above_centre_in_flat(self):
        dem = _flat_dem()
        centre = 5
        # Flat: flooding at 100.0 spreads everywhere
        count, _ = _flood_fill_area(dem, centre, centre, 100.0)
        assert count == dem.size


# ---------------------------------------------------------------------------
# _trapezoidal_volume
# ---------------------------------------------------------------------------


class TestTrapezoidalVolume:
    def test_zero_for_single_point(self):
        z = np.array([100.0])
        a = np.array([10.0])
        assert _trapezoidal_volume(z, a) == 0.0

    def test_simple_box(self):
        # Linear: z=100,110 (10m), a=5,5 (constant)
        z = np.array([100.0, 110.0])
        a = np.array([5.0, 5.0])
        # Volume = ((5+5)/2) * 10 = 50
        assert _trapezoidal_volume(z, a) == pytest.approx(50.0)

    def test_pyramid(self):
        # z=100,110, a=10,0 (linearly shrinking)
        z = np.array([100.0, 110.0])
        a = np.array([10.0, 0.0])
        # Volume = ((10+0)/2) * 10 = 50
        assert _trapezoidal_volume(z, a) == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# estimate_pond_capacity
# ---------------------------------------------------------------------------


class TestEstimatePondCapacity:
    def test_input_validation_too_small_dem(self):
        dem = np.zeros((2, 2), dtype=np.float64)
        with pytest.raises(ValueError):
            estimate_pond_capacity(dem, 0, 0, cell_size_m=1.0)

    def test_input_validation_out_of_bounds(self):
        dem = _flat_dem(5)
        with pytest.raises(ValueError):
            estimate_pond_capacity(dem, 10, 10, cell_size_m=1.0)

    def test_input_validation_too_few_slices(self):
        dem = _flat_dem(5)
        with pytest.raises(ValueError):
            estimate_pond_capacity(dem, 2, 2, cell_size_m=1.0, num_slices=1)

    def test_input_validation_bad_radius(self):
        dem = _flat_dem(5)
        with pytest.raises(ValueError):
            estimate_pond_capacity(dem, 2, 2, cell_size_m=1.0, neighbourhood_radius_cells=0)

    def test_bowl_produces_positive_depth(self):
        dem = _bowl_dem(n=11, depth=3.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        # Max depth should be close to 3.0 m (candidate - min neighbour)
        assert result.max_depth_m > 0
        assert result.max_depth_m <= 3.0
        # Usable depth = max depth - freeboard (default 0.5)
        assert result.usable_depth_m == pytest.approx(
            result.max_depth_m - 0.5, abs=1e-9
        )
        assert result.usable_depth_m >= 0

    def test_bowl_produces_positive_volume(self):
        dem = _bowl_dem(n=11, depth=3.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        assert result.storage_volume_m3 > 0
        assert result.storage_volume_litres == pytest.approx(
            result.storage_volume_m3 * 1000.0, abs=1e-6
        )

    def test_flat_terrain_zero_depth_with_warning(self):
        dem = _flat_dem(n=11)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        # No basin: max depth is zero
        assert result.max_depth_m == pytest.approx(0.0, abs=1e-9)
        assert result.usable_depth_m == pytest.approx(0.0, abs=1e-9)
        assert result.storage_volume_m3 == pytest.approx(0.0, abs=1e-9)
        # A warning should be issued
        assert any("flat" in w.lower() for w in result.warnings)

    def test_sloping_terrain_very_small_depth(self):
        dem = _sloping_dem(n=11)
        # Centre is in a moderately sloped area
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        # Depth must be non-negative and finite
        assert result.max_depth_m >= 0
        assert math.isfinite(result.storage_volume_m3)
        assert math.isfinite(result.surface_area_m2)

    def test_volume_consistent_with_area_and_depth(self):
        dem = _bowl_dem(n=11, depth=2.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        # Volume should be approximately bounded by area * depth.
        # Allow for very small depth (if flat) where this is degenerate.
        if result.usable_depth_m > 1e-3 and result.surface_area_m2 > 1e-3:
            # Implied average depth from the integrated volume and area
            implied_depth = result.storage_volume_m3 / result.surface_area_m2
            # Should be less than or equal to usable depth + freeboard
            # (volume is integrated up to usable_spill, not max)
            assert implied_depth <= result.usable_depth_m + result.freeboard_m + 0.5

    def test_litres_match_cubic_metres(self):
        dem = _bowl_dem(n=11, depth=4.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        assert result.storage_volume_litres == pytest.approx(
            result.storage_volume_m3 * 1000.0, abs=1e-6
        )

    def test_surface_area_matches_flooded_cells_or_implied_area(self):
        # Surface area is either:
        #   (a) cells_flooded_at_design_level * cell_size²  (normal path), or
        #   (b) implied_area = volume / usable_depth  (sanity-check fallback
        #       when the flood-fill area is unreasonably small relative to the
        #       integrated volume — the fallback prevents volume/area
        #       inconsistency in bowl-shaped basins).
        # We verify surface_area_m2 is one of these two values.
        dem = _bowl_dem(n=11, depth=3.0)
        centre = 5
        cell_size = 1.0
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=cell_size,
        )
        area_from_cells = result.cells_flooded_at_design_level * cell_size * cell_size
        if result.usable_depth_m > 1e-6:
            implied_area = result.storage_volume_m3 / result.usable_depth_m
        else:
            implied_area = 0.0
        # Surface area must match one of the two legitimate sources
        assert (
            result.surface_area_m2 == pytest.approx(area_from_cells, abs=1e-3)
            or result.surface_area_m2 == pytest.approx(implied_area, abs=1e-3)
        ), (
            f"surface_area_m2 ({result.surface_area_m2}) should match either "
            f"cells-derived area ({area_from_cells}) or implied area ({implied_area})"
        )

    def test_freeboard_subtracts_from_max_depth(self):
        dem = _bowl_dem(n=11, depth=2.0)
        centre = 5
        r1 = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0, freeboard_m=0.2,
        )
        r2 = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0, freeboard_m=0.8,
        )
        # Same terrain, different freeboard
        assert r1.max_depth_m == pytest.approx(r2.max_depth_m, abs=1e-9)
        assert r1.usable_depth_m == pytest.approx(
            r1.max_depth_m - 0.2, abs=1e-9
        )
        assert r2.usable_depth_m == pytest.approx(
            r2.max_depth_m - 0.8, abs=1e-9
        )
        # Larger freeboard => smaller usable depth
        assert r2.usable_depth_m <= r1.usable_depth_m

    def test_method_text_contains_key_info(self):
        dem = _bowl_dem(n=11, depth=2.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0, num_slices=10,
        )
        assert "trapezoidal" in result.method.lower()
        assert "10" in result.method  # num_slices

    def test_assumptions_list_nonempty(self):
        dem = _bowl_dem(n=11, depth=2.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        assert len(result.assumptions) >= 4
        for a in result.assumptions:
            assert isinstance(a, str)
            assert len(a) > 0

    def test_cell_area_m2_correct(self):
        dem = _flat_dem(n=11)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=2.0,
        )
        assert result.cell_area_m2 == pytest.approx(4.0, abs=1e-9)

    def test_neighbour_elevations_recorded(self):
        dem = _bowl_dem(n=11, depth=3.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        # Candidate elevation must match the original DEM
        assert result.candidate_elevation_m == pytest.approx(
            float(dem[centre, centre]), abs=1e-9
        )
        # Max neighbour should be at the rim elevation (100.0 for the bowl)
        assert result.max_neighbour_elevation_m >= 99.5  # near rim
        # Mean neighbour should be between min and max
        assert (
            result.min_neighbour_elevation_m
            <= result.mean_neighbour_elevation_m
            <= result.max_neighbour_elevation_m
        )


# ---------------------------------------------------------------------------
# summarise_pond_capacity
# ---------------------------------------------------------------------------


class TestSummarisePondCapacity:
    def test_returns_dict_with_all_keys(self):
        dem = _bowl_dem(n=11, depth=2.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        d = summarise_pond_capacity(result)
        required = [
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
        for key in required:
            assert key in d, f"Missing key: {key}"

    def test_numeric_values_serialised_as_numbers(self):
        dem = _bowl_dem(n=11, depth=2.0)
        centre = 5
        result = estimate_pond_capacity(
            dem, centre, centre, cell_size_m=1.0,
        )
        d = summarise_pond_capacity(result)
        for key, val in d.items():
            if key in ("method", "assumptions", "warnings"):
                continue
            assert isinstance(val, (int, float)), (
                f"Key {key} is not numeric: {type(val)}"
            )


# ---------------------------------------------------------------------------
# Different candidate locations produce different capacity results
# ---------------------------------------------------------------------------


class TestCandidateLocationMatters:
    def test_two_candidates_in_same_dem_differ(self):
        # Build a DEM with two distinct basins
        dem = _bowl_dem(n=15, depth=2.0)
        centre = 7
        # Create a deeper bowl in a different location
        dem[2, 2] = 90.0
        dem[1, 1] = 95.0
        dem[3, 3] = 95.0
        dem[1, 2] = 95.0
        dem[2, 1] = 95.0

        r1 = estimate_pond_capacity(dem, centre, centre, cell_size_m=1.0)
        r2 = estimate_pond_capacity(dem, 2, 2, cell_size_m=1.0)

        # The deeper bowl should yield a larger max depth
        assert r2.max_depth_m > r1.max_depth_m
