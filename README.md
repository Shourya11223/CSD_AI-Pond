# AI-Based Village Pond Planning System

A FastAPI + React system that turns contour data for a village-scale area into an
evidence-based pond-siting recommendation: it builds an elevation model from contour
lines, models the drainage network, ranks the best pond locations, delineates the
upstream catchment of the chosen pond, estimates the pond's depth and storage volume,
and attaches a climate / hydrology diagnostic layer (rainfall, design rainfall, land
cover, soil, SCS-CN runoff, time of concentration, pond adequacy).

Developed in numbered "Phases" (1–12). Every phase that needs an external dataset has an
explicit **graceful-degradation** path, and one phase (soil / HSG) is a deliberate,
honest **"unavailable"** stub rather than a fabricated dataset.

---

## 1. Problem statement

Village-scale rainwater harvesting requires a defensible answer to a simple question:
*where should a pond go, and how much water can it hold?* Doing this by eye is
error-prone, and professional GIS/engineering tooling (ArcGIS, HEC-HMS, full IDF
studies) is expensive and requires data that a village-scale project rarely has.

The raw data that *is* commonly available for Indian villages is a **contour map**
(KML/KMZ exported from a survey or a DEM). This project is built around that reality: it
takes contour data alone and derives the whole chain of terrain → drainage → pond siting
→ catchment → storage, augmenting it with free, keyless open data (OpenStreetMap,
Open-Meteo) where useful.

## 2. Objective

1. Recover a usable Digital Elevation Model (DEM) from contour lines.
2. Delineate the drainage network (depressions, flow directions, accumulation).
3. Rank candidate pond locations with a transparent, explainable scoring method.
4. Delineate the upstream catchment that feeds the selected pond.
5. Estimate the pond's terrain-derived depth and storage volume.
6. Attach climate / hydrology context (rainfall, design rainfall, land cover, soil,
   runoff, time of concentration, adequacy) **without fabricating unavailable data**.
7. Keep every stage independently testable, tunable, and explainable in a viva.

---

## 3. Workflow at a glance

```
Input (KML/KMZ upload  OR  pick a location + radius)
        │
        ▼
[1] Contour parsing            contour_parser.py
        │  List[ContourLine]
        ▼
[2] IDW terrain model (DEM)    terrain_model.py
        │  regular elevation grid + projection metadata
        ▼
[3] Hydrology                  hydrology.py
        │  Priority-Flood fill → D8 flow direction → flow accumulation
        ▼
[4] Water exclusion (OSM)      water_exclusion.py   (graceful fallback)
        │  boolean "existing water" mask
        ▼
[5] Pond candidate ranking     pond_selection.py
        │  4-factor percentile score + non-maximum suppression
        ▼
[6] Catchment delineation      catchment.py
        │  reverse-D8 BFS from the outlet (+ convex-hull boundary)
        ▼
[7] Pond capacity              pond_capacity.py
        │  spill/rim depth + trapezoidal volume integration
        ▼
[8–11] Climate / hydrology    rainfall, weather, design_rainfall,
        diagnostics           land_cover, soil_group, scs_cn,
        │                      time_of_concentration, pond_adequacy
        ▼
Integrated JSON response (also rendered in the React frontend)
```

**Canonical stage numbering** (used throughout this document):

| Stage | Name | Module |
|-------|------|--------|
| 1 | Contour parsing | `contour_parser.py` |
| 2 | Terrain / DEM | `terrain_model.py` |
| 3 | Hydrology | `hydrology.py` |
| 4 | Water exclusion | `water_exclusion.py` |
| 5 | Pond candidate selection | `pond_selection.py` |
| 6 | Catchment delineation | `catchment.py` |
| 7 | Pond capacity | `pond_capacity.py` |
| 8–11 | Climate / hydrology diagnostics | `rainfall.py`, `weather.py`, `design_rainfall.py`, `land_cover.py`, `soil_group.py`, `scs_cn.py`, `time_of_concentration.py`, `pond_adequacy.py`, `catchment_diagnostics.py` |

**Stages 1–7 execute together only in the integrated endpoints**
(`POST /api/analyze-contour`, `POST /api/analyze-location`). The standalone endpoints
expose the pipeline only up to a chosen stage (see §12); in particular, **Stage 4
(water exclusion) is wired only into the integrated endpoints**, and `/api/find-pond-candidates`
ranks candidates without it.

Stages 8–11 are **additive**: each provider is wrapped in its own try/except and simply
returns `null` / `data_available: false` if it cannot run, so a failure never breaks the
core analysis.

---

## 4. Architecture

- **Backend** — a FastAPI app (`backend/main.py`) exposing an `APIRouter`
  (`backend/api/routes.py`). All heavy lifting lives in `backend/services/`, one module
  per concern. Pydantic v2 models in `backend/models/__init__.py` are the API contract.
- **Frontend** — a React 18 + TypeScript single-page app (Vite) that uploads a contour
  file or picks a location, calls the API, and renders the candidates, catchment, map
  and every diagnostic panel. It performs **no modelling of its own**: every displayed
  number comes read-only from the backend response.
- **Data flow** — the backend is stateless. A request carries either an uploaded contour
  file or a location + radius; the response is a single JSON document mirroring
  `IntegratedAnalysisResponse` (also mirrored in `frontend/src/types/api.ts`).

---

## 5. Tech stack

| Layer     | Technology |
|-----------|------------|
| Backend   | Python, FastAPI, Uvicorn, Pydantic v2, NumPy, SciPy (`cKDTree`, `uniform_filter`, `ConvexHull`, `ndimage`), lxml, `requests`, `python-dotenv` |
| External  | OpenStreetMap Overpass API (water + land cover), Open-Meteo (historical rainfall, current weather, design rainfall), OpenTopography (DEM download), `gdal_contour` CLI (location mode) |
| Frontend  | React 18, TypeScript 5, Vite 5, Tailwind CSS 3, Leaflet + react-leaflet |
| Data      | Contour KML/KMZ files, GeoTIFF DEMs (location mode) |
| Testing   | pytest (553 tests) + FastAPI `TestClient` |

---

## 6. Repository structure

```
AI-Pond/
├── README.md
├── sample_data/
│   └── contours_1m.kml            # example 1 m contour map (6.7 MB, 1355 contours)
├── backend/
│   ├── main.py                    # FastAPI app, CORS, health check
│   ├── requirements.txt
│   ├── .env                       # OPTIONAL, git-ignored (OPENTOPOGRAPHY_API_KEY)
│   ├── api/
│   │   └── routes.py              # ALL HTTP endpoints + pipeline orchestration
│   ├── models/
│   │   └── __init__.py            # Pydantic request/response models (API contract)
│   ├── services/
│   │   ├── contour_parser.py            # Stage 1  KML/KMZ -> ContourLine
│   │   ├── terrain_model.py             # Stage 2  IDW interpolation -> DEM grid
│   │   ├── hydrology.py                 # Stage 3  Priority-Flood, D8, accumulation
│   │   ├── water_exclusion.py           # Stage 4  OSM/Overpass existing-water mask
│   │   ├── pond_selection.py            # Stage 5  multi-factor candidate ranking
│   │   ├── catchment.py                 # Stage 6  reverse-D8 catchment + boundary
│   │   ├── pond_capacity.py             # Stage 7  trapezoidal depth/volume
│   │   ├── overpass_client.py           # Resilient multi-endpoint Overpass client
│   │   ├── dem_acquisition.py           # OpenTopography DEM download (location mode)
│   │   ├── contour_generation.py        # gdal_contour -> ContourLine (location mode)
│   │   ├── rainfall.py                  # Historical rainfall (Open-Meteo ERA5)
│   │   ├── weather.py                   # Current weather (Open-Meteo)
│   │   ├── design_rainfall.py           # Gumbel design rainfall (Phase 9)
│   │   ├── land_cover.py                # OSM land-cover fractions (Phase 11B-1)
│   │   ├── soil_group.py                # HSG lookup (STUB: unavailable) (11B-2)
│   │   ├── scs_cn.py                    # SCS Curve Number runoff (11B-3)
│   │   ├── time_of_concentration.py     # Kirpich Tc (11B-4)
│   │   ├── pond_adequacy.py             # Storage vs runoff ratio (11B-5)
│   │   └── catchment_diagnostics.py     # Catchment slope/elevation/flow-path (11A)
│   └── tests/                     # pytest suite + conftest.py
└── frontend/
    ├── package.json               # React 18, Vite 5, Leaflet, Tailwind
    ├── vite.config.ts             # dev server :5173, /api proxied to :8000
    └── src/
        ├── App.tsx                # top-level state machine + layout
        ├── lib/api.ts             # fetch wrappers for the endpoints
        ├── types/api.ts           # TS mirror of the backend response models
        └── components/            # Header, FileUpload, MapView, ResultsPanel, ...
```

---

## 7. Installation

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Optional, for **location mode** only (DEM download):

```bash
# OpenTopography API key -> backend/.env  (git-ignored)
echo "OPENTOPOGRAPHY_API_KEY=your_key_here" > backend/.env
# Location mode also needs the GDAL contour CLI:
sudo apt install gdal-bin
```

### Frontend

```bash
cd frontend
npm install
```

### Environment variables

| Variable | Required for | Notes |
|----------|--------------|-------|
| `OPENTOPOGRAPHY_API_KEY` | `POST /api/analyze-location` only | Loaded from `backend/.env` or the shell. Every other endpoint works without it. |

OpenStreetMap (Overpass) and Open-Meteo need **no** API key.

---

## 8. Running instructions

### Backend

```bash
cd backend
python3 main.py                 # serves on http://0.0.0.0:8000
# or: python3 -m uvicorn main:app --reload
```

Interactive API docs: `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm run dev                     # serves on http://0.0.0.0:5173, proxies /api -> :8000
# production build:
npm run build                   # tsc + vite build -> frontend/dist
```

Open `http://localhost:5173`. The Vite dev server proxies every `/api/*` call to the
backend on port 8000, so **both must be running** for the app to work.

---

## 9. The two input modes

Both modes produce the same internal `List[ContourLine]`, so every downstream stage is
shared.

### Mode A — Upload a contour file (`POST /api/analyze-contour`)
Accepts `.kml` or `.kmz`. For each Placemark the parser extracts elevation from
(`ExtendedData`/`SchemaData` → `description` → `name`) using numeric-token heuristics
that reject suspicious values (4-digit years, `> 100000`, `< -1000`). Coordinates are
read from `LineString`, `MultiLineString` and nested `MultiGeometry`. Lat/lon are
range-validated.

### Mode B — Pick a location (`POST /api/analyze-location`, Phase 5)
The caller supplies `latitude`, `longitude`, `radius_km` (default 1, max 10),
`contour_interval_m` (default 1) and `dem_type` (default `COP30`). The backend:
1. converts radius → bounding box (equirectangular `radius_to_bounds`),
2. downloads a GeoTIFF DEM from OpenTopography (`download_dem`),
3. runs `gdal_contour -a elevation -i <interval>` to produce contours
   (`generate_contours`),
4. deletes the temporary DEM/GeoJSON and feeds the contours into the shared pipeline.

The response additionally carries a `source_info` block describing the download.

---

## 10. The core pipeline — algorithms & formulas

### Stage 1 — Parse contours (`contour_parser.py`)
KMZ is unzipped (preferring `doc.kml`, with a deterministic fallback). Output is a list
of `ContourLine{elevation, points[(lon, lat)]}`.

### Stage 2 — Terrain model / DEM (`terrain_model.py`)
Builds a regular elevation grid from the contour points with **k-nearest-neighbour
Inverse Distance Weighting (IDW)**:

1. **Local equirectangular projection** centred on the data extent:
   `x = (lon − center_lon)·m_per_deg_lon`, `y = (lat − center_lat)·111320`,
   with `m_per_deg_lon = 111320·cos(center_lat)`.
2. **Spatial thinning** — at most one point per cell, keeping the point closest to the
   cell centre (ties broken by input order), cell size `max(grid_cell_size_m, 5 m)`.
   The implementation is a vectorised `lexsort`, i.e. O(N log N).
3. **Grid** — cell size default **10 m** for the integrated endpoints and
   `find-pond-candidates` / `delineate-catchment`; **5 m** for the standalone
   `build-terrain` / `analyze-hydrology`. The grid auto-coarsens if `W·H > 200,000`.
4. **IDW** via `scipy.spatial.cKDTree`: for each cell, take the `k` nearest samples
   (default `k = 12`) and compute

   ```
   w_i = 1 / (d_i^power + epsilon)          power = 2, epsilon = 1e-6
   z   = Σ (w_i · z_i) / Σ w_i
   ```

5. Projection metadata (`projection_info`) stores the grid origin + geographic extent so
   `(row, col) ↔ (lat, lon)` round-trips exactly. Convention: **row 0 = south edge**,
   **col 0 = west edge**.

### Stage 3 — Hydrology (`hydrology.py`)

1. **Priority-Flood depression filling** (Barnes et al. 2014): seed a min-heap with every
   grid-boundary cell, then repeatedly pop the lowest spill cell and visit unvisited
   neighbours; any neighbour at or below the spill level is raised to
   `spill + epsilon` (`epsilon ≈ float32 ULP`). This yields the minimal modification such
   that every cell drains monotonically to the boundary. Modified-cell count and
   adjustment statistics are recorded.
2. **D8 flow direction**: each interior cell points to the steepest positive downhill
   neighbour, with gradient `(z − z_neighbour) / distance` and
   `distance = cell_size` (cardinal) or `cell_size·√2` (diagonal). Encoding is
   compass-rose: `1=E, 2=SE, 3=S, 4=SW, 5=W, 6=NW, 7=N, 8=NE`, `0 = no outflow`.
3. **Flow accumulation**: each cell's `indegree` (upstream neighbours) and downstream
   target are built, then a Kahn-style topological pass from the headwaters adds each
   cell's contribution downstream — O(N) and cycle-safe. Produces upstream cell count and
   contributing area (m²).

Optional **diagnostics** (`compute_diagnostics`) report the adjustment distribution
(mean/median/p95/max, threshold counts), original-vs-filled elevation stats and
boundary-outlet behaviour.

### Stage 4 — Water exclusion (`water_exclusion.py`)
Queries Overpass for `waterway` / `natural` / `landuse` water features inside the DEM
bbox, rasterises them into a boolean grid aligned with the DEM and applies a **30 m
buffer**. Candidates inside the mask are rejected before ranking. If Overpass is
unavailable the stage degrades to "no exclusion" (`applied: false, fallback_used: true`)
and the pipeline continues. This stage runs only in the integrated endpoints; the
standalone `/api/find-pond-candidates` skips it.

> Note: the mask rasteriser evaluates every DEM cell against every relevant feature, so
> it is O(features × cells) — fine for village grids, see §20.

### Stage 5 — Pond candidate selection (`pond_selection.py`)
Scores every interior cell on **four factors**, each converted to a **percentile rank in
[0, 100] computed over interior cells only** (so it adapts to any map size with no
hard-coded thresholds):

| Factor | Meaning | Source |
|--------|---------|--------|
| `accumulation` | Higher flow accumulation = larger upstream catchment | flow-accumulation grid |
| `low_slope` | Flatter terrain is better (inverse-slope percentile) | `np.gradient` on the **original** DEM |
| `low_relative_elevation` | Lower than the local neighbourhood = valley (inverse of `dem − box_mean`) | **original** DEM (`scipy.ndimage.uniform_filter`) |
| `drainage_concentration` | Accumulation percentile + a small bonus (±5) if on a D8 flow path | flow-dir + accumulation |

**Composite suitability** (weights normalised to sum to 1):

```
composite = 0.30·accumulation
          + 0.25·low_slope
          + 0.25·low_relative_elevation
          + 0.20·drainage_concentration
```

Then:
- **Boundary exclusion** — drop cells within a margin (default `2 × cell_size`) of the
  artificial DEM edge.
- **Non-maximum suppression** with a Chebyshev radius of 5 cells (50 m at 10 m cells) so
  returned candidates are spatially distinct.
- Return the top **3–5** ranked candidates, each with its factor scores, elevation,
  slope, relative elevation, flow accumulation and lat/lon.

The **original (un-filled) DEM** is used for slope and relative elevation so pond sites
reflect natural terrain rather than the depression-filled surface.

### Stage 6 — Catchment delineation (`catchment.py`)
**Reverse-D8 BFS** from the selected pond outlet: a neighbour belongs to the catchment if
its D8 arrow points directly into the current cell (each cell visited once). Produces:
- catchment mask, cell count, area in m² / ha / km², % of grid,
- flow accumulation at the outlet and a consistency check (`flow_accum == cells`),
- a **convex-hull boundary** (SciPy `ConvexHull`) in `[lon, lat]` for map display
  (falls back to boundary-cell centroids, then empty),
- validation diagnostics (outlet in catchment, no duplicate cells, safe termination,
  area consistency, area within grid).

### Stage 7 — Pond capacity (`pond_capacity.py`)
Terrain-derived depth and storage for the selected candidate, computed on the original
DEM:
- **Spill/rim elevation** = the `spill_percentile` (default **25th**) of neighbour cells
  that are higher than the candidate within a **3-cell** neighbourhood.
- `max_depth = spill − candidate`  (natural basin containment depth)
- `usable_depth = max(0, max_depth − 0.5 m freeboard)`
- **Volume** = trapezoidal integration over `20` elevation slices; each slice 8-connected
  flood-fills from the candidate to obtain its inundated area, then

  ```
  V = Σ ((A_i + A_{i+1}) / 2) · (z_{i+1} − z_i)
  ```

- Reports surface area at design level, volume (m³ and litres), assumptions, and warnings
  (e.g. flat terrain → zero usable depth → zero volume, with an explicit early return).

---

## 11. Stages 8–11 — Climate / hydrology diagnostics

Optional, additive fields on the integrated response (they run after Stages 1–7 and are
not exposed by the standalone endpoints). Each is wrapped in try/except and degrades to
`null` / `data_available: false`.

| Field | Module | What it does |
|-------|--------|--------------|
| `rainfall` | `rainfall.py` | Historical rainfall from the Open-Meteo ERA5 archive (annual total, monthly, rainy days, max daily). Point estimate at the catchment bounding-box centroid (falls back to the selected pond). |
| `weather` | `weather.py` | Current weather from Open-Meteo. Context only, never used for design. |
| `design_rainfall` | `design_rainfall.py` | Fetches ~30 years of daily precipitation, extracts **annual maxima**, fits a **Gumbel** distribution by **method of moments**, and returns the **25-year daily design depth (mm)**. |
| `catchment_terrain` | `catchment_diagnostics.py` | **11A**: catchment-masked slope stats (`np.gradient`, deg + m/m), min/max/relief/mean elevation, **longest D8 flow path** (headwater → outlet; cardinal = cell, diagonal = cell·√2). |
| `land_cover` | `land_cover.py` | **11B-1**: OSM `landuse`/`natural`/`leisure`/`building` features classified into 8 classes (`built`, `agricultural`, `forest`, `grassland`, `wetland`, `water`, `bare`, `unknown`) with area fractions. |
| `soil_group` | `soil_group.py` | **11B-2**: **deliberately unavailable stub.** Never fabricates an HSG; returns `data_available: false` plus candidate sources (ISRIC SoilGrids, FAO HWSD, NBSS&LUP) as provenance. |
| `runoff` | `scs_cn.py` | **11B-3**: SCS Curve Number runoff (see formulas below). |
| `time_of_concentration` | `time_of_concentration.py` | **11B-4**: Kirpich Tc (see formula below). Diagnostic only. |
| `pond_adequacy` | `pond_adequacy.py` | **11B-5**: `adequacy_ratio = storage / runoff`; status pass (≥ 1.0) / marginal (≥ 0.75) / fail. |

**Key formulas**

```
Gumbel (method of moments), return period T:
    y_T      = −ln(−ln(1 − 1/T))
    beta_hat = s_x · √6 / π
    mu_hat   = x̄ − beta_hat · γ            (γ = 0.57721566…)
    x_T      = mu_hat + beta_hat · y_T

SCS-CN runoff (USDA NRCS NEH-630):
    S  = 25400 / CN − 254                 (mm)
    Ia = 0.2 · S
    Q  = 0                                if P ≤ Ia
    Q  = (P − Ia)² / (P + 0.8·S)          if P > Ia
    V  = (Q / 1000) · A_m2                (m³)
    AMC I:   CN_I   = CN_II / (2.33 − 0.0136·CN_II)
    AMC III: CN_III = CN_II / (0.427 + 0.00573·CN_II)
    area-weighted CN: CN_w = Σ (f_i · CN_i)

Kirpich time of concentration:
    Tc = 0.01947 · L^0.77 · S^(−0.385)    (minutes; L in m, S in m/m)

Pond adequacy:
    adequacy_ratio = available_storage_m³ / runoff_volume_m³
    pass ≥ 1.0, marginal ≥ 0.75, else fail   (documented engineering judgments)
```

**Dependency chain:** `catchment_terrain` → `time_of_concentration`;
`land_cover` + `soil_group` + `design_rainfall` → `runoff`;
`runoff` + `pond_capacity` → `pond_adequacy`.
Because `soil_group` is always unavailable in this build, `runoff` and `pond_adequacy`
are effectively always returned as "unavailable" — by design, so no fabricated numbers
are produced. `time_of_concentration` still works (it depends only on terrain).

---

## 12. API reference

Base URL `http://localhost:8000`. All data endpoints are under `/api`.

| Method | Endpoint | Stages run | Purpose |
|--------|----------|------------|---------|
| GET  | `/` | — | Health check + a (partial) endpoint list. |
| POST | `/api/inspect-contour` | 1 | Parse a KML/KMZ; return contour count, elevation range, interval, bbox. |
| POST | `/api/build-terrain` | 1–2 | Parse + build the IDW terrain grid; return a compact grid summary. |
| POST | `/api/analyze-hydrology` | 1–3 | Parse + terrain + Priority-Flood/D8/accumulation; return stats + diagnostics. |
| POST | `/api/find-pond-candidates` | 1–3, 5 | Rank pond candidates (no OSM water exclusion). |
| POST | `/api/delineate-catchment` | 1–3, 6 | Given `pond_row`/`pond_col`, delineate that catchment. |
| POST | `/api/analyze-contour` | **1–7 + 8–11** | **Integrated**: parse → terrain → hydrology → water exclusion → pond selection → catchment → capacity → rainfall/design → 11A/11B. |
| POST | `/api/analyze-location` | **1–7 + 8–11** | **Integrated (location)**: download DEM → generate contours → the same integrated pipeline. |
| GET  | `/api/rainfall` | — | `?latitude=&longitude=` historical rainfall. |
| GET  | `/api/weather` | — | `?latitude=&longitude=` current weather. |

Only the two integrated endpoints run all of Stages 1–7 in one request and append the
Stage 8–11 diagnostics. The standalone endpoints stop at the stage shown; Stage 4 (water
exclusion) is not exposed on its own.

Common tuning query params: `grid_cell_size_m`, `idw_power` (2.0), `idw_k` (12),
`idw_epsilon` (1e-6), `thinning_cell_size_m`, `pond_rank` (1 = best), plus Stage-5 params
(`top_k` clamped 3–5, `nms_radius_cells`, `relative_radius_cells`, `boundary_margin_m`).

The full response contract lives in `backend/models/__init__.py`
(`IntegratedAnalysisResponse`) and is mirrored in `frontend/src/types/api.ts`.

---

## 13. Frontend behaviour

- **`App.tsx`** — state machine (`idle | busy | running | done`), mode switch
  (Location / Upload), calls `analyzeContour` or `analyzeLocation`, tracks selected vs
  analysing rank, keeps the previous result on the map while a new request runs, and uses
  an `AbortController` for cancel.
- **Left sidebar** — mode selector, then either the location map / coordinate picker +
  radius/interval/DEM controls, or the KML/KMZ upload + "initial pond rank" input.
- **Centre** — Leaflet `MapView`: OpenStreetMap tiles, a marker per candidate (rank 1
  highlighted), the catchment polygon (or a dashed bbox fallback), a legend, and
  click-to-select a candidate. While running, an animated overlay
  (`AnalysisLoader` + a cosmetic `PipelineStepper`) is shown.
- **Right sidebar** — two tabs:
  - **Compare** (`CandidateComparison`) — all ranked candidates with expandable factor
    scores and an "Analyze this candidate" button (re-runs the pipeline at that rank).
  - **Selected** (`ResultsPanel` + `HydrologyPanel`) — sections A–F (recommended pond,
    suitability breakdown, catchment, pond depth/storage, terrain & hydrology,
    validation/water exclusion) and G–N (rainfall/weather, design rainfall, catchment
    terrain, land cover, soil, runoff, Tc, pond adequacy).

All displayed values are read-only from the backend response — the frontend does no
modelling.

---

## 14. Testing

```bash
cd backend
pytest -q
```

**Result: `553 passed`.**

The suite has one file per service (`test_catchment.py`, `test_pond_capacity.py`,
`test_scs_cn.py`, `test_design_rainfall.py`, `test_water_exclusion.py`, …) plus
integration tests (`test_integrated_endpoint.py`, `test_runoff_integration.py`,
`test_contour_generation_regression.py`).

`backend/tests/conftest.py` contains one autouse fixture that **blocks real outbound HTTP
to external hosts** and makes such a call raise `ConnectionError` immediately. Provider
*logic* tests already monkeypatch `requests` themselves; this fixture only guarantees the
suite is deterministic and can never hang on an unreachable third-party endpoint (e.g.
Overpass). It changes **no production behaviour** — the services already treat a failed
provider as "unavailable / fallback".

> Runtime note: on this machine the suite completes in about **2 minutes 15 seconds**
> (`133.99 s`). The wall time is mostly the ~40 end-to-end integrations of the 6.7 MB
> sample KML (parsing + IDW + hydrology each time) plus the Overpass client's bounded
> retry/backoff `sleep`s, which `test_overpass_client.py` exercises against **mocked**
> responses (no real sockets). It scales with machine speed. `conftest.py` keeps the
> suite hermetic — it never opens a real socket to an external host — so the figure is
> reproducible regardless of whether a public provider is reachable.

---

## 15. End-to-end demo (verified)

Start both servers (§8), then either use the UI or:

```bash
# 1. Health check
curl http://localhost:8000/

# 2. Inspect the sample contour file
curl -X POST http://localhost:8000/api/inspect-contour \
     -F "file=@sample_data/contours_1m.kml"

# 3. Full integrated analysis on the sample file
curl -X POST "http://localhost:8000/api/analyze-contour?pond_rank=1" \
     -F "file=@sample_data/contours_1m.kml" \
     -o /tmp/analyze_contour.json
```

The commands below were actually run on this repository and returned the values shown.

**`/api/inspect-contour`** → `contour_count: 1355`, elevation `267–298 m`, estimated
interval `1.0 m`, bbox `21.2398–21.2636 N, 81.2814–81.3126 E`.

**`/api/analyze-contour`** → `HTTP 200`, `error: null`:

| Field | Observed value |
|-------|----------------|
| grid | `326 × 266`, 10 m cells, 1355 contours |
| `num_candidates` | 5 (ranks 1–5) |
| rank-1 pond | row 84, col 89 → `21.24737 N, 81.28998 E`, elevation 270.0 m, suitability 99.05 |
| factor scores | accumulation 99.9, low_slope 97.6, low_relative 98.7, drainage 100.0 |
| catchment | 19 712 cells = 1 971 200 m² (197.12 ha, 22.73 % of grid), `flow_accum_consistent: true` |
| diagnostics | all pass (outlet in catchment, no duplicates, safe termination, area consistent/within grid) |
| `water_exclusion` | applied, 11 real OSM features (`water`, `river`, `canal`), 9 328 cells (10.8 %) excluded, 30 m buffer |
| `pond_capacity` | max depth 0.35 m, usable depth 0.0 → 0 m³ (flat local basin < 0.5 m freeboard; explicit early return) |
| `rainfall` | available, 1415 mm/yr, lookup basis `catchment_centroid` |
| `weather` | available, 26.3 °C |
| `design_rainfall` | available, **159.96 mm** for a 25-yr return period (Gumbel, 30 annual maxima, `stronger historical basis`) |
| `catchment_terrain` | mean slope 3.17°, relief 30.67 m, longest D8 flow path 3549.9 m, 4942 headwater cells |
| `land_cover` | available, 4 OSM features; classes include `water` (fraction clipped to 1.0) and `built` |
| `soil_group` | `data_available: false` with 3 documented candidate sources |
| `runoff` | unavailable — `"Soil group (HSG) unavailable; cannot look up CN."` |
| `time_of_concentration` | available, 32.1 min (Kirpich, path 3549.9 m) |
| `pond_adequacy` | unavailable — runoff volume not available |
| `time_elapsed_s` | ≈ 115 s (≈ 1.9 min; ~86 s of that is the two Overpass queries failing over past the unreachable public endpoints in this environment — see §20) |

**Frontend** — `npm run build` → `tsc` clean, `vite build` OK (92 modules,
`dist/assets/index-*.js` 386.9 kB). `npm run dev` serves the app at
`http://localhost:5173` (title "AI Pond Catchment Analyzer").

---

## 16. Assumptions

- **Local planar projection.** A local equirectangular projection is accurate enough at
  village scale (a few km); a real GIS workflow would use UTM or a national grid.
- **Contour interval is meaningful.** IDW assumes each contour line's elevation is
  representative of its sampled points.
- **Freeboard = 0.5 m** for small earthen ponds; **spill percentile = 25th** of higher
  neighbours within 3 cells approximates the natural basin rim.
- **Water buffer = 30 m** around OSM water features is a conservative exclusion distance.
- **SCS-CN CN table** values are engineering assumptions from published NEH-4 tables,
  not observed data for this site.
- **Design rainfall is a point estimate** from ERA5-Land reanalysis, not an official IMD
  value, and is a **24-hour depth** (not converted to an intensity).
- **Pond volume assumes no engineered embankment**; the pond is the natural basin.

## 17. Limitations

- **Soil / HSG is unavailable** (deliberate stub), so `runoff` and `pond_adequacy` are
  always "unavailable" in a default run even though the full SCS-CN path exists.
- **Pond capacity is terrain-only**; it ignores seepage, evaporation, sediment yield, and
  any bund/embankment engineering.
- **Catchment is defined on the DEM grid only**; results are as good as the DEM built
  from the supplied contours (IDW is a smoothing interpolator).
- **Point rainfall / design rainfall** ignores spatial variability across a catchment.
- **DNS/network dependence:** the integrated endpoints call external APIs. If a public
  Overpass endpoint is unreachable the call still succeeds, but pays one timeout per dead
  endpoint before failing over (see §20). Results are unaffected — the provider is only
  reported as unavailable/fallback if *every* endpoint fails.
- **Frontend pipeline stepper is cosmetic** — the backend runs the whole pipeline in a
  single request; the stepper stages are purely visual.
- **Land-cover fractions can saturate** (a large water polygon overlapping the catchment
  bbox clips to a fraction of 1.0), as seen in the demo.

## 18. Implemented vs unavailable

**Fully implemented and exercised:** contour parsing (KML & KMZ), IDW DEM, Priority-Flood
fill, D8 flow direction, flow accumulation, hydrology diagnostics, water exclusion (with
graceful fallback), 4-factor pond ranking + NMS, reverse-D8 catchment delineation +
convex-hull boundary, trapezoidal pond capacity, historical rainfall, current weather,
Gumbel design rainfall, catchment terrain diagnostics, OSM land cover, Kirpich Tc,
location mode (DEM download + `gdal_contour`), and the full React frontend.

**Present in code but not returned with real values:** SCS-CN runoff and pond adequacy —
both correctly report `data_available: false` because their soil-group input is not
available. They are *not* faked.

**Deliberately unavailable:** hydrologic soil group (HSG). The stub documents ISRIC
SoilGrids, FAO HWSD and NBSS&LUP as candidate sources and never fabricates a class.

## 19. Viva explanation

- **"Why IDW and not kriging?"** IDW via a KD-tree is O(N·log N), needs no variogram
  fitting, and is fully transparent — every cell is a distance-weighted average of its
  k nearest contour samples. Kriging would add complexity for little village-scale gain.
- **"Why Priority-Flood?"** Interpolated DEMs contain spurious pits that trap flow. Rather
  than smoothing (which destroys real valleys), Priority-Flood raises each pit to the
  minimum spill level, giving the *minimal* hydrologically correct surface in one pass.
- **"How are pond sites chosen?"** Four physically meaningful factors, each turned into a
  **percentile over interior cells** (so thresholds are data-driven, not hard-coded),
  combined with documented weights (0.30 / 0.25 / 0.25 / 0.20), then non-maximum
  suppression to keep candidates spatially distinct. Every score is returned so the
  choice is auditable.
- **"How is the catchment defined?"** Reverse-D8 traversal from the outlet: a cell joins
  the catchment if its flow arrow points into an already-included cell. This is exactly
  consistent with the flow-accumulation grid, which is why
  `flow_accum_at_outlet == catchment_cells` (a built-in validation check).
- **"Is the volume trustworthy?"** It is a **terrain-derived** trapezoidal estimate of the
  natural basin, explicitly not an engineered design. Assumptions and warnings are
  returned with the number, and flat sites correctly yield zero usable depth.
- **"Why is runoff unavailable?"** Because it needs a hydrologic soil group, and there is
  no free, keyless, programmatically reliable HSG source for a village in this build. The
  honest answer is "unavailable" rather than a guessed CN.
- **"What proves it works?"** 553 backend tests pass, and the documented end-to-end demo
  (§15) shows a complete, internally consistent response on real sample data.

## 20. Known quirks / notes

1. **Overpass failover cost** — the public endpoints are unreachable from some networks.
   Each dead endpoint now costs a single bounded timeout (a 5 s connect budget, or the
   20 s read budget) and then fails over; a hostname can resolve to several addresses, so
   one dead endpoint measured ≈ 20 s. The two Overpass queries in an integrated run
   (Stage 4 water exclusion and Stage 14 land cover) therefore add ≈ 86 s when the primary
   endpoints are down. Neither provider is disabled — all three endpoints are always tried
   and the third answers normally.
2. **`_non_maximum_suppression`** previously compared every candidate against every kept
   cell (O(N × kept) ≈ 10.5 s for an 87 k-cell DEM). It now marks each accepted cell's
   Chebyshev neighbourhood, which is output-identical and runs in ≈ 0.02 s.
3. **Water-exclusion mask rasterisation** previously evaluated every feature against every
   DEM cell; it now scans only each feature's buffered bounding box (≤ 1 cell margin),
   which is output-identical (≈ 11 s → ≈ 5 s for 11 features over 87 k cells).
4. **Soil / HSG is a stub** — see §18.
5. **Frontend pipeline stepper is cosmetic** — see §17.
6. **`marginal` adequacy threshold (0.75)** and the Tc methodology are documented
   engineering judgments, not safety factors.
7. **Single-worker server** — the integrated handlers do blocking work, so the backend
   serves one analysis at a time and a browser abort does not cancel server-side work.
   Submitting repeatedly queues full analyses; submit once and wait.

## 21. Performance profile (measured)

Measured end-to-end with `sample_data/contours_1m.kml` (326 × 266 grid, 1355 contours;
84 364 interior cells). Network figures depend on public-provider availability, so they
are given as measured values with the range seen across runs.

| # | Stage | Before (s) | After (s) | What changed |
|---|-------|-----------:|----------:|--------------|
| 1 | Contour parsing | 0.60 | 0.60 | — |
| 2 | Terrain / IDW | 0.29 | 0.29 | — |
| 3 | Priority-Flood fill | 0.14 | 0.13 | — |
| 4 | D8 flow direction | 0.14 | 0.13 | — |
| 5 | Flow accumulation | 0.11 | 0.11 | — |
| 6 | Overpass water exclusion | **315.47** | **42–61** | bounded per-endpoint timeout + immediate failover |
| 7 | Water-mask rasterisation | 11.44 | 5.47 | per-feature bounding-box scan |
| 8 | Pond candidate scoring | 10.59 | 0.05 | — |
| 9 | Non-maximum suppression | **10.50** | **0.02** | occupied-neighbourhood mask |
| 10 | Catchment delineation | 0.05 | 0.05 | — |
| 11 | Pond capacity | 0.00 | 0.00 | flat basin → explicit early return |
| 12 | Rainfall + weather | 2.01 | 2.05 | Open-Meteo (fast) |
| 13 | Design rainfall | 1.04 | 1.09 | Gumbel (Open-Meteo) |
| 14 | Land cover | **315.77** | **55** | bounded per-endpoint timeout + immediate failover |
| 15 | Catchment diagnostics + Tc | 0.34 | 0.33 | — |
| | **Total (stage sum)** | **668.5** | **≈ 115–190** | 95 % of the "before" total was external network |
| | **`/api/analyze-contour` HTTP 200** | **656.5** | **114.6** | real endpoint, sample KML |

**Root cause of the original latency.** Two of the three public Overpass endpoints are
unreachable from this network, and `overpass-api.de` resolves to four addresses. The
client used one shared 20 s timeout for connect *and* read, and retried a timeout three
times per endpoint, so each dead endpoint cost `4 addresses × 20 s × 3 retries` — two
queries (water exclusion + land cover) accounted for ≈ 630 s of the ≈ 656 s run.

**Changes (all output-preserving).**
- `overpass_client.overpass_query`: a separate, short connect budget (`CONNECT_TIMEOUT_S`)
  and immediate failover on *any* timeout instead of retrying the same dead endpoint.
  All three endpoints are still tried; retries remain for 504/5xx; graceful degradation
  is unchanged.
- `pond_selection._non_maximum_suppression`: marks each kept cell's Chebyshev
  neighbourhood instead of scanning every kept cell — verified identical over 1600
  randomised cases.
- `water_exclusion._create_water_mask`: scans only each feature's buffered bounding box
  (≤ 1-cell margin) instead of the whole grid per feature — verified identical over 40
  randomised feature/grid cases.

**Correctness check.** Before/after responses were compared field by field on the sample
KML: all 32 top-level keys and all 24 compared structural/numerical values were identical
(selected pond, candidate scores, catchment, water exclusion, capacity, rainfall, design
rainfall, land cover, soil, runoff, Tc, adequacy). Only `time_elapsed_s` changed.
Full suite: **553 passed** (133.99 s, down from 683.73 s).
