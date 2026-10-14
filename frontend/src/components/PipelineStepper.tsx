import { useEffect, useState } from 'react';

const UPLOAD_STAGES = [
  { id: 1, label: 'Parsing contour data', detail: 'Reading KML/KMZ & extracting lines' },
  { id: 2, label: 'Building terrain model', detail: 'IDW interpolation of elevation grid' },
  { id: 3, label: 'Running hydrological analysis', detail: 'Depression fill · D8 flow · accumulation' },
  { id: 4, label: 'Selecting the pond location', detail: 'Multi-factor suitability ranking' },
  { id: 5, label: 'Delineating the catchment', detail: 'Reverse-D8 upstream traversal' },
  { id: 6, label: 'Hydrology & pond adequacy', detail: 'Rainfall · SCS-CN · Tc · storage check' },
] as const;

const LOCATION_STAGES = [
  { id: 1, label: 'Acquiring elevation data', detail: 'Fetching DEM tiles around the location' },
  { id: 2, label: 'Generating contour model', detail: 'Extracting contours from the terrain' },
  { id: 3, label: 'Building terrain model', detail: 'IDW interpolation of elevation grid' },
  { id: 4, label: 'Analyzing drainage', detail: 'Depression fill · D8 flow · accumulation' },
  { id: 5, label: 'Finding pond locations', detail: 'Multi-factor suitability ranking' },
  { id: 6, label: 'Delineating catchment', detail: 'Reverse-D8 upstream traversal' },
  { id: 7, label: 'Hydrology & pond adequacy', detail: 'Rainfall · SCS-CN · Tc · storage check' },
] as const;

const STAGE_DURATION_MS = 8_000;

type Mode = 'upload' | 'location';

interface Props {
  mode?: Mode;
}

/**
 * Animated multi-stage pipeline indicator.
 * Stages cycle sequentially while the parent request is in flight.
 * The actual analysis is a single HTTP request; these are visual indicators only.
 */
export function PipelineStepper({ mode = 'upload' }: Props) {
  const [activeIndex, setActiveIndex] = useState(0);

  const stages = mode === 'location' ? LOCATION_STAGES : UPLOAD_STAGES;

  useEffect(() => {
    setActiveIndex(0);
    const interval = setInterval(() => {
      setActiveIndex((i) => (i + 1) % stages.length);
    }, STAGE_DURATION_MS);
    return () => clearInterval(interval);
  }, [stages.length]);

  return (
    <div className="space-y-2">
      {stages.map((stage, idx) => {
        const isActive = idx === activeIndex;
        const isDone = idx < activeIndex;
        return (
          <div
            key={stage.id}
            className={[
              'flex items-start gap-3 p-2.5 rounded-xl transition-all duration-500',
              isActive ? 'bg-water-50 ring-1 ring-water-200' : isDone ? 'bg-green-50/40' : 'bg-transparent',
            ].join(' ')}
          >
            <div className="shrink-0 mt-0.5">
              {isDone ? (
                <div className="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center">
                  <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
              ) : isActive ? (
                <div className="w-5 h-5 rounded-full bg-water-500 flex items-center justify-center">
                  <span className="block w-2 h-2 rounded-full bg-white animate-pulse" />
                </div>
              ) : (
                <div className="w-5 h-5 rounded-full border-2 border-terrain-200" />
              )}
            </div>
            <div className="flex-1 min-w-0">
              <p className={['text-[13px] font-medium transition-colors', isActive ? 'text-water-900' : isDone ? 'text-terrain-600' : 'text-terrain-400'].join(' ')}>
                {stage.label}
              </p>
              <p className={['text-[11px] transition-colors', isActive ? 'text-water-700' : 'text-terrain-400'].join(' ')}>
                {stage.detail}
              </p>
            </div>
          </div>
        );
      })}
      <p className="text-[10px] text-terrain-400 italic mt-2 px-2">
        Visual stages only — the backend runs the full pipeline in a single request.
      </p>
    </div>
  );
}
