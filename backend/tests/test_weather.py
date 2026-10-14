"""
Unit tests for backend/services/weather.py (Phase 8).

Tests cover:
- valid coordinates
- invalid latitude / longitude
- successful provider response
- provider timeout
- provider HTTP error
- malformed provider response
- unavailable weather data
- normalized output structure
- cache behavior

All tests mock external HTTP requests using unittest.mock.
"""

import sys
from pathlib import Path
from unittest import mock
from datetime import datetime

import pytest
import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.weather import (
    get_weather,
    _fetch_open_meteo_weather,
    _validate_coordinates,
    _describe_weather_code,
    WeatherResult,
    WeatherError,
    WeatherValidationError,
    WeatherProviderError,
    clear_weather_cache,
)


def _mock_response(
    status_code=200,
    json_data=None,
    headers=None,
):
    """Create a mock requests.Response with the given properties."""
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.headers = headers or {"content-type": "application/json"}
    response.json = mock.MagicMock(return_value=json_data or {})
    response.text = str(json_data) if json_data else ""
    return response


def _valid_current_response():
    """Return a valid Open-Meteo current weather response."""
    return {
        "current": {
            "time": "2024-01-15T10:00",
            "temperature_2m": 25.4,
            "relative_humidity_2m": 65,
            "precipitation": 0.0,
            "weather_code": 1,
            "wind_speed_10m": 12.5,
            "wind_direction_10m": 180,
        }
    }


class TestValidation:
    def test_valid_coordinates(self):
        # Should not raise
        _validate_coordinates(21.2474, 81.2900)
        _validate_coordinates(-90.0, -180.0)
        _validate_coordinates(90.0, 180.0)
        _validate_coordinates(0.0, 0.0)

    def test_invalid_latitude_too_high(self):
        with pytest.raises(WeatherValidationError) as exc_info:
            _validate_coordinates(91.0, 0.0)
        assert "Latitude must be between" in str(exc_info.value)

    def test_invalid_latitude_too_low(self):
        with pytest.raises(WeatherValidationError) as exc_info:
            _validate_coordinates(-91.0, 0.0)
        assert "Latitude must be between" in str(exc_info.value)

    def test_invalid_longitude_too_high(self):
        with pytest.raises(WeatherValidationError) as exc_info:
            _validate_coordinates(0.0, 181.0)
        assert "Longitude must be between" in str(exc_info.value)

    def test_invalid_longitude_too_low(self):
        with pytest.raises(WeatherValidationError) as exc_info:
            _validate_coordinates(0.0, -181.0)
        assert "Longitude must be between" in str(exc_info.value)


class TestWeatherCodeDescription:
    def test_known_codes(self):
        assert _describe_weather_code(0) == "Clear sky"
        assert _describe_weather_code(1) == "Mainly clear"
        assert _describe_weather_code(3) == "Overcast"
        assert _describe_weather_code(61) == "Slight rain"
        assert _describe_weather_code(95) == "Thunderstorm"

    def test_none_code(self):
        assert _describe_weather_code(None) is None

    def test_unknown_code(self):
        result = _describe_weather_code(999)
        assert "999" in result


class TestFetchOpenMeteoWeather:
    """Tests for _fetch_open_meteo_weather with mocked responses."""

    def test_successful_response(self):
        clear_weather_cache()
        json_data = _valid_current_response()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = _fetch_open_meteo_weather(21.2474, 81.2900)

        assert isinstance(result, WeatherResult)
        assert result.source == "Open-Meteo-Forecast"
        assert result.latitude == 21.2474
        assert result.longitude == 81.2900
        assert result.weather_data_available is True
        assert result.observation_timestamp == "2024-01-15T10:00"
        assert result.temperature_c == 25.4
        assert result.humidity_pct == 65
        assert result.precipitation_mm == 0.0
        assert result.wind_speed_kmh == 12.5
        assert result.wind_direction_deg == 180
        assert result.weather_description == "Mainly clear"
        assert result.fetched_at is not None
        assert result.error_message is None

    def test_timeout_error(self):
        clear_weather_cache()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout("Connection timed out")

            with pytest.raises(WeatherProviderError) as exc_info:
                _fetch_open_meteo_weather(21.2474, 81.2900)

        assert "timed out" in str(exc_info.value)

    def test_http_error(self):
        clear_weather_cache()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(500, {"error": "Internal error"})

            with pytest.raises(WeatherProviderError) as exc_info:
                _fetch_open_meteo_weather(21.2474, 81.2900)

        assert "500" in str(exc_info.value)

    def test_rate_limit_error(self):
        clear_weather_cache()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(429, {"error": "Too many requests"})

            with pytest.raises(WeatherProviderError) as exc_info:
                _fetch_open_meteo_weather(21.2474, 81.2900)

        assert "rate limit" in str(exc_info.value).lower()

    def test_malformed_json(self):
        clear_weather_cache()

        with mock.patch("services.weather.requests.get") as mock_get:
            response = _mock_response(200, None)
            response.json.side_effect = ValueError("No JSON object")
            mock_get.return_value = response

            with pytest.raises(WeatherProviderError) as exc_info:
                _fetch_open_meteo_weather(21.2474, 81.2900)

        assert "Invalid JSON" in str(exc_info.value)

    def test_missing_current_data(self):
        clear_weather_cache()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"current": None})

            with pytest.raises(WeatherProviderError) as exc_info:
                _fetch_open_meteo_weather(21.2474, 81.2900)

        assert "No current weather" in str(exc_info.value)


class TestGetWeather:
    """Tests for the public get_weather function."""

    def test_invalid_coordinates_raises(self):
        clear_weather_cache()

        with pytest.raises(WeatherValidationError):
            get_weather(91.0, 0.0)

        with pytest.raises(WeatherValidationError):
            get_weather(0.0, 181.0)

    def test_provider_failure_returns_unavailable_result(self):
        clear_weather_cache()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout("timed out")

            result = get_weather(21.2474, 81.2900)

        assert isinstance(result, WeatherResult)
        assert result.weather_data_available is False
        assert result.source == "Open-Meteo-Forecast"
        assert result.latitude == 21.2474
        assert result.longitude == 81.2900
        assert result.error_message is not None
        assert "timed out" in result.error_message

    def test_successful_lookup(self):
        clear_weather_cache()
        json_data = _valid_current_response()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = get_weather(21.2474, 81.2900)

        assert result.weather_data_available is True
        assert result.temperature_c == 25.4


class TestWeatherCache:
    """Tests for the in-process weather cache."""

    def test_cache_hits(self):
        clear_weather_cache()
        json_data = _valid_current_response()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result1 = get_weather(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 1

            result2 = get_weather(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 1

            assert result1.temperature_c == result2.temperature_c

    def test_cache_bypassed(self):
        clear_weather_cache()
        json_data = _valid_current_response()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            get_weather(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 1

            get_weather(21.2474, 81.2900, use_cache=False)
            assert mock_get.call_count == 2

    def test_clear_cache(self):
        clear_weather_cache()
        json_data = _valid_current_response()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            get_weather(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 1

            clear_weather_cache()
            get_weather(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 2


class TestNormalizedOutput:
    """Verify the output structure matches the expected WeatherResult schema."""

    def test_all_required_fields_present(self):
        clear_weather_cache()
        json_data = _valid_current_response()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = get_weather(21.2474, 81.2900)

        required_fields = [
            "source", "latitude", "longitude", "weather_data_available",
            "fetched_at",
        ]
        for field in required_fields:
            assert hasattr(result, field), f"Missing attribute: {field}"

        assert isinstance(result.source, str)
        assert isinstance(result.latitude, float)
        assert isinstance(result.longitude, float)
        assert isinstance(result.weather_data_available, bool)
        assert isinstance(result.fetched_at, str)
        datetime.fromisoformat(result.fetched_at.replace("Z", "+00:00"))

    def test_none_fields_when_unavailable(self):
        clear_weather_cache()

        with mock.patch("services.weather.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout()

            result = get_weather(21.2474, 81.2900)

        assert result.observation_timestamp is None
        assert result.temperature_c is None
        assert result.precipitation_mm is None
        assert result.humidity_pct is None
        assert result.wind_speed_kmh is None
        assert result.wind_direction_deg is None
        assert result.weather_description is None


