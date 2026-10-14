"""
Design Rainfall Service (Phase 9).

Extracts design rainfall depth from historical daily rainfall using the
Gumbel extreme-value distribution.

Methodology
-----------
1. Historical DAILY precipitation is fetched from the Open-Meteo Archive API
   (ERA5-Land reanalysis, ~11 km / 0.1 degree resolution).
2. For each calendar year in the requested period, the MAXIMUM DAILY
   precipitation value is identified, forming the Annual Maximum Daily
   Rainfall (AMDR) series.
3. The Gumbel (Type I Extreme Value) distribution is fitted to the AMDR
   series using the method of moments.
4. The design rainfall for a given return period T is estimated via the
   standard Gumbel frequency relationship.

   Gumbel quantile formula (method of moments):
       x_T = mu_hat + beta_hat * y_T
   where:
       beta_hat = s_x * sqrt(6) / pi     (scale parameter estimate)
       mu_hat   = x_bar - beta_hat * gamma (location parameter estimate)
       y_T      = -ln(-ln(1 - 1/T))      (reduced variate)
       x_bar, s_x = sample mean and standard deviation of annual maxima
       gamma    ~ 0.57721566 (Euler-Mascheroni constant)

   Cumulative probability: F = 1 - 1/T
   Reduced variate:         y = -ln(-ln(F))

What This Is NOT
----------------
- This is NOT a full IDF (Intensity-Duration-Frequency) analysis.
- This is NOT a runoff calculation.
- This is NOT an SCS-CN method implementation.
- This is NOT the Rational Method.
- This does NOT modify the frontend.
- This does NOT integrate into the main analysis pipeline yet.

Limitations
-----------
- Design rainfall is a statistical estimate; reliability depends on the
  length of the historical record.
- Short records (< 10 years) yield unreliable estimates for long return
  periods (e.g., 50 or 100 years).
- The result is a POINT estimate at the given coordinates; it does not
  account for spatial variability over a catchment.
- The source is Open-Meteo ERA5-Land, NOT an official IMD design storm value.

Data Source
-----------
Open-Meteo Climate API - ERA5-Land Daily Aggregated Reanalysis.
- Global coverage, 0.1 degree (~11 km) resolution.
- No API key required.
- URL: https://archive-api.open-meteo.com/v1/archive

Environment Variables
---------------------
None required for Open-Meteo (no API key needed).
"""

from __future__ import annotations

import logging
import math
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Request timeout in seconds
REQUEST_TIMEOUT_S = 30.0

# Cache TTL in seconds (24 hours - historical data does not change)
CACHE_TTL_S = 24 * 60 * 60

# Coordinate limits
MIN_LAT, MAX_LAT = -90.0, 90.0
MIN_LON, MAX_LON = -180.0, 180.0

# Euler-Mascheroni constant (used in Gumbel method-of-moments)
_EULER_GAMMA = 0.5772156649015328606

# Default historical analysis period: last 30 years (excluding current year)
DEFAULT_END_YEAR_OFFSET = 1   # exclude the current (potentially incomplete) year
DEFAULT_START_YEAR_COUNT = 30  # aim for 30 years of data

# Minimum return period accepted by the service
MIN_RETURN_PERIOD = 2.0

# Data-quality thresholds (number of years in the annual-maximum series)
_QUALITY_INSUFFICIENT = 5   # < 5  years -> insufficient
_QUALITY_LIMITED      = 10  # 5-9  years -> limited
_QUALITY_MODERATE     = 20  # 10-19 years -> moderate
# >= 20 years -> stronger historical basis


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DesignRainfallError(Exception):
    """Base exception for design-rainfall service errors."""
    pass


class DesignRainfallValidationError(DesignRainfallError):
    """Raised when input parameters are invalid."""
    pass


class DesignRainfallProviderError(DesignRainfallError):
    """Raised when the external provider returns an error."""
    pass


class DesignRainfallDataUnavailable(DesignRainfallError):
    """Raised when sufficient rainfall data cannot be retrieved."""
    pass


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DesignRainfallResult:
    """
    Normalized design-rainfall result.

    Attributes
    ----------
    source : str
        Identifier of the data provider (e.g., "Open-Meteo-ERA5").
    latitude, longitude : float
        Coordinates of the lookup point.
    data_period_start, data_period_end : Optional[str]
        ISO 8601 date strings for the start and end of the historical
        data period actually returned by the provider.
    number_of_years : Optional[int]
        Number of complete calendar years with annual maxima.
    number_of_observations : Optional[int]
        Total number of daily observations used.
    annual_maxima_count : Optional[int]
        Number of annual maximum values extracted.
    annual_maximum_min_mm : Optional[float]
        Minimum value in the annual-maximum series (mm).
    annual_maximum_mean_mm : Optional[float]
        Mean of the annual-maximum series (mm).
    annual_maximum_max_mm : Optional[float]
        Maximum value in the annual-maximum series (mm).
    return_period_years : float
        Requested return period in years.
    design_rainfall_mm : Optional[float]
        Estimated design rainfall depth for the return period (mm).
    distribution : str
        Statistical distribution used ("Gumbel").
    fitting_method : str
        Fitting method used ("method_of_moments").
    data_quality : str
        Data-quality label: "insufficient", "limited", "moderate",
        "stronger historical basis".
    warnings : List[str]
        Human-readable warnings, e.g. short-record warnings.
    fetched_at : str
        ISO 8601 timestamp when the result was computed.
    design_rainfall_available : bool
        True when design_rainfall_mm is a valid estimate.
    error_message : Optional[str]
        Error description when design_rainfall_available is False.
    """
    source: str = "Open-Meteo-ERA5"
    latitude: float = 0.0
    longitude: float = 0.0
    data_period_start: Optional[str] = None
    data_period_end: Optional[str] = None
    number_of_years: Optional[int] = None
    number_of_observations: Optional[int] = None
    annual_maxima_count: Optional[int] = None
    annual_maximum_min_mm: Optional[float] = None
    annual_maximum_mean_mm: Optional[float] = None
    annual_maximum_max_mm: Optional[float] = None
    return_period_years: float = 25.0
    design_rainfall_mm: Optional[float] = None
    distribution: str = "Gumbel"
    fitting_method: str = "method_of_moments"
    data_quality: str = "unknown"
    warnings: List[str] = field(default_factory=list)
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    design_rainfall_available: bool = False
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# In-process cache
# ---------------------------------------------------------------------------


class _CacheEntry:
    """Cache entry with TTL."""
    __slots__ = ("value", "expires_at")

    def __init__(self, value: DesignRainfallResult, ttl_seconds: int = CACHE_TTL_S):
        self.value = value
        self.expires_at = time.time() + ttl_seconds

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class _DesignRainfallCache:
    """Simple in-process cache for design-rainfall results."""
    __slots__ = ("_cache", "_hits", "_misses")

    def __init__(self):
        self._cache: Dict[str, _CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    def _make_key(
        self,
        lat: float,
        lon: float,
        start_year: int,
        end_year: int,
        return_period_years: float,
    ) -> str:
        """Create a cache key that includes all relevant parameters."""
        return (
            f"{round(lat, 2):.2f},{round(lon, 2):.2f}"
            f"|{start_year}|{end_year}|{round(return_period_years, 1)}"
        )

    def get(
        self,
        lat: float,
        lon: float,
        start_year: int,
        end_year: int,
        return_period_years: float,
    ) -> Optional[DesignRainfallResult]:
        key = self._make_key(lat, lon, start_year, end_year, return_period_years)
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

    def set(
        self,
        lat: float,
        lon: float,
        start_year: int,
        end_year: int,
        return_period_years: float,
        value: DesignRainfallResult,
    ) -> None:
        key = self._make_key(lat, lon, start_year, end_year, return_period_years)
        self._cache[key] = _CacheEntry(value)

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> Dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "entries": len(self._cache)}


# Global cache instance
_design_rainfall_cache = _DesignRainfallCache()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_coordinates(latitude: float, longitude: float) -> None:
    """Validate latitude and longitude values."""
    if not (MIN_LAT <= latitude <= MAX_LAT):
        raise DesignRainfallValidationError(
            f"Latitude must be between {MIN_LAT} and {MAX_LAT}, got {latitude}."
        )
    if not (MIN_LON <= longitude <= MAX_LON):
        raise DesignRainfallValidationError(
            f"Longitude must be between {MIN_LON} and {MAX_LON}, got {longitude}."
        )


def _validate_return_period(return_period_years: float) -> None:
    """Validate return period value."""
    if not isinstance(return_period_years, (int, float)):
        raise DesignRainfallValidationError(
            f"Return period must be a number, got "
            f"{type(return_period_years).__name__}."
        )
    if isinstance(return_period_years, bool):
        # bool is a subclass of int in Python; explicitly reject
        raise DesignRainfallValidationError(
            "Return period must be a numeric value, not a boolean."
        )
    if return_period_years < MIN_RETURN_PERIOD:
        raise DesignRainfallValidationError(
            f"Return period must be >= {MIN_RETURN_PERIOD} year(s), "
            f"got {return_period_years}."
        )


# ---------------------------------------------------------------------------
# Annual maximum extraction
# ---------------------------------------------------------------------------


def _extract_annual_maxima(
    dates: List[str],
    precipitations: List[float],
) -> Tuple[List[int], List[float]]:
    """
    Extract the maximum daily rainfall for each calendar year.

    Parameters
    ----------
    dates : list of str
        ISO 8601 date strings (YYYY-MM-DD), sorted ascending.
    precipitations : list of float
        Corresponding daily precipitation sums (mm).

    Returns
    -------
    years : list of int
        Calendar years, one per annual maximum.
    maxima : list of float
        Maximum daily rainfall for each year (mm).
        Days with None/NaN precipitation are treated as 0.0.
        Negative precipitation values (data artefacts) are clamped to 0.0.

    Notes
    -----
    - Only years with at least one observation are included.
    - The result is sorted by year ascending.
    """
    if len(dates) != len(precipitations):
        raise ValueError("dates and precipitations must have the same length.")

    # Group by year
    by_year: Dict[int, List[float]] = {}
    for d_str, p_str in zip(dates, precipitations):
        try:
            year = int(d_str[:4])
        except (TypeError, ValueError):
            continue
        try:
            p_val = float(p_str) if p_str is not None else 0.0
        except (TypeError, ValueError):
            p_val = 0.0
        if p_val < 0:
            p_val = 0.0  # guard against negative precipitation
        by_year.setdefault(year, []).append(p_val)

    years: List[int] = []
    maxima: List[float] = []
    for year in sorted(by_year.keys()):
        vals = by_year[year]
        if vals:
            years.append(year)
            maxima.append(max(vals))

    return years, maxima


# ---------------------------------------------------------------------------
# Gumbel extreme-value fitting (method of moments)
# ---------------------------------------------------------------------------


def _fit_gumbel_moments(annual_maxima: List[float]) -> Tuple[float, float]:
    """
    Fit Gumbel (Type I Extreme Value) distribution using the method of moments.

    Parameters
    ----------
    annual_maxima : list of float
        Sample of annual maximum daily rainfall values (mm).

    Returns
    -------
    mu_hat : float
        Estimated Gumbel location parameter (mm).
    beta_hat : float
        Estimated Gumbel scale parameter (mm).

    Formulas (method of moments)
    ----------------------------
    Let x_bar be the sample mean and s_x be the sample standard deviation
    (n-1 denominator) of the annual-maximum series.

    The Gumbel scale parameter is estimated as:
        beta_hat = s_x * sqrt(6) / pi

    The Gumbel location parameter is estimated as:
        mu_hat = x_bar - beta_hat * gamma

    where gamma ~= 0.57721566 is the Euler-Mascheroni constant, the
    expected value of the standard Gumbel reduced variate.

    References
    ----------
    - Gumbel, E.J. (1958). Statistics of Extremes. Columbia University Press.
    - Coles, S. (2001). An Introduction to Statistical Modeling of Extreme Values.
    """
    n = len(annual_maxima)
    if n < 2:
        raise ValueError(
            f"Need at least 2 annual maxima to fit Gumbel, got {n}."
        )

    x_bar = statistics.mean(annual_maxima)
    s_x = statistics.stdev(annual_maxima)  # sample stdev (n-1 denominator)

    if s_x <= 0:
        raise ValueError(
            f"Annual maxima have zero variance (s_x={s_x:.4f}); "
            "cannot fit Gumbel distribution."
        )

    # Method-of-moments estimates
    beta_hat = s_x * math.sqrt(6.0) / math.pi
    mu_hat = x_bar - beta_hat * _EULER_GAMMA

    return mu_hat, beta_hat


def _gumbel_quantile(
    return_period_years: float,
    mu_hat: float,
    beta_hat: float,
) -> float:
    """
    Compute the Gumbel quantile (design rainfall) for a given return period.

    Parameters
    ----------
    return_period_years : float
        Return period T (> 1).
    mu_hat, beta_hat : float
        Gumbel location and scale parameter estimates from
        _fit_gumbel_moments.

    Returns
    -------
    x_T : float
        Design rainfall depth (mm) for return period T.

    Formula
    -------
    Cumulative probability for return period T:
        F = 1 - 1/T

    Reduced variate:
        y_T = -ln(-ln(F))
          = -ln(-ln(1 - 1/T))

    Gumbel quantile:
        x_T = mu_hat + beta_hat * y_T

    Notes
    -----
    - For very large T, x_T grows roughly linearly with ln(T).
    - For T = 2, F = 0.5, y_T ~= 0.1637.
    - For T -> infinity, x_T -> infinity (Gumbel has no upper bound).
    - Negative quantile values are clamped to 0.0.
    """
    if return_period_years <= 1.0:
        raise ValueError(
            f"Return period must be > 1, got {return_period_years}."
        )

    F = 1.0 - 1.0 / return_period_years
    if not (0.0 < F < 1.0):
        raise ValueError(
            f"Invalid return period {return_period_years}: "
            "F must be strictly between 0 and 1."
        )

    ln_F = math.log(F)
    if ln_F >= 0.0:
        raise ValueError(f"Invalid F={F} for return period {return_period_years}.")

    y_T = -math.log(-ln_F)
    x_T = mu_hat + beta_hat * y_T
    return max(0.0, x_T)  # rainfall cannot be negative


# ---------------------------------------------------------------------------
# Data-quality assessment
# ---------------------------------------------------------------------------


def _assess_data_quality(
    n_years: int,
    return_period_years: float,
) -> Tuple[str, List[str]]:
    """
    Assess the reliability of a design-rainfall estimate.

    Parameters
    ----------
    n_years : int
        Number of years in the annual-maximum series.
    return_period_years : float
        Requested return period.

    Returns
    -------
    quality : str
        One of: "insufficient", "limited", "moderate",
        "stronger historical basis".
    warnings : list of str
        Human-readable warnings.

    Thresholds
    ----------
    n_years < 5  -> insufficient
    n_years < 10 -> limited
    n_years < 20 -> moderate
    n_years >= 20 -> stronger historical basis

    Long-return-period warnings
    --------------------------
    If the record is shorter than 2x the return period, a specific
    warning is appended because the estimate is extrapolation.
    """
    warnings: List[str] = []

    if n_years < _QUALITY_INSUFFICIENT:
        quality = "insufficient"
        warnings.append(
            f"Only {n_years} year(s) of data available. "
            "The record is too short for reliable extreme-value analysis. "
            "Results should be treated with extreme caution."
        )
    elif n_years < _QUALITY_LIMITED:
        quality = "limited"
        warnings.append(
            f"Only {n_years} years of data available. "
            "Results should be used with caution."
        )
    elif n_years < _QUALITY_MODERATE:
        quality = "moderate"
    else:
        quality = "stronger historical basis"

    # Long-return-period warning
    if n_years > 0 and return_period_years > 2 * n_years:
        warnings.append(
            f"The requested return period ({return_period_years} years) is more than "
            f"twice the length of the data record ({n_years} years). "
            "This is substantial extrapolation and the estimate is highly uncertain."
        )

    return quality, warnings


# ---------------------------------------------------------------------------
# Historical rainfall fetching
# ---------------------------------------------------------------------------


def _fetch_multiyear_daily_rainfall(
    latitude: float,
    longitude: float,
    start_year: int,
    end_year: int,
) -> Tuple[List[str], List[float], str, str]:
    """
    Fetch daily precipitation from Open-Meteo Archive for a multi-year period.

    Parameters
    ----------
    latitude, longitude : float
        Coordinates.
    start_year, end_year : int
        Inclusive year range for the historical data.

    Returns
    -------
    dates : list of str
        ISO date strings (YYYY-MM-DD).
    precipitations : list of float
        Daily precipitation sums (mm), one per date.
    period_start : str
        ISO date string of the first returned observation.
    period_end : str
        ISO date string of the last returned observation.

    Raises
    ------
    DesignRainfallProviderError
        On network or HTTP error.
    DesignRainfallDataUnavailable
        When the API returns an error flag or no data.
    """
    start_date = f"{start_year}-01-01"
    end_date = f"{end_year}-12-31"

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
            OPEN_METEO_ARCHIVE_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_S,
        )
    except requests.Timeout as exc:
        raise DesignRainfallProviderError(
            f"Open-Meteo API request timed out: {exc}"
        ) from exc
    except requests.RequestException as exc:
        raise DesignRainfallProviderError(
            f"Open-Meteo API request failed: {exc}"
        ) from exc

    if response.status_code == 429:
        raise DesignRainfallProviderError("Open-Meteo API rate limit exceeded.")
    if response.status_code != 200:
        raise DesignRainfallProviderError(
            f"Open-Meteo API returned HTTP {response.status_code}."
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise DesignRainfallProviderError(
            f"Invalid JSON response from Open-Meteo: {exc}"
        ) from exc

    # Check for API-level error
    if data.get("error", False):
        reason = data.get("reason", "Unknown error")
        raise DesignRainfallDataUnavailable(
            f"Open-Meteo reported an error: {reason}"
        )

    daily = data.get("daily")
    if daily is None:
        raise DesignRainfallDataUnavailable(
            "No daily data in Open-Meteo response."
        )

    times = daily.get("time")
    precip = daily.get("precipitation_sum")

    if not times or not precip:
        raise DesignRainfallDataUnavailable(
            "Empty daily precipitation data returned by Open-Meteo."
        )

    if len(times) != len(precip):
        raise DesignRainfallProviderError(
            "Mismatched time and precipitation arrays in Open-Meteo response."
        )

    period_start = str(times[0]) if times else None
    period_end = str(times[-1]) if times else None

    return list(times), list(precip), period_start, period_end


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def get_design_rainfall(
    latitude: float,
    longitude: float,
    return_period_years: float = 25.0,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    use_cache: bool = True,
) -> DesignRainfallResult:
    """
    Estimate design daily rainfall depth for a given return period.

    The estimate is derived from historical daily precipitation (ERA5-Land
    reanalysis) by extracting the annual maximum daily rainfall series and
    fitting a Gumbel extreme-value distribution via the method of moments.

    Parameters
    ----------
    latitude, longitude : float
        Decimal-degree coordinates of the lookup point.
    return_period_years : float, default 25.0
        Return period in years. Must be >= 2.
    start_year, end_year : int, optional
        Inclusive year range for the historical analysis.
        Defaults to the last 30 complete years (end_year = current_year - 1,
        start_year = end_year - 29).
    use_cache : bool, default True
        Use cached result if available.

    Returns
    -------
    DesignRainfallResult
        Structured result. Check ``design_rainfall_available`` to determine
        if a valid estimate was computed.
    """
    _validate_coordinates(latitude, longitude)
    _validate_return_period(return_period_years)

    now = datetime.now(timezone.utc)
    if end_year is None:
        end_year = now.year - DEFAULT_END_YEAR_OFFSET
    if start_year is None:
        start_year = end_year - DEFAULT_START_YEAR_COUNT + 1

    if start_year > end_year:
        raise DesignRainfallValidationError(
            f"start_year ({start_year}) must be <= end_year ({end_year})."
        )

    # Check cache
    if use_cache:
        cached = _design_rainfall_cache.get(
            latitude, longitude, start_year, end_year, return_period_years
        )
        if cached is not None:
            logger.debug(
                "Design rainfall cache hit for (%.4f, %.4f) years %d-%d T=%.1f",
                latitude, longitude, start_year, end_year,
                return_period_years,
            )
            return cached

    # Fetch historical daily rainfall
    try:
        dates, precipitations, period_start, period_end = (
            _fetch_multiyear_daily_rainfall(
                latitude=latitude,
                longitude=longitude,
                start_year=start_year,
                end_year=end_year,
            )
        )
    except DesignRainfallError as exc:
        logger.warning(
            "Design rainfall data fetch failed for (%.4f, %.4f): %s",
            latitude, longitude, exc,
        )
        return DesignRainfallResult(
            source="Open-Meteo-ERA5",
            latitude=latitude,
            longitude=longitude,
            return_period_years=return_period_years,
            design_rainfall_available=False,
            data_quality="unavailable",
            error_message=str(exc),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    n_observations = len(dates)

    # Extract annual maximum series
    try:
        years, annual_maxima = _extract_annual_maxima(dates, precipitations)
    except Exception as exc:
        return DesignRainfallResult(
            source="Open-Meteo-ERA5",
            latitude=latitude,
            longitude=longitude,
            return_period_years=return_period_years,
            data_period_start=period_start,
            data_period_end=period_end,
            number_of_observations=n_observations,
            design_rainfall_available=False,
            data_quality="error",
            error_message=f"Annual maximum extraction failed: {exc}",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    n_years = len(annual_maxima)

    if n_years == 0:
        return DesignRainfallResult(
            source="Open-Meteo-ERA5",
            latitude=latitude,
            longitude=longitude,
            return_period_years=return_period_years,
            data_period_start=period_start,
            data_period_end=period_end,
            number_of_observations=n_observations,
            annual_maxima_count=0,
            design_rainfall_available=False,
            data_quality="insufficient",
            error_message="No valid annual maxima could be extracted from the data.",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    # Fit Gumbel distribution
    try:
        mu_hat, beta_hat = _fit_gumbel_moments(annual_maxima)
    except Exception as exc:
        return DesignRainfallResult(
            source="Open-Meteo-ERA5",
            latitude=latitude,
            longitude=longitude,
            return_period_years=return_period_years,
            data_period_start=period_start,
            data_period_end=period_end,
            number_of_observations=n_observations,
            annual_maxima_count=n_years,
            design_rainfall_available=False,
            data_quality="error",
            error_message=f"Gumbel fitting failed: {exc}",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    # Compute design rainfall for requested return period
    try:
        design_rainfall_mm = _gumbel_quantile(
            return_period_years=return_period_years,
            mu_hat=mu_hat,
            beta_hat=beta_hat,
        )
    except Exception as exc:
        return DesignRainfallResult(
            source="Open-Meteo-ERA5",
            latitude=latitude,
            longitude=longitude,
            return_period_years=return_period_years,
            data_period_start=period_start,
            data_period_end=period_end,
            number_of_observations=n_observations,
            annual_maxima_count=n_years,
            design_rainfall_available=False,
            data_quality="error",
            error_message=f"Design rainfall calculation failed: {exc}",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    # Assess data quality and generate warnings
    data_quality, warnings = _assess_data_quality(n_years, return_period_years)

    # Summary statistics of the annual-maximum series
    max_mm_min = min(annual_maxima)
    max_mm_max = max(annual_maxima)
    max_mm_mean = statistics.mean(annual_maxima)

    result = DesignRainfallResult(
        source="Open-Meteo-ERA5",
        latitude=latitude,
        longitude=longitude,
        data_period_start=period_start,
        data_period_end=period_end,
        number_of_years=n_years,
        number_of_observations=n_observations,
        annual_maxima_count=n_years,
        annual_maximum_min_mm=round(max_mm_min, 2),
        annual_maximum_mean_mm=round(max_mm_mean, 2),
        annual_maximum_max_mm=round(max_mm_max, 2),
        return_period_years=return_period_years,
        design_rainfall_mm=round(design_rainfall_mm, 2),
        distribution="Gumbel",
        fitting_method="method_of_moments",
        data_quality=data_quality,
        warnings=warnings,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        design_rainfall_available=True,
    )

    # Cache successful result
    if use_cache:
        _design_rainfall_cache.set(
            lat=latitude,
            lon=longitude,
            start_year=start_year,
            end_year=end_year,
            return_period_years=return_period_years,
            value=result,
        )

    return result


# ---------------------------------------------------------------------------
# Cache management helpers
# ---------------------------------------------------------------------------


def get_design_rainfall_cache_stats() -> Dict[str, int]:
    """Return cache statistics for monitoring."""
    return _design_rainfall_cache.stats


def clear_design_rainfall_cache() -> None:
    """Clear the design-rainfall cache."""
    _design_rainfall_cache.clear()