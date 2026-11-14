# Landslide Impact application

Three parts, all read-only against the pipeline's outputs (`data/`, `models/`, `results/` at the project root):

| Part | Folder | What it does |
|---|---|---|
| API | `apps/backend` | FastAPI. Serves the precomputed susceptibility map, exposure layers, live forecast, impact overlay and what-if scenario. It never runs the model: the map is scored offline by `scripts/predict_susceptibility_grid.py`. |
| Dashboard | `apps/frontend` | Next.js, Tailwind and MapLibre. |
| Forecast job | `apps/forecast` | One-shot container: `run_live_gfs_forecast.py` then `refresh_impact_overlay.py`. Run every 3 hours by cron on the server through `run-forecast.sh`, which falls back to the last good forecast if a run fails. |

Deployment, Docker and CI/CD are in `apps/deploy/README.md`. Live: https://landslide.spadace.com

## Backend

```bash
cd apps/backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000      # interactive docs at http://localhost:8000/docs
.venv/bin/pip install pytest httpx && .venv/bin/python -m pytest tests -q   # runs on a synthetic data tree
```

Static layers are read once and kept in memory as bytes (restart the API after new data); the live forecast and the
impact overlay are re-read on every request. `LANDSLIDE_ROOT` points the API at another data folder (default: the
project root).

| Endpoint | What it serves |
| --- | --- |
| `GET /api/health` | Liveness check used by Docker and the deploy smoke test |
| `GET /api/overview`, `GET /api/status` | Summary counts and what each pipeline step last produced |
| `GET /api/model`, `GET /api/model/comparison` | `model_metadata.json`; cross-validation and hold-out metrics of the eleven candidates |
| `GET /api/impact/susceptibility-raster.png`, `.json` | The 250 m map as one coloured PNG, and its corner coordinates with a content hash (`version`) |
| `GET /api/impact/susceptibility-at?lon=&lat=` | Calibrated score and class of the grid cell nearest a point (404 beyond ~400 m) |
| `GET /api/impact/tambons` | The 1,055 tambon polygons (simplified), joined on the map by `GID_3` |
| `GET /api/impact/overlay` | Per tambon and province: terrain tier, forecast rain and its class, live impact class, exposure |
| `GET /api/impact/scenario?rain_24h_mm=&province=&limit=&classes=` | What-if: replaces the 24 h rain in scope and re-applies the impact rule; `classes=true` adds every tambon's classes for the map |
| `GET /api/impact/live-forecast` | GFS 24 / 48 / 72 / 96 / 120 h rain per tambon and its classes |
| `GET /api/impact/buildings.pmtiles` | Building footprints as vector tiles, read with HTTP range requests |
| `GET /api/impact/boundary`, `/facilities`, `/susceptibility`, `/population` | Province outline, facility points, scored training/test points, WorldPop summary |
| `GET /api/impact/buildings?bbox…`, `/susceptibility-grid?bbox…` | Bounding-box queries kept for analysis; the dashboard no longer uses them (the buildings one needs the 140 MB GeoJSON and about 1.4 GB of RAM) |

Inputs are validated by FastAPI (`rain_24h_mm` 0–1500, a known province, `limit` 1–200, coordinates in range: otherwise
422); a missing data file gives 404 with the script to run; only GET is allowed.

## Dashboard

```bash
cd apps/frontend
npm install
npm run dev        # http://localhost:3000; NEXT_PUBLIC_API_URL defaults to http://localhost:8000
npm run lint && npm run build
```

| Page | Contents |
| --- | --- |
| `/` Overview | What the tool does, headline counts, pipeline status |
| `/impact` Live Impact | Full-screen map: tambon risk (live impact, terrain tier or rain class; GFS forecast or a what-if rainfall slider; search; click a tambon for its risk, exposure and a 5-day rain chart), a charts panel (tambons rated moderate or above and people at elevated risk by province; tambons with unusual rain on each of the next 5 days) that follows the forecast or the what-if rainfall, the 250 m susceptibility map, facilities, buildings, training/test points |
| `/warning` Early Warning | Forecast summary, live impact table and the what-if scenario panel |
| `/model` Model | Method, selected model, comparison table, limitations |
| `/data` Data | Inventory, the 19 factors and their sources, other datasets, limitations |

The live impact class is a transparent rule (terrain tier × how unusual the forecast rain is for the tambon), not a
validated landslide forecast; read `docs/METHODS.md`, Known issues, before using any number.
