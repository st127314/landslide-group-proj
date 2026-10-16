# Landslide Susceptibility Mapping and Rainfall-Triggered Early Warning — Southern Thailand

A landslide susceptibility model plus a live-impact view for the 14 southern provinces of Thailand:

1. **Susceptibility model** — where is terrain prone to landslides? (20 conditioning factors, 6,180 landslide + 6,180 paired non-landslide points, spatial cross-validation, calibrated scores, 250 m map.) **This is the validated part of the project.**
2. **Live forecast rainfall** — NOAA GFS rainfall for the next 24 / 48 / 72 h per tambon, judged against each tambon's own rainfall climate (wet-day percentiles P75/P90/P95 from 30 years of CHIRPS). No machine-learning model: an exploratory rainfall model was tried and shown to have no skill (hold-out ROC-AUC 0.34; `notebooks/rainfall_trigger_threshold.ipynb`, kept as a documented negative result).
3. **Live impact overlay and what-if scenario** — terrain factor × local rain class → impact class per tambon, plus a "what if X mm falls?" scenario (no AI assistant, no extra model); with the buildings, critical facilities and people at elevated risk. A transparent triage rule, **not a validated landslide forecast**.

Read `docs/METHODS.md` first for how everything was built and, importantly, its **Known issues** section before relying on any number here.

## Headline results

| | |
|---|---|
| Susceptibility model (selected by nested spatial CV) | `svm_rbf`; nested-CV ROC-AUC 0.934 ± 0.028; spatial hold-out ROC-AUC 0.940 (95% CI 0.932–0.948), PR-AUC 0.904 |
| Map | 1,137,629 cells at 250 m: 64% very low, 7% low, 8% moderate, 11% high, 9% very high |
| Exposure in high / very-high cells (any weather) | 59,663 of 9,385,884 people (0.64%); 4,402 of 426,519 buildings (1.0%); 29 of 3,895 facilities |
| Largest exposed populations | Phuket 16,398 (1.6%), Nakhon Si Thammarat 13,494 (1.0%), Yala 11,941 (2.8%), Ranong 4,306 — **these four have almost no landslide training points, so they are extrapolation** |
| Live forecast shipped (GFS run 2026-10-15 18:00 UTC, quiet weather) | next 24 h: max 18.1 mm; all 1,055 tambons below their own P75 (the fixed 10 mm rule would have flagged 130) |
| Live impact for that run | all 1,053 assessed tambons low; nobody at elevated risk (no unusual rain forecast) |
| What-if scenario (24 h rain, whole south) | 30 mm: 138 tambons high, 24,070 people at elevated risk; 50 mm: 75 very high + 199 high, 41,128 people; 100 mm and above: 43,209 people (classes saturate above each tambon's P95) |

Figures are in `results/figures/`. Terrain scores are relative rankings under 1:1 pseudo-absence sampling, not calibrated real-world probabilities, and the negatives are easy lowland points (Known issue 4). The rain thresholds are local climate percentiles, not calibrated on landslides.

## Folder layout

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
docs/                      METHODS.md, DATA_SOURCES.md, original parameter list (.docx)
```

Left out on purpose (the project is about 460 MB; everything below is regenerable or an intermediate):

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

Steps 3, 4, 6 and 8 need an Earth Engine service-account key at `scripts/service_account/key.json` (not included; Earth Engine project and quota are the author's). Everything else, including steps 5, 7 and 9, runs from the files in this folder.

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

Sources, citations and licences are in `docs/DATA_SOURCES.md`. OpenStreetMap-derived layers are © OpenStreetMap contributors (ODbL 1.0); GEM faults are CC BY-SA 4.0; WorldPop is CC BY 4.0; GLiM is free for non-commercial scientific use with citation.
