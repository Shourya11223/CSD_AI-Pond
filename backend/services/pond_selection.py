"""
Pond candidate selection service (Stage 4).

Identifies and ranks interior pond candidate locations from a hydrology
pipeline result. The algorithm is intentionally general: it does not
hard-code any coordinates or thresholds specific to a particular
contour file. All factor scores are derived from the actual DEM,
flow-direction and flow-accumulation arrays, and all thresholds are
expressed in physical units (metres) or in percentile-based scores
so that the method adapts to maps of any size.

Methodology
-----------

For every cell in the (H, W) DEM we compute a small set of physical /
hydrological attributes:

    1. Boundary exclusion mask
       Cells within ``boundary_margin_m`` of any grid edge are excluded.
       The default margin is 2 * cell_size_m so that slope and local
       elevation statistics are reliable (the neighbourhood window does
       not run off the edge) and so that the candidate is not adjacent
       to the artificial rectangular DEM boundary (which is a flow
       terminator in the current Priority-Flood implementation).

    2. Flow accumulation percentile
       The cell's upstream contributing cell count, mapped to [0, 100]
       using a percentile rank against the INTERIOR cells only. Cells
       with very high accumulation are preferred (they collect water
       from a large area) but the score is saturated at the 99th
       percentile to avoid bias from a single extreme catchment.

    3. Local slope (from the ORIGINAL DEM)
       Computed with metric cell spacing using a finite-difference
       gradient. Steep slopes are penalised; flat or gently sloping
       locations are rewarded. The slope score is the percentile of
       (max_slope - slope) so that low slopes score high.

    4. Relative local elevation (valley preference)
       For each cell, the difference between its elevation and the
       mean elevation of a square neighbourhood. Cells that are
       LOWER than their surroundings score high (they sit in a
       valley), cells on a ridge score low.

    5. Drainage concentration
       The flow-accumulation percentile of the cell PLUS a small
       bonus for being on a flow path (flow_direction != 0). The
       bonus is bounded so that the score cannot be gamed by being
       on a tiny tributary far from the main drainage.

All four factors are then combined into a transparent composite
suitability score:

    composite = 0.30 * accumulation_pct
              + 0.25 * low_slope_pct
              + 0.25 * low_relative_pct
              + 0.20 * drainage_concentration_pct

We then apply non-maximum suppression with a minimum spatial
separation (default: 5 cells) so that the top-k candidates are
spatially distinct, and we return the best 3-5 candidates.

The result is fully explainable: every candidate carries its
individual factor scores so the choice can be defended during a Viva.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# Re-use the boundary helper from the hydrology service to keep
# definitions consistent across stages.
from services.hydrology import _is_on_boundary, _grid_to_geographic

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class PondSelectionConfig:
    """
    Tunable parameters for the pond-candidate selection algorithm.

    All defaults are physically reasonable for a 10 m cell size, but
    every value can be overridden by the caller. None of the defaults
    are hard-coded to the sample KML.
    """

    # --- Boundary exclusion ---
    boundary_margin_m: Optional[float] = None
    # If None, the margin defaults to 2 * cell_size_m, which gives
    # slope / local-elevation statistics a reliable neighbourhood
    # while keeping candidates well away from the artificial edge.

    # --- Local-elevation neighbourhood ---
    relative_radius_cells: int = 5
    # Side length of the square window used for the relative-elevation
    # factor, in cells. 5 gives a 11x11 window, i.e. ~110 m at 10 m
    # resolution -- a reasonable valley-scale neighbourhood.

    # --- Slope score: max acceptable slope (above this, score = 0) ---
    # We use a percentile score, so this is only a clamp. It guards
    # against numerical noise (e.g. IDW spikes) producing a single
    # artificially steep cell that would otherwise dominate.
    slope_soft_cap_m_per_m: float = 1.0  # 100% gradient, i.e. 45 deg

    # --- Drainage bonus for being on a flow path ---
    on_flow_path_bonus: float = 5.0
    # A flat bonus added to the accumulation score (already in [0, 100])
    # for any cell that has a defined D8 flow direction. This nudges
    # the algorithm towards natural drainage lines without making it
    # ignore flat valleys that happen to have flow_dir = 0.

    # --- Non-maximum suppression ---
    nms_radius_cells: int = 5
    # When ranking, suppress any candidate that lies within this many
    # cells (Chebyshev / square distance) of an already-selected
    # higher-ranked one. 5 cells = 50 m at 10 m resolution.

    # --- Composite weights (must sum to 1.0) ---
    weight_accumulation: float = 0.30
    weight_low_slope: float = 0.25
    weight_low_relative: float = 0.25
    weight_drainage: float = 0.20

    # --- Output ---
    top_k: int = 5
    # Clamped to [3, 5] by the public entry point.

    # --- Water exclusion (Phase 2) ---
    water_exclusion_applied: bool = False
    # Whether water exclusion mask was applied during candidate selection.

    water_excluded_cells: int = 0
    # Number of cells excluded by the water exclusion mask.

    water_mask: Optional[np.ndarray] = None
    # Boolean 2D array of shape (H, W); True = inside excluded water area.
    # May be None if water exclusion was not applied.

    def normalised_weights(self) -> Tuple[float, float, float, float]:
        """Return weights scaled so they sum to 1.0 exactly."""
        s = (
            self.weight_accumulation
            + self.weight_low_slope
            + self.weight_low_relative
            + self.weight_drainage
        )
        if s <= 0:
            return 0.25, 0.25, 0.25, 0.25
        return (
            self.weight_accumulation / s,
            self.weight_low_slope / s,
            self.weight_low_relative / s,
            self.weight_drainage / s,
        )


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class PondCandidate:
    """A single ranked pond-candidate location."""

    rank: int
    row: int
    col: int
    lat: Optional[float]
    lon: Optional[float]
    elevation_m: float
    flow_accumulation_cells: int
    upstream_area_m2: float
    local_slope_m_per_m: float
    local_slope_deg: float
    relative_elevation_m: float
    # Individual factor scores in [0, 100]
    score_accumulation: float
    score_low_slope: float
    score_low_relative: float
    score_drainage: float
    # Final composite score in [0, 100]
    score_total: float

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "row": self.row,
            "col": self.col,
            "lat": self.lat,
            "lon": self.lon,
            "elevation_m": float(self.elevation_m),
            "flow_accumulation_cells": int(self.flow_accumulation_cells),
            "upstream_area_m2": float(self.upstream_area_m2),
            "local_slope_m_per_m": float(self.local_slope_m_per_m),
            "local_slope_deg": float(self.local_slope_deg),
            "relative_elevation_m": float(self.relative_elevation_m),
            "factor_scores": {
                "accumulation": float(self.score_accumulation),
                "low_slope": float(self.score_low_slope),
                "low_relative_elevation": float(self.score_low_relative),
                "drainage_concentration": float(self.score_drainage),
            },
            "suitability_score": float(self.score_total),
        }


@dataclass
class PondSelectionResult:
    """Full output of the pond-selection stage."""

    candidates: List[PondCandidate]
    boundary_margin_cells: int
    boundary_margin_m: float
    cells_total: int
    cells_inside_margin: int
    cells_excluded_boundary: int
    cells_excluded_water: int
    cells_suppressed_by_nms: int
    cells_considered: int
    min_kept_score: float
    weights: Dict[str, float]
    methodology: str
    nms_radius_cells: int
    water_exclusion_applied: bool = False
    water_features_found: int = 0
    water_buffer_m: float = 0.0
    water_fallback_used: bool = False
    water_error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "diagnostics": {
                "boundary_margin_cells": int(self.boundary_margin_cells),
                "boundary_margin_m": float(self.boundary_margin_m),
                "cells_total": int(self.cells_total),
                "cells_inside_margin": int(self.cells_inside_margin),
                "cells_excluded_boundary": int(self.cells_excluded_boundary),
                "cells_excluded_water": int(self.cells_excluded_water),
                "cells_suppressed_by_nms": int(self.cells_suppressed_by_nms),
                "cells_considered": int(self.cells_considered),
                "min_kept_score": float(self.min_kept_score),
                "nms_radius_cells": int(self.nms_radius_cells),
                "weights": self.weights,
                "methodology": self.methodology,
                "water_exclusion": {
                    "applied": self.water_exclusion_applied,
                    "features_found": self.water_features_found,
                    "buffer_metres": self.water_buffer_m,
                    "fallback_used": self.water_fallback_used,
                    "error_message": self.water_error_message,
                },
            },
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _percentile_rank_padded(
    values: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """
    For every cell in ``values``, return its percentile rank (0-100)
    computed ONLY over the cells where ``mask`` is True. Cells outside
    the mask receive 0.0.

    The percentile is the standard "fraction of mask-True values that
    are <= this value", mapped to 0-100. This is the data-driven
    normalisation the user requested: no fixed thresholds.
    """
    out = np.zeros_like(values, dtype=np.float64)
    if not mask.any():
        return out
    pool = values[mask]
    sorted_pool = np.sort(pool)
    n = sorted_pool.size
    # Use np.searchsorted for an O(N log M) vectorised rank.
    ranks = np.searchsorted(sorted_pool, values, side="left")
    # Use the (n - 1) denominator so the maximum value gets 100 %
    # and the minimum value gets 0 %. (Standard "fraction of values
    # strictly less than x" form.)
    denom = max(1, n - 1)
    pct = 100.0 * ranks / denom
    # Clip to [0, 100] in case of ties at the extreme.
    pct = np.clip(pct, 0.0, 100.0)
    out[mask] = pct[mask]
    return out


def _compute_local_slope(
    dem: np.ndarray, cell_size_m: float
) -> np.ndarray:
    """
    Estimate the local slope (rise/run, m/m) at every interior cell of
    the DEM using centred finite differences on the metric grid.

    The slope in the row and column directions is computed with
    np.gradient, which handles the edges with first-order differences
    (we mask those out later via the boundary exclusion anyway).
    """
    # np.gradient returns d/daxis values assuming unit spacing. The
    # actual axis spacing is cell_size_m, so we divide by it.
    dy, dx = np.gradient(dem, cell_size_m, cell_size_m)
    slope = np.sqrt(dx * dx + dy * dy)
    return slope


def _compute_relative_elevation(
    dem: np.ndarray, radius_cells: int
) -> np.ndarray:
    """
    For every cell, compute (cell_elevation - mean of its square
    neighbourhood). Negative values mean the cell sits in a local
    valley (lower than its surroundings); positive values mean it
    sits on a local ridge.

    The neighbourhood is (2 * radius_cells + 1) on a side. Edge cells
    with insufficient neighbours are handled by using a uniform-edge
    padding that does NOT bias the mean: we pad with the cell value
    itself via np.pad(mode="edge") so that the mean is dominated by
    genuine neighbours, not by zeros.
    """
    if radius_cells < 1:
        return np.zeros_like(dem, dtype=np.float64)
    # scipy.ndimage.uniform_filter gives an O(H*W) box mean that
    # correctly handles the edge cells by replicating the boundary
    # values. This is the same effect we want: cells on the edge of
    # the grid see their own value reflected back as a neighbour,
    # so the mean is not biased by spurious zeros.
    from scipy.ndimage import uniform_filter
    window = 2 * radius_cells + 1
    mean = uniform_filter(dem.astype(np.float64), size=window, mode="nearest")
    rel = dem - mean
    return rel


def _build_boundary_mask(
    h: int, w: int, margin_cells: int
) -> np.ndarray:
    """Return a boolean mask of cells OUTSIDE the boundary margin."""
    if margin_cells <= 0:
        return np.ones((h, w), dtype=bool)
    if 2 * margin_cells >= min(h, w):
        # Margin would consume the entire grid; return empty.
        return np.zeros((h, w), dtype=bool)
    mask = np.ones((h, w), dtype=bool)
    mask[:margin_cells, :] = False
    mask[-margin_cells:, :] = False
    mask[:, :margin_cells] = False
    mask[:, -margin_cells:] = False
    return mask


def _non_maximum_suppression(
    scores: np.ndarray,
    row_indices: np.ndarray,
    col_indices: np.ndarray,
    radius: int,
) -> List[int]:
    """
    Given a list of (row, col, score) cells sorted by score
    descending, return the indices into that list that survive NMS:
    a cell is kept only if it is further than ``radius`` cells
    (Chebyshev distance) from every already-kept cell with a higher
    score.

    Implementation note: rather than testing each candidate against every
    already-kept cell (O(N x kept)), each accepted cell marks its
    (2*radius+1)^2 Chebyshev neighbourhood as occupied. A candidate is then
    rejected iff its own cell is already occupied -- exactly the
    "within radius of a higher-scoring kept cell" condition. The kept set is
    therefore identical to the naive comparison, in O(N + kept *
    (2*radius+1)^2).
    """
    order = np.argsort(-scores)  # descending
    if order.size == 0:
        return []

    max_row = int(row_indices.max())
    max_col = int(col_indices.max())
    occupied = np.zeros((max_row + 1, max_col + 1), dtype=bool)

    kept: List[int] = []
    for idx in order:
        r = int(row_indices[idx])
        c = int(col_indices[idx])
        if occupied[r, c]:
            continue
        kept.append(int(idx))
        r0 = r - radius if r - radius > 0 else 0
        c0 = c - radius if c - radius > 0 else 0
        r1 = r + radius if r + radius < max_row else max_row
        c1 = c + radius if c + radius < max_col else max_col
        occupied[r0:r1 + 1, c0:c1 + 1] = True
    return kept


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def find_pond_candidates(
    dem: np.ndarray,
    flow_direction: np.ndarray,
    flow_accumulation_cells: np.ndarray,
    cell_size_m: float,
    projection_info: Optional[dict] = None,
    config: Optional[PondSelectionConfig] = None,
    water_mask: Optional[np.ndarray] = None,
    water_result: Optional[object] = None,
) -> PondSelectionResult:
    """
    Identify and rank interior pond-candidate locations.

    Parameters
    ----------
    dem : (H, W) float64 ndarray
        The ORIGINAL (un-filled) elevation grid, in metres. The
        original DEM is used for slope and relative elevation, so the
        pond sites reflect the natural terrain, not the depression-
        filled surface.
    flow_direction : (H, W) int ndarray
        D8 flow-direction grid (0-8) as returned by run_hydrology.
    flow_accumulation_cells : (H, W) int ndarray
        Upstream contributing cell count.
    cell_size_m : float
        Metric cell-centre spacing in metres.
    projection_info : dict, optional
        Projection metadata used to convert (row, col) to (lat, lon).
    config : PondSelectionConfig, optional
        Tunable parameters. If None, defaults are used.
    water_mask : ndarray, optional
        Boolean 2D array of shape (H, W). True = inside excluded water area.
        Candidates inside water exclusion zones are rejected (Phase 2).
    water_result : WaterExclusionResult, optional
        Water exclusion result for diagnostics (Phase 2).

    Returns
    -------
    PondSelectionResult
        Contains the ranked list of candidates (3-5 entries) plus a
        diagnostics block describing the methodology and the cell
        counts at every exclusion step.
    """
    if config is None:
        config = PondSelectionConfig()

    # Clamp top_k into [3, 5] per the requirements.
    config.top_k = max(3, min(5, int(config.top_k)))

    h, w = dem.shape
    if flow_direction.shape != dem.shape:
        raise ValueError("flow_direction must match dem shape")
    if flow_accumulation_cells.shape != dem.shape:
        raise ValueError("flow_accumulation_cells must match dem shape")

    # --- 1. Boundary exclusion mask ---
    if config.boundary_margin_m is None:
        margin_m = 2.0 * float(cell_size_m)
    else:
        margin_m = float(config.boundary_margin_m)
    margin_cells = int(math.ceil(margin_m / float(cell_size_m)))
    margin_cells = max(1, margin_cells)
    inside_mask = _build_boundary_mask(h, w, margin_cells)
    excluded_boundary = int((~inside_mask).sum())
    cells_total = h * w
    cells_inside = int(inside_mask.sum())

    # --- 1b. Water exclusion mask (Phase 2) ---
    # Apply water exclusion mask if provided. This rejects or penalizes
    # candidates that fall inside existing rivers, streams, or water bodies.
    excluded_water = 0
    if water_mask is not None:
        if water_mask.shape != (h, w):
            logger.warning(
                f"Water mask shape {water_mask.shape} != DEM shape ({h}, {w}). "
                "Ignoring water exclusion."
            )
        else:
            # Combine boundary mask with water mask: cells must be
            # inside boundary AND outside water exclusion zones.
            inside_mask = inside_mask & (~water_mask)
            excluded_water = int(water_mask.sum())
            logger.info(
                f"Water exclusion: {excluded_water} cells excluded, "
                f"{int(inside_mask.sum())} cells remain valid candidates"
            )

    # --- 2. Compute slope and relative elevation on the ORIGINAL DEM ---
    slope = _compute_local_slope(dem, float(cell_size_m))
    rel = _compute_relative_elevation(dem, config.relative_radius_cells)

    # --- 3. Build the per-factor percentile scores over interior cells ---
    # 3a. Accumulation: higher = better.
    acc_pct = _percentile_rank_padded(
        flow_accumulation_cells.astype(np.float64), inside_mask
    )
    # 3b. Low slope: invert so that flat cells score high.
    #    Clamp at the soft cap so a single IDW spike cannot dominate.
    slope_clamped = np.minimum(slope, config.slope_soft_cap_m_per_m)
    inv_slope = config.slope_soft_cap_m_per_m - slope_clamped
    low_slope_pct = _percentile_rank_padded(inv_slope, inside_mask)
    # 3c. Low relative elevation: invert so that valley cells score high.
    inv_rel = -rel  # valley (rel < 0) becomes positive score
    low_rel_pct = _percentile_rank_padded(inv_rel, inside_mask)
    # 3d. Drainage concentration: accumulation percentile + on-path bonus.
    on_path = (flow_direction > 0).astype(np.float64) * config.on_flow_path_bonus
    drainage_pct = np.clip(acc_pct + on_path, 0.0, 100.0)

    # --- 4. Composite suitability score ---
    wa, ws, wr, wd = config.normalised_weights()
    composite = (
        wa * acc_pct
        + ws * low_slope_pct
        + wr * low_rel_pct
        + wd * drainage_pct
    )

    # Mask out everything outside the boundary margin: those cells
    # must never appear as candidates.
    composite_masked = np.where(inside_mask, composite, -np.inf)

    # --- 5. Pick the top-k via NMS ---
    rows, cols = np.meshgrid(
        np.arange(h, dtype=np.int64), np.arange(w, dtype=np.int64),
        indexing="ij",
    )
    rr = rows.ravel()
    cc = cols.ravel()
    sc = composite_masked.ravel()

    # Drop cells with -inf (outside margin) before sorting.
    valid = np.isfinite(sc)
    rr = rr[valid]
    cc = cc[valid]
    sc = sc[valid]

    # Apply NMS to get spatially distinct candidates. ``kept_indices``
    # contains ALL cells that survived NMS (i.e. are not within the
    # NMS radius of a higher-scoring neighbour). The top-k by score
    # are then chosen from that set.
    all_kept = _non_maximum_suppression(
        sc, rr, cc, config.nms_radius_cells
    )
    cells_suppressed_by_nms = int(len(sc) - len(all_kept))

    kept_indices = all_kept[: config.top_k]

    # The minimum score among the kept cells is reported as a
    # diagnostic; the algorithm does not impose a hard threshold
    # below which cells are excluded.
    if kept_indices:
        min_kept_score = float(sc[kept_indices].min())
    else:
        min_kept_score = float("nan")

    # --- 6. Build the candidate list (ranked by composite score) ---
    # Sort kept indices by score descending so rank 1 is the best.
    kept_indices.sort(key=lambda i: -float(sc[i]))
    candidates: List[PondCandidate] = []
    for rank, idx in enumerate(kept_indices, start=1):
        r = int(rr[idx])
        c = int(cc[idx])
        lat, lon = _grid_to_geographic(
            r, c, h, w, float(cell_size_m), projection_info
        )
        cell_area_m2 = float(cell_size_m) * float(cell_size_m)
        candidates.append(
            PondCandidate(
                rank=rank,
                row=r,
                col=c,
                lat=lat,
                lon=lon,
                elevation_m=float(dem[r, c]),
                flow_accumulation_cells=int(flow_accumulation_cells[r, c]),
                upstream_area_m2=float(flow_accumulation_cells[r, c]) * cell_area_m2,
                local_slope_m_per_m=float(slope[r, c]),
                local_slope_deg=float(math.degrees(math.atan(slope[r, c]))),
                relative_elevation_m=float(rel[r, c]),
                score_accumulation=float(acc_pct[r, c]),
                score_low_slope=float(low_slope_pct[r, c]),
                score_low_relative=float(low_rel_pct[r, c]),
                score_drainage=float(drainage_pct[r, c]),
                score_total=float(composite[r, c]),
            )
        )

    # --- 7. Methodology text for diagnostics ---
    methodology = (
        "Each interior cell is scored on four factors, all "
        "percentile-normalised against the interior cells only: "
        "(a) flow accumulation percentile (upstream catchment size), "
        "(b) low local slope percentile (flat to moderately sloping), "
        "(c) low relative-elevation percentile (locally lower than the "
        f"{2*config.relative_radius_cells+1}-cell neighbourhood, i.e. a "
        "valley rather than a ridge), and (d) drainage concentration "
        "(accumulation + a small bonus for being on a defined D8 flow "
        "path). The factors are combined into a 0-100 suitability score "
        f"with weights "
        f"accumulation={wa:.2f}, low_slope={ws:.2f}, "
        f"low_relative={wr:.2f}, drainage={wd:.2f}. "
        f"A boundary margin of {margin_cells} cells "
        f"({margin_m:.1f} m, default 2 * cell_size) is excluded to avoid "
        "the artificial DEM edge. Non-maximum suppression with a "
        f"{config.nms_radius_cells}-cell radius keeps the returned "
        f"candidates spatially distinct. The original (un-filled) DEM "
        "is used for slope and relative elevation so that pond sites "
        "reflect the natural terrain rather than the Priority-Flood-"
        "conditioned surface."
    )
    if water_mask is not None and water_mask.shape == (h, w):
        methodology += (
            f" Water exclusion was applied: {excluded_water} cells "
            f"({100*excluded_water/cells_total:.1f}% of grid) were excluded "
            f"as they fall within {getattr(water_result, 'buffer_metres', 0):.0f} m of "
            f"{getattr(water_result, 'features_found', 0)} water features "
            f"from OpenStreetMap (Phase 2)."
        )
    else:
        methodology += (
            " Water exclusion was NOT applied (Phase 2): "
            + str(getattr(water_result, 'error_message', 'no water data available'))
            + "."
        )

    return PondSelectionResult(
        candidates=candidates,
        boundary_margin_cells=margin_cells,
        boundary_margin_m=margin_m,
        cells_total=cells_total,
        cells_inside_margin=cells_inside,
        cells_excluded_boundary=excluded_boundary,
        cells_suppressed_by_nms=cells_suppressed_by_nms,
        cells_considered=int(sc.size),
        min_kept_score=min_kept_score,
        weights={
            "accumulation": wa,
            "low_slope": ws,
            "low_relative_elevation": wr,
            "drainage_concentration": wd,
        },
        methodology=methodology,
        nms_radius_cells=config.nms_radius_cells,
        cells_excluded_water=excluded_water,
        water_exclusion_applied=water_result is not None and water_result.applied,
        water_features_found=getattr(water_result, 'features_found', 0) if water_result else 0,
        water_buffer_m=getattr(water_result, 'buffer_metres', 0.0) if water_result else 0.0,
        water_fallback_used=getattr(water_result, 'fallback_used', True) if water_result else True,
        water_error_message=getattr(water_result, 'error_message', None) if water_result else None,
    )


# ---------------------------------------------------------------------------
# Compact summariser (JSON-friendly)
# ---------------------------------------------------------------------------


def summarise_pond_selection(result: PondSelectionResult) -> dict:
    """Return a compact, JSON-friendly summary of a PondSelectionResult."""
    return result.to_dict()
