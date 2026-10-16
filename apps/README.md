# Landslide Impact app

Two apps, both read-only against the data pipeline's outputs
(`data/`, `models/`, `results/` at the project root). Neither writes
into that pipeline -- rerun the relevant script/notebook to refresh data,
then restart the backend (it caches pipeline outputs in memory at startup).

## Backend (`apps/backend`) -- FastAPI

```bash
cd apps/backend
python3 -m venv .venv && PIP_USER=0 .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Docs/try-it-out UI: http://localhost:8000/docs

| Endpoint | What it serves |
| --- | --- |
| `GET /api/overview` | Summary stats (event/building/facility/population counts, best model) + pipeline status |
| `GET /api/status` | Status of the pipeline pieces (factor grid, susceptibility map, live forecast, impact overlay) |
| `GET /api/model` | Full `model_metadata.json` from the susceptibility-modeling notebook |
| `GET /api/model/comparison` | Per-model CV + held-out test metrics, side by side |
| `GET /api/impact/boundary` | Study-area boundary GeoJSON |
| `GET /api/impact/susceptibility` | Point-level susceptibility scores for the training/test inventory (6,180 landslide + 6,180 non-landslide points) -- for model evaluation, not the map itself |
| `GET /api/impact/susceptibility-grid?min_lon=&min_lat=&max_lon=&max_lat=&limit=` | The actual susceptibility **map**: ~1.14M points on a 250m grid, scored by the trained model (viewport-limited, same pattern as `/buildings`) |
| `GET /api/impact/susceptibility-grid/metadata` | Class-bin counts, score interpretation, limitations for the grid above |
| `GET /api/impact/facilities` | Critical-facility points (hospitals, schools, emergency services, transport hubs, places of worship) |
| `GET /api/impact/buildings?min_lon=&min_lat=&max_lon=&max_lat=&limit=` | Building footprints for a bounding box (viewport-limited -- 426k+ total, never served unfiltered) |
| `GET /api/impact/live-forecast` | NOAA GFS 24/48/72 h rainfall per tambon and its (assumed-threshold) rain class (from `scripts/run_live_gfs_forecast.py`) |
| `GET /api/impact/scenario?rain_24h_mm=&province=&limit=` | What-if: replaces the 24 h rainfall in scope (all tambons or one province) and re-applies the impact rule to the stored overlay; in-memory, no Earth Engine, no AI assistant (see `apps/backend/app/scenario.py`) |
| `GET /api/impact/overlay` | Live impact per tambon/province: terrain tier x GFS rain class x exposed buildings/facilities/population (from `scripts/build_impact_overlay.py`) |
| `GET /api/impact/population` | WorldPop population stats for the study area (raster itself not tiled/served yet) |

## Frontend (`apps/frontend`) -- Next.js + Tailwind + MapLibre

```bash
cd apps/frontend
npm install
npm run dev
```

http://localhost:3000, configured via `.env.local` (`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`).

| Page | Contents |
| --- | --- |
| `/` Overview | Stat cards, live pipeline-job progress, links to the other two pages |
| `/impact` Live Impact | MapLibre map: study-area boundary, the 250m susceptibility map, critical facilities, buildings (all loaded per-viewport), plus the raw training/test sample points as a toggle |
| `/model` Model | Methodology write-up, best-model/threshold cards, full CV-vs-test model comparison table |

## Data pipeline recap

- **Susceptibility factor grid**: sampled as 250m points via Earth Engine
  `reduceRegions` (`scripts/gee_sample_factor_grid_points.py`), not a raster
  download -- an earlier raster-tile approach
  (`gee_export_factor_grid_local.py`) was abandoned partway through because
  it was ~10-60x slower and hit an undocumented Earth Engine 5,000-element
  cap on large point counts (fixed in the point-sampling script by chunking).
  See that script's docstring for why 250m is not a meaningful resolution
  loss given the model's own ~28km spatial-CV validation granularity.
- **Susceptibility map**: `scripts/predict_susceptibility_grid.py` applies
  the trained pipeline + isotonic calibrator to that grid, producing
  `results/susceptibility_map/susceptibility_grid_points.csv` (served by the
  API above) and a GeoTIFF (`susceptibility_grid.tif`) for GIS/zonal-stats use
  outside this app.
- **Exploratory rainfall model** (not used by the live pipeline): `notebooks/rainfall_trigger_threshold.ipynb`
  fits IMERG antecedent rainfall on the landslide/paired-negative inventory. It has **no skill** (hold-out ROC-AUC 0.34):
  the negatives share their landslide's date and region and the landslide dates are image dates. Kept as a documented
  negative result; see `docs/METHODS.md`, Section 3 and Known issues.
- **Live forecast + impact overlay**: `scripts/run_live_gfs_forecast.py` fetches NOAA GFS 24/48/72 h rainfall per tambon
  (`results/live_forecast/latest.json`, served at `/api/impact/live-forecast`); `scripts/build_impact_overlay.py` joins it
  with the susceptibility grid and OSM buildings / facilities / WorldPop population per tambon
  (`results/impact_overlay/`, served at `/api/impact/overlay`, shown on the Early Warning page). Re-run both for a fresh
  forecast. The impact class is a transparent triage rule (terrain factor x local rain class), not a validated forecast.
- **Tambon aggregation**: boundaries are clipped from GADM (`scripts/clip_tambon_boundaries.py`)
  into `data/boundary/southern_thailand_tambons.geojson` and used by the live forecast and the overlay.

## What's not wired up yet

- **Population raster on the map** -- only summary stats are served today;
  showing the raster itself would need a tile server (e.g. titiler) in front
  of `data/external/worldpop_2020_UNadj_constrained_aoi.tif`.
