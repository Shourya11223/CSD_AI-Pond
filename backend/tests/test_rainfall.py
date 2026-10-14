"""
Unit tests for backend/services/rainfall.py (Phase 8).

Tests cover:
- valid coordinates
- invalid latitude / longitude
- successful provider response
- provider timeout
- provider HTTP error
- malformed provider response
- unavailable rainfall data
- normalized output structure
- cache behavior

All tests mock external HTTP requests using unittest.mock.
"""

import sys
from pathlib import Path
from unittest import mock
from datetime import datetime, timezone

import pytest
import requests

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.rainfall import (
    get_rainfall,
    get_rainfall_for_bbox,
    _fetch_open_meteo_rainfall,
    _validate_coordinates,
    RainfallResult,
    RainfallError,
    RainfallValidationError,
    RainfallProviderError,
    RainfallDataUnavailable,
    clear_rainfall_cache,
    get_rainfall_cache_stats,
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


def _valid_daily_response():
    """Return a valid Open-Meteo daily precipitation response."""
    return {
        "daily": {
            "time": [
                "2023-06-28",
                "2023-06-29",
                "2023-06-30",
                "2023-07-01",
                "2023-07-02",
            ],
            "precipitation_sum": [0.0, 5.5, 12.3, 0.0, 8.1],
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
        with pytest.raises(RainfallValidationError) as exc_info:
            _validate_coordinates(91.0, 0.0)
        assert "Latitude must be between" in str(exc_info.value)

    def test_invalid_latitude_too_low(self):
        with pytest.raises(RainfallValidationError) as exc_info:
            _validate_coordinates(-91.0, 0.0)
        assert "Latitude must be between" in str(exc_info.value)

    def test_invalid_longitude_too_high(self):
        with pytest.raises(RainfallValidationError) as exc_info:
            _validate_coordinates(0.0, 181.0)
        assert "Longitude must be between" in str(exc_info.value)

    def test_invalid_longitude_too_low(self):
        with pytest.raises(RainfallValidationError) as exc_info:
            _validate_coordinates(0.0, -181.0)
        assert "Longitude must be between" in str(exc_info.value)


class TestFetchOpenMeteoRainfall:
    """Tests for _fetch_open_meteo_rainfall with mocked responses."""

    def test_successful_response(self):
        clear_rainfall_cache()
        json_data = _valid_daily_response()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = _fetch_open_meteo_rainfall(21.2474, 81.2900)

        assert isinstance(result, RainfallResult)
        assert result.source == "Open-Meteo-ERA5"
        assert result.latitude == 21.2474
        assert result.longitude == 81.2900
        assert result.rainfall_data_available is True
        assert result.data_resolution == "0.1 degree (~11 km)"
        assert result.data_quality == "historical_gridded_reanalysis"
        assert result.monthly_rainfall_mm is not None
        assert result.annual_rainfall_mm is not None
        assert result.annual_rainfall_mm >= 0
        # rainy_days: 3 out of 5 days had rain (>0.1mm)
        assert result.rainy_days == 3
        # max_daily: 12.3 mm
        assert result.max_daily_rainfall_mm == 12.3
        assert result.number_of_observations == 5
        assert result.fetched_at is not None
        assert result.error_message is None
        assert result.lookup_method == "point_lookup"

    def test_timeout_error(self):
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout("Connection timed out")

            with pytest.raises(RainfallProviderError) as exc_info:
                _fetch_open_meteo_rainfall(21.2474, 81.2900)

        assert "timed out" in str(exc_info.value)

    def test_http_error(self):
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(500, {"error": "Internal server error"})

            with pytest.raises(RainfallProviderError) as exc_info:
                _fetch_open_meteo_rainfall(21.2474, 81.2900)

        assert "500" in str(exc_info.value)

    def test_rate_limit_error(self):
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(429, {"error": "Too many requests"})

            with pytest.raises(RainfallProviderError) as exc_info:
                _fetch_open_meteo_rainfall(21.2474, 81.2900)

        assert "rate limit" in str(exc_info.value).lower()

    def test_malformed_json(self):
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            response = _mock_response(200, None)
            response.json.side_effect = ValueError("No JSON object")
            mock_get.return_value = response

            with pytest.raises(RainfallProviderError) as exc_info:
                _fetch_open_meteo_rainfall(21.2474, 81.2900)

        assert "Invalid JSON" in str(exc_info.value)

    def test_api_error_flag(self):
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"error": "Invalid coordinates"})

            with pytest.raises(RainfallDataUnavailable) as exc_info:
                _fetch_open_meteo_rainfall(91.0, 181.0)

        assert "Invalid coordinates" in str(exc_info.value)

    def test_missing_daily_data(self):
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"daily": None})

            with pytest.raises(RainfallDataUnavailable) as exc_info:
                _fetch_open_meteo_rainfall(21.2474, 81.2900)

        assert "No daily precipitation" in str(exc_info.value)

    def test_empty_daily_data(self):
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"daily": {"time": [], "precipitation_sum": []}})

            with pytest.raises(RainfallDataUnavailable) as exc_info:
                _fetch_open_meteo_rainfall(21.2474, 81.2900)

        assert "Empty precipitation" in str(exc_info.value)

    def test_custom_date_range(self):
        clear_rainfall_cache()
        json_data = _valid_daily_response()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = _fetch_open_meteo_rainfall(
                latitude=21.2474,
                longitude=81.2900,
                start_date="2020-01-01",
                end_date="2020-12-31",
            )

        assert result.rainfall_data_available is True
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs["params"]
        assert params["start_date"] == "2020-01-01"
        assert params["end_date"] == "2020-12-31"


class TestGetRainfall:
    """Tests for the public get_rainfall function."""

    def test_invalid_coordinates_raises(self):
        clear_rainfall_cache()

        with pytest.raises(RainfallValidationError):
            get_rainfall(91.0, 0.0)

        with pytest.raises(RainfallValidationError):
            get_rainfall(0.0, 181.0)

    def test_provider_failure_returns_unavailable_result(self):
        """When the provider fails, get_rainfall should return a structured
        unavailable response rather than raising an exception."""
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout("timed out")

            result = get_rainfall(21.2474, 81.2900)

        assert isinstance(result, RainfallResult)
        assert result.rainfall_data_available is False
        assert result.source == "Open-Meteo-ERA5"
        assert result.latitude == 21.2474
        assert result.longitude == 81.2900
        assert result.error_message is not None
        assert "timed out" in result.error_message

    def test_successful_lookup(self):
        clear_rainfall_cache()
        json_data = _valid_daily_response()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = get_rainfall(21.2474, 81.2900)

        assert result.rainfall_data_available is True
        assert result.annual_rainfall_mm is not None


class TestGetRainfallForBbox:
    """Tests for get_rainfall_for_bbox."""

    def test_uses_centroid(self):
        clear_rainfall_cache()
        json_data = _valid_daily_response()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = get_rainfall_for_bbox(
                min_lat=21.0,
                max_lat=21.5,
                min_lon=81.0,
                max_lon=81.5,
            )

        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs["params"]
        assert params["latitude"] == 21.25
        assert params["longitude"] == 81.25
        assert result.lookup_method == "bbox_centroid"


class TestRainfallCache:
    """Tests for the in-process rainfall cache."""

    def test_cache_hits(self):
        clear_rainfall_cache()
        json_data = _valid_daily_response()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result1 = get_rainfall(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 1

            result2 = get_rainfall(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 1

            assert result1.annual_rainfall_mm == result2.annual_rainfall_mm

    def test_cache_bypassed(self):
        clear_rainfall_cache()
        json_data = _valid_daily_response()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            get_rainfall(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 1

            get_rainfall(21.2474, 81.2900, use_cache=False)
            assert mock_get.call_count == 2

    def test_cache_stats(self):
        clear_rainfall_cache()
        stats = get_rainfall_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["entries"] == 0

    def test_clear_cache(self):
        clear_rainfall_cache()
        json_data = _valid_daily_response()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            get_rainfall(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 1

            clear_rainfall_cache()
            get_rainfall(21.2474, 81.2900, use_cache=True)
            assert mock_get.call_count == 2


class TestNormalizedOutput:
    """Verify the output structure matches the expected RainfallResult schema."""

    def test_all_required_fields_present(self):
        clear_rainfall_cache()
        json_data = _valid_daily_response()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = get_rainfall(21.2474, 81.2900)

        required_fields = [
            "source", "latitude", "longitude", "rainfall_data_available",
            "data_quality", "fetched_at", "lookup_method",
        ]
        for field in required_fields:
            assert hasattr(result, field), f"Missing attribute: {field}"

        assert isinstance(result.source, str)
        assert isinstance(result.latitude, float)
        assert isinstance(result.longitude, float)
        assert isinstance(result.rainfall_data_available, bool)
        assert isinstance(result.fetched_at, str)
        datetime.fromisoformat(result.fetched_at.replace("Z", "+00:00"))

    def test_none_fields_when_unavailable(self):
        clear_rainfall_cache()

        with mock.patch("services.rainfall.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout()

            result = get_rainfall(21.2474, 81.2900)

        assert result.annual_rainfall_mm is None
        assert result.monthly_rainfall_mm is None
        assert result.data_resolution is None
        assert result.rainy_days is None
        assert result.max_daily_rainfall_mm is None
        assert result.number_of_observations is None
        assert result.data_period_start is None
        assert result.data_period_end is None

