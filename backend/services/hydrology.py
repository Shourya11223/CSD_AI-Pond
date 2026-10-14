"""
Hydrology service (Stage 3).

Transforms an interpolated Digital Elevation Model (DEM) into a
hydrologically usable terrain model by:

    1. Filling spurious depressions (sinks) with the Priority-Flood
       algorithm, starting from the grid boundary and processing
       inwards using a priority queue ordered by elevation.

    2. Computing a D8 flow-direction grid (each cell routes to the
       steepest positive downhill neighbour among the 8 surrounding
       cells).

    3. Computing a flow-accumulation grid (number of upstream cells
       that ultimately drain through every cell) using a topological
       indegree-based pass, which runs in O(N) rather than the naive
       O(N * path_length) approach.

The service is intentionally modular: future stages (pond selection,
catchment delineation) can re-use the returned DEM, flow direction
and accumulation arrays without recomputing anything.

Notes / explainability (Viva points)
-----------------------------------
* **Priority-Flood (Barnes 2014)**: rather than iteratively smoothing
  the terrain (which both destroys genuine valleys and may never
  terminate on a large DEM), we perform a single priority-queue
  flood from the boundary. Any cell reached by the flood is
  guaranteed to be at a "spill elevation" >= its original elevation,
  so the result is a hydrologically sound surface that is the
  minimal modification of the original (in the L-infinity sense).

* **D8 directions**: each interior cell points to exactly one of
  its 8 neighbours based on the steepest positive gradient. The
  integer encoding is::

       7  8  1
       6  *  2       (clockwise from East, "compass-rose" encoding)
       5  4  3

  which matches the convention used by ESRI/ArcGIS and by the
  RichDEM / pysheds libraries. Value 0 means "no outflow"
  (boundary cell or local pit that survived the fill step).

* **Flow accumulation**: the indegree (number of upstream
  neighbours) of each cell is computed, then a Kahn-style
  topological pass drains the graph from the headwaters. Each
  cell's contribution (1 grid cell worth of area) is added to
  its downstream neighbour. This avoids repeatedly tracing paths
  from every cell and naturally produces an O(N) pass that is
  cycle-safe: the depression-filling step has already removed
  the closed basins that would otherwise create cycles.
"""

from __future__ import annotations

import heapq
import logging
import math
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# D8 direction encoding
# ---------------------------------------------------------------------------
#
# Compass-rose (ArcGIS / RichDEM / pysheds) encoding:
#
#         7  8  1
#         6  *  2
#         5  4  3
#
# For each direction code we store (row_offset, col_offset) where
# row increases SOUTH (numpy convention) and col increases EAST.
# 0 is reserved for "no outflow / sink / boundary".
#
D8_OFFSETS: Dict[int, Tuple[int, int]] = {
    1: (0, 1),    # East
    2: (1, 1),    # South-East
    3: (1, 0),    # South
    4: (1, -1),   # South-West
    5: (0, -1),   # West
    6: (-1, -1),  # North-West
    7: (-1, 0),   # North
    8: (-1, 1),   # North-East
}

# Inverse lookup: (row_offset, col_offset) -> direction code
_D8_LOOKUP: Dict[Tuple[int, int], int] = {v: k for k, v in D8_OFFSETS.items()}

# Distance from a cell centre to the centre of its neighbour.
_CARDINAL_DIST = 1.0
_DIAGONAL_DIST = math.sqrt(2.0)

# Sentinel direction value for "no outflow" / boundary cell.
NO_FLOW = 0

# Human-readable D8 mapping for API responses / docs.
D8_ENCODING_DESCRIPTION: Dict[str, str] = {
    "0": "no outflow (boundary or local pit)",
    "1": "East",
    "2": "South-East",
    "3": "South",
    "4": "South-West",
    "5": "West",
    "6": "North-West",
    "7": "North",
    "8": "North-East",
}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class HydrologyResult:
    """Container for the full hydrology pipeline output.

    The grids are kept here so that downstream stages (pond
    selection, catchment delineation) can re-use them without
    re-running the pipeline.

    Attributes
    ----------
    dem_original : (H, W) float64 ndarray
        The pre-fill elevation grid (the Stage 2 IDW output).
        Stored so that diagnostics can recompute the adjustment
        distribution without re-running the pipeline.
    dem_filled : (H, W) float64 ndarray
        The depression-filled elevation grid.
    flow_direction : (H, W) int8 ndarray
        D8 flow-direction codes (0-8).
    flow_accumulation_cells : (H, W) int64 ndarray
        Upstream contributing cell count.
    flow_accumulation_area : (H, W) float64 ndarray
        Contributing area in square metres.
    depression_modified_cells : int
    depression_max_adjustment : float
    depression_total_adjustment : float
    valid_flow_cells : int
    sink_cells : int
    max_accumulated_cells : int
    max_accumulated_area_m2 : float
    max_accum_row : int
    max_accum_col : int
    min_accumulated_cells : int
    total_flowing_cells : int
    projection_info : dict or None
        Projection metadata (bounding box + metres-per-degree).
    diagnostics : dict or None
        Extended diagnostics as returned by compute_diagnostics().
    """
    dem_original: np.ndarray
    dem_filled: np.ndarray
    flow_direction: np.ndarray
    flow_accumulation_cells: np.ndarray
    flow_accumulation_area: np.ndarray
    depression_modified_cells: int
    depression_max_adjustment: float
    depression_total_adjustment: float
    valid_flow_cells: int
    sink_cells: int
    max_accumulated_cells: int
    max_accumulated_area_m2: float
    max_accum_row: int
    max_accum_col: int
    min_accumulated_cells: int
    total_flowing_cells: int
    projection_info: dict = None
    diagnostics: dict = None


# ---------------------------------------------------------------------------
# 1. Priority-Flood depression filling
# ---------------------------------------------------------------------------

def _priority_flood_fill(dem: np.ndarray) -> Tuple[np.ndarray, float, float, int]:
    """
    Fill spurious depressions in ``dem`` using the Priority-Flood algorithm.

    The implementation follows Barnes, Lehman & Mulla (2014) "Priority-Flood:
    An Optimal Depression-Filling and Watershed-Labeling Algorithm for
    Digital Elevation Models", Computers & Geosciences.

    Conceptually:

      * Treat every cell as a node in a graph weighted by elevation.
      * Push all boundary cells onto a min-heap and mark them "visited".
      * Repeatedly pop the lowest-elevation visited cell ``c``;
        for each unvisited neighbour ``n``:
            - mark ``n`` as visited
            - if ``dem[n] <= dem[c]`` we MUST raise ``dem[n]`` to
              ``dem[c]`` plus a tiny epsilon so that water can leave
              ``n`` (otherwise ``n`` becomes a new pit inside the
              basin we are filling).
            - push ``(dem[n], n)`` onto the heap.

    The result is the minimal (in L-infinity sense) modification of
    the original DEM such that every cell has a monotonically
    non-increasing path to the boundary.

    Parameters
    ----------
    dem : (H, W) float ndarray
        Input elevation grid in metres.

    Returns
    -------
    filled : (H, W) float ndarray
        The filled DEM (a copy of ``dem``).
    max_adjustment : float
        Maximum single-cell elevation raise, in metres.
    total_adjustment : float
        Sum of every cell's elevation raise, in metres.
    modified_cells : int
        Number of cells whose elevation was raised.
    """
    h, w = dem.shape

    # Work on a copy so the caller's array is never mutated.
    filled = dem.astype(np.float64, copy=True)

    # Accumulators for statistics.
    total_adjustment = 0.0
    max_adjustment = 0.0
    modified_cells = 0

    # visited mask: True once a cell has been pulled from the heap
    # (or pushed as a boundary seed).
    visited = np.zeros((h, w), dtype=bool)

    # Min-heap of (elevation, row, col).
    heap: list[tuple[float, int, int]] = []

    # Seed the heap with the entire grid boundary. These are the
    # natural spill points / outlets of the DEM.
    for col in range(w):
        visited[0, col] = True
        heapq.heappush(heap, (filled[0, col], 0, col))
        visited[h - 1, col] = True
        heapq.heappush(heap, (filled[h - 1, col], h - 1, col))
    for row in range(1, h - 1):
        visited[row, 0] = True
        heapq.heappush(heap, (filled[row, 0], row, 0))
        visited[row, w - 1] = True
        heapq.heappush(heap, (filled[row, w - 1], row, w - 1))

    # Priority-Flood main loop. Each pop is O(log N) so the whole
    # fill is O(N log N) where N = h * w.
    while heap:
        z, r, c = heapq.heappop(heap)

        for dr, dc in D8_OFFSETS.values():
            nr, nc = r + dr, c + dc
            if nr < 0 or nr >= h or nc < 0 or nc >= w:
                continue
            if visited[nr, nc]:
                continue
            visited[nr, nc] = True

            neighbour_z = filled[nr, nc]
            if neighbour_z <= z:
                # The neighbour is a pit (or a flat inside a basin).
                # Raise it to (z + epsilon) so it can spill into us.
                # The epsilon is a tiny value (32-bit float ULP scaled
                # by local relief) that is physically meaningless but
                # breaks ties without distorting the terrain.
                eps = max(np.finfo(np.float32).eps * max(1.0, abs(z)), 1e-9)
                new_z = z + eps
                adjustment = new_z - neighbour_z
                filled[nr, nc] = new_z
                total_adjustment += adjustment
                if adjustment > max_adjustment:
                    max_adjustment = adjustment
                modified_cells += 1
                heapq.heappush(heap, (new_z, nr, nc))
            else:
                # Neighbour is already higher than the current spill
                # level; just add it to the heap at its own elevation.
                heapq.heappush(heap, (neighbour_z, nr, nc))

    return filled, max_adjustment, total_adjustment, modified_cells

# ---------------------------------------------------------------------------
# 3. Flow accumulation (topological / indegree-based)
# ---------------------------------------------------------------------------

def _compute_flow_accumulation(flow_dir, cell_size_m):
    """
    Compute the flow-accumulation grid using a topological pass.

    Algorithm
    ---------
    1. Compute each cell's indegree = number of upstream neighbours
       that flow INTO it. For a D8 grid this is at most 8.
    2. Initialise every cell's accumulation to 1 (each cell
       contributes itself to the area of whatever drains through it).
    3. Push every cell with indegree == 0 (headwater / boundary
       outlets) into a queue.
    4. Repeatedly pop a cell c and:
           - look up its downstream neighbour d (if any),
           - add accumulation[c] to accumulation[d],
           - decrement indegree[d] and, if it reaches 0, push d.

    This is a Kahn-style topological sort of the flow graph. It
    runs in O(N) (each cell is popped once) and is naturally
    cycle-safe: the depression-filling step has already eliminated
    the closed basins that would otherwise create routing cycles.
    If a cycle ever did survive the fill, the affected cells would
    simply have indegree > 0 forever and be excluded from the
    queue. We log a warning if that happens so it can be diagnosed.

    Parameters
    ----------
    flow_dir : (H, W) int ndarray
        D8 flow direction grid (0-8).
    cell_size_m : float
        Grid cell size in metres.

    Returns
    -------
    accum_cells : (H, W) int64 ndarray
        Number of upstream cells (including the cell itself) that
        drain through every cell.
    accum_area : (H, W) float64 ndarray
        Contributing area in square metres
        (accum_cells * cell_size_m^2).
    stats : dict
        Aggregate statistics.
    """
    h, w = flow_dir.shape
    accum_cells = np.ones((h, w), dtype=np.int64)
    accum_area = np.full((h, w), cell_size_m * cell_size_m, dtype=np.float64)

    # Build indegree and flattened downstream index.
    indegree = np.zeros((h, w), dtype=np.int32)
    downstream = np.full((h, w), -1, dtype=np.int32)  # -1 = no downstream

    for r in range(h):
        for c in range(w):
            d = int(flow_dir[r, c])
            if d == NO_FLOW:
                continue
            dr, dc = D8_OFFSETS[d]
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w:
                downstream[r, c] = nr * w + nc
                indegree[nr, nc] += 1

    # Kahn's algorithm: every cell with indegree 0 is a headwater.
    queue = list(np.flatnonzero(indegree == 0))

    head = 0
    while head < len(queue):
        flat = queue[head]
        head += 1
        r, c = divmod(flat, w)

        ds = int(downstream[r, c])
        if ds < 0:
            continue
        nr, nc = divmod(ds, w)
        accum_cells[nr, nc] += accum_cells[r, c]
        accum_area[nr, nc] += accum_area[r, c]
        indegree[nr, nc] -= 1
        if indegree[nr, nc] == 0:
            queue.append(ds)

    # Sanity: how many cells were never popped? Any non-zero count
    # indicates a routing cycle that survived the depression fill.
    unprocessed = int((indegree > 0).sum())
    if unprocessed > 0:
        logger.warning(
            "Flow accumulation: %d cells were never popped (possible routing cycle).",
            unprocessed,
        )

    # Aggregate statistics.
    max_idx = int(np.argmax(accum_cells))
    max_row, max_col = divmod(max_idx, w)

    stats = {
        "max_accumulated_cells": int(accum_cells.max()),
        "max_accumulated_area_m2": float(accum_cells.max() * cell_size_m * cell_size_m),
        "max_accum_row": int(max_row),
        "max_accum_col": int(max_col),
        "min_accumulated_cells": int(accum_cells.min()),
        "total_flowing_cells": int((accum_cells > 0).sum()),
        "unprocessed_cells": unprocessed,
    }
    return accum_cells, accum_area, stats



# ---------------------------------------------------------------------------
# 2. D8 flow direction
# ---------------------------------------------------------------------------

def _compute_d8_flow_direction(dem):
    """
    Compute the D8 flow-direction grid for a hydrologically conditioned DEM.

    For every INTERIOR cell (not on the grid boundary) the algorithm:

      1. Looks at the 8 surrounding neighbours.
      2. For each neighbour with a strictly LOWER elevation, computes
         the gradient ``(z - z_n) / distance``, where
         ``distance = cell_size`` for cardinal neighbours and
         ``distance = cell_size * sqrt(2)`` for diagonal neighbours.
      3. Routes the flow to the neighbour with the steepest positive
         gradient.

    Boundary cells are implicitly marked with ``NO_FLOW`` (0) because
    there is no neighbour on the outside of the grid.

    Cells that have no strictly-lower neighbour are local minima;
    because the DEM has been depression-filled these should be
    extremely rare, but if they do occur we mark them with
    ``NO_FLOW`` and report them as "sink cells" in the statistics.
    This is the documented behaviour: a sink with no outflow
    contributes its own 1 cell to the accumulation grid, but does
    not pass flow onward. Downstream pond selection can use the
    accumulation map of these cells as pond candidates.

    Parameters
    ----------
    dem : (H, W) float ndarray
        Depression-filled elevation grid (metres).

    Returns
    -------
    flow_dir : (H, W) int8 ndarray
        Integer D8 direction codes (0-8, see ``D8_OFFSETS``).
    valid_flow_cells : int
        Number of interior cells that point to a strictly lower neighbour.
    sink_cells : int
        Number of interior cells with no lower neighbour (rare after fill).
    """
    h, w = dem.shape
    flow_dir = np.zeros((h, w), dtype=np.int8)

    valid_flow_cells = 0
    sink_cells = 0

    for r in range(1, h - 1):
        for c in range(1, w - 1):
            z = dem[r, c]
            best_grad = 0.0
            best_dir = NO_FLOW

            for d, (dr, dc) in D8_OFFSETS.items():
                nz = dem[r + dr, c + dc]
                drop = z - nz
                if drop <= 0.0:
                    continue
                dist = _DIAGONAL_DIST if dr != 0 and dc != 0 else _CARDINAL_DIST
                grad = drop / dist
                if grad > best_grad:
                    best_grad = grad
                    best_dir = d

            flow_dir[r, c] = best_dir
            if best_dir == NO_FLOW:
                sink_cells += 1
            else:
                valid_flow_cells += 1

    return flow_dir, valid_flow_cells, sink_cells

# ---------------------------------------------------------------------------
# 3b. Diagnostics (extended, reusable, no algorithmic side effects)
# ---------------------------------------------------------------------------

# These thresholds are the user-facing thresholds mentioned in the
# spec. They are applied as exclusive comparisons (> threshold) so
# that a raise of exactly 0.10 m does NOT count as "above 0.1 m".
# Keeping them in one place makes the diagnostics easy to extend.
ADJUSTMENT_THRESHOLDS_M: tuple = (0.1, 0.5, 1.0, 2.0, 5.0)


def _is_on_boundary(h: int, w: int, r: int, c: int) -> bool:
    """Return True if cell (r, c) is on the outer edge of an (h, w) grid."""
    return r == 0 or r == h - 1 or c == 0 or c == w - 1


def _grid_to_geographic(
    row: int,
    col: int,
    grid_height: int,
    grid_width: int,
    grid_cell_size_m: float,
    projection_info: dict | None,
) -> tuple:
    """
    Convert grid (row, col) -> (lat, lon) using a local equirectangular
    projection (the same one used by services.terrain_model).

    Coordinate convention (consistent with terrain_model):
        * x = (lon - center_lon) * metres_per_degree_lon
        * y = (lat - center_lat) * metres_per_degree_lat
        * cell centre at (gx_min + (c+0.5)*cell, gy_min + (r+0.5)*cell)
        * row=0 is the SMALLEST y (i.e. the MIN latitude, the south edge)
        * row=H-1 is the LARGEST y (i.e. the MAX latitude, the north edge)

    Parameters
    ----------
    row, col : int
        0-based grid indices.
    grid_height, grid_width : int
        Grid dimensions in cells.
    grid_cell_size_m : float
        Cell-centre spacing in metres.
    projection_info : dict or None
        Projection metadata as returned by terrain_model.build_terrain_model.
        Must contain: center_lat_deg, center_lon_deg, metres_per_degree_lon,
        and (post-fix) grid_origin_x_m, grid_origin_y_m.
        If None or missing required keys, returns (None, None).

    Returns
    -------
    (lat, lon) : tuple of float or (None, None)
    """
    if projection_info is None:
        return None, None
    m_per_deg_lon = float(projection_info.get("metres_per_degree_lon", 0.0))
    m_per_deg_lat = float(projection_info.get("metres_per_degree_lat", 111320.0))
    center_lon = float(projection_info.get("center_lon_deg", 0.0))
    center_lat = float(projection_info.get("center_lat_deg", 0.0))
    if m_per_deg_lon <= 0:
        return None, None

    # Preferred path: use the grid origin stored in projection_info
    # by terrain_model. This guarantees consistency between the
    # forward (lat/lon -> grid) and inverse (grid -> lat/lon) maps.
    gx_min = projection_info.get("grid_origin_x_m")
    gy_min = projection_info.get("grid_origin_y_m")
    if gx_min is not None and gy_min is not None:
        cell_size = float(grid_cell_size_m)
        x_m = float(gx_min) + (col + 0.5) * cell_size
        y_m = float(gy_min) + (row + 0.5) * cell_size
        lon = center_lon + x_m / m_per_deg_lon
        lat = center_lat + y_m / m_per_deg_lat
        return lat, lon

    # Fallback (legacy / missing origin): this used to silently produce
    # wildly wrong coordinates. We deliberately do NOT guess the origin
    # any more; we return (None, None) so the caller knows to supply
    # an enriched projection_info.
    return None, None


def compute_diagnostics(
    dem_original: np.ndarray,
    dem_filled: np.ndarray,
    flow_dir: np.ndarray,
    flow_accumulation_cells: np.ndarray,
    cell_size_m: float,
    projection_info: dict | None = None,
) -> dict:
    """
    Compute extended diagnostics for the hydrology pipeline.

    This function is intentionally a PURE ANALYSIS step: it does not
    modify any of the input arrays. It is designed to be called after
    run_hydrology() and to be reusable for any (dem, flow_dir,
    accumulation) triplet.

    The function reports:

    1. **Elevation-adjustment distribution** (over the modified cells):
       count, percentage, mean, median, 95th percentile, max, std.

    2. **Threshold exceedances**: how many modified cells exceed
       0.1, 0.5, 1.0, 2.0 and 5.0 m.

    3. **Location of the maximum adjustment** in grid coordinates
       and, if projection info is available, in geographic
       lat/lon.

    4. **Boundary diagnostics**: how many grid-boundary cells are
       flow outlets, and whether the maximum-accumulation cell is
       itself on the grid boundary.

    5. **Terrain sanity**: original vs filled elevation statistics,
       and a check that the algorithm never lowered any cell.

    Parameters
    ----------
    dem_original : (H, W) ndarray
        Pre-fill elevation grid (the Stage 2 output).
    dem_filled : (H, W) ndarray
        Post-fill elevation grid (the Stage 3 DEM).
    flow_dir : (H, W) ndarray
        D8 direction grid (0-8).
    flow_accumulation_cells : (H, W) ndarray
        Accumulation grid in upstream-cell count.
    cell_size_m : float
        Cell-centre spacing in metres.
    projection_info : dict, optional
        Projection metadata as returned by
        services.terrain_model.build_terrain_model. When supplied,
        geographic (lat, lon) of the diagnostic points is also
        reported. If absent, lat/lon fields are returned as None.

    Returns
    -------
    dict
        A JSON-serialisable dictionary matching the
        HydrologyDiagnostics Pydantic model.
    """
    if dem_original.shape != dem_filled.shape:
        raise ValueError(
            f"Shape mismatch: original {dem_original.shape} vs "
            f"filled {dem_filled.shape}"
        )
    h, w = dem_filled.shape
    total_cells = int(h * w)

    # --- Elevation adjustment distribution ---
    diff = (dem_filled - dem_original).astype(np.float64)
    positive = diff[diff > 0.0]
    modified_cells = int(positive.size)
    modified_pct = 100.0 * modified_cells / total_cells if total_cells > 0 else 0.0

    if modified_cells > 0:
        mean_adj = float(positive.mean())
        median_adj = float(np.median(positive))
        p95_adj = float(np.percentile(positive, 95))
        max_adj = float(positive.max())
        std_adj = float(positive.std())
        # Location of the maximum adjustment
        max_flat = int(np.argmax(diff))
        max_row, max_col = divmod(max_flat, w)
        # Threshold exceedance counts
        c_01 = int(np.sum(positive > 0.1))
        c_05 = int(np.sum(positive > 0.5))
        c_10 = int(np.sum(positive > 1.0))
        c_20 = int(np.sum(positive > 2.0))
        c_50 = int(np.sum(positive > 5.0))
    else:
        mean_adj = 0.0
        median_adj = 0.0
        p95_adj = 0.0
        max_adj = 0.0
        std_adj = 0.0
        max_row = 0
        max_col = 0
        c_01 = c_05 = c_10 = c_20 = c_50 = 0

    # --- Terrain sanity statistics ---
    orig_min = float(dem_original.min())
    orig_max = float(dem_original.max())
    orig_mean = float(dem_original.mean())
    orig_std = float(dem_original.std())
    fill_min = float(dem_filled.min())
    fill_max = float(dem_filled.max())
    fill_mean = float(dem_filled.mean())
    fill_std = float(dem_filled.std())
    no_cells_lowered = bool(np.all(diff >= 0.0))
    all_changes_nonneg = bool(np.all(diff >= 0.0))

    max_adj_lat, max_adj_lon = _grid_to_geographic(
        max_row, max_col, h, w, cell_size_m, projection_info
    )

    # --- Boundary flow diagnostics ---
    # A boundary cell is an "outlet" if its flow_dir is 0 (no
    # downstream neighbour); this is the natural definition for a
    # well-formed DEM whose highest cells are inside the grid.
    boundary_mask = np.zeros((h, w), dtype=bool)
    boundary_mask[0, :] = True
    boundary_mask[-1, :] = True
    boundary_mask[1:-1, 0] = True
    boundary_mask[1:-1, -1] = True
    total_boundary_cells = int(boundary_mask.sum())
    boundary_outlets = int(np.sum(flow_dir[boundary_mask] == NO_FLOW))

    # Maximum-accumulation cell
    max_accum_idx = int(np.argmax(flow_accumulation_cells))
    max_accum_row, max_accum_col = divmod(max_accum_idx, w)
    max_accum_on_boundary = _is_on_boundary(
        h, w, max_accum_row, max_accum_col
    )
    max_accum_lat, max_accum_lon = _grid_to_geographic(
        max_accum_row, max_accum_col, h, w, cell_size_m, projection_info
    )

    return {
        "depression_fill": {
            "total_cells": total_cells,
            "modified_cells": modified_cells,
            "modified_pct": modified_pct,
            "mean_adjustment_m": mean_adj,
            "median_adjustment_m": median_adj,
            "p95_adjustment_m": p95_adj,
            "max_adjustment_m": max_adj,
            "std_adjustment_m": std_adj,
            "cells_above_0_1m": c_01,
            "cells_above_0_5m": c_05,
            "cells_above_1_0m": c_10,
            "cells_above_2_0m": c_20,
            "cells_above_5_0m": c_50,
            "max_adjustment_row": int(max_row),
            "max_adjustment_col": int(max_col),
            "max_adjustment_lat": max_adj_lat,
            "max_adjustment_lon": max_adj_lon,
            "elevation_change": {
                "original_min": orig_min,
                "original_max": orig_max,
                "original_mean": orig_mean,
                "original_std": orig_std,
                "filled_min": fill_min,
                "filled_max": fill_max,
                "filled_mean": fill_mean,
                "filled_std": fill_std,
                "mean_increase": fill_mean - orig_mean,
                "max_increase": fill_max - orig_max,
            },
            "no_cells_lowered": no_cells_lowered,
            "all_changes_nonnegative": all_changes_nonneg,
        },
        "boundary": {
            "total_boundary_cells": total_boundary_cells,
            "boundary_outlets": boundary_outlets,
            "max_accum_is_boundary": max_accum_on_boundary,
            "max_accum_row": int(max_accum_row),
            "max_accum_col": int(max_accum_col),
            "max_accum_lat": max_accum_lat,
            "max_accum_lon": max_accum_lon,
        },
    }


# ---------------------------------------------------------------------------
# 4. Public entry point
# ---------------------------------------------------------------------------

def run_hydrology(dem, cell_size_m, projection_info=None, include_diagnostics=True):
    """
    Run the full hydrology pipeline on an interpolated DEM.

    Parameters
    ----------
    dem : (H, W) float ndarray
        Interpolated elevation grid in metres (output of Stage 2).
    cell_size_m : float
        Grid cell size in metres (cell-to-centre spacing).

    Returns
    -------
    HydrologyResult
        Dataclass with the depression-filled DEM, the D8 direction
        grid, the flow-accumulation grids (cells and area) and
        diagnostic statistics.

    Raises
    ------
    ValueError
        If the DEM is too small (< 3x3) or cell_size_m is not positive.
    """
    if cell_size_m <= 0:
        raise ValueError(f"cell_size_m must be > 0, got {cell_size_m}.")
    if dem.ndim != 2:
        raise ValueError(f"DEM must be 2-D, got shape {dem.shape}.")
    if dem.shape[0] < 3 or dem.shape[1] < 3:
        raise ValueError(
            f"DEM must be at least 3x3 for flow-direction analysis, "
            f"got shape {dem.shape}."
        )

    logger.info(
        "Running hydrology pipeline on %d x %d DEM (cell size = %.3f m).",
        dem.shape[0], dem.shape[1], cell_size_m,
    )

    # 1. Depression filling.
    dem_filled, max_adj, total_adj, modified_cells = _priority_flood_fill(dem)
    logger.info(
        "Priority-Flood fill: %d cells modified, max raise = %.6f m, "
        "total raise = %.6f m.",
        modified_cells, max_adj, total_adj,
    )

    # 2. D8 flow direction.
    flow_dir, valid_flow_cells, sink_cells = _compute_d8_flow_direction(dem_filled)
    logger.info(
        "D8 flow direction: %d valid flow cells, %d sinks.",
        valid_flow_cells, sink_cells,
    )

    # 3. Flow accumulation.
    accum_cells, accum_area, stats = _compute_flow_accumulation(flow_dir, cell_size_m)
    logger.info(
        "Flow accumulation: max = %d cells (%.3f m^2) at (%d, %d).",
        stats["max_accumulated_cells"],
        stats["max_accumulated_area_m2"],
        stats["max_accum_row"],
        stats["max_accum_col"],
    )

    # 4. Extended diagnostics (optional).
    diagnostics = None
    if include_diagnostics:
        diagnostics = compute_diagnostics(
            dem_original=dem,
            dem_filled=dem_filled,
            flow_dir=flow_dir,
            flow_accumulation_cells=accum_cells,
            cell_size_m=cell_size_m,
            projection_info=projection_info,
        )

    return HydrologyResult(
        dem_original=dem.astype(np.float64, copy=True),
        dem_filled=dem_filled,
        flow_direction=flow_dir,
        flow_accumulation_cells=accum_cells,
        flow_accumulation_area=accum_area,
        depression_modified_cells=int(modified_cells),
        depression_max_adjustment=float(max_adj),
        depression_total_adjustment=float(total_adj),
        valid_flow_cells=int(valid_flow_cells),
        sink_cells=int(sink_cells),
        max_accumulated_cells=int(stats["max_accumulated_cells"]),
        max_accumulated_area_m2=float(stats["max_accumulated_area_m2"]),
        max_accum_row=int(stats["max_accum_row"]),
        max_accum_col=int(stats["max_accum_col"]),
        min_accumulated_cells=int(stats["min_accumulated_cells"]),
        total_flowing_cells=int(stats["total_flowing_cells"]),
        projection_info=projection_info,
        diagnostics=diagnostics,
    )


# ---------------------------------------------------------------------------
# 5. Diagnostics summary (compact, JSON-friendly)
# ---------------------------------------------------------------------------

def summarise_hydrology(result):
    """
    Return a compact, JSON-friendly summary of a HydrologyResult.

    The full grids are deliberately omitted to keep the response
    size bounded; callers that need the grids can access them
    directly on the result object.
    """
    modified = result.depression_modified_cells
    return {
        "depression_fill": {
            "modified_cells": result.depression_modified_cells,
            "max_elevation_adjustment_m": result.depression_max_adjustment,
            "total_elevation_adjustment_m": result.depression_total_adjustment,
            "mean_adjustment_m": (
                result.depression_total_adjustment / modified
                if modified > 0 else 0.0
            ),
        },
        "flow_direction": {
            "valid_flow_cells": result.valid_flow_cells,
            "sink_cells": result.sink_cells,
            "d8_encoding": D8_ENCODING_DESCRIPTION,
        },
        "flow_accumulation": {
            "max_accumulated_cells": result.max_accumulated_cells,
            "max_accumulated_area_m2": result.max_accumulated_area_m2,
            "max_accum_row": result.max_accum_row,
            "max_accum_col": result.max_accum_col,
            "min_accumulated_cells": result.min_accumulated_cells,
            "total_flowing_cells": result.total_flowing_cells,
        },
    }

