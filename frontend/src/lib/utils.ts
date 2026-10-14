// Formatting and utility helpers.
import type { FactorScores } from '../types/api';

/** Format a number to a fixed number of decimal places, stripping trailing zeros. */
export function fmt(n: number, decimals = 2): string {
  return n.toFixed(decimals).replace(/\.?0+$/, '');
}

/** Format an area in m^2, automatically choosing the best unit. */
export function fmtArea(m2: number): string {
  if (m2 >= 1_000_000) return `${(m2 / 1_000_000).toFixed(3)} km²`;
  if (m2 >= 10_000) return `${(m2 / 10_000).toFixed(2)} ha`;
  return `${m2.toFixed(0)} m²`;
}

/** Format latitude/longitude to 5 decimal places. */
export function fmtCoord(lat: number, lon: number): string {
  return `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
}

/** Format a large integer with locale separators. */
export function fmtInt(n: number): string {
  return n.toLocaleString();
}

/** Format seconds as "Xm Ys". */
export function fmtDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

/** Return a CSS hex colour for the suitability score band. */
export function scoreColor(score: number): string {
  if (score >= 80) return '#16a34a'; // green-600
  if (score >= 50) return '#ca8a04'; // yellow-600
  return '#dc2626'; // red-600
}

/** Return Tailwind classes for the suitability score badge. */
export function scoreBgClass(score: number): string {
  if (score >= 80) return 'bg-green-100 text-green-800 ring-green-200';
  if (score >= 50) return 'bg-amber-100 text-amber-800 ring-amber-200';
  return 'bg-red-100 text-red-800 ring-red-200';
}

/** Format a file size in human-readable form. */
export function fmtFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Validate that a File looks like a KML or KMZ.
 * Returns a human-readable error message or null if valid.
 */
export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  if (!name.endsWith('.kml') && !name.endsWith('.kmz')) {
    return `"${file.name}" is not a .kml or .kmz file.`;
  }
  if (file.size === 0) {
    return 'The file is empty.';
  }
  return null;
}

/** Convert [lon, lat] pairs (backend format) to [lat, lon] (Leaflet format). */
export function lonLatToLatLon(coords: number[][]): [number, number][] {
  return coords.map(([lon, lat]) => [lat, lon]);
}

/** Convert a backend bounding_box object to Leaflet [[minLat, minLon], [maxLat, maxLon]] bounds. */
export function bboxToLeafletBounds(bb: {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
}): [[number, number], [number, number]] {
  return [
    [bb.min_lat, bb.min_lon],
    [bb.max_lat, bb.max_lon],
  ];
}

/** Format a number with locale separators and optional fixed decimals. */
export function fmtNumber(n: number, decimals = 0): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Format a storage volume as {m3, litres} strings. */
export function fmtVolume(m3: number): { m3: string; litres: string } {
  return {
    m3: m3 >= 1000 ? `${(m3 / 1000).toFixed(2)} × 10³ m³` : `${m3.toFixed(2)} m³`,
    litres: m3 > 0 ? `${(m3 * 1000).toLocaleString()} L` : '0 L',
  };
}

/** Format an elevation with 1 decimal place. */
export function fmtElevation(m: number): string {
  return `${m.toFixed(1)} m`;
}

/** Format a slope in degrees. */
export function fmtSlope(deg: number): string {
  return `${deg.toFixed(2)}°`;
}

/** Human-readable factor score label mapping. */
export const FACTOR_LABELS: Record<keyof FactorScores, string> = {
  accumulation: 'Flow Accumulation',
  low_slope: 'Flat Terrain',
  low_relative_elevation: 'Valley Position',
  drainage_concentration: 'Drainage Concentration',
};

/** Round a number for compact display in legend / map labels. */
export function fmtCompact(n: number): string {
  if (Math.abs(n) >= 1000) return n.toLocaleString();
  if (Math.abs(n) >= 10) return n.toFixed(1);
  return n.toFixed(2);
}
