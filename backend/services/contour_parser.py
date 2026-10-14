
"""
Contour parser service for KML and KMZ files.

Phase 7 improvements:
- Robust elevation extraction from multiple sources
- Support for MultiLineString and nested MultiGeometry
- Improved KMZ selection strategy
"""
import io
import logging
import math
import re
import zipfile
from typing import List, Optional, Tuple
from xml.etree import ElementTree as ET

from models import ContourPoint, ContourLine

logger = logging.getLogger(__name__)

KML_NS_URI = "http://www.opengis.net/kml/2.2"

ELEVATION_FIELD_NAMES = frozenset([
    "elevation", "elev", "height", "contour", "contour_elevation",
    "z", "alt", "altitude", "level", "contour_level"
])

DESCRIPTION_ELEVATION_PATTERNS = [
    re.compile(r"(?:elevation|elev|height|contour|h)\s*[:=]?\s*([+-]?\d+(?:\.\d+)?)\s*[mM]?", re.IGNORECASE),
    re.compile(r"level\s*[:=]?\s*([+-]?\d+(?:\.\d+)?)\s*[mM]?", re.IGNORECASE),
]


class ContourParserError(Exception):
    pass


def _is_numeric_token(s: str) -> bool:
    if s is None:
        return False
    s = s.strip()
    if not s:
        return False
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def _is_valid_coordinate(lon: float, lat: float) -> bool:
    if not math.isfinite(lon) or not math.isfinite(lat):
        return False
    if lon < -180.0 or lon > 180.0:
        return False
    if lat < -90.0 or lat > 90.0:
        return False
    return True


def _is_suspicious_numeric_value(value_str: str) -> bool:
    if not value_str:
        return True
    if re.match(r"^\d{4}$", value_str.strip()):
        return True
    try:
        val = float(value_str)
        if val > 100000 or val < -1000:
            return True
    except (ValueError, TypeError):
        return True
    return False


def _parse_elevation_from_name(name: Optional[str]) -> Optional[float]:
    if not name:
        return None
    name = name.strip()
    for pattern in DESCRIPTION_ELEVATION_PATTERNS:
        match = pattern.search(name)
        if match:
            value_str = match.group(1)
            if not _is_suspicious_numeric_value(value_str):
                try:
                    return float(value_str)
                except ValueError:
                    pass
    for token in re.split(r"[\s_]+", name):
        cleaned = token.rstrip("mM")
        if _is_numeric_token(cleaned) and not _is_suspicious_numeric_value(cleaned):
            try:
                return float(cleaned)
            except ValueError:
                continue
    return None


def _parse_elevation_from_extended_data(placemark: ET.Element) -> Optional[float]:
    tag_ns = f"{{{KML_NS_URI}}}"
    for data_elem in placemark.iter(f"{tag_ns}Data"):
        name_attr = data_elem.get("name", "")
        if name_attr.lower() in ELEVATION_FIELD_NAMES:
            value_elem = data_elem.find(f"{tag_ns}value")
            if value_elem is not None and value_elem.text:
                value_str = value_elem.text.strip()
                if _is_numeric_token(value_str) and not _is_suspicious_numeric_value(value_str):
                    try:
                        return float(value_str)
                    except ValueError:
                        pass
    for schema_data in placemark.iter(f"{tag_ns}SchemaData"):
        for simple_data in schema_data:
            name_attr = simple_data.get("name", "")
            if name_attr.lower() in ELEVATION_FIELD_NAMES:
                if simple_data.text:
                    value_str = simple_data.text.strip()
                    if _is_numeric_token(value_str) and not _is_suspicious_numeric_value(value_str):
                        try:
                            return float(value_str)
                        except ValueError:
                            pass
    return None


def _parse_elevation_from_description(placemark: ET.Element) -> Optional[float]:
    tag_ns = f"{{{KML_NS_URI}}}"
    desc_elem = placemark.find(f"{tag_ns}description")
    if desc_elem is None or not desc_elem.text:
        return None
    desc_text = desc_elem.text.strip()
    for pattern in DESCRIPTION_ELEVATION_PATTERNS:
        match = pattern.search(desc_text)
        if match:
            value_str = match.group(1)
            if not _is_suspicious_numeric_value(value_str):
                try:
                    return float(value_str)
                except ValueError:
                    pass
    return None


def _get_median_value(values: List[float]) -> Optional[float]:
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0


def _parse_kml_coordinates(coord_text: str, include_z: bool = False) -> List[Tuple[float, float, Optional[float]]]:
    if not coord_text:
        return []
    points = []
    for raw in coord_text.split():
        raw = raw.strip()
        if not raw:
            continue
        parts = raw.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except (ValueError, IndexError):
            continue
        z = None
        if include_z and len(parts) >= 3:
            try:
                z = float(parts[2])
                if not math.isfinite(z):
                    z = None
            except (ValueError, IndexError):
                pass
        points.append((lon, lat, z))
    return points


def _extract_all_linestrings(element: ET.Element) -> List[ET.Element]:
    tag_ns = f"{{{KML_NS_URI}}}"
    linestrings = []
    for ls in element.iter(f"{tag_ns}LineString"):
        linestrings.append(ls)
    for mls in element.iter(f"{tag_ns}MultiLineString"):
        for ls in mls:
            if "LineString" in ls.tag:
                linestrings.append(ls)
    for mg in element.iter(f"{tag_ns}MultiGeometry"):
        for child in mg:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child_tag == "LineString":
                linestrings.append(child)
            elif child_tag == "MultiLineString":
                for ls in child:
                    if "LineString" in ls.tag:
                        linestrings.append(ls)
            elif child_tag == "MultiGeometry":
                nested_ls = _extract_all_linestrings(child)
                linestrings.extend(nested_ls)
    return linestrings


def _extract_kml_from_kmz(data: bytes) -> bytes:
    """Extract KML from KMZ with deterministic selection."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            kml_files = [n for n in zf.namelist() 
                        if n.lower().endswith(".kml") and not n.startswith("__MACOSX")]
            if not kml_files:
                raise ContourParserError("KMZ archive contains no KML document.")
            def normalize_path(name: str) -> str:
                return name.lower().replace("\\", "/").split("/")[-1]
            doc_kml_matches = [n for n in kml_files if normalize_path(n) == "doc.kml"]
            if doc_kml_matches:
                return zf.read(doc_kml_matches[0])
            root_kmls = [n for n in kml_files if "/" not in n and "\\" not in n]
            if root_kmls:
                selected = sorted(root_kmls, key=lambda x: normalize_path(x))[0]
                return zf.read(selected)
            selected = sorted(kml_files, key=lambda x: normalize_path(x))[0]
            return zf.read(selected)
    except zipfile.BadZipFile as exc:
        raise ContourParserError(f"Invalid KMZ archive: {exc}") from exc
    except KeyError as exc:
        raise ContourParserError(f"KML file not found in KMZ: {exc}") from exc


def _parse_kml_bytes(kml_bytes: bytes) -> List[ContourLine]:
    """Parse KML bytes and return list of ContourLine objects."""
    try:
        root = ET.fromstring(kml_bytes)
    except ET.ParseError as exc:
        raise ContourParserError(f"Invalid KML XML: {exc}") from exc
    contours = []
    seen_coords = set()
    for placemark in root.iter(f"{{{KML_NS_URI}}}Placemark"):
        elevation = None
        try:
            elevation = _parse_elevation_from_extended_data(placemark)
            if elevation is None:
                elevation = _parse_elevation_from_description(placemark)
            if elevation is None:
                name_elem = placemark.find(f"{{{KML_NS_URI}}}name")
                if name_elem is not None and name_elem.text:
                    elevation = _parse_elevation_from_name(name_elem.text)
            if elevation is None:
                continue
            linestrings = _extract_all_linestrings(placemark)
            if not linestrings:
                continue
            all_points = []
            for linestring in linestrings:
                coords_elem = linestring.find(f"{{{KML_NS_URI}}}coordinates")
                if coords_elem is None or not coords_elem.text:
                    continue
                raw_points = _parse_kml_coordinates(coords_elem.text, include_z=True)
                for lon, lat, z in raw_points:
                    coord_key = (round(lon, 6), round(lat, 6))
                    if coord_key in seen_coords:
                        continue
                    seen_coords.add(coord_key)
                    if not _is_valid_coordinate(lon, lat):
                        continue
                    all_points.append((lon, lat))
            if len(all_points) < 2:
                continue
            points = [
                ContourPoint(lon=lon, lat=lat, elevation=elevation)
                for lon, lat in all_points
            ]
            contours.append(ContourLine(elevation=elevation, points=points))
        except Exception:
            continue
    if not contours:
        raise ContourParserError("No valid contour lines found in KML.")
    return contours


def parse_contour_file(filename: str, data: bytes) -> List[ContourLine]:
    """Public entry point for parsing KML/KMZ files."""
    if not data:
        raise ContourParserError("Uploaded file is empty.")
    if not filename:
        raise ContourParserError("Uploaded file has no filename.")
    name_lower = filename.lower()
    if name_lower.endswith(".kmz"):
        kml_bytes = _extract_kml_from_kmz(data)
        return _parse_kml_bytes(kml_bytes)
    if name_lower.endswith(".kml"):
        return _parse_kml_bytes(data)
    raise ContourParserError(
        f"Unsupported file type for '{filename}'. Expected .kml or .kmz."
    )
