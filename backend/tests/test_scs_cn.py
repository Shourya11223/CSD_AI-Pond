"""Tests for the Phase 11 SCS-CN runoff service."""

import pytest
from services.scs_cn import (
    compute_S,
    compute_Ia,
    compute_runoff_depth,
    compute_runoff_volume,
    lookup_CN,
    get_cn_for_amc,
    compute_scs_cn_runoff,
    summarise_scs_cn,
    SCSCNResult,
    CN_TABLE_II,
    _cn_i_from_cn_ii,
    _cn_iii_from_cn_ii,
)


# ---------------- S, Ia ----------------

class TestSAndIa:
    def test_S_at_CN_100(self):
        # S = 25400/100 - 254 = 0
        assert compute_S(100.0) == pytest.approx(0.0, abs=1e-9)

    def test_S_at_CN_50(self):
        # S = 25400/50 - 254 = 508 - 254 = 254
        assert compute_S(50.0) == pytest.approx(254.0, abs=0.1)

    def test_S_at_CN_75(self):
        # S = 25400/75 - 254 = 338.67 - 254 = 84.67
        S = compute_S(75.0)
        assert 84.0 < S < 85.0

    def test_Ia_is_0_2_S(self):
        S = 100.0
        assert compute_Ia(S) == pytest.approx(20.0)


class TestAMCConversion:
    def test_cn_i_lower_than_cn_ii(self):
        cn_i = _cn_i_from_cn_ii(75.0)
        assert cn_i < 75.0

    def test_cn_iii_higher_than_cn_ii(self):
        cn_iii = _cn_iii_from_cn_ii(75.0)
        assert cn_iii > 75.0

    def test_get_cn_for_amc_ii(self):
        assert get_cn_for_amc(75.0, "II") == pytest.approx(75.0)

    def test_get_cn_for_amc_i(self):
        cn_i = get_cn_for_amc(75.0, "I")
        assert cn_i < 75.0

    def test_get_cn_for_amc_iii(self):
        cn_iii = get_cn_for_amc(75.0, "III")
        assert cn_iii > 75.0


# ---------------- Runoff depth Q ----------------

class TestRunoffDepth:
    def test_Q_zero_when_P_below_Ia(self):
        # CN=75 -> S~84.7, Ia~16.9.  P=10 < Ia -> Q=0
        assert compute_runoff_depth(P=10.0, cn=75.0) == pytest.approx(0.0)

    def test_Q_positive_when_P_above_Ia(self):
        # CN=75, S~84.7, Ia~16.9. P=100 > Ia -> Q>0
        Q = compute_runoff_depth(P=100.0, cn=75.0)
        assert Q > 0.0
        assert Q < 100.0

    def test_Q_zero_for_zero_CN(self):
        assert compute_runoff_depth(P=100.0, cn=0.0) == 0.0

    def test_Q_zero_for_negative_CN(self):
        assert compute_runoff_depth(P=100.0, cn=-5.0) == 0.0

    def test_Q_increases_with_P(self):
        Q_low = compute_runoff_depth(P=50.0, cn=75.0)
        Q_high = compute_runoff_depth(P=200.0, cn=75.0)
        assert Q_high > Q_low

    def test_Q_increases_with_CN(self):
        Q_low_cn = compute_runoff_depth(P=100.0, cn=50.0)
        Q_high_cn = compute_runoff_depth(P=100.0, cn=90.0)
        assert Q_high_cn > Q_low_cn

# ---------------- Runoff volume V ----------------

class TestRunoffVolume:
    def test_volume_formula(self):
        # Q=10 mm, A=1000 m2 -> V = (10/1000)*1000 = 10 m3
        V = compute_runoff_volume(Q_mm=10.0, catchment_area_m2=1000.0)
        assert V == pytest.approx(10.0)

    def test_volume_zero_when_Q_zero(self):
        V = compute_runoff_volume(Q_mm=0.0, catchment_area_m2=1000.0)
        assert V == 0.0

    def test_volume_scales_with_area(self):
        V_small = compute_runoff_volume(Q_mm=50.0, catchment_area_m2=1000.0)
        V_large = compute_runoff_volume(Q_mm=50.0, catchment_area_m2=10_000.0)
        assert V_large == 10.0 * V_small


# ---------------- CN lookup table ----------------

class TestCNTable:
    def test_built_has_all_hsg(self):
        for hsg in ["A", "B", "C", "D"]:
            assert lookup_CN("built", hsg) is not None
            assert lookup_CN("built", hsg) > 50

    def test_forest_has_all_hsg(self):
        for hsg in ["A", "B", "C", "D"]:
            assert lookup_CN("forest", hsg) is not None

    def test_water_always_99(self):
        for hsg in ["A", "B", "C", "D"]:
            assert lookup_CN("water", hsg) == 99

    def test_unknown_has_fallback(self):
        for hsg in ["A", "B", "C", "D"]:
            assert lookup_CN("unknown", hsg) is not None

    def test_missing_class_returns_none(self):
        assert lookup_CN("nonexistent_class", "A") is None


# ---------------- compute_scs_cn_runoff (integration) ----------------

class TestComputeSCSCNRunoff:
    def test_land_cover_unavailable_returns_unavailable(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={"data_available": False},
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is False
        assert "land cover" in result.error_message.lower()

    def test_soil_group_unavailable_returns_unavailable(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [{"land_cover_class": "forest", "fraction": 1.0}],
            },
            soil_group_summary={"data_available": False},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is False
        assert "soil" in result.error_message.lower() or "HSG" in result.error_message

    def test_rainfall_none_returns_unavailable(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [{"land_cover_class": "forest", "fraction": 1.0}],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=None,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is False
        assert "rainfall" in result.error_message.lower()

    def test_rainfall_zero_returns_unavailable(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [{"land_cover_class": "forest", "fraction": 1.0}],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=0.0,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is False

    def test_valid_inputs_returns_available(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [
                    {"land_cover_class": "forest", "fraction": 1.0}
                ],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is True
        assert result.soil_group == "B"
        assert result.rainfall_P_mm == 100.0
        assert result.weighted_CN is not None
        assert result.S_mm is not None
        assert result.Ia_mm is not None
        assert result.runoff_depth_mm is not None
        assert result.runoff_volume_m3 is not None
        assert result.runoff_volume_m3 > 0.0

    def test_area_weighted_CN_forest_B(self):
        # Forest, HSG B -> CN=55 (AMC II)
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [
                    {"land_cover_class": "forest", "fraction": 1.0}
                ],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        # CN for forest/B = 55
        assert result.weighted_CN == pytest.approx(55.0, abs=0.5)

    def test_area_weighted_CN_mixed_land_cover(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [
                    {"land_cover_class": "built", "fraction": 0.5},
                    {"land_cover_class": "forest", "fraction": 0.5},
                ],
            },
            soil_group_summary={"data_available": True, "soil_group": "A"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        # built/A=77, forest/A=30 -> weighted = 0.5*77 + 0.5*30 = 53.5
        assert 53.0 < result.weighted_CN < 54.0

    def test_runoff_volume_uses_catchment_area(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [
                    {"land_cover_class": "forest", "fraction": 1.0}
                ],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,  # 100 ha
        )
        # Verify volume = Q/1000 * area (allow rounding to 2 dp)
        Q = result.runoff_depth_mm
        V_expected = (Q / 1000.0) * 1_000_000.0
        assert result.runoff_volume_m3 == pytest.approx(V_expected, abs=0.01)

    def test_cn_contributions_populated(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [
                    {"land_cover_class": "forest", "fraction": 1.0}
                ],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        assert len(result.CN_contributions) == 1
        assert result.CN_contributions[0].land_cover_class == "forest"

    def test_warnings_contains_area_weighted_note(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [
                    {"land_cover_class": "forest", "fraction": 1.0}
                ],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        assert any("area-weighted" in w.lower() for w in result.warnings)

    def test_unknown_class_falls_back_to_conservative_CN(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [
                    {"land_cover_class": "nonexistent_class", "fraction": 1.0}
                ],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        assert result.data_available is True
        # Falls back to unknown class -> conservative CN around 75
        assert result.weighted_CN is not None
        assert result.weighted_CN > 0


class TestSummariseSCSCN:
    def test_summary_keys(self):
        result = compute_scs_cn_runoff(
            land_cover_summary={
                "data_available": True,
                "land_cover_classes": [
                    {"land_cover_class": "forest", "fraction": 1.0}
                ],
            },
            soil_group_summary={"data_available": True, "soil_group": "B"},
            rainfall_P_mm=100.0,
            catchment_area_m2=1_000_000.0,
        )
        s = summarise_scs_cn(result)
        for key in ["data_available", "source", "weighted_CN",
                    "S_mm", "Ia_mm", "runoff_depth_mm", "runoff_volume_m3",
                    "catchment_area_m2", "warnings", "CN_contributions"]:
            assert key in s
