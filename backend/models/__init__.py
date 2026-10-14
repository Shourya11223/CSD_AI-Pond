"""Pydantic models for the contour inspection API."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ContourPoint(BaseModel):
    """A single point on a contour line."""
    lat: float = Field(..., description="Latitude in decimal degrees")
    lon: float = Field(..., description="Longitude in decimal degrees")
    elevation: float = Field(..., description="Elevation in meters")


class ContourLine(BaseModel):
    """A contour line with its elevation and coordinate sequence."""
    elevation: float = Field(..., description="Contour elevation in meters")
    points: List[ContourPoint] = Field(..., description="Sequence of (lat, lon) coordinates")


class BoundingBox(BaseModel):
    """Geographic bounding box from contour points."""
    min_lat: float = Field(..., description="Minimum latitude")
    max_lat: float = Field(..., description="Maximum latitude")
    min_lon: float = Field(..., description="Minimum longitude")
    max_lon: float = Field(..., description="Maximum longitude")


# ---- Phase 5: location-based analysis request model ----


class LocationAnalysisRequest(BaseModel):
    """
    Request model for the /api/analyze-location endpoint.

    Parameters
    ----------
    latitude : float
        Center point latitude in decimal degrees (-90 to 90).
    longitude : float
        Center point longitude in decimal degrees (-180 to 180).
    radius_km : float
        Analysis radius in kilometers around the center point.
        The bounding box is computed from (latitude, longitude, radius_km).
        Default: 1.0 km (produces approximately a 2 km x 2 km area).
        Maximum recommended: 10.0 km.
    contour_interval_m : float
        Vertical interval between contour lines in metres.
        Default: 1.0 m (matches the sample data resolution).
    dem_type : str
        OpenTopography DEM type to download.
        Default: "COP30" (Copernicus GLO-30, 30m resolution, global).
        Supported: COP30, COP90, SRTMGL1, SRTMGL3, SRTMGL1_E, AW3D30.
    """
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Center point latitude in decimal degrees (-90 to 90).",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Center point longitude in decimal degrees (-180 to 180).",
    )
    radius_km: float = Field(
        default=1.0,
        gt=0.0,
        le=10.0,
        description=(
            "Analysis radius in kilometers around the center point. "
            "Default: 1.0 km. Maximum: 10.0 km. "
            "Larger radii increase processing time significantly."
        ),
    )
    contour_interval_m: float = Field(
        default=1.0,
        gt=0.0,
        le=100.0,
        description="Vertical interval between contour lines in metres. Default: 1.0 m.",
    )
    dem_type: str = Field(
        default="COP30",
        description=(
            "OpenTopography DEM type. Default: COP30 "
            "(Copernicus GLO-30, 30m resolution, global coverage). "
            "Supported: COP30, COP90, SRTMGL1, SRTMGL3, SRTMGL1_E, AW3D30."
        ),
    )


class LocationSourceInfo(BaseModel):
    """
    Source metadata for location-based analyses (Phase 5).

    Provides a small, optional block that describes how the contour
    data was generated (downloaded DEM from OpenTopography) instead
    of being uploaded as a KML/KMZ file.

    Attributes are kept descriptive but small. They do not replace
    any existing field in IntegratedAnalysisResponse.
    """
    source: str = Field(
        default="location",
        description='How the contour data was obtained. Always "location" for this endpoint.',
    )
    latitude: float = Field(
        ..., description="Center point latitude (decimal degrees)."
    )
    longitude: float = Field(
        ..., description="Center point longitude (decimal degrees)."
    )
    radius_km: float = Field(
        ..., description="Analysis radius in kilometers."
    )
    dem_type: str = Field(
        ..., description="OpenTopography DEM type used (e.g. COP30)."
    )
    contour_interval_m: float = Field(
        ..., description="Contour interval in metres."
    )
    south: float = Field(..., description="Bounding box south latitude.")
    north: float = Field(..., description="Bounding box north latitude.")
    west: float = Field(..., description="Bounding box west longitude.")
    east: float = Field(..., description="Bounding box east longitude.")


class ContourInspectionResponse(BaseModel):
    """Response from the /api/inspect-contour endpoint."""
    filename: str = Field(..., description="Name of the uploaded file")
    contour_count: int = Field(..., description="Number of distinct contour lines found")
    total_coordinate_points: int = Field(..., description="Total number of coordinate points across all contours")
    min_elevation_m: float = Field(..., description="Minimum elevation among all contours")
    max_elevation_m: float = Field(..., description="Maximum elevation among all contours")
    estimated_contour_interval_m: Optional[float] = Field(
        None,
        description="Estimated contour interval (if derivable from unique elevations)"
    )
    bounding_box: BoundingBox = Field(..., description="Geographic bounding box")
    error: Optional[str] = Field(None, description="Error message if parsing failed")


class ParseError(Exception):
    """Raised when KML/KMZ parsing fails."""
    pass


# ---- Stage 2: terrain model response models ----

class ProjectionInfo(BaseModel):
    """Information about the local projection used for the terrain grid."""
    projection: str = Field(..., description="Projection name")
    center_lat_deg: float = Field(..., description="Latitude of the projection centre")
    center_lon_deg: float = Field(..., description="Longitude of the projection centre")
    metres_per_degree_lat: float = Field(..., description="Metres per degree of latitude")
    metres_per_degree_lon: float = Field(..., description="Metres per degree of longitude at the centre latitude")
    epsg_note: str = Field(..., description="Notes on the projection choice")


class TerrainGridSummary(BaseModel):
    """Compact summary of an interpolated terrain grid (for API response)."""
    shape: List[int] = Field(..., description="Full grid [height, width]")
    min: float = Field(..., description="Minimum interpolated elevation in metres")
    max: float = Field(..., description="Maximum interpolated elevation in metres")
    mean: float = Field(..., description="Mean interpolated elevation in metres")
    std: float = Field(..., description="Standard deviation of interpolated elevation in metres")
    sampled_shape: List[int] = Field(..., description="Shape of the sampled sub-grid")
    sampled_grid: List[List[float]] = Field(..., description="Sub-sampled grid for validation")


class TerrainBuildResponse(BaseModel):
    """Response from the /api/build-terrain endpoint."""
    filename: str = Field(..., description="Name of the uploaded file")
    grid_width: int = Field(..., description="Number of grid columns")
    grid_height: int = Field(..., description="Number of grid rows")
    grid_cell_size_m: float = Field(..., description="Grid cell size in metres (after any auto-coarsening)")
    requested_grid_cell_size_m: float = Field(..., description="Grid cell size originally requested")
    min_elevation_m: float = Field(..., description="Minimum interpolated elevation in metres")
    max_elevation_m: float = Field(..., description="Maximum interpolated elevation in metres")
    mean_elevation_m: float = Field(..., description="Mean interpolated elevation in metres")
    std_elevation_m: float = Field(..., description="Standard deviation of interpolated elevation in metres")
    contour_min_elevation_m: float = Field(..., description="Minimum contour elevation present in the source data")
    contour_max_elevation_m: float = Field(..., description="Maximum contour elevation present in the source data")
    num_sample_points: int = Field(..., description="Number of points used for interpolation (after thinning)")
    num_contour_points: int = Field(..., description="Total number of contour points in the source data")
    contour_count: int = Field(..., description="Number of distinct contour lines")
    projection_info: ProjectionInfo = Field(..., description="Coordinate reference / projection details")
    bounding_box: BoundingBox = Field(..., description="Geographic bounding box of the source data")
    grid_summary: TerrainGridSummary = Field(..., description="Compact summary of the interpolated grid")
    idw_power: float = Field(..., description="IDW power exponent used")
    idw_k: int = Field(..., description="Number of nearest neighbours used for IDW interpolation")
    idw_epsilon: float = Field(..., description="IDW epsilon guard against division by zero")
    elevation_in_range: bool = Field(..., description="True if interpolated elevations are within the contour range")
    error: Optional[str] = Field(None, description="Error message if building the terrain model failed")


# ---- Stage 3: hydrology response models ----


class DepressionFillStats(BaseModel):
    """Statistics from the Priority-Flood depression-filling step."""
    modified_cells: int = Field(..., description="Number of cells whose elevation was raised")
    max_elevation_adjustment_m: float = Field(..., description="Maximum single-cell elevation raise in metres")
    total_elevation_adjustment_m: float = Field(..., description="Sum of all elevation raises in metres")
    mean_adjustment_m: float = Field(..., description="Mean elevation raise over modified cells")


class FlowDirectionStats(BaseModel):
    """Statistics from D8 flow-direction computation."""
    valid_flow_cells: int = Field(..., description="Number of cells with a defined downhill flow direction")
    sink_cells: int = Field(..., description="Number of cells with no lower neighbour (boundary or flat)")
    d8_encoding: dict = Field(
        ...,
        description=(
            "Integer encoding for the 8 D8 directions: 1=E, 2=SE, 3=S, 4=SW, "
            "5=W, 6=NW, 7=N, 8=NE. Value 0 = no outflow (sink/boundary)."
        ),
    )


class FlowAccumulationStats(BaseModel):
    """Statistics from the flow-accumulation step."""
    max_accumulated_cells: int = Field(..., description="Maximum upstream cell count")
    max_accumulated_area_m2: float = Field(..., description="Maximum contributing area in square metres")
    max_accum_row: int = Field(..., description="Grid row (y) of the maximum-accumulation cell (0-based)")
    max_accum_col: int = Field(..., description="Grid column (x) of the maximum-accumulation cell (0-based)")
    min_accumulated_cells: int = Field(..., description="Minimum upstream cell count (usually 1)")
    total_flowing_cells: int = Field(..., description="Number of cells with non-zero accumulation")



# ---- Stage 3 extended diagnostics models ----


class ElevationChangeStats(BaseModel):
    """Side-by-side elevation statistics for the original and filled DEMs."""
    original_min: float = Field(..., description="Minimum elevation of the original (pre-fill) DEM")
    original_max: float = Field(..., description="Maximum elevation of the original (pre-fill) DEM")
    original_mean: float = Field(..., description="Mean elevation of the original DEM")
    original_std: float = Field(..., description="Std deviation of the original DEM")
    filled_min: float = Field(..., description="Minimum elevation of the filled DEM")
    filled_max: float = Field(..., description="Maximum elevation of the filled DEM")
    filled_mean: float = Field(..., description="Mean elevation of the filled DEM")
    filled_std: float = Field(..., description="Std deviation of the filled DEM")
    mean_increase: float = Field(..., description="Change in mean elevation (filled minus original)")
    max_increase: float = Field(..., description="Change in max elevation (filled minus original)")


class DepressionFillDiagnostics(BaseModel):
    """
    Extended diagnostics for the Priority-Flood depression-filling step.

    These diagnostics quantify whether the depression-filling algorithm
    made large, terrain-distorting adjustments or only small corrections
    consistent with normal interpolation noise.
    """
    total_cells: int = Field(..., description="Total number of grid cells")
    modified_cells: int = Field(..., description="Number of cells whose elevation was raised")
    modified_pct: float = Field(
        ...,
        description="Percentage of cells modified by the fill (0-100)"
    )
    mean_adjustment_m: float = Field(..., description="Mean elevation raise over modified cells")
    median_adjustment_m: float = Field(..., description="Median elevation raise over modified cells")
    p95_adjustment_m: float = Field(..., description="95th-percentile elevation raise over modified cells")
    max_adjustment_m: float = Field(..., description="Maximum single-cell elevation raise")
    std_adjustment_m: float = Field(..., description="Std deviation of elevation raises")
    cells_above_0_1m: int = Field(..., description="Modified cells with raise > 0.1 m")
    cells_above_0_5m: int = Field(..., description="Modified cells with raise > 0.5 m")
    cells_above_1_0m: int = Field(..., description="Modified cells with raise > 1.0 m")
    cells_above_2_0m: int = Field(..., description="Modified cells with raise > 2.0 m")
    cells_above_5_0m: int = Field(..., description="Modified cells with raise > 5.0 m")
    max_adjustment_row: int = Field(..., description="Grid row of the cell with maximum raise (0-based)")
    max_adjustment_col: int = Field(..., description="Grid column of the cell with maximum raise (0-based)")
    max_adjustment_lat: Optional[float] = Field(
        None,
        description="Latitude of the maximum-raise cell (if projection info was supplied)"
    )
    max_adjustment_lon: Optional[float] = Field(
        None,
        description="Longitude of the maximum-raise cell (if projection info was supplied)"
    )
    elevation_change: ElevationChangeStats = Field(..., description="Elevation statistics comparison")
    no_cells_lowered: bool = Field(
        ...,
        description="True if no cell was lowered by the fill (always True by algorithm design)"
    )
    all_changes_nonnegative: bool = Field(
        ...,
        description="True if every cell change is >= 0 (always True by algorithm design)"
    )


class BoundaryDiagnostics(BaseModel):
    """
    Diagnostics for grid-boundary flow behaviour.

    A well-formed DEM should have all major flow-accumulation outlets
    on the grid boundary, and the cell with the highest accumulation
    should be one of those boundary outlets.
    """
    total_boundary_cells: int = Field(..., description="Total number of cells on the grid boundary")
    boundary_outlets: int = Field(
        ...,
        description=(
            "Number of boundary cells that have no downstream neighbour "
            "(flow direction = 0 because the cell's steepest gradient points off-grid)"
        )
    )
    max_accum_is_boundary: bool = Field(
        ...,
        description=(
            "True if the cell with the highest flow accumulation is on "
            "the grid boundary (expected for a well-formed DEM)"
        )
    )
    max_accum_row: int = Field(..., description="Grid row of the maximum-accumulation cell (0-based)")
    max_accum_col: int = Field(..., description="Grid column of the maximum-accumulation cell (0-based)")
    max_accum_lat: Optional[float] = Field(
        None,
        description="Latitude of the max-accumulation cell (if projection info was supplied)"
    )
    max_accum_lon: Optional[float] = Field(
        None,
        description="Longitude of the max-accumulation cell (if projection info was supplied)"
    )


class HydrologyDiagnostics(BaseModel):
    """
    Extended diagnostics for the hydrology pipeline.

    These diagnostics do not alter the algorithm but expose detailed
    statistical summaries for quality-assurance, report writing, and
    debugging.
    """
    depression_fill: DepressionFillDiagnostics = Field(..., description="Depression-filling diagnostics")
    boundary: BoundaryDiagnostics = Field(..., description="Boundary flow diagnostics")

class HydrologyAnalysisResponse(BaseModel):
    """
    Response from the /api/analyze-hydrology endpoint.

    Contains compact statistics only — the full flow-direction and
    flow-accumulation grids are deliberately omitted to keep the
    response size bounded.
    """
    filename: str = Field(..., description="Name of the uploaded contour file")
    grid_width: int = Field(..., description="Terrain grid width in cells")
    grid_height: int = Field(..., description="Terrain grid height in cells")
    grid_cell_size_m: float = Field(..., description="Terrain grid cell size in metres")
    # Terrain source info
    contour_count: int = Field(..., description="Number of contours parsed from the file")
    contour_min_elevation_m: float = Field(..., description="Minimum elevation among source contours")
    contour_max_elevation_m: float = Field(..., description="Maximum elevation among source contours")
    interpolated_min_elevation_m: float = Field(..., description="Minimum interpolated elevation")
    interpolated_max_elevation_m: float = Field(..., description="Maximum interpolated elevation")
    # Depression filling
    depression_fill: DepressionFillStats = Field(..., description="Depression-filling statistics")
    # D8 flow direction
    flow_direction: FlowDirectionStats = Field(..., description="D8 flow-direction statistics")
    # Flow accumulation
    flow_accumulation: FlowAccumulationStats = Field(..., description="Flow-accumulation statistics")
    error: Optional[str] = Field(None, description="Error message if analysis failed")
    diagnostics: Optional[HydrologyDiagnostics] = Field(
        None,
        description="Extended diagnostics for depression filling and boundary behaviour. "
        "Present when diagnostics=True (default)."
    )




# ---- Stage 4: pond candidate selection response models ----


class FactorScores(BaseModel):
    """Individual suitability factor scores, each in [0, 100]."""
    accumulation: float = Field(
        ...,
        description="Flow accumulation percentile (higher = larger upstream catchment)",
    )
    low_slope: float = Field(
        ...,
        description="Inverse-slope percentile (higher = flatter local terrain)",
    )
    low_relative_elevation: float = Field(
        ...,
        description="Inverse-relative-elevation percentile (higher = more valley-like)",
    )
    drainage_concentration: float = Field(
        ...,
        description="Drainage concentration percentile (accumulation + on-flow-path bonus)",
    )


class PondCandidate(BaseModel):
    """A single ranked pond candidate location."""
    rank: int = Field(..., description="1-based rank (1 = best)")
    row: int = Field(..., description="Grid row (0-based)")
    col: int = Field(..., description="Grid column (0-based)")
    lat: Optional[float] = Field(None, description="Latitude in decimal degrees")
    lon: Optional[float] = Field(None, description="Longitude in decimal degrees")
    elevation_m: float = Field(..., description="Elevation at the candidate cell (metres)")
    flow_accumulation_cells: int = Field(
        ..., description="Upstream contributing cell count (D8)"
    )
    upstream_area_m2: float = Field(
        ..., description="Upstream contributing area in square metres"
    )
    local_slope_m_per_m: float = Field(
        ..., description="Local slope (rise/run) at the candidate cell"
    )
    local_slope_deg: float = Field(
        ..., description="Local slope in degrees"
    )
    relative_elevation_m: float = Field(
        ...,
        description=(
            "Elevation minus neighbourhood mean (negative => cell is in a "
            "local valley)"
        ),
    )
    factor_scores: FactorScores = Field(
        ..., description="Individual factor scores in [0, 100]"
    )
    suitability_score: float = Field(
        ..., description="Final composite suitability score in [0, 100]"
    )


class PondSelectionDiagnostics(BaseModel):
    """Diagnostics describing how the candidate list was produced."""
    boundary_margin_cells: int = Field(
        ..., description="Exclusion margin expressed in cells"
    )
    boundary_margin_m: float = Field(
        ..., description="Exclusion margin expressed in metres"
    )
    cells_total: int = Field(..., description="Total cells in the DEM")
    cells_inside_margin: int = Field(
        ..., description="Cells inside the allowed interior region"
    )
    cells_excluded_boundary: int = Field(
        ..., description="Cells removed because they lie on/within the boundary margin"
    )
    cells_suppressed_by_nms: int = Field(
        ...,
        description=(
            "Interior cells that were within the NMS radius of a higher-"
            "scoring cell and were therefore suppressed (i.e. not chosen "
            "as a distinct candidate)."
        ),
    )
    cells_considered: int = Field(
        ..., description="Number of interior cells passed to NMS"
    )
    min_kept_score: float = Field(
        ...,
        description=(
            "Lowest composite score among the kept candidates. The "
            "algorithm does not impose a hard threshold; this is purely "
            "informative."
        ),
    )
    nms_radius_cells: int = Field(
        ..., description="Non-maximum suppression radius in cells"
    )
    weights: dict = Field(
        ..., description="Composite-score weights (must sum to 1.0)"
    )
    methodology: str = Field(
        ...,
        description="Human-readable description of the candidate selection methodology",
    )


class PondSelectionResponse(BaseModel):
    """Response from the /api/find-pond-candidates endpoint."""
    filename: str = Field(..., description="Name of the uploaded contour file")
    grid_width: int = Field(..., description="Terrain grid width in cells")
    grid_height: int = Field(..., description="Terrain grid height in cells")
    grid_cell_size_m: float = Field(..., description="Terrain grid cell size in metres")
    grid_extent: dict = Field(
        ...,
        description=(
            "Geographic extent of the regular terrain grid (cell centres, "
            "inclusive), derived from origin_xy_m. This is what bounds the "
            "candidate lat/lon values; it may be slightly LARGER than the "
            "raw contour point bounding box (by at most one cell size on "
            "each side) because the grid is padded by half a cell."
        ),
    )
    contour_extent: dict = Field(
        ...,
        description=(
            "Geographic bounding box of the raw contour points (the input "
            "extent). Provided for context only; the grid extent is the "
            "authoritative bounds for the candidate lat/lon values."
        ),
    )
    contour_count: int = Field(..., description="Number of contours parsed from the file")
    num_candidates: int = Field(..., description="Number of candidates returned")
    candidates: List[PondCandidate] = Field(
        ..., description="Ranked list of pond candidate locations"
    )
    diagnostics: PondSelectionDiagnostics = Field(
        ..., description="Selection diagnostics and methodology"
    )
    error: Optional[str] = Field(
        None, description="Error message if candidate selection failed"
    )
# ---------------------------------------------------------------------------
# Stage 5: Catchment delineation models
# ---------------------------------------------------------------------------


class CatchmentBoundaryInfo(BaseModel):
    """Geographic boundary representation of the catchment for frontend."""
    boundary_type: str = Field(
        ...,
        description=(
            "Type: 'convex_hull', 'boundary_centroids', or 'empty'."
        ),
    )
    boundary_coordinates: List[List[float]] = Field(
        default_factory=list,
        description="List of [lon, lat] coordinate pairs forming the boundary.",
    )
    num_boundary_cells: int = Field(..., description="Number of boundary cells.")
    num_boundary_points: int = Field(..., description="Number of coordinate points.")
    bounding_box: dict = Field(
        ..., description="{min_lat, max_lat, min_lon, max_lon}."
    )


class CatchmentDiagnosticsInfo(BaseModel):
    """Validation and performance diagnostics for catchment delineation."""
    outlet_in_catchment: bool = Field(..., description="Outlet is in its catchment.")
    no_duplicate_cells: bool = Field(..., description="No cells added twice.")
    traversal_terminated_safely: bool = Field(..., description="BFS terminated safely.")
    cells_visited: int = Field(..., description="Total cells visited during BFS.")
    max_queue_size: int = Field(..., description="Maximum BFS queue size.")
    flow_accum_consistent: bool = Field(
        ..., description="flow_accum_at_outlet == catchment_cells."
    )
    area_consistent: bool = Field(..., description="Area math is correct.")
    area_within_grid: bool = Field(..., description="Catchment area <= grid area.")



class CatchmentDelineationResponse(BaseModel):
    """Response from the /api/delineate-catchment endpoint."""
    filename: str = Field(..., description="Name of the uploaded contour file.")
    grid_width: int = Field(..., description="Terrain grid width in cells.")
    grid_height: int = Field(..., description="Terrain grid height in cells.")
    grid_cell_size_m: float = Field(..., description="Terrain grid cell size in metres.")
    grid_area_m2: float = Field(..., description="Total grid area in square metres.")
    outlet: dict = Field(..., description="Outlet cell: row, col, lat, lon.")
    catchment_cells: int = Field(..., description="Number of cells in the catchment.")
    catchment_area_m2: float = Field(..., description="Catchment area in m^2.")
    catchment_area_ha: float = Field(..., description="Catchment area in hectares.")
    catchment_area_km2: float = Field(..., description="Catchment area in km^2.")
    catchment_pct_of_grid: float = Field(
        ..., description="Catchment area as percentage of total grid area."
    )
    flow_accum_at_outlet: int = Field(
        ..., description="Flow accumulation (cells) at the outlet."
    )
    outlet_upstream_area_m2: float = Field(
        ..., description="Upstream contributing area at the outlet in m^2."
    )
    boundary: CatchmentBoundaryInfo = Field(
        ..., description="Geographic boundary for frontend visualization."
    )
    diagnostics: CatchmentDiagnosticsInfo = Field(
        ..., description="Validation and performance diagnostics."
    )
    error: Optional[str] = Field(
        None, description="Error message if catchment delineation failed."
    )


class PondCandidateInfo(BaseModel):
    """Compact view of a single ranked pond candidate for the integrated response."""
    rank: int = Field(..., description="1-based rank (1 = best).")
    row: int = Field(..., description="Grid row index.")
    col: int = Field(..., description="Grid column index.")
    lat: float = Field(..., description="Latitude in decimal degrees.")
    lon: float = Field(..., description="Longitude in decimal degrees.")
    elevation_m: float = Field(
        ..., description="Terrain elevation at the candidate in metres."
    )
    suitability_score: float = Field(
        ..., description="Final composite suitability score in [0, 100]."
    )
    flow_accumulation_cells: int = Field(
        ..., description="Number of upstream cells draining to this candidate."
    )
    local_slope_deg: float = Field(
        ..., description="Local terrain slope at the candidate in degrees."
    )
    relative_elevation_m: float = Field(
        ..., description="Elevation relative to local neighbourhood mean in metres."
    )
    factor_scores: FactorScores = Field(
        ..., description="Individual factor scores in [0, 100]."
    )


class WaterExclusionInfo(BaseModel):
    """Concise summary of the Phase 2 water exclusion analysis."""
    applied: bool = Field(
        ..., description="Whether water exclusion was successfully applied."
    )
    fallback_used: bool = Field(
        ..., description="Whether a fallback (no exclusion) was used due to an error."
    )
    features_found: int = Field(
        0, description="Number of water features found from OpenStreetMap."
    )
    feature_types: List[str] = Field(
        default_factory=list, description="Types of water features found."
    )
    cells_excluded: int = Field(
        0, description="Number of grid cells excluded as water areas."
    )
    buffer_metres: float = Field(
        0.0, description="Safety buffer applied around water features in metres."
    )
    error_message: Optional[str] = Field(
        None, description="Non-fatal error message if water exclusion failed."
    )


class PondCapacityInfo(BaseModel):
    """Pond depth and storage volume estimates (Phase 4).

    All numeric values are derived from the terrain DEM via
    trapezoidal elevation-slice integration.  The catchment area is
    the upstream contributing area of the pond; the surface_area_m2
    is the local water-surface footprint of the pond itself.
    """
    usable_depth_m: float = Field(
        ...,
        description=(
            "Estimated usable water depth in metres.  Equal to "
            "max_depth_m minus the safety freeboard."
        ),
    )
    max_depth_m: float = Field(
        ...,
        description=(
            "Maximum terrain-based depth in metres.  Equal to the candidate "
            "elevation minus the minimum neighbour elevation within the "
            "configured neighbourhood radius."
        ),
    )
    usable_spill_elevation_m: float = Field(
        ...,
        description=(
            "Elevation of the water surface at the design usable depth "
            "(candidate_elevation_m + usable_depth_m)."
        ),
    )
    spill_elevation_m: float = Field(
        ...,
        description=(
            "Estimated natural basin rim elevation.  Computed as the "
            "configurable percentile of higher-neighbour elevations."
        ),
    )
    cell_area_m2: float = Field(
        ..., description="Area of a single DEM grid cell in m^2."
    )
    surface_area_m2: float = Field(
        ...,
        description=(
            "Estimated pond water-surface area at the design water level "
            "in m^2.  Distinct from the upstream catchment area."
        ),
    )
    storage_volume_m3: float = Field(
        ...,
        description=(
            "Estimated pond storage volume at the design water level "
            "in cubic metres (m^3)."
        ),
    )
    storage_volume_litres: float = Field(
        ...,
        description=(
            "Estimated pond storage volume in litres (1 m^3 = 1000 L)."
        ),
    )
    method: str = Field(
        ..., description="Human-readable description of the estimation method."
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description="Assumptions made by the estimation algorithm.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Reliability warnings (e.g. flat terrain).",
    )
    num_slices: int = Field(
        ..., description="Number of elevation slices used in trapezoidal integration."
    )
    neighbourhood_radius_cells: int = Field(
        ..., description="Neighbourhood radius used to find the basin rim (cells)."
    )
    freeboard_m: float = Field(
        ..., description="Safety freeboard subtracted from max depth (metres)."
    )
    candidate_elevation_m: float = Field(
        ...,
        description="Elevation of the selected pond candidate from the original DEM.",
    )
    min_neighbour_elevation_m: float = Field(
        ...,
        description="Minimum neighbour elevation within the neighbourhood radius.",
    )
    max_neighbour_elevation_m: float = Field(
        ...,
        description="Maximum neighbour elevation within the neighbourhood radius.",
    )
    mean_neighbour_elevation_m: float = Field(
        ...,
        description="Mean neighbour elevation within the neighbourhood radius.",
    )
    cells_flooded_at_design_level: int = Field(
        ...,
        description=(
            "Number of DEM cells flooded at the design water level "
            "(used to derive surface_area_m2)."
        ),
    )


class IntegratedAnalysisResponse(BaseModel):
    """Response from the /api/analyze-contour endpoint (all stages combined)."""
    filename: str = Field(..., description="Name of the uploaded contour file.")
    source_info: Optional[LocationSourceInfo] = Field(
        None,
        description=(
            "Optional metadata describing how the contour data was "
            "obtained. Populated for location-based analyses "
            "(Phase 5); null for KML/KMZ uploads."
        ),
    )
    grid_width: int = Field(..., description="Terrain grid width in cells.")
    grid_height: int = Field(..., description="Terrain grid height in cells.")
    grid_cell_size_m: float = Field(..., description="Terrain grid cell size in metres.")
    contour_count: int = Field(..., description="Number of contours parsed.")
    num_candidates: int = Field(
        ..., description="Number of valid pond candidates returned."
    )
    pond_candidates: List[PondCandidateInfo] = Field(
        ..., description="Ranked list of pond candidates (best first)."
    )
    selected_pond: dict = Field(..., description="Selected pond candidate details.")
    catchment_cells: int = Field(..., description="Number of cells in the catchment.")
    catchment_area_m2: float = Field(..., description="Catchment area in m^2.")
    catchment_area_ha: float = Field(..., description="Catchment area in hectares.")
    catchment_area_km2: float = Field(..., description="Catchment area in km^2.")
    catchment_pct_of_grid: float = Field(
        ..., description="Catchment area as percentage of total grid area."
    )
    flow_accum_at_outlet: int = Field(
        ..., description="Flow accumulation (cells) at the outlet."
    )
    flow_accum_consistent: bool = Field(
        ..., description="Whether flow_accum equals catchment cells."
    )
    boundary: CatchmentBoundaryInfo = Field(
        ..., description="Catchment boundary for visualization."
    )
    diagnostics: CatchmentDiagnosticsInfo = Field(
        ..., description="Catchment validation diagnostics."
    )
    water_exclusion: WaterExclusionInfo = Field(
        ..., description="Summary of the Phase 2 water exclusion analysis."
    )
    pond_capacity: Optional["PondCapacityInfo"] = Field(
        None,
        description="Pond depth and storage volume estimates for the selected candidate (Phase 4).",
    )
    error: Optional[str] = Field(
        None, description="Error message if analysis failed."
    )
    time_elapsed_s: float = Field(..., description="Execution time in seconds.")
    # ---- Phase 8: optional rainfall and weather data (additive) ----
    rainfall: Optional["RainfallInfo"] = Field(
        None,
        description=(
            "Optional Phase 8 rainfall data. Null if the rainfall service "
            "could not determine a lookup location (e.g., empty contour data) "
            "or if the provider was unavailable."
        ),
    )
    weather: Optional["WeatherInfo"] = Field(
        None,
        description=(
            "Optional Phase 8 weather data. Null if not retrieved."
        ),
    )
    rainfall_lookup: Optional["RainfallLookupMetadata"] = Field(
        None,
        description=(
            "Optional metadata describing how the rainfall lookup location "
            "was determined (e.g., 'catchment_centroid')."
        ),
    )
    # ---- Phase 9: design rainfall (additive) ----
    design_rainfall: Optional["DesignRainfallInfo"] = Field(
        None,
        description=(
            "Optional Phase 9 design rainfall data derived from historical "
            "annual-maximum daily rainfall using the Gumbel distribution. "
            "Null if the design-rainfall service was unavailable or returned an error."
        ),
    )
    # ---- Phase 11A: catchment terrain diagnostics (additive) ----
    catchment_terrain: Optional["CatchmentTerrainDiagnostics"] = Field(
        None,
        description=(
            "Optional Phase 11A catchment terrain diagnostics: catchment-scoped "
            "slope statistics (degrees and m/m), elevation statistics (min/max/relief), "
            "and the longest D8 flow path length. Null if computation failed or "
            "catchment was degenerate."
        ),
    )
    # ---- Phase 11B: land cover, soil, runoff, Tc, pond adequacy (additive) ----
    land_cover: Optional["LandCoverInfo"] = Field(
        None,
        description=(
            "Optional Phase 11 land-cover analysis: area-weighted fractions of "
            "OpenStreetMap-derived land-cover classes within the catchment "
            "bounding box. Null when the OSM provider is unavailable or no "
            "features could be mapped."
        ),
    )
    soil_group: Optional["SoilGroupInfo"] = Field(
        None,
        description=(
            "Optional Phase 11 soil / hydrologic-soil-group (HSG) lookup. "
            "data_available is False in this build because no real soil-data "
            "provider is connected; documented candidate sources are listed "
            "in candidate_sources_considered for provenance."
        ),
    )
    runoff: Optional["RunoffInfo"] = Field(
        None,
        description=(
            "Optional Phase 11 SCS-CN runoff estimate: design rainfall depth, "
            "weighted curve number, S, Ia, runoff depth, runoff volume. "
            "Null when land cover, soil group, or design rainfall is unavailable."
        ),
    )
    time_of_concentration: Optional["TimeOfConcentrationInfo"] = Field(
        None,
        description=(
            "Optional Phase 11 time of concentration (Kirpich, 1940) using "
            "the longest D8 flow path and mean catchment slope from Phase 11A. "
            "Reported as a hydrologic diagnostic; the design rainfall remains "
            "a 24-hour depth and is not converted to an intensity here."
        ),
    )
    pond_adequacy: Optional["PondAdequacyInfo"] = Field(
        None,
        description=(
            "Optional Phase 11 pond adequacy: comparison of available pond "
            "storage against the SCS-CN runoff volume. Status thresholds are "
            "explicit, documented engineering judgments (no safety factor)."
        ),
    )


# ---- Phase 9: Design rainfall data model ----


class DesignRainfallInfo(BaseModel):
    """
    Design rainfall data derived from historical annual-maximum daily rainfall
    using the Gumbel extreme-value distribution (Phase 9 integration).

    Returned as the optional ``design_rainfall`` field in integrated analyses.
    Mirrors the fields of DesignRainfallResult from the design-rainfall service.
    """
    source: str = Field(
        ..., description="Identifier of the data provider (e.g., 'Open-Meteo-ERA5')."
    )
    latitude: float = Field(..., description="Lookup latitude in decimal degrees.")
    longitude: float = Field(..., description="Lookup longitude in decimal degrees.")
    data_period_start: Optional[str] = Field(
        None,
        description="ISO 8601 date string for the start of the data period.",
    )
    data_period_end: Optional[str] = Field(
        None,
        description="ISO 8601 date string for the end of the data period.",
    )
    number_of_years: Optional[int] = Field(
        None,
        description="Number of complete calendar years with annual maxima.",
    )
    number_of_observations: Optional[int] = Field(
        None,
        description="Total number of daily observations used.",
    )
    annual_maxima_count: Optional[int] = Field(
        None,
        description="Number of annual maximum values extracted.",
    )
    annual_maximum_min_mm: Optional[float] = Field(
        None,
        description="Minimum value in the annual-maximum series (mm).",
    )
    annual_maximum_mean_mm: Optional[float] = Field(
        None,
        description="Mean of the annual-maximum series (mm).",
    )
    annual_maximum_max_mm: Optional[float] = Field(
        None,
        description="Maximum value in the annual-maximum series (mm).",
    )
    return_period_years: float = Field(
        25.0,
        description="Requested return period in years.",
    )
    design_rainfall_mm: Optional[float] = Field(
        None,
        description="Estimated design rainfall depth for the return period (mm).",
    )
    distribution: str = Field(
        "Gumbel",
        description="Statistical distribution used for the estimate.",
    )
    fitting_method: str = Field(
        "method_of_moments",
        description="Fitting method used.",
    )
    data_quality: str = Field(
        "unknown",
        description=(
            "Data-quality label: 'insufficient', 'limited', 'moderate', "
            "'stronger historical basis'."
        ),
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Human-readable warnings (e.g. short-record warnings).",
    )
    fetched_at: str = Field(
        ..., description="ISO 8601 timestamp when the result was computed."
    )
    design_rainfall_available: bool = Field(
        ...,
        description="True when design_rainfall_mm is a valid estimate.",
    )
    error_message: Optional[str] = Field(
        None,
        description="Error description when design_rainfall_available is False.",
    )


# ---- Phase 11A: Catchment terrain diagnostics model ----


class CatchmentTerrainDiagnostics(BaseModel):
    """
    Catchment-scoped terrain diagnostics (Phase 11A).

    All values are derived purely from the existing DEM, D8 flow
    direction grid, and catchment mask.  No external data is used
    and no engineering parameters (e.g. roughness, CN, runoff
    coefficient) are introduced.

    These diagnostics are intended as input quantities for later
    runoff / time-of-concentration / SCS-CN phases.
    """
    # ---- Slope statistics (over catchment cells) ----
    mean_slope_deg: float = Field(
        ...,
        description=(
            "Mean slope of catchment cells in degrees. Computed from the "
            "finite-difference gradient of the original (pre-fill) DEM, "
            "masked to catchment cells, then converted via atan(m/m)."
        ),
    )
    mean_slope_m_per_m: float = Field(
        ...,
        description=(
            "Mean slope of catchment cells in m/m (rise/run). "
            "Computed from sqrt(dx^2 + dy^2) of the gradient."
        ),
    )
    max_slope_deg: float = Field(
        ...,
        description="Maximum slope among catchment cells in degrees.",
    )
    max_slope_m_per_m: float = Field(
        ...,
        description="Maximum slope among catchment cells in m/m.",
    )
    min_slope_deg: float = Field(
        ...,
        description="Minimum slope among catchment cells in degrees.",
    )
    min_slope_m_per_m: float = Field(
        ...,
        description="Minimum slope among catchment cells in m/m.",
    )

    # ---- Elevation statistics (over catchment cells) ----
    min_elevation_m: float = Field(
        ...,
        description="Minimum DEM elevation within the catchment (metres).",
    )
    max_elevation_m: float = Field(
        ...,
        description="Maximum DEM elevation within the catchment (metres).",
    )
    relief_m: float = Field(
        ...,
        description=(
            "Elevation relief of the catchment: max_elevation_m - min_elevation_m "
            "(metres). 0 for single-cell catchments."
        ),
    )
    mean_elevation_m: float = Field(
        ...,
        description="Mean DEM elevation within the catchment (metres).",
    )

    # ---- Longest D8 flow path ----
    longest_flow_path_m: float = Field(
        ...,
        description=(
            "Length of the longest upstream D8 flow path terminating at the "
            "outlet, in metres. Cardinal steps contribute cell_size_m; "
            "diagonal steps contribute cell_size_m * sqrt(2)."
        ),
    )
    longest_flow_path_cells: int = Field(
        ...,
        description=(
            "Number of cells traversed along the longest upstream D8 path "
            "(from headwater to outlet, inclusive)."
        ),
    )
    longest_flow_path_outlet_row: int = Field(
        ...,
        description="Row of the outlet cell used for the longest-path trace.",
    )
    longest_flow_path_outlet_col: int = Field(
        ...,
        description="Column of the outlet cell used for the longest-path trace.",
    )
    number_of_headwater_cells: int = Field(
        ...,
        description=(
            "Number of headwater (source) cells identified in the catchment "
            "(cells with zero upstream neighbours)."
        ),
    )

    # ---- Methodology and diagnostics ----
    method: str = Field(
        ...,
        description=(
            "Human-readable description of the slope, elevation, and "
            "longest-flow-path methodologies."
        ),
    )
    warnings: List[str] = Field(
        default_factory=list,
        description=(
            "Warnings (e.g. degenerate catchments, zero path lengths). "
            "Empty list when no conditions were detected."
        ),
    )


# ---- Phase 8: Rainfall and Weather data models ----


class RainfallInfo(BaseModel):
    """
    Normalized historical/climatological rainfall data (Phase 8).

    Returned by GET /api/rainfall and embedded in integrated analyses
    as the optional ``rainfall`` field.

    The data represents POINT-based historical rainfall estimates
    for the lookup coordinates. This is NOT design rainfall.
    """
    source: str = Field(
        ...,
        description="Identifier of the data provider (e.g., 'Open-Meteo-ERA5').",
    )
    latitude: float = Field(..., description="Lookup latitude in decimal degrees.")
    longitude: float = Field(..., description="Lookup longitude in decimal degrees.")
    data_period_start: Optional[str] = Field(
        None, description="ISO 8601 date string for the start of the data period.",
    )
    data_period_end: Optional[str] = Field(
        None, description="ISO 8601 date string for the end of the data period.",
    )
    annual_rainfall_mm: Optional[float] = Field(
        None,
        description=(
            "Mean annual precipitation in millimetres. Null if data unavailable."
        ),
    )
    monthly_rainfall_mm: Optional[dict] = Field(
        None,
        description=(
            "Mean monthly rainfall totals in mm, keyed by month number "
            "as string ('1' to '12'). Null if unavailable."
        ),
    )
    rainfall_data_available: bool = Field(
        ...,
        description=(
            "True if valid rainfall data was obtained. False indicates the "
            "external provider was unavailable or returned an error."
        ),
    )
    data_resolution: Optional[str] = Field(
        None, description="Spatial resolution of the data (e.g., '0.1 degree').",
    )
    data_quality: str = Field(
        "unknown",
        description=(
            "Quality classification: 'historical_gridded_reanalysis', "
            "'unavailable', etc."
        ),
    )
    fetched_at: str = Field(
        ..., description="ISO 8601 timestamp when data was fetched."
    )
    error_message: Optional[str] = Field(
        None, description="Error description if rainfall_data_available is False.",
    )
    rainy_days: Optional[int] = Field(
        None, description="Approximate number of rainy days in the data period.",
    )
    max_daily_rainfall_mm: Optional[float] = Field(
        None, description="Maximum observed daily rainfall in mm.",
    )
    number_of_observations: Optional[int] = Field(
        None, description="Number of daily observations used to compute statistics.",
    )
    lookup_method: str = Field(
        "point_lookup",
        description=(
            "How the lookup location was determined: 'point_lookup', "
            "'catchment_centroid', 'bbox_centroid', etc."
        ),
    )


class WeatherInfo(BaseModel):
    """
    Supplementary current/forecast weather information (Phase 8).

    This is contextual information, NOT the basis for design rainfall.
    Returned by GET /api/weather and embedded in integrated analyses
    as the optional ``weather`` field.
    """
    source: str = Field(
        ..., description="Identifier of the weather data provider.",
    )
    latitude: float = Field(..., description="Lookup latitude in decimal degrees.")
    longitude: float = Field(..., description="Lookup longitude in decimal degrees.")
    observation_timestamp: Optional[str] = Field(
        None, description="ISO 8601 timestamp of the observation/forecast.",
    )
    temperature_c: Optional[float] = Field(
        None, description="Air temperature in degrees Celsius."
    )
    precipitation_mm: Optional[float] = Field(
        None, description="Recent or forecast precipitation in mm."
    )
    humidity_pct: Optional[float] = Field(
        None, description="Relative humidity in percent."
    )
    wind_speed_kmh: Optional[float] = Field(
        None, description="Wind speed in km/h."
    )
    wind_direction_deg: Optional[float] = Field(
        None, description="Wind direction in degrees (0-360, 0 = North).",
    )
    weather_description: Optional[str] = Field(
        None, description="Short text description of the weather."
    )
    weather_data_available: bool = Field(
        ..., description="True if valid weather data was obtained.",
    )
    fetched_at: str = Field(
        ..., description="ISO 8601 timestamp when data was fetched."
    )
    error_message: Optional[str] = Field(
        None,
        description="Error description if weather_data_available is False.",
    )


class RainfallLookupMetadata(BaseModel):
    """
    Metadata describing how the rainfall lookup location was determined
    in an integrated analysis (Phase 8).
    """
    lookup_location: dict = Field(
        ...,
        description=(
            "The coordinates actually used for the rainfall lookup "
            "(e.g., the catchment centroid or the user-selected point)."
        ),
    )
    lookup_basis: str = Field(
        ...,
        description=(
            "How the lookup location was determined: 'catchment_centroid', "
            "'selected_pond', 'contour_bbox_centroid', 'user_location'."
        ),
    )
    note: Optional[str] = Field(
        None,
        description=(
            "Optional human-readable note (e.g., warning that this is a "
            "point estimate, not a catchment average)."
        ),
    )


# ---------------------------------------------------------------------------
# Phase 11 - Part 1: Land Cover model
# ---------------------------------------------------------------------------


class LandCoverClassFraction(BaseModel):
    """Area fraction for a single land-cover class within the catchment."""
    land_cover_class: str = Field(..., description="Project land-cover class label.")
    area_m2: float = Field(..., description="Total area (m^2) of this class.")
    fraction: float = Field(..., description="Area fraction (0-1) of this class.")
    feature_count: int = Field(..., description="Number of OSM features mapped to this class.")


class LandCoverInfo(BaseModel):
    """
    Land-cover analysis result (Phase 11 - Part 1).

    Source is OpenStreetMap via the Overpass API.  OSM features are
    NOT authoritative land-cover classification.
    """
    data_available: bool = Field(
        ...,
        description="True when at least one OSM feature was mapped to a project land-cover class.",
    )
    source: str = Field(
        "OpenStreetMap / Overpass API",
        description="Identifier of the data source.",
    )
    bbox: Optional[dict] = Field(
        None,
        description="Geographic bounding box (degrees) used for the query.",
    )
    bbox_area_m2: float = Field(
        ...,
        description="Reference area (m^2) used as the denominator for fractions.",
    )
    land_cover_classes: List[LandCoverClassFraction] = Field(
        default_factory=list,
        description="Per-class area and fraction statistics.",
    )
    features_found: int = Field(
        0,
        description="Total number of OSM features returned by Overpass.",
    )
    features_mapped: int = Field(
        0,
        description="Number of OSM features successfully mapped to project classes.",
    )
    query_time_s: float = Field(
        0.0,
        description="Overpass API round-trip time in seconds.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Human-readable warnings about coverage and methodology limitations.",
    )
    error_message: Optional[str] = Field(
        None,
        description="Error description when data_available is False.",
    )


# ---------------------------------------------------------------------------
# Phase 11 - Part 2: Soil / HSG model
# ---------------------------------------------------------------------------


class SoilGroupFraction(BaseModel):
    """Area fraction for a single hydrologic soil group."""
    soil_group: str = Field(..., description="HSG class label (A, B, C, or D).")
    fraction: float = Field(..., description="Area fraction (0-1) of this HSG.")
    feature_count: int = Field(0, description="Number of features mapped to this HSG.")


class CandidateSoilSource(BaseModel):
    """Provenance for a soil-data source that was considered."""
    id: str = Field(..., description="Source identifier.")
    name: str = Field(..., description="Human-readable source name.")
    url: Optional[str] = Field(None, description="Source URL.")
    resolution: Optional[str] = Field(None, description="Source data resolution.")
    status: str = Field(..., description="Connection status: 'connected' or 'not_connected'.")
    reason: Optional[str] = Field(None, description="Reason for current connection status.")


class SoilGroupInfo(BaseModel):
    """
    Soil / HSG analysis result (Phase 11 - Part 2).

    data_available is False in this build because no real soil-data
    provider is connected.  Candidate sources are listed for provenance.
    """
    data_available: bool = Field(
        ...,
        description="True when a real provider returned a valid HSG.",
    )
    source: str = Field(
        "unavailable",
        description="Identifier of the connected provider, or 'unavailable'.",
    )
    lookup_method: str = Field(
        ...,
        description="Description of the lookup strategy used.",
    )
    soil_group: Optional[str] = Field(
        None,
        description="Dominant hydrologic soil group (A, B, C, or D), if available.",
    )
    soil_group_fractions: List[SoilGroupFraction] = Field(
        default_factory=list,
        description="Per-HSG area fractions, if available.",
    )
    bbox: Optional[dict] = Field(
        None,
        description="Geographic bounding box used for the lookup, if applicable.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Human-readable warnings about availability and methodology.",
    )
    error_message: Optional[str] = Field(
        None,
        description="Error description when data_available is False.",
    )
    candidate_sources_considered: List[CandidateSoilSource] = Field(
        default_factory=list,
        description="Provenance of candidate soil-data sources.",
    )


# ---------------------------------------------------------------------------
# Phase 11 - Part 3: SCS-CN runoff model
# ---------------------------------------------------------------------------


class LandCoverCNContribution(BaseModel):
    """Per-class CN contribution used in the area-weighted CN calculation."""
    land_cover_class: str = Field(..., description="Land-cover class label.")
    soil_group: str = Field(..., description="HSG class used for this contribution.")
    cn_ii: int = Field(..., description="CN value for AMC II.")
    cn_amc: float = Field(..., description="CN value adjusted to the chosen AMC condition.")
    area_fraction: float = Field(..., description="Area fraction (0-1) of this class.")
    weighted_cn: float = Field(..., description="area_fraction * cn_amc.")
    warning: Optional[str] = Field(None, description="Per-class warning, if any.")


class RunoffInfo(BaseModel):
    """
    SCS-CN runoff analysis result (Phase 11 - Part 3).
    """
    data_available: bool = Field(
        ...,
        description="True when all required inputs (land cover, HSG, rainfall) were available.",
    )
    source: str = Field(
        "SCS-CN (USDA NRCS NEH-630)",
        description="Source of the SCS-CN method.",
    )
    method: str = Field(
        ...,
        description="Description of the CN lookup and area-weighting methodology.",
    )
    rainfall_P_mm: Optional[float] = Field(
        None,
        description="Design rainfall depth P (mm) used.",
    )
    amc_condition: str = Field(
        "II",
        description="Antecedent moisture condition used: I, II, or III.",
    )
    soil_group: Optional[str] = Field(
        None,
        description="HSG used for the CN lookup.",
    )
    weighted_CN: Optional[float] = Field(
        None,
        description="Area-weighted curve number (0-100).",
    )
    CN_contributions: List[LandCoverCNContribution] = Field(
        default_factory=list,
        description="Per-class CN breakdown.",
    )
    S_mm: Optional[float] = Field(
        None,
        description="Potential retention S (mm) = 25400/CN - 254.",
    )
    Ia_mm: Optional[float] = Field(
        None,
        description="Initial abstraction Ia (mm) = 0.2 * S.",
    )
    runoff_depth_mm: Optional[float] = Field(
        None,
        description="Runoff depth Q (mm) from the SCS-CN equation.",
    )
    runoff_volume_m3: Optional[float] = Field(
        None,
        description="Runoff volume V (m^3) = (Q/1000) * catchment_area_m2.",
    )
    catchment_area_m2: float = Field(
        0.0,
        description="Catchment area (m^2) used to compute runoff volume.",
    )
    catchment_area_ha: float = Field(
        0.0,
        description="Catchment area (ha) used.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Methodology / input warnings.",
    )
    error_message: Optional[str] = Field(
        None,
        description="Error description when data_available is False.",
    )


# ---------------------------------------------------------------------------
# Phase 11 - Part 4: Time of Concentration model
# ---------------------------------------------------------------------------


class TimeOfConcentrationInfo(BaseModel):
    """
    Time of concentration (Phase 11 - Part 4) using Kirpich (1940).
    """
    data_available: bool = Field(
        ...,
        description="True when valid path length and slope were provided.",
    )
    method: str = Field(
        "Kirpich (1940)",
        description="Method used for the Tc estimate.",
    )
    formula: str = Field(
        "Tc = 0.01947 * L^0.77 * S^-0.385  (minutes, m, m/m)",
        description="Formula used.",
    )
    longest_flow_path_m: float = Field(
        0.0,
        description="Longest D8 flow path (m) from Phase 11A.",
    )
    slope_m_per_m: float = Field(
        0.0,
        description="Representative slope (m/m) from Phase 11A.",
    )
    slope_source: str = Field(
        "mean catchment slope (m/m) from Phase 11A",
        description="Source of the slope value.",
    )
    tc_minutes: float = Field(
        0.0,
        description="Time of concentration in minutes.",
    )
    tc_hours: float = Field(
        0.0,
        description="Time of concentration in hours.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Methodology / input warnings.",
    )
    error_message: Optional[str] = Field(
        None,
        description="Error description when data_available is False.",
    )


# ---------------------------------------------------------------------------
# Phase 11 - Part 5: Pond Adequacy model
# ---------------------------------------------------------------------------


class PondAdequacyInfo(BaseModel):
    """
    Pond adequacy (Phase 11 - Part 5).

    Compares design runoff volume against available pond storage.
    No safety factor is applied; thresholds are documented engineering
    judgments, not safety factors.
    """
    data_available: bool = Field(
        ...,
        description="True when both runoff and storage are available.",
    )
    runoff_volume_m3: Optional[float] = Field(
        None,
        description="Design runoff volume (m^3).",
    )
    available_storage_m3: Optional[float] = Field(
        None,
        description="Available pond storage volume (m^3).",
    )
    adequacy_ratio: Optional[float] = Field(
        None,
        description="available_storage / runoff_volume.  None if unavailable.",
    )
    status: str = Field(
        "unavailable",
        description="'pass' (>= 1.0), 'marginal' (>= threshold_marginal), 'fail' (< threshold_marginal), or 'unavailable'.",
    )
    threshold_pass: float = Field(
        1.0,
        description="Adequacy ratio threshold for 'pass' status.",
    )
    threshold_marginal: float = Field(
        0.75,
        description="Adequacy ratio threshold for 'marginal' status.",
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="Methodology warnings.",
    )
    error_message: Optional[str] = Field(
        None,
        description="Error description when data_available is False.",
    )
