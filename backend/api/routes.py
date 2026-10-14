"""
API routes for the contour inspection, terrain modelling, and
hydrological analysis services.
"""
import logging
import time
from fastapi import APIRouter, File, UploadFile, HTTPException

from models import (
    ContourInspectionResponse,
    TerrainBuildResponse,
    ProjectionInfo,
    TerrainGridSummary,
    BoundingBox,
    HydrologyAnalysisResponse,
    DepressionFillStats,
    FlowDirectionStats,
    FlowAccumulationStats,
    HydrologyDiagnostics,
    DepressionFillDiagnostics,
    BoundaryDiagnostics,
    ElevationChangeStats,
    PondSelectionResponse,
    PondCandidate,
    PondSelectionDiagnostics,
    FactorScores,
    CatchmentDelineationResponse,
    CatchmentBoundaryInfo,
    CatchmentDiagnosticsInfo,
    IntegratedAnalysisResponse,
    PondCandidateInfo,
    WaterExclusionInfo,
    PondCapacityInfo,
    LocationAnalysisRequest,
    LocationSourceInfo,
    RainfallInfo,
    WeatherInfo,
    RainfallLookupMetadata,
    DesignRainfallInfo,
    CatchmentTerrainDiagnostics,
    LandCoverInfo,
    SoilGroupInfo,
    RunoffInfo,
    TimeOfConcentrationInfo,
    PondAdequacyInfo,
)
from services.contour_parser import parse_contour_file, ContourParserError
from services.rainfall import get_rainfall, RainfallError, RainfallValidationError
from services.weather import get_weather, WeatherError, WeatherValidationError
from services.design_rainfall import (
    get_design_rainfall,
    DesignRainfallError,
)
from services.land_cover import get_land_cover, summarise_land_cover
from services.soil_group import get_soil_group, summarise_soil_group
from services.scs_cn import compute_scs_cn_runoff, summarise_scs_cn
from services.time_of_concentration import (
    compute_time_of_concentration,
    summarise_time_of_concentration,
)
from services.pond_adequacy import compute_pond_adequacy, summarise_pond_adequacy


# ---------------------------------------------------------------------------
# Phase 8: Rainfall/Weather helper for integrated analysis
# ---------------------------------------------------------------------------


def _build_rainfall_info(result) -> "RainfallInfo":
    """Convert a RainfallResult dataclass to a RainfallInfo Pydantic model."""
    return RainfallInfo(
        source=result.source,
        latitude=result.latitude,
        longitude=result.longitude,
        data_period_start=result.data_period_start,
        data_period_end=result.data_period_end,
        annual_rainfall_mm=result.annual_rainfall_mm,
        monthly_rainfall_mm=result.monthly_rainfall_mm,
        rainfall_data_available=result.rainfall_data_available,
        data_resolution=result.data_resolution,
        data_quality=result.data_quality,
        fetched_at=result.fetched_at,
        error_message=result.error_message,
        rainy_days=result.rainy_days,
        max_daily_rainfall_mm=result.max_daily_rainfall_mm,
        number_of_observations=result.number_of_observations,
        lookup_method=result.lookup_method,
    )


def _build_weather_info(result) -> "WeatherInfo":
    """Convert a WeatherResult dataclass to a WeatherInfo Pydantic model."""
    return WeatherInfo(
        source=result.source,
        latitude=result.latitude,
        longitude=result.longitude,
        observation_timestamp=result.observation_timestamp,
        temperature_c=result.temperature_c,
        precipitation_mm=result.precipitation_mm,
        humidity_pct=result.humidity_pct,
        wind_speed_kmh=result.wind_speed_kmh,
        wind_direction_deg=result.wind_direction_deg,
        weather_description=result.weather_description,
        weather_data_available=result.weather_data_available,
        fetched_at=result.fetched_at,
        error_message=result.error_message,
    )


def _get_rainfall_lookup_coords_for_kml(catchment, integrated):
    """
    Determine rainfall lookup coordinates for KML/KMZ analyses.

    Returns
    -------
    tuple
        (latitude, longitude, lookup_basis, note)
    """
    if (catchment and catchment.boundary
            and catchment.boundary.bounding_box):
        bb = catchment.boundary.bounding_box
        if all(k in bb for k in (
            "min_lat", "max_lat", "min_lon", "max_lon"
        )):
            lat = (bb["min_lat"] + bb["max_lat"]) / 2.0
            lon = (bb["min_lon"] + bb["max_lon"]) / 2.0
            return lat, lon, "catchment_centroid", (
                "Rainfall estimated at catchment bounding-box centroid. "
                "Phase 9 may average rainfall over the full catchment polygon."
            )

    selected = integrated.get("selected_pond", {})
    if "lat" in selected and "lon" in selected:
        return selected["lat"], selected["lon"], "selected_pond", (
            "Rainfall estimated at selected pond outlet location "
            "(catchment centroid not available)."
        )

    return None, None, None, "Could not determine rainfall lookup location."


def _safe_rainfall_weather_lookup(lat, lon, lookup_basis, note):
    """Perform a safe rainfall + weather lookup."""
    rainfall_info = None
    weather_info = None
    rainfall_lookup_meta = None

    if lat is not None and lon is not None:
        try:
            rainfall_result = get_rainfall(lat, lon, use_cache=True)
            rainfall_info = _build_rainfall_info(rainfall_result)
        except RainfallError as exc:
            logger.warning(
                "Rainfall lookup failed for (%.4f, %.4f): %s",
                lat, lon, exc,
            )

        try:
            weather_result = get_weather(lat, lon, use_cache=True)
            weather_info = _build_weather_info(weather_result)
        except WeatherError as exc:
            logger.warning(
                "Weather lookup failed for (%.4f, %.4f): %s",
                lat, lon, exc,
            )

        if rainfall_info is not None or weather_info is not None:
            rainfall_lookup_meta = RainfallLookupMetadata(
                lookup_location={"latitude": lat, "longitude": lon},
                lookup_basis=lookup_basis,
                note=note,
            )

    return rainfall_info, weather_info, rainfall_lookup_meta


# --------------------------------------------------------------------------
# Phase 9: Design rainfall helper for integrated analysis
# --------------------------------------------------------------------------


def _build_design_rainfall_info(result) -> "DesignRainfallInfo":
    """Convert a DesignRainfallResult dataclass to a DesignRainfallInfo Pydantic model."""
    return DesignRainfallInfo(
        source=result.source,
        latitude=result.latitude,
        longitude=result.longitude,
        data_period_start=result.data_period_start,
        data_period_end=result.data_period_end,
        number_of_years=result.number_of_years,
        number_of_observations=result.number_of_observations,
        annual_maxima_count=result.annual_maxima_count,
        annual_maximum_min_mm=result.annual_maximum_min_mm,
        annual_maximum_mean_mm=result.annual_maximum_mean_mm,
        annual_maximum_max_mm=result.annual_maximum_max_mm,
        return_period_years=result.return_period_years,
        design_rainfall_mm=result.design_rainfall_mm,
        distribution=result.distribution,
        fitting_method=result.fitting_method,
        data_quality=result.data_quality,
        warnings=result.warnings,
        fetched_at=result.fetched_at,
        design_rainfall_available=result.design_rainfall_available,
        error_message=result.error_message,
    )


def _safe_design_rainfall_lookup(lat, lon) -> "DesignRainfallInfo | None":
    """
    Perform a safe design-rainfall lookup.

    Calls get_design_rainfall with a 25-year return period.
    Returns None if the service raises DesignRainfallError, allowing the
    main pipeline to continue successfully.

    Parameters
    ----------
    lat : float
        Latitude of the lookup point.
    lon : float
        Longitude of the lookup point.

    Returns
    -------
    DesignRainfallInfo or None
    """
    if lat is None or lon is None:
        return None

    try:
        result = get_design_rainfall(
            latitude=lat,
            longitude=lon,
            return_period_years=25.0,
        )
        return _build_design_rainfall_info(result)
    except DesignRainfallError as exc:
        logger.warning(
            "Design rainfall lookup failed for (%.4f, %.4f): %s",
            lat, lon, exc,
        )
        return None


from services.terrain_model import build_terrain_model, summarise_terrain_grid
from services.hydrology import run_hydrology, summarise_hydrology
from services.pond_selection import (
    find_pond_candidates,
    summarise_pond_selection,
    PondSelectionConfig,
)
from services.water_exclusion import (
    get_water_exclusion_mask,
    summarise_water_exclusion,
    WaterExclusionConfig,
)
from services.pond_capacity import (
    estimate_pond_capacity,
    summarise_pond_capacity,
)
from services.hydrology import _grid_to_geographic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["contour"])


def _compute_bounding_box(contours) -> BoundingBox:
    """Compute the geographic bounding box from all contour points."""
    if not contours:
        return BoundingBox(min_lat=0, max_lat=0, min_lon=0, max_lon=0)
    min_lat = float(min(pt.lat for c in contours for pt in c.points))
    max_lat = float(max(pt.lat for c in contours for pt in c.points))
    min_lon = float(min(pt.lon for c in contours for pt in c.points))
    max_lon = float(max(pt.lon for c in contours for pt in c.points))
    return BoundingBox(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)


def _estimate_contour_interval(contours) -> float | None:
    """Estimate the contour interval from unique elevation values."""
    if not contours:
        return None
    elevations = sorted(set(c.elevation for c in contours))
    if len(elevations) < 2:
        return None
    diffs = [round(elevations[i + 1] - elevations[i], 3) for i in range(len(elevations) - 1)]
    from collections import Counter
    diff_counts = Counter(diffs)
    most_common_diff, count = diff_counts.most_common(1)[0]
    if count >= 2:
        return most_common_diff
    if len(set(diffs)) == 1:
        return diffs[0]
    return None


@router.post(
    "/inspect-contour",
    response_model=ContourInspectionResponse,
    summary="Inspect uploaded contour map (KML/KMZ)",
    description=(
        "Upload a KML or KMZ file containing contour lines as Placemarks "
        "with LineString geometries. The service extracts elevation from "
        "each Placemark's name and coordinates from its LineString, then "
        "returns summary statistics including contour count, elevation "
        "range, estimated contour interval, and geographic bounding box."
    ),
)
async def inspect_contour(file: UploadFile = File(...)) -> ContourInspectionResponse:
    """
    Inspect a KML or KMZ contour map file.

    Args:
        file: Uploaded .kml or .kmz file.

    Returns:
        ContourInspectionResponse with summary statistics.

    Raises:
        HTTPException: 400 for invalid files, 500 for parsing errors.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    name_lower = file.filename.lower()
    if not (name_lower.endswith(".kml") or name_lower.endswith(".kmz")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Expected .kml or .kmz.",
        )

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to read uploaded file: {exc}"
        ) from exc

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        contours = parse_contour_file(file.filename, content)
    except ContourParserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during contour parsing")
        raise HTTPException(
            status_code=500, detail=f"Internal server error: {exc}",
        ) from exc

    if not contours:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid contour lines found. Ensure the KML contains "
                "Placemarks with numeric names (elevations) and LineString geometries."
            ),
        )

    contour_count = len(contours)
    total_points = sum(len(c.points) for c in contours)
    elevations = [c.elevation for c in contours]
    min_elevation = min(elevations)
    max_elevation = max(elevations)
    estimated_interval = _estimate_contour_interval(contours)
    bounding_box = _compute_bounding_box(contours)

    return ContourInspectionResponse(
        filename=file.filename,
        contour_count=contour_count,
        total_coordinate_points=total_points,
        min_elevation_m=min_elevation,
        max_elevation_m=max_elevation,
        estimated_contour_interval_m=estimated_interval,
        bounding_box=bounding_box,
        error=None,
    )


@router.post(
    "/build-terrain",
    response_model=TerrainBuildResponse,
    summary="Build interpolated terrain model from contour data",
    description=(
        "Transform parsed contour lines into a regular elevation grid using "
        "Inverse Distance Weighting (IDW) interpolation. The pipeline collects "
        "all contour points, thins them spatially for tractability, converts "
        "geographic (lat/lon) coordinates to a local metres system centred on "
        "the data extent, builds a configurable regular grid, and interpolates "
        "elevation at each grid cell via IDW with a configurable power exponent "
        "and k-nearest neighbours. The full grid is not returned in the JSON "
        "response; instead a compact summary and sampled sub-grid are provided "
        "so the response stays lightweight. The returned grid can be saved locally "
        "for downstream analysis (e.g. D8 flow routing, catchment delineation) "
        "in future phases."
    ),
)
async def build_terrain(
    file: UploadFile = File(...),
    grid_cell_size_m: float = 5.0,
    idw_power: float = 2.0,
    idw_k: int = 12,
    idw_epsilon: float = 1e-6,
    thinning_cell_size_m: float | None = None,
) -> TerrainBuildResponse:
    """
    Build an interpolated terrain model from an uploaded KML/KMZ file.

    Args:
        file: Uploaded .kml or .kmz contour file.
        grid_cell_size_m: Spacing of the regular grid in metres. Default 5 m.
        idw_power: IDW power exponent. Default 2.0 is standard for GIS.
        idw_k: Number of nearest neighbours used for IDW at each grid cell.
            Default 12. Higher values smooth the terrain more; lower values
            make it rougher but more sensitive to local contour data.
        idw_epsilon: Small guard to avoid division by zero when a grid cell
            is extremely close to a sample point. Default 1e-6.
        thinning_cell_size_m: Cell size for spatial thinning. When None,
            defaults to max(grid_cell_size_m, 5 m). If set very small, the
            full point density is kept; if very large, points are heavily thinned.

    Returns:
        TerrainBuildResponse with the terrain model metadata and a compact
        grid summary.

    Raises:
        HTTPException: 400 for invalid files, 422 if the contour data cannot
            be used to build a terrain model, 500 for unexpected errors.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    name_lower = file.filename.lower()
    if not (name_lower.endswith(".kml") or name_lower.endswith(".kmz")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Expected .kml or .kmz.",
        )

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to read uploaded file: {exc}"
        ) from exc

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        contours = parse_contour_file(file.filename, content)
    except ContourParserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during contour parsing")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during parsing: {exc}",
        ) from exc

    if not contours:
        raise HTTPException(
            status_code=400,
            detail="No valid contour lines found. Ensure the KML contains "
            "Placemarks with numeric names and LineString geometries.",
        )

    # --- Stage 2: Build the terrain model ---
    try:
        model = build_terrain_model(
            contours,
            grid_cell_size_m=grid_cell_size_m,
            idw_power=idw_power,
            idw_k=idw_k,
            idw_epsilon=idw_epsilon,
            thinning_cell_size_m=thinning_cell_size_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during terrain model construction")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during terrain modelling: {exc}",
        ) from exc

    # --- Assemble the response ---
    grid_summary = summarise_terrain_grid(model["grid"])

    all_elevations = [c.elevation for c in contours]
    contour_min = min(all_elevations)
    contour_max = max(all_elevations)

    elev_in_range = (
        contour_min - 1.0 <= model["min_elevation_m"] <= contour_max + 1.0
        and contour_min - 1.0 <= model["max_elevation_m"] <= contour_max + 1.0
    )

    proj_info = ProjectionInfo(
        projection=model["projection_info"]["projection"],
        center_lat_deg=model["projection_info"]["center_lat_deg"],
        center_lon_deg=model["projection_info"]["center_lon_deg"],
        metres_per_degree_lat=model["projection_info"]["metres_per_degree_lat"],
        metres_per_degree_lon=model["projection_info"]["metres_per_degree_lon"],
        epsg_note=model["projection_info"]["epsg_note"],
    )

    return TerrainBuildResponse(
        filename=file.filename,
        grid_width=model["grid_width"],
        grid_height=model["grid_height"],
        grid_cell_size_m=model["grid_cell_size_m"],
        requested_grid_cell_size_m=grid_cell_size_m,
        min_elevation_m=model["min_elevation_m"],
        max_elevation_m=model["max_elevation_m"],
        mean_elevation_m=model["mean_elevation_m"],
        std_elevation_m=model["std_elevation_m"],
        contour_min_elevation_m=contour_min,
        contour_max_elevation_m=contour_max,
        num_sample_points=model["num_sample_points"],
        num_contour_points=model["num_contour_points"],
        contour_count=model["contour_count"],
        projection_info=proj_info,
        bounding_box=model["bounding_box"],
        grid_summary=grid_summary,
        idw_power=idw_power,
        idw_k=idw_k,
        idw_epsilon=idw_epsilon,
        elevation_in_range=elev_in_range,
        error=None,
    )

# ---- Stage 3: hydrology analysis endpoint ----

@router.post(
    "/analyze-hydrology",
    response_model=HydrologyAnalysisResponse,
    summary="Run hydrological analysis on a contour file",
    description=(
        "Parses a KML/KMZ contour file, builds the terrain model, "
        "then runs the full Stage 3 hydrology pipeline: Priority-Flood "
        "depression filling, D8 flow direction, and flow accumulation. "
        "Returns compact statistics only."
    ),
)
async def analyze_hydrology(
    file: UploadFile = File(...),
    grid_cell_size_m: float = 5.0,
    idw_power: float = 2.0,
    idw_k: int = 12,
    idw_epsilon: float = 1e-6,
    thinning_cell_size_m: float | None = None,
    include_diagnostics: bool = True,
) -> HydrologyAnalysisResponse:
    """
    Run hydrological analysis on an uploaded KML/KMZ contour file.

    Pipeline:
      1. Parse the KML/KMZ to extract contour lines.
      2. Build the terrain model (Stage 2) using IDW interpolation.
      3. Fill depressions using Priority-Flood.
      4. Compute D8 flow directions.
      5. Compute flow accumulation via a topological pass.

    Args:
        file: Uploaded .kml or .kmz contour file.
        grid_cell_size_m: Terrain grid cell size in metres. Default 5 m.
        idw_power: IDW power exponent. Default 2.0.
        idw_k: Number of nearest neighbours for IDW. Default 12.
        idw_epsilon: IDW epsilon guard. Default 1e-6.
        thinning_cell_size_m: Spatial thinning cell size.

    Returns:
        HydrologyAnalysisResponse with statistics from all pipeline stages.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    name_lower = file.filename.lower()
    if not (name_lower.endswith(".kml") or name_lower.endswith(".kmz")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Expected .kml or .kmz.",
        )

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to read uploaded file: {exc}"
        ) from exc

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Stage 1: Parse contours.
    try:
        contours = parse_contour_file(file.filename, content)
    except ContourParserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during contour parsing")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during parsing: {exc}",
        ) from exc

    if not contours:
        raise HTTPException(
            status_code=400,
            detail="No valid contour lines found.",
        )

    # Stage 2: Build terrain model.
    try:
        model = build_terrain_model(
            contours,
            grid_cell_size_m=grid_cell_size_m,
            idw_power=idw_power,
            idw_k=idw_k,
            idw_epsilon=idw_epsilon,
            thinning_cell_size_m=thinning_cell_size_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during terrain model construction")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during terrain modelling: {exc}",
        ) from exc

    # Stage 3: Hydrological analysis.
    try:
        hydro_result = run_hydrology(
            model["grid"],
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            include_diagnostics=include_diagnostics,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during hydrology analysis")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during hydrology analysis: {exc}",
        ) from exc

    # Assemble the response.
    contour_min = float(min(c.elevation for c in contours))
    contour_max = float(max(c.elevation for c in contours))
    hydro_summary = summarise_hydrology(hydro_result)

    response = HydrologyAnalysisResponse(
        filename=file.filename,
        grid_width=model["grid_width"],
        grid_height=model["grid_height"],
        grid_cell_size_m=model["grid_cell_size_m"],
        contour_count=model["contour_count"],
        contour_min_elevation_m=contour_min,
        contour_max_elevation_m=contour_max,
        interpolated_min_elevation_m=model["min_elevation_m"],
        interpolated_max_elevation_m=model["max_elevation_m"],
        depression_fill=DepressionFillStats(
            modified_cells=hydro_summary["depression_fill"]["modified_cells"],
            max_elevation_adjustment_m=hydro_summary["depression_fill"]["max_elevation_adjustment_m"],
            total_elevation_adjustment_m=hydro_summary["depression_fill"]["total_elevation_adjustment_m"],
            mean_adjustment_m=hydro_summary["depression_fill"]["mean_adjustment_m"],
        ),
        flow_direction=FlowDirectionStats(
            valid_flow_cells=hydro_summary["flow_direction"]["valid_flow_cells"],
            sink_cells=hydro_summary["flow_direction"]["sink_cells"],
            d8_encoding=hydro_summary["flow_direction"]["d8_encoding"],
        ),
        flow_accumulation=FlowAccumulationStats(
            max_accumulated_cells=hydro_summary["flow_accumulation"]["max_accumulated_cells"],
            max_accumulated_area_m2=hydro_summary["flow_accumulation"]["max_accumulated_area_m2"],
            max_accum_row=hydro_summary["flow_accumulation"]["max_accum_row"],
            max_accum_col=hydro_summary["flow_accumulation"]["max_accum_col"],
            min_accumulated_cells=hydro_summary["flow_accumulation"]["min_accumulated_cells"],
            total_flowing_cells=hydro_summary["flow_accumulation"]["total_flowing_cells"],
        ),
        error=None,
    )

    # Optionally attach extended diagnostics.
    if include_diagnostics and hydro_result.diagnostics:
        d = hydro_result.diagnostics
        df = d["depression_fill"]
        bnd = d["boundary"]
        ec = df["elevation_change"]
        response.diagnostics = HydrologyDiagnostics(
            depression_fill=DepressionFillDiagnostics(
                total_cells=df["total_cells"],
                modified_cells=df["modified_cells"],
                modified_pct=df["modified_pct"],
                mean_adjustment_m=df["mean_adjustment_m"],
                median_adjustment_m=df["median_adjustment_m"],
                p95_adjustment_m=df["p95_adjustment_m"],
                max_adjustment_m=df["max_adjustment_m"],
                std_adjustment_m=df["std_adjustment_m"],
                cells_above_0_1m=df["cells_above_0_1m"],
                cells_above_0_5m=df["cells_above_0_5m"],
                cells_above_1_0m=df["cells_above_1_0m"],
                cells_above_2_0m=df["cells_above_2_0m"],
                cells_above_5_0m=df["cells_above_5_0m"],
                max_adjustment_row=df["max_adjustment_row"],
                max_adjustment_col=df["max_adjustment_col"],
                max_adjustment_lat=df["max_adjustment_lat"],
                max_adjustment_lon=df["max_adjustment_lon"],
                elevation_change=ElevationChangeStats(
                    original_min=ec["original_min"],
                    original_max=ec["original_max"],
                    original_mean=ec["original_mean"],
                    original_std=ec["original_std"],
                    filled_min=ec["filled_min"],
                    filled_max=ec["filled_max"],
                    filled_mean=ec["filled_mean"],
                    filled_std=ec["filled_std"],
                    mean_increase=ec["mean_increase"],
                    max_increase=ec["max_increase"],
                ),
                no_cells_lowered=df["no_cells_lowered"],
                all_changes_nonnegative=df["all_changes_nonnegative"],
            ),
            boundary=BoundaryDiagnostics(
                total_boundary_cells=bnd["total_boundary_cells"],
                boundary_outlets=bnd["boundary_outlets"],
                max_accum_is_boundary=bnd["max_accum_is_boundary"],
                max_accum_row=bnd["max_accum_row"],
                max_accum_col=bnd["max_accum_col"],
                max_accum_lat=bnd["max_accum_lat"],
                max_accum_lon=bnd["max_accum_lon"],
            ),
        )
    return response



# ----------------------------------------------------------------------
# Stage 4: pond candidate selection
# ----------------------------------------------------------------------


@router.post(
    "/find-pond-candidates",
    response_model=PondSelectionResponse,
    summary="Find and rank pond candidate locations",
    description=(
        "Parses a KML/KMZ contour file, builds the terrain model and runs "
        "the full Stage 3 hydrology pipeline, then applies a multi-factor "
        "suitability scoring algorithm to identify the top 3-5 spatially-"
        "distinct interior pond candidates. The original (un-filled) DEM "
        "is used for slope and relative-elevation factors so that pond "
        "sites reflect the natural terrain, not the Priority-Flood-"
        "conditioned surface. All factor scores are percentile-normalised "
        "against the interior cells so the method adapts to maps of any "
        "size without hard-coded thresholds."
    ),
)
async def find_pond_candidates_endpoint(
    file: UploadFile = File(...),
    grid_cell_size_m: float = 10.0,
    idw_power: float = 2.0,
    idw_k: int = 12,
    idw_epsilon: float = 1e-6,
    thinning_cell_size_m: float | None = None,
    top_k: int = 5,
    boundary_margin_m: float | None = None,
    nms_radius_cells: int = 5,
    relative_radius_cells: int = 5,
) -> PondSelectionResponse:
    """
    Find and rank pond candidate locations.

    Pipeline:
      1. Parse the KML/KMZ for contour lines.
      2. Build the interpolated DEM (Stage 2).
      3. Run Priority-Flood + D8 + flow accumulation (Stage 3).
      4. Score every interior cell on four factors derived from the
         original DEM (slope, relative elevation) and the hydrology
         grids (flow accumulation, drainage concentration).
      5. Apply non-maximum suppression to return spatially distinct
         candidates.

    Query parameters allow tuning grid resolution, candidate count, and
    the key algorithm radii.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    name_lower = file.filename.lower()
    if not (name_lower.endswith(".kml") or name_lower.endswith(".kmz")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Expected .kml or .kmz.",
        )

    # Read and parse the contour file.
    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read uploaded file: {exc}",
        ) from exc

    try:
        contours = parse_contour_file(file.filename, content)
    except ContourParserError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Contour parsing failed: {exc}",
        ) from exc

    if not contours:
        raise HTTPException(
            status_code=400,
            detail="No valid contour lines found.",
        )

    # Stage 2: build terrain model.
    try:
        model = build_terrain_model(
            contours,
            grid_cell_size_m=grid_cell_size_m,
            idw_power=idw_power,
            idw_k=idw_k,
            idw_epsilon=idw_epsilon,
            thinning_cell_size_m=thinning_cell_size_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during terrain model construction")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during terrain modelling: {exc}",
        ) from exc

    # Stage 3: hydrology (no diagnostics needed for pond selection).
    try:
        hydro_result = run_hydrology(
            model["grid"],
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            include_diagnostics=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during hydrology analysis")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during hydrology analysis: {exc}",
        ) from exc

    # Stage 4: pond candidate selection.
    # Clamp top_k to [3, 5].
    top_k_val = max(3, min(5, int(top_k)))
    config = PondSelectionConfig(
        boundary_margin_m=boundary_margin_m,
        relative_radius_cells=max(1, int(relative_radius_cells)),
        nms_radius_cells=max(1, int(nms_radius_cells)),
        top_k=top_k_val,
    )

    try:
        pond_result = find_pond_candidates(
            dem=hydro_result.dem_original,  # original DEM for slope/rel-elev
            flow_direction=hydro_result.flow_direction,
            flow_accumulation_cells=hydro_result.flow_accumulation_cells,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            config=config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during pond candidate selection")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during pond candidate selection: {exc}",
        ) from exc

    # Assemble the Pydantic response.
    pond_summary = summarise_pond_selection(pond_result)
    diag = pond_summary["diagnostics"]

    candidate_models: List[PondCandidate] = []
    for c_dict in pond_summary["candidates"]:
        fs = c_dict["factor_scores"]
        candidate_models.append(
            PondCandidate(
                rank=c_dict["rank"],
                row=c_dict["row"],
                col=c_dict["col"],
                lat=c_dict.get("lat"),
                lon=c_dict.get("lon"),
                elevation_m=c_dict["elevation_m"],
                flow_accumulation_cells=c_dict["flow_accumulation_cells"],
                upstream_area_m2=c_dict["upstream_area_m2"],
                local_slope_m_per_m=c_dict["local_slope_m_per_m"],
                local_slope_deg=c_dict["local_slope_deg"],
                relative_elevation_m=c_dict["relative_elevation_m"],
                factor_scores=FactorScores(
                    accumulation=fs["accumulation"],
                    low_slope=fs["low_slope"],
                    low_relative_elevation=fs["low_relative_elevation"],
                    drainage_concentration=fs["drainage_concentration"],
                ),
                suitability_score=c_dict["suitability_score"],
            )
        )

    proj_info = model.get("projection_info", {})
    grid_extent = {
        "lat_min": proj_info.get("grid_lat_min"),
        "lat_max": proj_info.get("grid_lat_max"),
        "lon_min": proj_info.get("grid_lon_min"),
        "lon_max": proj_info.get("grid_lon_max"),
    }
    bbox = model.get("bounding_box", {})
    contour_extent = {
        "lat_min": bbox.get("min_lat"),
        "lat_max": bbox.get("max_lat"),
        "lon_min": bbox.get("min_lon"),
        "lon_max": bbox.get("max_lon"),
    }

    return PondSelectionResponse(
        filename=file.filename,
        grid_width=model["grid_width"],
        grid_height=model["grid_height"],
        grid_cell_size_m=model["grid_cell_size_m"],
        grid_extent=grid_extent,
        contour_extent=contour_extent,
        contour_count=model["contour_count"],
        num_candidates=len(candidate_models),
        candidates=candidate_models,
        diagnostics=PondSelectionDiagnostics(
            boundary_margin_cells=diag["boundary_margin_cells"],
            boundary_margin_m=diag["boundary_margin_m"],
            cells_total=diag["cells_total"],
            cells_inside_margin=diag["cells_inside_margin"],
            cells_excluded_boundary=diag["cells_excluded_boundary"],
            cells_suppressed_by_nms=diag["cells_suppressed_by_nms"],
            cells_considered=diag["cells_considered"],
            min_kept_score=diag["min_kept_score"],
            nms_radius_cells=diag["nms_radius_cells"],
            weights=diag["weights"],
            methodology=diag["methodology"],
        ),
        error=None,
    )


# ---------------------------------------------------------------------------
# Stage 5: Catchment Delineation
# ---------------------------------------------------------------------------


async def _build_full_pipeline(
    file: UploadFile,
    grid_cell_size_m: float,
    idw_power: float,
    idw_k: int,
    idw_epsilon: float,
    thinning_cell_size_m: float | None,
):
    """
    Build terrain + run hydrology from an uploaded KML/KMZ file.

    Returns the contours, terrain model dict, and hydrology result.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")
    name_lower = file.filename.lower()
    if not (name_lower.endswith(".kml") or name_lower.endswith(".kmz")):
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Expected .kml or .kmz.",
        )

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to read uploaded file: {exc}"
        ) from exc

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        contours = parse_contour_file(file.filename, content)
    except ContourParserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected error during contour parsing")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error during parsing: {exc}",
        ) from exc

    if not contours:
        raise HTTPException(
            status_code=400,
            detail="No valid contour lines found.",
        )

    # Build terrain
    model = build_terrain_model(
        contours,
        grid_cell_size_m=grid_cell_size_m,
        idw_power=idw_power,
        idw_k=idw_k,
        idw_epsilon=idw_epsilon,
        thinning_cell_size_m=thinning_cell_size_m,
    )

    # Hydrology
    hydro = run_hydrology(
        model["grid"],
        cell_size_m=model["grid_cell_size_m"],
        projection_info=model.get("projection_info"),
        include_diagnostics=False,
    )

    return contours, model, hydro


@router.post(
    "/delineate-catchment",
    response_model=CatchmentDelineationResponse,
    summary="Delineate upstream catchment for a selected pond candidate",
    description=(
        "Upload a KML/KMZ file and provide pond_row / pond_col to delineate "
        "the upstream catchment using reverse D8 traversal."
    ),
)
async def delineate_catchment_endpoint(
    file: UploadFile = File(...),
    pond_row: int = 0,
    pond_col: int = 0,
    grid_cell_size_m: float = 10.0,
    idw_power: float = 2.0,
    idw_k: int = 12,
    idw_epsilon: float = 1e-6,
    thinning_cell_size_m: float | None = None,
):
    """Delineate catchment for a manually selected pond outlet (row, col)."""
    from services.catchment import (
        delineate_catchment,
        summarise_catchment,
        CatchmentConfig,
    )

    try:
        contours, model, hydro = await _build_full_pipeline(
            file, grid_cell_size_m, idw_power, idw_k, idw_epsilon,
            thinning_cell_size_m,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Pipeline build error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        result = delineate_catchment(
            outlet_row=pond_row,
            outlet_col=pond_col,
            flow_direction=hydro.flow_direction,
            flow_accumulation=hydro.flow_accumulation_cells,
            dem=hydro.dem_original,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            config=CatchmentConfig(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Catchment delineation error")
        raise HTTPException(
            status_code=500,
            detail=f"Catchment delineation failed: {exc}",
        ) from exc

    summary = summarise_catchment(result)

    return CatchmentDelineationResponse(
        filename=file.filename,
        grid_width=model["grid_width"],
        grid_height=model["grid_height"],
        grid_cell_size_m=model["grid_cell_size_m"],
        grid_area_m2=result.grid_area_m2,
        outlet=summary["outlet"],
        catchment_cells=result.catchment_cells,
        catchment_area_m2=result.catchment_area_m2,
        catchment_area_ha=result.catchment_area_ha,
        catchment_area_km2=result.catchment_area_km2,
        catchment_pct_of_grid=result.catchment_pct_of_grid,
        flow_accum_at_outlet=result.flow_accum_at_outlet,
        outlet_upstream_area_m2=result.outlet_upstream_area_m2,
        boundary=CatchmentBoundaryInfo(**summary["boundary"]),
        diagnostics=CatchmentDiagnosticsInfo(**summary["diagnostics"]),
        error=None,
    )


@router.post(
    "/analyze-contour",
    response_model=IntegratedAnalysisResponse,
    summary="Integrated analysis: parse, terrain, hydrology, pond, catchment",
    description=(
        "End-to-end pipeline: parse contours, build terrain, run hydrology, "
        "select pond candidates, pick the top-ranked one (or another by "
        "rank), and delineate its catchment."
    ),
)
async def analyze_contour(
    file: UploadFile = File(...),
    pond_rank: int = 1,
    grid_cell_size_m: float = 10.0,
    idw_power: float = 2.0,
    idw_k: int = 12,
    idw_epsilon: float = 1e-6,
    thinning_cell_size_m: float | None = None,
):
    """Integrated analysis: parse -> terrain -> hydrology -> pond -> catchment."""
    from services.catchment import run_integrated_analysis, CatchmentConfig

    t0 = time.perf_counter()
    try:
        contours, model, hydro = await _build_full_pipeline(
            file, grid_cell_size_m, idw_power, idw_k, idw_epsilon,
            thinning_cell_size_m,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Pipeline build error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Get water exclusion mask from OpenStreetMap/Overpass
    proj_info = model.get("projection_info")
    bbox = model.get("bounding_box", {})
    h, w = hydro.dem_original.shape
    cell_size = model["grid_cell_size_m"]
    water_result = None
    water_mask = None

    if proj_info and bbox.get("min_lat") is not None:
        try:
            # Grid origin: top-left corner of the grid in geographic coords
            # Row 0 = max_lat, Col 0 = min_lon
            center_lat = proj_info.get("center_lat_deg", (bbox["min_lat"] + bbox["max_lat"]) / 2.0)
            center_lon = proj_info.get("center_lon_deg", (bbox["min_lon"] + bbox["max_lon"]) / 2.0)
            m_per_deg_lon = proj_info.get("metres_per_degree_lon", 111320.0 * 0.85)

            # DEM origin (top-left = row 0, col 0)
            grid_width_m = w * cell_size
            grid_height_m = h * cell_size
            origin_lat = center_lat + (grid_height_m / 2.0) / 111320.0
            origin_lon = center_lon - (grid_width_m / 2.0) / m_per_deg_lon

            water_result = get_water_exclusion_mask(
                bbox=(bbox["min_lat"], bbox["min_lon"],
                      bbox["max_lat"], bbox["max_lon"]),
                dem_rows=h,
                dem_cols=w,
                dem_cell_size_m=cell_size,
                dem_origin_lat=origin_lat,
                dem_origin_lon=origin_lon,
                config=WaterExclusionConfig(),
            )
            water_mask = water_result.mask
            logger.info(
                f"Water exclusion: applied={water_result.applied}, "
                f"features={water_result.features_found}, "
                f"excluded_cells={int(water_mask.sum())}"
            )
        except Exception as exc:
            logger.warning(f"Water exclusion failed, continuing without: {exc}")
            water_mask = None

    try:
        pond_result = find_pond_candidates(
            dem=hydro.dem_original,
            flow_direction=hydro.flow_direction,
            flow_accumulation_cells=hydro.flow_accumulation_cells,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            config=PondSelectionConfig(),
            water_mask=water_mask,
            water_result=water_result,
        )
    except Exception as exc:
        logger.exception("Pond selection error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not pond_result.candidates:
        raise HTTPException(
            status_code=404,
            detail="No pond candidates were found for this terrain.",
        )

    # Build a compact water-exclusion summary for the response.  The
    # raw OSM geometry is intentionally NOT included to keep the payload
    # small (Phase 3 requirement #5).
    if water_result is not None:
        water_exclusion_info = {
            "applied": bool(water_result.applied),
            "fallback_used": bool(water_result.fallback_used),
            "features_found": int(water_result.features_found),
            "feature_types": list(water_result.feature_types or []),
            "cells_excluded": (
                int(water_result.mask.sum())
                if water_result.mask is not None else 0
            ),
            "buffer_metres": float(water_result.buffer_metres),
            "error_message": water_result.error_message,
        }
    else:
        water_exclusion_info = {
            "applied": False,
            "fallback_used": True,
            "features_found": 0,
            "feature_types": [],
            "cells_excluded": 0,
            "buffer_metres": 0.0,
            "error_message": "Water exclusion was not run.",
        }

    try:
        catchment, integrated = run_integrated_analysis(
            pond_result=pond_result,
            hydro_result=hydro,
            model=model,
            rank=pond_rank,
            config=CatchmentConfig(),
            water_exclusion_info=water_exclusion_info,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Integrated analysis error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Build the ranked candidate list for the response.  Each entry uses
    # the actual factor scores produced by the pond selection algorithm;
    # no factor values are invented.
    pond_candidates: List[PondCandidateInfo] = []
    for c in integrated["pond_candidates"]:
        pond_candidates.append(
            PondCandidateInfo(
                rank=c["rank"],
                row=c["row"],
                col=c["col"],
                lat=c["lat"],
                lon=c["lon"],
                elevation_m=c["elevation_m"],
                suitability_score=c["suitability_score"],
                flow_accumulation_cells=c["flow_accumulation_cells"],
                local_slope_deg=c["local_slope_deg"],
                relative_elevation_m=c["relative_elevation_m"],
                factor_scores=FactorScores(
                    accumulation=c["factor_scores"]["accumulation"],
                    low_slope=c["factor_scores"]["low_slope"],
                    low_relative_elevation=c["factor_scores"]["low_relative_elevation"],
                    drainage_concentration=c["factor_scores"]["drainage_concentration"],
                ),
            )
        )

    # --- Phase 4: Pond depth and storage volume estimation ---
    # Only the selected candidate (determined by pond_rank) is analysed
    # to keep computation tractable.  The pond_candidates list remains
    # lightweight (no depth/volume per candidate).
    capacity_summary: dict = {}
    try:
        capacity_result = estimate_pond_capacity(
            dem=hydro.dem_original,
            row=integrated["selected_pond"]["row"],
            col=integrated["selected_pond"]["col"],
            cell_size_m=model["grid_cell_size_m"],
        )
        capacity_summary = summarise_pond_capacity(capacity_result)
    except Exception as exc:
        logger.warning(
            f"Pond capacity estimation failed for rank-{pond_rank} "
            f"candidate: {exc}. Proceeding without capacity data."
        )
        capacity_summary = {}

    pond_capacity_model = (
        PondCapacityInfo(**capacity_summary) if capacity_summary else None
    )

    # ---- Phase 8: Rainfall and Weather lookup for KML/KMZ analyses ----
    rw_lat, rw_lon, rw_basis, rw_note = _get_rainfall_lookup_coords_for_kml(
        catchment=catchment,
        integrated=integrated,
    )
    rainfall_info, weather_info, rainfall_lookup_meta = (
        _safe_rainfall_weather_lookup(rw_lat, rw_lon, rw_basis, rw_note)
    )

    # ---- Phase 9: Design rainfall lookup for KML/KMZ analyses ----
    # Uses the same representative rainfall coordinates as the Phase 8
    # rainfall/weather lookup so that all three lookups are consistent.
    design_rainfall_info = _safe_design_rainfall_lookup(rw_lat, rw_lon)

    # ---- Phase 11B-2: Soil / HSG lookup ----
    # Requires the catchment bounding box.
    soil_group_summary: Optional[dict] = None
    try:
        bbox = catchment.boundary.bounding_box
        if bbox and any(v is not None for v in bbox.values()):
            soil_result = get_soil_group(
                bbox=(
                    bbox.get("min_lat", 0.0) or 0.0,
                    bbox.get("min_lon", 0.0) or 0.0,
                    bbox.get("max_lat", 0.0) or 0.0,
                    bbox.get("max_lon", 0.0) or 0.0,
                )
            )
            soil_group_summary = summarise_soil_group(soil_result)
    except Exception as exc:
        logger.warning("Phase 11B soil/HSG failed: %s", exc)
        soil_group_summary = None

    # ---- Phase 11B-3: SCS-CN runoff ----
    runoff_summary: Optional[dict] = None
    try:
        scs_result = compute_scs_cn_runoff(
            land_cover_summary=integrated.get("land_cover"),
            soil_group_summary=soil_group_summary,
            rainfall_P_mm=(
                design_rainfall_info.design_rainfall_mm
                if design_rainfall_info else None
            ),
            catchment_area_m2=catchment.catchment_area_m2,
            amc_condition="II",
        )
        runoff_summary = summarise_scs_cn(scs_result)
    except Exception as exc:
        logger.warning("Phase 11B SCS-CN runoff failed: %s", exc)
        runoff_summary = None

    # ---- Phase 11B-5: Pond adequacy ----
    pond_adequacy_summary: Optional[dict] = None
    try:
        available_storage = None
        if capacity_summary:
            available_storage = capacity_summary.get("storage_volume_m3")
        runoff_vol = (
            runoff_summary.get("runoff_volume_m3")
            if runoff_summary else None
        )
        adequacy_result = compute_pond_adequacy(
            runoff_volume_m3=runoff_vol,
            available_storage_m3=available_storage,
        )
        pond_adequacy_summary = summarise_pond_adequacy(adequacy_result)
    except Exception as exc:
        logger.warning("Phase 11B pond adequacy failed: %s", exc)
        pond_adequacy_summary = None

    return IntegratedAnalysisResponse(
        filename=file.filename,
        grid_width=model["grid_width"],
        grid_height=model["grid_height"],
        grid_cell_size_m=model["grid_cell_size_m"],
        contour_count=model["contour_count"],
        num_candidates=integrated["num_candidates"],
        pond_candidates=pond_candidates,
        selected_pond=integrated["selected_pond"],
        catchment_cells=catchment.catchment_cells,
        catchment_area_m2=catchment.catchment_area_m2,
        catchment_area_ha=catchment.catchment_area_ha,
        catchment_area_km2=catchment.catchment_area_km2,
        catchment_pct_of_grid=catchment.catchment_pct_of_grid,
        flow_accum_at_outlet=catchment.flow_accum_at_outlet,
        flow_accum_consistent=catchment.flow_accum_at_outlet == catchment.catchment_cells,
        boundary=CatchmentBoundaryInfo(
            boundary_type=catchment.boundary.boundary_type,
            boundary_coordinates=catchment.boundary.boundary_coordinates,
            num_boundary_cells=catchment.boundary.num_boundary_cells,
            num_boundary_points=catchment.boundary.num_boundary_points,
            bounding_box=catchment.boundary.bounding_box,
        ),
        diagnostics=CatchmentDiagnosticsInfo(
            outlet_in_catchment=catchment.diagnostics.outlet_in_catchment,
            no_duplicate_cells=catchment.diagnostics.no_duplicate_cells,
            traversal_terminated_safely=catchment.diagnostics.traversal_terminated_safely,
            cells_visited=catchment.diagnostics.cells_visited_count,
            max_queue_size=catchment.diagnostics.max_queue_size,
            flow_accum_consistent=catchment.diagnostics.outlet_flow_accum_consistent,
            area_consistent=catchment.diagnostics.catchment_area_consistent,
            area_within_grid=catchment.diagnostics.area_within_grid,
            time_elapsed_s=catchment.diagnostics.time_elapsed_s,
        ),
        water_exclusion=WaterExclusionInfo(**integrated["water_exclusion"]),
        pond_capacity=pond_capacity_model,
        error=None,
        time_elapsed_s=time.perf_counter() - t0,
        rainfall=rainfall_info,
        weather=weather_info,
        rainfall_lookup=rainfall_lookup_meta,
        design_rainfall=design_rainfall_info,
        catchment_terrain=(
            CatchmentTerrainDiagnostics(**integrated["catchment_terrain"])
            if integrated.get("catchment_terrain") else None
        ),
        land_cover=(
            LandCoverInfo(**integrated["land_cover"])
            if integrated.get("land_cover") else None
        ),
        soil_group=(
            SoilGroupInfo(**soil_group_summary)
            if soil_group_summary else None
        ),
        runoff=(
            RunoffInfo(**runoff_summary)
            if runoff_summary else None
        ),
        time_of_concentration=(
            TimeOfConcentrationInfo(**integrated["time_of_concentration"])
            if integrated.get("time_of_concentration") else None
        ),
        pond_adequacy=(
            PondAdequacyInfo(**pond_adequacy_summary)
            if pond_adequacy_summary else None
        ),
    )


@router.post(
    "/analyze-location",
    response_model=IntegratedAnalysisResponse,
    summary="Location-based integrated analysis (Phase 5)",
    description=(
        "Given a geographic center point and radius, download a DEM from "
        "OpenTopography, generate contours, and run the full pipeline: "
        "terrain model, hydrology, water exclusion, pond candidate selection, "
        "catchment delineation, and pond capacity estimation."
    ),
)
async def analyze_location(
    request: LocationAnalysisRequest,
    pond_rank: int = 1,
    grid_cell_size_m: float = 10.0,
    idw_power: float = 2.0,
    idw_k: int = 12,
    idw_epsilon: float = 1e-6,
):
    """
    Location-based integrated analysis pipeline (Phase 5).

    Workflow:
    1. Convert (latitude, longitude, radius_km) to DEM bounding box.
    2. Download DEM from OpenTopography.
    3. Generate contours using GDAL.
    4. Build terrain model from contours.
    5. Run hydrology analysis.
    6. Run water exclusion (OpenStreetMap/Overpass).
    7. Select pond candidates.
    8. Delineate catchment for the selected candidate.
    9. Estimate pond depth/storage.
    10. Return IntegratedAnalysisResponse.
    """
    from services.catchment import run_integrated_analysis, CatchmentConfig
    from services.dem_acquisition import (
        download_dem,
        cleanup_dem,
        radius_to_bounds,
        DEMAcquisitionError,
        DEMValidationError,
        DEMAPIError,
    )
    from services.contour_generation import (
        generate_contours,
        cleanup_contour_result,
        ContourGenerationError,
        ContourValidationError,
        GDALNotFoundError,
    )

    t0 = time.perf_counter()

    # Convert radius to bounding box
    try:
        south, north, west, east = radius_to_bounds(
            latitude=request.latitude,
            longitude=request.longitude,
            radius_km=request.radius_km,
        )
    except DEMValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Generate a meaningful source filename
    source_filename = "location_{lat}_{lon}_{dem}".format(
        lat="{:.4f}".format(request.latitude),
        lon="{:.4f}".format(request.longitude),
        dem=request.dem_type.lower(),
    )

    # Step 1: Download DEM
    dem_result = None
    contour_result = None
    model = None
    hydro = None

    try:
        try:
            dem_result = download_dem(
                south=south,
                north=north,
                west=west,
                east=east,
                dem_type=request.dem_type,
            )
        except DEMValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DEMAPIError as exc:
            raise HTTPException(
                status_code=502,
                detail="OpenTopography API error: " + str(exc),
            ) from exc
        except DEMAcquisitionError as exc:
            raise HTTPException(
                status_code=502,
                detail="DEM download failed: " + str(exc),
            ) from exc

        # Step 2: Generate contours
        try:
            contour_result = generate_contours(
                dem_path=dem_result.file_path,
                interval_m=request.contour_interval_m,
            )
        except ContourValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GDALNotFoundError as exc:
            raise HTTPException(
                status_code=500,
                detail="GDAL contour tool not installed: " + str(exc),
            ) from exc
        except ContourGenerationError as exc:
            raise HTTPException(
                status_code=500,
                detail="Contour generation failed: " + str(exc),
            ) from exc

        contours = contour_result.contours

        if not contours:
            raise HTTPException(
                status_code=422,
                detail="No contours generated. The DEM may be flat or the interval too small.",
            )

        # Step 3: Build terrain model
        try:
            model = build_terrain_model(
                contours=contours,
                grid_cell_size_m=grid_cell_size_m,
                idw_power=idw_power,
                idw_k=idw_k,
                idw_epsilon=idw_epsilon,
            )
        except Exception as exc:
            logger.exception("Terrain model build error")
            raise HTTPException(
                status_code=500,
                detail="Terrain model build failed: " + str(exc),
            ) from exc

        # Step 4: Run hydrology
        try:
            hydro = run_hydrology(
                dem=model["grid"],
                cell_size_m=model["grid_cell_size_m"],
                projection_info=model.get("projection_info"),
            )
        except Exception as exc:
            logger.exception("Hydrology error")
            raise HTTPException(
                status_code=500,
                detail="Hydrology analysis failed: " + str(exc),
            ) from exc

    finally:
        # Clean up temporary DEM and contour files
        if contour_result is not None:
            cleanup_contour_result(contour_result)
        if dem_result is not None:
            cleanup_dem(dem_result)

    # Step 5: Water exclusion
    proj_info = model.get("projection_info")
    bbox = model.get("bounding_box", {})
    h, w = hydro.dem_original.shape
    cell_size = model["grid_cell_size_m"]
    water_result = None
    water_mask = None

    if proj_info and bbox.get("min_lat") is not None:
        try:
            water_result = get_water_exclusion_mask(
                bbox=(bbox["min_lat"], bbox["min_lon"],
                      bbox["max_lat"], bbox["max_lon"]),
                dem_rows=h,
                dem_cols=w,
                dem_cell_size_m=cell_size,
                dem_origin_lat=proj_info.get("grid_lat_min"),
                dem_origin_lon=proj_info.get("grid_lon_min"),
            )
            water_mask = water_result.mask
        except Exception as exc:
            logger.warning("Water exclusion failed: %s", exc)
            water_result = None
            water_mask = None

    # Step 6: Pond selection
    try:
        pond_result = find_pond_candidates(
            dem=hydro.dem_original,
            flow_direction=hydro.flow_direction,
            flow_accumulation_cells=hydro.flow_accumulation_cells,
            cell_size_m=model["grid_cell_size_m"],
            projection_info=model.get("projection_info"),
            config=PondSelectionConfig(),
            water_mask=water_mask,
            water_result=water_result,
        )
    except Exception as exc:
        logger.exception("Pond selection error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not pond_result.candidates:
        raise HTTPException(
            status_code=404,
            detail="No pond candidates were found for this terrain.",
        )

    # Build water exclusion info for response
    if water_result is not None:
        water_exclusion_info = {
            "applied": bool(water_result.applied),
            "fallback_used": bool(water_result.fallback_used),
            "features_found": int(water_result.features_found),
            "feature_types": list(water_result.feature_types or []),
            "cells_excluded": (
                int(water_result.mask.sum())
                if water_result.mask is not None else 0
            ),
            "buffer_metres": float(water_result.buffer_metres),
            "error_message": water_result.error_message,
        }
    else:
        water_exclusion_info = {
            "applied": False,
            "fallback_used": True,
            "features_found": 0,
            "feature_types": [],
            "cells_excluded": 0,
            "buffer_metres": 0.0,
            "error_message": "Water exclusion was not run.",
        }

    # Step 7: Integrated analysis (catchment + pond capacity)
    try:
        catchment, integrated = run_integrated_analysis(
            pond_result=pond_result,
            hydro_result=hydro,
            model=model,
            rank=pond_rank,
            config=CatchmentConfig(),
            water_exclusion_info=water_exclusion_info,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Integrated analysis error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Build ranked candidate list for response
    pond_candidates: List[PondCandidateInfo] = []
    for c in integrated["pond_candidates"]:
        pond_candidates.append(
            PondCandidateInfo(
                rank=c["rank"],
                row=c["row"],
                col=c["col"],
                lat=c["lat"],
                lon=c["lon"],
                elevation_m=c["elevation_m"],
                suitability_score=c["suitability_score"],
                flow_accumulation_cells=c["flow_accumulation_cells"],
                local_slope_deg=c["local_slope_deg"],
                relative_elevation_m=c["relative_elevation_m"],
                factor_scores=FactorScores(
                    accumulation=c["factor_scores"]["accumulation"],
                    low_slope=c["factor_scores"]["low_slope"],
                    low_relative_elevation=c["factor_scores"]["low_relative_elevation"],
                    drainage_concentration=c["factor_scores"]["drainage_concentration"],
                ),
            )
        )

    # Step 8: Pond capacity estimation
    capacity_summary: dict = {}
    try:
        capacity_result = estimate_pond_capacity(
            dem=hydro.dem_original,
            row=integrated["selected_pond"]["row"],
            col=integrated["selected_pond"]["col"],
            cell_size_m=model["grid_cell_size_m"],
        )
        capacity_summary = summarise_pond_capacity(capacity_result)
    except Exception as exc:
        logger.warning(
            "Pond capacity estimation failed for rank-%d candidate: %s. Proceeding without capacity data.",
            pond_rank, exc,
        )
        capacity_summary = {}

    pond_capacity_model = (
        PondCapacityInfo(**capacity_summary) if capacity_summary else None
    )

    # Build source info
    source_info = LocationSourceInfo(
        source="location",
        latitude=request.latitude,
        longitude=request.longitude,
        radius_km=request.radius_km,
        dem_type=request.dem_type,
        contour_interval_m=request.contour_interval_m,
        south=south,
        north=north,
        west=west,
        east=east,
    )

    # ---- Phase 8: Rainfall and Weather lookup for location-based analyses ----
    # ---- Phase 8/9: Rainfall, weather, and design rainfall lookup for location-based analyses ----
    # Use catchment-aware coordinate selection when available, falling back to
    # the user-selected location (consistent with the KML workflow).
    rw_lat, rw_lon, rw_basis, rw_note = _get_rainfall_lookup_coords_for_kml(
        catchment=catchment,
        integrated=integrated,
    )
    # Fall back to user location if catchment-aware coords are unavailable
    if rw_lat is None or rw_lon is None:
        rw_lat = request.latitude
        rw_lon = request.longitude
        rw_basis = "user_location"
        rw_note = (
            "Rainfall and design rainfall estimated at the user-specified "
            "location coordinates (catchment centroid not available). "
            "This is a point estimate."
        )
    rainfall_info, weather_info, rainfall_lookup_meta = (
        _safe_rainfall_weather_lookup(rw_lat, rw_lon, rw_basis, rw_note)
    )
    # ---- Phase 9: Design rainfall lookup for location-based analyses ----
    # Uses the same representative rainfall coordinates as the Phase 8
    # rainfall/weather lookup so that all three lookups are consistent.
    design_rainfall_info = _safe_design_rainfall_lookup(rw_lat, rw_lon)

    # ---- Phase 11B-2: Soil / HSG lookup ----
    soil_group_summary_l: Optional[dict] = None
    try:
        bbox = catchment.boundary.bounding_box
        if bbox and any(v is not None for v in bbox.values()):
            soil_result = get_soil_group(
                bbox=(
                    bbox.get("min_lat", 0.0) or 0.0,
                    bbox.get("min_lon", 0.0) or 0.0,
                    bbox.get("max_lat", 0.0) or 0.0,
                    bbox.get("max_lon", 0.0) or 0.0,
                )
            )
            soil_group_summary_l = summarise_soil_group(soil_result)
    except Exception as exc:
        logger.warning("Phase 11B soil/HSG failed: %s", exc)
        soil_group_summary_l = None

    # ---- Phase 11B-3: SCS-CN runoff ----
    runoff_summary_l: Optional[dict] = None
    try:
        scs_result = compute_scs_cn_runoff(
            land_cover_summary=integrated.get("land_cover"),
            soil_group_summary=soil_group_summary_l,
            rainfall_P_mm=(
                design_rainfall_info.design_rainfall_mm
                if design_rainfall_info else None
            ),
            catchment_area_m2=catchment.catchment_area_m2,
            amc_condition="II",
        )
        runoff_summary_l = summarise_scs_cn(scs_result)
    except Exception as exc:
        logger.warning("Phase 11B SCS-CN runoff failed: %s", exc)
        runoff_summary_l = None

    # ---- Phase 11B-5: Pond adequacy ----
    pond_adequacy_summary_l: Optional[dict] = None
    try:
        available_storage = None
        if capacity_summary:
            available_storage = capacity_summary.get("storage_volume_m3")
        runoff_vol = (
            runoff_summary_l.get("runoff_volume_m3")
            if runoff_summary_l else None
        )
        adequacy_result = compute_pond_adequacy(
            runoff_volume_m3=runoff_vol,
            available_storage_m3=available_storage,
        )
        pond_adequacy_summary_l = summarise_pond_adequacy(adequacy_result)
    except Exception as exc:
        logger.warning("Phase 11B pond adequacy failed: %s", exc)
        pond_adequacy_summary_l = None

    return IntegratedAnalysisResponse(
        filename=source_filename,
        source_info=source_info,
        grid_width=model["grid_width"],
        grid_height=model["grid_height"],
        grid_cell_size_m=model["grid_cell_size_m"],
        contour_count=model["contour_count"],
        num_candidates=integrated["num_candidates"],
        pond_candidates=pond_candidates,
        selected_pond=integrated["selected_pond"],
        catchment_cells=catchment.catchment_cells,
        catchment_area_m2=catchment.catchment_area_m2,
        catchment_area_ha=catchment.catchment_area_ha,
        catchment_area_km2=catchment.catchment_area_km2,
        catchment_pct_of_grid=catchment.catchment_pct_of_grid,
        flow_accum_at_outlet=catchment.flow_accum_at_outlet,
        flow_accum_consistent=catchment.flow_accum_at_outlet == catchment.catchment_cells,
        boundary=CatchmentBoundaryInfo(
            boundary_type=catchment.boundary.boundary_type,
            boundary_coordinates=catchment.boundary.boundary_coordinates,
            num_boundary_cells=catchment.boundary.num_boundary_cells,
            num_boundary_points=catchment.boundary.num_boundary_points,
            bounding_box=catchment.boundary.bounding_box,
        ),
        diagnostics=CatchmentDiagnosticsInfo(
            outlet_in_catchment=catchment.diagnostics.outlet_in_catchment,
            no_duplicate_cells=catchment.diagnostics.no_duplicate_cells,
            traversal_terminated_safely=catchment.diagnostics.traversal_terminated_safely,
            cells_visited=catchment.diagnostics.cells_visited_count,
            max_queue_size=catchment.diagnostics.max_queue_size,
            flow_accum_consistent=catchment.diagnostics.outlet_flow_accum_consistent,
            area_consistent=catchment.diagnostics.catchment_area_consistent,
            area_within_grid=catchment.diagnostics.area_within_grid,
            time_elapsed_s=catchment.diagnostics.time_elapsed_s,
        ),
        water_exclusion=WaterExclusionInfo(**integrated["water_exclusion"]),
        pond_capacity=pond_capacity_model,
        error=None,
        time_elapsed_s=time.perf_counter() - t0,
        rainfall=rainfall_info,
        weather=weather_info,
        rainfall_lookup=rainfall_lookup_meta,
        design_rainfall=design_rainfall_info,
        catchment_terrain=(
            CatchmentTerrainDiagnostics(**integrated["catchment_terrain"])
            if integrated.get("catchment_terrain") else None
        ),
        land_cover=(
            LandCoverInfo(**integrated["land_cover"])
            if integrated.get("land_cover") else None
        ),
        soil_group=(
            SoilGroupInfo(**soil_group_summary_l)
            if soil_group_summary_l else None
        ),
        runoff=(
            RunoffInfo(**runoff_summary_l)
            if runoff_summary_l else None
        ),
        time_of_concentration=(
            TimeOfConcentrationInfo(**integrated["time_of_concentration"])
            if integrated.get("time_of_concentration") else None
        ),
        pond_adequacy=(
            PondAdequacyInfo(**pond_adequacy_summary_l)
            if pond_adequacy_summary_l else None
        ),
    )
# ---------------------------------------------------------------------------
# Phase 8: Rainfall and Weather endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/rainfall",
    response_model=RainfallInfo,
    summary="Get historical rainfall data for a location (Phase 8)",
    description=(
        "Retrieves historical/climatological rainfall data from an external "
        "provider (Open-Meteo/ERA5 reanalysis) for the specified coordinates. "
        "Returns normalized rainfall information including annual totals, monthly "
        "averages, and statistics. "
        "\n\n"
        "**Important**: This provides POINT-based historical rainfall estimates. "
        "It is NOT design rainfall. Phase 9 (runoff) will use this data to "
        "compute design rainfall values for the catchment."
    ),
)
async def get_rainfall_endpoint(
    latitude: float,
    longitude: float,
    start_date: str | None = None,
    end_date: str | None = None,
) -> RainfallInfo:
    """Retrieve rainfall data for a geographic location."""
    try:
        result = get_rainfall(
            latitude=latitude,
            longitude=longitude,
            start_date=start_date,
            end_date=end_date,
        )
    except RainfallValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid coordinates: {exc}",
        ) from exc

    return RainfallInfo(
        source=result.source,
        latitude=result.latitude,
        longitude=result.longitude,
        data_period_start=result.data_period_start,
        data_period_end=result.data_period_end,
        annual_rainfall_mm=result.annual_rainfall_mm,
        monthly_rainfall_mm=result.monthly_rainfall_mm,
        rainfall_data_available=result.rainfall_data_available,
        data_resolution=result.data_resolution,
        data_quality=result.data_quality,
        fetched_at=result.fetched_at,
        error_message=result.error_message,
        rainy_days=result.rainy_days,
        max_daily_rainfall_mm=result.max_daily_rainfall_mm,
        number_of_observations=result.number_of_observations,
        lookup_method=result.lookup_method,
    )


@router.get(
    "/weather",
    response_model=WeatherInfo,
    summary="Get current weather for a location (Phase 8)",
    description=(
        "Retrieves current weather conditions from an external provider "
        "(Open-Meteo) for the specified coordinates. "
        "\n\n"
        "**Note**: This is supplementary contextual information. Do NOT use "
        "current weather for design rainfall or runoff calculations. "
        "Use the /api/rainfall endpoint for historical rainfall data."
    ),
)
async def get_weather_endpoint(
    latitude: float,
    longitude: float,
) -> WeatherInfo:
    """Retrieve current weather data for a geographic location."""
    try:
        result = get_weather(latitude=latitude, longitude=longitude)
    except WeatherValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid coordinates: {exc}",
        ) from exc

    return WeatherInfo(
        source=result.source,
        latitude=result.latitude,
        longitude=result.longitude,
        observation_timestamp=result.observation_timestamp,
        temperature_c=result.temperature_c,
        precipitation_mm=result.precipitation_mm,
        humidity_pct=result.humidity_pct,
        wind_speed_kmh=result.wind_speed_kmh,
        wind_direction_deg=result.wind_direction_deg,
        weather_description=result.weather_description,
        weather_data_available=result.weather_data_available,
        fetched_at=result.fetched_at,
        error_message=result.error_message,
    )
