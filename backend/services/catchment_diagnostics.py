
"""
Catchment Terrain Diagnostics Service (Phase 11A).

Computes additional terrain statistics for a delineated catchment that are
derived entirely from the existing DEM, D8 flow-direction grid,
catchment mask, and grid metadata. No external data sources, no
roughness assumptions, no soil or land-cover data.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np

from services.hydrology import D8_OFFSETS, NO_FLOW

logger = logging.getLogger(__name__)

# Cardinal directions: 1=E, 3=S, 5=W, 7=N
# Diagonal directions: 2=SE, 4=SW, 6=NW, 8=NE
_CARDINAL_DIRS = {1, 3, 5, 7}
_DIAGONAL_DIRS = {2, 4, 6, 8}


def _d8_step_distance(direction: int, cell_size_m: float) -> float:
    """Geometric distance of one D8 step in metres."""
    if direction in _CARDINAL_DIRS:
        return float(cell_size_m)
    if direction in _DIAGONAL_DIRS:
        return float(cell_size_m) * math.sqrt(2.0)
    return 0.0


@dataclass
class CatchmentTerrainDiagnosticsResult:
    """
    Terrain statistics scoped to the catchment mask.

    Attributes
    ----------
    mean_slope_deg, mean_slope_m_per_m : float
        Mean slope of catchment cells in degrees and m/m.
    max_slope_deg, max_slope_m_per_m : float
        Maximum slope among catchment cells in degrees and m/m.
    min_slope_deg, min_slope_m_per_m : float
        Minimum slope among catchment cells in degrees and m/m.
    min_elevation_m, max_elevation_m : float
        Min and max DEM elevation within the catchment (metres).
    relief_m : float
        Elevation range: max_elevation_m - min_elevation_m.
    mean_elevation_m : float
        Mean DEM elevation within the catchment.
    longest_flow_path_m : float
        Length of the longest D8 flow path (headwater to outlet) in metres.
    longest_flow_path_cells : int
        Number of cells in the longest path.
    longest_flow_path_outlet_row, longest_flow_path_outlet_col : int
        Outlet cell coordinates used for the trace.
    number_of_headwater_cells : int
        Number of headwater (source) cells in the catchment.
    method : str
        Human-readable methodology description.
    warnings : List[str]
        Conditions affecting reliability.
    """

    mean_slope_deg: float = 0.0
    mean_slope_m_per_m: float = 0.0
    max_slope_deg: float = 0.0
    max_slope_m_per_m: float = 0.0
    min_slope_deg: float = 0.0
    min_slope_m_per_m: float = 0.0
    min_elevation_m: float = 0.0
    max_elevation_m: float = 0.0
    relief_m: float = 0.0
    mean_elevation_m: float = 0.0
    longest_flow_path_m: float = 0.0
    longest_flow_path_cells: int = 0
    longest_flow_path_outlet_row: int = 0
    longest_flow_path_outlet_col: int = 0
    number_of_headwater_cells: int = 0
    method: str = ""
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def compute_catchment_slope_statistics(
    dem: np.ndarray,
    catchment_mask: np.ndarray,
    cell_size_m: float,
) -> Tuple[float, float, float, float, float, float]:
    """
    Compute slope statistics over catchment cells using finite-difference
    gradient of the DEM.

    np.gradient is applied with explicit cell_size_m spacing.
    slope_m_per_m = sqrt(dx^2 + dy^2)
    slope_deg = atan(slope_m_per_m) * 180/pi
    NaN values are excluded via nanmean/nanmax/nanmin.

    Returns (mean_deg, mean_m, max_deg, max_m, min_deg, min_m).
    """
    h, w = dem.shape
    if h < 2 or w < 2 or cell_size_m <= 0:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    dy, dx = np.gradient(dem, cell_size_m, cell_size_m)
    slope = np.sqrt(dx * dx + dy * dy)
    masked = np.where(catchment_mask, slope, np.nan)

    mean_m = float(np.nanmean(masked))
    max_m = float(np.nanmax(masked))
    min_m = float(np.nanmin(masked))

    def atan_deg(v):
        return math.degrees(math.atan(v)) if v > 0 else 0.0

    return (
        atan_deg(mean_m), mean_m,
        atan_deg(max_m), max_m,
        atan_deg(min_m), min_m,
    )


def compute_catchment_elevation_statistics(
    dem: np.ndarray,
    catchment_mask: np.ndarray,
) -> Tuple[float, float, float, float]:
    """
    Compute elevation statistics over catchment cells.

    Returns (min_m, max_m, relief_m, mean_m).
    Raises ValueError if the catchment mask is empty.
    """
    if not np.any(catchment_mask):
        raise ValueError("Catchment mask is empty.")
    masked = np.where(catchment_mask, dem, np.nan)
    min_m = float(np.nanmin(masked))
    max_m = float(np.nanmax(masked))
    return min_m, max_m, max_m - min_m, float(np.nanmean(masked))


def _build_upstream_graph(
    flow_direction: np.ndarray,
    catchment_mask: np.ndarray,
) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    """
    Build an upstream-neighbour graph for all catchment cells.

    upstream[(r,c)] = list of neighbour cells that flow into (r,c).
    A neighbour (nr,nc) flows into (r,c) when its D8 direction
    points from (nr,nc) to (r,c).
    """
    h, w = flow_direction.shape
    upstream: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for r in range(h):
        for c in range(w):
            if catchment_mask[r, c]:
                upstream[(r, c)] = []

    for r in range(h):
        for c in range(w):
            if not catchment_mask[r, c]:
                continue
            d = int(flow_direction[r, c])
            if d == NO_FLOW or d not in D8_OFFSETS:
                continue
            dr, dc = D8_OFFSETS[d]
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and catchment_mask[nr, nc]:
                upstream[(nr, nc)].append((r, c))
    return upstream


def _trace_downstream_path(
    start_row: int,
    start_col: int,
    outlet_row: int,
    outlet_col: int,
    flow_direction: np.ndarray,
    catchment_mask: np.ndarray,
    cell_size_m: float,
) -> Tuple[float, int]:
    """
    Trace from start cell downstream to the outlet, accumulating
    geometric path length.  Returns (total_length_m, num_cells).
    """
    h, w = flow_direction.shape
    total_len = 0.0
    num_cells = 0
    visited = set()
    r, c = start_row, start_col
    while True:
        if (r, c) in visited:
            break
        visited.add((r, c))
        num_cells += 1
        if r == outlet_row and c == outlet_col:
            break
        d = int(flow_direction[r, c])
        if d == NO_FLOW or d not in D8_OFFSETS:
            break
        dr, dc = D8_OFFSETS[d]
        nr, nc = r + dr, c + dc
        if not (0 <= nr < h and 0 <= nc < w and catchment_mask[nr, nc]):
            break
        total_len += _d8_step_distance(d, cell_size_m)
        r, c = nr, nc
        if num_cells > h * w:
            break
    return total_len, num_cells


def compute_longest_d8_flow_path(
    flow_direction: np.ndarray,
    catchment_mask: np.ndarray,
    outlet_row: int,
    outlet_col: int,
    cell_size_m: float,
) -> Tuple[float, int, int, int, int]:
    """
    Compute the longest D8 flow path within the catchment.

    Algorithm:
    1. Build upstream graph over catchment cells.
    2. Find headwater cells (zero upstream neighbours).
    3. Trace each headwater downstream to the outlet.
    4. Return the longest.

    Returns (longest_path_m, longest_cells,
             num_headwaters, outlet_row, outlet_col).
    """
    if not catchment_mask[outlet_row, outlet_col]:
        raise ValueError(
            f"Outlet ({outlet_row},{outlet_col}) not in catchment mask."
        )
    upstream = _build_upstream_graph(flow_direction, catchment_mask)
    headwaters = [k for k, v in upstream.items() if len(v) == 0]
    if not headwaters:
        return 0.0, 0, 0, outlet_row, outlet_col

    best_len = 0.0
    best_cells = 0
    for hw_r, hw_c in headwaters:
        path_len, n_cells = _trace_downstream_path(
            hw_r, hw_c, outlet_row, outlet_col,
            flow_direction, catchment_mask, cell_size_m,
        )
        if path_len > best_len:
            best_len, best_cells = path_len, n_cells
    return float(best_len), int(best_cells), len(headwaters), outlet_row, outlet_col


def compute_catchment_terrain_diagnostics(
    dem: np.ndarray,
    flow_direction: np.ndarray,
    catchment_mask: np.ndarray,
    outlet_row: int,
    outlet_col: int,
    cell_size_m: float,
) -> CatchmentTerrainDiagnosticsResult:
    """
    Compute all Phase 11A catchment terrain diagnostics.
    """
    warnings = []

    # Slope statistics
    try:
        mean_d, mean_m, max_d, max_m, min_d, min_m =             compute_catchment_slope_statistics(dem, catchment_mask, cell_size_m)
    except Exception as exc:
        logger.warning("Slope stats failed: %s", exc)
        mean_d = mean_m = max_d = max_m = min_d = min_m = 0.0
        warnings.append(f"Slope: {exc}")

    # Elevation statistics
    try:
        min_e, max_e, relief, mean_e =             compute_catchment_elevation_statistics(dem, catchment_mask)
    except Exception as exc:
        logger.warning("Elevation stats failed: %s", exc)
        min_e = max_e = relief = mean_e = 0.0
        warnings.append(f"Elevation: {exc}")

    # Longest flow path
    path_m = path_cells = num_hw = 0
    out_r, out_c = outlet_row, outlet_col
    try:
        path_m, path_cells, num_hw, out_r, out_c =             compute_longest_d8_flow_path(
                flow_direction, catchment_mask,
                outlet_row, outlet_col, cell_size_m,
            )
    except Exception as exc:
        logger.warning("Flow path failed: %s", exc)
        warnings.append(f"Flow path: {exc}")

    if path_cells == 0:
        warnings.append(
            "Longest flow path is zero or undefined. "
            "Catchment may be degenerate (single cell) or "
            "all paths terminate before reaching the outlet."
        )

    method = (
        f"Slope: finite-diff gradient of original DEM masked to catchment; "
        f"gradient(dem, {cell_size_m:.1f}m) -> dx/dy in m/m; "
        f"slope_m_per_m = sqrt(dx^2+dy^2); "
        f"slope_deg = atan(slope)*180/pi.  "
        f"Elevation: min/max/mean of dem[catchment_mask].  "
        f"Longest flow path: D8 predecessor graph over catchment; "
        f"all headwater-to-outlet paths traced; "
        f"cardinal step={cell_size_m:.1f}m, diagonal={cell_size_m:.1f}m*sqrt(2).  "
        f"Path length = sum of step distances."
    )

    return CatchmentTerrainDiagnosticsResult(
        mean_slope_deg=round(mean_d, 6),
        mean_slope_m_per_m=round(mean_m, 8),
        max_slope_deg=round(max_d, 6),
        max_slope_m_per_m=round(max_m, 8),
        min_slope_deg=round(min_d, 6),
        min_slope_m_per_m=round(min_m, 8),
        min_elevation_m=round(min_e, 4),
        max_elevation_m=round(max_e, 4),
        relief_m=round(relief, 4),
        mean_elevation_m=round(mean_e, 4),
        longest_flow_path_m=round(path_m, 4),
        longest_flow_path_cells=int(path_cells),
        longest_flow_path_outlet_row=int(out_r),
        longest_flow_path_outlet_col=int(out_c),
        number_of_headwater_cells=int(num_hw),
        method=method,
        warnings=warnings,
    )


def summarise_terrain_diagnostics(
    result: CatchmentTerrainDiagnosticsResult,
) -> dict:
    """Return a JSON-friendly dict representation."""
    return {
        "mean_slope_deg": result.mean_slope_deg,
        "mean_slope_m_per_m": result.mean_slope_m_per_m,
        "max_slope_deg": result.max_slope_deg,
        "max_slope_m_per_m": result.max_slope_m_per_m,
        "min_slope_deg": result.min_slope_deg,
        "min_slope_m_per_m": result.min_slope_m_per_m,
        "min_elevation_m": result.min_elevation_m,
        "max_elevation_m": result.max_elevation_m,
        "relief_m": result.relief_m,
        "mean_elevation_m": result.mean_elevation_m,
        "longest_flow_path_m": result.longest_flow_path_m,
        "longest_flow_path_cells": result.longest_flow_path_cells,
        "longest_flow_path_outlet_row": result.longest_flow_path_outlet_row,
        "longest_flow_path_outlet_col": result.longest_flow_path_outlet_col,
        "number_of_headwater_cells": result.number_of_headwater_cells,
        "method": result.method,
        "warnings": result.warnings,
    }
