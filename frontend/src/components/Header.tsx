import { useEffect, useState } from 'react';

type Status = 'checking' | 'online' | 'offline';

export function Header() {
  const [status, setStatus] = useState<Status>('checking');

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        // Probe the root (always 200 if backend is up). 405 also proves
        // the backend is reachable; treat any response with a status
        // (i.e. not a network error) as "online".
        const resp = await fetch('/api/analyze-contour', { method: 'GET' });
        if (!cancelled) setStatus(resp.status > 0 ? 'online' : 'offline');
      } catch {
        if (!cancelled) setStatus('offline');
      }
    };
    check();
    const id = setInterval(check, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const dot =
    status === 'online' ? 'bg-green-500' :
    status === 'offline' ? 'bg-red-500' :
    'bg-amber-400 animate-pulse';
  const label =
    status === 'online' ? 'API online' :
    status === 'offline' ? 'API offline' :
    'Checking...';

  return (
    <header className="bg-white border-b border-terrain-100 px-5 py-3 flex items-center justify-between shrink-0 z-10">
      <div className="flex items-center gap-3">
        <svg width="32" height="32" viewBox="0 0 28 28" fill="none" aria-hidden="true">
          <path d="M14 3C14 3 6 12 6 17.5C6 21.6421 9.358 25 14 25C18.642 25 22 21.6421 22 17.5C22 12 14 3 14 3Z" fill="#1d6ef5" />
          <path d="M10 17C10 17 11 18.5 13 18.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" opacity="0.6" />
        </svg>
        <div className="leading-tight">
          <h1 className="font-semibold text-terrain-900 text-[15px] tracking-tight">
            AI Pond Catchment Analyzer
          </h1>
          <p className="text-[10.5px] text-terrain-500 mt-0.5">
            Terrain-driven pond placement and catchment delineation
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-[11px] font-mono text-terrain-400 hidden sm:inline">v1.0</span>
        <div className="h-4 w-px bg-terrain-100" />
        <div className="flex items-center gap-1.5" title={label}>
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${dot}`} />
          <span className="text-[11px] text-terrain-500">{label}</span>
        </div>
      </div>
    </header>
  );
}
