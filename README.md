# Landslide Susceptibility Mapping and Rainfall-Based Impact Triage — Southern Thailand

A landslide susceptibility model plus a live-impact view for the 14 southern provinces of Thailand.

**Live application:** https://landslide.spadace.com (the API is under `/api/`, for example `/api/health` and `/api/overview`). Deployment and CI/CD are described in `apps/deploy/README.md`.

The project has three parts:

1. **Susceptibility model** — where is terrain prone to landslides? (19 conditioning factors, 6,180 landslide + 6,180 paired non-landslide points, spatial cross-validation, calibrated scores, 250 m map.) **This is the validated part of the project.**
2. **Live forecast rainfall** — NOAA GFS rainfall for the next 24 / 48 / 72 / 96 / 120 h (5 days) per tambon, judged against each tambon's own rainfall climate (wet-day percentiles P75/P90/P95 from 30 years of CHIRPS). No machine-learning model: an exploratory rainfall model was tried and shown to have no skill (hold-out ROC-AUC 0.34; `notebooks/rainfall_trigger_threshold.ipynb`, kept as a documented negative result).
3. **Live impact overlay and what-if scenario** — terrain factor × local rain class → impact class per tambon, plus a "what if X mm falls?" scenario (no extra model); with the buildings, facilities and people at elevated risk, shown per tambon on the dashboard map. A transparent triage rule, **not a validated landslide forecast**.

Read `docs/METHODS.md` first for how everything was built and, importantly, its **Known issues** section before relying on any number here.

## What is in this repository

The repository holds what a team member needs to run and extend the modelling notebooks:

| Path | Contents |
|---|---|
| `notebooks/` | susceptibility modelling and rainfall-trigger notebooks, plus `susc_utils.py` |
| `notebooks/experiments/` | `run_experiments.py`: experiments E1–E7, error analysis and partial dependence; `run_followup_experiments.py`: follow-ups F0–F5 (permutation importance, near-duplicate thinning, the decision value on the map by factor set, environment-matched negatives, the final-review checks on NDVI, the missing-value indicators and the hold-out interval, and the grid's road and river distances); `common.py`: shared folds, preprocessing and models |
| `notebooks/tracking.py` | experiment tracking with MLflow on the local machine: one run per candidate model and per experiment configuration, and the selected pipeline as a version in a local model registry (`mlflow.db` and `mlartifacts/`, not in git) |
| `scripts/` | data pipeline: Earth Engine extraction, negative sampling, cleaning, grid prediction, rainfall percentiles, live forecast, impact overlay, web layers and tiles, figures (see `scripts/README.md`) |
| `data/processed/landslide_event_factors_cleaned.csv` | model-ready table: 6,180 landslide + 6,180 paired non-landslide points, the 19 conditioning factors of the model plus NDVI, which is kept in the table but not used (input of the susceptibility notebook) |
| `data/processed/*_antecedent_rainfall.csv` | IMERG antecedent rainfall per event (input of the rainfall-trigger notebook) |
| `data/processed/landslide_event_factors_cleaning_report.txt`, `data/DATA_DICTIONARY.md` | how the table was cleaned; meaning of every column |
| `models/*/model_metadata.json`, `models/rainfall_trigger/rainfall_trigger_metadata.json` | cross-validation and hold-out scores of every candidate model, selected hyperparameters |
| `results/experiments/` | outputs of the experiments (`results.json`, `errors.json`, `followup.json`) and the province of each point used for E5 |
| `results/figures/` | susceptibility map, live-impact map, model comparison and exposure figures |
| `docs/` | methods (including data sources), dataset descriptions, proposal report and slides |
| `requirements.txt` | Python dependencies for the pipeline and notebooks |
| `apps/`, `tests/`, `.github/` | API, dashboard, forecast job, deployment files, tests and CI/CD (see `apps/README.md`, `apps/deploy/README.md`) |

**Kept outside git on purpose:** the raw landslide inventory and source spreadsheets, the raw Earth Engine samples, external layers (OSM, WorldPop, GLiM, GEM, GADM boundaries), the 250 m factor grid, the scored map, trained model files and credentials. GADM boundaries may not be redistributed, and the large layers exceed GitHub's file limits. Clone the repo, install `requirements.txt` (or `notebooks/requirements-modeling.txt`) and run the notebooks from the project root; they write trained model files to `models/`, which are not tracked. The Earth Engine scripts need your own service-account key and copies of the input assets (see `scripts/README.md`).

The landslide inventory was provided by ADPC; cite it accordingly when reusing the processed tables.

## Headline results

| | |
|---|---|
| Susceptibility model (selected by nested spatial CV) | `logistic_regression_feature_selected` (19 factors); nested-CV ROC-AUC 0.918 ± 0.030; spatial hold-out ROC-AUC 0.888, PR-AUC 0.806. Plain logistic regression is within the fold spread (0.910 ± 0.039). NDVI was removed because it was measured after the scar formed (see `docs/METHODS.md`, Known issue 14); with NDVI the hold-out was 0.940 |
| Map | 1,137,629 cells at 250 m: 68% very low, 4% low, 5% moderate, 8% high, 15% very high |
| Exposure in high / very-high cells (any weather) | 55,669 of 9,385,884 people (0.59%); 3,947 of 426,519 buildings (0.9%); 32 of 3,895 facilities |
| Largest exposed populations | Nakhon Si Thammarat 13,941 (1.0%), Yala 11,464 (2.7%), Phuket 10,603 (1.0%), Ranong 4,015 — **these four have almost no landslide training points, so they are extrapolation** |
| Held-out landslides in the map's top 20% of cells (like for like, `followup.json` F2) | 60% for the selected model (59% plain logistic regression, 61% SVM, 62% terrain factors only); no skill = 20%. Removing NDVI did not change this figure |
| Environment-matched negatives (F3) | ROC-AUC ≈ 0.50 when negatives have the same slope and elevation as the landslides: the model separates hillslopes from lowland, not failed from unfailed slopes |
| Live forecast snapshot (GFS run 2026-11-10 00:00 UTC) | next 24 h: max 36.1 mm, median 5.3 mm; 766 tambons below their own P75, 188 at P75–P90, 101 at P90–P95 |
| Live impact for that run | 11 tambons high, 112 moderate, 930 low, 2 not assessed; 1,024 people at elevated risk |
| What-if scenario (24 h rain, whole south) | 30 mm: 1 very high + 153 high tambons, 21,977 people at elevated risk; 50 mm: 82 very high + 213 high, 38,809 people; 100 mm and above: 40,841 people (classes saturate above each tambon's P95) |

The map, the exposure figures, the live-impact overlay, the figures and `results/experiments/` were all regenerated on 2026-11-14 with the model without NDVI.

Figures are in `results/figures/`. Terrain scores are relative rankings under 1:1 pseudo-absence sampling, not calibrated real-world probabilities, and the negatives are easy lowland points (Known issue 4). The rain thresholds are local climate percentiles, not calibrated on landslides.

## Folder layout

The layout below is the team's full working folder (about 4 GB with the raw downloads, caches and the 250 m factor grid). The repository holds the paths listed in the table above; the remaining files under `data/`, `models/` and `results/` are produced locally by the pipeline, and `FILE_MANIFEST.csv` stays in the working folder. Their contents are described here for reference.

```
README.md                  this file
requirements.txt           Python dependencies for everything below
FILE_MANIFEST.csv          size, row count and SHA-256 of every file in data/, models/, results/
data/
  boundary/                study area (14 provinces), 1,055 tambons, one sample point per tambon
  inventory/               landslide inventory (6,180) and non-landslide pseudo-absences (6,180)
  external/                OSM buildings (GeoJSON and PMTiles) and facilities, WorldPop, rainfall percentiles
  raw/, cache/             source downloads and resumable Earth Engine parts (local only)
  processed/               model-ready tables: event factors, antecedent rainfall, 250 m factor grid
  DATA_DICTIONARY.md       every column of every final table
models/
  susceptibility/          trained pipeline + isotonic calibrator + metadata (+ per-event scores)
  rainfall_trigger/        exploratory rainfall model (no skill; not used by the live pipeline)
results/
  susceptibility_map/      250 m scored grid (CSV + GeoTIFF), the PNG the web map draws, and metadata
  live_forecast/           latest GFS rainfall forecast per tambon (24 h to 5 days) and its rain class
  impact_overlay/          per-tambon / per-province / per-facility exposure and combined class
  figures/                 report-ready PNG figures
notebooks/                 the two modelling notebooks (+ susc_utils.py needed to load the pickled model)
scripts/                   data-acquisition and pipeline scripts (see scripts/README.md)
apps/                      FastAPI backend + Next.js frontend that serve the results (see apps/README.md)
tests/                     tests of the processed data, modelling helpers, training/serving consistency, overlay refresh and Earth Engine extraction logic
docs/                      METHODS.md, dataset descriptions, proposal report and slides
```

Regenerable intermediates that are not kept in `data/external/`: the OSM roads / rivers / waterways, GEM faults and GLiM lithology GeoJSON layers (about 390 MB), which were only inputs for Earth Engine assets that are already uploaded; `python scripts/download_external_data.py` re-creates them. Credentials live in `scripts/service_account/` and `credentials/`, both ignored by git.

## Pipeline order

| Step | Script / notebook | Output |
|---|---|---|
| 1 | `scripts/download_external_data.py`, `download_worldpop_population.py`, `clip_tambon_boundaries.py` | `data/external/`, `data/boundary/` |
| 2 | `scripts/generate_paired_negatives.py` | `data/inventory/non_landslide_events.geojson` (one negative per landslide, same date and province) |
| 3 | `scripts/gee_landslide_factors.py` (Earth Engine) for the landslides; `scripts/gee_extract_paired_negatives.py` for the negatives | `data/processed/landslide_event_factors.csv` (landslide rows), `data/cache/paired_negative_event_factors.csv` |
| 4 | `scripts/gee_imerg_antecedent_rainfall.py` (landslides) and `scripts/gee_imerg_paired_negatives.py` (negatives), both Earth Engine | `data/processed/*_antecedent_rainfall.csv` |
| 4b | `scripts/assemble_paired_dataset.py` (strict checks; uses `clean_event_factors.py`) | `data/processed/landslide_event_factors.csv` (both classes), `landslide_event_factors_cleaned.csv`, cleaning report |
| 5 | `notebooks/landslide_susceptibility_modeling.ipynb` | `models/susceptibility/` |
| 5b | `notebooks/experiments/run_experiments.py`, `run_followup_experiments.py` | `results/experiments/` |
| 5c | `notebooks/tracking.py --experiments` (optional; the notebook logs its own model comparison). View with `mlflow ui --backend-store-uri sqlite:///mlflow.db` | local MLflow store: `mlflow.db`, `mlartifacts/` |
| 6 | `scripts/gee_sample_factor_grid_points.py` (Earth Engine) → `data/processed/factor_grid_points/` (local only, not in git), then `check_grid_inputs.py` (compares every factor on the grid with the training table; a new mismatch stops the scoring) and `predict_susceptibility_grid.py` | `results/susceptibility_map/` |
| 7 | `notebooks/rainfall_trigger_threshold.ipynb` (exploratory, no skill; not used downstream) | `models/rainfall_trigger/` |
| 7b | `scripts/compute_rain_percentiles.py` (Earth Engine, ~1 min, one-off) | `data/external/rain_percentiles_24h_tambon.csv` |
| 8 | `scripts/run_live_gfs_forecast.py` (Earth Engine, ~10 s; rerun for a fresh forecast) | `results/live_forecast/latest.json` |
| 9 | `scripts/build_impact_overlay.py` (full build) or `scripts/refresh_impact_overlay.py` (new forecast only, seconds); `scripts/make_figures.py` | `results/impact_overlay/`, `results/figures/` |
| 10 | `scripts/make_web_layers.py`, `scripts/make_susceptibility_png.py`, `scripts/make_buildings_tiles.sh` | slim boundary, tambon and facility layers, the map PNG and the building tiles the API serves |
| 11 | `scripts/make_manifest.py` | `FILE_MANIFEST.csv` |

Steps 3, 4, 6, 7b and 8 need an Earth Engine service-account key at `scripts/service_account/key.json` (not included; Earth Engine project and quota are the team's). Everything else runs from the files in this folder. The landslide inventory itself was supplied as a workbook (not included); the pipeline starts from `data/inventory/`. On the server, steps 8 and 9 (refresh) run as a scheduled container job (`apps/forecast/`, `apps/deploy/install-forecast-cron.sh`).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# rebuild the impact overlay and figures (needs the local data/ folder; under a minute)
python scripts/build_impact_overlay.py
python scripts/make_figures.py

# run the tests (no network or credentials required); the API tests are in apps/backend/tests
pip install -r tests/requirements.txt && python -m pytest tests -q

# serve the results
cd apps/backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd apps/frontend && npm install && npm run dev        # http://localhost:3000
```

`scripts/build_impact_overlay.py` uses GDAL's Python bindings (`osgeo`); install GDAL through your system package manager (for example `brew install gdal`) and match the Python package version.

## Data and licences

Data sources are summarised in `docs/METHODS.md` and `data/DATA_DICTIONARY.md`. OpenStreetMap-derived layers are © OpenStreetMap contributors (ODbL 1.0); GEM faults are CC BY-SA 4.0; WorldPop is CC BY 4.0; GLiM is free for non-commercial scientific use with citation.
