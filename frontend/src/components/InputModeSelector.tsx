export type InputMode = 'location' | 'upload';

interface Props {
  mode: InputMode;
  onChange: (mode: InputMode) => void;
}

/**
 * Toggle between location-based analysis and KML/KMZ upload.
 * Provides a clean, integrated tab-like selector.
 */
export function InputModeSelector({ mode, onChange }: Props) {
  return (
    <div className="card p-3 space-y-2">
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-terrain-500">
        Terrain source
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onChange('location')}
          className={[
            'flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-[12px] font-medium transition-all border',
            mode === 'location'
              ? 'bg-water-50 border-water-400 text-water-800 ring-2 ring-water-300'
              : 'bg-white border-terrain-100 text-terrain-500 hover:border-water-200 hover:text-water-600',
          ].join(' ')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
            <circle cx="12" cy="10" r="3" />
          </svg>
          Select location
        </button>

        <button
          type="button"
          onClick={() => onChange('upload')}
          className={[
            'flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-[12px] font-medium transition-all border',
            mode === 'upload'
              ? 'bg-water-50 border-water-400 text-water-800 ring-2 ring-water-300'
              : 'bg-white border-terrain-100 text-terrain-500 hover:border-water-200 hover:text-water-600',
          ].join(' ')}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          Upload contours
        </button>
      </div>
    </div>
  );
}