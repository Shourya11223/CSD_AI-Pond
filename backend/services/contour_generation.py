"""
Contour Generation Service (Phase 5).

Generates contour lines from a Digital Elevation Model (DEM) using
GDAL's ``gdal_contour`` command-line tool, and converts the resulting
GeoJSON features directly into the project's existing ``ContourLine``
representation.

Pipeline
--------
1. Validate the DEM file exists and ``gdal_contour`` is available.
2. Run ``gdal_contour`` with the configured interval to produce a
   temporary GeoJSON file.
3. Read the GeoJSON features and convert LineString / MultiLineString
   geometries into ``ContourLine`` objects (each point tagged with
   the elevation attribute that ``gdal_contour -a elevation`` writes).

This service produces the same in-memory representation as
``services.contour_parser.parse_contour_file`` so downstream stages
(terrain model, hydrology, pond selection, catchment, capacity) can
use the generated contours without any code changes.

Notes
-----
* We deliberately avoid the round-trip ``DEM -> GeoJSON -> KML -> KML
  parser`` because it is wasteful, slower, and loses precision.
* ``gdal_contour`` is expected to be on ``PATH`` (e.g.
  ``/usr/bin/gdal_contour``).  On Debian/Ubuntu it is provided by the
  ``gdal-bin`` package.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from models import ContourPoint, ContourLine

logger = logging.getLogger(__name__)

GDAL_CONTOUR_CMD = "gdal_contour"

# Default contour interval (metres).  Matches Map_generator/new.py.
DEFAULT_CONTOUR_INTERVAL_M = 1.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ContourGenerationError(Exception):
    """Raised when contour generation fails."""
    pass


class ContourValidationError(ContourGenerationError):
    """Raised when input parameters are invalid."""
    pass


class GDALNotFoundError(ContourGenerationError):
    """Raised when ``gdal_contour`` is not installed on PATH."""
    pass


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class ContourGenerationResult:
    """Result of contour generation."""
    contours: List[ContourLine]
    dem_path: str
    output_geojson_path: str
    interval_m: float
    num_features: int

    @property
    def contour_count(self) -> int:
        return len(self.contours)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_interval(interval_m: float) -> None:
    if interval_m <= 0:
        raise ContourValidationError(
            "Contour interval must be positive, got {0}.".format(interval_m)
        )


def _validate_dem(dem_path: str) -> None:
    if not dem_path:
        raise ContourValidationError("DEM file path is empty.")
    if not os.path.exists(dem_path):
        raise ContourValidationError(
            "DEM file does not exist: {0}".format(dem_path)
        )
    if not os.path.isfile(dem_path):
        raise ContourValidationError(
            "DEM path is not a file: {0}".format(dem_path)
        )


def _check_gdal_contour() -> str:
    """Verify gdal_contour is available and return its resolved path."""
    found = shutil.which(GDAL_CONTOUR_CMD)
    if not found:
        raise GDALNotFoundError(
            "gdal_contour not found on PATH. Install GDAL tools "
            "(e.g. 'sudo apt install gdal-bin' on Debian/Ubuntu)."
        )
    return found


# ---------------------------------------------------------------------------
# GeoJSON -> ContourLine conversion
# ---------------------------------------------------------------------------


def _parse_geojson_features(geojson_data: dict) -> List[ContourLine]:
    """
    Convert GeoJSON features produced by gdal_contour into ContourLine objects.

    Each feature's geometry can be:
      * LineString         -> one ContourLine
      * MultiLineString    -> one ContourLine per line part

    The elevation value is read from the feature property "elevation"
    (which is what ``gdal_contour -a elevation`` writes).
    """
    contours: List[ContourLine] = []
    features = geojson_data.get("features", []) or []

    for feature in features:
        props = feature.get("properties", {}) or {}
        elev_raw = props.get("elevation")
        if elev_raw is None:
            logger.debug("Feature without elevation property; skipping.")
            continue
        try:
            elevation = float(elev_raw)
        except (TypeError, ValueError):
            logger.debug("Feature with non-numeric elevation %r; skipping.", elev_raw)
            continue

        geometry = feature.get("geometry") or {}
        geom_type = geometry.get("type")
        coords = geometry.get("coordinates") or []

        if geom_type == "LineString":
            contour = _build_contour(elevation, coords)
            if contour is not None:
                contours.append(contour)
        elif geom_type == "MultiLineString":
            for line_coords in coords:
                contour = _build_contour(elevation, line_coords)
                if contour is not None:
                    contours.append(contour)
        else:
            logger.debug("Unsupported geometry type %r; skipping.", geom_type)

    return contours


def _build_contour(elevation: float, coords: list) -> Optional[ContourLine]:
    """Build a ContourLine from a list of [lon, lat] (or [lon, lat, alt]) tuples."""
    points: List[ContourPoint] = []
    for raw in coords:
        if not isinstance(raw, (list, tuple)) or len(raw) < 2:
            continue
        try:
            lon = float(raw[0])
            lat = float(raw[1])
        except (TypeError, ValueError):
            continue
        points.append(ContourPoint(lon=lon, lat=lat, elevation=elevation))
    if not points:
        return None
    return ContourLine(elevation=elevation, points=points)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_contours(
    dem_path: str,
    interval_m: float = DEFAULT_CONTOUR_INTERVAL_M,
    output_geojson_path: Optional[str] = None,
    keep_geojson: bool = False,
) -> ContourGenerationResult:
    """
    Generate contour lines from a DEM file using ``gdal_contour``.

    Parameters
    ----------
    dem_path : str
        Path to the input DEM file (GeoTIFF or any GDAL-supported raster).
    interval_m : float, optional
        Contour interval in metres.  Must be > 0.  Default is 1.0.
    output_geojson_path : str, optional
        Path to write the intermediate GeoJSON file.  If not provided,
        a temporary file is created (recommended for single-request use).
    keep_geojson : bool, optional
        If True and ``output_geojson_path`` is None, the temporary
        GeoJSON file is NOT deleted after parsing.  Default is False.

    Returns
    -------
    ContourGenerationResult
        Contains the parsed ``ContourLine`` list, source DEM path,
        GeoJSON path, interval, and feature count.

    Raises
    ------
    ContourValidationError
        If ``dem_path`` is missing/invalid or ``interval_m`` is not positive.
    GDALNotFoundError
        If the ``gdal_contour`` executable is not available.
    ContourGenerationError
        If GDAL fails, the GeoJSON file is not created, or parsing fails.
    """
    _validate_interval(interval_m)
    _validate_dem(dem_path)
    gdal_path = _check_gdal_contour()

    if output_geojson_path is None:
        # Reserve a unique path. ``tempfile.mkstemp`` is atomic and unique, but
        # it also *creates* the file as a side effect. GDAL's GeoJSON driver
        # refuses to overwrite an existing file (it returns error 6: "The
        # GeoJSON driver does not overwrite existing files."), so we must
        # remove the 0-byte file mkstemp created before invoking gdal_contour.
        fd, temp_path = tempfile.mkstemp(suffix=".geojson", prefix="contours_")
        os.close(fd)
        _safe_unlink(temp_path)
        geojson_path = temp_path
        is_temp = True
    else:
        geojson_path = output_geojson_path
        is_temp = False
        # GDAL's GeoJSON driver does not support overwriting existing files
        # (see GDAL error 6: "The GeoJSON driver does not overwrite existing
        # files."). Remove any pre-existing file at the caller's output path
        # to ensure gdal_contour can write successfully. This only affects the
        # file at the path the caller asked us to write to.
        _safe_unlink(geojson_path)

    logger.info(
        "Generating contours: dem=%s, interval=%sm, output=%s",
        dem_path, interval_m, geojson_path,
    )

    command = [
        gdal_path,
        "-a", "elevation",
        "-i", str(interval_m),
        "-f", "GeoJSON",
        dem_path,
        geojson_path,
    ]

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        if is_temp:
            _safe_unlink(geojson_path)
        raise ContourGenerationError(
            "gdal_contour timed out after 300s."
        ) from exc
    except OSError as exc:
        if is_temp:
            _safe_unlink(geojson_path)
        raise ContourGenerationError(
            "Failed to invoke gdal_contour: {0}".format(exc)
        ) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "")[:1000]
        if is_temp:
            _safe_unlink(geojson_path)
        raise ContourGenerationError(
            "gdal_contour failed with code {0}: {1}".format(
                result.returncode, stderr
            )
        )

    if not os.path.exists(geojson_path):
        raise ContourGenerationError(
            "gdal_contour did not produce output file: {0}".format(geojson_path)
        )

    try:
        with open(geojson_path, "r", encoding="utf-8") as f:
            geojson_data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        if is_temp:
            _safe_unlink(geojson_path)
        raise ContourGenerationError(
            "Failed to read GeoJSON output: {0}".format(exc)
        ) from exc

    num_features = len(geojson_data.get("features", []) or [])
    contours = _parse_geojson_features(geojson_data)

    if not contours:
        if is_temp:
            _safe_unlink(geojson_path)
        raise ContourGenerationError(
            "No valid contours were generated. "
            "The DEM may be flat or the interval too small."
        )

    logger.info(
        "Generated %d contour lines from %d GeoJSON features.",
        len(contours), num_features,
    )

    if is_temp and not keep_geojson:
        _safe_unlink(geojson_path)
        geojson_path_return = ""
    else:
        geojson_path_return = geojson_path

    return ContourGenerationResult(
        contours=contours,
        dem_path=dem_path,
        output_geojson_path=geojson_path_return,
        interval_m=interval_m,
        num_features=num_features,
    )


def cleanup_contour_result(result: ContourGenerationResult) -> None:
    """Remove any temporary files associated with this contour result."""
    if result.output_geojson_path:
        _safe_unlink(result.output_geojson_path)


def _safe_unlink(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("Failed to remove %s: %s", path, exc)