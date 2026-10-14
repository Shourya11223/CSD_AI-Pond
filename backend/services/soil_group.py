"""
Soil Group / Hydrologic Soil Group (HSG) Service (Phase 11 - Part 2).

This service attempts to determine the hydrologic soil group (A, B, C, D)
for the catchment so that downstream SCS-CN calculations can produce a
defensible runoff estimate.

Defensible Source Selection
---------------------------
Several free soil-data sources exist for India (e.g. ISRIC SoilGrids,
NBSS&LUP soil maps, FAO HWSD).  However:

1. ISRIC SoilGrids requires a separate API key and accepts a coarse
   areal unit (250 m raster cells) that does not directly produce an
   HSG class without a documented mapping to USDA texture classes.
2. The FAO Harmonized World Soil Database (HWSD) provides a 30-arcsec
   (~1 km) soil-unit raster with a documented USDA texture class.
   However it ships as a multi-GB download that exceeds the
   "no heavy GIS dependencies" project constraint.
3. NBSS&LUP publishes India soil maps but in shapefile / PDF formats
   that require GIS infrastructure to consume reliably.

The project therefore implements this service as a defensible
"unavailable" stub that:

- Never fabricates an HSG value.
- Documents the data sources it considered and the reason each was
  not programmatically accessible in this build.
- Returns ``data_available = False`` with explicit provenance, so that
  downstream CN / runoff stages can be marked unavailable rather than
  producing fake engineering numbers.

Future Implementation
---------------------
A real provider can be plugged in by populating the
``_attempt_provider_lookup`` function with a concrete implementation.
The rest of the service (dataclass, summary, validation) is designed
to accommodate any provider that returns a soil-class fraction or a
single dominant class.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Documented candidate soil-data sources.
# These are not contacted in this build but are listed for provenance.
CANDIDATE_SOURCES = [
    {
        "id": "isric-soilgrids",
        "name": "ISRIC SoilGrids",
        "url": "https://www.isric.org/explore/soilgrids",
        "resolution": "250 m raster",
        "status": "not_connected",
        "reason": (
            "Requires ISRIC API key; provides texture class but no "
            "native HSG mapping; would need documented USDA texture -> "
            "HSG conversion and a raster tile fetch pipeline."
        ),
    },
    {
        "id": "fao-hwsd",
        "name": "FAO Harmonized World Soil Database",
        "url": "https://www.fao.org/soils-portal/data-hub/soil-maps-and-databases/harmonized-world-soil-database-v12/en/",
        "resolution": "30 arcsec (~1 km)",
        "status": "not_connected",
        "reason": (
            "Multi-GB download with associated .mdb MS Access database; "
            "exceeds the project's no-heavy-GIS-dependencies constraint."
        ),
    },
    {
        "id": "nbsslup-india",
        "name": "NBSS&LUP (India) Soil Maps",
        "url": "https://www.nbsslup.in/",
        "resolution": "Various scales",
        "status": "not_connected",
        "reason": (
            "Distributed as PDF / shapefile downloads; "
            "requires GIS infrastructure to extract pixel-level HSG."
        ),
    },
]


# Hydrologic Soil Group definitions.
# A: high infiltration, deep well-drained sands/loams
# B: moderate infiltration, moderately deep, moderately well drained
# C: slow infiltration, layer restricting downward flow
# D: very slow infiltration, clay / shallow / water table
VALID_HSG_CLASSES = ("A", "B", "C", "D")


@dataclass
class SoilClassFraction:
    """Area fraction for a single hydrologic soil group."""
    soil_group: str
    fraction: float       # 0-1
    feature_count: int = 0


@dataclass
class SoilGroupResult:
    """
    Soil / HSG analysis result.

    Attributes
    ----------
    data_available : bool
        True when a real provider returned valid HSG data.
        False in this build (no provider is connected).
    source : str
        Identifier of the data provider (or "unavailable").
    lookup_method : str
        Description of the lookup strategy attempted.
    soil_group : Optional[str]
        Dominant HSG class (A/B/C/D), or None if unavailable.
    soil_group_fractions : List[SoilClassFraction]
        Per-HSG area fractions (empty if unavailable).
    bbox : Optional[dict]
        Bounding box used for the lookup, if applicable.
    warnings : List[str]
        Human-readable warnings about why HSG is unavailable
        or about interpretation.
    error_message : Optional[str]
        Error description when data_available is False.
    candidate_sources_considered : List[dict]
        Provenance of candidate sources that were evaluated.
    """
    data_available: bool = False
    source: str = "unavailable"
    lookup_method: str = (
        "No real soil / HSG provider is connected in this build. "
        "Documented candidate sources (ISRIC SoilGrids, FAO HWSD, "
        "NBSS&LUP) require GIS infrastructure or API keys not "
        "available to this project."
    )
    soil_group: Optional[str] = None
    soil_group_fractions: List[SoilClassFraction] = field(default_factory=list)
    bbox: Optional[dict] = None
    warnings: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    candidate_sources_considered: List[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.candidate_sources_considered:
            self.candidate_sources_considered = list(CANDIDATE_SOURCES)
        if not self.warnings:
            self.warnings = list(_default_warnings())

    def to_dict(self) -> dict:
        return {
            "data_available": self.data_available,
            "source": self.source,
            "lookup_method": self.lookup_method,
            "soil_group": self.soil_group,
            "soil_group_fractions": [
                {
                    "soil_group": s.soil_group,
                    "fraction": round(s.fraction, 4),
                    "feature_count": s.feature_count,
                }
                for s in self.soil_group_fractions
            ],
            "bbox": self.bbox,
            "warnings": self.warnings,
            "error_message": self.error_message,
            "candidate_sources_considered": self.candidate_sources_considered,
        }


def _default_warnings() -> List[str]:
    return [
        "Hydrologic soil group (HSG) could not be automatically "
        "determined for this catchment.",
        "No real soil-data provider is currently integrated.",
        "Downstream SCS-CN runoff and pond-adequacy stages will "
        "return unavailable rather than fabricate values.",
        "Documented candidate sources (ISRIC SoilGrids, FAO HWSD, "
        "NBSS&LUP) were considered but were not connected.",
    ]


def _attempt_provider_lookup(
    bbox: Tuple[float, float, float, float],
) -> Tuple[Optional[str], Optional[Dict[str, float]], str]:
    """
    Stub for connecting a real soil-data provider.

    In this build, no real provider is connected.  The function is
    designed so that a future implementation can simply populate
    ``dominant_group`` and ``fractions`` from a real source.

    Parameters
    ----------
    bbox : (min_lat, min_lon, max_lat, max_lon)

    Returns
    -------
    (dominant_group, fractions, error_message)
        dominant_group : str or None
        fractions : dict of {group: fraction} or None
        error_message : str (empty when successful)
    """
    # No real provider is connected in this build.
    return None, None, (
        "No real soil / HSG provider is integrated in this build. "
        "See candidate_sources_considered in the result for details."
    )


def get_soil_group(
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> SoilGroupResult:
    """
    Attempt to determine the hydrologic soil group for a catchment.

    Parameters
    ----------
    bbox : (min_lat, min_lon, max_lat, max_lon), optional
        Geographic bounding box of the catchment.  Currently unused
        because no real provider is connected.

    Returns
    -------
    SoilGroupResult
        Always returns data_available=False in this build.
    """
    bbox_dict: Optional[dict] = None
    if bbox is not None:
        min_lat, min_lon, max_lat, max_lon = bbox
        bbox_dict = {
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        }

    logger.info("Soil group lookup requested; no provider connected.")
    dominant, fractions, error = _attempt_provider_lookup(bbox or (0, 0, 0, 0))

    if dominant is None:
        return SoilGroupResult(
            data_available=False,
            source="unavailable",
            bbox=bbox_dict,
            error_message=error,
        )

    # If a real provider is later connected, validate and build fractions
    if dominant not in VALID_HSG_CLASSES:
        return SoilGroupResult(
            data_available=False,
            source="unavailable",
            bbox=bbox_dict,
            error_message=f"Invalid HSG class returned: {dominant!r}",
        )

    soil_fractions: List[SoilClassFraction] = []
    if fractions:
        total = sum(fractions.values())
        if total > 0:
            for cls, frac in fractions.items():
                if cls in VALID_HSG_CLASSES:
                    soil_fractions.append(
                        SoilClassFraction(
                            soil_group=cls,
                            fraction=frac / total,
                        )
                    )

    return SoilGroupResult(
        data_available=True,
        source="unavailable",  # Replace with real provider id when connected
        soil_group=dominant,
        soil_group_fractions=soil_fractions,
        bbox=bbox_dict,
        warnings=[],
        error_message=None,
    )


def summarise_soil_group(result: SoilGroupResult) -> dict:
    """Return a compact JSON-friendly summary for pipeline integration."""
    return result.to_dict()
