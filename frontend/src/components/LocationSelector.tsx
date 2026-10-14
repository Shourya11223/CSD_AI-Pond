import { useState, useCallback } from 'react';
import { MapContainer, TileLayer, Marker, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

export interface SelectedLocation {
  latitude: number;
  longitude: number;
}

interface Props {
  selected: SelectedLocation | null;
  onSelect: (location: SelectedLocation) => void;
  disabled?: boolean;
  initialCenter?: [number, number];
}

function makeLocationIcon() {
  const html = `
    <div style="
      width: 28px; height: 28px;
      border-radius: 9999px;
      background: #ef4444;
      border: 3px solid white;
      box-shadow: 0 2px 8px rgba(0,0,0,0.4);
      display: flex; align-items: center; justify-content: center;
    ">
      <div style="
        width: 10px; height: 10px;
        border-radius: 9999px;
        background: white;
      "></div>
    </div>
  `;
  return L.divIcon({
    className: 'location-marker',
    html,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -16],
  });
}

interface InnerProps extends Props {
  initialCenter: [number, number];
}

function LocationMapClick({
  selected,
  onSelect,
  disabled,
}: InnerProps) {
  useMapEvents({
    click(e) {
      if (disabled) return;
      onSelect({ latitude: e.latlng.lat, longitude: e.latlng.lng });
    },
  });

  return (
    <>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {selected && (
        <Marker
          position={[selected.latitude, selected.longitude]}
          icon={makeLocationIcon()}
          interactive={false}
        />
      )}
    </>
  );
}

export function LocationSelector({
  selected,
  onSelect,
  disabled,
  initialCenter = [20.0, 82.0],
}: Props) {
  const [latInput, setLatInput] = useState('');
  const [lonInput, setLonInput] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);

  const handleCoordinateSubmit = useCallback(() => {
    setInputError(null);
    const lat = parseFloat(latInput);
    const lon = parseFloat(lonInput);

    if (isNaN(lat) || isNaN(lon)) {
      setInputError('Please enter valid numbers.');
      return;
    }
    if (lat < -90 || lat > 90) {
      setInputError('Latitude must be between -90 and 90.');
      return;
    }
    if (lon < -180 || lon > 180) {
      setInputError('Longitude must be between -180 and 180.');
      return;
    }

    onSelect({ latitude: lat, longitude: lon });
  }, [latInput, lonInput, onSelect]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleCoordinateSubmit();
  };

  return (
    <div className="space-y-3">
      <div className="relative rounded-xl overflow-hidden border border-terrain-200 h-48">
        <MapContainer
          center={selected ? [selected.latitude, selected.longitude] : initialCenter}
          zoom={selected ? 14 : 5}
          className="h-full w-full"
          zoomControl={true}
          scrollWheelZoom={true}
        >
          <LocationMapClick
            selected={selected}
            onSelect={onSelect}
            disabled={disabled}
            initialCenter={initialCenter}
          />
        </MapContainer>

        {!selected && !disabled && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="bg-white/90 backdrop-blur-sm rounded-lg px-3 py-1.5 text-[11px] text-terrain-600 shadow-sm">
              Click anywhere on the map to choose a location
            </div>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label htmlFor="loc-lat" className="text-[10px] font-medium text-terrain-500 block mb-1">
              Latitude
            </label>
            <input
              id="loc-lat"
              type="text"
              inputMode="decimal"
              placeholder="-90 to 90"
              value={latInput}
              onChange={(e) => setLatInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              className="w-full rounded-lg border border-terrain-200 px-3 py-1.5 text-[13px] text-terrain-800 bg-white font-mono focus:outline-none focus:ring-2 focus:ring-water-300 focus:border-water-400 disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>
          <div>
            <label htmlFor="loc-lon" className="text-[10px] font-medium text-terrain-500 block mb-1">
              Longitude
            </label>
            <input
              id="loc-lon"
              type="text"
              inputMode="decimal"
              placeholder="-180 to 180"
              value={lonInput}
              onChange={(e) => setLonInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={disabled}
              className="w-full rounded-lg border border-terrain-200 px-3 py-1.5 text-[13px] text-terrain-800 bg-white font-mono focus:outline-none focus:ring-2 focus:ring-water-300 focus:border-water-400 disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>
        </div>

        <button
          type="button"
          onClick={handleCoordinateSubmit}
          disabled={disabled || !latInput || !lonInput}
          className={[
            'w-full py-2 rounded-lg text-[12px] font-medium transition-all',
            disabled || !latInput || !lonInput
              ? 'bg-terrain-100 text-terrain-400 cursor-not-allowed'
              : 'bg-water-600 text-white hover:bg-water-700 active:scale-[0.98]',
          ].join(' ')}
        >
          Go to coordinates
        </button>

        {inputError && (
          <p className="text-[11px] text-red-600">{inputError}</p>
        )}
      </div>

      {selected && (
        <div className="bg-water-50 border border-water-200 rounded-xl p-3 space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-water-700">
            Selected location
          </p>
          <div className="font-mono text-[13px] text-terrain-800 space-y-0.5">
            <div>
              {selected.latitude >= 0
                ? `${selected.latitude.toFixed(5)}° N`
                : `${Math.abs(selected.latitude).toFixed(5)}° S`}
            </div>
            <div>
              {selected.longitude >= 0
                ? `${selected.longitude.toFixed(5)}° E`
                : `${Math.abs(selected.longitude).toFixed(5)}° W`}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
