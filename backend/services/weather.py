"""
Weather Information Service (Phase 8).

Provides supplementary current/forecast weather data for a location.
This is NOT used for rainfall calculations or design-rainfall derivation.

Provider: Open-Meteo Forecast API
    - Global coverage, no API key required
    - Includes current conditions and short-term forecasts

Design Principles
----------------
1. Weather is supplementary context, not the basis for design decisions.
2. All external API calls go through this service.
3. Provider failures return structured unavailable responses, not crashes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_S = 20.0
CACHE_TTL_S = 15 * 60
MIN_LAT, MAX_LAT = -90.0, 90.0
MIN_LON, MAX_LON = -180.0, 180.0


class WeatherError(Exception):
    """Base exception for weather service errors."""
    pass


class WeatherValidationError(WeatherError):
    """Raised when input coordinates are invalid."""
    pass


class WeatherProviderError(WeatherError):
    """Raised when the external provider returns an error."""
    pass


@dataclass
class WeatherResult:
    """
    Normalized weather data result.

    Attributes
    ----------
    source : str
        Identifier of the data provider.
    latitude, longitude : float
        Coordinates of the lookup point.
    observation_timestamp : Optional[str]
        ISO 8601 timestamp of the observation.
    temperature_c : Optional[float]
        Air temperature in degrees Celsius.
    precipitation_mm : Optional[float]
        Precipitation in mm.
    humidity_pct : Optional[float]
        Relative humidity in percent.
    wind_speed_kmh : Optional[float]
        Wind speed in km/h.
    wind_direction_deg : Optional[float]
        Wind direction in degrees (0-360).
    weather_description : Optional[str]
        Short text description of the weather.
    weather_data_available : bool
        True if valid weather data was obtained.
    fetched_at : str
        ISO 8601 timestamp when data was fetched.
    error_message : Optional[str]
        Error description if data is unavailable.
    """
    source: str
    latitude: float
    longitude: float
    observation_timestamp: Optional[str] = None
    temperature_c: Optional[float] = None
    precipitation_mm: Optional[float] = None
    humidity_pct: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    weather_description: Optional[str] = None
    weather_data_available: bool = False
    fetched_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value, ttl_seconds=CACHE_TTL_S):
        self.value = value
        self.expires_at = time.time() + ttl_seconds

    def is_expired(self):
        return time.time() > self.expires_at


class _WeatherCache:
    __slots__ = ("_cache",)

    def __init__(self):
        self._cache = {}

    def _make_key(self, lat, lon):
        return f"{round(lat, 3):.3f},{round(lon, 3):.3f}"

    def get(self, lat, lon):
        key = self._make_key(lat, lon)
        entry = self._cache.get(key)
        if entry is None or entry.is_expired():
            if entry is not None:
                del self._cache[key]
            return None
        return entry.value

    def set(self, lat, lon, value):
        key = self._make_key(lat, lon)
        self._cache[key] = _CacheEntry(value)

    def clear(self):
        self._cache.clear()


_weather_cache = _WeatherCache()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_coordinates(latitude, longitude):
    if not (MIN_LAT <= latitude <= MAX_LAT):
        raise WeatherValidationError(
            f"Latitude must be between {MIN_LAT} and {MAX_LAT}, got {latitude}."
        )
    if not (MIN_LON <= longitude <= MAX_LON):
        raise WeatherValidationError(
            f"Longitude must be between {MIN_LON} and {MAX_LON}, got {longitude}."
        )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


_WEATHER_CODE_MAP = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm", 99: "Thunderstorm with heavy hail",
}


def _describe_weather_code(code):
    if code is None:
        return None
    return _WEATHER_CODE_MAP.get(int(code), f"Weather code {code}")


def _fetch_open_meteo_weather(latitude, longitude):
    """Fetch current weather from Open-Meteo Forecast API."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ("temperature_2m,relative_humidity_2m,precipitation,"
                    "weather_code,wind_speed_10m,wind_direction_10m"),
        "timezone": "auto",
    }
    try:
        response = requests.get(
            OPEN_METEO_FORECAST_URL, params=params, timeout=REQUEST_TIMEOUT_S,
        )
    except requests.Timeout as exc:
        raise WeatherProviderError(
            f"Open-Meteo weather request timed out: {exc}"
        ) from exc
    except requests.RequestException as exc:
        raise WeatherProviderError(
            f"Open-Meteo weather request failed: {exc}"
        ) from exc

    if response.status_code == 429:
        raise WeatherProviderError(
            "Open-Meteo weather API rate limit exceeded."
        )
    if response.status_code != 200:
        raise WeatherProviderError(
            f"Open-Meteo weather API returned status {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise WeatherProviderError(
            f"Invalid JSON from Open-Meteo weather API: {exc}"
        ) from exc

    if data.get("error"):
        raise WeatherProviderError(
            f"Open-Meteo: {data.get('error', 'Unknown API error')}"
        )

    current = data.get("current")
    if current is None:
        raise WeatherProviderError(
            "No current weather data from Open-Meteo."
        )

    return WeatherResult(
        source="Open-Meteo-Forecast",
        latitude=latitude,
        longitude=longitude,
        observation_timestamp=current.get("time"),
        temperature_c=current.get("temperature_2m"),
        precipitation_mm=current.get("precipitation"),
        humidity_pct=current.get("relative_humidity_2m"),
        wind_speed_kmh=current.get("wind_speed_10m"),
        wind_direction_deg=current.get("wind_direction_10m"),
        weather_description=_describe_weather_code(current.get("weather_code")),
        weather_data_available=True,
    )


# ---------------------------------------------------------------------------
# Main service function
# ---------------------------------------------------------------------------


def get_weather(latitude, longitude, use_cache=True):
    """Retrieve current weather data for a geographic location."""
    _validate_coordinates(latitude, longitude)

    if use_cache:
        cached = _weather_cache.get(latitude, longitude)
        if cached is not None:
            return cached

    try:
        result = _fetch_open_meteo_weather(
            latitude=latitude, longitude=longitude
        )
    except WeatherError as exc:
        logger.warning(
            "Weather provider failed for (%.4f, %.4f): %s",
            latitude, longitude, exc,
        )
        result = WeatherResult(
            source="Open-Meteo-Forecast",
            latitude=latitude,
            longitude=longitude,
            weather_data_available=False,
            error_message=str(exc),
        )

    if use_cache and result.weather_data_available:
        _weather_cache.set(latitude, longitude, result)

    return result


def clear_weather_cache():
    """Clear the weather cache."""
    _weather_cache.clear()


