"""Tests for the Phase 11 pond-adequacy service."""

import pytest
from services.pond_adequacy import (
    compute_pond_adequacy,
    summarise_pond_adequacy,
    PondAdequacyResult,
    ADEQUACY_RATIO_PASS,
    MARGINAL_RATIO,
)


# ---------------- compute_pond_adequacy ----------------

class TestComputePondAdequacy:
    def test_storage_greater_than_runoff_pass(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=2000.0,
        )
        assert result.data_available is True
        assert result.status == "pass"
        assert result.adequacy_ratio == pytest.approx(2.0)

    def test_storage_equal_to_runoff_pass(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=1000.0,
        )
        assert result.status == "pass"
        assert result.adequacy_ratio == pytest.approx(1.0)

    def test_storage_less_than_runoff_marginal(self):
        # ratio = 0.8 -> marginal
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=800.0,
        )
        assert result.status == "marginal"
        assert result.adequacy_ratio == pytest.approx(0.8)

    def test_storage_very_small_fail(self):
        # ratio = 0.5 -> fail
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=500.0,
        )
        assert result.status == "fail"
        assert result.adequacy_ratio == pytest.approx(0.5)

    def test_zero_runoff_pass(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=0.0,
            available_storage_m3=500.0,
        )
        assert result.data_available is True
        assert result.status == "pass"
        # adequacy ratio is inf when storage > 0 and runoff == 0
        assert result.adequacy_ratio == float("inf") or result.adequacy_ratio > 1e10

    def test_zero_runoff_with_zero_storage(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=0.0,
            available_storage_m3=0.0,
        )
        # runoff==0 -> trivially passes; ratio=0 since storage==0
        assert result.data_available is True
        assert result.status == "pass"

    def test_zero_storage_fail(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=0.0,
        )
        assert result.data_available is True
        assert result.status == "fail"
        assert result.adequacy_ratio == 0.0

    def test_none_runoff_unavailable(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=None,
            available_storage_m3=2000.0,
        )
        assert result.data_available is False
        assert result.status == "unavailable"
        assert "runoff" in result.error_message.lower()

    def test_none_storage_unavailable(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=None,
        )
        assert result.data_available is False
        assert result.status == "unavailable"
        assert "storage" in result.error_message.lower()

    def test_both_none_unavailable(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=None,
            available_storage_m3=None,
        )
        assert result.data_available is False
        assert result.status == "unavailable"

    def test_ratio_correctness(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=2500.0,
            available_storage_m3=1000.0,
        )
        assert result.adequacy_ratio == pytest.approx(0.4)

    def test_warnings_include_thresholds(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=2000.0,
        )
        text = " ".join(result.warnings)
        assert "threshold" in text.lower() or "0.75" in text or "1.0" in text

    def test_thresholds_are_exposed(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=2000.0,
        )
        assert result.threshold_pass == ADEQUACY_RATIO_PASS
        assert result.threshold_marginal == MARGINAL_RATIO

    def test_warnings_mention_no_safety_factor(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=2000.0,
        )
        text = " ".join(result.warnings)
        assert "safety factor" in text.lower()


class TestSummarisePondAdequacy:
    def test_summary_keys(self):
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=2000.0,
        )
        s = summarise_pond_adequacy(result)
        for key in ["data_available", "runoff_volume_m3", "available_storage_m3",
                    "adequacy_ratio", "status", "threshold_pass",
                    "threshold_marginal", "warnings"]:
            assert key in s
