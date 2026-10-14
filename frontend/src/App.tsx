import { useCallback, useEffect, useRef, useState } from 'react';
import { analyzeContour, analyzeLocation } from './lib/api';
import { ApiError, type IntegratedAnalysisResponse, type PondCandidateInfo } from './types/api';
import { fmtCoord } from './lib/utils';
import { Header } from './components/Header';
import { FileUpload } from './components/FileUpload';
import { AnalysisLoader } from './components/AnalysisLoader';
import { MapView } from './components/MapView';
import { ResultsPanel } from './components/ResultsPanel';
import { CandidateComparison } from './components/CandidateComparison';
import { EmptyState } from './components/EmptyState';
import { ErrorBanner } from './components/ErrorBanner';
import { InputModeSelector, type InputMode } from './components/InputModeSelector';
import { LocationSelector, type SelectedLocation } from './components/LocationSelector';
import { LocationControls, type LocationParams } from './components/LocationControls';
import { LocationSourceCard } from './components/LocationSourceCard';
import './App.css';

type AppPhase = 'idle' | 'busy' | 'running' | 'done';

const DEFAULT_LOCATION_PARAMS: LocationParams = {
  radiusKm: 1.0,
  contourIntervalM: 1.0,
  demType: 'COP30',
};

function App() {
  const [inputMode, setInputMode] = useState<InputMode>('location');

  // Upload state
  const [file, setFile] = useState<File | null>(null);

  // Location state
  const [selectedLocation, setSelectedLocation] = useState<SelectedLocation | null>(null);
  const [locationParams, setLocationParams] = useState<LocationParams>(DEFAULT_LOCATION_PARAMS);
  const [lastLocationParams, setLastLocationParams] = useState<LocationParams | null>(null);

  // Shared analysis state
  const [pendingRank, setPendingRank] = useState(1);
  const [selectedRank, setSelectedRank] = useState(1);
  const [phase, setPhase] = useState<AppPhase>('idle');
  const [result, setResult] = useState<IntegratedAnalysisResponse | null>(null);
  const [previous, setPrevious] = useState<IntegratedAnalysisResponse | null>(null);
  const [analyzingRank, setAnalyzingRank] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [startedAt, setStartedAt] = useState<number>(Date.now());
  const [showComparison, setShowComparison] = useState(true);
  const abortRef = useRef<AbortController | null>(null);

  const handleFileSelected = useCallback((f: File | null) => {
    setFile(f);
    setError(null);
    if (f) {
      setPhase('busy');
      setResult(null);
      setPrevious(null);
      setPendingRank(1);
      setSelectedRank(1);
      setAnalyzingRank(null);
    } else {
      setPhase('idle');
      setResult(null);
      setPrevious(null);
      setAnalyzingRank(null);
    }
  }, []);

  const handleModeChange = useCallback(
    (mode: InputMode) => {
      // If a request is in flight, let it finish; we just switch UI state.
      setInputMode(mode);
      // Do not clear existing results — preserve them.
    },
    [],
  );

  const runUploadAnalysis = useCallback(
    async (rankOverride?: number) => {
      if (!file) return;
      const rankToUse = rankOverride ?? pendingRank;

      setError(null);

      if (result) setPrevious(result);

      setPhase('running');
      setAnalyzingRank(rankToUse);
      setSelectedRank(rankToUse);
      setStartedAt(Date.now());

      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const data = await analyzeContour(file, {
          signal: controller.signal,
          pondRank: rankToUse,
        });
        setResult(data);
        setPendingRank(data.selected_pond.rank);
        setSelectedRank(data.selected_pond.rank);
        setPrevious(null);
        setPhase('done');
      } catch (err) {
        const apiErr =
          err instanceof ApiError
            ? err
            : new ApiError(0, err instanceof Error ? err.message : String(err));
        setError(apiErr);
        setPhase(result ? 'done' : 'busy');
        if (result) setPrevious(null);
      } finally {
        setAnalyzingRank(null);
        abortRef.current = null;
      }
    },
    [file, pendingRank, result],
  );

  const runLocationAnalysis = useCallback(
    async (rankOverride?: number) => {
      if (!selectedLocation) return;
      const rankToUse = rankOverride ?? pendingRank;
      const params = lastLocationParams ?? locationParams;

      setError(null);

      if (result) setPrevious(result);

      setPhase('running');
      setAnalyzingRank(rankToUse);
      setSelectedRank(rankToUse);
      setStartedAt(Date.now());

      // Remember parameters so candidate re-analysis uses the same terrain.
      setLastLocationParams(params);

      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const data = await analyzeLocation(
          selectedLocation.latitude,
          selectedLocation.longitude,
          params.radiusKm,
          params.contourIntervalM,
          params.demType,
          {
            signal: controller.signal,
            pondRank: rankToUse,
          },
        );
        setResult(data);
        setPendingRank(data.selected_pond.rank);
        setSelectedRank(data.selected_pond.rank);
        setPrevious(null);
        setPhase('done');
      } catch (err) {
        const apiErr =
          err instanceof ApiError
            ? err
            : new ApiError(0, err instanceof Error ? err.message : String(err));
        setError(apiErr);
        setPhase(result ? 'done' : 'busy');
        if (result) setPrevious(null);
      } finally {
        setAnalyzingRank(null);
        abortRef.current = null;
      }
    },
    [selectedLocation, locationParams, lastLocationParams, pendingRank, result],
  );

  const runAnalysis = useCallback(
    (rankOverride?: number) => {
      if (inputMode === 'location') {
        void runLocationAnalysis(rankOverride);
      } else {
        void runUploadAnalysis(rankOverride);
      }
    },
    [inputMode, runLocationAnalysis, runUploadAnalysis],
  );

  const cancelAnalysis = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  const startNew = useCallback(() => {
    setFile(null);
    setResult(null);
    setPrevious(null);
    setError(null);
    setPhase('idle');
    setPendingRank(1);
    setSelectedRank(1);
    setAnalyzingRank(null);
    setLastLocationParams(null);
    setSelectedLocation(null);
    setLocationParams(DEFAULT_LOCATION_PARAMS);
  }, []);

  // Auto-collapse the comparison panel on very small screens
  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth < 1100) setShowComparison(false);
    };
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // What is shown on the map right now: the latest successful result, or
  // (if available) the previously analysed result while a new request runs.
  const mapResult: IntegratedAnalysisResponse | null = result ?? previous;

  // Primary analyse button state for the active mode
  const canAnalyseUpload = !!file && phase !== 'running';
  const canAnalyseLocation = !!selectedLocation && phase !== 'running';

  return (
    <div className="h-screen flex flex-col bg-terrain-50">
      <Header />
      <main className="flex-1 flex min-h-0">
        {/* Left sidebar: input mode + controls */}
        <aside className="w-80 xl:w-80 border-r border-terrain-100 bg-white/60 backdrop-blur-sm shrink-0 overflow-y-auto p-4 space-y-4">
          <InputModeSelector mode={inputMode} onChange={handleModeChange} />

          {inputMode === 'location' ? (
            <>
              <LocationSelector
                selected={selectedLocation}
                onSelect={setSelectedLocation}
                disabled={phase === 'running'}
              />
              <LocationControls
                params={locationParams}
                onChange={setLocationParams}
                disabled={phase === 'running'}
              />

              <button
                onClick={() => runAnalysis()}
                disabled={!canAnalyseLocation}
                className={[
                  'w-full py-3 rounded-xl text-[14px] font-semibold transition-all',
                  !canAnalyseLocation
                    ? 'bg-terrain-100 text-terrain-400 cursor-not-allowed'
                    : 'bg-water-600 text-white hover:bg-water-700 active:scale-[0.98] shadow-lg shadow-water-200',
                ].join(' ')}
              >
                {phase === 'running' ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
                      <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" fill="none" />
                    </svg>
                    Analysing&hellip;
                  </span>
                ) : result
                  ? 'Re-analyze location'
                  : 'Analyze this location'}
              </button>

              {phase === 'running' && (
                <button
                  onClick={cancelAnalysis}
                  className="w-full py-2 rounded-xl border border-terrain-200 text-terrain-600 text-[12px] hover:bg-terrain-50 transition-colors"
                >
                  Cancel
                </button>
              )}

              {phase !== 'running' && !result && (
                <div className="text-[11px] text-terrain-500 leading-relaxed px-1 space-y-1">
                  <p className="font-semibold text-terrain-600">How it works</p>
                  <p>
                    The system retrieves elevation data, models the drainage network, and identifies
                    potential pond sites around the selected point.
                  </p>
                </div>
              )}
            </>
          ) : (
            <>
              <FileUpload file={file} onFileSelected={handleFileSelected} disabled={phase === 'running'} />

              <div className="card p-4 space-y-2">
                <label htmlFor="pond-rank" className="text-[11px] font-semibold uppercase tracking-[0.1em] text-terrain-700 block">
                  Initial Pond Candidate
                </label>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-terrain-500 shrink-0">Rank</span>
                  <input
                    id="pond-rank"
                    type="number"
                    min={1}
                    max={20}
                    value={pendingRank}
                    onChange={(e) => setPendingRank(Math.max(1, parseInt(e.target.value) || 1))}
                    disabled={phase === 'running'}
                    className="flex-1 rounded-lg border border-terrain-200 px-3 py-1.5 text-[13px] text-terrain-800 bg-terrain-50 focus:outline-none focus:ring-2 focus:ring-water-300 focus:border-water-400 disabled:opacity-50 disabled:cursor-not-allowed font-mono text-center"
                  />
                  <span className="text-[11px] text-terrain-500 shrink-0">1 = best</span>
                </div>
                <p className="text-[10px] text-terrain-400 leading-snug">
                  Choose which ranked pond candidate to analyse. Rank 1 is the highest-scoring location.
                  You can also switch candidates after the analysis finishes.
                </p>
              </div>

              <button
                onClick={() => runAnalysis()}
                disabled={!canAnalyseUpload}
                className={[
                  'w-full py-3 rounded-xl text-[14px] font-semibold transition-all',
                  !canAnalyseUpload
                    ? 'bg-terrain-100 text-terrain-400 cursor-not-allowed'
                    : 'bg-water-600 text-white hover:bg-water-700 active:scale-[0.98] shadow-lg shadow-water-200',
                ].join(' ')}
              >
                {phase === 'running' ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
                      <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" fill="none" />
                    </svg>
                    Analysing&hellip;
                  </span>
                ) : result
                  ? `Re-analyze rank ${pendingRank} catchment`
                  : `Analyze rank ${pendingRank}`}
              </button>

              {phase === 'running' && (
                <button
                  onClick={cancelAnalysis}
                  className="w-full py-2 rounded-xl border border-terrain-200 text-terrain-600 text-[12px] hover:bg-terrain-50 transition-colors"
                >
                  Cancel
                </button>
              )}

              {phase !== 'running' && (
                <div className="text-[11px] text-terrain-500 leading-relaxed px-1 space-y-1">
                  <p className="font-semibold text-terrain-600">What this does</p>
                  <p>
                    Reads contour lines, builds an elevation model, runs flow analysis,
                    selects the best pond locations, and delineates the upstream catchment of the chosen candidate.
                  </p>
                </div>
              )}
            </>
          )}
        </aside>

        {/* Center: map or empty state */}
        <section className="flex-1 relative min-w-0">
          {mapResult ? (
            <MapView
              result={mapResult}
              selectedRank={selectedRank}
              analyzingRank={analyzingRank}
              onSelectCandidate={(rank) => setSelectedRank(rank)}
            />
          ) : (
            <div className="h-full flex items-center justify-center bg-terrain-100">
              <EmptyState inputMode={inputMode} />
            </div>
          )}
          {phase === 'running' && (
            <AnalysisLoader
              filename={file?.name ?? null}
              startedAt={startedAt}
              mode={inputMode}
              locationLabel={
                selectedLocation
                  ? `${selectedLocation.latitude.toFixed(4)}, ${selectedLocation.longitude.toFixed(4)}`
                  : null
              }
            />
          )}
        </section>

        {/* Right sidebar: results / comparison */}
        <aside className="w-[380px] xl:w-[420px] border-l border-terrain-100 bg-white shrink-0 min-h-0 overflow-hidden">
          {result ? (
            <div className="h-full flex flex-col min-h-0">
              {/* Tab bar */}
              <div className="flex border-b border-terrain-100 px-2 pt-2 bg-white shrink-0">
                <button
                  type="button"
                  onClick={() => setShowComparison(true)}
                  className={[
                    'px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.08em] rounded-t-lg transition-colors',
                    showComparison
                      ? 'text-water-700 bg-water-50 border border-water-200 border-b-white'
                      : 'text-terrain-500 hover:text-terrain-700',
                  ].join(' ')}
                >
                  Compare
                </button>
                <button
                  type="button"
                  onClick={() => setShowComparison(false)}
                  className={[
                    'px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.08em] rounded-t-lg transition-colors',
                    !showComparison
                      ? 'text-water-700 bg-water-50 border border-water-200 border-b-white'
                      : 'text-terrain-500 hover:text-terrain-700',
                  ].join(' ')}
                >
                  Selected
                </button>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
                {showComparison ? (
                  <>
                    {result.source_info && (
                      <LocationSourceCard source={result.source_info} />
                    )}
                    <CandidateComparison
                      result={result}
                      selectedRank={selectedRank}
                      analyzingRank={analyzingRank}
                      onSelect={(rank) => setSelectedRank(rank)}
                      onAnalyze={(rank) => runAnalysis(rank)}
                    />
                    <SelectedPondSummaryInline result={result} rank={selectedRank} />
                  </>
                ) : (
                  <ResultsPanel result={result} onNewAnalysis={startNew} />
                )}
              </div>
            </div>
          ) : (
            <div className="h-full p-4 flex flex-col gap-3">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-terrain-700">Insights</h2>
              <div className="flex-1 flex items-center justify-center text-center">
                <p className="text-[12px] text-terrain-400 max-w-[200px]">
                  Analysis summary, catchment details, terrain metrics and validation checks will appear here.
                </p>
              </div>
            </div>
          )}
        </aside>
      </main>

      <ErrorBanner error={error} onDismiss={() => setError(null)} />
    </div>
  );
}

function SelectedPondSummaryInline({
  result,
  rank,
}: {
  result: IntegratedAnalysisResponse;
  rank: number;
}) {
  const candidate: PondCandidateInfo | undefined =
    rank === result.selected_pond.rank
      ? (result.selected_pond as unknown as PondCandidateInfo)
      : result.pond_candidates.find((c) => c.rank === rank);
  if (!candidate) return null;
  return (
    <div className="card-elevated p-3 space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-terrain-700">
          Selected Pond
        </h2>
        <span className="pill bg-water-100 text-water-800">Rank {candidate.rank}</span>
      </div>
      <div className="space-y-1 text-[12px]">
        <div className="flex justify-between gap-2">
          <span className="stat-label">Suitability</span>
          <span className="font-mono text-terrain-800">{candidate.suitability_score.toFixed(1)}/100</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="stat-label">Coordinates</span>
          <span className="font-mono text-terrain-800">{fmtCoord(candidate.lat, candidate.lon)}</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="stat-label">Elevation</span>
          <span className="font-mono text-terrain-800">{candidate.elevation_m.toFixed(1)} m</span>
        </div>
        <div className="flex justify-between gap-2">
          <span className="stat-label">Flow accum.</span>
          <span className="font-mono text-terrain-800">{candidate.flow_accumulation_cells.toLocaleString()} cells</span>
        </div>
      </div>
      <p className="text-[10px] text-terrain-400 italic pt-1">
        Switch to the &ldquo;Selected&rdquo; tab for the full terrain, catchment and validation breakdown.
      </p>
    </div>
  );
}

export default App;
