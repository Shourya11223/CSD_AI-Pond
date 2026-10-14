// ============================================================
// API types — mirrors IntegratedAnalysisResponse from the backend
// (Phase 3 water exclusion + Phase 4.1 pond capacity included)
// Phase 6: location analysis source info
// Phase 8: rainfall & weather
// Phase 9: design rainfall
// Phase 11A: catchment terrain diagnostics
// Phase 11B: land cover, soil, SCS-CN runoff, Tc, pond adequacy
// ============================================================

// ---- Phase 8: Rainfall data ----

export interface RainfallInfo {
  source: string;
  latitude: number;
  longitude: number;
  data_period_start: string | null;
  data_period_end: string | null;
  annual_rainfall_mm: number | null;
  monthly_rainfall_mm: Record<string, number> | null;
  rainfall_data_available: boolean;
  data_resolution: string | null;
  data_quality: string;
  fetched_at: string;
  error_message: string | null;
  rainy_days: number | null;
  max_daily_rainfall_mm: number | null;
  number_of_observations: number | null;
  lookup_method: string;
}

// ---- Phase 8: Weather data ----

export interface WeatherInfo {
  source: string;
  latitude: number;
  longitude: number;
  observation_timestamp: string | null;
  temperature_c: number | null;
  precipitation_mm: number | null;
  humidity_pct: number | null;
  wind_speed_kmh: number | null;
  wind_direction_deg: number | null;
  weather_description: string | null;
  weather_data_available: boolean;
  fetched_at: string;
  error_message: string | null;
}

// ---- Phase 8: Rainfall lookup metadata ----

export interface RainfallLookupMetadata {
  lookup_location: { latitude: number; longitude: number };
  lookup_basis: string;
  note: string | null;
}

// ---- Phase 9: Design rainfall data ----

export interface DesignRainfallInfo {
  source: string;
  latitude: number;
  longitude: number;
  data_period_start: string | null;
  data_period_end: string | null;
  number_of_years: number | null;
  number_of_observations: number | null;
  annual_maxima_count: number | null;
  annual_maximum_min_mm: number | null;
  annual_maximum_mean_mm: number | null;
  annual_maximum_max_mm: number | null;
  return_period_years: number;
  design_rainfall_mm: number | null;
  distribution: string;
  fitting_method: string;
  data_quality: string;
  warnings: string[];
  fetched_at: string;
  design_rainfall_available: boolean;
  error_message: string | null;
}

// ---- Phase 11A: Catchment terrain diagnostics ----

export interface CatchmentTerrainDiagnostics {
  mean_slope_deg: number;
  mean_slope_m_per_m: number;
  max_slope_deg: number;
  max_slope_m_per_m: number;
  min_slope_deg: number;
  min_slope_m_per_m: number;
  min_elevation_m: number;
  max_elevation_m: number;
  relief_m: number;
  mean_elevation_m: number;
  longest_flow_path_m: number;
  longest_flow_path_cells: number;
  longest_flow_path_outlet_row: number;
  longest_flow_path_outlet_col: number;
  number_of_headwater_cells: number;
  method: string;
  warnings: string[];
}

// ---- Phase 11B-1: Land cover ----

export interface LandCoverClassFraction {
  land_cover_class: string;
  area_m2: number;
  fraction: number;
  feature_count: number;
}

export interface LandCoverInfo {
  data_available: boolean;
  source: string;
  bbox: { min_lat: number; min_lon: number; max_lat: number; max_lon: number } | null;
  bbox_area_m2: number;
  land_cover_classes: LandCoverClassFraction[];
  features_found: number;
  features_mapped: number;
  query_time_s: number;
  warnings: string[];
  error_message: string | null;
}

// ---- Phase 11B-2: Soil / HSG ----

export interface SoilGroupFraction {
  soil_group: string;
  fraction: number;
  feature_count: number;
}

export interface CandidateSoilSource {
  id: string;
  name: string;
  url: string | null;
  resolution: string | null;
  status: string;
  reason: string | null;
}

export interface SoilGroupInfo {
  data_available: boolean;
  source: string;
  lookup_method: string;
  soil_group: string | null;
  soil_group_fractions: SoilGroupFraction[];
  bbox: Record<string, number> | null;
  warnings: string[];
  error_message: string | null;
  candidate_sources_considered: CandidateSoilSource[];
}

// ---- Phase 11B-3: SCS-CN runoff ----

export interface LandCoverCNContribution {
  land_cover_class: string;
  soil_group: string;
  cn_ii: number;
  cn_amc: number;
  area_fraction: number;
  weighted_cn: number;
  warning: string | null;
}

export interface RunoffInfo {
  data_available: boolean;
  source: string;
  method: string;
  rainfall_P_mm: number | null;
  amc_condition: string;
  soil_group: string | null;
  weighted_CN: number | null;
  CN_contributions: LandCoverCNContribution[];
  S_mm: number | null;
  Ia_mm: number | null;
  runoff_depth_mm: number | null;
  runoff_volume_m3: number | null;
  catchment_area_m2: number;
  catchment_area_ha: number;
  warnings: string[];
  error_message: string | null;
}

// ---- Phase 11B-4: Time of concentration ----

export interface TimeOfConcentrationInfo {
  data_available: boolean;
  method: string;
  formula: string;
  longest_flow_path_m: number;
  slope_m_per_m: number;
  slope_source: string;
  tc_minutes: number;
  tc_hours: number;
  warnings: string[];
  error_message: string | null;
}

// ---- Phase 11B-5: Pond adequacy ----

export interface PondAdequacyInfo {
  data_available: boolean;
  runoff_volume_m3: number | null;
  available_storage_m3: number | null;
  adequacy_ratio: number | null;
  status: string;
  threshold_pass: number;
  threshold_marginal: number;
  warnings: string[];
  error_message: string | null;
}

export interface BoundingBox {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
}

/** Source information for location-based analyses. */
export interface LocationSourceInfo {
  latitude: number;
  longitude: number;
  radius_km: number;
  contour_interval_m: number;
  dem_type: string;
}

/** Individual suitability factor scores, each in [0, 100]. */
export interface FactorScores {
  /** Flow accumulation percentile (higher = larger upstream catchment). */
  accumulation: number;
  /** Inverse-slope percentile (higher = flatter local terrain). */
  low_slope: number;
  /** Inverse-relative-elevation percentile (higher = more valley-like). */
  low_relative_elevation: number;
  /** Drainage concentration percentile (accumulation + on-flow-path bonus). */
  drainage_concentration: number;
}

/** A single ranked pond candidate returned by the pond-selection stage. */
export interface PondCandidateInfo {
  rank: number;
  row: number;
  col: number;
  lat: number;
  lon: number;
  elevation_m: number;
  suitability_score: number;
  flow_accumulation_cells: number;
  local_slope_deg: number;
  relative_elevation_m: number;
  factor_scores: FactorScores;
}

/**
 * The currently selected pond candidate (Phase 3 compact view).
 *
 * Note: the backend intentionally returns only 8 fields here (no
 * `factor_scores`, `local_slope_deg` or `relative_elevation_m`).
 * To get those values for the selected candidate, look it up in
 * `IntegratedAnalysisResponse.pond_candidates` by rank.
 */
export interface SelectedPond {
  rank: number;
  row: number;
  col: number;
  lat: number;
  lon: number;
  elevation_m: number;
  suitability_score: number;
  flow_accumulation_cells: number;
}

/** Geographic boundary representation of the catchment. */
export interface CatchmentBoundaryInfo {
  boundary_type: string;
  /** List of [lon, lat] coordinate pairs forming the boundary. */
  boundary_coordinates: number[][];
  num_boundary_cells: number;
  num_boundary_points: number;
  bounding_box: BoundingBox;
}

/** Validation and performance diagnostics for catchment delineation. */
export interface CatchmentDiagnosticsInfo {
  outlet_in_catchment: boolean;
  no_duplicate_cells: boolean;
  traversal_terminated_safely: boolean;
  cells_visited: number;
  max_queue_size: number;
  flow_accum_consistent: boolean;
  area_consistent: boolean;
  area_within_grid: boolean;
}

/** Summary of the Phase 2 water exclusion analysis. */
export interface WaterExclusionInfo {
  applied: boolean;
  fallback_used: boolean;
  features_found: number;
  feature_types: string[];
  cells_excluded: number;
  buffer_metres: number;
  error_message: string | null;
}

/**
 * Pond depth and storage volume estimates (Phase 4.1).
 *
 * All numeric values are derived from the terrain DEM via
 * trapezoidal elevation-slice integration. `usable_depth_m == 0`
 * and `storage_volume_m3 == 0` are expected when the surrounding
 * terrain does not provide enough natural containment.
 */
export interface PondCapacityInfo {
  usable_depth_m: number;
  max_depth_m: number;
  usable_spill_elevation_m: number;
  spill_elevation_m: number;
  cell_area_m2: number;
  surface_area_m2: number;
  storage_volume_m3: number;
  storage_volume_litres: number;
  method: string;
  assumptions: string[];
  warnings: string[];
  num_slices: number;
  neighbourhood_radius_cells: number;
  freeboard_m: number;
  candidate_elevation_m: number;
  min_neighbour_elevation_m: number;
  max_neighbour_elevation_m: number;
  mean_neighbour_elevation_m: number;
  cells_flooded_at_design_level: number;
}

/** Full response from POST /api/analyze-contour */
export interface IntegratedAnalysisResponse {
  filename: string;
  grid_width: number;
  grid_height: number;
  grid_cell_size_m: number;
  contour_count: number;
  num_candidates: number;
  pond_candidates: PondCandidateInfo[];
  selected_pond: SelectedPond;
  catchment_cells: number;
  catchment_area_m2: number;
  catchment_area_ha: number;
  catchment_area_km2: number;
  catchment_pct_of_grid: number;
  flow_accum_at_outlet: number;
  flow_accum_consistent: boolean;
  boundary: CatchmentBoundaryInfo;
  diagnostics: CatchmentDiagnosticsInfo;
  water_exclusion: WaterExclusionInfo;
  pond_capacity: PondCapacityInfo | null;
  source_info: LocationSourceInfo | null;
  error: string | null;
  time_elapsed_s: number;
  // ---- Phase 8: rainfall and weather (additive) ----
  rainfall: RainfallInfo | null;
  weather: WeatherInfo | null;
  rainfall_lookup: RainfallLookupMetadata | null;
  // ---- Phase 9: design rainfall (additive) ----
  design_rainfall: DesignRainfallInfo | null;
  // ---- Phase 11A: catchment terrain diagnostics (additive) ----
  catchment_terrain: CatchmentTerrainDiagnostics | null;
  // ---- Phase 11B: land cover, soil, runoff, Tc, pond adequacy (additive) ----
  land_cover: LandCoverInfo | null;
  soil_group: SoilGroupInfo | null;
  runoff: RunoffInfo | null;
  time_of_concentration: TimeOfConcentrationInfo | null;
  pond_adequacy: PondAdequacyInfo | null;
}

/** Request body for POST /api/analyze-location */
export interface LocationAnalysisRequest {
  latitude: number;
  longitude: number;
  radius_km: number;
  contour_interval_m: number;
  dem_type: string;
}

/** Options for analyzeLocation(). */
export interface LocationAnalysisOptions {
  /** Which ranked pond candidate to analyse (default: 1). */
  pondRank?: number;
  /** Terrain grid cell size in metres (default: 10). */
  gridCellSizeM?: number;
  /** IDW power (default: 2.0). */
  idwPower?: number;
  /** IDW k (default: 12). */
  idwK?: number;
  /** IDW epsilon (default: 1e-6). */
  idwEpsilon?: number;
  /** AbortSignal for request cancellation. */
  signal?: AbortSignal;
}

/** Typed API error with HTTP status and detail. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = 'ApiError';
  }
}
