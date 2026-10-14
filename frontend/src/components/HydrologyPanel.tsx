import type {
  IntegratedAnalysisResponse,
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
} from '../types/api';
import { fmtInt } from '../lib/utils';

interface Props {
  result: IntegratedAnalysisResponse;
}

// =============================================================================
// HydrologyPanel
//
// Phase 12 (Final): read-only display of the seven Phase 8/9/11 fields
// already emitted by the backend. No calculations are performed here;
// every value rendered comes directly from the backend response.
// All sections handle missing or "unavailable" data gracefully.
// =============================================================================

const MONTH_NAMES = [
  '', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

function fmtPercent(fraction: number, decimals = 1): string {
  return `${(fraction * 100).toFixed(decimals)}%`;
}

function fmtPeriod(start: string | null, end: string | null): string {
  if (start && end) return `${start} → ${end}`;
  if (start) return `from ${start}`;
  if (end) return `until ${end}`;
  return '—';
}

function fmtLookupBasis(basis: string): string {
  switch (basis) {
    case 'catchment_centroid': return 'Catchment centroid';
    case 'selected_pond': return 'Selected pond';
    case 'contour_bbox_centroid': return 'Contour bounding-box centroid';
    case 'user_location': return 'User-selected location';
    case 'point_lookup': return 'Point lookup';
    default: return basis.replace(/_/g, ' ');
  }
}

function SectionHeading({ letter, title }: { letter: string; title: string }) {
  return (
    <h2 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-terrain-700">
      {letter} &middot; {title}
    </h2>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="stat-label shrink-0">{label}</span>
      <span className="text-[12px] text-terrain-800 text-right break-all">{value}</span>
    </div>
  );
}

function UnavailableBanner({ message, error }: { message: string; error?: string | null }) {
  return (
    <div className="bg-amber-50 border border-amber-200 rounded-lg p-2.5 space-y-1">
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0" />
        <p className="text-[11px] font-semibold text-terrain-800">{message}</p>
      </div>
      {error && (
        <p className="text-[11px] text-amber-700 italic pl-4">{error}</p>
      )}
    </div>
  );
}

function WarningsBlock({ warnings }: { warnings: string[] }) {
  if (!warnings || warnings.length === 0) return null;
  return (
    <div className="bg-amber-50 border border-amber-100 rounded-lg p-2.5 space-y-1">
      <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-amber-700">
        Warnings
      </p>
      <ul className="space-y-0.5">
        {warnings.map((w, i) => (
          <li key={i} className="text-[11px] text-amber-800 flex gap-1.5">
            <span className="text-amber-400 shrink-0">&#9888;</span>
            <span>{w}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// =============================================================================
// A. Rainfall & Weather
// =============================================================================

function RainfallWeatherSection({
  rainfall,
  weather,
  rainfall_lookup,
}: {
  rainfall: RainfallInfo | null;
  weather: WeatherInfo | null;
  rainfall_lookup: RainfallLookupMetadata | null;
}) {
  // If all three are null, skip the entire section.
  if (rainfall === null && weather === null && rainfall_lookup === null) {
    return null;
  }

  return (
    <div className="card-elevated p-4 space-y-3">
      <SectionHeading letter="G" title="Rainfall &amp; Weather" />

      {/* Rainfall lookup metadata */}
      {rainfall_lookup && (
        <div className="rounded-lg bg-water-50 border border-water-100 p-2.5 space-y-1">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-water-500 shrink-0" />
            <p className="text-[11px] font-semibold text-terrain-800">
              Rainfall lookup: {fmtLookupBasis(rainfall_lookup.lookup_basis)}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px] pl-4">
            <StatRow
              label="Latitude"
              value={rainfall_lookup.lookup_location.latitude.toFixed(5) + '°'}
            />
            <StatRow
              label="Longitude"
              value={rainfall_lookup.lookup_location.longitude.toFixed(5) + '°'}
            />
          </div>
          {rainfall_lookup.note && (
            <p className="text-[10px] text-terrain-600 italic pl-4">
              {rainfall_lookup.note}
            </p>
          )}
        </div>
      )}

      {/* Rainfall */}
      {rainfall && (
        <div className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500">
            Historical rainfall ({rainfall.source})
          </p>
          {rainfall.rainfall_data_available ? (
            <div className="space-y-1">
              <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
                <StatRow
                  label="Period"
                  value={fmtPeriod(rainfall.data_period_start, rainfall.data_period_end)}
                />
                <StatRow label="Resolution" value={rainfall.data_resolution ?? '—'} />
                <StatRow label="Annual total" value={
                  rainfall.annual_rainfall_mm !== null
                    ? `${rainfall.annual_rainfall_mm.toFixed(0)} mm`
                    : '—'
                } />
                <StatRow label="Rainy days" value={
                  rainfall.rainy_days !== null
                    ? fmtInt(rainfall.rainy_days)
                    : '—'
                } />
                <StatRow label="Max daily" value={
                  rainfall.max_daily_rainfall_mm !== null
                    ? `${rainfall.max_daily_rainfall_mm.toFixed(1)} mm`
                    : '—'
                } />
                <StatRow label="Observations" value={
                  rainfall.number_of_observations !== null
                    ? fmtInt(rainfall.number_of_observations)
                    : '—'
                } />
              </div>
              {rainfall.monthly_rainfall_mm && Object.keys(rainfall.monthly_rainfall_mm).length > 0 && (
                <div className="pt-1">
                  <p className="text-[10px] uppercase tracking-[0.08em] text-terrain-500 font-semibold mb-1">
                    Monthly rainfall (mm)
                  </p>
                  <div className="grid grid-cols-6 gap-1 text-[10px] font-mono">
                    {Array.from({ length: 12 }, (_, i) => {
                      const key = String(i + 1);
                      const v = rainfall.monthly_rainfall_mm?.[key];
                      return (
                        <div key={key} className="text-center bg-terrain-50 rounded px-1 py-0.5">
                          <div className="text-terrain-500">{MONTH_NAMES[i + 1]}</div>
                          <div className="text-terrain-800 font-semibold">
                            {v !== undefined && v !== null ? v.toFixed(0) : '—'}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {rainfall.error_message && rainfall.rainfall_data_available && (
                <p className="text-[10px] text-amber-700 italic">
                  {rainfall.error_message}
                </p>
              )}
            </div>
          ) : (
            <UnavailableBanner
              message="Rainfall data unavailable"
              error={rainfall.error_message}
            />
          )}
        </div>
      )}

      {/* Weather */}
      {weather && (
        <div className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500">
            Current weather ({weather.source})
          </p>
          {weather.weather_data_available ? (
            <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
              <StatRow label="Observed at" value={
                weather.observation_timestamp ?? '—'
              } />
              <StatRow label="Temperature" value={
                weather.temperature_c !== null
                  ? `${weather.temperature_c.toFixed(1)} °C`
                  : '—'
              } />
              <StatRow label="Humidity" value={
                weather.humidity_pct !== null
                  ? `${weather.humidity_pct.toFixed(0)} %`
                  : '—'
              } />
              <StatRow label="Precipitation" value={
                weather.precipitation_mm !== null
                  ? `${weather.precipitation_mm.toFixed(1)} mm`
                  : '—'
              } />
              <StatRow label="Wind speed" value={
                weather.wind_speed_kmh !== null
                  ? `${weather.wind_speed_kmh.toFixed(1)} km/h`
                  : '—'
              } />
              <StatRow label="Wind direction" value={
                weather.wind_direction_deg !== null
                  ? `${weather.wind_direction_deg.toFixed(0)}°`
                  : '—'
              } />
              {weather.weather_description && (
                <div className="col-span-2">
                  <StatRow
                    label="Conditions"
                    value={weather.weather_description}
                  />
                </div>
              )}
            </div>
          ) : (
            <UnavailableBanner
              message="Weather data unavailable"
              error={weather.error_message}
            />
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// B. Design Rainfall
// =============================================================================

function DesignRainfallSection({ dr }: { dr: DesignRainfallInfo | null }) {
  if (!dr) return null;

  return (
    <div className="card-elevated p-4 space-y-3">
      <SectionHeading letter="H" title="Design Rainfall" />

      {dr.design_rainfall_available ? (
        <div className="space-y-1.5">
          {/* Key result banner */}
          <div className="rounded-lg bg-water-50 border border-water-100 p-3 flex items-center gap-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-water-600 mb-0.5">
                {dr.return_period_years}-year, 24-hour depth
              </p>
              <p className="text-[22px] font-mono font-bold text-water-700 leading-none">
                {dr.design_rainfall_mm !== null ? `${dr.design_rainfall_mm.toFixed(1)} mm` : '—'}
              </p>
            </div>
            <div className="border-l border-water-200 pl-4 space-y-0.5">
              <div className="text-[10px] text-terrain-500">Return period</div>
              <div className="text-[12px] font-mono font-semibold text-terrain-800">
                {dr.return_period_years}-year
              </div>
              <div className="text-[10px] text-terrain-500">Distribution</div>
              <div className="text-[12px] font-mono text-terrain-700">
                {dr.distribution}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <StatRow label="Source" value={dr.source} />
            <StatRow label="Fitting method" value={dr.fitting_method} />
            <StatRow label="Data period" value={fmtPeriod(dr.data_period_start, dr.data_period_end)} />
            <StatRow label="Data quality" value={dr.data_quality.replace(/_/g, ' ')} />
            <StatRow label="Years of data" value={
              dr.number_of_years !== null ? fmtInt(dr.number_of_years) : '—'
            } />
            <StatRow label="Observations" value={
              dr.number_of_observations !== null ? fmtInt(dr.number_of_observations) : '—'
            } />
            <StatRow label="Annual max. count" value={
              dr.annual_maxima_count !== null ? fmtInt(dr.annual_maxima_count) : '—'
            } />
            <StatRow label="Max annual max." value={
              dr.annual_maximum_max_mm !== null ? `${dr.annual_maximum_max_mm.toFixed(1)} mm` : '—'
            } />
            <StatRow label="Mean annual max." value={
              dr.annual_maximum_mean_mm !== null ? `${dr.annual_maximum_mean_mm.toFixed(1)} mm` : '—'
            } />
            <StatRow label="Min annual max." value={
              dr.annual_maximum_min_mm !== null ? `${dr.annual_maximum_min_mm.toFixed(1)} mm` : '—'
            } />
          </div>

          <p className="text-[10px] text-terrain-500 italic leading-snug">
            24-hour design rainfall depth derived from historical annual-maximum daily rainfall
            using the {dr.distribution} distribution ({dr.fitting_method}).
            Not a storm intensity — use an appropriate design storm profile for runoff routing.
          </p>

          <WarningsBlock warnings={dr.warnings} />
        </div>
      ) : (
        <UnavailableBanner message="Design rainfall unavailable" error={dr.error_message} />
      )}
    </div>
  );
}

// =============================================================================
// C. Catchment Terrain Diagnostics
// =============================================================================

function CatchmentTerrainSection({ ct }: { ct: CatchmentTerrainDiagnostics | null }) {
  if (!ct) return null;

  return (
    <div className="card-elevated p-4 space-y-3">
      <SectionHeading letter="I" title="Catchment Terrain" />

      <div className="space-y-1.5">
        {/* Slope */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-1">
            Slope statistics
          </p>
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'Mean', deg: ct.mean_slope_deg, m: ct.mean_slope_m_per_m },
              { label: 'Max', deg: ct.max_slope_deg, m: ct.max_slope_m_per_m },
              { label: 'Min', deg: ct.min_slope_deg, m: ct.min_slope_m_per_m },
            ].map(({ label, deg, m }) => (
              <div key={label} className="rounded-lg bg-terrain-50 p-2 text-center">
                <div className="text-[10px] text-terrain-500 mb-0.5">{label}</div>
                <div className="text-[13px] font-mono font-semibold text-terrain-800">
                  {deg.toFixed(2)}°
                </div>
                <div className="text-[10px] font-mono text-terrain-500">
                  {m.toFixed(4)} m/m
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Elevation */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-1">
            Elevation statistics
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <StatRow label="Min elevation" value={`${ct.min_elevation_m.toFixed(2)} m`} />
            <StatRow label="Max elevation" value={`${ct.max_elevation_m.toFixed(2)} m`} />
            <StatRow label="Relief" value={`${ct.relief_m.toFixed(2)} m`} />
            <StatRow label="Mean elevation" value={`${ct.mean_elevation_m.toFixed(2)} m`} />
          </div>
        </div>

        {/* Flow path */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-1">
            Longest flow path
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <StatRow label="Path length" value={`${ct.longest_flow_path_m.toFixed(1)} m`} />
            <StatRow label="Cells" value={fmtInt(ct.longest_flow_path_cells)} />
            <StatRow label="Headwater cells" value={fmtInt(ct.number_of_headwater_cells)} />
            <StatRow label="Outlet cell" value={`[${ct.longest_flow_path_outlet_row}, ${ct.longest_flow_path_outlet_col}]`} />
          </div>
        </div>

        <p className="text-[10px] text-terrain-500 italic">
          {ct.method}
        </p>

        <WarningsBlock warnings={ct.warnings} />
      </div>
    </div>
  );
}

// =============================================================================
// D. Land Cover
// =============================================================================

function LandCoverSection({ lc }: { lc: LandCoverInfo | null }) {
  if (!lc) return null;

  return (
    <div className="card-elevated p-4 space-y-3">
      <SectionHeading letter="J" title="Land Cover" />

      {lc.data_available ? (
        <div className="space-y-1.5">
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <StatRow label="Source" value={lc.source} />
            <StatRow label="Features found" value={fmtInt(lc.features_found)} />
            <StatRow label="Features mapped" value={fmtInt(lc.features_mapped)} />
            <StatRow label="BBox area" value={
              lc.bbox_area_m2 >= 1_000_000
                ? `${(lc.bbox_area_m2 / 1_000_000).toFixed(4)} km²`
                : `${lc.bbox_area_m2.toFixed(0)} m²`
            } />
          </div>

          {lc.land_cover_classes.length > 0 ? (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500">
                Land-cover fractions
              </p>
              {lc.land_cover_classes.map((cls) => (
                <div key={cls.land_cover_class} className="space-y-0.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-terrain-700 capitalize">
                      {cls.land_cover_class.replace(/_/g, ' ')}
                    </span>
                    <span className="text-[11px] font-mono text-terrain-800">
                      {fmtPercent(cls.fraction)} &nbsp; <span className="text-terrain-400">
                        ({cls.area_m2 >= 1000
                          ? `${(cls.area_m2 / 1000).toFixed(0)}k m²`
                          : `${cls.area_m2.toFixed(0)} m²`})
                      </span>
                    </span>
                  </div>
                  <div className="h-1.5 bg-terrain-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-water-400 rounded-full"
                      style={{ width: `${Math.min(100, cls.fraction * 100).toFixed(1)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-terrain-500 italic">
              No land-cover features could be mapped within the catchment bounding box.
            </p>
          )}

          <WarningsBlock warnings={lc.warnings} />
        </div>
      ) : (
        <UnavailableBanner
          message="Land-cover data unavailable"
          error={lc.error_message}
        />
      )}
    </div>
  );
}

// =============================================================================
// E. Soil / Hydrologic Soil Group (HSG)
// Special handling: NEVER fabricate. Explicit "unavailable" state with sources.
// =============================================================================

function SoilGroupSection({ sg }: { sg: SoilGroupInfo | null }) {
  if (!sg) return null;

  return (
    <div className="card-elevated p-4 space-y-3">
      <SectionHeading letter="K" title="Soil / Hydrologic Soil Group" />

      {sg.data_available ? (
        // Future: real soil provider connected. Render the actual HSG.
        <div className="space-y-1.5">
          <div className="rounded-lg bg-water-50 border border-water-100 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-water-600 mb-0.5">
              Dominant HSG
            </p>
            <p className="text-[22px] font-mono font-bold text-water-700 leading-none">
              {sg.soil_group ?? '—'}
            </p>
          </div>
          <p className="text-[10px] text-terrain-500 italic">{sg.lookup_method}</p>

          {sg.soil_group_fractions.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500">
                HSG fractions
              </p>
              {sg.soil_group_fractions.map((f) => (
                <div key={f.soil_group} className="flex items-center justify-between text-[11px]">
                  <span className="font-mono text-terrain-800">HSG {f.soil_group}</span>
                  <span className="font-mono text-terrain-700">
                    {fmtPercent(f.fraction)}
                    <span className="text-terrain-400 ml-1">
                      ({fmtInt(f.feature_count)} features)
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}

          <WarningsBlock warnings={sg.warnings} />
        </div>
      ) : (
        // No real soil-data provider is connected in this build. We must
        // never fabricate an HSG from land-cover. Show the explicit
        // "unavailable" state plus the candidate sources the backend
        // considered for provenance.
        <div className="space-y-2">
          <UnavailableBanner
            message="Soil / HSG data unavailable — no authoritative soil provider is connected"
            error={sg.error_message}
          />
          <p className="text-[11px] text-terrain-600 italic">
            {sg.lookup_method}
          </p>

          {sg.candidate_sources_considered.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500">
                Candidate soil-data sources (provenance)
              </p>
              <ul className="space-y-1">
                {sg.candidate_sources_considered.map((src) => (
                  <li key={src.id} className="text-[11px] bg-terrain-50 rounded px-2 py-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-terrain-800">{src.name}</span>
                      <span className={`pill ${src.status === 'connected'
                        ? 'bg-green-100 text-green-700'
                        : 'bg-amber-100 text-amber-700'}`}>
                        {src.status === 'connected' ? 'connected' : 'not connected'}
                      </span>
                    </div>
                    <div className="text-[10px] text-terrain-500 mt-0.5">
                      {src.resolution && <>Resolution: {src.resolution}</>}
                      {src.reason && (
                        <> &middot; {src.reason}</>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-[10px] text-terrain-500 italic leading-snug">
            Runoff and pond adequacy are unavailable in this build because they require a real
            soil / HSG value. The hydrologic soil group is not inferred from land-cover.
          </p>

          <WarningsBlock warnings={sg.warnings} />
        </div>
      )}
    </div>
  );
}

// =============================================================================
// F. Runoff (SCS-CN)
// =============================================================================

function RunoffSection({ ro }: { ro: RunoffInfo | null }) {
  if (!ro) return null;

  return (
    <div className="card-elevated p-4 space-y-3">
      <SectionHeading letter="L" title="Runoff (SCS-CN)" />

      {ro.data_available ? (
        <div className="space-y-1.5">
          {/* Inputs / Outputs */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            <div className="rounded-lg bg-terrain-50 p-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-1">
                Forcing (rainfall P)
              </p>
              <p className="text-[18px] font-mono font-bold text-terrain-800 leading-none">
                {ro.rainfall_P_mm !== null ? `${ro.rainfall_P_mm.toFixed(1)} mm` : '—'}
              </p>
              <p className="text-[10px] text-terrain-500 mt-0.5">AMC {ro.amc_condition}</p>
            </div>
            <div className="rounded-lg bg-water-50 border border-water-100 p-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-water-600 mb-1">
                Response (runoff Q)
              </p>
              <p className="text-[18px] font-mono font-bold text-water-700 leading-none">
                {ro.runoff_depth_mm !== null ? `${ro.runoff_depth_mm.toFixed(2)} mm` : '—'}
              </p>
              <p className="text-[10px] text-water-600 mt-0.5">
                {ro.runoff_volume_m3 !== null
                  ? `${fmtInt(ro.runoff_volume_m3)} m³`
                  : '—'}
              </p>
            </div>
          </div>

          {/* CN / S / Ia */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <StatRow label="Weighted CN" value={
              ro.weighted_CN !== null ? ro.weighted_CN.toFixed(1) : '—'
            } />
            <StatRow label="Soil group" value={ro.soil_group ?? '—'} />
            <StatRow label="S (potential retention)" value={
              ro.S_mm !== null ? `${ro.S_mm.toFixed(2)} mm` : '—'
            } />
            <StatRow label="Ia (initial abstraction)" value={
              ro.Ia_mm !== null ? `${ro.Ia_mm.toFixed(2)} mm` : '—'
            } />
            <StatRow label="Catchment area" value={
              ro.catchment_area_ha >= 1
                ? `${ro.catchment_area_ha.toFixed(2)} ha`
                : `${ro.catchment_area_m2.toFixed(0)} m²`
            } />
            <StatRow label="AMC condition" value={ro.amc_condition} />
          </div>

          {/* CN contributions */}
          {ro.CN_contributions.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500">
                Per-class CN contributions
              </p>
              {ro.CN_contributions.map((c, i) => (
                <div key={i} className="bg-terrain-50 rounded px-2 py-1.5 space-y-0.5">
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-terrain-800 capitalize">
                      {c.land_cover_class.replace(/_/g, ' ')}
                    </span>
                    <span className="font-mono text-terrain-700">
                      CN II {c.cn_ii} → AMC {c.cn_amc.toFixed(1)}
                    </span>
                  </div>
                  <div className="text-[10px] text-terrain-500 font-mono">
                    HSG {c.soil_group} &middot; frac {fmtPercent(c.area_fraction, 0)} &middot; weighted CN {c.weighted_cn.toFixed(2)}
                  </div>
                  {c.warning && (
                    <p className="text-[10px] text-amber-700 italic">{c.warning}</p>
                  )}
                </div>
              ))}
            </div>
          )}

          <p className="text-[10px] text-terrain-500 italic">{ro.method}</p>
          <WarningsBlock warnings={ro.warnings} />
        </div>
      ) : (
        // Explicit unavailable. NEVER display fake zero runoff.
        <UnavailableBanner
          message="Runoff unavailable"
          error={ro.error_message}
        />
      )}
    </div>
  );
}

// =============================================================================
// G. Time of Concentration (Kirpich 1940)
// =============================================================================

function TimeOfConcentrationSection({ tc }: { tc: TimeOfConcentrationInfo | null }) {
  if (!tc) return null;

  return (
    <div className="card-elevated p-4 space-y-3">
      <SectionHeading letter="M" title="Time of Concentration" />

      {tc.data_available ? (
        <div className="space-y-1.5">
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg bg-water-50 border border-water-100 p-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-water-600 mb-0.5">
                Tc (minutes)
              </p>
              <p className="text-[20px] font-mono font-bold text-water-700 leading-none">
                {tc.tc_minutes.toFixed(1)}
              </p>
            </div>
            <div className="rounded-lg bg-terrain-50 p-2.5">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-0.5">
                Tc (hours)
              </p>
              <p className="text-[20px] font-mono font-bold text-terrain-800 leading-none">
                {tc.tc_hours.toFixed(2)}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <StatRow label="Method" value={tc.method} />
            <StatRow label="Longest flow path" value={`${tc.longest_flow_path_m.toFixed(1)} m`} />
            <StatRow label="Slope (m/m)" value={tc.slope_m_per_m.toFixed(4)} />
            <StatRow label="Slope source" value={tc.slope_source} />
          </div>

          <div className="bg-terrain-50 rounded px-2 py-1.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-0.5">
              Formula
            </p>
            <p className="text-[11px] font-mono text-terrain-700 break-all">
              {tc.formula}
            </p>
          </div>

          <WarningsBlock warnings={tc.warnings} />
        </div>
      ) : (
        <UnavailableBanner
          message="Time of concentration unavailable"
          error={tc.error_message}
        />
      )}
    </div>
  );
}

// =============================================================================
// H. Pond Adequacy
// =============================================================================

function statusPill(status: string): { label: string; classes: string } {
  switch (status) {
    case 'pass':
      return { label: 'PASS', classes: 'bg-green-100 text-green-800' };
    case 'marginal':
      return { label: 'MARGINAL', classes: 'bg-amber-100 text-amber-800' };
    case 'fail':
      return { label: 'FAIL', classes: 'bg-red-100 text-red-800' };
    case 'unavailable':
      return { label: 'UNAVAILABLE', classes: 'bg-terrain-100 text-terrain-700' };
    default:
      return { label: status.toUpperCase(), classes: 'bg-terrain-100 text-terrain-700' };
  }
}

function PondAdequacySection({ pa }: { pa: PondAdequacyInfo | null }) {
  if (!pa) return null;

  const pill = statusPill(pa.status);

  return (
    <div className="card-elevated p-4 space-y-3">
      <SectionHeading letter="N" title="Pond Adequacy" />

      {pa.data_available ? (
        <div className="space-y-1.5">
          <div className="rounded-lg bg-white border border-terrain-200 p-3 flex items-center justify-between">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-0.5">
                Status
              </p>
              <p className="text-[20px] font-mono font-bold leading-none">
                <span className={`pill ${pill.classes} text-[14px] font-semibold`}>
                  {pill.label}
                </span>
              </p>
            </div>
            <div className="text-right">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-0.5">
                Adequacy ratio
              </p>
              <p className="text-[20px] font-mono font-bold text-terrain-800 leading-none">
                {pa.adequacy_ratio !== null
                  ? (Number.isFinite(pa.adequacy_ratio)
                      ? pa.adequacy_ratio.toFixed(2)
                      : '∞')
                  : '—'}
              </p>
              <p className="text-[10px] text-terrain-500 mt-0.5">
                storage / runoff
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <StatRow label="Runoff volume" value={
              pa.runoff_volume_m3 !== null
                ? `${fmtInt(pa.runoff_volume_m3)} m³`
                : '—'
            } />
            <StatRow label="Available storage" value={
              pa.available_storage_m3 !== null
                ? `${fmtInt(pa.available_storage_m3)} m³`
                : '—'
            } />
            <StatRow label="Pass threshold" value={`≥ ${pa.threshold_pass.toFixed(2)}`} />
            <StatRow label="Marginal threshold" value={`≥ ${pa.threshold_marginal.toFixed(2)}`} />
          </div>

          <p className="text-[10px] text-terrain-500 italic leading-snug">
            Thresholds are documented engineering judgments; no safety factor is applied.
          </p>

          <WarningsBlock warnings={pa.warnings} />
        </div>
      ) : (
        // Runoff or storage unavailable -> adequacy unavailable.
        // Do not treat as zero. Do not fabricate PASS/MARGINAL/FAIL.
        <UnavailableBanner
          message="Pond adequacy unavailable"
          error={pa.error_message}
        />
      )}
    </div>
  );
}

// =============================================================================
// Main HydrologyPanel
// =============================================================================

export function HydrologyPanel({ result }: Props) {
  return (
    <div className="space-y-4">
      <RainfallWeatherSection
        rainfall={result.rainfall}
        weather={result.weather}
        rainfall_lookup={result.rainfall_lookup}
      />
      <DesignRainfallSection dr={result.design_rainfall} />
      <CatchmentTerrainSection ct={result.catchment_terrain} />
      <LandCoverSection lc={result.land_cover} />
      <SoilGroupSection sg={result.soil_group} />
      <RunoffSection ro={result.runoff} />
      <TimeOfConcentrationSection tc={result.time_of_concentration} />
      <PondAdequacySection pa={result.pond_adequacy} />
    </div>
  );
}
