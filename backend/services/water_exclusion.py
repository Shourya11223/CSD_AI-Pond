"""
Water Exclusion Service (Phase 2).

Fetches existing water features (rivers, streams, lakes, ponds) from
OpenStreetMap via the Overpass API and builds a boolean mask that can
be used to exclude or penalize candidate pond locations that fall inside
existing water bodies.

Why OpenStreetMap?
- Free, openly licensed data (ODbL license)
- Global coverage including India (our area of interest)
- Overpass API provides a free, rate-limited endpoint

Approach:
1. Determine the geographic bounding box from the DEM/analysis area
2. Query the Overpass API for water-related ways and relations
3. Parse the response and build a boolean mask aligned to the DEM grid
4. Apply a configurable safety buffer (default 30 m) around water features
5. Return the mask and diagnostics

Graceful Degradation:
- If the Overpass API is unavailable: returns mask of all-False
- Core terrain/hydrology analysis continues unaffected
- Diagnostics clearly indicate water exclusion status

References:
- Overpass API: https://wiki.openstreetmap.org/wiki/Overpass_API
- ODbL License: https://opendatacommons.org/licenses/odbl/
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

from services.overpass_client import overpass_query, OVERPASS_ENDPOINTS

logger = logging.getLogger(__name__)

# Backwards-compatible alias (older tests may import this name).
OVERPASS_API_URL = OVERPASS_ENDPOINTS[0]

# Request timeout in seconds (delegated to the shared client).
REQUEST_TIMEOUT_S = 20.0

# Default safety buffer around water features in metres
DEFAULT_WATER_BUFFER_M = 30.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class WaterExclusionConfig:
    """Configuration for water exclusion service."""

    # Safety buffer around water features in metres
    buffer_metres: float = DEFAULT_WATER_BUFFER_M

    # Maximum bounding box dimension in degrees
    max_bbox_deg: float = 0.5

    # Cell size for raster mask (metres)
    mask_cell_size_m: float = 10.0

    # Whether to use EXCLUDE mode (reject candidates) or PENALTY mode
    mode: str = "exclude"  # "exclude" or "penalty"

    # Penalty value for PENALTY mode (0-100 scale)
    penalty_score: float = 0.0

    def __post_init__(self):
        if self.mode not in ("exclude", "penalty"):
            self.mode = "exclude"
        self.penalty_score = max(0.0, min(100.0, self.penalty_score))


@dataclass
class WaterFeature:
    """A geographic water feature (polygon or polyline)."""

    osm_type: str  # "way" or "relation"
    osm_id: int
    geometry_type: str  # "polygon" or "linestring"
    coordinates: List[Tuple[float, float]]  # [(lon, lat), ...]
    name: Optional[str] = None
    waterway_type: Optional[str] = None
    natural: Optional[str] = None


@dataclass
class WaterExclusionResult:
    """Result of water exclusion analysis."""

    # Boolean mask: True = inside/excluded water area
    mask: np.ndarray

    # Geographic bounding box used for the query
    bbox_min_lat: float
    bbox_max_lat: float
    bbox_min_lon: float
    bbox_max_lon: float

    # Raster mask metadata
    mask_rows: int
    mask_cols: int
    mask_cell_size_m: float
    mask_origin_lat: float
    mask_origin_lon: float

    # Features found
    features_found: int
    feature_types: List[str]

    # Buffer applied
    buffer_metres: float

    # Mode used
    mode: str

    # Status
    applied: bool
    fallback_used: bool
    error_message: Optional[str]

    # Performance
    query_time_s: float
    parse_time_s: float

    def to_dict(self) -> dict:
        """Return a JSON-friendly dictionary representation."""
        return {
            "applied": self.applied,
            "fallback_used": self.fallback_used,
            "error_message": self.error_message,
            "features_found": self.features_found,
            "feature_types": self.feature_types,
            "buffer_metres": self.buffer_metres,
            "mode": self.mode,
            "mask_shape": list(self.mask.shape) if self.mask is not None else None,
            "bbox": {
                "min_lat": self.bbox_min_lat,
                "max_lat": self.bbox_max_lat,
                "min_lon": self.bbox_min_lon,
                "max_lon": self.bbox_max_lon,
            },
            "mask_cell_size_m": self.mask_cell_size_m,
            "query_time_s": round(self.query_time_s, 3),
            "parse_time_s": round(self.parse_time_s, 3),
        }


# ---------------------------------------------------------------------------
# Overpass API interaction
# ---------------------------------------------------------------------------


def _build_overpass_query(bbox: Tuple[float, float, float, float]) -> str:
    """
    Build an Overpass QL query for water features within a bounding box.

    Args:
        bbox: (min_lat, min_lon, max_lat, max_lon)

    Returns:
        Overpass QL query string.
    """
    min_lat, min_lon, max_lat, max_lon = bbox

    # Overpass QL query for water features
    # Covers: rivers, streams, canals, lakes, ponds, reservoirs, wetlands
    query = f"""
[out:json][timeout:25];
(
  // Waterways (rivers, streams, canals)
  way["waterway"]({min_lat},{min_lon},{max_lat},{max_lon});
  // Natural water bodies (lakes, ponds, wetlands)
  way["natural"]({min_lat},{min_lon},{max_lat},{max_lon});
  // Landuse water (reservoirs, basins)
  way["landuse"]({min_lat},{min_lon},{max_lat},{max_lon});
);
// Output geometry with coordinates
out body geom;
"""
    return query.strip()


def _fetch_water_features(
    bbox: Tuple[float, float, float, float],
    timeout_s: float = REQUEST_TIMEOUT_S,
) -> Tuple[List[WaterFeature], Optional[str]]:
    """
    Fetch water features from the Overpass API using the robust multi-endpoint
    client with retries and fallback.

    Args:
        bbox: Geographic bounding box (min_lat, min_lon, max_lat, max_lon)
        timeout_s: Per-request timeout passed to the shared Overpass client.

    Returns:
        Tuple of (list of WaterFeature objects, error message or None)
    """
    query = _build_overpass_query(bbox)
    data, error = overpass_query(query, timeout_s=timeout_s)
    if error is not None:
        return [], error
    return _parse_overpass_response(data)


def _parse_overpass_response(data: dict) -> Tuple[List[WaterFeature], Optional[str]]:
    """
    Parse the Overpass API JSON response into WaterFeature objects.

    Args:
        data: JSON response from Overpass API

    Returns:
        Tuple of (list of WaterFeature objects, error message or None)
    """
    features = []

    try:
        elements = data.get("elements", [])
    except (TypeError, AttributeError):
        return [], "Invalid Overpass API response format"

    for element in elements:
        osm_type = element.get("type")
        osm_id = element.get("id")

        if osm_type not in ("way", "relation"):
            continue

        # Get geometry
        geometry = element.get("geometry", [])
        if not geometry:
            continue

        coordinates = [(pt["lon"], pt["lat"]) for pt in geometry]

        if len(coordinates) < 2:
            continue

        # Determine geometry type (polygon vs linestring)
        is_closed = (
            coordinates[0] == coordinates[-1] and len(coordinates) >= 3
        )
        geometry_type = "polygon" if is_closed else "linestring"

        # Extract tags
        tags = element.get("tags", {})
        name = tags.get("name")
        waterway_type = tags.get("waterway")
        natural = tags.get("natural")

        feature = WaterFeature(
            osm_type=osm_type,
            osm_id=osm_id,
            geometry_type=geometry_type,
            coordinates=coordinates,
            name=name,
            waterway_type=waterway_type,
            natural=natural,
        )
        features.append(feature)

    return features, None


# ---------------------------------------------------------------------------
# Raster mask creation - geometric helpers
# ---------------------------------------------------------------------------


def _metres_per_degree(lat: float) -> Tuple[float, float]:
    """
    Approximate metres per degree at a given latitude.

    Args:
        lat: Latitude in decimal degrees

    Returns:
        Tuple of (metres_per_degree_lat, metres_per_degree_lon)
    """
    # At equator: 1 degree ~ 111.32 km
    metres_per_degree_lat = 111_320.0
    # Longitude shrinks with latitude
    metres_per_degree_lon = 111_320.0 * math.cos(math.radians(lat))
    return metres_per_degree_lat, metres_per_degree_lon


def _point_in_polygon_ray(
    lat: float,
    lon: float,
    polygon: List[Tuple[float, float]],
    buffer_lat: float,
    buffer_lon: float,
) -> bool:
    """
    Point-in-polygon test using ray casting (even-odd rule).

    The polygon is expanded by (buffer_lat, buffer_lon) before testing,
    which approximates a small buffer in degrees.

    Args:
        lat, lon: Point coordinates (lat, lon)
        polygon: List of (lon, lat) vertices
        buffer_lat, buffer_lon: Buffer in degrees to expand the polygon

    Returns:
        True if point is inside the buffered polygon
    """
    n = len(polygon)
    inside = False

    j = n - 1
    for i in range(n):
        # Note: polygon vertices are (lon, lat); we work in (lat, lon)
        yi = polygon[i][1] - buffer_lat
        xi = polygon[i][0] - buffer_lon
        yj = polygon[j][1] - buffer_lat
        xj = polygon[j][0] - buffer_lon

        # Check if horizontal ray from point crosses edge
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i

    return inside


def _min_distance_to_linestring(
    lat: float,
    lon: float,
    linestring: List[Tuple[float, float]],
    m_per_deg_lat: float,
    m_per_deg_lon: float,
) -> Optional[float]:
    """
    Calculate minimum distance from a point to a linestring in metres.

    Args:
        lat, lon: Point coordinates
        linestring: List of (lon, lat) vertices
        m_per_deg_lat, m_per_deg_lon: Metres per degree

    Returns:
        Minimum distance in metres, or None if linestring is empty
    """
    if len(linestring) < 2:
        return None

    min_dist = float("inf")

    for i in range(len(linestring) - 1):
        p1_lon, p1_lat = linestring[i]
        p2_lon, p2_lat = linestring[i + 1]

        dist = _point_to_segment_distance_metres(
            lat, lon,
            p1_lat, p1_lon,
            p2_lat, p2_lon,
            m_per_deg_lat, m_per_deg_lon,
        )
        min_dist = min(min_dist, dist)

    return min_dist if min_dist < float("inf") else None


def _point_to_segment_distance_metres(
    px_lat: float, px_lon: float,
    p1_lat: float, p1_lon: float,
    p2_lat: float, p2_lon: float,
    m_per_deg_lat: float,
    m_per_deg_lon: float,
) -> float:
    """
    Minimum distance from point P to line segment P1-P2, in metres.

    Uses local-tangent-plane approximation: convert all coordinates to
    metres at the given latitude, then compute Euclidean distance.

    Args:
        px_lat, px_lon: Point coordinates
        p1_lat, p1_lon: Segment endpoint 1
        p2_lat, p2_lon: Segment endpoint 2

    Returns:
        Distance in metres
    """
    # Convert all to local metres
    x1 = p1_lon * m_per_deg_lon
    y1 = p1_lat * m_per_deg_lat
    x2 = p2_lon * m_per_deg_lon
    y2 = p2_lat * m_per_deg_lat
    x = px_lon * m_per_deg_lon
    y = px_lat * m_per_deg_lat

    # Vector from p1 to p2
    dx = x2 - x1
    dy = y2 - y1

    # Squared length of segment
    len_sq = dx * dx + dy * dy

    if len_sq < 1e-12:
        # Segment is a point
        return math.sqrt((x - x1) ** 2 + (y - y1) ** 2)

    # Parameter t for projection onto line, clamped to [0, 1]
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / len_sq))

    # Nearest point on segment
    near_x = x1 + t * dx
    near_y = y1 + t * dy

    return math.sqrt((x - near_x) ** 2 + (y - near_y) ** 2)


# ---------------------------------------------------------------------------
# Raster mask creation
# ---------------------------------------------------------------------------


def _create_water_mask(
    features: List[WaterFeature],
    bbox: Tuple[float, float, float, float],
    dem_rows: int,
    dem_cols: int,
    dem_cell_size_m: float,
    dem_origin_lat: float,
    dem_origin_lon: float,
    buffer_m: float,
) -> np.ndarray:
    """
    Create a boolean mask of water exclusion zones aligned to the DEM grid.

    Uses a grid-based approach: for each DEM cell, check if its centroid
    falls inside any buffered water feature.

    Args:
        features: List of water features from Overpass
        bbox: Geographic bounding box (min_lat, min_lon, max_lat, max_lon)
        dem_rows: Number of rows in the DEM grid
        dem_cols: Number of columns in the DEM grid
        dem_cell_size_m: DEM cell size in metres
        dem_origin_lat: Latitude of DEM origin (top-left corner)
        dem_origin_lon: Longitude of DEM origin (top-left corner)
        buffer_m: Safety buffer around water features in metres

    Returns:
        Boolean numpy array of shape (dem_rows, dem_cols).
        True = inside/excluded water area.
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    centre_lat = (min_lat + max_lat) / 2.0
    m_per_deg_lat, m_per_deg_lon = _metres_per_degree(centre_lat)

    # Buffer in degrees (approximate)
    buffer_deg_lat = buffer_m / m_per_deg_lat
    buffer_deg_lon = buffer_m / m_per_deg_lon

    # Initialize mask to False (no exclusion)
    mask = np.zeros((dem_rows, dem_cols), dtype=np.bool_)

    # Filter features to those that intersect our bbox
    relevant_features = []
    for f in features:
        coords = f.coordinates
        feat_min_lat = min(pt[1] for pt in coords)
        feat_max_lat = max(pt[1] for pt in coords)
        feat_min_lon = min(pt[0] for pt in coords)
        feat_max_lon = max(pt[0] for pt in coords)

        if (feat_max_lat >= min_lat and feat_min_lat <= max_lat and
                feat_max_lon >= min_lon and feat_min_lon <= max_lon):
            relevant_features.append(f)

    logger.info(f"Water exclusion: {len(relevant_features)}/{len(features)} features relevant to bbox")

    # Degrees of latitude/longitude covered by one DEM cell.
    deg_per_row = dem_cell_size_m / m_per_deg_lat
    deg_per_col = dem_cell_size_m / m_per_deg_lon

    for feature in relevant_features:
        coords = feature.coordinates

        # Restrict the scan to the feature's buffered bounding box. A cell
        # whose centroid lies outside it can be neither inside the buffered
        # polygon nor within buffer_m of the line, so the mask is unchanged;
        # this only avoids evaluating the entire grid for every feature.
        feat_min_lat = min(pt[1] for pt in coords) - buffer_deg_lat
        feat_max_lat = max(pt[1] for pt in coords) + buffer_deg_lat
        feat_min_lon = min(pt[0] for pt in coords) - buffer_deg_lon
        feat_max_lon = max(pt[0] for pt in coords) + buffer_deg_lon

        # Invert the centroid mapping (row 0 = north/top edge, col 0 = west),
        # with a one-cell safety margin so no boundary cell can be missed.
        r_lo = int(math.floor((dem_origin_lat - feat_max_lat) / deg_per_row - 0.5)) - 1
        r_hi = int(math.ceil((dem_origin_lat - feat_min_lat) / deg_per_row - 0.5)) + 1
        c_lo = int(math.floor((feat_min_lon - dem_origin_lon) / deg_per_col - 0.5)) - 1
        c_hi = int(math.ceil((feat_max_lon - dem_origin_lon) / deg_per_col - 0.5)) + 1

        r_lo = max(0, r_lo)
        r_hi = min(dem_rows - 1, r_hi)
        c_lo = max(0, c_lo)
        c_hi = min(dem_cols - 1, c_hi)
        if r_lo > r_hi or c_lo > c_hi:
            # Feature (plus buffer) does not intersect this grid.
            continue

        for r in range(r_lo, r_hi + 1):
            # Cell centroid latitude (constant for the whole row).
            cell_lat = dem_origin_lat - (r + 0.5) * deg_per_row

            for c in range(c_lo, c_hi + 1):
                # Cell centroid in geographic coordinates
                cell_lon = dem_origin_lon + (c + 0.5) * deg_per_col

                if feature.geometry_type == "polygon":
                    if _point_in_polygon_ray(
                        cell_lat, cell_lon, coords, buffer_deg_lat, buffer_deg_lon
                    ):
                        mask[r, c] = True
                else:
                    min_dist = _min_distance_to_linestring(
                        cell_lat, cell_lon, coords, m_per_deg_lat, m_per_deg_lon
                    )
                    if min_dist is not None and min_dist <= buffer_m:
                        mask[r, c] = True

    return mask


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def get_water_exclusion_mask(
    bbox: Tuple[float, float, float, float],
    dem_rows: int,
    dem_cols: int,
    dem_cell_size_m: float,
    dem_origin_lat: float,
    dem_origin_lon: float,
    config: Optional[WaterExclusionConfig] = None,
) -> WaterExclusionResult:
    """Get a water exclusion mask for the given DEM grid.
    
    This is the main entry point for the water exclusion service.
    """
    if config is None:
        config = WaterExclusionConfig()

    min_lat, min_lon, max_lat, max_lon = bbox

    # Clip bbox if too large for Overpass API
    bbox_size = max(max_lat - min_lat, max_lon - min_lon)
    if bbox_size > config.max_bbox_deg:
        logger.warning(f"Bbox size {bbox_size:.3f} deg exceeds max {config.max_bbox_deg}. Clipping.")
        if max_lat - min_lat > config.max_bbox_deg:
            center = (min_lat + max_lat) / 2
            min_lat = center - config.max_bbox_deg / 2
            max_lat = center + config.max_bbox_deg / 2
        if max_lon - min_lon > config.max_bbox_deg:
            center = (min_lon + max_lon) / 2
            min_lon = center - config.max_bbox_deg / 2
            max_lon = center + config.max_bbox_deg / 2
        bbox = (min_lat, min_lon, max_lat, max_lon)

    query_start = time.perf_counter()
    features, error = _fetch_water_features(bbox)
    query_time = time.perf_counter() - query_start

    parse_start = time.perf_counter()

    if error:
        logger.warning(f"Water exclusion fetch failed: {error}")
        parse_time = time.perf_counter() - parse_start
        return WaterExclusionResult(
            mask=np.zeros((dem_rows, dem_cols), dtype=np.bool_),
            bbox_min_lat=min_lat, bbox_max_lat=max_lat,
            bbox_min_lon=min_lon, bbox_max_lon=max_lon,
            mask_rows=dem_rows, mask_cols=dem_cols,
            mask_cell_size_m=config.mask_cell_size_m,
            mask_origin_lat=dem_origin_lat, mask_origin_lon=dem_origin_lon,
            features_found=0, feature_types=[],
            buffer_metres=config.buffer_metres, mode=config.mode,
            applied=False, fallback_used=True, error_message=error,
            query_time_s=query_time, parse_time_s=parse_time,
        )

    # Extract feature types for diagnostics
    feature_types = []
    for feat in features:
        if feat.waterway_type and feat.waterway_type not in feature_types:
            feature_types.append(feat.waterway_type)
        if feat.natural and feat.natural not in feature_types:
            feature_types.append(feat.natural)

    logger.info(f"Water exclusion: found {len(features)} features ({', '.join(feature_types) or 'unknown'})")

    # Create mask
    mask = _create_water_mask(
        features=features, bbox=bbox,
        dem_rows=dem_rows, dem_cols=dem_cols,
        dem_cell_size_m=dem_cell_size_m,
        dem_origin_lat=dem_origin_lat, dem_origin_lon=dem_origin_lon,
        buffer_m=config.buffer_metres,
    )

    excluded_cells = int(mask.sum())
    logger.info(f"Water exclusion: {excluded_cells} cells ({100*excluded_cells/(dem_rows*dem_cols):.1f}%) excluded")

    parse_time = time.perf_counter() - parse_start

    return WaterExclusionResult(
        mask=mask,
        bbox_min_lat=min_lat, bbox_max_lat=max_lat,
        bbox_min_lon=min_lon, bbox_max_lon=max_lon,
        mask_rows=dem_rows, mask_cols=dem_cols,
        mask_cell_size_m=config.mask_cell_size_m,
        mask_origin_lat=dem_origin_lat, mask_origin_lon=dem_origin_lon,
        features_found=len(features), feature_types=feature_types,
        buffer_metres=config.buffer_metres, mode=config.mode,
        applied=True, fallback_used=False, error_message=None,
        query_time_s=query_time, parse_time_s=parse_time,
    )


def summarise_water_exclusion(result: WaterExclusionResult) -> dict:
    """Return a compact JSON-friendly summary of a WaterExclusionResult."""
    return result.to_dict()
