"""Land Cover Service (Phase 11 - Part 1)."""

from __future__ import annotations


import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import requests

from services.overpass_client import overpass_query, OVERPASS_ENDPOINTS
from services.water_exclusion import _metres_per_degree

logger = logging.getLogger(__name__)

# Backwards-compatible alias (older tests may import this name).
OVERPASS_API_URL = OVERPASS_ENDPOINTS[0]
REQUEST_TIMEOUT_S = 20.0
MAX_BBOX_DEG = 0.5

LAND_COVER_CLASSES = [
    "built", "agricultural", "forest", "grassland",
    "wetland", "water", "bare", "unknown",
]

OSM_TAG_MAP: Dict[Tuple[str, str], str] = {
    ("landuse", "residential"):   "built",
    ("landuse", "commercial"):    "built",
    ("landuse", "industrial"):    "built",
    ("landuse", "retail"):        "built",
    ("landuse", "farmland"):      "agricultural",
    ("landuse", "orchard"):       "agricultural",
    ("landuse", "vineyard"):      "agricultural",
    ("landuse", "plant_nursery"): "agricultural",
    ("landuse", "greenhouse_horticulture"): "agricultural",
    ("landuse", "forest"):        "forest",
    ("landuse", "farmyard"):      "agricultural",
    ("landuse", "grass"):         "grassland",
    ("landuse", "meadow"):        "grassland",
    ("landuse", "pasture"):       "grassland",
    ("landuse", "basin"):         "water",
    ("landuse", "reservoir"):     "water",
    ("landuse", "water"):         "water",
    ("landuse", "quarry"):        "bare",
    ("landuse", "landfill"):      "bare",
    ("natural", "wood"):          "forest",
    ("natural", "forest"):         "forest",
    ("natural", "scrub"):          "grassland",
    ("natural", "grassland"):     "grassland",
    ("natural", "heath"):         "grassland",
    ("natural", "marsh"):         "wetland",
    ("natural", "swamp"):         "wetland",
    ("natural", "wetland"):       "wetland",
    ("natural", "bog"):           "wetland",
    ("natural", "fen"):           "wetland",
    ("natural", "water"):         "water",
    ("natural", "lake"):          "water",
    ("natural", "pond"):          "water",
    ("natural", "lagoon"):        "water",
    ("natural", "scree"):         "bare",
    ("natural", "shingle"):       "bare",
    ("natural", "rock"):          "bare",
    ("natural", "beach"):         "bare",
    ("natural", "sand"):          "bare",
    ("natural", "glacier"):        "bare",
    ("leisure", "park"):          "grassland",
    ("leisure", "garden"):        "grassland",
    ("leisure", "golf_course"):   "grassland",
    ("leisure", "pitch"):         "built",
    ("leisure", "track"):         "built",
    ("leisure", "stadium"):       "built",
    ("leisure", "common"):        "grassland",
    ("leisure", "nature_reserve"): "forest",
    ("building", "yes"):          "built",
    ("building", "house"):        "built",
    ("building", "residential"):  "built",
    ("building", "apartments"):   "built",
    ("building", "commercial"):   "built",
    ("building", "industrial"):   "built",
    ("building", "retail"):       "built",
    ("building", "school"):       "built",
    ("building", "hospital"):     "built",
    ("building", "farm_auxiliary"): "agricultural",
    ("building", "barn"):         "agricultural",
    ("building", "silo"):         "agricultural",
    ("building", "greenhouse"):   "agricultural",
    ("building", "hut"):          "unknown",
    ("building", "shed"):         "unknown",
    ("building", "garage"):       "built",
    ("building", "roof"):         "unknown",
    ("landcover", "grass"):       "grassland",
    ("landcover", "trees"):       "forest",
    ("landcover", "scrub"):       "grassland",
    ("landcover", "bare_rock"):   "bare",
}

@dataclass
class LandCoverFeature:
    osm_type: str
    osm_id: int
    geometry_type: str  # "polygon" or "linestring"
    coordinates: List[Tuple[float, float]]
    land_cover_class: str
    area_m2: float
    original_tags: Dict[str, str]


@dataclass
class LandCoverClassFraction:
    land_cover_class: str
    area_m2: float
    fraction: float
    feature_count: int


@dataclass
class LandCoverResult:
    data_available: bool = False
    source: str = "OpenStreetMap / Overpass API"
    bbox_min_lat: float = 0.0
    bbox_max_lat: float = 0.0
    bbox_min_lon: float = 0.0
    bbox_max_lon: float = 0.0
    bbox_area_m2: float = 0.0
    land_cover_classes: List[LandCoverClassFraction] = field(default_factory=list)
    features_found: int = 0
    features_mapped: int = 0
    query_time_s: float = 0.0
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    raw_features: List[LandCoverFeature] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "data_available": self.data_available,
            "source": self.source,
            "bbox": {
                "min_lat": self.bbox_min_lat,
                "max_lat": self.bbox_max_lat,
                "min_lon": self.bbox_min_lon,
                "max_lon": self.bbox_max_lon,
            },
            "bbox_area_m2": round(self.bbox_area_m2, 2),
            "land_cover_classes": [
                {
                    "land_cover_class": lc.land_cover_class,
                    "area_m2": round(lc.area_m2, 2),
                    "fraction": round(lc.fraction, 4),
                    "feature_count": lc.feature_count,
                }
                for lc in self.land_cover_classes
            ],
            "features_found": self.features_found,
            "features_mapped": self.features_mapped,
            "query_time_s": round(self.query_time_s, 3),
            "warnings": self.warnings,
            "error_message": self.error_message,
        }


def _build_overpass_query(bbox):
    min_lat, min_lon, max_lat, max_lon = bbox
    q = f'''[out:json][timeout:25];
(
  way["landuse"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["natural"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["leisure"]({min_lat},{min_lon},{max_lat},{max_lon});
  way["building"]({min_lat},{min_lon},{max_lat},{max_lon});
);
out body geom;'''
    return q.strip()


def _classify_osm_feature(tags):
    if tags.get("natural") == "water":
        return "water"
    lu = tags.get("landuse", "")
    if lu in ("reservoir", "basin", "water"):
        return "water"
    for (k, v), cls in OSM_TAG_MAP.items():
        if tags.get(k) == v:
            return cls
    if "natural" in tags:
        return "unknown"
    if "landuse" in tags:
        return "unknown"
    if "leisure" in tags:
        return "unknown"
    if "building" in tags:
        return "built"
    return "unknown"


def _polygon_area_m2(coords, center_lat):
    if len(coords) < 3:
        return 0.0
    m_per_deg_lat, m_per_deg_lon = _metres_per_degree(center_lat)
    n = len(coords)
    cx = sum(c[0] for c in coords) / n
    cy = sum(c[1] for c in coords) / n
    x = [(c[0] - cx) * m_per_deg_lon for c in coords]
    y = [(c[1] - cy) * m_per_deg_lat for c in coords]
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += x[i] * y[j] - x[j] * y[i]
    return abs(area) / 2.0


def _bbox_area_m2(bbox):
    min_lat, min_lon, max_lat, max_lon = bbox
    R = 6371000.0
    lat1, lat2 = math.radians(min_lat), math.radians(max_lat)
    lon1, lon2 = math.radians(min_lon), math.radians(max_lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R**2 * c


def _fetch_osm_features(bbox, timeout_s=REQUEST_TIMEOUT_S):
    """Fetch land-cover features from the Overpass API using the robust
    multi-endpoint client with retries and fallback.

    Returns ``(features, error)``. On any successful response,
    ``error`` is ``None``. If all endpoints fail, ``features`` is empty
    and ``error`` describes the failure across endpoints.
    """
    query = _build_overpass_query(bbox)
    data, error = overpass_query(query, timeout_s=timeout_s)
    if error is not None:
        return [], error
    return _parse_overpass_landcover(data)


def _parse_overpass_landcover(data):
    features = []
    try:
        elements = data.get("elements", [])
    except (TypeError, AttributeError):
        return [], "Invalid Overpass response format"
    if not isinstance(elements, list):
        return [], "Overpass returned non-list elements"
    for element in elements:
        osm_type = element.get("type")
        osm_id = element.get("id")
        if osm_type not in ("way", "relation"):
            continue
        geometry = element.get("geometry", [])
        if not geometry:
            continue
        coordinates = [(pt["lon"], pt["lat"]) for pt in geometry]
        if len(coordinates) < 2:
            continue
        tags = dict(element.get("tags", {}))
        is_closed = (coordinates[0] == coordinates[-1] and len(coordinates) >= 3)
        geometry_type = "polygon" if is_closed else "linestring"
        land_cover_class = _classify_osm_feature(tags)
        if geometry_type == "polygon":
            lats = [c[1] for c in coordinates]
            center_lat = sum(lats) / len(lats)
            area_m2 = _polygon_area_m2(coordinates, center_lat)
        else:
            area_m2 = 0.0
        features.append(LandCoverFeature(
            osm_type=osm_type, osm_id=osm_id,
            geometry_type=geometry_type, coordinates=coordinates,
            land_cover_class=land_cover_class, area_m2=area_m2,
            original_tags=tags,
        ))
    return features, None


def _compute_fractions(features, bbox, catchment_area_m2=None):
    min_lat, min_lon, max_lat, max_lon = bbox
    center_lat = (min_lat + max_lat) / 2
    m_per_deg_lat, m_per_deg_lon = _metres_per_degree(center_lat)
    bbox_area = (max_lat - min_lat) * m_per_deg_lat * (max_lon - min_lon) * m_per_deg_lon * math.cos(math.radians(center_lat))
    denom = catchment_area_m2 if catchment_area_m2 and catchment_area_m2 > 0 else bbox_area
    class_area: Dict[str, float] = {c: 0.0 for c in LAND_COVER_CLASSES}
    class_count: Dict[str, int] = {c: 0 for c in LAND_COVER_CLASSES}
    for feat in features:
        if feat.geometry_type == "polygon" and feat.area_m2 > 0:
            cls = feat.land_cover_class
            class_area[cls] += feat.area_m2
            class_count[cls] += 1
    fractions = []
    for cls in LAND_COVER_CLASSES:
        if class_count[cls] > 0:
            fraction = class_area[cls] / denom
            fractions.append(LandCoverClassFraction(
                land_cover_class=cls, area_m2=class_area[cls],
                fraction=min(fraction, 1.0), feature_count=class_count[cls],
            ))
    return fractions


def get_land_cover(bbox, catchment_area_m2=None):
    """Fetch and analyse land cover for a catchment bounding box.

    Parameters
    ----------
    bbox : (min_lat, min_lon, max_lat, max_lon)
    catchment_area_m2 : float, optional
        If provided, used as the denominator for area fractions instead of
        the full bbox area.

    Returns
    -------
    LandCoverResult
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    bbox_size = max(max_lat - min_lat, max_lon - min_lon)
    if bbox_size > MAX_BBOX_DEG:
        logger.warning(f"Land cover bbox {bbox_size:.3f} deg > {MAX_BBOX_DEG}. Clipping.")
        if max_lat - min_lat > MAX_BBOX_DEG:
            c = (min_lat + max_lat) / 2
            min_lat = c - MAX_BBOX_DEG / 2
            max_lat = c + MAX_BBOX_DEG / 2
        if max_lon - min_lon > MAX_BBOX_DEG:
            c = (min_lon + max_lon) / 2
            min_lon = c - MAX_BBOX_DEG / 2
            max_lon = c + MAX_BBOX_DEG / 2
        bbox = (min_lat, min_lon, max_lat, max_lon)
    t0 = time.perf_counter()
    features, error = _fetch_osm_features(bbox)
    query_time = time.perf_counter() - t0
    if error:
        logger.warning(f"Land cover fetch failed: {error}")
        return LandCoverResult(
            bbox_min_lat=min_lat, bbox_max_lat=max_lat,
            bbox_min_lon=min_lon, bbox_max_lon=max_lon,
            query_time_s=query_time,
            warnings=["Land cover data could not be retrieved from OSM."],
            error_message=error,
        )
    bbox_area_m2 = _bbox_area_m2(bbox)
    mapped_count = sum(1 for f in features if f.land_cover_class != "unknown")
    fractions = _compute_fractions(features, bbox, catchment_area_m2)
    denom = catchment_area_m2 if catchment_area_m2 and catchment_area_m2 > 0 else bbox_area_m2
    warnings = []
    if not features:
        warnings.append(
            "No OSM land-cover features found in the bounding box. "
            "This may indicate sparse OSM coverage or a remote catchment."
        )
    building_count = sum(
        1 for f in features if f.original_tags.get("building") and f.land_cover_class == "built"
    )
    if building_count > 0:
        warnings.append(
            f"{building_count} OSM building footprints are included in the built class. "
            "Building footprints may underrepresent the true impervious fraction."
        )
    if mapped_count == 0 and features:
        warnings.append(
            "All OSM features were classified as unknown. "
            "Land cover fractions are set to 0."
        )
    return LandCoverResult(
        data_available=mapped_count > 0,
        bbox_min_lat=min_lat, bbox_max_lat=max_lat,
        bbox_min_lon=min_lon, bbox_max_lon=max_lon,
        bbox_area_m2=denom,
        land_cover_classes=fractions,
        features_found=len(features),
        features_mapped=mapped_count,
        query_time_s=query_time,
        warnings=warnings,
        raw_features=features,
    )


def summarise_land_cover(result):
    """Return a compact JSON-friendly summary for pipeline integration."""
    return result.to_dict()
