"""Tests for the Phase 11 time-of-concentration service."""

import pytest
from services.time_of_concentration import (
    kirpich_tc_minutes,
    compute_time_of_concentration,
    summarise_time_of_concentration,
    TimeOfConcentrationResult,
    KIRPICH_COEFFICIENT,
    KIRPICH_L_EXPONENT,
    KIRPICH_S_EXPONENT,
)


# ---------------- kirpich_tc_minutes ----------------

class TestKirpichTc:
    def test_canonical_case(self):
        # L=1000 m, S=0.01 (1%) -> Tc should be around 30 min
        # Tc = 0.01947 * 1000^0.77 * 0.01^-0.385
        tc = kirpich_tc_minutes(longest_flow_path_m=1000.0, slope_m_per_m=0.01)
        assert 20.0 < tc < 40.0

    def test_steeper_slope_reduces_tc(self):
        tc_steep = kirpich_tc_minutes(longest_flow_path_m=1000.0, slope_m_per_m=0.1)
        tc_gentle = kirpich_tc_minutes(longest_flow_path_m=1000.0, slope_m_per_m=0.01)
        assert tc_steep < tc_gentle

    def test_longer_path_increases_tc(self):
        tc_long = kirpich_tc_minutes(longest_flow_path_m=5000.0, slope_m_per_m=0.01)
        tc_short = kirpich_tc_minutes(longest_flow_path_m=1000.0, slope_m_per_m=0.01)
        assert tc_long > tc_short

    def test_invalid_path_raises(self):
        with pytest.raises(ValueError):
            kirpich_tc_minutes(longest_flow_path_m=0.0, slope_m_per_m=0.01)

    def test_invalid_path_negative_raises(self):
        with pytest.raises(ValueError):
            kirpich_tc_minutes(longest_flow_path_m=-100.0, slope_m_per_m=0.01)

    def test_invalid_slope_zero_raises(self):
        with pytest.raises(ValueError):
            kirpich_tc_minutes(longest_flow_path_m=1000.0, slope_m_per_m=0.0)

    def test_invalid_slope_negative_raises(self):
        with pytest.raises(ValueError):
            kirpich_tc_minutes(longest_flow_path_m=1000.0, slope_m_per_m=-0.01)

    def test_formula_exponents(self):
        # Verify the formula uses correct exponents
        tc_1000_001 = kirpich_tc_minutes(1000.0, 0.001)
        # Should be larger than for 0.01 slope
        tc_1000_01 = kirpich_tc_minutes(1000.0, 0.01)
        assert tc_1000_001 > tc_1000_01


# ---------------- compute_time_of_concentration ----------------

class TestComputeTimeOfConcentration:
    def test_valid_inputs(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=2000.0,
            slope_m_per_m=0.005,
        )
        assert isinstance(result, TimeOfConcentrationResult)
        assert result.data_available is True
        assert result.tc_minutes > 0
        assert result.tc_hours == pytest.approx(result.tc_minutes / 60.0, abs=0.0001)

    def test_method_is_kirpich(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=2000.0,
            slope_m_per_m=0.005,
        )
        assert "Kirpich" in result.method
        assert "0.01947" in result.formula

    def test_longest_flow_path_preserved(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=3500.0,
            slope_m_per_m=0.02,
        )
        assert result.longest_flow_path_m == 3500.0
        assert result.slope_m_per_m == 0.02

    def test_none_path(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=None,
            slope_m_per_m=0.01,
        )
        assert result.data_available is False
        assert result.tc_minutes == 0.0
        assert result.error_message is not None

    def test_zero_path(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=0.0,
            slope_m_per_m=0.01,
        )
        assert result.data_available is False
        assert "invalid" in result.error_message.lower()

    def test_none_slope(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=1000.0,
            slope_m_per_m=None,
        )
        assert result.data_available is False
        assert result.error_message is not None

    def test_zero_slope(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=1000.0,
            slope_m_per_m=0.0,
        )
        assert result.data_available is False
        assert "slope" in result.error_message.lower()

    def test_warnings_mention_kirpich_limitation(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=1000.0,
            slope_m_per_m=0.01,
        )
        text = " ".join(result.warnings)
        assert "Kirpich" in text

    def test_warnings_mention_24h_rainfall(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=1000.0,
            slope_m_per_m=0.01,
        )
        text = " ".join(result.warnings)
        assert "24-hour" in text or "design rainfall" in text


class TestSummariseTimeOfConcentration:
    def test_summary_keys(self):
        result = compute_time_of_concentration(
            longest_flow_path_m=2000.0,
            slope_m_per_m=0.005,
        )
        s = summarise_time_of_concentration(result)
        for key in ["data_available", "method", "formula",
                    "longest_flow_path_m", "slope_m_per_m",
                    "tc_minutes", "tc_hours", "warnings"]:
            assert key in s
