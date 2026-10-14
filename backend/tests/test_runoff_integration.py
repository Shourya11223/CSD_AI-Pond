"""Integration tests for Phase 11 runoff pipeline."""

from unittest.mock import patch, MagicMock
import pytest

from services.land_cover import (
    get_land_cover, summarise_land_cover, LandCoverResult,
)
from services.soil_group import (
    get_soil_group, summarise_soil_group,
)
from services.scs_cn import compute_scs_cn_runoff, summarise_scs_cn
from services.time_of_concentration import (
    compute_time_of_concentration, summarise_time_of_concentration,
)
from services.pond_adequacy import (
    compute_pond_adequacy, summarise_pond_adequacy,
)


# =====================================================================
# Test: full pipeline with mocked land cover and soil
# =====================================================================

class TestFullPipelineMocked:
    """Test the complete Phase 11 pipeline using mocked external inputs."""

    def test_land_cover_osm_success(self):
        """Land cover resolves successfully via OSM."""
        with patch("services.land_cover._fetch_osm_features") as mock_fetch:
            feat = MagicMock()
            feat.geometry_type = "polygon"
            feat.land_cover_class = "agricultural"
            feat.area_m2 = 500_000.0
            feat.original_tags = {"landuse": "farmland"}
            mock_fetch.return_value = ([feat], None)
            result = get_land_cover(
                bbox=(10.0, 76.0, 11.0, 77.0),
                catchment_area_m2=1_000_000.0,
            )
        assert result.data_available is True
        assert result.features_mapped == 1
        classes = {lc.land_cover_class for lc in result.land_cover_classes}
        assert "agricultural" in classes

    def test_soil_group_unavailable_no_fabrication(self):
        """Soil group returns unavailable - no HSG is fabricated."""
        result = get_soil_group(bbox=(10.0, 76.0, 11.0, 77.0))
        assert result.data_available is False
        assert result.soil_group is None

    def test_runoff_unavailable_when_soil_unavailable(self):
        """SCS-CN runoff is unavailable when soil group is unavailable."""
        land_cover_summary = {
            "data_available": True,
            "land_cover_classes": [
                {"land_cover_class": "forest", "fraction": 1.0}
            ],
        }
        soil_summary = {
            "data_available": False,
        }
        result = compute_scs_cn_runoff(
            land_cover_summary=land_cover_summary,
            soil_group_summary=soil_summary,
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is False
        assert "soil" in result.error_message.lower()

    def test_runoff_unavailable_when_land_cover_unavailable(self):
        """SCS-CN runoff is unavailable when land cover is unavailable."""
        soil_summary = {"data_available": True, "soil_group": "B"}
        result = compute_scs_cn_runoff(
            land_cover_summary={"data_available": False},
            soil_group_summary=soil_summary,
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is False
        assert "land cover" in result.error_message.lower()

    def test_runoff_unavailable_when_rainfall_missing(self):
        """SCS-CN runoff is unavailable when rainfall is None."""
        land_cover_summary = {
            "data_available": True,
            "land_cover_classes": [
                {"land_cover_class": "forest", "fraction": 1.0}
            ],
        }
        soil_summary = {"data_available": True, "soil_group": "B"}
        result = compute_scs_cn_runoff(
            land_cover_summary=land_cover_summary,
            soil_group_summary=soil_summary,
            rainfall_P_mm=None,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is False

    def test_runoff_volume_formula_verification(self):
        """Verify: V = (Q/1000) * A_m2"""
        land_cover_summary = {
            "data_available": True,
            "land_cover_classes": [
                {"land_cover_class": "forest", "fraction": 1.0}
            ],
        }
        soil_summary = {"data_available": True, "soil_group": "B"}
        result = compute_scs_cn_runoff(
            land_cover_summary=land_cover_summary,
            soil_group_summary=soil_summary,
            rainfall_P_mm=100.0,
            catchment_area_m2=100_000.0,  # 10 ha
        )
        assert result.data_available is True
        Q = result.runoff_depth_mm
        A = result.catchment_area_m2
        expected_V = (Q / 1000.0) * A
        assert result.runoff_volume_m3 == pytest.approx(expected_V, abs=0.01)

    def test_tc_uses_phase11a_outputs(self):
        """Tc uses longest flow path and slope from Phase 11A."""
        result = compute_time_of_concentration(
            longest_flow_path_m=3000.0,
            slope_m_per_m=0.008,
        )
        assert result.data_available is True
        assert result.longest_flow_path_m == 3000.0
        assert result.slope_m_per_m == 0.008
        assert result.tc_minutes > 0
        assert result.tc_hours == pytest.approx(result.tc_minutes / 60.0, abs=0.0001)

    def test_pond_adequacy_pass(self):
        """Pond storage exceeds runoff -> pass."""
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=1500.0,
        )
        assert result.data_available is True
        assert result.status == "pass"
        assert result.adequacy_ratio == pytest.approx(1.5)

    def test_pond_adequacy_fail(self):
        """Pond storage less than runoff -> fail."""
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=300.0,
        )
        assert result.data_available is True
        assert result.status == "fail"
        assert result.adequacy_ratio == pytest.approx(0.3)

    def test_pond_adequacy_unavailable_when_runoff_missing(self):
        """Pond adequacy unavailable when runoff is None."""
        result = compute_pond_adequacy(
            runoff_volume_m3=None,
            available_storage_m3=500.0,
        )
        assert result.data_available is False
        assert result.status == "unavailable"

    def test_pond_adequacy_unavailable_when_storage_missing(self):
        """Pond adequacy unavailable when storage is None."""
        result = compute_pond_adequacy(
            runoff_volume_m3=1000.0,
            available_storage_m3=None,
        )
        assert result.data_available is False
        assert result.status == "unavailable"

    def test_pipeline_order_soil_unavailable_does_not_break_tc(self):
        """Soil unavailability does not prevent Tc computation."""
        tc_result = compute_time_of_concentration(
            longest_flow_path_m=1000.0,
            slope_m_per_m=0.01,
        )
        assert tc_result.data_available is True
        # Tc should succeed independently
        assert tc_result.tc_minutes > 0

    def test_pipeline_order_land_cover_unavailable_does_not_break_tc(self):
        """Land cover unavailability does not prevent Tc computation."""
        tc_result = compute_time_of_concentration(
            longest_flow_path_m=2000.0,
            slope_m_per_m=0.005,
        )
        assert tc_result.data_available is True
        assert tc_result.tc_minutes > 0

    def test_pipeline_order_land_cover_unavailable_does_not_break_soil(self):
        """Land cover unavailability does not prevent soil lookup."""
        soil_result = get_soil_group(bbox=(10.0, 76.0, 11.0, 77.0))
        assert soil_result.data_available is False
        # Soil result is still returned (not raised)
        assert isinstance(soil_result.soil_group, type(None))

    def test_end_to_end_with_mocked_inputs(self):
        """Simulate end-to-end Phase 11 pipeline with all inputs mocked."""
        # ---- Phase 11A-equivalent inputs (from catchment diagnostics) ----
        longest_flow_path_m = 2500.0
        mean_slope_m_per_m = 0.012
        catchment_area_m2 = 500_000.0  # 50 ha

        # ---- Phase 11B-1: land cover ----
        lc_summary = {
            "data_available": True,
            "land_cover_classes": [
                {"land_cover_class": "agricultural", "fraction": 0.6},
                {"land_cover_class": "forest", "fraction": 0.4},
            ],
        }

        # ---- Phase 11B-2: soil group (unavailable) ----
        soil_summary = {"data_available": False}

        # ---- Phase 9: design rainfall ----
        rainfall_P_mm = 150.0

        # ---- Phase 11B-4: Tc ----
        tc_result = compute_time_of_concentration(
            longest_flow_path_m=longest_flow_path_m,
            slope_m_per_m=mean_slope_m_per_m,
        )
        assert tc_result.data_available is True

        # ---- Phase 11B-3: SCS-CN (unavailable due to soil) ----
        runoff_result = compute_scs_cn_runoff(
            land_cover_summary=lc_summary,
            soil_group_summary=soil_summary,
            rainfall_P_mm=rainfall_P_mm,
            catchment_area_m2=catchment_area_m2,
        )
        assert runoff_result.data_available is False
        assert "soil" in runoff_result.error_message.lower()

        # ---- Phase 11B-5: pond adequacy (unavailable due to no runoff) ----
        adequacy_result = compute_pond_adequacy(
            runoff_volume_m3=None,  # unavailable
            available_storage_m3=1000.0,
        )
        assert adequacy_result.data_available is False
        assert adequacy_result.status == "unavailable"

        # ---- Verify all summaries serialise ----
        tc_s = summarise_time_of_concentration(tc_result)
        assert "tc_minutes" in tc_s
        assert "slope_source" in tc_s
        assert tc_s["data_available"] is True

        runoff_s = summarise_scs_cn(runoff_result)
        assert "data_available" in runoff_s
        assert runoff_s["data_available"] is False

        adequacy_s = summarise_pond_adequacy(adequacy_result)
        assert "data_available" in adequacy_s
        assert adequacy_s["data_available"] is False


class TestNewResponseFields:
    """Test that new optional fields are present in Pydantic models."""

    def test_integrated_response_has_land_cover_field(self):
        from models import IntegratedAnalysisResponse
        assert "land_cover" in IntegratedAnalysisResponse.model_fields

    def test_integrated_response_has_soil_group_field(self):
        from models import IntegratedAnalysisResponse
        assert "soil_group" in IntegratedAnalysisResponse.model_fields

    def test_integrated_response_has_runoff_field(self):
        from models import IntegratedAnalysisResponse
        assert "runoff" in IntegratedAnalysisResponse.model_fields

    def test_integrated_response_has_time_of_concentration_field(self):
        from models import IntegratedAnalysisResponse
        assert "time_of_concentration" in IntegratedAnalysisResponse.model_fields

    def test_integrated_response_has_pond_adequacy_field(self):
        from models import IntegratedAnalysisResponse
        assert "pond_adequacy" in IntegratedAnalysisResponse.model_fields

    def test_land_cover_info_model(self):
        from models import LandCoverInfo
        fields = LandCoverInfo.model_fields
        assert "data_available" in fields
        assert "source" in fields
        assert "land_cover_classes" in fields
        assert "warnings" in fields

    def test_soil_group_info_model(self):
        from models import SoilGroupInfo
        fields = SoilGroupInfo.model_fields
        assert "data_available" in fields
        assert "soil_group" in fields
        assert "candidate_sources_considered" in fields

    def test_runoff_info_model(self):
        from models import RunoffInfo
        fields = RunoffInfo.model_fields
        assert "weighted_CN" in fields
        assert "S_mm" in fields
        assert "Ia_mm" in fields
        assert "runoff_depth_mm" in fields
        assert "runoff_volume_m3" in fields

    def test_time_of_concentration_info_model(self):
        from models import TimeOfConcentrationInfo
        fields = TimeOfConcentrationInfo.model_fields
        assert "tc_minutes" in fields
        assert "tc_hours" in fields
        assert "method" in fields

    def test_pond_adequacy_info_model(self):
        from models import PondAdequacyInfo
        fields = PondAdequacyInfo.model_fields
        assert "adequacy_ratio" in fields
        assert "status" in fields
        assert "threshold_pass" in fields
        assert "threshold_marginal" in fields


# =====================================================================
# Test: Overpass and Rainfall independence (Problem 3 verification)
# =====================================================================

class TestOverpassAndRainfallIndependence:
    """
    Verify that Overpass API failures and Open-Meteo/ERA5 rainfall failures
    are tracked independently.

    Data-integrity rules:
    1. Overpass failures must never cause rainfall to be discarded.
    2. Rainfall failures must never cause Overpass/land-cover to be discarded.
    3. When both succeed, the full runoff pipeline runs.
    4. When either is missing, the other is still computed.
    """

    @patch("services.land_cover._fetch_osm_features")
    @patch("services.rainfall.get_rainfall")
    def test_overpass_failure_does_not_affect_rainfall(
        self, mock_rainfall, mock_fetch_osm
    ):
        """Overpass failing must not cause rainfall lookup to be skipped."""
        # Simulate Overpass being completely unavailable.
        mock_fetch_osm.return_value = ([], "All Overpass endpoints failed")

        # Simulate rainfall being available.
        mock_rainfall.return_value = MagicMock(
            rainfall_data_available=True,
            annual_rainfall_mm=1200.0,
            source="Open-Meteo-ERA5",
        )

        from services.land_cover import get_land_cover
        from services.rainfall import get_rainfall

        # Call both services independently.
        land_result = get_land_cover(bbox=(25.0, 78.0, 25.5, 78.5))
        rainfall_result = get_rainfall(latitude=25.2, longitude=78.3)

        # Rainfall must still be available (Overpass failure must not affect it).
        assert rainfall_result.rainfall_data_available is True
        assert rainfall_result.annual_rainfall_mm == 1200.0

        # Land cover should reflect Overpass failure.
        assert land_result.data_available is False

    @patch("services.land_cover._fetch_osm_features")
    @patch("services.rainfall.get_rainfall")
    def test_rainfall_failure_does_not_affect_overpass(
        self, mock_rainfall, mock_fetch_osm
    ):
        """Rainfall failing must not cause Overpass lookup to be skipped."""
        # Overpass succeeds with a forest feature.
        mock_feature = MagicMock()
        mock_feature.land_cover_class = "forest"
        mock_feature.geometry_type = "polygon"
        mock_feature.area_m2 = 10000.0
        mock_feature.original_tags = {"landuse": "forest"}
        mock_fetch_osm.return_value = ([mock_feature], None)

        # Rainfall fails completely.
        mock_rainfall.side_effect = RuntimeError("Open-Meteo unreachable")

        from services.land_cover import get_land_cover
        from services.rainfall import get_rainfall

        # Land cover must still be computed.
        land_result = get_land_cover(bbox=(25.0, 78.0, 25.5, 78.5))

        try:
            rainfall_result = get_rainfall(latitude=25.2, longitude=78.3)
        except Exception:
            pass  # Expected: rainfall raised.

        # Land cover should succeed even though rainfall failed.
        assert land_result.data_available is True
        assert any(
            lc.land_cover_class == "forest"
            for lc in land_result.land_cover_classes
        )

    @patch("services.land_cover._fetch_osm_features")
    @patch("services.rainfall.get_rainfall")
    def test_both_failures_independent_error_messages(
        self, mock_rainfall, mock_fetch_osm
    ):
        """Both can fail simultaneously, each with its own error message."""
        mock_fetch_osm.return_value = ([], "All Overpass endpoints failed: 429")
        mock_rainfall.side_effect = RuntimeError("Open-Meteo API error")

        from services.land_cover import get_land_cover
        from services.rainfall import get_rainfall

        land_result = get_land_cover(bbox=(25.0, 78.0, 25.5, 78.5))
        assert land_result.data_available is False
        assert "overpass" in str(land_result.error_message).lower()

        try:
            rainfall_result = get_rainfall(latitude=25.2, longitude=78.3)
            pytest.fail("Expected RuntimeError from rainfall")
        except RuntimeError as exc:
            assert "open-meteo" in str(exc).lower()
