"""
Time of Concentration Service (Phase 11 - Part 4).

Implements a defensible Kirpich-based time of concentration (Tc) calculation
using the Phase 11A terrain diagnostics outputs (longest D8 flow path and
mean catchment slope).

Formula (Kirpich 1940)
----------------------
    Tc = 0.01947 * L^0.77 * S^(-0.385)

where:
    L = longest flow path length (m)
    S = representative slope (m/m)

Returns
-------
    Tc in minutes and hours, along with provenance and warnings.

Limitations
-----------
Kirpich was developed for small rural watersheds in the USA (Tennessee).
It is an overland-flow method and may underestimate Tc on long channels
or for low-relief terrain.  It is used here because it is a widely
documented, defensible first-order Tc estimate that uses quantities
already available from the Phase 11A catchment terrain diagnostics.

Tc is reported as a hydrologic diagnostic / prerequisite.  It is NOT
used here to convert the 24-hour design rainfall into an intensity.
The current design rainfall is a 24-hour depth and remains a depth.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

KIRPICH_COEFFICIENT = 0.01947
KIRPICH_L_EXPONENT = 0.77
KIRPICH_S_EXPONENT = -0.385
MIN_SLOPE_M_PER_M = 1e-6   # practical lower bound
MIN_PATH_M = 1.0           # practical lower bound


def kirpich_tc_minutes(
    longest_flow_path_m: float,
    slope_m_per_m: float,
) -> float:
    """
    Compute Tc in minutes using Kirpich (1940).

    Tc = 0.01947 * L^0.77 * S^-0.385

    Raises
    ------
    ValueError
        When path or slope is invalid.
    """
    if longest_flow_path_m is None or longest_flow_path_m < MIN_PATH_M:
        raise ValueError(
            f"longest_flow_path_m must be >= {MIN_PATH_M} m "
            f"(got {longest_flow_path_m})"
        )
    if slope_m_per_m is None or slope_m_per_m <= 0:
        raise ValueError(
            f"slope_m_per_m must be > 0 (got {slope_m_per_m})"
        )
    return KIRPICH_COEFFICIENT * (
        longest_flow_path_m ** KIRPICH_L_EXPONENT
    ) * (slope_m_per_m ** KIRPICH_S_EXPONENT)


@dataclass
class TimeOfConcentrationResult:
    """
    Time of concentration analysis result.

    Attributes
    ----------
    data_available : bool
        True when valid input was provided.
    method : str
        Name of the method used.
    formula : str
        Formula used (Kirpich form).
    longest_flow_path_m : float
        Longest D8 flow path used (metres).
    slope_m_per_m : float
        Representative slope used (m/m).
    slope_source : str
        Source of the slope (e.g. "mean catchment slope").
    tc_minutes : float
        Time of concentration in minutes.
    tc_hours : float
        Time of concentration in hours.
    warnings : List[str]
        Methodology / input warnings.
    error_message : Optional[str]
        Error description when data_available is False.
    """
    data_available: bool = True
    method: str = "Kirpich (1940)"
    formula: str = "Tc = 0.01947 * L^0.77 * S^-0.385  (minutes, m, m/m)"
    longest_flow_path_m: float = 0.0
    slope_m_per_m: float = 0.0
    slope_source: str = "mean catchment slope (m/m) from Phase 11A"
    tc_minutes: float = 0.0
    tc_hours: float = 0.0
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "data_available": self.data_available,
            "method": self.method,
            "formula": self.formula,
            "longest_flow_path_m": round(self.longest_flow_path_m, 2),
            "slope_m_per_m": round(self.slope_m_per_m, 6),
            "slope_source": self.slope_source,
            "tc_minutes": round(self.tc_minutes, 3),
            "tc_hours": round(self.tc_hours, 4),
            "warnings": self.warnings,
            "error_message": self.error_message,
        }


def compute_time_of_concentration(
    longest_flow_path_m: Optional[float],
    slope_m_per_m: Optional[float],
) -> TimeOfConcentrationResult:
    """
    Compute time of concentration using Kirpich.

    Parameters
    ----------
    longest_flow_path_m : float, optional
        Longest upstream D8 flow path (metres).
    slope_m_per_m : float, optional
        Representative slope (m/m).

    Returns
    -------
    TimeOfConcentrationResult
    """
    warnings: List[str] = []
    if longest_flow_path_m is None or longest_flow_path_m < MIN_PATH_M:
        msg = (
            f"Longest flow path is invalid ({longest_flow_path_m} m). "
            "Tc cannot be computed."
        )
        logger.warning(msg)
        return TimeOfConcentrationResult(
            data_available=False,
            longest_flow_path_m=float(longest_flow_path_m or 0.0),
            slope_m_per_m=float(slope_m_per_m or 0.0),
            warnings=[],
            error_message=msg,
        )
    if slope_m_per_m is None or slope_m_per_m <= 0:
        msg = (
            f"Slope is invalid ({slope_m_per_m} m/m). "
            "Tc cannot be computed."
        )
        logger.warning(msg)
        return TimeOfConcentrationResult(
            data_available=False,
            longest_flow_path_m=float(longest_flow_path_m or 0.0),
            slope_m_per_m=float(slope_m_per_m or 0.0),
            warnings=[],
            error_message=msg,
        )

    # Apply practical lower bound on slope to avoid divide-by-zero blowup
    effective_slope = max(slope_m_per_m, MIN_SLOPE_M_PER_M)
    if effective_slope != slope_m_per_m:
        warnings.append(
            f"Slope {slope_m_per_m:.6f} m/m is below the practical lower "
            f"bound {MIN_SLOPE_M_PER_M} m/m; using {effective_slope:.6f}."
        )

    try:
        tc_min = kirpich_tc_minutes(longest_flow_path_m, effective_slope)
    except ValueError as exc:
        return TimeOfConcentrationResult(
            data_available=False,
            longest_flow_path_m=longest_flow_path_m,
            slope_m_per_m=slope_m_per_m,
            warnings=[],
            error_message=str(exc),
        )

    warnings.append(
        "Kirpich (1940) was developed for small rural USA watersheds "
        "and may underestimate Tc on long channels or low-relief terrain."
    )
    warnings.append(
        "Tc is reported as a hydrologic diagnostic; the design rainfall "
        "is a 24-hour depth and is not converted to an intensity here."
    )

    return TimeOfConcentrationResult(
        data_available=True,
        longest_flow_path_m=longest_flow_path_m,
        slope_m_per_m=slope_m_per_m,
        tc_minutes=round(tc_min, 3),
        tc_hours=round(tc_min / 60.0, 4),
        warnings=warnings,
        error_message=None,
    )


def summarise_time_of_concentration(
    result: TimeOfConcentrationResult,
) -> dict:
    """Return a compact JSON-friendly summary for pipeline integration."""
    return result.to_dict()
