import { useEffect, useState } from 'react';
import { PipelineStepper } from './PipelineStepper';

type Mode = 'upload' | 'location';

interface Props {
  filename: string | null;
  startedAt: number;
  mode?: Mode;
  locationLabel?: string | null;
}

/**
 * Full-overlay "the analysis is running" panel.
 * Shows the multi-stage stepper, elapsed timer, and a note that
 * the backend can take ~1 minute for a typical analysis.
 */
export function AnalysisLoader({ filename, startedAt, mode = 'upload', locationLabel }: Props) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 250);
    return () => clearInterval(id);
  }, [startedAt]);

  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;

  const title = mode === 'location' ? 'Building terrain analysis…' : 'Reading the terrain…';
  const note =
    mode === 'location'
      ? 'Location analysis can take around a minute.'
      : 'Processing typically takes 45–60 seconds for a typical KML.';

  return (
    <div className="absolute inset-0 bg-terrain-50/90 backdrop-blur-sm flex items-center justify-center z-[500] animate-fade-in">
      <div className="bg-white rounded-3xl shadow-2xl border border-terrain-100 max-w-md w-full mx-4 overflow-hidden">
        <div className="p-6 space-y-1">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-terrain-900">{title}</h2>
            <span className="font-mono text-[11px] text-terrain-500 tabular-nums">
              {m}:{s.toString().padStart(2, '0')}
            </span>
          </div>
          {mode === 'upload' && filename && (
            <p className="text-[11px] text-terrain-500 truncate">
              File: <span className="font-mono">{filename}</span>
            </p>
          )}
          {mode === 'location' && locationLabel && (
            <p className="text-[11px] text-terrain-500 truncate font-mono">
              {locationLabel}
            </p>
          )}
        </div>
        <div className="px-6 pb-6">
          <PipelineStepper mode={mode} />
        </div>
        <div className="border-t border-terrain-100 px-6 py-3 bg-terrain-50/50 flex items-center gap-2 text-[11px] text-terrain-500">
          <svg className="w-3.5 h-3.5 text-terrain-400 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
            <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" fill="none" />
          </svg>
          <span>{note}</span>
        </div>
      </div>
    </div>
  );
}
