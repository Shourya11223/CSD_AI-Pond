import { ApiError } from '../types/api';

interface Props {
  error: ApiError | null;
  onDismiss: () => void;
}

export function ErrorBanner({ error, onDismiss }: Props) {
  if (!error) return null;

  const isTimeout = error.status === 0;
  const isNotFound = error.status === 404;
  const isValidation = error.status === 422;
  const isBadFile = error.status === 400;
  const isServerError = error.status >= 500;

  // Detect DEM/terrain acquisition errors from detail message
  const detailLower = (error.detail || '').toLowerCase();
  const isDemError =
    detailLower.includes('opentopography') ||
    detailLower.includes('dem') ||
    detailLower.includes('elevation') ||
    detailLower.includes('geotiff') ||
    detailLower.includes('content type');

  let icon = '\u26a0';
  let title = 'Analysis Failed';
  let suggestion = 'Please check your KML/KMZ file and try again.';

  if (isTimeout) {
    icon = '\u23f1';
    title = 'Request Timed Out';
    suggestion = 'The analysis took longer than 15 minutes. The server may still be busy. Check that the backend is running, then try again.';
  } else if (isNotFound) {
    icon = '\uD83D\uDD0D';
    title = 'No Pond Candidates Found';
    suggestion = 'The terrain does not contain suitable locations for pond placement. The contour map may be too flat or too uniform.';
  } else if (isServerError || error.status === 502) {
    icon = '\uD83D\uDD27';
    title = 'Server Error';
    if (isDemError) {
      title = 'DEM Acquisition Error';
      suggestion =
        'Failed to download elevation data from OpenTopography. The service may be temporarily unavailable, or the API key may need verification. Check backend logs for details.';
    } else {
      suggestion = 'An internal error occurred on the server. Check the backend logs and restart if needed.';
    }
  } else if (isValidation) {
    icon = '\uD83D\uDCCB';
    title = 'Invalid Request';
    if (isDemError) {
      title = 'DEM Parameter Error';
      suggestion =
        'The location analysis parameters were invalid (e.g., coordinates out of range). Check the latitude, longitude, radius, and contour interval.';
    } else {
      suggestion = 'The request parameters were invalid. Check that the uploaded file is a valid KML or KMZ.';
    }
  } else if (isBadFile) {
    icon = '\uD83D\uDCC4';
    title = 'Invalid File';
    suggestion = 'The uploaded file could not be processed. Make sure it is a valid .kml or .kmz contour map.';
  }

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[1000] w-full max-w-lg px-4 animate-slide-up">
      <div className="bg-white border border-red-200 rounded-2xl shadow-2xl shadow-red-100 p-4">
        <div className="flex items-start gap-3">
          <span className="text-2xl leading-none mt-0.5 shrink-0" aria-hidden="true">{icon}</span>
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-red-800 text-sm">{title}</p>
            <p className="text-red-600 text-xs mt-1 break-words">{error.detail}</p>
            <p className="text-red-400 text-xs mt-1 italic">{suggestion}</p>
          </div>
          <button
            onClick={onDismiss}
            className="shrink-0 text-red-400 hover:text-red-600 transition-colors p-1 rounded-md hover:bg-red-50"
            aria-label="Dismiss error"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
