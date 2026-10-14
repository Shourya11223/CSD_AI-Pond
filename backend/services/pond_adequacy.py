"""
Pond Adequacy Service (Phase 11 - Part 5).

Compares the design runoff volume against the available pond storage
volume for the selected candidate and reports an adequacy ratio.

Definition
----------
    adequacy_ratio = available_storage_m3 / runoff_volume_m3

If available_storage >= runoff_volume, the pond is large enough to
contain the design storm runoff.  If not, additional storage or
treatment capacity is required.

Status Thresholds
-----------------
Two explicit, documented thresholds are used:

  - ADEQUACY_RATIO_PASS:           >= 1.0  (storage >= runoff)
  - ADEQUACY_RATIO_MARGINAL:       >= MARGINAL_RATIO

The MARGINAL_RATIO threshold is a configurable constant (default 0.75).
Below that, the status is "fail".  These thresholds are engineering
judgments, not safety factors; no arbitrary safety factor is applied.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# Status thresholds (documented engineering interpretations)
ADEQUACY_RATIO_PASS = 1.0     # ratio >= 1.0 -> "pass"
MARGINAL_RATIO = 0.75         # ratio < MARGINAL_RATIO -> "fail"


@dataclass
class PondAdequacyResult:
    """
    Pond adequacy analysis result.

    Attributes
    ----------
    data_available : bool
        True when both runoff and storage are available.
    runoff_volume_m3 : Optional[float]
        Design runoff volume (m3).
    available_storage_m3 : Optional[float]
        Available pond storage (m3).
    adequacy_ratio : Optional[float]
        available_storage / runoff_volume.  None if unavailable.
    status : str
        "pass" (ratio >= 1.0), "marginal" (MARGINAL <= ratio < 1.0),
        "fail" (ratio < MARGINAL), or "unavailable".
    threshold_pass : float
        The pass threshold used (1.0 by default).
    threshold_marginal : float
        The marginal threshold used (0.75 by default).
    warnings : List[str]
        Methodology warnings.
    error_message : Optional[str]
        Error description when data_available is False.
    """
    data_available: bool = True
    runoff_volume_m3: Optional[float] = None
    available_storage_m3: Optional[float] = None
    adequacy_ratio: Optional[float] = None
    status: str = "unavailable"
    threshold_pass: float = ADEQUACY_RATIO_PASS
    threshold_marginal: float = MARGINAL_RATIO
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "data_available": self.data_available,
            "runoff_volume_m3": (round(self.runoff_volume_m3, 2)
                                 if self.runoff_volume_m3 is not None else None),
            "available_storage_m3": (round(self.available_storage_m3, 2)
                                    if self.available_storage_m3 is not None else None),
            "adequacy_ratio": (round(self.adequacy_ratio, 4)
                               if self.adequacy_ratio is not None else None),
            "status": self.status,
            "threshold_pass": self.threshold_pass,
            "threshold_marginal": self.threshold_marginal,
            "warnings": self.warnings,
            "error_message": self.error_message,
        }


def compute_pond_adequacy(
    runoff_volume_m3: Optional[float],
    available_storage_m3: Optional[float],
) -> PondAdequacyResult:
    """
    Compute pond adequacy.

    Parameters
    ----------
    runoff_volume_m3 : float, optional
        Design runoff volume (m3) from SCS-CN.
    available_storage_m3 : float, optional
        Available pond storage (m3) from the pond-capacity service.

    Returns
    -------
    PondAdequacyResult
    """
    if runoff_volume_m3 is None:
        msg = "Runoff volume is not available; cannot assess pond adequacy."
        logger.warning(msg)
        return PondAdequacyResult(
            data_available=False,
            available_storage_m3=available_storage_m3,
            status="unavailable",
            warnings=[],
            error_message=msg,
        )
    if available_storage_m3 is None:
        msg = "Pond storage is not available; cannot assess pond adequacy."
        logger.warning(msg)
        return PondAdequacyResult(
            data_available=False,
            runoff_volume_m3=runoff_volume_m3,
            status="unavailable",
            warnings=[],
            error_message=msg,
        )

    warnings: List[str] = []

    if runoff_volume_m3 == 0.0:
        msg = "Runoff volume is 0 m3; pond adequacy is trivially satisfied."
        logger.info(msg)
        warnings.append(msg)
        return PondAdequacyResult(
            data_available=True,
            runoff_volume_m3=0.0,
            available_storage_m3=available_storage_m3,
            adequacy_ratio=float("inf") if available_storage_m3 > 0 else 0.0,
            status="pass",
            warnings=warnings,
        )

    if available_storage_m3 <= 0:
        msg = "Available storage is <= 0; pond is not viable."
        logger.warning(msg)
        warnings.append(msg)
        return PondAdequacyResult(
            data_available=True,
            runoff_volume_m3=runoff_volume_m3,
            available_storage_m3=available_storage_m3,
            adequacy_ratio=0.0,
            status="fail",
            warnings=warnings,
        )

    ratio = available_storage_m3 / runoff_volume_m3

    if ratio >= ADEQUACY_RATIO_PASS:
        status = "pass"
    elif ratio >= MARGINAL_RATIO:
        status = "marginal"
    else:
        status = "fail"

    warnings.append(
        f"Pond adequacy thresholds: pass >= {ADEQUACY_RATIO_PASS}, "
        f"marginal >= {MARGINAL_RATIO}, fail < {MARGINAL_RATIO}. "
        "These are engineering judgments, not safety factors; "
        "no safety factor is applied."
    )

    return PondAdequacyResult(
        data_available=True,
        runoff_volume_m3=runoff_volume_m3,
        available_storage_m3=available_storage_m3,
        adequacy_ratio=ratio,
        status=status,
        warnings=warnings,
    )


def summarise_pond_adequacy(result: PondAdequacyResult) -> dict:
    """Return a compact JSON-friendly summary for pipeline integration."""
    return result.to_dict()
