"""
AI-Based Village Pond Planning System - Stage 5: Catchment Delineation.

FastAPI application providing a backend API for contour map analysis.
- Stage 1: KML/KMZ parsing and /api/inspect-contour endpoint.
- Stage 2: Terrain elevation modelling via IDW interpolation
  and /api/build-terrain endpoint.
- Stage 3: Hydrological analysis (Priority-Flood depression
  filling, D8 flow direction, flow accumulation) and the
  /api/analyze-hydrology endpoint.
- Stage 4: Pond candidate identification and ranking.
- Stage 5: Catchment delineation using reverse D8 traversal.

The catchment service re-uses existing hydrology results (D8 flow
direction, flow accumulation) to delineate the upstream catchment of
a selected pond candidate. The algorithm uses BFS to find all cells
whose D8 direction points toward the outlet, ensuring consistency
between the delineated catchment and the flow accumulation network.
"""
import logging
import sys
from pathlib import Path

# Add the backend directory to Python path so imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv  # python-dotenv (optional)

    # Load environment variables from backend/.env (if present).
    # The real .env is git-ignored; .env.example is a safe template.
    _env_path = Path(__file__).resolve().parent / ".env"
    if _env_path.is_file():
        load_dotenv(_env_path)
except ImportError:
    # python-dotenv is not installed; environment variables must be
    # supplied through the shell (e.g. export OPENTOPOGRAPHY_API_KEY=...).
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as contour_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AI-Based Village Pond Planning System",
    description=(
        "Phase 5: KML/KMZ contour parsing, terrain elevation modelling, "
        "hydrological analysis, pond candidate selection, and catchment "
        "delineation. Accepts KML/KMZ files, extracts contour lines, "
        "builds an interpolated elevation grid (DEM) using Inverse Distance "
        "Weighting, runs Priority-Flood depression filling, D8 flow "
        "direction and flow accumulation, identifies and ranks pond "
        "candidates using a multi-factor suitability scoring methodology, "
        "and delineates the upstream catchment of a selected candidate "
        "using reverse D8 traversal."
    ),
    version="0.5.0",
)

# CORS middleware (useful if a frontend is added later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(contour_router)


@app.get("/", tags=["health"])
async def root() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "AI-Based Village Pond Planning System",
        "version": "0.5.0",
        "endpoints": {
            "inspect_contour": "/api/inspect-contour (POST)",
            "build_terrain": "/api/build-terrain (POST)",
            "analyze_hydrology": "/api/analyze-hydrology (POST)",
            "find_pond_candidates": "/api/find-pond-candidates (POST)",
            "delineate_catchment": "/api/delineate-catchment (POST)",
            "analyze_contour": "/api/analyze-contour (POST)",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
