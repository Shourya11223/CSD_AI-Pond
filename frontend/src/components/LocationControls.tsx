import { useState } from 'react';

export interface LocationParams {
  radiusKm: number;
  contourIntervalM: number;
  demType: string;
}

interface Props {
  params: LocationParams;
  onChange: (params: LocationParams) => void;
  disabled?: boolean;
}

const RADIUS_OPTIONS = [
  { label: '0.5 km', value: 0.5 },
  { label: '1 km', value: 1.0 },
  { label: '2 km', value: 2.0 },
  { label: '5 km', value: 5.0 },
];

const DEM_OPTIONS = [
  { label: 'COP30', value: 'COP30', hint: '30 m Copernicus DEM' },
  { label: 'COP90', value: 'COP90', hint: '90 m Copernicus DEM' },
  { label: 'SRTMGL1', value: 'SRTMGL1', hint: '1 arc-second SRTM' },
  { label: 'SRTMGL3', value: 'SRTMGL3', hint: '3 arc-second SRTM' },
  { label: 'SRTMGL1_E', value: 'SRTMGL1_E', hint: 'SRTM void-filled' },
  { label: 'AW3D30', value: 'AW3D30', hint: 'ALOS World 3D 30 m' },
];

/**
 * Controls for analysis radius, contour interval, and DEM type.
 * Advanced settings are collapsed under a toggle.
 */
export function LocationControls({ params, onChange, disabled }: Props) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleRadiusChange = (value: number) => {
    onChange({ ...params, radiusKm: value });
  };

  const handleContourIntervalChange = (value: string) => {
    const v = parseFloat(value);
    if (!isNaN(v) && v > 0) {
      onChange({ ...params, contourIntervalM: v });
    }
  };

  const handleDemChange = (value: string) => {
    onChange({ ...params, demType: value });
  };

  return (
    <div className="card p-3 space-y-3">
      {/* Radius selector */}
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 block mb-2">
          Analysis radius
        </label>
        <div className="flex flex-wrap gap-1.5">
          {RADIUS_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => handleRadiusChange(opt.value)}
              disabled={disabled}
              className={[
                'px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all border',
                params.radiusKm === opt.value
                  ? 'bg-water-50 border-water-400 text-water-800 ring-1 ring-water-300'
                  : 'bg-white border-terrain-100 text-terrain-500 hover:border-water-200',
                disabled ? 'opacity-50 cursor-not-allowed' : '',
              ].join(' ')}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-terrain-400 mt-1.5 leading-snug">
          Radius controls the terrain area downloaded around the selected location.
        </p>
      </div>

      {/* Advanced settings toggle */}
      <button
        type="button"
        onClick={() => setShowAdvanced((s) => !s)}
        className="w-full flex items-center justify-between text-[11px] text-terrain-500 hover:text-water-600 transition-colors"
      >
        <span>Advanced terrain settings</span>
        <svg
          className={`w-4 h-4 transition-transform ${showAdvanced ? 'rotate-180' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Advanced settings */}
      {showAdvanced && (
        <div className="space-y-3 pt-1 border-t border-terrain-100">
          {/* Contour interval */}
          <div>
            <label htmlFor="contour-interval" className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 block mb-1">
              Contour interval
            </label>
            <div className="flex items-center gap-2">
              <input
                id="contour-interval"
                type="number"
                min={0.1}
                max={100}
                step={0.1}
                value={params.contourIntervalM}
                onChange={(e) => handleContourIntervalChange(e.target.value)}
                disabled={disabled}
                className="flex-1 rounded-lg border border-terrain-200 px-3 py-1.5 text-[13px] text-terrain-800 bg-white font-mono focus:outline-none focus:ring-2 focus:ring-water-300 focus:border-water-400 disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <span className="text-[11px] text-terrain-500">m</span>
            </div>
          </div>

          {/* DEM type */}
          <div>
            <label htmlFor="dem-type" className="text-[10px] font-semibold uppercase tracking-[0.08em] text-terrain-500 block mb-1">
              DEM source
            </label>
            <select
              id="dem-type"
              value={params.demType}
              onChange={(e) => handleDemChange(e.target.value)}
              disabled={disabled}
              className="w-full rounded-lg border border-terrain-200 px-3 py-1.5 text-[13px] text-terrain-800 bg-white focus:outline-none focus:ring-2 focus:ring-water-300 focus:border-water-400 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {DEM_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value} title={opt.hint}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="text-[10px] text-terrain-400 mt-1 leading-snug" title="DEM availability depends on region.">
              DEM availability depends on the selected region.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
