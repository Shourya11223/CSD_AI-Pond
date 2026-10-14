"""
Pond capacity estimation: depth and storage volume for a selected pond candidate.

Phase 4 extends the AI Pond Catchment Analyzer with terrain-based pond depth
and water storage volume estimates for the selected pond candidate.

Methodology
-----------
1. Spill (rim) elevation: a configurable percentile (default 25th) of the
   neighbour cells within ``neighbourhood_radius_cells`` that are higher
   than the candidate.  This approximates the natural basin rim.
2. Max depth: spill_elevation − candidate_elevation (terrain-derived
   containment depth of the natural basin, before any freeboard is applied).
3. Usable depth: max_depth − freeboard safety margin (default 0.5 m).
4. Volume: trapezoidal elevation-slice integration.  Each slice flood-fills
   the original DEM from the candidate at a given elevation to determine
   the inundated area, then volume is integrated between slice pairs.
5. Only the selected candidate is analysed (pond_rank selects which one).

References
----------
- Trapezoidal rule: standard hydrological basin-modelling approach.
- Freeboard: standard engineering practice (e.g. USDA NRCS gives 0.3-0.6 m
  freeboard for small earthen ponds).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_NEIGHBOURHOOD_RADIUS_CELLS = 3
"""Default radius (cells) for the local elevation neighbourhood."""

DEFAULT_FREEBBOARD_M = 0.5
"""Default freeboard safety margin in metres."""

DEFAULT_NUM_SLICES = 20
"""Default number of elevation slices for trapezoidal volume integration."""

DEFAULT_SPILL_PERCENTILE = 25.0
"""Percentile of higher-neighbour elevations used to estimate spill elevation."""


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class PondCapacityResult:
    """
    Result of pond depth and storage-volume estimation.

    Attributes
    ----------
    usable_depth_m : float
        Estimated usable water depth in metres (max_depth_m minus freeboard).
    max_depth_m : float
        Maximum terrain-based depth in metres.  Equal to the estimated
        natural basin rim (spill_elevation_m) minus the candidate elevation.
    usable_spill_elevation_m : float
        Candidate elevation + usable depth (water surface at design level).
    spill_elevation_m : float
        Estimated natural basin rim elevation.
    cell_area_m2 : float
        Area of a single DEM grid cell in m^2.
    surface_area_m2 : float
        Estimated pond water-surface area at usable depth in m^2.
    storage_volume_m3 : float
        Estimated storage volume in cubic metres.
    storage_volume_litres : float
        Volume in litres (storage_volume_m3 * 1000).
    method : str
        Human-readable description of the estimation methodology.
    assumptions : List[str]
        List of assumptions made by the algorithm.
    warnings : List[str]
        Any conditions that may reduce estimate reliability.
    num_slices : int
        Number of elevation slices used in trapezoidal integration.
    neighbourhood_radius_cells : int
        Cells used to search for the basin rim.
    freeboard_m : float
        Freeboard safety margin applied (metres).
    candidate_elevation_m : float
        Elevation of the selected pond candidate (original DEM).
    min_neighbour_elevation_m : float
        Minimum elevation in the neighbourhood radius.
    max_neighbour_elevation_m : float
        Maximum elevation in the neighbourhood radius.
    mean_neighbour_elevation_m : float
        Mean elevation of neighbour cells.
    cells_flooded_at_design_level : int
        Number of DEM cells inundated at the design water surface.
    """

    usable_depth_m: float
    max_depth_m: float
    usable_spill_elevation_m: float
    spill_elevation_m: float
    cell_area_m2: float
    surface_area_m2: float
    storage_volume_m3: float
    storage_volume_litres: float
    method: str
    assumptions: List[str]
    warnings: List[str]
    num_slices: int
    neighbourhood_radius_cells: int
    freeboard_m: float
    candidate_elevation_m: float
    min_neighbour_elevation_m: float
    max_neighbour_elevation_m: float
    mean_neighbour_elevation_m: float
    cells_flooded_at_design_level: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_neighbour_elevations(
    dem: np.ndarray, row: int, col: int, radius: int
) -> np.ndarray:
    """
    Return the elevations of all cells within ``radius`` cells of (row, col),
    excluding the centre cell itself.  Boundary cells outside the grid are
    ignored.

    Parameters
    ----------
    dem : (H, W) ndarray
        Elevation grid (metres).
    row, col : int
        Centre cell coordinates.
    radius : int
        Chebyshev (square) neighbourhood radius in cells.

    Returns
    -------
    ndarray
        1-D array of neighbour elevations.
    """
    h, w = dem.shape
    r_min = max(0, row - radius)
    r_max = min(h, row + radius + 1)
    c_min = max(0, col - radius)
    c_max = min(w, col + radius + 1)

    neigh = dem[r_min:r_max, c_min:c_max].copy()
    dr = row - r_min
    dc = col - c_min
    neigh[dr, dc] = np.nan

    return neigh[~np.isnan(neigh)]


def _flood_fill_area(
    dem: np.ndarray, row: int, col: int, max_elevation: float
) -> Tuple[int, set]:
    """
    Count all DEM cells reachable from (row, col) whose elevation is
    strictly less than or equal to ``max_elevation``.

    Uses an iterative BFS stack to avoid Python recursion limits on
    large grids.  8-connected.

    Parameters
    ----------
    dem : (H, W) ndarray
        Elevation grid.
    row, col : int
        Starting cell.
    max_elevation : float
        Maximum elevation to flood (inclusive).

    Returns
    -------
    Tuple[int, set]
        (cell_count, set_of_flooded_cell_index_pairs)
    """
    h, w = dem.shape

    visited = np.zeros((h, w), dtype=np.float64)
    visited[row, col] = 1.0

    stack: List[Tuple[int, int]] = [(row, col)]
    flooded: set = {(row, col)}

    D8_ROWS = (-1, -1, -1, 0, 0, 1, 1, 1)
    D8_COLS = (-1, 0, 1, -1, 1, -1, 0, 1)

    while stack:
        r, c = stack.pop()
        for dr, dc in zip(D8_ROWS, D8_COLS):
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and visited[nr, nc] == 0:
                if dem[nr, nc] <= max_elevation:
                    visited[nr, nc] = 1.0
                    stack.append((nr, nc))
                    flooded.add((nr, nc))

    return len(flooded), flooded


def _trapezoidal_volume(
    elevations_m: np.ndarray, areas_m2: np.ndarray
) -> float:
    """
    Integrate area-over-elevation to obtain volume using the trapezoidal rule.

    Parameters
    ----------
    elevations_m : ndarray
        Monotonically increasing elevation values (z-axis).
    areas_m2 : ndarray
        Inundated area (m^2) at each corresponding elevation.

    Returns
    -------
    float
        Volume in cubic metres.
    """
    if len(elevations_m) < 2:
        return 0.0

    z = np.asarray(elevations_m, dtype=np.float64)
    a = np.asarray(areas_m2, dtype=np.float64)

    dz = np.diff(z)
    avg_area = (a[:-1] + a[1:]) / 2.0

    return float(np.sum(avg_area * dz))




def estimate_pond_capacity(
    dem: np.ndarray,
    row: int,
    col: int,
    cell_size_m: float,
    neighbourhood_radius_cells: int = DEFAULT_NEIGHBOURHOOD_RADIUS_CELLS,
    freeboard_m: float = DEFAULT_FREEBBOARD_M,
    num_slices: int = DEFAULT_NUM_SLICES,
    spill_percentile: float = DEFAULT_SPILL_PERCENTILE,
) -> PondCapacityResult:
    """
    Estimate pond depth and storage volume for a selected pond candidate.

    Uses trapezoidal elevation-slice integration with 8-connected flood-filling
    on the original (pre-fill) DEM to determine inundated area at each level.

    Parameters
    ----------
    dem : (H, W) float64 ndarray
        The original (pre-fill) DEM elevation grid, in metres.
    row, col : int
        Grid coordinates of the selected pond candidate.
    cell_size_m : float
        Grid cell size in metres.
    neighbourhood_radius_cells : int, optional
        Chebyshev radius for the basin neighbourhood. Default 3.
    freeboard_m : float, optional
        Safety freeboard subtracted from max depth. Default 0.5 m.
    num_slices : int, optional
        Number of elevation slices. Default 20.
    spill_percentile : float, optional
        Percentile of higher neighbours used for spill elevation. Default 25.

    Returns
    -------
    PondCapacityResult

    Raises
    ------
    ValueError
        If the DEM is too small, coordinates are out of bounds,
        or invalid numeric parameters are supplied.
    """
    # --- Validate inputs ---
    h, w = dem.shape
    if h < 3 or w < 3:
        raise ValueError(
            f"DEM must have at least 3 rows and 3 columns (got {h}x{w})"
        )
    if not (0 <= row < h and 0 <= col < w):
        raise ValueError(
            f"Candidate ({row}, {col}) is outside DEM bounds ({h}, {w})"
        )
    if num_slices < 2:
        raise ValueError(f"num_slices must be >= 2 (got {num_slices})")
    if neighbourhood_radius_cells < 1:
        raise ValueError(
            f"neighbourhood_radius_cells must be >= 1 "
            f"(got {neighbourhood_radius_cells})"
        )

    # --- Candidate elevation and cell area ---
    candidate_elev = float(dem[row, col])
    cell_area_m2 = float(cell_size_m) ** 2

    # --- Neighbourhood statistics ---
    neighbour_elevs = _get_neighbour_elevations(
        dem, row, col, neighbourhood_radius_cells
    )

    if neighbour_elevs.size == 0:
        min_neigh_elev = candidate_elev
        max_neigh_elev = candidate_elev
        mean_neigh_elev = candidate_elev
        higher_neigh_elevs: np.ndarray = np.array([], dtype=np.float64)
    else:
        min_neigh_elev = float(np.nanmin(neighbour_elevs))
        max_neigh_elev = float(np.nanmax(neighbour_elevs))
        mean_neigh_elev = float(np.nanmean(neighbour_elevs))
        higher_neigh_elevs = neighbour_elevs[neighbour_elevs > candidate_elev]

    # --- Spill elevation (natural basin rim) ---
    # The spill/rim elevation is the level at which water would overflow
    # the natural basin.  We approximate it as the spill_percentile of
    # neighbour cells that are higher than the candidate.  This is a
    # terrain-derived estimate of the containment elevation.
    # NOTE: this must be computed BEFORE max_depth so the early-return
    # check uses the correct containment depth.
    if higher_neigh_elevs.size > 0:
        spill_elev = float(np.percentile(higher_neigh_elevs, spill_percentile))
    else:
        # No neighbours higher than the candidate: water cannot be
        # contained.  Use the mean neighbour elevation as a fallback.
        spill_elev = mean_neigh_elev

    # --- Max depth (terrain-based containment) ---
    # Depth = rim - bottom.  The candidate is the pond bottom; the spill
    # elevation is the natural containment rim.  This is the terrain-derived
    # maximum depth of the natural basin, before any freeboard is applied.
    max_depth = spill_elev - candidate_elev
    if max_depth < 0:
        max_depth = 0.0
        spill_elev = candidate_elev

    # --- Warnings ---
    warnings: List[str] = []
    if max_depth < 0.1:
        warnings.append(
            "Terrain is essentially flat near the selected location "
            "(max depth < 0.1 m). Volume and depth estimates are unreliable."
        )

    # --- Usable depth (max depth minus freeboard) ---
    usable_depth = max(0.0, max_depth - float(freeboard_m))

        # If no usable depth (flat terrain), volume and surface area are zero.
    if usable_depth < 1e-6:
        return PondCapacityResult(
            usable_depth_m=0.0,
            max_depth_m=max_depth,
            usable_spill_elevation_m=candidate_elev,
            spill_elevation_m=spill_elev,
            cell_area_m2=cell_area_m2,
            surface_area_m2=0.0,
            storage_volume_m3=0.0,
            storage_volume_litres=0.0,
            method=(
                f"No usable depth: max terrain depth {max_depth:.4f} m "
                f"is <= freeboard {freeboard_m:.2f} m. "
                f"Volume and surface area set to 0.0."
            ),
            assumptions=[],
            warnings=[
                "Terrain is essentially flat near the selected location "
                "(max depth < freeboard). Volume and depth estimates are unreliable.",
            ],
            num_slices=num_slices,
            neighbourhood_radius_cells=neighbourhood_radius_cells,
            freeboard_m=freeboard_m,
            candidate_elevation_m=candidate_elev,
            min_neighbour_elevation_m=min_neigh_elev,
            max_neighbour_elevation_m=max_neigh_elev,
            mean_neighbour_elevation_m=mean_neigh_elev,
            cells_flooded_at_design_level=0,
        )

    usable_spill_elev = candidate_elev + usable_depth

    # --- Volume via trapezoidal elevation slices ---
    lower_bound = float(candidate_elev)
    upper_bound = max(usable_spill_elev, spill_elev)
    if upper_bound <= lower_bound + 1e-6:
        upper_bound = lower_bound + 1.0

    slice_elevations = np.linspace(lower_bound, upper_bound, num=num_slices)
    slice_areas_m2: List[float] = []

    for lvl in slice_elevations:
        count, _ = _flood_fill_area(dem, row, col, float(lvl))
        slice_areas_m2.append(count * cell_area_m2)

    storage_volume_m3 = _trapezoidal_volume(
        slice_elevations, np.array(slice_areas_m2)
    )
    storage_volume_l = storage_volume_m3 * 1000.0

    # --- Surface area at design water level ---
    design_level = float(usable_spill_elev)
    cells_at_design, _ = _flood_fill_area(dem, row, col, design_level)
    surface_area_m2 = cells_at_design * cell_area_m2

    # Sanity check: fallback if trapezoidal gives unreasonable area
    if usable_depth > 1e-6:
        implied_area = storage_volume_m3 / usable_depth
        if surface_area_m2 < implied_area * 0.1:
            surface_area_m2 = implied_area
    else:
        surface_area_m2 = cells_at_design * cell_area_m2

    # --- Assumptions list ---
    assumptions = [
        (
            f"Max depth = estimated spill/rim elevation ({spill_elev:.2f} m) minus "
            f"candidate elevation ({candidate_elev:.2f} m).  Spill elevation is the "
            f"{spill_percentile:.0f}th percentile of neighbour cells higher than the "
            f"candidate within a {neighbourhood_radius_cells}-cell neighbourhood, "
            f"approximating the natural basin rim."
        ),
        (
            f"Freeboard of {freeboard_m:.2f} m is subtracted from max depth to obtain "
            f"the usable design depth (standard practice for small earthen ponds)."
        ),
        (
            f"Storage volume via trapezoidal integration of {num_slices} "
            f"elevation slices, each 8-connected flood-filling the original DEM."
        ),
        (
            "The original (pre-fill) DEM is used so estimates reflect natural "
            "terrain rather than the depression-filled surface."
        ),
        (
            "Volume estimates assume no engineered embankment; the pond is "
            "formed entirely by the natural basin."
        ),
    ]

    # --- Method text ---
    method = (
        f"Trapezoidal elevation-slice integration using {num_slices} slices "
        f"from {lower_bound:.2f} m to {upper_bound:.2f} m.  "
        f"Each slice 8-connected flood-fills the original DEM from the pond "
        f"candidate at the given elevation level to determine inundated area.  "
        f"Volume = sum over adjacent slice pairs of "
        f"((A[i] + A[i+1]) / 2) * (z[i+1] - z[i]).  "
        f"Usable depth = max_depth ({max_depth:.2f} m) - freeboard "
        f"({freeboard_m:.2f} m) = {usable_depth:.2f} m.  "
        f"Spill elevation = {spill_elev:.2f} m."
    )

    return PondCapacityResult(
        usable_depth_m=usable_depth,
        max_depth_m=max_depth,
        usable_spill_elevation_m=usable_spill_elev,
        spill_elevation_m=spill_elev,
        cell_area_m2=cell_area_m2,
        surface_area_m2=surface_area_m2,
        storage_volume_m3=storage_volume_m3,
        storage_volume_litres=storage_volume_l,
        method=method,
        assumptions=assumptions,
        warnings=warnings,
        num_slices=num_slices,
        neighbourhood_radius_cells=neighbourhood_radius_cells,
        freeboard_m=freeboard_m,
        candidate_elevation_m=candidate_elev,
        min_neighbour_elevation_m=min_neigh_elev,
        max_neighbour_elevation_m=max_neigh_elev,
        mean_neighbour_elevation_m=mean_neigh_elev,
        cells_flooded_at_design_level=cells_at_design,
    )


def summarise_pond_capacity(result: PondCapacityResult) -> dict:
    """Return a JSON-friendly dict representation of a PondCapacityResult."""
    return {
        "usable_depth_m": round(result.usable_depth_m, 4),
        "max_depth_m": round(result.max_depth_m, 4),
        "usable_spill_elevation_m": round(result.usable_spill_elevation_m, 4),
        "spill_elevation_m": round(result.spill_elevation_m, 4),
        "cell_area_m2": round(result.cell_area_m2, 6),
        "surface_area_m2": round(result.surface_area_m2, 4),
        "storage_volume_m3": round(result.storage_volume_m3, 4),
        "storage_volume_litres": round(result.storage_volume_litres, 2),
        "method": result.method,
        "assumptions": result.assumptions,
        "warnings": result.warnings,
        "num_slices": result.num_slices,
        "neighbourhood_radius_cells": result.neighbourhood_radius_cells,
        "freeboard_m": result.freeboard_m,
        "candidate_elevation_m": round(result.candidate_elevation_m, 4),
        "min_neighbour_elevation_m": round(result.min_neighbour_elevation_m, 4),
        "max_neighbour_elevation_m": round(result.max_neighbour_elevation_m, 4),
        "mean_neighbour_elevation_m": round(result.mean_neighbour_elevation_m, 4),
        "cells_flooded_at_design_level": result.cells_flooded_at_design_level,
    }
