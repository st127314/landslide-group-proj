"""Central place for every on-disk path the API reads from.

Everything here is read-only: the API never writes into the data/, models/ or
results/ directories. All paths resolve relative to the project root (three
levels up from this file: apps/backend/app/paths.py -> project/).
"""

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
# Containers mount the read-only data/, models/ and results/ folders under LANDSLIDE_ROOT
# (see apps/deploy); locally it defaults to the project root.
PROJECT_ROOT = Path(os.environ.get("LANDSLIDE_ROOT") or APP_DIR.parent.parent.parent)

DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = PROJECT_ROOT / "results"
MODELS_DIR = PROJECT_ROOT / "models"
EXTERNAL_DIR = DATA_DIR / "external"
BOUNDARY_DIR = DATA_DIR / "boundary"
INVENTORY_DIR = DATA_DIR / "inventory"
PROCESSED_DIR = DATA_DIR / "processed"
MODEL_ARTIFACTS_DIR = MODELS_DIR / "susceptibility"

MODEL_METADATA_PATH = MODEL_ARTIFACTS_DIR / "model_metadata.json"
SUSCEPTIBILITY_SCORES_CSV = MODEL_ARTIFACTS_DIR / "landslide_sample_susceptibility_scores.csv"

SUSCEPTIBILITY_MAP_DIR = RESULTS_DIR / "susceptibility_map"
SUSCEPTIBILITY_GRID_CSV = SUSCEPTIBILITY_MAP_DIR / "susceptibility_grid_points.csv"
SUSCEPTIBILITY_MAP_METADATA_PATH = SUSCEPTIBILITY_MAP_DIR / "susceptibility_map_metadata.json"

BOUNDARY_PATH = BOUNDARY_DIR / "southern_thailand.geojson"
BUILDINGS_PATH = EXTERNAL_DIR / "buildings_aoi.geojson"
FACILITIES_PATH = EXTERNAL_DIR / "facilities_aoi.geojson"
WORLDPOP_MANIFEST_PATH = EXTERNAL_DIR / "worldpop_manifest.json"
EXTERNAL_MANIFEST_PATH = EXTERNAL_DIR / "manifest.json"

# Pipeline outputs this API reports progress from (see /api/status).
FACTOR_GRID_POINTS_DIR = PROCESSED_DIR / "factor_grid_points"  # 250 m point-sampled factor grid

TAMBON_BOUNDARY_PATH = BOUNDARY_DIR / "southern_thailand_tambons.geojson"
LIVE_FORECAST_JSON = RESULTS_DIR / "live_forecast" / "latest.json"
IMPACT_OVERLAY_JSON = RESULTS_DIR / "impact_overlay" / "impact_overlay.json"
