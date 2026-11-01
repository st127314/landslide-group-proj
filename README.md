# Landslide Susceptibility Mapping and Rainfall-Based Impact Triage — Southern Thailand

A landslide susceptibility model plus a live-impact view for the 14 southern provinces of Thailand:

1. **Susceptibility model** — where is terrain prone to landslides? (20 conditioning factors, 6,180 landslide + 6,180 paired non-landslide points, spatial cross-validation, calibrated scores, 250 m map.) **This is the validated part of the project.**
2. **Live forecast rainfall** — NOAA GFS rainfall for the next 24 / 48 / 72 h per tambon, judged against each tambon's own rainfall climate (wet-day percentiles P75/P90/P95 from 30 years of CHIRPS). No machine-learning model: an exploratory rainfall model was tried and shown to have no skill (hold-out ROC-AUC 0.34; `notebooks/rainfall_trigger_threshold.ipynb`, kept as a documented negative result).
3. **Live impact overlay and what-if scenario** — terrain factor × local rain class → impact class per tambon, plus a "what if X mm falls?" scenario (no extra model); with the buildings, critical facilities and people at elevated risk. A transparent triage rule, **not a validated landslide forecast**.

Read `docs/METHODS.md` first for how everything was built and, importantly, its **Known issues** section before relying on any number here.

## What is in this repository

The repository holds what a team member needs to run and extend the modelling notebooks:

| Path | Contents |
|---|---|
| `notebooks/` | susceptibility modelling and rainfall-trigger notebooks, plus `susc_utils.py` |
| `notebooks/experiments/run_experiments.py` | supplementary experiments E1–E7, error analysis and partial dependence reported in the progress report |
| `scripts/` | data pipeline: Earth Engine extraction, negative sampling, cleaning, grid prediction, rainfall percentiles, live forecast, impact overlay, figures (see `scripts/README.md`) |
| `data/processed/landslide_event_factors_cleaned.csv` | model-ready table: 6,180 landslide + 6,180 paired non-landslide points, 20 conditioning factors (input of the susceptibility notebook) |
| `data/processed/*_antecedent_rainfall.csv` | IMERG antecedent rainfall per event (input of the rainfall-trigger notebook) |
| `data/processed/landslide_event_factors_cleaning_report.txt`, `data/DATA_DICTIONARY.md` | how the table was cleaned; meaning of every column |
| `models/*/model_metadata.json`, `models/rainfall_trigger/rainfall_trigger_metadata.json` | cross-validation and hold-out scores of every candidate model, selected hyperparameters |
| `results/experiments/` | outputs of the supplementary experiments (`results.json`, `errors.json`) and the province of each point used for E5 |
| `results/figures/` | susceptibility map, live-impact map, model comparison and exposure figures |
| `docs/` | methods (including data sources), dataset descriptions, proposal report and slides |
| `requirements.txt` | Python dependencies for the pipeline and notebooks |
| `apps/`, `tests/`, `.github/` | API, dashboard, tests and CI/CD |

**Kept outside git on purpose:** the raw landslide inventory and source spreadsheets, the raw Earth Engine samples, external layers (OSM, WorldPop, GLiM, GEM, GADM boundaries), the 250 m factor grid, the scored map, trained model files and credentials. GADM boundaries may not be redistributed, and the large layers exceed GitHub's file limits. Clone the repo, install `requirements.txt` (or `notebooks/requirements-modeling.txt`) and run the notebooks from the project root; they write trained model files to `models/`, which are not tracked. The Earth Engine scripts need your own service-account key and copies of the input assets (see `scripts/README.md`).

The landslide inventory was provided by ADPC; cite it accordingly when reusing the processed tables.

## Headline results

| | |
|---|---|
| Susceptibility model (selected by nested spatial CV) | `svm_rbf`; nested-CV ROC-AUC 0.934 ± 0.028; spatial hold-out ROC-AUC 0.940 (95% CI 0.932–0.948), PR-AUC 0.904 |
| Map | 1,137,629 cells at 250 m: 63% very low, 7% low, 7% moderate, 11% high, 11% very high |
| Exposure in high / very-high cells (any weather) | 71,402 of 9,385,884 people (0.76%); 5,983 of 426,519 buildings (1.4%); 34 of 3,895 facilities |
| Largest exposed populations | Phuket 21,320 (2.1%), Nakhon Si Thammarat 13,625 (1.0%), Yala 12,998 (3.1%), Ranong 5,239 — **these four have almost no landslide training points, so they are extrapolation** |
| Live forecast shipped (GFS run 2026-10-15 18:00 UTC, quiet weather) | next 24 h: max 18.1 mm; all 1,055 tambons below their own P75 (the fixed 10 mm rule would have flagged 130) |
| Live impact for that run | all 1,053 assessed tambons low; nobody at elevated risk (no unusual rain forecast) |
| What-if scenario (24 h rain, whole south) | 30 mm: 2 very high + 152 high tambons, 30,879 people at elevated risk; 50 mm: 81 very high + 215 high, 51,537 people; 100 mm and above: 54,022 people (classes saturate above each tambon's P95) |

Figures are in `results/figures/`. Terrain scores are relative rankings under 1:1 pseudo-absence sampling, not calibrated real-world probabilities, and the negatives are easy lowland points (Known issue 4). The rain thresholds are local climate percentiles, not calibrated on landslides.

## Folder layout

The layout below is the team's full working folder. The repository holds the paths listed in the table above; the remaining files under `data/`, `models/` and `results/` are produced locally by the pipeline, and `FILE_MANIFEST.csv` stays in the working folder. Their contents are described here for reference.

```
README.md                  this file
requirements.txt           Python dependencies for everything below
FILE_MANIFEST.csv          size, row count and SHA-256 of every file in data/, models/, results/
data/
  boundary/                study area (14 provinces), 1,055 tambons, one sample point per tambon
  inventory/               landslide inventory (6,180) and non-landslide pseudo-absences (6,180)
  external/                OSM roads/rivers/waterways/buildings/facilities, GEM faults, GLiM lithology, WorldPop
  processed/               model-ready tables: event factors, antecedent rainfall, 250 m factor grid
  DATA_DICTIONARY.md       every column of every final table
models/
  susceptibility/          trained pipeline + isotonic calibrator + metadata (+ per-event scores)
  rainfall_trigger/        exploratory rainfall model (no skill; not used by the live pipeline)
results/
  susceptibility_map/      250 m scored grid (CSV + GeoTIFF) and metadata
  live_forecast/           latest GFS rainfall forecast per tambon (24/48/72 h) and its rain class
  impact_overlay/          per-tambon / per-province / per-facility exposure and combined class
  figures/                 report-ready PNG figures
notebooks/                 the two modelling notebooks (+ susc_utils.py needed to load the pickled model)
scripts/                   data-acquisition and pipeline scripts (see scripts/README.md)
apps/                      FastAPI backend + Next.js frontend that serve the results (see apps/README.md)
tests/                     unit tests for the Earth Engine extraction logic
docs/                      METHODS.md, dataset descriptions, proposal report and slides
```

Also left out of the local submission folder (the project is about 460 MB; everything below is regenerable or an intermediate):

- the OSM roads / rivers / waterways, GEM faults and GLiM lithology GeoJSON layers (about 390 MB), which were only inputs for Earth Engine assets that are already uploaded: `python scripts/download_external_data.py` re-creates them;
- the 250 m factor grid (`data/processed/factor_grid_points/`, 272 MB), an intermediate behind the scored map: `scripts/gee_sample_factor_grid_points.py` re-creates it, and it is only needed to re-run `predict_susceptibility_grid.py`;
- Earth Engine caches and run logs, virtual environments, credentials, and the original inventory spreadsheets.

## Pipeline order

| Step | Script / notebook | Output |
|---|---|---|
| 1 | `scripts/download_external_data.py`, `download_worldpop_population.py`, `clip_tambon_boundaries.py` | `data/external/`, `data/boundary/` |
| 2 | `scripts/generate_paired_negatives.py` | `data/inventory/non_landslide_events.geojson` (one negative per landslide, same date and province) |
| 3 | `scripts/gee_extract_paired_negatives.py` (Earth Engine) for the negatives; landslide rows unchanged | `data/processed/landslide_event_factors.csv` |
| 4 | `scripts/gee_imerg_paired_negatives.py` (Earth Engine); landslide rainfall unchanged | `data/processed/*_antecedent_rainfall.csv` |
| 4b | `scripts/assemble_paired_dataset.py` (strict checks) | `data/processed/landslide_event_factors_cleaned.csv` |
| 5 | `notebooks/landslide_susceptibility_modeling.ipynb` | `models/susceptibility/` |
| 6 | `scripts/gee_sample_factor_grid_points.py` (Earth Engine) → `data/processed/factor_grid_points/` (an intermediate, archived for the submission), then `predict_susceptibility_grid.py` | `results/susceptibility_map/` |
| 7 | `notebooks/rainfall_trigger_threshold.ipynb` (exploratory, no skill; not used downstream) | `models/rainfall_trigger/` |
| 7b | `scripts/compute_rain_percentiles.py` (Earth Engine, ~1 min, one-off) | `data/external/rain_percentiles_24h_tambon.csv` |
| 8 | `scripts/run_live_gfs_forecast.py` (Earth Engine, ~10 s; rerun for a fresh forecast) | `results/live_forecast/latest.json` |
| 9 | `scripts/build_impact_overlay.py`, `scripts/make_figures.py` | `results/impact_overlay/`, `results/figures/` |

Steps 3, 4, 6 and 8 need an Earth Engine service-account key at `scripts/service_account/key.json` (not included; Earth Engine project and quota are the team's). Everything else, including steps 5, 7 and 9, runs from the files in this folder.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# rebuild the impact overlay and figures from the shipped results (~10 s)
python scripts/build_impact_overlay.py
python scripts/make_figures.py

# run the unit tests (need earthengine-api; no network or credentials required)
python -m unittest discover -s tests

# serve the results
cd apps/backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000
cd apps/frontend && npm install && npm run dev        # http://localhost:3000
```

`scripts/build_impact_overlay.py` uses GDAL's Python bindings (`osgeo`); install GDAL through your system package manager (for example `brew install gdal`) and match the Python package version.

## Data and licences

Data sources are summarised in `docs/METHODS.md` and `data/DATA_DICTIONARY.md`. OpenStreetMap-derived layers are © OpenStreetMap contributors (ODbL 1.0); GEM faults are CC BY-SA 4.0; WorldPop is CC BY 4.0; GLiM is free for non-commercial scientific use with citation.
