/**
 * Shown when no analysis has been run yet.
 * Displays a gentle prompt describing the chosen input mode.
 */
interface Props {
  inputMode?: 'location' | 'upload';
}

export function EmptyState({ inputMode = 'upload' }: Props) {
  if (inputMode === 'location') {
    return (
      <div className="h-full flex flex-col items-center justify-center p-8 text-center space-y-4">
        <div className="w-16 h-16 rounded-2xl bg-water-50 border border-water-100 flex items-center justify-center">
          <svg
            width="36"
            height="36"
            viewBox="0 0 36 36"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <path
              d="M18 4C18 4 8 15 8 22C8 27.5228 12.4772 32 18 32C23.5228 32 28 27.5228 28 22C28 15 18 4 18 4Z"
              fill="#BFDBFE"
              stroke="#1D6EF5"
              strokeWidth="2"
            />
            <path
              d="M13 22C13 22 14.5 24 17 24"
              stroke="white"
              strokeWidth="1.5"
              strokeLinecap="round"
              opacity="0.7"
            />
          </svg>
        </div>
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-terrain-800">
            Find a pond location
          </h2>
          <p className="text-sm text-terrain-500 max-w-xs">
            Choose a point on the map or enter coordinates. The system will retrieve elevation data,
            model drainage, and identify potential pond sites.
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2 text-[11px] text-terrain-400">
          <span className="pill bg-terrain-50 border border-terrain-100">
            Click map to choose location
          </span>
          <span className="pill bg-terrain-50 border border-terrain-100">
            OpenStreetMap base
          </span>
          <span className="pill bg-terrain-50 border border-terrain-100">
            ~1 min processing
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col items-center justify-center p-8 text-center space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-water-50 border border-water-100 flex items-center justify-center">
        <svg
          width="36"
          height="36"
          viewBox="0 0 36 36"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden="true"
        >
          <path
            d="M18 4C18 4 8 15 8 22C8 27.5228 12.4772 32 18 32C23.5228 32 28 27.5228 28 22C28 15 18 4 18 4Z"
            fill="#BFDBFE"
            stroke="#1D6EF5"
            strokeWidth="2"
          />
          <path
            d="M13 22C13 22 14.5 24 17 24"
            stroke="white"
            strokeWidth="1.5"
            strokeLinecap="round"
            opacity="0.7"
          />
        </svg>
      </div>
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-terrain-800">
          No analysis yet
        </h2>
        <p className="text-sm text-terrain-500 max-w-xs">
          Upload a KML or KMZ contour map to find the best location for a pond and its upstream catchment.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2 text-[11px] text-terrain-400">
        <span className="pill bg-terrain-50 border border-terrain-100">
          KML / KMZ supported
        </span>
        <span className="pill bg-terrain-50 border border-terrain-100">
          OpenStreetMap base
        </span>
        <span className="pill bg-terrain-50 border border-terrain-100">
          ~45 s processing
        </span>
      </div>
      <p className="text-[11px] text-terrain-400 pt-2 max-w-xs">
        Already have contour data? Upload KML/KMZ instead.
      </p>
    </div>
  );
}
