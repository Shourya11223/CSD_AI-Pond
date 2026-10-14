"""Tests for the Phase 11 soil-group service."""

import pytest

from services.soil_group import (
    get_soil_group,
    summarise_soil_group,
    SoilGroupResult,
    _attempt_provider_lookup,
    _default_warnings,
    CANDIDATE_SOURCES,
)


# ---------------- Top-level API ----------------

class TestGetSoilGroup:
    def test_returns_unavailable_result(self):
        """No real provider is connected, so result must be unavailable."""
        result = get_soil_group(bbox=(10.0, 76.0, 11.0, 77.0))
        assert isinstance(result, SoilGroupResult)
        assert result.data_available is False
        assert result.soil_group is None
        assert result.source == "unavailable"

    def test_candidate_sources_preserved(self):
        result = get_soil_group(bbox=(10.0, 76.0, 11.0, 77.0))
        assert len(result.candidate_sources_considered) == len(CANDIDATE_SOURCES)
        for src in result.candidate_sources_considered:
            assert src["status"] == "not_connected"

    def test_warnings_contain_unavailable_notice(self):
        result = get_soil_group(bbox=(10.0, 76.0, 11.0, 77.0))
        text = " ".join(result.warnings)
        assert "HSG" in text or "soil" in text.lower()

    def test_bbox_preserved(self):
        result = get_soil_group(bbox=(10.0, 76.0, 11.0, 77.0))
        assert result.bbox is not None
        assert result.bbox["min_lat"] == 10.0

    def test_error_message_not_none(self):
        result = get_soil_group(bbox=(10.0, 76.0, 11.0, 77.0))
        assert result.error_message is not None
        assert len(result.error_message) > 10

    def test_empty_bbox_still_returns_unavailable(self):
        result = get_soil_group(bbox=None)
        assert result.data_available is False
        assert result.soil_group is None


class TestAttemptProviderLookup:
    def test_returns_none_with_explanatory_error(self):
        dom, fracs, err = _attempt_provider_lookup((0, 0, 1, 1))
        assert dom is None
        assert fracs is None
        assert err is not None
        assert "not_connected" in err or "provider" in err.lower()


class TestDefaultWarnings:
    def test_returns_list_of_strings(self):
        warnings = _default_warnings()
        assert isinstance(warnings, list)
        assert all(isinstance(w, str) for w in warnings)
        assert len(warnings) > 0


class TestSummariseSoilGroup:
    def test_summary_keys(self):
        result = get_soil_group()
        s = summarise_soil_group(result)
        assert "data_available" in s
        assert "source" in s
        assert "lookup_method" in s
        assert "soil_group" in s
        assert "candidate_sources_considered" in s
        assert "warnings" in s
        assert "error_message" in s
        assert "soil_group_fractions" in s
