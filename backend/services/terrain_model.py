"""
Terrain modeling service for building interpolated elevation grids from contour data.

This module converts parsed contour lines into a regular elevation grid
using a memory-efficient k-nearest-neighbour Inverse Distance Weighting
(IDW) implementation.  The pipeline:

1. Extract all contour points (lat, lon, elevation) from the parsed contour lines.
2. Thin/sample points spatially to keep computation tractable while preserving
   terrain shape.
3. Convert geographic (lat/lon) coordinates to a local metric coordinate system
   (metres) centred on the data extent.
4. Build a configurable regular grid covering the bounding box.
5. Build a KD-tree over the sample points and run k-nearest-neighbour IDW
   at each grid cell.  This avoids materialising the full N x M distance
   matrix, making the routine both fast and memory-efficient even when
   sample counts are large.
6. Return the grid with metadata.

All parameters are configurable so the service remains extensible for future
phases that may need different interpolation strategies or grid densities.
"""
import logging
import math
from typing import List, Optional, Tuple

import numpy as np
from scipy.spatial import cKDTree

from services.contour_parser import ContourLine

logger = logging.getLogger(__name__)

# Earth's meridional radius (metres per degree latitude, approximately constant)
_METRES_PER_DEG_LAT = 111_320.0


# --- Coordinate Reference / Projection ----------------------------------------

def _build_projection_info(
    min_lat: float, max_lat: float, min_lon: float, max_lon: float
) -> dict:
    """
    Build a minimal projection description from the geographic extent.

    For a small local area (a few km), an equirectangular projection
    centred on the data extent is sufficient and keeps distances in
    metres. The latitude of true scale is the centre latitude.

    For real GIS workflows a proper UTM or national-grid EPSG code
    would be used; this is a documented simplification.
    """
    center_lat = (min_lat + max_lat) / 2.0
    center_lon = (min_lon + max_lon) / 2.0
    metres_per_deg_lon = _METRES_PER_DEG_LAT * math.cos(math.radians(center_lat))
    return {
        "projection": "local_equirectangular",
        "center_lat_deg": center_lat,
        "center_lon_deg": center_lon,
        "metres_per_degree_lat": _METRES_PER_DEG_LAT,
        "metres_per_degree_lon": metres_per_deg_lon,
        "epsg_note": (
            "Approximate local Cartesian projection. For real GIS workflows, "
            "replace with a UTM or national-grid EPSG code."
        ),
    }


# --- Lat/Lon <-> Metres ---------------------------------------------------

def _latlon_to_metres(
    lat: np.ndarray, lon: np.ndarray,
    center_lat: float, center_lon: float,
    m_per_deg_lon: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Vectorised lat/lon to local metres."""
    x = (lon - center_lon) * m_per_deg_lon
    y = (lat - center_lat) * _METRES_PER_DEG_LAT
    return x, y


# --- Spatial thinning ------------------------------------------------------

def _spatial_thin(
    points_xy: np.ndarray,
    cell_size_m: float,
) -> np.ndarray:
    """
    Thin a set of 2-D metric points by keeping at most one point per cell.

    For each occupied cell the point closest to the cell centre is kept
    (ties broken by original input order). This preserves the spatial
    distribution while reducing density.

    The implementation is vectorised: a single lexicographic sort groups
    points by cell and orders them by distance-to-centre, then the first
    entry of each group is kept. This is mathematically identical to a
    per-cell ``argmin`` loop but runs in O(N log N) instead of
    O(cells * N), which is essential for large contour files.
    """
    if len(points_xy) == 0:
        return points_xy
    cell_indices = np.floor(points_xy / cell_size_m).astype(np.int64)
    _, inverse = np.unique(cell_indices, axis=0, return_inverse=True)
    inverse = np.asarray(inverse).reshape(-1)

    # Squared distance from each point to its own cell centre.
    centres = (cell_indices.astype(points_xy.dtype) + 0.5) * cell_size_m
    dists = np.sum((points_xy - centres) ** 2, axis=1)

    # Sort by (cell, distance, original index): the first entry per cell
    # is the point nearest the centre, ties resolved by input order.
    order = np.lexsort((np.arange(len(points_xy)), dists, inverse))
    sorted_cells = inverse[order]

    keep_mask = np.empty(sorted_cells.shape, dtype=bool)
    keep_mask[0] = True
    keep_mask[1:] = sorted_cells[1:] != sorted_cells[:-1]
    return points_xy[order[keep_mask]]


# --- IDW interpolation using KD-tree ----------------------------------------

def _idw_interpolate(
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    sample_xy: np.ndarray,
    sample_z: np.ndarray,
    k: int = 12,
    power: float = 2.0,
    epsilon: float = 1e-6,
) -> np.ndarray:
    """
    k-nearest-neighbour IDW interpolation via a KD-tree.

    For every grid cell we query the k nearest sample points and combine
    their elevations with inverse-distance weights:

        w_i = 1 / (d_i^p + eps)
        z   = sum(w_i * z_i) / sum(w_i)

    Using a KD-tree keeps the operation O((H*W) * log N) and avoids
    materialising the full H*W x N distance matrix.  This is critical
    when N (number of samples) is large.
    """
    tree = cKDTree(sample_xy)
    h = len(y_centers)
    w = len(x_centers)

    # Build the flat list of query points (x, y) in row-major order.
    grid_x, grid_y = np.meshgrid(x_centers, y_centers)
    query_pts = np.column_stack([grid_x.ravel(), grid_y.ravel()])

    # Query the k nearest neighbours.
    # dist shape: (H*W, k)
    # idx  shape: (H*W, k)
    dist, idx = tree.query(query_pts, k=k)

    # Handle the case where k > len(sample_xy) gracefully.
    k_actual = idx.shape[1]
    if k_actual < k:
        logger.warning(
            "Requested k=%d but only %d samples available; using %d.",
            k, k_actual, k_actual,
        )

    # Look up neighbour elevations.
    z_neighbours = sample_z[idx]   # (H*W, k)

    # IDW weights with epsilon guard.
    weights = 1.0 / (dist ** power + epsilon)   # (H*W, k)
    weight_sum = np.sum(weights, axis=1)

    # Weighted average.
    z_flat = np.sum(weights * z_neighbours, axis=1) / weight_sum
    return z_flat.reshape(h, w)


# --- Public API ------------------------------------------------------------

def build_terrain_model(
    contours: List[ContourLine],
    grid_cell_size_m: float = 5.0,
    idw_power: float = 2.0,
    idw_epsilon: float = 1e-6,
    idw_k: int = 12,
    thinning_cell_size_m: Optional[float] = None,
    max_grid_cells: int = 200_000,
) -> dict:
    """
    Build an interpolated terrain model from parsed contour lines.

    Parameters
    ----------
    contours : list[ContourLine]
        Contour lines produced by the contour parser.
    grid_cell_size_m : float, optional
        Spacing of the regular grid in metres.  Default 5 m is appropriate
        for village-scale analysis with ~1 m contour intervals.
    idw_power : float, optional
        IDW power exponent.  Default 2.0 is the standard choice in most
        GIS packages (e.g. ArcGIS Geostatistical Analyst).
    idw_epsilon : float, optional
        Small constant added to distance^p in the IDW denominator to
        avoid division by zero when a grid cell sits on a sample point.
    idw_k : int, optional
        Number of nearest neighbours to use for IDW at each grid cell.
        Default 12 is a good balance: enough samples to smooth out
        local noise, few enough to keep each estimate locally
        sensitive.  Too many neighbours over-smooths the terrain.
    thinning_cell_size_m : float, optional
        Cell size for spatial thinning.  When None, defaults to
        max(grid_cell_size_m, 5 m) so the sample density is at least one
        point per analysis cell.
    max_grid_cells : int, optional
        Soft cap on the total number of grid cells (W * H).  If the
        requested resolution would exceed this, the grid is coarsened
        automatically so the response stays tractable.

    Returns
    -------
    dict with full terrain description (grid + metadata).  The numpy
    array of interpolated elevations is included for downstream use;
    API responses should convert it to a compact summary.
    """
    if not contours:
        raise ValueError("No contour lines provided for terrain modelling.")

    # 1. Collect all contour points.
    all_lats, all_lons, all_elevs = [], [], []
    for c in contours:
        for pt in c.points:
            all_lats.append(pt.lat)
            all_lons.append(pt.lon)
            all_elevs.append(c.elevation)
    all_lats = np.array(all_lats)
    all_lons = np.array(all_lons)
    all_elevs = np.array(all_elevs)
    num_contour_points = len(all_lats)

    min_lat, max_lat = float(all_lats.min()), float(all_lats.max())
    min_lon, max_lon = float(all_lons.min()), float(all_lons.max())

    # 2. Projection.
    proj = _build_projection_info(min_lat, max_lat, min_lon, max_lon)
    center_lat = proj["center_lat_deg"]
    center_lon = proj["center_lon_deg"]
    m_per_deg_lon = proj["metres_per_degree_lon"]

    # 3. Convert to metres.
    x_m, y_m = _latlon_to_metres(
        all_lats, all_lons, center_lat, center_lon, m_per_deg_lon
    )
    all_xy = np.column_stack([x_m, y_m])

    # 4. Spatial thinning.
    if thinning_cell_size_m is None:
        thinning_cell_size_m = max(grid_cell_size_m, 5.0)
    sampled_xy = _spatial_thin(all_xy, thinning_cell_size_m)

    # Find each kept point's nearest original point to get its elevation.
    if len(sampled_xy) < len(all_xy):
        tree_full = cKDTree(all_xy)
        _, nearest_idx = tree_full.query(sampled_xy, k=1)
        sampled_z = all_elevs[nearest_idx]
    else:
        sampled_z = all_elevs

    num_sample_points = len(sampled_xy)
    logger.info(
        "Thinned %d contour points to %d samples (cell=%.1f m)",
        num_contour_points, num_sample_points, thinning_cell_size_m,
    )

    # 5. Build the regular metric grid, coarsening if necessary.
    extent_x = float(sampled_xy[:, 0].max() - sampled_xy[:, 0].min())
    extent_y = float(sampled_xy[:, 1].max() - sampled_xy[:, 1].min())

    requested_w = max(1, int(math.ceil(extent_x / grid_cell_size_m)) + 1)
    requested_h = max(1, int(math.ceil(extent_y / grid_cell_size_m)) + 1)
    if requested_w * requested_h > max_grid_cells:
        scale = math.sqrt((requested_w * requested_h) / max_grid_cells)
        adjusted_cell = grid_cell_size_m * scale
        logger.warning(
            "Grid would be %d x %d = %d cells; coarsening to %.2f m to stay "
            "under the %d-cell cap.",
            requested_w, requested_h, requested_w * requested_h,
            adjusted_cell, max_grid_cells,
        )
        grid_cell_size_m = adjusted_cell

    pad = grid_cell_size_m * 0.5
    gx_min = float(sampled_xy[:, 0].min()) - pad
    gy_min = float(sampled_xy[:, 1].min()) - pad
    grid_width = max(1, int(math.ceil(extent_x / grid_cell_size_m)) + 1)
    grid_height = max(1, int(math.ceil(extent_y / grid_cell_size_m)) + 1)

    x_centers = gx_min + (np.arange(grid_width) + 0.5) * grid_cell_size_m
    y_centers = gy_min + (np.arange(grid_height) + 0.5) * grid_cell_size_m

    # 6. KD-tree-based IDW interpolation.
    logger.info(
        "Starting IDW interpolation: %d samples, grid %d x %d (%.1f m cells), "
        "k=%d neighbours, power=%.1f",
        num_sample_points, grid_width, grid_height, grid_cell_size_m,
        idw_k, idw_power,
    )
    grid_z = _idw_interpolate(
        x_centers, y_centers, sampled_xy, sampled_z,
        k=idw_k, power=idw_power, epsilon=idw_epsilon,
    )

    z_min = float(np.nanmin(grid_z))
    z_max = float(np.nanmax(grid_z))
    z_mean = float(np.nanmean(grid_z))
    z_std = float(np.nanstd(grid_z))

    # Enrich projection info with the actual grid origin so that
    # downstream code (e.g. services.hydrology._grid_to_geographic)
    # can reconstruct (lat, lon) from (row, col) without re-deriving
    # the origin from the contour bounding box.
    #
    # Coordinate convention used everywhere in this codebase:
    #   * x = (lon - center_lon) * metres_per_degree_lon   (east in metres)
    #   * y = (lat - center_lat) * metres_per_degree_lat   (north in metres)
    #   * cell centre at (gx_min + (c+0.5)*cell, gy_min + (r+0.5)*cell)
    #   * row=0 is the SMALLEST y (i.e. the MIN latitude, the south edge)
    #   * row=H-1 is the LARGEST y (i.e. the MAX latitude, the north edge)
    proj = dict(proj)  # do not mutate the original
    proj["grid_origin_x_m"] = float(gx_min)
    proj["grid_origin_y_m"] = float(gy_min)
    proj["grid_width_cells"] = int(grid_width)
    proj["grid_height_cells"] = int(grid_height)
    proj["grid_cell_size_m"] = float(grid_cell_size_m)
    # Geographic extent of the grid in lat/lon (cell centres, inclusive).
    # The southern edge of the grid is at gy_min + 0.5*cell_size (i.e. row 0)
    # and the northern edge is at gy_min + (H-0.5)*cell_size (i.e. row H-1).
    proj["grid_lat_min"] = center_lat + (gy_min + 0.5 * grid_cell_size_m) / _METRES_PER_DEG_LAT
    proj["grid_lat_max"] = center_lat + (gy_min + (grid_height - 0.5) * grid_cell_size_m) / _METRES_PER_DEG_LAT
    proj["grid_lon_min"] = center_lon + (gx_min + 0.5 * grid_cell_size_m) / m_per_deg_lon
    proj["grid_lon_max"] = center_lon + (gx_min + (grid_width - 0.5) * grid_cell_size_m) / m_per_deg_lon

    return {
        "grid_width": int(grid_width),
        "grid_height": int(grid_height),
        "grid_cell_size_m": float(grid_cell_size_m),
        "min_elevation_m": z_min,
        "max_elevation_m": z_max,
        "mean_elevation_m": z_mean,
        "std_elevation_m": z_std,
        "num_sample_points": int(num_sample_points),
        "num_contour_points": int(num_contour_points),
        "contour_count": len(contours),
        "projection_info": proj,
        "bounding_box": {
            "min_lat": min_lat, "max_lat": max_lat,
            "min_lon": min_lon, "max_lon": max_lon,
        },
        "grid": grid_z,
        "origin_xy_m": (float(gx_min), float(gy_min)),
    }


def summarise_terrain_grid(grid_z: np.ndarray, sample_rows: int = 8, sample_cols: int = 8) -> dict:
    """
    Build a compact, validation-friendly summary of an interpolated grid.

    The full grid is too large to send over the API as JSON.  This
    function returns:
      - basic statistics
      - a uniformly sub-sampled 2-D array (default 8x8) so the caller
        can sanity-check the terrain shape without exploding the response
        size
    """
    h, w = grid_z.shape
    row_idx = np.linspace(0, h - 1, sample_rows, dtype=int)
    col_idx = np.linspace(0, w - 1, sample_cols, dtype=int)
    sampled = grid_z[np.ix_(row_idx, col_idx)]

    return {
        "shape": [int(h), int(w)],
        "min": float(np.nanmin(grid_z)),
        "max": float(np.nanmax(grid_z)),
        "mean": float(np.nanmean(grid_z)),
        "std": float(np.nanstd(grid_z)),
        "sampled_shape": [int(sample_rows), int(sample_cols)],
        "sampled_grid": sampled.tolist(),
    }
