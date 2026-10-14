import type { LocationSourceInfo } from '../types/api';

interface Props {
  source: LocationSourceInfo;
}

/**
 * Displays source information for a location-based analysis.
 */
export function LocationSourceCard({ source }: Props) {
  return (
    <div className="card-elevated p-3 space-y-2">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-terrain-700">
        Input source
      </h2>
      <div className="text-[12px] text-terrain-700 space-y-1">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-water-500 shrink-0" />
          <span className="font-medium">Location</span>
        </div>
        <div className="pl-4 space-y-0.5">
          <div className="flex justify-between gap-2">
            <span className="stat-label">Latitude</span>
            <span className="font-mono text-terrain-800">{source.latitude.toFixed(5)}°</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="stat-label">Longitude</span>
            <span className="font-mono text-terrain-800">{source.longitude.toFixed(5)}°</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="stat-label">DEM</span>
            <span className="font-mono text-terrain-800">{source.dem_type}</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="stat-label">Radius</span>
            <span className="font-mono text-terrain-800">{source.radius_km} km</span>
          </div>
          <div className="flex justify-between gap-2">
            <span className="stat-label">Contour interval</span>
            <span className="font-mono text-terrain-800">{source.contour_interval_m} m</span>
          </div>
        </div>
      </div>
    </div>
  );
}
