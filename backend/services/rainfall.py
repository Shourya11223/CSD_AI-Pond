"""
Rainfall Data Service (Phase 8).

Retrieves historical/climatological rainfall data based on geographic coordinates.
Designed with a provider abstraction to support multiple data sources.

Primary Provider: Open-Meteo Climate API
    - Historical precipitation data (ERA5-Land reanalysis)
    - Global coverage, 0.1 degree resolution
    - No API key required
    - Data includes monthly precipitation totals and statistics

Design Principles
----------------
1. All external API calls are made through this service.
2. The frontend MUST NOT call external rainfall APIs directly.
3. API credentials are obtained from environment variables only.
4. Responses are normalized regardless of the underlying provider.
5. Provider failures result in a structured unavailable response, not crashes.

Note on Data Interpretation
---------------------------
- Current implementation provides POINT-based rainfall estimates.
- Phase 9 (runoff) should consider spatial averaging over catchment polygons.
- This data represents HISTORICAL/CLIMATOLOGICAL rainfall, not design rainfall.

Environment Variables
---------------------
None required for Open-Meteo (no API key needed).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Provider configuration
# -----------------------------------------------------------------------

OPEN_METEO_CLIMATE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Request timeout in seconds
REQUEST_TIMEOUT_S = 30.0

# Cache TTL in seconds (6 hours for historical rainfall data)
CACHE_TTL_S = 6 * 60 * 60

# Valid coordinate ranges
MIN_LAT, MAX_LAT = -90.0, 90.0
MIN_LON, MAX_LON = -180.0, 180.0


# -----------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------


class RainfallError(Exception):
    """Base exception for rainfall service errors."""
    pass


class RainfallValidationError(RainfallError):
    """Raised when input coordinates are invalid."""
    pass


class RainfallProviderError(RainfallError):
    """Raised when the external provider returns an error."""
    pass


class RainfallDataUnavailable(RainfallError):
    """Raised when rainfall data is not available for the requested location."""
    pass


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RainfallResult:
    """
    Normalized rainfall data result.

    Attributes
    ----------
    source : str
        Identifier of the data provider (e.g., "Open-Meteo-ERA5").
    latitude : float
        Latitude of the lookup point.
    longitude : float
        Longitude of the lookup point.
    data_period_start : Optional[str]
        ISO 8601 date string for the start of the data period.
    data_period_end : Optional[str]
        ISO 8601 date string for the end of the data period.
    annual_rainfall_mm : Optional[float]
        Total annual rainfall in millimeters (mean annual precipitation).
    monthly_rainfall_mm : Optional[Dict[str, float]]
        Monthly rainfall totals in mm, keyed by month number (1-12).
    rainfall_data_available : bool
        True if valid rainfall data was obtained.
    data_resolution : Optional[str]
        Spatial resolution of the data.
    data_quality : str
        Quality classification.
    fetched_at : str
        ISO 8601 timestamp when data was fetched.
    error_message : Optional[str]
        Error description if rainfall_data_available is False.
    rainy_days : Optional[int]
        Approximate number of rainy days per year.
    max_daily_rainfall_mm : Optional[float]
        Maximum observed daily rainfall in mm.
    number_of_observations : Optional[int]
        Number of observations used to compute statistics.
    lookup_method : str
        How the lookup location was determined.
    """
    source: str
    latitude: float
    longitude: float
    data_period_start: Optional[str] = None
    data_period_end: Optional[str] = None
    annual_rainfall_mm: Optional[float] = None
    monthly_rainfall_mm: Optional[Dict[str, float]] = None
    rainfall_data_available: bool = False
    data_resolution: Optional[str] = None
    data_quality: str = "unknown"
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error_message: Optional[str] = None
    rainy_days: Optional[int] = None
    max_daily_rainfall_mm: Optional[float] = None
    number_of_observations: Optional[int] = None
    lookup_method: str = "point_lookup"


# ---------------------------------------------------------------------------
# Simple in-memory cache
# ---------------------------------------------------------------------------


class _CacheEntry:
    """Cache entry with TTL."""
    __slots__ = ("value", "expires_at")

    def __init__(self, value: RainfallResult, ttl_seconds: int = CACHE_TTL_S):
        self.value = value
        self.expires_at = time.time() + ttl_seconds

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class _RainfallCache:
    """Simple in-process cache for rainfall results."""
    __slots__ = ("_cache", "_hits", "_misses")

    def __init__(self):
        self._cache: Dict[str, _CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def _make_key(self, lat: float, lon: float) -> str:
        """Create a cache key with coordinate quantization."""
        return f"{round(lat, 2):.2f},{round(lon, 2):.2f}"

    def get(self, lat: float, lon: float) -> Optional[RainfallResult]:
        key = self._make_key(lat, lon)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired():
            del self._cache[key]
            self._misses += 1
            return None
        self._hits += 1
        return entry.value

    def set(self, lat: float, lon: float, value: RainfallResult) -> None:
        key = self._make_key(lat, lon)
        self._cache[key] = _CacheEntry(value)

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> Dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "entries": len(self._cache)}


# Global cache instance
_rainfall_cache = _RainfallCache()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_coordinates(latitude: float, longitude: float) -> None:
    """Validate latitude and longitude values."""
    if not (MIN_LAT <= latitude <= MAX_LAT):
        raise RainfallValidationError(
            f"Latitude must be between {MIN_LAT} and {MAX_LAT}, got {latitude}."
        )
    if not (MIN_LON <= longitude <= MAX_LON):
        raise RainfallValidationError(
            f"Longitude must be between {MIN_LON} and {MAX_LON}, got {longitude}."
        )


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _fetch_open_meteo_rainfall(
    latitude: float,
    longitude: float,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> RainfallResult:
    """
    Fetch rainfall data from Open-Meteo Climate API (ERA5-Land reanalysis).

    Parameters
    ----------
    latitude : float
        Latitude in decimal degrees.
    longitude : float
        Longitude in decimal degrees.
    start_date : str, optional
        Start date in YYYY-MM-DD format.
    end_date : str, optional
        End date in YYYY-MM-DD format.

    Returns
    -------
    RainfallResult
        Normalized rainfall data.

    Raises
    ------
    RainfallProviderError
        If the API returns an error.
    RainfallDataUnavailable
        If no rainfall data is available.
    """
    # Default to last full year of data
    now = datetime.now(timezone.utc)
    if end_date is None:
        end_date = f"{now.year - 1}-12-31"
    if start_date is None:
        start_date = f"{now.year - 10}-01-01"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "precipitation_sum",
        "timezone": "UTC",
    }

    try:
        response = requests.get(
            OPEN_METEO_CLIMATE_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.Timeout as exc:
        raise RainfallProviderError(
            f"Open-Meteo API request timed out: {exc}"
        ) from exc
    except requests.RequestException as exc:
        raise RainfallProviderError(
            f"Open-Meteo API request failed: {exc}"
        ) from exc

    if response.status_code == 429:
        raise RainfallProviderError("Open-Meteo API rate limit exceeded.")
    if response.status_code != 200:
        raise RainfallProviderError(
            f"Open-Meteo API returned status {response.status_code}: "
            f"{response.text[:200]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RainfallProviderError(
            f"Invalid JSON response from Open-Meteo: {exc}"
        ) from exc

    # Check for API-level errors
    if data.get("error"):
        error_msg = str(data.get("error", "Unknown API error"))
        raise RainfallDataUnavailable(f"Open-Meteo: {error_msg}")

    # Extract precipitation data
    daily = data.get("daily")
    if daily is None:
        raise RainfallDataUnavailable(
            "No daily precipitation data available from Open-Meteo."
        )

    precipitation = daily.get("precipitation_sum")
    time_series = daily.get("time", [])

    if not precipitation or not time_series:
        raise RainfallDataUnavailable(
            "Empty precipitation time series from Open-Meteo."
        )

    # Process monthly aggregates - average per calendar month across all years
    # Open-Meteo provides daily data; we aggregate by month-of-year
    monthly_sums: Dict[str, float] = {}
    monthly_counts: Dict[str, int] = {}

    for date_str, precip in zip(time_series, precipitation):
        if precip is None:
            continue
        # Extract month (1-12) from "YYYY-MM-DD"
        month_str = date_str.split("-")[1].lstrip("0")
        if not month_str:
            month_str = "12"
        monthly_sums[month_str] = monthly_sums.get(month_str, 0.0) + precip
        monthly_counts[month_str] = monthly_counts.get(month_str, 0) + 1

    # Calculate per-year monthly average: sum / num_years
    # Number of years in dataset
    if time_series:
        first_year = int(time_series[0][:4])
        last_year = int(time_series[-1][:4])
        num_years = max(1, last_year - first_year + 1)
    else:
        num_years = 1

    monthly_averages: Dict[str, float] = {}
    for month_str in monthly_sums:
        # Average monthly total = total / num_years
        avg = monthly_sums[month_str] / num_years
        monthly_averages[month_str] = round(avg, 1)

    # Calculate mean annual total
    annual_total = sum(monthly_averages.values()) if monthly_averages else None

    # Count rainy days (days with precipitation > 0.1 mm)
    rainy_days = sum(1 for p in precipitation if p is not None and p > 0.1)

    # Find maximum daily rainfall
    valid_precip = [p for p in precipitation if p is not None]
    max_daily = max(valid_precip) if valid_precip else None

    return RainfallResult(
        source="Open-Meteo-ERA5",
        latitude=latitude,
        longitude=longitude,
        data_period_start=start_date,
        data_period_end=end_date,
        annual_rainfall_mm=round(annual_total, 1) if annual_total else None,
        monthly_rainfall_mm=monthly_averages if monthly_averages else None,
        rainfall_data_available=True,
        data_resolution="0.1 degree (~11 km)",
        data_quality="historical_gridded_reanalysis",
        rainy_days=rainy_days,
        max_daily_rainfall_mm=round(max_daily, 1) if max_daily else None,
        number_of_observations=len(valid_precip) if valid_precip else None,
        lookup_method="point_lookup",
    )


# ---------------------------------------------------------------------------
# Main service function
# ---------------------------------------------------------------------------


def get_rainfall(
    latitude: float,
    longitude: float,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    use_cache: bool = True,
) -> RainfallResult:
    """
    Retrieve rainfall data for a geographic location.

    This function queries external rainfall data providers and returns
    normalized historical/climatological rainfall information.

    Parameters
    ----------
    latitude : float
        Latitude in decimal degrees (-90 to 90).
    longitude : float
        Longitude in decimal degrees (-180 to 180).
    start_date : str, optional
        Start date in YYYY-MM-DD format. Defaults to 10 years ago.
    end_date : str, optional
        End date in YYYY-MM-DD format. Defaults to last complete year.
    use_cache : bool, default True
        Whether to use cached results if available.

    Returns
    -------
    RainfallResult
        Normalized rainfall data. Check `rainfall_data_available` to
        determine if data was successfully retrieved.

    Notes
    -----
    - Current implementation provides POINT-based rainfall estimates.
    - The returned `annual_rainfall_mm` represents historical mean precipitation.
    - This is NOT design rainfall - that will be addressed in Phase 9.
    - The `lookup_method` field indicates how the location was determined.
    """
    _validate_coordinates(latitude, longitude)

    # Check cache first
    if use_cache:
        cached = _rainfall_cache.get(latitude, longitude)
        if cached is not None:
            logger.debug(
                "Rainfall cache hit for (%.4f, %.4f)", latitude, longitude
            )
            return cached

    # Try primary provider (Open-Meteo)
    try:
        result = _fetch_open_meteo_rainfall(
            latitude=latitude,
            longitude=longitude,
            start_date=start_date,
            end_date=end_date,
        )
    except RainfallError as exc:
        logger.warning(
            "Primary rainfall provider failed for (%.4f, %.4f): %s",
            latitude, longitude, exc,
        )
        # Return structured unavailable response
        result = RainfallResult(
            source="Open-Meteo-ERA5",
            latitude=latitude,
            longitude=longitude,
            rainfall_data_available=False,
            data_quality="unavailable",
            error_message=str(exc),
            lookup_method="point_lookup",
        )

    # Cache successful results
    if use_cache and result.rainfall_data_available:
        _rainfall_cache.set(latitude, longitude, result)

    return result


def get_rainfall_for_bbox(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> RainfallResult:
    """
    Retrieve rainfall data for a bounding box (area estimate).

    Currently, this function estimates rainfall at the bounding box centroid.
    Phase 9 should implement proper spatial averaging over the catchment.

    Parameters
    ----------
    min_lat, max_lat : float
        Latitude bounds.
    min_lon, max_lon : float
        Longitude bounds.
    start_date, end_date : str, optional
        Date range for historical data.

    Returns
    -------
    RainfallResult
        Normalized rainfall data with `lookup_method` indicating "bbox_centroid".
    """
    # Calculate centroid
    centroid_lat = (min_lat + max_lat) / 2.0
    centroid_lon = (min_lon + max_lon) / 2.0

    result = get_rainfall(
        latitude=centroid_lat,
        longitude=centroid_lon,
        start_date=start_date,
        end_date=end_date,
    )

    # Update lookup method to indicate bbox-based lookup
    result.lookup_method = "bbox_centroid"

    return result


def get_rainfall_cache_stats() -> Dict[str, int]:
    """Return cache statistics for monitoring."""
    return _rainfall_cache.stats


def clear_rainfall_cache() -> None:
    """Clear the rainfall cache."""
    _rainfall_cache.clear()

