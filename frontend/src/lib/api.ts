import { ApiError, IntegratedAnalysisResponse, LocationAnalysisOptions } from '../types/api';

export interface AnalyzeOptions {
  pondRank?: number;
  gridCellSizeM?: number;
  signal?: AbortSignal;
}

export async function analyzeContour(
  file: File,
  opts: AnalyzeOptions = {},
): Promise<IntegratedAnalysisResponse> {
  const formData = new FormData();
  formData.append('file', file);

  if (opts.pondRank !== undefined) {
    formData.append('pond_rank', String(opts.pondRank));
  }
  if (opts.gridCellSizeM !== undefined) {
    formData.append('grid_cell_size_m', String(opts.gridCellSizeM));
  }

  const url = new URL('/api/analyze-contour', window.location.origin);
  if (opts.pondRank !== undefined) {
    url.searchParams.set('pond_rank', String(opts.pondRank));
  }

  const controller = new AbortController();
  // Long-running analysis can take several minutes; use a generous timeout.
  // 15 minutes (900_000 ms) allows complete processing without arbitrary
  // abortion, including when external providers (Overpass, Open-Meteo) are
  // slow to fail over.
  const timeoutId = setTimeout(() => controller.abort(), 900_000);

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(0, 'Request timed out after 15 minutes. The backend may still be processing.');
    }
    throw new ApiError(0, `Network error: ${err instanceof Error ? err.message : String(err)}`);
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // use the status-text fallback
    }
    throw new ApiError(response.status, detail);
  }

  const data: IntegratedAnalysisResponse = await response.json();
  return data;
}

export async function analyzeLocation(
  latitude: number,
  longitude: number,
  radiusKm: number,
  contourIntervalM: number,
  demType: string,
  opts: LocationAnalysisOptions = {},
): Promise<IntegratedAnalysisResponse> {
  const url = new URL('/api/analyze-location', window.location.origin);
  if (opts.pondRank !== undefined) {
    url.searchParams.set('pond_rank', String(opts.pondRank));
  }
  if (opts.gridCellSizeM !== undefined) {
    url.searchParams.set('grid_cell_size_m', String(opts.gridCellSizeM));
  }
  if (opts.idwPower !== undefined) {
    url.searchParams.set('idw_power', String(opts.idwPower));
  }
  if (opts.idwK !== undefined) {
    url.searchParams.set('idw_k', String(opts.idwK));
  }
  if (opts.idwEpsilon !== undefined) {
    url.searchParams.set('idw_epsilon', String(opts.idwEpsilon));
  }

  const body = {
    latitude,
    longitude,
    radius_km: radiusKm,
    contour_interval_m: contourIntervalM,
    dem_type: demType,
  };

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 180_000);

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: opts.signal ?? controller.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(0, 'Location analysis timed out after 3 minutes. The server may still be processing.');
    }
    throw new ApiError(0, `Network error: ${err instanceof Error ? err.message : String(err)}`);
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const json = (await response.json()) as { detail?: string };
      if (json.detail) detail = json.detail;
    } catch {
      // use the status-text fallback
    }

    if (response.status === 404) {
      throw new ApiError(response.status, 'No elevation data could be retrieved for this location.');
    } else if (response.status === 422) {
      throw new ApiError(response.status, detail || 'Invalid request parameters.');
    } else if (response.status === 400) {
      throw new ApiError(response.status, detail || 'Invalid request parameters.');
    }

    throw new ApiError(response.status, detail);
  }

  const data: IntegratedAnalysisResponse = await response.json();
  return data;
}
