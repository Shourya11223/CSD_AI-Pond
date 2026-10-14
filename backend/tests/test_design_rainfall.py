"""
Unit tests for backend/services/design_rainfall.py (Phase 9).

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

from services.design_rainfall import (
    get_design_rainfall,
    _validate_coordinates,
    _validate_return_period,
    _extract_annual_maxima,
    _fit_gumbel_moments,
    _gumbel_quantile,
    _assess_data_quality,
    _fetch_multiyear_daily_rainfall,
    DesignRainfallResult,
    DesignRainfallValidationError,
    DesignRainfallProviderError,
    DesignRainfallDataUnavailable,
    clear_design_rainfall_cache,
    get_design_rainfall_cache_stats,
)


def _mock_response(status_code=200, json_data=None, headers=None):
    """Create a mock requests.Response with the given properties."""
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.headers = headers or {"content-type": "application/json"}
    response.json = mock.MagicMock(return_value=json_data or {})
    response.text = str(json_data) if json_data else ""
    return response


def _valid_multiyear_response():
    """Valid Open-Meteo multi-year response.

    Annual maxima:
      2022: max(5,10,50,30) = 50
      2023: max(8,12,70,40,60) = 70
      2024: max(15,20,80,55,65) = 80
    """
    return {
        "daily": {
            "time": [
                "2022-01-01", "2022-01-15", "2022-02-01",
                "2022-07-01", "2022-07-15",
                "2023-01-01", "2023-02-01", "2023-03-01",
                "2023-07-01", "2023-07-20", "2023-08-01",
                "2024-01-01", "2024-01-10", "2024-02-01",
                "2024-07-01", "2024-07-10", "2024-08-01",
            ],
            "precipitation_sum": [
                0.0, 5.0, 10.0, 50.0, 30.0,
                0.0, 8.0, 12.0, 70.0, 40.0, 60.0,
                15.0, 20.0, 5.0, 80.0, 55.0, 65.0,
            ],
        }
    }

# -----------------------------------------------------------------------
# 1. Coordinate validation
# -----------------------------------------------------------------------

class TestCoordinateValidation:
    def test_valid_coordinates(self):
        _validate_coordinates(21.2474, 81.2900)
        _validate_coordinates(-90.0, -180.0)
        _validate_coordinates(90.0, 180.0)
        _validate_coordinates(0.0, 0.0)

    def test_invalid_latitude_too_high(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_coordinates(91.0, 0.0)
        assert "Latitude must be between" in str(exc_info.value)

    def test_invalid_latitude_too_low(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_coordinates(-91.0, 0.0)
        assert "Latitude must be between" in str(exc_info.value)

    def test_invalid_longitude_too_high(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_coordinates(0.0, 181.0)
        assert "Longitude must be between" in str(exc_info.value)

    def test_invalid_longitude_too_low(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_coordinates(0.0, -181.0)
        assert "Longitude must be between" in str(exc_info.value)


# -----------------------------------------------------------------------
# 4-5. Return-period validation
# -----------------------------------------------------------------------

class TestReturnPeriodValidation:
    @pytest.mark.parametrize("t", [2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 1000.0])
    def test_valid_return_periods(self, t):
        _validate_return_period(t)

    def test_invalid_return_period_zero(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_return_period(0.0)
        assert "must be >= 2" in str(exc_info.value)

    def test_invalid_return_period_one(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_return_period(1.0)
        assert "must be >= 2" in str(exc_info.value)

    def test_invalid_return_period_negative(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_return_period(-5.0)
        assert "must be >= 2" in str(exc_info.value)

    def test_invalid_return_period_string(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_return_period("twenty-five")  # type: ignore
        assert "must be a number" in str(exc_info.value)

    def test_invalid_return_period_boolean(self):
        with pytest.raises(DesignRainfallValidationError) as exc_info:
            _validate_return_period(True)  # type: ignore
        assert "not a boolean" in str(exc_info.value)


# -----------------------------------------------------------------------
# 7-8. Annual maximum extraction
# -----------------------------------------------------------------------

class TestAnnualMaximumExtraction:
    def test_annual_maxima_basic(self):
        resp = _valid_multiyear_response()
        years, maxima = _extract_annual_maxima(
            resp["daily"]["time"], resp["daily"]["precipitation_sum"]
        )
        assert years == [2022, 2023, 2024]
        assert maxima == [50.0, 70.0, 80.0]

    def test_annual_maxima_none_treated_as_zero(self):
        dates = ["2022-01-01", "2022-01-15", "2022-02-01"]
        precip = [None, 20.0, None]
        years, maxima = _extract_annual_maxima(dates, precip)
        assert maxima == [20.0]

    def test_annual_maxima_negative_clamped_to_zero(self):
        dates = ["2022-01-01", "2022-01-15", "2022-02-01"]
        precip = [-5.0, 30.0, -2.0]
        years, maxima = _extract_annual_maxima(dates, precip)
        assert maxima == [30.0]

    def test_annual_maxima_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            _extract_annual_maxima(["2022-01-01", "2022-01-15"], [10.0])


# -----------------------------------------------------------------------
# 9. Gumbel fitting
# -----------------------------------------------------------------------

class TestGumbelFitting:
    def test_gumbel_fitting_deterministic(self):
        import math
        annual_maxima = [10.0, 15.0, 20.0, 25.0, 30.0]
        mu_hat, beta_hat = _fit_gumbel_moments(annual_maxima)
        x_bar = 20.0
        s_x = 7.905694550420565
        gamma = 0.5772156649015328606
        beta_expected = s_x * math.sqrt(6.0) / math.pi
        mu_expected = x_bar - beta_expected * gamma
        assert abs(beta_hat - beta_expected) < 1e-6
        assert abs(mu_hat - mu_expected) < 1e-6

    def test_gumbel_fitting_two_values(self):
        mu_hat, beta_hat = _fit_gumbel_moments([10.0, 20.0])
        assert mu_hat > 0
        assert beta_hat > 0

    def test_gumbel_fitting_single_value_raises(self):
        with pytest.raises(ValueError) as exc_info:
            _fit_gumbel_moments([42.0])
        assert "at least 2" in str(exc_info.value)

    def test_gumbel_fitting_zero_variance_raises(self):
        with pytest.raises(ValueError) as exc_info:
            _fit_gumbel_moments([10.0, 10.0, 10.0])
        assert "zero variance" in str(exc_info.value)


# -----------------------------------------------------------------------
# 10-11. Gumbel quantile / return period calculation
# -----------------------------------------------------------------------

class TestGumbelQuantile:
    def test_gumbel_quantile_T2_above_mean(self):
        mu, beta = 20.0, 5.0
        x_T = _gumbel_quantile(2.0, mu, beta)
        assert x_T > mu

    def test_gumbel_quantile_T100_greater_than_T25(self):
        mu, beta = 20.0, 5.0
        x_T25 = _gumbel_quantile(25.0, mu, beta)
        x_T100 = _gumbel_quantile(100.0, mu, beta)
        assert x_T100 > x_T25

    def test_gumbel_quantile_negative_clamped_to_zero(self):
        x_T = _gumbel_quantile(2.0, mu_hat=-1000.0, beta_hat=0.1)
        assert x_T == 0.0

    def test_gumbel_quantile_T_le_1_raises(self):
        with pytest.raises(ValueError):
            _gumbel_quantile(1.0, 20.0, 5.0)

    def test_gumbel_quantile_T25_exceeds_observed_max(self):
        annual_maxima = [50.0, 70.0, 80.0]
        mu_hat, beta_hat = _fit_gumbel_moments(annual_maxima)
        x_T25 = _gumbel_quantile(25.0, mu_hat, beta_hat)
        assert x_T25 > max(annual_maxima)


# -----------------------------------------------------------------------
# 12. Data quality assessment
# -----------------------------------------------------------------------

class TestDataQualityAssessment:
    def test_insufficient_under_5_years(self):
        quality, warnings = _assess_data_quality(3, 25.0)
        assert quality == "insufficient"
        assert len(warnings) >= 1
        assert "too short" in warnings[0]

    def test_limited_5_to_9_years(self):
        # 7 years and a return period of 10 -> only the limited-quality warning
        quality, warnings = _assess_data_quality(7, 10.0)
        assert quality == "limited"
        assert len(warnings) == 1

    def test_moderate_10_to_19_years(self):
        quality, warnings = _assess_data_quality(15, 25.0)
        assert quality == "moderate"
        assert len(warnings) == 0

    def test_stronger_historical_basis_20_plus_years(self):
        quality, warnings = _assess_data_quality(30, 25.0)
        assert quality == "stronger historical basis"
        assert len(warnings) == 0

    def test_long_return_period_extrapolation_warning(self):
        quality, warnings = _assess_data_quality(10, 100.0)
        assert any("extrapolation" in w.lower() for w in warnings)

    def test_no_extrapolation_warning_when_record_adequate(self):
        quality, warnings = _assess_data_quality(20, 25.0)
        assert len(warnings) == 0


# -----------------------------------------------------------------------
# 6, 13-15. Provider-level tests
# -----------------------------------------------------------------------

class TestFetchMultiyearRainfall:
    def test_successful_response(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            dates, precip, p_start, p_end = _fetch_multiyear_daily_rainfall(
                latitude=21.2474, longitude=81.2900,
                start_year=2022, end_year=2024,
            )

        assert len(dates) == 17
        assert len(precip) == 17
        assert p_start == "2022-01-01"
        assert p_end == "2024-08-01"

    def test_timeout_error(self):
        clear_design_rainfall_cache()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout("Connection timed out")

            with pytest.raises(DesignRainfallProviderError) as exc_info:
                _fetch_multiyear_daily_rainfall(21.2474, 81.2900, 2022, 2024)

        assert "timed out" in str(exc_info.value)

    def test_http_error(self):
        clear_design_rainfall_cache()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(500, {"error": "Internal error"})

            with pytest.raises(DesignRainfallProviderError) as exc_info:
                _fetch_multiyear_daily_rainfall(21.2474, 81.2900, 2022, 2024)

        assert "500" in str(exc_info.value)

    def test_rate_limit_error(self):
        clear_design_rainfall_cache()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(429, {"error": "Rate limited"})

            with pytest.raises(DesignRainfallProviderError) as exc_info:
                _fetch_multiyear_daily_rainfall(21.2474, 81.2900, 2022, 2024)

        assert "rate limit" in str(exc_info.value).lower()

    def test_malformed_json(self):
        clear_design_rainfall_cache()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            response = _mock_response(200, None)
            response.json.side_effect = ValueError("No JSON object")
            mock_get.return_value = response

            with pytest.raises(DesignRainfallProviderError) as exc_info:
                _fetch_multiyear_daily_rainfall(21.2474, 81.2900, 2022, 2024)

        assert "Invalid JSON" in str(exc_info.value)

    def test_api_error_flag(self):
        clear_design_rainfall_cache()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(
                200, {"error": True, "reason": "Invalid coordinates"}
            )

            with pytest.raises(DesignRainfallDataUnavailable) as exc_info:
                _fetch_multiyear_daily_rainfall(91.0, 181.0, 2022, 2024)

        assert "Invalid coordinates" in str(exc_info.value)

    def test_missing_daily_data(self):
        clear_design_rainfall_cache()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, {"daily": None})

            with pytest.raises(DesignRainfallDataUnavailable) as exc_info:
                _fetch_multiyear_daily_rainfall(21.2474, 81.2900, 2022, 2024)

        assert "No daily data" in str(exc_info.value)

    def test_empty_daily_data(self):
        clear_design_rainfall_cache()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(
                200, {"daily": {"time": [], "precipitation_sum": []}}
            )

            with pytest.raises(DesignRainfallDataUnavailable) as exc_info:
                _fetch_multiyear_daily_rainfall(21.2474, 81.2900, 2022, 2024)

        assert "Empty daily precipitation" in str(exc_info.value)

    def test_custom_date_range_params(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            _fetch_multiyear_daily_rainfall(
                latitude=21.2474, longitude=81.2900,
                start_year=2010, end_year=2020,
            )

        params = mock_get.call_args.kwargs["params"]
        assert params["start_date"] == "2010-01-01"
        assert params["end_date"] == "2020-12-31"
        assert params["daily"] == "precipitation_sum"


# -----------------------------------------------------------------------
# 16-19. Cache behavior
# -----------------------------------------------------------------------

class TestCache:
    def test_cache_miss_then_hit(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            # First call -> miss
            result1 = get_design_rainfall(
                21.2474, 81.2900, return_period_years=25.0,
                start_year=2022, end_year=2024, use_cache=True,
            )
            assert mock_get.call_count == 1

            # Second identical call -> hit
            result2 = get_design_rainfall(
                21.2474, 81.2900, return_period_years=25.0,
                start_year=2022, end_year=2024, use_cache=True,
            )
            assert mock_get.call_count == 1
            assert result1.design_rainfall_mm == result2.design_rainfall_mm

    def test_cache_bypassed(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            get_design_rainfall(21.2474, 81.2900, start_year=2022,
                                end_year=2024, use_cache=True)
            assert mock_get.call_count == 1

            get_design_rainfall(21.2474, 81.2900, start_year=2022,
                                end_year=2024, use_cache=False)
            assert mock_get.call_count == 2

    def test_cache_key_differs_by_return_period(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            r25 = get_design_rainfall(
                21.2474, 81.2900, return_period_years=25.0,
                start_year=2022, end_year=2024, use_cache=True,
            )
            r100 = get_design_rainfall(
                21.2474, 81.2900, return_period_years=100.0,
                start_year=2022, end_year=2024, use_cache=True,
            )

            assert mock_get.call_count == 2
            assert r25.design_rainfall_mm != r100.design_rainfall_mm
            assert r100.design_rainfall_mm > r25.design_rainfall_mm

    def test_cache_clear(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            get_design_rainfall(21.2474, 81.2900, start_year=2022,
                                end_year=2024, use_cache=True)
            assert mock_get.call_count == 1

            clear_design_rainfall_cache()

            get_design_rainfall(21.2474, 81.2900, start_year=2022,
                                end_year=2024, use_cache=True)
            assert mock_get.call_count == 2

    def test_cache_stats(self):
        clear_design_rainfall_cache()
        stats = get_design_rainfall_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["entries"] == 0


# -----------------------------------------------------------------------
# 20. Normalized output structure
# -----------------------------------------------------------------------

class TestNormalizedOutput:
    def test_all_required_fields_present(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = get_design_rainfall(
                21.2474, 81.2900, return_period_years=25.0,
                start_year=2022, end_year=2024,
            )

        required_fields = [
            "source", "latitude", "longitude",
            "data_period_start", "data_period_end",
            "number_of_years", "number_of_observations",
            "annual_maxima_count",
            "annual_maximum_min_mm", "annual_maximum_mean_mm",
            "annual_maximum_max_mm",
            "return_period_years", "design_rainfall_mm",
            "distribution", "fitting_method", "data_quality",
            "warnings", "fetched_at",
            "design_rainfall_available", "error_message",
        ]
        for field in required_fields:
            assert hasattr(result, field), f"Missing attribute: {field}"

        assert result.distribution == "Gumbel"
        assert result.fitting_method == "method_of_moments"
        datetime.fromisoformat(result.fetched_at.replace("Z", "+00:00"))

    def test_values_correctly_typed_and_sensible(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = get_design_rainfall(
                21.2474, 81.2900, return_period_years=25.0,
                start_year=2022, end_year=2024,
            )

        assert result.design_rainfall_available is True
        assert result.design_rainfall_mm is not None
        assert result.design_rainfall_mm > 0
        assert result.number_of_years == 3
        assert result.number_of_observations == 17
        assert result.annual_maxima_count == 3
        assert result.annual_maximum_min_mm == 50.0
        assert result.annual_maximum_max_mm == 80.0

    def test_provider_failure_returns_structured_unavailable(self):
        clear_design_rainfall_cache()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.side_effect = requests.Timeout()

            result = get_design_rainfall(
                21.2474, 81.2900, return_period_years=25.0,
                start_year=2022, end_year=2024,
            )

        assert result.design_rainfall_available is False
        assert result.design_rainfall_mm is None
        assert result.data_quality == "unavailable"
        assert result.error_message is not None

    def test_extrapolation_warning_in_output(self):
        clear_design_rainfall_cache()
        json_data = _valid_multiyear_response()

        with mock.patch("services.design_rainfall.requests.get") as mock_get:
            mock_get.return_value = _mock_response(200, json_data)

            result = get_design_rainfall(
                21.2474, 81.2900, return_period_years=100.0,
                start_year=2022, end_year=2024,
            )

        assert result.design_rainfall_available is True
        assert len(result.warnings) >= 1
        assert any("extrapolation" in w.lower() for w in result.warnings)
