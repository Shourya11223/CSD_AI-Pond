import type { IntegratedAnalysisResponse } from '../types/api';
import { fmtInt, fmtDuration, scoreBgClass, scoreColor, FACTOR_LABELS, fmtVolume } from '../lib/utils';
import { HydrologyPanel } from './HydrologyPanel';

interface Props {
  result: IntegratedAnalysisResponse;
  onNewAnalysis: () => void;
}

function ScoreRing({ score }: { score: number }) {
  const r = 30;
  const circ = 2 * Math.PI * r;
  const filled = (score / 100) * circ;
  const color = scoreColor(score);
  return (
    <div className="relative w-[72px] h-[72px] shrink-0">
      <svg width="72" height="72" viewBox="0 0 72 72" className="-rotate-90">
        <circle cx="36" cy="36" r={r} fill="none" stroke="#e5e1d5" strokeWidth="5" />
        <circle
          cx="36" cy="36" r={r} fill="none" stroke={color} strokeWidth="5"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circ}`}
          style={{ transition: 'stroke-dasharray 0.8s cubic-bezier(0.4,0,0.2,1)' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono font-bold text-[16px] leading-none" style={{ color }}>{score.toFixed(0)}</span>
        <span className="text-[9px] text-terrain-400 font-mono">/100</span>
      </div>
    </div>
  );
}

function ValidationPill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <div className={`pill ${ok ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'}`}>
      <span>{ok ? '&#10003;' : '&#9888;'}</span>
      <span>{label}</span>
    </div>
  );
}

/** Horizontal bar for a factor score */
function FactorBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-terrain-600">{label}</span>
        <span className="text-[11px] font-mono font-semibold tabular-nums" style={{ color: scoreColor(value) }}>
          {value.toFixed(0)}
        </span>
      </div>
      <div className="h-1.5 bg-terrain-100 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${Math.min(100, Math.max(0, value))}%`, backgroundColor: scoreColor(value) }}
        />
      </div>
    </div>
  );
}

/** Section heading with letter label */
function SectionHeader({ letter, title }: { letter: string; title: string }) {
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

export function ResultsPanel({ result, onNewAnalysis }: Props) {
  const {
    selected_pond,
    pond_candidates,
    catchment_cells,
    catchment_area_ha,
    catchment_area_km2,
    catchment_area_m2,
    catchment_pct_of_grid,
    flow_accum_at_outlet,
    flow_accum_consistent,
    boundary,
    diagnostics,
    grid_width,
    grid_height,
    grid_cell_size_m,
    contour_count,
    time_elapsed_s,
    filename,
    water_exclusion,
    pond_capacity,
  } = result;

  const { suitability_score, lat, lon, elevation_m, flow_accumulation_cells } = selected_pond;
  // `selected_pond` from the backend does not include factor_scores.
  // Look them up from the matching entry in `pond_candidates`.
  const candidateDetails = pond_candidates.find((c) => c.rank === selected_pond.rank) ?? null;
  const isZeroCapacity = pond_capacity && (pond_capacity.usable_depth_m === 0 || pond_capacity.storage_volume_m3 === 0);

  return (
    <div className="h-full overflow-y-auto p-4 space-y-4 animate-slide-up">

      {/* ── A. Recommended Pond ── */}
      <div className="card-elevated p-4 space-y-3">
        <SectionHeader letter="A" title="Recommended Pond" />
        <div className="flex items-start gap-3">
          <ScoreRing score={suitability_score} />
          <div className="flex-1 min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-terrain-500 mb-0.5">Suitability Score</p>
            <div className={`pill ${scoreBgClass(suitability_score)}`}>
              {suitability_score >= 80 ? 'Excellent' : suitability_score >= 50 ? 'Good' : 'Low'}
            </div>
            <p className="text-[10px] text-terrain-400 mt-1">
              Candidate rank {selected_pond.rank} &middot; {fmtInt(flow_accumulation_cells)} cells upstream
              {pond_candidates.length > 1 && (
                <span className="ml-1 text-terrain-400">
                  of {fmtInt(pond_candidates.reduce((s, c) => s + c.flow_accumulation_cells, 0))} total candidate cells
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="space-y-1.5">
          <div className="flex items-baseline gap-2">
            <span className="stat-label w-20 shrink-0">Latitude</span>
            <span className="stat-value text-[12px]">{lat.toFixed(6)}</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="stat-label w-20 shrink-0">Longitude</span>
            <span className="stat-value text-[12px]">{lon.toFixed(6)}</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="stat-label w-20 shrink-0">Elevation</span>
            <span className="stat-value text-[12px]">{elevation_m.toFixed(1)} m</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="stat-label w-20 shrink-0">Grid location</span>
            <span className="stat-value text-[12px]">row {selected_pond.row}, col {selected_pond.col}</span>
          </div>
        </div>
      </div>

      {/* ── B. Suitability Breakdown ── */}
      <div className="card-elevated p-4 space-y-2">
        <SectionHeader letter="B" title="Suitability Breakdown" />
        {candidateDetails ? (
          <div className="space-y-2">
            {(Object.keys(candidateDetails.factor_scores) as (keyof typeof candidateDetails.factor_scores)[]).map((k) => (
              <FactorBar key={k} label={FACTOR_LABELS[k]} value={candidateDetails.factor_scores[k]} />
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-terrain-500 italic">
            Factor scores for the selected candidate are not available.
          </p>
        )}
        <p className="text-[10px] text-terrain-400 italic pt-1">
          Scores are percentiles from 0&ndash;100 derived from the terrain grid.
          Higher is better for all factors.
        </p>
      </div>

      {/* ── C. Catchment ── */}
      <div className="card-elevated p-4 space-y-3">
        <SectionHeader letter="C" title="Catchment" />
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
          <StatRow label="Area (primary)" value={`${catchment_area_ha.toFixed(2)} ha`} />
          <StatRow label="km&sup2;" value={`${catchment_area_km2.toFixed(4)} km²`} />
          <StatRow label="m²" value={`${catchment_area_m2.toLocaleString()} m²`} />
          <StatRow label="Grid %" value={`${catchment_pct_of_grid.toFixed(1)}%`} />
          <StatRow label="Cells" value={fmtInt(catchment_cells)} />
          <StatRow label="Flow accum. at outlet" value={fmtInt(flow_accum_at_outlet)} />
        </div>
        <div className="space-y-1">
          <div className="h-2 bg-terrain-100 rounded-full overflow-hidden">
            <div className="h-full bg-water-500 rounded-full transition-all duration-700" style={{ width: `${Math.min(catchment_pct_of_grid, 100)}%` }} />
          </div>
          <p className="text-[10px] text-terrain-400 text-right">{catchment_pct_of_grid.toFixed(1)}% of total grid</p>
        </div>
        <div className="flex items-center gap-1.5 pt-0.5">
          <span className={`w-1.5 h-1.5 rounded-full ${flow_accum_consistent ? 'bg-green-400' : 'bg-amber-400'}`} />
          <span className="text-[11px] text-terrain-500">
            {flow_accum_consistent
              ? 'Flow accumulation consistent with catchment cells'
              : 'Flow accumulation inconsistency detected'}
          </span>
        </div>
      </div>

      {/* ── D. Pond Depth & Storage Capacity ── */}
      {pond_capacity ? (
        <div className="card-elevated p-4 space-y-3">
          <SectionHeader letter="D" title="Pond Depth &amp; Storage" />
          {isZeroCapacity ? (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 space-y-2">
              <p className="text-[12px] font-semibold text-amber-900">
                &#9888; Insufficient natural containment
              </p>
              <p className="text-[11px] text-amber-800 leading-relaxed">
                The surrounding terrain does not provide enough natural containment
                for the configured design assumptions. Terrain-derived depth and
                volume are zero or negligible.
              </p>
              <p className="text-[11px] text-amber-700 italic">
                This is not an error &mdash; it reflects the actual topographic conditions
                at this location.
              </p>
            </div>
          ) : null}

          {/* Primary stats */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
            <StatRow
              label="Max terrain depth"
              value={`${pond_capacity.max_depth_m.toFixed(2)} m`}
            />
            <StatRow
              label="Usable depth"
              value={`${pond_capacity.usable_depth_m.toFixed(2)} m`}
            />
            <StatRow
              label="Surface area"
              value={`${pond_capacity.surface_area_m2.toFixed(1)} m²`}
            />
            <StatRow
              label="Storage (m³)"
              value={fmtVolume(pond_capacity.storage_volume_m3).m3}
            />
            {pond_capacity.storage_volume_m3 > 0 && (
              <StatRow
                label="Storage (L)"
                value={fmtVolume(pond_capacity.storage_volume_m3).litres}
              />
            )}
            <StatRow
              label="Spill elevation"
              value={`${pond_capacity.spill_elevation_m.toFixed(2)} m`}
            />
          </div>

          {/* Design assumptions */}
          <div className="space-y-1 pt-1">
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 mb-1">
              Terrain-based estimates (not final engineering design)
            </p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
              <StatRow label="Method" value={pond_capacity.method} />
              <StatRow label="Neighbourhood" value={`${pond_capacity.neighbourhood_radius_cells} cells`} />
              <StatRow label="Freeboard" value={`${pond_capacity.freeboard_m} m`} />
              <StatRow label="Slices" value={String(pond_capacity.num_slices)} />
              <StatRow
                label="Candidate elev."
                value={`${pond_capacity.candidate_elevation_m.toFixed(2)} m`}
              />
              <StatRow
                label="Cells flooded"
                value={fmtInt(pond_capacity.cells_flooded_at_design_level)}
              />
            </div>
          </div>

          {/* Assumptions list */}
          {pond_capacity.assumptions.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500">Assumptions</p>
              <ul className="space-y-0.5">
                {pond_capacity.assumptions.map((a, i) => (
                  <li key={i} className="text-[11px] text-terrain-600 flex gap-1.5">
                    <span className="text-terrain-300 shrink-0">&bull;</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Warnings list */}
          {pond_capacity.warnings.length > 0 && (
            <div className="bg-amber-50 border border-amber-100 rounded-lg p-2.5 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-amber-700">Reliability warnings</p>
              <ul className="space-y-0.5">
                {pond_capacity.warnings.map((w, i) => (
                  <li key={i} className="text-[11px] text-amber-800 flex gap-1.5">
                    <span className="text-amber-400 shrink-0">&#9888;</span>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="card-elevated p-4">
          <SectionHeader letter="D" title="Pond Depth &amp; Storage" />
          <p className="text-[12px] text-terrain-500 mt-2 italic">
            Pond capacity estimation was not available for this analysis.
          </p>
        </div>
      )}

      {/* ── E. Terrain & Hydrology ── */}
      <div className="card-elevated p-4 space-y-2">
        <SectionHeader letter="E" title="Terrain &amp; Hydrology" />
        <div className="space-y-1">
          {([
            ['Grid dimensions', `${grid_width} × ${grid_height} cells`],
            ['Cell size', `${grid_cell_size_m} m`],
            ['Contour lines', fmtInt(contour_count)],
            ['Flow accum. at outlet', fmtInt(flow_accum_at_outlet)],
            ['Boundary type', boundary.boundary_type.replace(/_/g, ' ')],
            ['Boundary cells', fmtInt(boundary.num_boundary_cells)],
            ['Processing time', fmtDuration(time_elapsed_s)],
            ['Source file', filename],
          ] as [string, string][]).map(([label, value]) => (
            <div key={label} className="flex items-start justify-between gap-2">
              <span className="stat-label shrink-0">{label}</span>
              <span className="text-[12px] text-terrain-800 text-right break-all">{value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── F. Validation & Water Exclusion ── */}
      <div className="card-elevated p-4 space-y-2.5">
        <SectionHeader letter="F" title="Validation &amp; Water Exclusion" />

        {/* Water exclusion status */}
        <div className={`rounded-lg p-2.5 space-y-1 ${water_exclusion.fallback_used ? 'bg-amber-50 border border-amber-200' : 'bg-green-50 border border-green-100'}`}>
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${water_exclusion.fallback_used ? 'bg-amber-400' : 'bg-green-400'}`} />
            <p className="text-[11px] font-semibold text-terrain-800">
              {water_exclusion.fallback_used
                ? 'Fallback used &mdash; river exclusion not applied'
                : 'Water exclusion applied'}
            </p>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[11px]">
            <div className="flex justify-between gap-2">
              <span className="stat-label">Features found</span>
              <span className="font-mono text-terrain-800">{fmtInt(water_exclusion.features_found)}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="stat-label">Cells excluded</span>
              <span className="font-mono text-terrain-800">{fmtInt(water_exclusion.cells_excluded)}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="stat-label">Buffer</span>
              <span className="font-mono text-terrain-800">{water_exclusion.buffer_metres} m</span>
            </div>
            {water_exclusion.feature_types.length > 0 && (
              <div className="flex justify-between gap-2 col-span-2">
                <span className="stat-label">Feature types</span>
                <span className="text-terrain-800 text-right text-[11px]">{water_exclusion.feature_types.join(', ')}</span>
              </div>
            )}
          </div>
          {water_exclusion.error_message && (
            <p className="text-[11px] text-amber-700 italic">
              {water_exclusion.error_message}
            </p>
          )}
          {water_exclusion.fallback_used && (
            <p className="text-[10px] text-amber-600 italic">
              River exclusion was not applied. Candidates were not filtered based on proximity to mapped water features.
            </p>
          )}
        </div>

        {/* Catchment diagnostics */}
        <div className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500">
            Catchment Diagnostics
          </p>
          <div className="flex flex-wrap gap-1.5">
            <ValidationPill label="Outlet in catchment" ok={diagnostics.outlet_in_catchment} />
            <ValidationPill label="No duplicate cells" ok={diagnostics.no_duplicate_cells} />
            <ValidationPill label="Safe traversal" ok={diagnostics.traversal_terminated_safely} />
            <ValidationPill label="Flow accum. valid" ok={diagnostics.flow_accum_consistent} />
            <ValidationPill label="Area consistent" ok={diagnostics.area_consistent} />
            <ValidationPill label="Area within grid" ok={diagnostics.area_within_grid} />
          </div>
          <div className="text-[11px] text-terrain-400 grid grid-cols-2 gap-x-4">
            <span>Cells visited: <span className="font-mono">{fmtInt(diagnostics.cells_visited)}</span></span>
            <span>Max queue: <span className="font-mono">{fmtInt(diagnostics.max_queue_size)}</span></span>
            <span>Cells visited: <span className="font-mono">{fmtInt(diagnostics.cells_visited)}</span></span>
          </div>
        </div>
      </div>

      {/* ── G. Hydrology & Adequacy (Phase 12) ── */}
      <div className="card-elevated p-4 space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-terrain-700">
          G &middot; Hydrology &amp; Adequacy
        </h2>
        <p className="text-[10px] text-terrain-500 italic leading-snug">
          Catchment terrain, land cover, soil group, SCS-CN runoff, time of concentration, and pond adequacy.
          All values are computed by the backend and displayed read-only.
        </p>
        <HydrologyPanel result={result} />
      </div>

      {/* New Analysis */}
      <button
        onClick={onNewAnalysis}
        className="w-full py-2.5 rounded-xl border border-terrain-200 text-terrain-700 text-[13px] font-medium hover:bg-terrain-50 hover:border-terrain-300 active:scale-[0.98] transition-all"
      >
        Analyze another file
      </button>
    </div>
  );
}