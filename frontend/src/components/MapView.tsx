import { useEffect, useMemo } from 'react';
import { MapContainer, TileLayer, Marker, Polygon, Rectangle, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import type { IntegratedAnalysisResponse } from '../types/api';
import { bboxToLeafletBounds, lonLatToLatLon } from '../lib/utils';

/**
 * Build a divIcon for a candidate marker. Rank 1 is largest/most prominent;
 * the selected candidate is highlighted with a ring; others are smaller.
 */
function makeCandidateIcon(rank: number, isSelected: boolean, isAnalysed: boolean) {
  const fillColor =
    rank === 1 ? '#1d6ef5' :
    rank === 2 ? '#3689ff' :
    rank === 3 ? '#59a7ff' :
    '#7e7247';
  const size = rank === 1 ? 34 : 28;
  const ringWidth = isSelected ? 4 : 2;
  const ringColor = isSelected ? '#f59e0b' : 'white';
  const pulse = isAnalysed && !isSelected
    ? 'animation: pond-pulse 1.6s ease-in-out infinite;'
    : '';
  const html = `
    <div style="
      width: ${size}px; height: ${size}px; border-radius: 9999px;
      background: ${fillColor};
      border: ${ringWidth}px solid ${ringColor};
      box-shadow: 0 2px 8px rgba(38,33,21,0.35);
      display: flex; align-items: center; justify-content: center;
      color: white; font-family: 'JetBrains Mono', monospace; font-weight: 700;
      font-size: ${rank === 1 ? '14px' : '12px'};
      ${pulse}
    ">${rank}</div>
  `;
  return L.divIcon({
    className: 'pond-marker',
    html,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -size / 2],
  });
}

/**
 * Helper component that auto-fits the map to a set of bounds.
 * Must be a child of <MapContainer>.
 */
function FitBounds({ bounds }: { bounds: L.LatLngBoundsExpression | null }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17, animate: true });
    }
  }, [map, bounds]);
  return null;
}

interface Props {
  result: IntegratedAnalysisResponse;
  selectedRank: number;
  analyzingRank: number | null;
  onSelectCandidate: (rank: number) => void;
}

/**
 * Leaflet map showing all pond candidates, the catchment polygon, and
 * the bounding-box fallback. The currently selected candidate is highlighted
 * and the catchment belongs to the candidate that was analysed (selected_pond).
 */
export function MapView({ result, selectedRank, analyzingRank, onSelectCandidate }: Props) {
  const { boundary, selected_pond, pond_candidates } = result;
  const bb = boundary.bounding_box;

  // Convert [lon, lat] -> [lat, lon]
  const polygonPositions = useMemo<[number, number][]>(() => {
    if (!boundary.boundary_coordinates || boundary.boundary_coordinates.length < 3) {
      return [];
    }
    return lonLatToLatLon(boundary.boundary_coordinates);
  }, [boundary.boundary_coordinates]);

  // Compute a smart fit bounds that includes candidates + catchment boundary
  const bounds = useMemo<L.LatLngBoundsExpression | null>(() => {
    const latLngs: [number, number][] = [];

    if (polygonPositions.length >= 3) {
      latLngs.push(...polygonPositions);
    }

    if (bb.min_lat !== bb.max_lat && bb.min_lon !== bb.max_lon) {
      latLngs.push([bb.min_lat, bb.min_lon]);
      latLngs.push([bb.max_lat, bb.max_lon]);
    }

    for (const c of pond_candidates) {
      if (Number.isFinite(c.lat) && Number.isFinite(c.lon)) {
        latLngs.push([c.lat, c.lon]);
      }
    }

    if (latLngs.length >= 2) {
      // Deduplicate exact matches and find min/max
      let minLat = Infinity, minLon = Infinity, maxLat = -Infinity, maxLon = -Infinity;
      for (const [la, lo] of latLngs) {
        if (la < minLat) minLat = la;
        if (la > maxLat) maxLat = la;
        if (lo < minLon) minLon = lo;
        if (lo > maxLon) maxLon = lo;
      }
      if (minLat === maxLat || minLon === maxLon) {
        // Add a tiny pad for single-point selections
        const pad = 0.0005;
        minLat -= pad; maxLat += pad; minLon -= pad; maxLon += pad;
      }
      return [
        [minLat, minLon],
        [maxLat, maxLon],
      ] as L.LatLngBoundsExpression;
    }
    return null;
  }, [polygonPositions, bb, pond_candidates]);

  // Initial center: prefer selected pond, fall back to bbox centroid
  const center: [number, number] =
    selected_pond && Number.isFinite(selected_pond.lat) && Number.isFinite(selected_pond.lon)
      ? [selected_pond.lat, selected_pond.lon]
      : [(bb.min_lat + bb.max_lat) / 2, (bb.min_lon + bb.max_lon) / 2];

  const hasEmptyBoundary = polygonPositions.length < 3;
  const hasWaterExclusionIssue =
    result.water_exclusion && result.water_exclusion.fallback_used;

  return (
    <div className="relative h-full w-full animate-fade-in">
      {hasEmptyBoundary && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-[400] bg-amber-50 border border-amber-200 rounded-xl px-3 py-1.5 text-[11px] text-amber-800 shadow-sm">
          ⚠ Catchment boundary unavailable — showing the recommended pond and all candidates.
        </div>
      )}

      <MapContainer
        center={center}
        zoom={14}
        scrollWheelZoom
        className="h-full w-full"
        style={{ background: '#ede9df' }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />

        {/* Catchment polygon for the analysed candidate */}
        {!hasEmptyBoundary && (
          <Polygon
            positions={polygonPositions}
            pathOptions={{
              color: '#1d6ef5',
              weight: 2,
              opacity: 0.9,
              fillColor: '#3689ff',
              fillOpacity: 0.18,
            }}
          >
            <Popup>
              <div className="font-medium text-terrain-900">
                Catchment &middot; Rank {selected_pond.rank}
              </div>
              <div className="text-[11px] text-terrain-500 mt-1">
                {result.catchment_cells.toLocaleString()} cells
                &middot; {result.catchment_area_ha.toFixed(2)} ha
              </div>
            </Popup>
          </Polygon>
        )}

        {/* Bounding-box fallback when polygon is unavailable */}
        {hasEmptyBoundary && bb.min_lat !== bb.max_lat && (
          <Rectangle
            bounds={bboxToLeafletBounds(bb)}
            pathOptions={{
              color: '#1d6ef5',
              weight: 1.5,
              dashArray: '6 4',
              fillColor: '#3689ff',
              fillOpacity: 0.06,
            }}
          />
        )}

        {/* All pond candidate markers */}
        {pond_candidates.map((c) => {
          if (!Number.isFinite(c.lat) || !Number.isFinite(c.lon)) return null;
          const isSelected = c.rank === selectedRank;
          const isAnalysed = c.rank === result.selected_pond.rank;
          const icon = makeCandidateIcon(c.rank, isSelected, isAnalysed);
          return (
            <Marker
              key={c.rank}
              position={[c.lat, c.lon]}
              icon={icon}
              zIndexOffset={isSelected ? 1000 : c.rank === 1 ? 500 : 0}
              eventHandlers={{
                click: () => onSelectCandidate(c.rank),
              }}
            >
              <Popup>
                <div className="space-y-1">
                  <div className="font-semibold text-terrain-900 text-[13px]">
                    Rank {c.rank} &middot; Pond Candidate
                  </div>
                  <div className="font-mono text-[11px] text-terrain-600">
                    {c.lat.toFixed(5)}, {c.lon.toFixed(5)}
                  </div>
                  <div className="text-[11px] text-terrain-500">
                    Suitability: <span className="font-mono">{c.suitability_score.toFixed(1)}/100</span>
                  </div>
                  <div className="text-[11px] text-terrain-500">
                    Elevation: <span className="font-mono">{c.elevation_m.toFixed(1)} m</span>
                  </div>
                  <div className="text-[11px] text-terrain-500">
                    Flow accum.: <span className="font-mono">{c.flow_accumulation_cells.toLocaleString()}</span>
                  </div>
                  {isAnalysed && (
                    <div className="text-[10px] text-water-700 font-semibold mt-1">
                      Currently analysed
                    </div>
                  )}
                </div>
              </Popup>
            </Marker>
          );
        })}

        <FitBounds bounds={bounds} />
      </MapContainer>

      {/* Map legend */}
      <div className="absolute bottom-4 right-4 z-[400] bg-white/95 backdrop-blur-sm rounded-xl shadow-lg border border-terrain-100 px-3 py-2.5 text-[11px] max-w-[220px]">
        <p className="font-semibold text-terrain-800 uppercase tracking-[0.08em] text-[10px] mb-1.5">
          Map Legend
        </p>
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full bg-water-600 border-2 border-white shadow-sm" />
            <span className="text-terrain-700">Rank 1 &middot; top candidate</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full bg-water-400 border-2 border-white shadow-sm" />
            <span className="text-terrain-700">Rank 2&ndash;3</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full bg-terrain-500 border-2 border-white shadow-sm" />
            <span className="text-terrain-700">Other candidates</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block w-3 h-3 rounded-full bg-water-600 border-[3px] border-amber-500 shadow-sm" />
            <span className="text-terrain-700">Selected on map</span>
          </div>
          <div className="flex items-center gap-2 pt-1 border-t border-terrain-100">
            <span className="inline-block w-3 h-2 bg-water-500/40 border border-water-600" />
            <span className="text-terrain-700">Catchment polygon</span>
          </div>
          {hasWaterExclusionIssue && (
            <div className="flex items-center gap-2 pt-1 border-t border-terrain-100">
              <span className="inline-block w-3 h-2 border border-amber-400 border-dashed bg-amber-50" />
              <span className="text-amber-700">Fallback bbox used</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}