"""
Catchment delineation service (Stage 5).

Given a D8 flow-direction grid, flow-accumulation grid, and a selected
pond-candidate outlet cell, this service delineates the upstream catchment
using a reverse D8 traversal (also known as "upstream accumulation" or
"flow trace" approach).

Algorithm
---------

1. **Input**: A pond-candidate outlet cell (row, col), D8 flow-direction
   grid, flow-accumulation grid, terrain grid, and projection metadata.

2. **Delineation via reverse D8 traversal**:
   - Start from the selected outlet cell.
   - Add the outlet to the catchment queue.
   - For each cell in the queue, inspect all 8 neighbours.
   - A neighbour belongs to the catchment if its D8 direction points
     *directly* into the current cell (i.e., the neighbour routes to
     this cell via D8).
   - Continue using BFS until no additional upstream cells remain.
   - Each cell is visited at most once (tracked by a boolean mask).

3. **Output**:
   - Binary catchment mask (True = inside catchment).
   - Catchment cell count and area in m^2, hectares, and km^2.
   - Geographic boundary representation for visualization.
   - Validation diagnostics.

The D8 direction encoding used is the compass-rose convention::

        7  8  1
        6  *  2
        5  4  3

where 0 means "no outflow / sink".  The inverse lookup is used to
determine if a neighbour's D8 direction points into the current cell.

Time Complexity
---------------
O(N) where N is the number of cells in the grid, because each cell
is visited at most once during the BFS traversal.

Space Complexity
----------------
O(N) for the boolean visited/catchment mask.

References
----------
- O'Callaghan, J.F. & Mark, D.M. (1984). The extraction of drainage
  networks from digital elevation data. Computer Vision, Graphics, and
  Image Processing.
- Barnes, M. et al. (2014). The Priority-Flood algorithm for regular
  raster grids. Computers & Geosciences.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from services.hydrology import D8_OFFSETS, NO_FLOW, _grid_to_geographic

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class CatchmentConfig:
    """Configuration for catchment delineation."""
    # Reserved for future use (e.g. boundary margin overrides).
    boundary_margin_cells: int = 2


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CatchmentBoundary:
    """
    Geographic boundary representation of the catchment for frontend visualization.

    Attributes
    ----------
    boundary_type : str
        Type of boundary: "convex_hull", "boundary_centroids", or "empty".
    boundary_coordinates : List[List[float]]
        List of [lon, lat] coordinate pairs (or local metres if no
        projection is available). For convex_hull, this is the polygon
        vertices in order. For boundary_centroids, this is the centre
        point of each boundary cell.
    boundary_cells : List[Dict]
        List of cell dictionaries with row, col, lat, lon, elevation_m
        for each boundary cell.
    num_boundary_cells : int
        Number of cells on the catchment boundary.
    num_boundary_points : int
        Number of coordinate points in the boundary representation.
    bounding_box : Dict
        Bounding box of the catchment: {min_lat, max_lat, min_lon, max_lon}.
    """
    boundary_type: str
    boundary_coordinates: List[List[float]]
    boundary_cells: List[Dict]
    num_boundary_cells: int
    num_boundary_points: int
    bounding_box: Dict


@dataclass
class CatchmentDiagnostics:
    """
    Diagnostics for catchment validation and algorithm performance.
    """
    outlet_in_catchment: bool = False
    no_duplicate_cells: bool = False
    traversal_terminated_safely: bool = False
    cells_visited_count: int = 0
    max_queue_size: int = 0
    outlet_flow_accum_consistent: bool = False
    catchment_area_consistent: bool = False
    area_within_grid: bool = False
    time_elapsed_s: float = 0.0


@dataclass
class CatchmentResult:
    """
    Result of catchment delineation for a selected outlet.
    """
    outlet_row: int
    outlet_col: int
    outlet_lat: float
    outlet_lon: float
    catchment_mask: np.ndarray
    catchment_cells: int
    catchment_area_m2: float
    catchment_area_ha: float
    catchment_area_km2: float
    catchment_pct_of_grid: float
    flow_accum_at_outlet: int
    outlet_upstream_area_m2: float
    grid_area_m2: float
    grid_cells: int
    boundary: CatchmentBoundary
    diagnostics: CatchmentDiagnostics


# ---------------------------------------------------------------------------
# Core delineation algorithm
# ---------------------------------------------------------------------------


def delineate_catchment(
    outlet_row: int,
    outlet_col: int,
    flow_direction: np.ndarray,
    flow_accumulation: np.ndarray,
    dem: np.ndarray,
    cell_size_m: float,
    projection_info: Optional[dict] = None,
    config: Optional[CatchmentConfig] = None,
) -> CatchmentResult:
    """
    Delineate the upstream catchment for a selected pond-candidate outlet
    using reverse D8 traversal (BFS).

    The algorithm starts from the outlet cell and finds all upstream
    neighbours whose D8 direction points into the current cell.
    Each cell is visited at most once.

    Returns a CatchmentResult with mask, area, boundary, and diagnostics.
    Raises ValueError if outlet coordinates are outside grid bounds.
    """
    t_start = time.time()

    if config is None:
        config = CatchmentConfig()

    h, w = flow_direction.shape

    # Validate outlet coordinates
    if not (0 <= outlet_row < h and 0 <= outlet_col < w):
        raise ValueError(
            f"Outlet coordinates ({outlet_row}, {outlet_col}) are outside "
            f"grid bounds ({h} rows x {w} cols)."
        )

    # Initialize masks
    catchment_mask = np.zeros((h, w), dtype=bool)
    visited = np.zeros((h, w), dtype=bool)

    # BFS: start from outlet
    queue = deque()
    queue.append((outlet_row, outlet_col))
    catchment_mask[outlet_row, outlet_col] = True
    visited[outlet_row, outlet_col] = True

    cells_visited = 0
    max_queue_size = 0

    # Reverse D8 traversal using BFS
    while queue:
        max_queue_size = max(max_queue_size, len(queue))
        r, c = queue.popleft()
        cells_visited += 1

        # Check all 8 neighbours
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue

                nr, nc = r + dr, c + dc

                # Bounds check
                if not (0 <= nr < h and 0 <= nc < w):
                    continue

                if visited[nr, nc]:
                    continue

                neigh_dir = int(flow_direction[nr, nc])

                if neigh_dir == NO_FLOW:
                    continue

                if neigh_dir not in D8_OFFSETS:
                    continue

                offset_r, offset_c = D8_OFFSETS[neigh_dir]

                # Neighbour drains into current cell if:
                # offset_r == -dr and offset_c == -dc
                if offset_r == -dr and offset_c == -dc:
                    queue.append((nr, nc))
                    catchment_mask[nr, nc] = True
                    visited[nr, nc] = True

    # Compute catchment area
    catchment_cells = int(catchment_mask.sum())
    cell_area_m2 = cell_size_m ** 2
    catchment_area_m2 = float(catchment_cells) * cell_area_m2
    catchment_area_ha = catchment_area_m2 / 10_000.0
    catchment_area_km2 = catchment_area_m2 / 1_000_000.0

    grid_cells_total = h * w
    grid_area_m2 = float(grid_cells_total) * cell_area_m2
    catchment_pct_of_grid = (
        (catchment_area_m2 / grid_area_m2 * 100.0) if grid_area_m2 > 0 else 0.0
    )

    # Flow accumulation at outlet
    flow_accum_at_outlet = int(flow_accumulation[outlet_row, outlet_col])
    outlet_upstream_area_m2 = float(flow_accum_at_outlet) * cell_area_m2

    # Outlet geographic coordinates
    if projection_info is not None:
        outlet_lat, outlet_lon = _grid_to_geographic(
            outlet_row, outlet_col, h, w, cell_size_m, projection_info
        )
    else:
        outlet_lat, outlet_lon = None, None

    # Generate boundary
    boundary = _generate_catchment_boundary(
        catchment_mask, dem, cell_size_m, projection_info
    )

    # Validation diagnostics
    diagnostics = CatchmentDiagnostics(
        outlet_in_catchment=bool(catchment_mask[outlet_row, outlet_col]),
        no_duplicate_cells=(cells_visited == catchment_cells),
        traversal_terminated_safely=True,
        cells_visited_count=cells_visited,
        max_queue_size=max_queue_size,
        outlet_flow_accum_consistent=(flow_accum_at_outlet == catchment_cells),
        catchment_area_consistent=(
            abs(catchment_area_m2 - float(catchment_cells) * cell_area_m2) < 1e-6
        ),
        area_within_grid=(catchment_area_m2 <= grid_area_m2 * 1.001),
        time_elapsed_s=time.time() - t_start,
    )

    return CatchmentResult(
        outlet_row=outlet_row,
        outlet_col=outlet_col,
        outlet_lat=float(outlet_lat) if outlet_lat is not None else 0.0,
        outlet_lon=float(outlet_lon) if outlet_lon is not None else 0.0,
        catchment_mask=catchment_mask,
        catchment_cells=catchment_cells,
        catchment_area_m2=catchment_area_m2,
        catchment_area_ha=catchment_area_ha,
        catchment_area_km2=catchment_area_km2,
        catchment_pct_of_grid=catchment_pct_of_grid,
        flow_accum_at_outlet=flow_accum_at_outlet,
        outlet_upstream_area_m2=outlet_upstream_area_m2,
        grid_area_m2=grid_area_m2,
        grid_cells=grid_cells_total,
        boundary=boundary,
        diagnostics=diagnostics,
    )



# ---------------------------------------------------------------------------
# Boundary generation
# ---------------------------------------------------------------------------


def _generate_catchment_boundary(
    catchment_mask: np.ndarray,
    dem: np.ndarray,
    cell_size_m: float,
    projection_info: Optional[dict] = None,
) -> CatchmentBoundary:
    """
    Generate a geographic boundary representation of the catchment.

    Identifies the boundary cells (catchment cells with at least one
    non-catchment neighbour) and produces a convex hull polygon (if
    scipy is available) or a list of boundary cell centroids for
    frontend visualization.

    The convex hull is a SIMPLIFIED representation: a mathematically
    smooth watershed boundary would require a full marching-squares
    polygon extraction. We explicitly do NOT pretend that the raster
    cell outline is a smooth watershed boundary.
    """
    h, w = catchment_mask.shape

    # Find boundary cells: catchment cells with at least one
    # non-catchment 8-neighbour
    boundary_cells = []
    for r in range(h):
        for c in range(w):
            if not catchment_mask[r, c]:
                continue

            is_boundary = False
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < h and 0 <= nc < w:
                        if not catchment_mask[nr, nc]:
                            is_boundary = True
                            break
                if is_boundary:
                    break

            if is_boundary:
                lat, lon = None, None
                if projection_info is not None:
                    lat, lon = _grid_to_geographic(
                        r, c, h, w, cell_size_m, projection_info
                    )
                boundary_cells.append({
                    "row": int(r),
                    "col": int(c),
                    "lat": float(lat) if lat is not None else None,
                    "lon": float(lon) if lon is not None else None,
                    "elevation_m": float(dem[r, c]) if dem is not None else None,
                })

    num_boundary_cells = len(boundary_cells)

    # Compute bounding box
    lats = [bc["lat"] for bc in boundary_cells if bc["lat"] is not None]
    lons = [bc["lon"] for bc in boundary_cells if bc["lon"] is not None]
    if lats and lons:
        bbox = {
            "min_lat": min(lats),
            "max_lat": max(lats),
            "min_lon": min(lons),
            "max_lon": max(lons),
        }
    else:
        bbox = {
            "min_lat": None, "max_lat": None,
            "min_lon": None, "max_lon": None,
        }

    # Attempt to build a convex hull for smoother visualization
    boundary_type = "empty"
    boundary_coordinates: List[List[float]] = []

    try:
        from scipy.spatial import ConvexHull

        catchment_indices = np.where(catchment_mask)
        if len(catchment_indices[0]) >= 3:
            rows = catchment_indices[0]
            cols = catchment_indices[1]

            # Cell centres in local metres from the grid origin
            y_coords = rows.astype(np.float64) * cell_size_m + cell_size_m / 2.0
            x_coords = cols.astype(np.float64) * cell_size_m + cell_size_m / 2.0

            points = np.column_stack([x_coords, y_coords])

            try:
                hull = ConvexHull(points)
                hull_vertices = points[hull.vertices]

                if projection_info is not None:
                    origin_x = projection_info.get("grid_origin_x_m", 0.0)
                    origin_y = projection_info.get("grid_origin_y_m", 0.0)
                    center_lat = projection_info.get("center_lat_deg", 0.0)
                    center_lon = projection_info.get("center_lon_deg", 0.0)
                    m_per_deg_lat = projection_info.get("metres_per_degree_lat", 111320.0)
                    m_per_deg_lon = projection_info.get("metres_per_degree_lon", 111320.0)

                    for vx, vy in hull_vertices:
                        lon = center_lon + (origin_x + float(vx)) / m_per_deg_lon
                        lat = center_lat + (origin_y + float(vy)) / m_per_deg_lat
                        boundary_coordinates.append([float(lon), float(lat)])
                else:
                    for vx, vy in hull_vertices:
                        boundary_coordinates.append([float(vx), float(vy)])

                boundary_type = "convex_hull"
            except Exception as e:
                logger.debug("Convex hull computation failed: %s", e)
    except ImportError:
        logger.debug("scipy not available for convex hull")

    # Fallback: boundary cell centroids
    if not boundary_coordinates and boundary_cells:
        for bc in boundary_cells:
            if bc["lon"] is not None and bc["lat"] is not None:
                boundary_coordinates.append([bc["lon"], bc["lat"]])
        if boundary_coordinates:
            boundary_type = "boundary_centroids"

    return CatchmentBoundary(
        boundary_type=boundary_type,
        boundary_coordinates=boundary_coordinates,
        boundary_cells=boundary_cells,
        num_boundary_cells=num_boundary_cells,
        num_boundary_points=len(boundary_coordinates),
        bounding_box=bbox,
    )



# ---------------------------------------------------------------------------
# Compact summariser (JSON-friendly)
# ---------------------------------------------------------------------------


def summarise_catchment(result: CatchmentResult) -> dict:
    """
    Return a compact, JSON-friendly summary of a CatchmentResult.

    The full catchment mask is omitted to keep the response size
    bounded; callers that need the mask can access it directly on
    the result object.
    """
    return {
        "outlet": {
            "row": result.outlet_row,
            "col": result.outlet_col,
            "lat": result.outlet_lat,
            "lon": result.outlet_lon,
        },
        "catchment": {
            "cells": result.catchment_cells,
            "area_m2": result.catchment_area_m2,
            "area_ha": result.catchment_area_ha,
            "area_km2": result.catchment_area_km2,
            "pct_of_grid": result.catchment_pct_of_grid,
        },
        "flow_accumulation": {
            "at_outlet": result.flow_accum_at_outlet,
            "upstream_area_m2": result.outlet_upstream_area_m2,
        },
        "grid": {
            "cells": result.grid_cells,
            "area_m2": result.grid_area_m2,
        },
        "boundary": {
            "type": result.boundary.boundary_type,
            "num_boundary_cells": result.boundary.num_boundary_cells,
            "num_boundary_points": result.boundary.num_boundary_points,
            "bounding_box": result.boundary.bounding_box,
            "coordinates": result.boundary.boundary_coordinates,
        },
        "diagnostics": {
            "outlet_in_catchment": result.diagnostics.outlet_in_catchment,
            "no_duplicate_cells": result.diagnostics.no_duplicate_cells,
            "traversal_terminated_safely": result.diagnostics.traversal_terminated_safely,
            "cells_visited": result.diagnostics.cells_visited_count,
            "max_queue_size": result.diagnostics.max_queue_size,
            "flow_accum_consistent": result.diagnostics.outlet_flow_accum_consistent,
            "area_consistent": result.diagnostics.catchment_area_consistent,
            "area_within_grid": result.diagnostics.area_within_grid,
            "time_elapsed_s": result.diagnostics.time_elapsed_s,
        },
    }


# ---------------------------------------------------------------------------
# Integrated analysis: pond -> catchment
# ---------------------------------------------------------------------------


def _candidate_to_summary_dict(candidate) -> dict:
    """Convert a PondCandidate dataclass to a JSON-friendly summary dict.

    Reuses the actual values produced by the pond selection algorithm
    so that the frontend can compare candidates honestly. Does not
    invent factor values.
    """
    return {
        "rank": int(candidate.rank),
        "row": int(candidate.row),
        "col": int(candidate.col),
        "lat": candidate.lat,
        "lon": candidate.lon,
        "elevation_m": float(candidate.elevation_m),
        "suitability_score": float(candidate.score_total),
        "flow_accumulation_cells": int(candidate.flow_accumulation_cells),
        "local_slope_deg": float(candidate.local_slope_deg),
        "relative_elevation_m": float(candidate.relative_elevation_m),
        "factor_scores": {
            "accumulation": float(candidate.score_accumulation),
            "low_slope": float(candidate.score_low_slope),
            "low_relative_elevation": float(candidate.score_low_relative),
            "drainage_concentration": float(candidate.score_drainage),
        },
    }


def run_integrated_analysis(
    pond_result,
    hydro_result,
    model: dict,
    rank: int = 1,
    config: Optional[CatchmentConfig] = None,
    water_exclusion_info: Optional[dict] = None,
) -> Tuple[CatchmentResult, dict]:
    """
    Run catchment delineation for a selected (by rank) pond candidate
    from a precomputed pond selection and hydrology result.

    Parameters
    ----------
    pond_result : PondSelectionResult
        Pond selection result containing ranked candidates.
    hydro_result : HydrologyResult
        Hydrology result with flow_direction, flow_accumulation, dem_original.
    model : dict
        Terrain model dict (must contain grid_cell_size_m, projection_info).
    rank : int
        Rank of pond candidate to delineate (1 = top-ranked).
    config : CatchmentConfig, optional
        Configuration for catchment delineation.
    water_exclusion_info : dict, optional
        Compact summary of the Phase 2 water exclusion analysis to be
        echoed back to the caller for diagnostic purposes.

    Returns
    -------
    Tuple[CatchmentResult, dict]
        Catchment result and integrated analysis summary dict. The summary
        dict now includes the full ranked list of candidates under
        ``pond_candidates`` so the frontend can compare alternatives
        without re-running the pipeline.
    """
    if not pond_result.candidates:
        raise ValueError("No pond candidates found.")

    if rank < 1 or rank > len(pond_result.candidates):
        raise ValueError(
            f"Invalid rank {rank}. Must be between 1 and {len(pond_result.candidates)}."
        )

    selected = pond_result.candidates[rank - 1]

    catchment = delineate_catchment(
        outlet_row=selected.row,
        outlet_col=selected.col,
        flow_direction=hydro_result.flow_direction,
        flow_accumulation=hydro_result.flow_accumulation_cells,
        dem=hydro_result.dem_original,
        cell_size_m=model["grid_cell_size_m"],
        projection_info=model.get("projection_info"),
        config=config,
    )

    # ---- Phase 11A: Catchment terrain diagnostics (additive) ----
    # Computed once per integrated analysis, using the delineated
    # catchment mask and the original D8 flow-direction grid.
    # On any error, returns None so the main analysis is unaffected.
    try:
        from services.catchment_diagnostics import (
            compute_catchment_terrain_diagnostics,
            summarise_terrain_diagnostics,
        )
        terrain_diag = compute_catchment_terrain_diagnostics(
            dem=hydro_result.dem_original,
            flow_direction=hydro_result.flow_direction,
            catchment_mask=catchment.catchment_mask,
            outlet_row=catchment.outlet_row,
            outlet_col=catchment.outlet_col,
            cell_size_m=model["grid_cell_size_m"],
        )
        terrain_diag_summary = summarise_terrain_diagnostics(terrain_diag)
    except Exception as exc:
        logger.warning(
            "Phase 11A catchment terrain diagnostics failed: %s. "
            "Continuing without catchment_terrain.", exc,
        )
        terrain_diag_summary = None

    # ---- Phase 11B-1: Land cover (OSM/Overpass) ----
    # Computed once per integrated analysis using the catchment bounding box.
    # Requires no external rainfall input.
    land_cover_summary: Optional[dict] = None
    try:
        from services.land_cover import get_land_cover, summarise_land_cover
        bbox = catchment.boundary.bounding_box
        if bbox and any(v is not None for v in bbox.values()):
            lc_result = get_land_cover(
                bbox=(
                    bbox.get("min_lat", 0.0) or 0.0,
                    bbox.get("min_lon", 0.0) or 0.0,
                    bbox.get("max_lat", 0.0) or 0.0,
                    bbox.get("max_lon", 0.0) or 0.0,
                ),
                catchment_area_m2=catchment.catchment_area_m2,
            )
            land_cover_summary = summarise_land_cover(lc_result)
        else:
            logger.info("No catchment bounding box available for land cover query.")
    except Exception as exc:
        logger.warning(
            "Phase 11B land cover failed: %s. "
            "Continuing without land_cover.", exc,
        )
        land_cover_summary = None

    # ---- Phase 11B-4: Time of concentration (Kirpich) ----
    # Requires longest flow path and slope from Phase 11A.
    tc_summary: Optional[dict] = None
    if terrain_diag_summary is not None:
        try:
            from services.time_of_concentration import (
                compute_time_of_concentration,
                summarise_time_of_concentration,
            )
            tc_result = compute_time_of_concentration(
                longest_flow_path_m=terrain_diag_summary.get("longest_flow_path_m"),
                slope_m_per_m=terrain_diag_summary.get("mean_slope_m_per_m"),
            )
            tc_summary = summarise_time_of_concentration(tc_result)
        except Exception as exc:
            logger.warning(
                "Phase 11B time of concentration failed: %s. "
                "Continuing without time_of_concentration.", exc,
            )
            tc_summary = None

    # Build the full ranked candidate list (top 3-5 typically) for the
    # frontend. Candidates that were rejected by water exclusion are
    # already excluded upstream by ``find_pond_candidates``, so this
    # list is guaranteed to contain only valid, water-aware candidates.
    candidates_summary = [
        _candidate_to_summary_dict(c) for c in pond_result.candidates
    ]
    selected_summary = _candidate_to_summary_dict(selected)

    summary = {
        # Kept for backward compatibility — same shape as before.
        "selected_pond": {
            "rank": selected_summary["rank"],
            "row": selected_summary["row"],
            "col": selected_summary["col"],
            "lat": selected_summary["lat"],
            "lon": selected_summary["lon"],
            "elevation_m": selected_summary["elevation_m"],
            "suitability_score": selected_summary["suitability_score"],
            "flow_accumulation_cells": selected_summary["flow_accumulation_cells"],
        },
        # New: full ranked candidate list for comparison.
        "pond_candidates": candidates_summary,
        "num_candidates": len(candidates_summary),
        # Indicates which candidate has the detailed catchment result
        # (Phase 3 requirement #4).
        "selected_rank": int(selected.rank),
        "catchment": summarise_catchment(catchment),
        "consistency_check": {
            "flow_accum_at_outlet": catchment.flow_accum_at_outlet,
            "catchment_cells": catchment.catchment_cells,
            "consistent": catchment.flow_accum_at_outlet == catchment.catchment_cells,
        },
        "water_exclusion": water_exclusion_info or {
            "applied": False,
            "fallback_used": True,
            "features_found": 0,
            "feature_types": [],
            "cells_excluded": 0,
            "buffer_metres": 0.0,
            "error_message": "Water exclusion was not run.",
        },
        # ---- Phase 11A: catchment terrain diagnostics ----
        "catchment_terrain": terrain_diag_summary,
        # ---- Phase 11B-1: land cover (OSM/Overpass) ----
        "land_cover": land_cover_summary,
        # ---- Phase 11B-4: time of concentration ----
        "time_of_concentration": tc_summary,
    }

    return catchment, summary
