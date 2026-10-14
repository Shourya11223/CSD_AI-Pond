"""
DEM Acquisition Service (Phase 5).

Downloads Digital Elevation Models (DEM) from OpenTopography's global
DEM API for a specified geographic bounding box.

Environment Variables
--------------------
OPENTOPOGRAPHY_API_KEY
    Required API key for OpenTopography.
    Obtain from: https://opentopography.org/

Supported DEM Types
-------------------
- COP30: Copernicus GLO-30 (30m resolution, global coverage)
- COP90: Copernicus GLO-90 (90m resolution, global coverage)
- SRTMGL1: SRTM GL1 (30m resolution, limited coverage)
- SRTMGL3: SRTM GL3 (90m resolution, limited coverage)
- SRTMGL1_E: SRTM GL1 Ellipsoidal (30m resolution)
- AW3D30: ALOS World 3D (30m resolution, limited coverage)
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Attempt to load .env from the backend directory so that the API key
# is available when this module is imported directly (e.g. in tests or
# standalone scripts) without going through main.py.
# If python-dotenv is not installed, the variable must be set in the shell.
try:
    from dotenv import load_dotenv

    _backend_root = Path(__file__).resolve().parent.parent
    _env_path = _backend_root / ".env"
    if _env_path.is_file():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

OPENTOPOGRAPHY_API_URL = "https://portal.opentopography.org/API/globaldem"
REQUEST_TIMEOUT_S = 120.0

# GeoTIFF file signatures (magic bytes).
# TIFF/GeoTIFF files start with either:
#   - "II" (0x49, 0x49) = little-endian byte order
#   - "MM" (0x4D, 0x4D) = big-endian byte order
# Followed by TIFF magic number 42 (0x2A00 or 0x002A).
_GEOTIFF_LITTLE_ENDIAN = b"II*\x00"
_GEOTIFF_BIG_ENDIAN = b"MM\x00*"


def _is_geotiff_binary(content: bytes) -> bool:
    """
    Check whether the first few bytes of `content` look like a valid
    GeoTIFF file signature.

    We accept the standard TIFF/GeoTIFF header (8 bytes) to avoid
    accepting arbitrary binary data as a DEM.
    """
    if len(content) < 8:
        return False
    return (
        content.startswith(_GEOTIFF_LITTLE_ENDIAN)
        or content.startswith(_GEOTIFF_BIG_ENDIAN)
    )


SUPPORTED_DEM_TYPES = {
    "COP30", "COP90", "SRTMGL1", "SRTMGL3", "SRTMGL1_E", "AW3D30",
}

DEFAULT_DEM_TYPE = "COP30"

MIN_LAT, MAX_LAT = -90.0, 90.0
MIN_LON, MAX_LON = -180.0, 180.0
METRES_PER_DEG_LAT = 111_320.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DEMAcquisitionError(Exception):
    """Raised when DEM acquisition fails."""
    pass


class DEMValidationError(DEMAcquisitionError):
    """Raised when input parameters are invalid."""
    pass


class DEMAPIError(DEMAcquisitionError):
    """Raised when the OpenTopography API returns an error."""
    pass


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class DEMResult:
    """Result of a successful DEM download."""
    file_path: str
    dem_type: str
    bbox: tuple  # (south, north, west, east)
    metadata: dict
    is_temp: bool = True

    @property
    def south(self) -> float:
        return self.bbox[0]

    @property
    def north(self) -> float:
        return self.bbox[1]

    @property
    def west(self) -> float:
        return self.bbox[2]

    @property
    def east(self) -> float:
        return self.bbox[3]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_bounds(
    south: float, north: float, west: float, east: float,
) -> None:
    if not (MIN_LAT <= south <= MAX_LAT):
        raise DEMValidationError(
            f"south must be between {MIN_LAT} and {MAX_LAT}, got {south}."
        )
    if not (MIN_LAT <= north <= MAX_LAT):
        raise DEMValidationError(
            f"north must be between {MIN_LAT} and {MAX_LAT}, got {north}."
        )
    if not (MIN_LON <= west <= MAX_LON):
        raise DEMValidationError(
            f"west must be between {MIN_LON} and {MAX_LON}, got {west}."
        )
    if not (MIN_LON <= east <= MAX_LON):
        raise DEMValidationError(
            f"east must be between {MIN_LON} and {MAX_LON}, got {east}."
        )
    if south >= north:
        raise DEMValidationError(
            f"south ({south}) must be less than north ({north})."
        )
    if west >= east:
        raise DEMValidationError(
            f"west ({west}) must be less than east ({east})."
        )


def _validate_dem_type(dem_type: str) -> None:
    if dem_type not in SUPPORTED_DEM_TYPES:
        raise DEMValidationError(
            'Unsupported DEM type "{0}". Supported types: {1}'.format(
                dem_type, sorted(SUPPORTED_DEM_TYPES)
            )
        )


def _get_api_key() -> str:
    key = os.environ.get("OPENTOPOGRAPHY_API_KEY", "").strip()
    if not key:
        raise DEMValidationError(
            "OpenTopography API key not found. "
            "Set the OPENTOPOGRAPHY_API_KEY environment variable."
        )
    return key


# ---------------------------------------------------------------------------
# Core download function
# ---------------------------------------------------------------------------


def download_dem(
    south: float,
    north: float,
    west: float,
    east: float,
    dem_type: str = DEFAULT_DEM_TYPE,
    output_path: Optional[str] = None,
) -> DEMResult:
    """
    Download a DEM from OpenTopography for the specified bounding box.

    Parameters
    ----------
    south, north, west, east : float
        Geographic bounding box boundaries in degrees.
    dem_type : str, optional
        DEM type to download. Default is "COP30".
    output_path : str, optional
        Path to save the DEM. If not provided, a temporary file is created.

    Returns
    -------
    DEMResult
        Path, bounding box, and metadata for the downloaded DEM.

    Raises
    ------
    DEMValidationError
        If input parameters are invalid.
    DEMAPIError
        If the OpenTopography API returns an error.
    DEMAcquisitionError
        For network errors or other failures.
    """
    _validate_bounds(south, north, west, east)
    _validate_dem_type(dem_type)
    api_key = _get_api_key()

    if output_path is None:
        fd, temp_path = tempfile.mkstemp(suffix=".tif", prefix="dem_")
        os.close(fd)
        file_path = temp_path
        is_temp = True
    else:
        file_path = output_path
        is_temp = False

    logger.info(
        "Downloading DEM: type=%s, bbox=(%.4f, %.4f, %.4f, %.4f), output=%s",
        dem_type, south, north, west, east, file_path,
    )

    params = {
        "demtype": dem_type,
        "south": south,
        "north": north,
        "west": west,
        "east": east,
        "outputFormat": "GTiff",
        "API_Key": api_key,
    }

    try:
        response = requests.get(
            OPENTOPOGRAPHY_API_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_S,
            stream=True,
        )
    except requests.Timeout as exc:
        raise DEMAcquisitionError(
            f"Request timed out after {REQUEST_TIMEOUT_S}s."
        ) from exc
    except requests.ConnectionError as exc:
        raise DEMAcquisitionError(
            f"Network connection failed: {exc}"
        ) from exc
    except requests.RequestException as exc:
        raise DEMAcquisitionError(
            f"Request failed: {exc}"
        ) from exc

    if response.status_code == 401:
        raise DEMAPIError(
            "OpenTopography API authentication failed. "
            "Check that your OPENTOPOGRAPHY_API_KEY is valid."
        )
    if response.status_code == 429:
        raise DEMAPIError(
            "OpenTopography API rate limit exceeded. "
            "Wait before making another request."
        )
    if response.status_code != 200:
        raise DEMAPIError(
            f"OpenTopography API returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    content_type = response.headers.get("Content-Type", "")
    # Accept both image/tiff, application/octet-stream (if binary is valid GeoTIFF)
    if content_type.lower().startswith("image/tiff") or content_type.lower().startswith("image/geotiff"):
        # Standard GeoTIFF content type - validate binary content
        if len(response.content) < 8:
            raise DEMAPIError("OpenTopography API returned a response too small to be a valid GeoTIFF.")
        if not _is_geotiff_binary(response.content):
            raise DEMAPIError("OpenTopography API returned a response that does not contain a valid GeoTIFF header.")
    elif content_type.lower() == "application/octet-stream":
        # Some OpenTopography versions return octet-stream for GeoTIFF files.
        # We must validate that the binary payload is actually a GeoTIFF.
        if len(response.content) < 8:
            raise DEMAPIError("OpenTopography API returned an empty or invalid response.")
        if not _is_geotiff_binary(response.content):
            raise DEMAPIError("OpenTopography API returned unexpected binary data that is not a valid GeoTIFF.")
    elif "tiff" not in content_type.lower() and "geotiff" not in content_type.lower():
        if "application/json" in content_type or response.text.strip().startswith("{"):
            try:
                error_data = response.json()
                error_msg = error_data.get("error", error_data.get("message", response.text[:500]))
                raise DEMAPIError(f"OpenTopography API error: {error_msg}")
            except ValueError:
                pass
        raise DEMAPIError(
            'Unexpected content type "{0}". Expected a GeoTIFF response.'.format(content_type)
        )

    if len(response.content) == 0:
        raise DEMAPIError("OpenTopography API returned an empty response.")

    try:
        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=65536):
                f.write(chunk)
    except IOError as exc:
        raise DEMAcquisitionError(
            f"Failed to write DEM file to {file_path}: {exc}"
        ) from exc

    file_size = Path(file_path).stat().st_size
    if file_size == 0:
        raise DEMAPIError("Downloaded DEM file is empty.")

    logger.info(
        "DEM downloaded successfully: %s (%.2f MB)",
        file_path, file_size / (1024 * 1024),
    )

    return DEMResult(
        file_path=file_path,
        dem_type=dem_type,
        bbox=(south, north, west, east),
        metadata={
            "content_type": content_type,
            "file_size_bytes": file_size,
            "response_headers": dict(response.headers),
        },
        is_temp=is_temp,
    )


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------


def cleanup_dem(result: DEMResult) -> None:
    """Remove a temporary DEM file if it exists. Safe to call on any result."""
    if result.is_temp and result.file_path:
        try:
            Path(result.file_path).unlink(missing_ok=True)
            logger.debug("Cleaned up temporary DEM: %s", result.file_path)
        except OSError as exc:
            logger.warning(
                "Failed to clean up temporary DEM %s: %s",
                result.file_path, exc,
            )


# ---------------------------------------------------------------------------
# Radius-to-bounds converter
# ---------------------------------------------------------------------------


def radius_to_bounds(
    latitude: float,
    longitude: float,
    radius_km: float,
) -> tuple[float, float, float, float]:
    """
    Convert a center point and radius to a geographic bounding box.

    Uses a simple equirectangular approximation suitable for small
    areas (up to ~50 km radius).

    Returns
    -------
    tuple
        (south, north, west, east) bounding box in degrees.

    Raises
    ------
    DEMValidationError
        If inputs are out of valid range or radius is not positive.
    """
    if not (MIN_LAT <= latitude <= MAX_LAT):
        raise DEMValidationError(
            f"latitude must be between {MIN_LAT} and {MAX_LAT}, got {latitude}."
        )
    if not (MIN_LON <= longitude <= MAX_LON):
        raise DEMValidationError(
            f"longitude must be between {MIN_LON} and {MAX_LON}, got {longitude}."
        )
    if radius_km <= 0:
        raise DEMValidationError(
            f"radius_km must be positive, got {radius_km}."
        )

    m_per_deg_lon = METRES_PER_DEG_LAT * abs(math.cos(math.radians(latitude)))

    delta_lat = (radius_km * 1000.0) / METRES_PER_DEG_LAT
    delta_lon = (radius_km * 1000.0) / m_per_deg_lon

    south = max(latitude - delta_lat, MIN_LAT)
    north = min(latitude + delta_lat, MAX_LAT)
    west = max(longitude - delta_lon, MIN_LON)
    east = min(longitude + delta_lon, MAX_LON)

    return (south, north, west, east)