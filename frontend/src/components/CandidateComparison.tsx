import { useState } from 'react';
import type { PondCandidateInfo, IntegratedAnalysisResponse } from '../types/api';
import { fmtCoord, fmtInt, scoreColor, FACTOR_LABELS } from '../lib/utils';

interface Props {
  result: IntegratedAnalysisResponse;
  selectedRank: number;
  analyzingRank: number | null;
  onSelect: (rank: number) => void;
  onAnalyze: (rank: number) => void;
}

export function CandidateComparison({
  result,
  selectedRank,
  analyzingRank,
  onSelect,
  onAnalyze,
}: Props) {
  const [expanded, setExpanded] = useState<number | null>(1);
  const candidates = result.pond_candidates;
  const total = candidates.length;

  if (total === 0) {
    return (
      <div className="card-elevated p-4 text-[12px] text-terrain-500">
        No pond candidates were returned by the backend.
      </div>
    );
  }

  return (
    <div className="card-elevated p-3 space-y-2">
      <div className="flex items-center justify-between px-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-terrain-700">
          Pond Candidates
        </h2>
        <span className="text-[10px] text-terrain-400 font-mono">
          {total} ranked
        </span>
      </div>

      <div className="space-y-1.5">
        {candidates.map((c) => (
          <CandidateRow
            key={c.rank}
            c={c}
            isSelected={c.rank === selectedRank}
            isAnalyzing={c.rank === analyzingRank}
            expanded={expanded === c.rank}
            onToggle={() => setExpanded(expanded === c.rank ? null : c.rank)}
            onSelect={() => onSelect(c.rank)}
            onAnalyze={() => onAnalyze(c.rank)}
          />
        ))}
      </div>

      <p className="text-[10px] text-terrain-400 leading-snug px-1 pt-1">
        Candidates excluded by the water-exclusion layer are not shown here.
      </p>
    </div>
  );
}

interface RowProps {
  c: PondCandidateInfo;
  isSelected: boolean;
  isAnalyzing: boolean;
  expanded: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onAnalyze: () => void;
}

function CandidateRow({
  c,
  isSelected,
  isAnalyzing,
  expanded,
  onToggle,
  onSelect,
  onAnalyze,
}: RowProps) {
  const rankBg =
    c.rank === 1 ? 'bg-water-600 text-white' :
    c.rank === 2 ? 'bg-water-500 text-white' :
    c.rank === 3 ? 'bg-water-400 text-white' :
    'bg-terrain-200 text-terrain-800';

  return (
    <div
      className={[
        'rounded-xl border transition-all',
        isSelected
          ? 'border-water-400 bg-water-50/40 ring-2 ring-water-400'
          : 'border-terrain-100 bg-white hover:border-water-200',
      ].join(' ')}
    >
      <button
        type="button"
        onClick={onSelect}
        className="w-full text-left px-3 py-2.5 flex items-start gap-3"
      >
        <div className={[
          'shrink-0 w-7 h-7 rounded-full flex items-center justify-center font-mono font-bold text-[12px] shadow-sm',
          rankBg,
        ].join(' ')}>
          {c.rank}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <span
                className="font-mono text-[12px] font-semibold tabular-nums"
                style={{ color: scoreColor(c.suitability_score) }}
              >
                {c.suitability_score.toFixed(1)}
              </span>
              <span className="text-[10px] text-terrain-400">/100</span>
              {isSelected && (
                <span className="text-[9px] uppercase tracking-[0.08em] text-water-700 font-semibold bg-water-100 rounded-full px-1.5 py-0.5">
                  selected
                </span>
              )}
              {isAnalyzing && (
                <span className="text-[9px] uppercase tracking-[0.08em] text-amber-700 font-semibold bg-amber-100 rounded-full px-1.5 py-0.5 animate-pulse">
                  analysing
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onToggle(); }}
              className="text-[10px] text-terrain-400 hover:text-terrain-700 w-5 h-5 rounded flex items-center justify-center"
              aria-label={expanded ? 'Collapse' : 'Expand'}
            >
              {expanded ? '−' : '+'}
            </button>
          </div>

          <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] font-mono text-terrain-600">
            <span>elev {c.elevation_m.toFixed(1)} m</span>
            <span>flow {fmtInt(c.flow_accumulation_cells)}</span>
          </div>
          <div className="text-[10px] text-terrain-400 font-mono truncate mt-0.5">
            {fmtCoord(c.lat, c.lon)}
          </div>
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-terrain-100/60 space-y-1.5">
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
            <div className="flex justify-between gap-2">
              <span className="stat-label">Slope</span>
              <span className="font-mono text-terrain-800">{c.local_slope_deg.toFixed(2)}°</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="stat-label">Rel. elev</span>
              <span className="font-mono text-terrain-800">{c.relative_elevation_m.toFixed(2)} m</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="stat-label">Row</span>
              <span className="font-mono text-terrain-800">{c.row}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="stat-label">Col</span>
              <span className="font-mono text-terrain-800">{c.col}</span>
            </div>
          </div>

          <div className="pt-1">
            <p className="text-[10px] uppercase tracking-[0.08em] text-terrain-500 font-semibold mb-1">
              Factor Scores
            </p>
            <div className="space-y-1">
              {(Object.keys(c.factor_scores) as (keyof typeof c.factor_scores)[]).map((k) => {
                const v = c.factor_scores[k];
                return (
                  <div key={k} className="flex items-center gap-2">
                    <span className="text-[10px] text-terrain-500 w-[100px] shrink-0">
                      {FACTOR_LABELS[k]}
                    </span>
                    <div className="flex-1 h-1.5 bg-terrain-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-water-500 rounded-full transition-all"
                        style={{ width: `${Math.min(100, Math.max(0, v))}%` }}
                      />
                    </div>
                    <span className="text-[10px] font-mono text-terrain-700 w-9 text-right tabular-nums">
                      {v.toFixed(0)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          <button
            type="button"
            onClick={onAnalyze}
            disabled={isAnalyzing}
            className={[
              'w-full mt-2 py-2 rounded-lg text-[12px] font-semibold transition-all',
              isAnalyzing
                ? 'bg-terrain-100 text-terrain-400 cursor-not-allowed'
                : 'bg-water-600 text-white hover:bg-water-700 active:scale-[0.98]',
            ].join(' ')}
          >
            {isAnalyzing ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
                  <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" fill="none" />
                </svg>
                Analysing this candidate&hellip;
              </span>
            ) : isSelected ? 'Re-analyze catchment' : 'Analyze this candidate'}
          </button>
        </div>
      )}
    </div>
  );
}