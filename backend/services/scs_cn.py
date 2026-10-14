"""
SCS-CN Runoff Service (Phase 11 - Part 3).

Implements the USDA NRCS (formerly SCS) Curve Number method for estimating
given rainfall depth, land cover, and hydrologic soil group (HSG).

Formulae (USDA NRCS National Engineering Handbook, Part 630)
-------------------------------------------------------------------
1. Potential retention S (mm):     S = 25400/CN - 254
2. Initial abstraction Ia (mm):   Ia = 0.2 * S
3. Runoff depth Q (mm):
       If P <= Ia:  Q = 0
       If P > Ia:   Q = (P - Ia)^2 / (P + 0.8*S)
4. Runoff volume V (m3):
       V = (Q / 1000) * A_m2

AMC Handling
-------------
AMC conditions modify CN to account for soil moisture:
  AMC I: CN_I = CN_II / (2.33 - 0.0136*CN_II)
  AMC III: CN_III = CN_II / (0.427 + 0.00573*CN_II)
AMC II is the default.  AMC I and AMC III are provided as options.

Area-Weighted CN
-----------------
When multiple land-cover classes are present, an area-weighted CN is
a computed: CN_w = sum(f_i * CN_i)
This is an approximation, not a spatially distributed simulation.
See the warnings field in the result.

Data Dependencies
------------------
This service requires both:
  - land_cover: from services.land_cover
  - soil_group: from services.soil_group
If either is unavailable, the result is marked unavailable rather than
fabricating CN or runoff values.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CN lookup table: CN_II values for (land_cover_class, HSG)
# Source: USDA NRCS National Engineering Handbook, Part 630, Table 9-1
# and engineering judgment for classes not explicitly in NEH-4.
#
# IMPORTANT: These values are engineering assumptions based on published
# tables.  They are NOT observed data.  Always consult local guidelines
# for India-specific values.
# ---------------------------------------------------------------------------

# Keys are the project land_cover classes from land_cover.py
# Values: dict of HSG -> CN_II
# absent entries default to None (unavailable)
CN_TABLE_II: Dict[str, Dict[str, Optional[int]]] = {
    # --- Built / urban ---
    "built": {
        "A": 77,   # Open spaces, lawns, parks (impervious surfaces dominate)
        "B": 85,   # Impervious + moderate permeability
        "C": 90,   # Dense impervious
        "D": 92,   # Very dense impervious
    },
    # --- Agricultural ---
    "agricultural": {
        "A": 72,   # Fallow / straight row, bare soil
        "B": 81,   # Fallow / straight row
        "C": 88,   # Fallow / straight row
        "D": 91,   # Fallow / straight row
    },
    # --- Forest ---
    "forest": {
        "A": 30,   # Good cover
        "B": 55,   # Good cover
        "C": 70,   # Good cover
        "D": 77,   # Good cover
    },
    # --- Grassland / pasture ---
    "grassland": {
        "A": 49,   # Good condition
        "B": 69,   # Good condition
        "C": 79,   # Good condition
        "D": 84,   # Good condition
    },
    # --- Wetland ---
    "wetland": {
        "A": 78,   # Poorly drained, high water table
        "B": 85,
        "C": 89,
        "D": 92,
    },
    # --- Water ---
    "water": {
        "A": 99,   # Direct runoff; no infiltration
        "B": 99,
        "C": 99,
        "D": 99,
    },
    # --- Bare ---
    "bare": {
        "A": 77,   # Assumed bare soil
        "B": 86,
        "C": 91,
        "D": 94,
    },
    # --- Unknown ---
    "unknown": {
        "A": 72,   # Conservative estimate
        "B": 81,
        "C": 88,
        "D": 91,
    },
}

AMCType = Literal["I", "II", "III"]


def _cn_i_from_cn_ii(cn_ii: int) -> float:
    """Convert CN_II to CN_I (AMC I, dry conditions)."""
    return cn_ii / (2.33 - 0.0136 * cn_ii)


def _cn_iii_from_cn_ii(cn_ii: int) -> float:
    """Convert CN_II to CN_III (AMC III, wet conditions)."""
    return cn_ii / (0.427 + 0.00573 * cn_ii)


def get_cn_for_amc(cn_ii: int, amc: AMCType = "II") -> float:
    """Return the CN for the specified AMC condition."""
    if amc == "I":
        return _cn_i_from_cn_ii(cn_ii)
    elif amc == "III":
        return _cn_iii_from_cn_ii(cn_ii)
    return float(cn_ii)


def compute_S(cn: float) -> float:
    """Potential retention S (mm) from curve number."""
    return 25400.0 / max(cn, 0.01) - 254.0


def compute_Ia(S: float) -> float:
    """Initial abstraction Ia (mm) = 0.2 * S."""
    return 0.2 * S


def compute_runoff_depth(P: float, cn: float) -> float:
    """Compute runoff depth Q (mm) for rainfall P (mm) and CN.

    Uses: S = 25400/CN - 254
          Ia = 0.2*S
          Q = (P - Ia)^2 / (P + 0.8*S)   for P > Ia
          Q = 0                              for P <= Ia
    """
    if cn <= 0:
        return 0.0
    S = compute_S(cn)
    if S <= 0:
        return 0.0
    Ia = compute_Ia(S)
    if P <= Ia:
        return 0.0
    Q = (P - Ia) ** 2 / (P + 0.8 * S)
    return max(0.0, Q)


def compute_runoff_volume(Q_mm: float, catchment_area_m2: float) -> float:
    """Compute runoff volume V (m3) from depth Q (mm) and area (m2).

    V = (Q / 1000) * A_m2
    """
    return (Q_mm / 1000.0) * catchment_area_m2


def lookup_CN(
    land_cover_class: str,
    soil_group: str,
) -> Optional[int]:
    """Look up CN_II from the table.  Returns None if not available."""
    hsg_table = CN_TABLE_II.get(land_cover_class, {})
    return hsg_table.get(soil_group, None)


@dataclass
class LandCoverCNContribution:
    """CN contribution from a single land-cover class fraction."""
    land_cover_class: str
    soil_group: str
    cn_ii: int
    cn_amc: float
    area_fraction: float
    weighted_cn: float
    warning: Optional[str] = None


@dataclass
class SCSCNResult:
    """
    SCS-CN runoff analysis result.

    Attributes
    ----------
    data_available : bool
        True when all required inputs (land_cover, soil_group, rainfall)
        were available.
    source : str
        Always "SCS-CN (USDA NRCS NEH-630)".
    method : str
        Description of the CN lookup and area-weighting methodology.
    rainfall_P_mm : Optional[float]
        Design rainfall depth P (mm) used.
    amc_condition : str
        Antecedent moisture condition used (I, II, or III).
    soil_group : Optional[str]
        HSG used (from soil_group service).  None if unavailable.
    weighted_CN : Optional[float]
        Area-weighted CN for the catchment.  None if unavailable.
    CN_contributions : List[LandCoverCNContribution]
        Per-class CN breakdown.
    S_mm : Optional[float]
        Potential retention S (mm).  None if unavailable.
    Ia_mm : Optional[float]
        Initial abstraction Ia (mm).  None if unavailable.
    runoff_depth_mm : Optional[float]
        Runoff depth Q (mm).  None if unavailable.
    runoff_volume_m3 : Optional[float]
        Runoff volume V (m3).  None if unavailable.
    catchment_area_m2 : float
        Catchment area (m2) used to compute volume.
    catchment_area_ha : float
        Catchment area (ha) used.
    warnings : List[str]
        Methodology warnings.
    error_message : Optional[str]
        Error description when data_available is False.
    """
    data_available: bool = False
    source: str = "SCS-CN (USDA NRCS NEH-630)"
    method: str = (
        "USDA NRCS Curve Number method per NEH-630. CN_II lookup from "
        "NEH-4 Table 9-1. AMC conversion via published formulas. "
        "Area-weighted CN when multiple land-cover classes present."
    )
    rainfall_P_mm: Optional[float] = None
    amc_condition: str = "II"
    soil_group: Optional[str] = None
    weighted_CN: Optional[float] = None
    CN_contributions: List[LandCoverCNContribution] = field(default_factory=list)
    S_mm: Optional[float] = None
    Ia_mm: Optional[float] = None
    runoff_depth_mm: Optional[float] = None
    runoff_volume_m3: Optional[float] = None
    catchment_area_m2: float = 0.0
    catchment_area_ha: float = 0.0
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "data_available": self.data_available,
            "source": self.source,
            "method": self.method,
            "rainfall_P_mm": (round(self.rainfall_P_mm, 2)
                               if self.rainfall_P_mm is not None else None),
            "amc_condition": self.amc_condition,
            "soil_group": self.soil_group,
            "weighted_CN": (round(self.weighted_CN, 1)
                           if self.weighted_CN is not None else None),
            "CN_contributions": [
                {
                    "land_cover_class": c.land_cover_class,
                    "soil_group": c.soil_group,
                    "cn_ii": c.cn_ii,
                    "cn_amc": round(c.cn_amc, 1),
                    "area_fraction": round(c.area_fraction, 4),
                    "weighted_cn": round(c.weighted_cn, 2),
                    "warning": c.warning,
                }
                for c in self.CN_contributions
            ],
            "S_mm": round(self.S_mm, 2) if self.S_mm is not None else None,
            "Ia_mm": round(self.Ia_mm, 2) if self.Ia_mm is not None else None,
            "runoff_depth_mm": (round(self.runoff_depth_mm, 2)
                                if self.runoff_depth_mm is not None else None),
            "runoff_volume_m3": (round(self.runoff_volume_m3, 2)
                                 if self.runoff_volume_m3 is not None else None),
            "catchment_area_m2": round(self.catchment_area_m2, 2),
            "catchment_area_ha": round(self.catchment_area_ha, 2),
            "warnings": self.warnings,
            "error_message": self.error_message,
        }


def compute_scs_cn_runoff(
    land_cover_summary: Optional[dict],
    soil_group_summary: Optional[dict],
    rainfall_P_mm: Optional[float],
    catchment_area_m2: float,
    amc_condition: AMCType = "II",
) -> SCSCNResult:
    """
    Compute SCS-CN runoff given land cover, soil group, and rainfall depth.

    Parameters
    ----------
    land_cover_summary : dict, optional
        Summary dict from summarise_land_cover().  Required fields:
        - land_cover_classes: list of {land_cover_class, fraction}
        - data_available: bool
    soil_group_summary : dict, optional
        Summary dict from summarise_soil_group().  Required fields:
        - soil_group: str (A/B/C/D) or None
        - data_available: bool
    rainfall_P_mm : float, optional
        24-hour design rainfall depth P (mm).
    catchment_area_m2 : float
        Catchment area in square metres.
    amc_condition : str
        AMC condition: "I", "II", or "III".  Default "II".

    Returns
    -------
    SCSCNResult
        Structured result with runoff estimates or an unavailable result.
    """
    catchment_area_ha = catchment_area_m2 / 10000.0

    # Check land cover availability
    if land_cover_summary is None or not land_cover_summary.get("data_available"):
        msg = "Land cover data unavailable; cannot determine CN."
        logger.warning(msg)
        return SCSCNResult(
            catchment_area_m2=catchment_area_m2,
            catchment_area_ha=catchment_area_ha,
            amc_condition=amc_condition,
            warnings=[],
            error_message=msg,
        )

    # Check soil group availability
    soil_group: Optional[str] = None
    if soil_group_summary is not None and soil_group_summary.get("data_available"):
        soil_group = soil_group_summary.get("soil_group")

    if soil_group is None:
        msg = "Soil group (HSG) unavailable; cannot look up CN."
        logger.warning(msg)
        return SCSCNResult(
            catchment_area_m2=catchment_area_m2,
            catchment_area_ha=catchment_area_ha,
            amc_condition=amc_condition,
            warnings=[],
            error_message=msg,
        )

    # Check rainfall
    if rainfall_P_mm is None or rainfall_P_mm <= 0:
        msg = "Rainfall depth P is not available or invalid."
        logger.warning(msg)
        return SCSCNResult(
            catchment_area_m2=catchment_area_m2,
            catchment_area_ha=catchment_area_ha,
            amc_condition=amc_condition,
            soil_group=soil_group,
            warnings=[],
            error_message=msg,
        )

    # Get land cover classes
    lc_classes = land_cover_summary.get("land_cover_classes", [])
    if not lc_classes:
        msg = "No land cover classes found in summary."
        logger.warning(msg)
        return SCSCNResult(
            catchment_area_m2=catchment_area_m2,
            catchment_area_ha=catchment_area_ha,
            amc_condition=amc_condition,
            soil_group=soil_group,
            warnings=[],
            error_message=msg,
        )

    warnings: List[str] = []
    contributions: List[LandCoverCNContribution] = []
    weighted_CN_sum = 0.0
    total_frac = 0.0

    for lc in lc_classes:
        lc_class = lc.get("land_cover_class", "unknown")
        frac = float(lc.get("fraction", 0.0))
        if frac <= 0:
            continue

        cn_ii = lookup_CN(lc_class, soil_group)

        if cn_ii is None:
            # Map to unknown class CN (conservative)
            cn_ii = lookup_CN("unknown", soil_group)
            if cn_ii is None:
                cn_ii = 75  # hardcoded fallback
                contrib_warning = (
                    f"No CN entry for class={lc_class}, HSG={soil_group}; "
                    f"using conservative default CN_II={cn_ii}."
                )
            else:
                contrib_warning = (
                    f"Class {lc_class} not in CN table for HSG {soil_group}; "
                    f"falling back to 'unknown' class CN_II={cn_ii}."
                )
            warnings.append(contrib_warning)
        else:
            contrib_warning = None

        cn_amc = get_cn_for_amc(cn_ii, amc_condition)
        weighted_cn = frac * cn_amc
        weighted_CN_sum += weighted_cn
        total_frac += frac

        contributions.append(LandCoverCNContribution(
            land_cover_class=lc_class,
            soil_group=soil_group,
            cn_ii=cn_ii,
            cn_amc=cn_amc,
            area_fraction=frac,
            weighted_cn=weighted_cn,
            warning=contrib_warning,
        ))

    # Normalise CN by total fraction (handles partial coverage)
    if total_frac > 0:
        weighted_CN = weighted_CN_sum / total_frac
    else:
        weighted_CN = weighted_CN_sum

    # Compute S, Ia, Q
    S_mm = compute_S(weighted_CN)
    Ia_mm = compute_Ia(S_mm)
    Q_mm = compute_runoff_depth(rainfall_P_mm, weighted_CN)
    # Round depth first so volume is derived from the same rounded Q
    # that is stored in the result -- keeps V = (Q_rounded/1000)*A consistent.
    runoff_depth_mm = round(Q_mm, 2)
    V_m3 = compute_runoff_volume(runoff_depth_mm, catchment_area_m2)

    # Warn if area-weighted CN is used
    if total_frac < 0.9:
        warnings.append(
            f"Total land cover fraction {total_frac:.2f} < 0.9. "
            "The catchment may have unmapped areas; area-weighted CN "
            "applies only to the mapped fraction."
        )

    warnings.append(
        "Area-weighted CN is an approximation, not a spatially "
        "distributed hydrologic simulation.  Consult local guidelines "
        "for India-specific CN values."
    )

    return SCSCNResult(
        data_available=True,
        rainfall_P_mm=rainfall_P_mm,
        amc_condition=amc_condition,
        soil_group=soil_group,
        weighted_CN=round(weighted_CN, 1),
        CN_contributions=contributions,
        S_mm=round(S_mm, 2),
        Ia_mm=round(Ia_mm, 2),
        runoff_depth_mm=runoff_depth_mm,
        runoff_volume_m3=round(V_m3, 2),
        catchment_area_m2=catchment_area_m2,
        catchment_area_ha=round(catchment_area_ha, 2),
        warnings=warnings,
        error_message=None,
    )


def summarise_scs_cn(result: SCSCNResult) -> dict:
    """Return a compact JSON-friendly summary for pipeline integration."""
    return result.to_dict()
