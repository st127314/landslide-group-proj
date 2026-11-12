# Final stage: what was added, how, and what it showed

This folder is the progress-report project (`updated project files`) plus the final-stage work planned in
**Table 10 (Remaining work)** of `progress report/Progress_report_landslide.pdf`. All new code is in
[`final_pipeline/`](final_pipeline/); all new results are in [`results/final/`](results/final/).

**In one paragraph.** We removed the NDVI scar leakage, thinned duplicate landslides, replaced the broken road and
river distances in the map grid, tested harder negative samples, re-selected the production model with a stricter,
map-based version of the success rule, rebuilt the map with an uncertainty layer, and added a model registry with a
promotion gate. The honest outcome: once leakage and the grid's distance errors are removed and decision value is
measured on the map itself, **the models are close to equivalent (about 75–80% of validation landslides in the top 20%
of the area), and on the held-out fold neither the selected model nor logistic regression reaches the 70% target
(63%).** The progress report's 0.940 ROC-AUC and 87.9% decision value were inflated by NDVI leakage and by scoring
landslides with point factors rather than map factors.

---

## 1. How to run

```bash
python -m venv .venv && .venv/bin/pip install -r final_pipeline/requirements.txt   # scikit-learn==1.9.0
PYTHON=.venv/bin/python final_pipeline/run_all.sh                                    # about 2 hours on 4 cores
```

* **scikit-learn must be 1.9.0.** Other versions split `StratifiedGroupKFold` differently, which changes every fold
  and every number (checked: 1.6.1 gives a different hold-out fold).
* Inputs not in the public repo: the 250 m factor grid (`data/processed/factor_grid_points/`), the private
  inventory/boundary/exposure data (`data/inventory`, `data/boundary`, `data/external`) and the Geofabrik extract
  (`data/external/osm/thailand-free.shp.zip`, downloaded from https://download.geofabrik.de/asia/thailand-latest-free.shp.zip).

| Step | Script | Runtime |
|---|---|---|
| 01 | `01_osm_distances.py` — road/river distances from OSM | 4 min |
| 02 | `02_thin_duplicates.py` — near-duplicate thinning | seconds |
| 03 | `03_negative_designs.py` — matched negatives, negative-distance sensitivity | 65 min |
| 04 | `04_model_selection.py --data points` — nested spatial CV, 5 candidates | 28 min |
| 04b | `04b_map_decision_value.py` — map-based decision value, success rule, held-out test | 7 min |
| 05 | `05_final_model_map.py --data points` — final model, map, uncertainty, grid size | 2 min (GB) / 32 min (SVM) |
| 07 | `07_exposure_summary.py` — terrain tiers and exposure on the new map | 1 min |
| 06 | `06_model_registry.py` — registry and promotion gate | seconds |

---

## 2. Remaining-work items: status

| Table 10 task | Status | Where |
|---|---|---|
| Re-extract road and river distances for the 119 grid tiles | **Done** (locally from OSM; all tiles replaced, see 3.1) | `01_osm_distances.py`, `common.load_grid` |
| Apply near-duplicate thinning and re-evaluate | **Done** | `02_thin_duplicates.py` |
| Environment-matched negatives (E4) | **Done** (on the 250 m grid) | `03_negative_designs.py` |
| Sensitivity: negative distance, grid size | **Done** | `03_negative_designs.py`, `05_final_model_map.py` |
| Uncertainty map from fold spread | **Done** | `05_final_model_map.py` |
| Reselect the production model; apply the success rule | **Done** (map-based rule, see 3.4) | `04_model_selection.py`, `04b_map_decision_value.py` |
| Model registry with metadata and promotion gate | **Done** | `06_model_registry.py`, `models/registry/` |
| Schedule the GFS refresh | **Written, not enabled** (needs the server) | `apps/deploy/gfs-refresh.sh`, `landslide-gfs-refresh.{service,timer}`, `install-gfs-timer.sh` |
| Recompute NDVI as an annual composite | **Script written, not run** (needs Earth Engine credentials); NDVI **dropped** from the model meanwhile | `gee_ndvi_annual_composite.py` |
| Repository secrets, deploy job, DNS and HTTPS | **Not done** (needs the team's GitHub, AWS and DNS accounts); steps unchanged in `apps/deploy/README.md` | — |
| Final report and presentation | Not part of this folder | — |

---

## 3. What was added, how, and the results

### 3.1 Road and river distances recomputed (step 01)

**How.** The same source as the training table: Geofabrik OSM shapefiles, all road classes
(`gis_osm_roads_free_1`, 325,202 lines) and all waterway classes (`gis_osm_waterways_free_1`, 11,151 lines), clipped to
the study area plus about 20 km, projected to UTM 47N; the nearest line is found with a shapely STRtree, capped at
20 km like Earth Engine's `searchRadius`.

**Validation first.** On the 12,360 training points the local distances reproduce the Earth Engine values almost
exactly (Spearman 0.998 for roads and 0.9999 for rivers; median difference 13 m, i.e. pixel precision).

**Finding.** The Earth Engine grid export was not only incomplete (77% of cells empty) but also **wrong where it had
values**: on those cells it agrees poorly with the true distances (Spearman 0.14 for roads, 0.23 for rivers; median
error 2.3 km and 3.1 km). The final grid therefore uses the local distances for **every** cell, not only the gaps
(`common.load_grid`). The progress-report map was scored with these faulty distances.

### 3.2 Near-duplicate thinning (step 02)

Landslides closer than 30 m were grouped (single linkage); each group keeps its earliest record, and **each dropped
landslide also loses its paired negative**, so the classes stay balanced and every negative keeps its pair.

| | Value |
|---|---|
| Landslide pairs within 30 m | 335 (the progress report counted 337 with a slightly different distance formula) |
| Duplicate groups (largest) | 264 (6 records) |
| Landslides / negatives dropped | 312 / 312 |
| Rows before → after | 12,360 → **11,736** (5,868 per class) |

### 3.3 Negative-sampling designs (step 03): matched negatives and negative distance

**How.** Earth Engine could not extract factors at new points, so every design draws its negatives from the 250 m
grid, and **each landslide takes the factors of its own grid cell**. Both classes then come from the same layers and
sources and differ only in how negatives are chosen. Only date-independent factors are used (no NDVI, no land cover).
Every negative is at least 2 km from all 23,284 recorded landslides. Scored with the fixed progress-report LR and SVM
settings on buffered spatial folds.

| Design | Negatives: median elevation / slope | ROC-AUC (LR / SVM) | Decision value, top 20% (LR / SVM) |
|---|---|---|---|
| Random (study area) | 38 m / 4° | 0.94 / 0.95 | 80% / 85% |
| Paired ring 2–10 km, same province (current design) | 73 m / 7° | 0.87 / 0.88 | 75% / 78% |
| Ring 2–5 km | 68 m / 7° | 0.90 / 0.89 | 81% / 76% |
| Ring 5–10 km | 71 m / 7° | 0.90 / 0.89 | 82% / 82% |
| Ring 10–20 km | 61 m / 6° | 0.94 / 0.94 | 76% / 73% |
| **Environment-matched** (same province, slope band, elevation band) | **332 m / 26°** | **0.59 / 0.59** | **38% / 52%** |

Landslides: median 332 m and 26°. 454 of 5,867 matched draws needed a relaxed match (same bands, other province).

**What we learned.**
* **Skill on difficult ground is low.** When negatives share the landslides' slope and elevation, ROC-AUC falls to
  0.59: beyond terrain, the remaining factors add only weak discrimination. Most of the reported skill is the
  hillslope-versus-lowland contrast the progress report suspected (E4).
* **Training on matched negatives makes a poor map** (38–52%): the model learns only within-terrain differences and
  loses the terrain signal that dominates where landslides happen. The paired design is kept for the production model.
* **Negative distance has no consistent effect** (2–5, 5–10, 10–20 km): fold-to-fold variation is larger than the
  differences between rings.

### 3.4 Production model re-selected (steps 04 and 04b)

**Data.** The thinned table (11,736 rows), event-date factors, **NDVI removed** (scar leakage, progress report 4.1).
19 factors.

**How.** The notebook's nested spatial search (5 buffered outer folds, 3 buffered inner folds, 8 random-search
iterations, ROC-AUC) for logistic regression, SVM (RBF), random forest and histogram gradient boosting, plus the
frequency-ratio baseline. Same 0.5° blocks, 5 km buffer and hold-out rule as before (hold-out fold 3, 7,869
training / 2,463 test rows).

**A correction to the decision-value metric (04b).** Step 04 scored each validation landslide with its own point
factors against the grid cells, as the progress report did. But the map shows grid-cell scores, and the grid's factors
at the same place differ (2026 land cover instead of the event year; ALOS/MERIT instead of SRTM/HydroSHEDS for older
events). Scoring each landslide **at its own map cell** gives the decision value a user of the map actually sees,
and it is lower for every model:

| Model | ROC-AUC (5 outer folds) | Decision value, point factors (04) | **Decision value, map cell (04b)** | Folds beating LR on the map |
|---|---|---|---|---|
| Logistic regression (baseline) | 0.915 ± 0.036 | 84.9% | 77.2% | — |
| Frequency ratio (baseline) | 0.905 ± 0.045 | 80.7% | 79.5% | 4 of 5 ✅ |
| **Gradient boosting** | 0.903 ± 0.055 | 86.3% | **79.6%** | **4 of 5 ✅** |
| SVM (RBF) | 0.912 ± 0.040 | 88.8% | 76.1% | 3 of 5 ❌ |
| Random forest | 0.898 ± 0.065 | 87.1% | 75.1% | 3 of 5 ❌ |

**Success rule (fixed before the run).** A candidate replaces logistic regression only if it has the higher decision
value in at least 4 of 5 folds and its mean ROC-AUC is not lower by more than LR's fold SD; among passing candidates
the highest mean decision value wins. On the map-based metric, **gradient boosting is selected**, with frequency ratio
virtually tied (79.5%). On the point-based metric the SVM would have won; its advantage came from the point/grid factor
mismatch.

**Held-out fold (used once, after selection):**

| | ROC-AUC | PR-AUC | **Map decision value (top 20% / 10%)** | Brier | Calibration slope |
|---|---|---|---|---|---|
| Gradient boosting (selected) | 0.857 | 0.765 | **62.7% / 34.3%** | 0.160 | 0.54 |
| Logistic regression | **0.893** | **0.821** | **63.6% / 30.8%** | **0.144** | **0.99** |

The held-out fold **does not confirm** gradient boosting: logistic regression is at least as good and much better
calibrated, and **neither model reaches the 70% target** on unseen ground. The rule was followed as planned, so the
registry holds gradient boosting, but **we recommend the team treat logistic regression as an equally valid, simpler
and better-calibrated production choice**. To switch: `python final_pipeline/05_final_model_map.py --data points
--model logistic_regression`, then rerun `07_exposure_summary.py` and `06_model_registry.py` (the gate then compares
the new candidate with the current production model on the same folds).

**E3 rerun on the final data** (fixed LR, outer-fold ROC-AUC): all factors 0.919; without terrain 0.872 (−0.046);
removing hydrology, soil, land cover, lithology or distances changes it by at most ±0.004. Terrain still carries the
signal.

### 3.5 Final map, uncertainty and grid size (step 05)

* **Model:** gradient boosting refitted on all 11,736 rows; `models/final/gradient_boosting_final_pipeline.joblib`,
  metadata in [`models/final/final_model_metadata.json`](models/final/final_model_metadata.json).
* **Classes are relative, by grid percentile:** very high = top 10% of cells, high = next 10%, moderate 15%, low 25%,
  very low 40%. High plus very high is exactly the "top 20%" of the decision-value target. Scores are not
  probabilities (isotonic calibration made them worse in the progress report).
* **Same file format as before** (`results/susceptibility_map/susceptibility_grid_points.csv`, `.tif` with a percentile
  band and an uncertainty band, `susceptibility_map_metadata.json`), so `build_impact_overlay.py` and the app read it
  unchanged. Note: `calibrated_probability` now holds the percentile (name kept for app compatibility).
* **Uncertainty** (the five outer-fold models score the grid; SD of their percentile ranks): median SD 0.062 (90th
  percentile 0.133). Ranks are most stable on high-risk ridges and least stable on the low-lying eastern plain, where
  differences between near-zero scores are noise. All five models agree on the class for 50% of cells; of the cells
  any model puts in the top 20%, 50% are put there by all five.
* **Grid-size sensitivity** (decision value on the validation blocks with cells aggregated): 250 m 79.6%, 500 m 77.1%,
  1 km 77.9%. Coarsening costs about 2 points, so 250 m is a reasonable map resolution.
* Figures: [`results/final/figures/final_susceptibility_map.png`](results/final/figures/final_susceptibility_map.png),
  [`final_uncertainty_map.png`](results/final/figures/final_uncertainty_map.png).

### 3.6 Exposure on the new map (step 07)

`build_impact_overlay.py` also needs a live GFS forecast (Earth Engine) and GDAL, so the weather-independent parts were
recomputed with the same rules (tier from the share of high/very-high cells: < 15% low, 15–40% moderate, ≥ 40% high;
each item takes the class of its nearest cell within 400 m).

| | Progress-report map | Final map |
|---|---|---|
| Tambon tiers (low / moderate / high) | 753 / 194 / 106 | 799 / 166 / 88 |
| People on high / very-high cells | 71,402 | 70,561 |
| Buildings on high / very-high cells | 5,983 | 2,925 |
| Facilities on high / very-high cells | 34 | 34 |
| Largest populations on high / very-high ground | Phuket, Nakhon Si Thammarat, Yala, Ranong | Yala 28,558; Nakhon Si Thammarat 14,652; Phuket 8,847; Ranong 5,019 |

Yala, Phuket, Nakhon Si Thammarat and Ranong have almost no landslide labels, so these exposure figures are
extrapolation (Known issue 3 in `docs/METHODS.md`).

### 3.7 Model registry and promotion gate (step 06)

`models/registry/<version>/` holds a copy of each model and its metadata (features, hyperparameters, SHA-256 of the
model and of the training data, scikit-learn version, git commit, fold metrics). `index.json` lists versions and their
status; `production.json` is the pointer the API can load.

**Gate.** (1) A candidate is eligible only with no blocked feature (`ndvi`, the scar leakage) and the 70% map-based
target met in at least 4 of 5 folds. (2) If the current production model is not eligible, an eligible candidate
replaces it. (3) Otherwise the production model's specification is refitted on the candidate's folds and the success
rule decides.

**Result:** v1 (progress-report SVM with NDVI) → archived; **v2 (gradient boosting, no NDVI) → production**, because v1
uses the blocked feature and v2 meets the target in 4 of 5 folds ([`results/final/06_promotion_gate.json`](results/final/06_promotion_gate.json)).

### 3.8 Deployment additions

* **GFS refresh** every 6 hours (04:30, 10:30, 16:30, 22:30 UTC, after each GFS cycle is published): `gfs-refresh.sh`
  runs `run_live_gfs_forecast.py` then `build_impact_overlay.py` with a lock file; systemd service and timer files;
  `install-gfs-timer.sh` installs them on the server. Not enabled: it needs the server, its Python environment and the
  Earth Engine key.
* **NDVI annual composite** (`gee_ndvi_annual_composite.py`): median of all valid Landsat/Sentinel-2 NDVI in the
  calendar year before each event year, with the project's own cloud masks; resumable, chunked, with retries. Not run:
  no Earth Engine credentials on the machine used.

---

## 4. Why the numbers are lower than in the progress report

| Progress report | Final stage | Main reason |
|---|---|---|
| Held-out ROC-AUC 0.940 (SVM) | 0.857 (GB) / 0.893 (LR) | NDVI removed (it measured the scar itself); duplicates removed |
| Held-out decision value 87.9% | 62.7% (GB) / 63.6% (LR) | Measured at the landslide's own **map** cell instead of with its point factors; correct road distances in the map; NDVI removed |
| Production model SVM | Gradient boosting (≈ LR, ≈ frequency ratio) | On the map-based metric the SVM no longer beats LR |

Lower but more honest: these are the numbers the map can actually deliver on unseen ground.

---

## 5. Limitations

1. **NDVI is excluded, not fixed.** The annual composite that would restore a leakage-free vegetation signal needs
   Earth Engine (script ready). The current model has no vegetation factor apart from land cover.
2. **The 70% target is not met on the held-out fold** (63% for both models), although it is met in 4 of 5 CV folds.
   One CV fold (fold 2) is weak for every model (38–51%), so performance depends strongly on the region.
3. **Model choice is within noise.** Gradient boosting, frequency ratio and logistic regression differ by about 2
   points on the map, less than the fold spread; the held-out fold favours LR. The rule picked GB; LR is defensible.
4. **Gradient boosting is poorly calibrated** (held-out calibration slope 0.54); scores are presented as percentile
   classes, not probabilities.
5. **Point and grid factors differ** at the same place (land cover year, DEM/hydrology source), which is why
   point-based decision value overstated the map's skill. A training table extracted from the same grid layers would
   remove the mismatch.
6. **Matched-negative and ring experiments use grid factors** (250 m, 2026 reference date, no NDVI or land cover), so
   they compare sampling designs fairly with each other but not directly with the event-date model.
7. **OSM is a newer snapshot** (Geofabrik, 11 Nov 2026) than the training table's (September 2026); the validation
   shows a 13 m median difference, so the effect is negligible.
8. **Labels remain in 6 of 14 provinces;** the map elsewhere is extrapolation, and the exposure totals are dominated by
   provinces without labels (Yala, Phuket, Nakhon Si Thammarat).
9. **Event dates are image dates;** the rainfall-trigger model remains out of scope (unchanged from the progress report).
10. **Raster seams:** a few 250 m cells along tile edges fall into empty raster pixels (faint lines in the GeoTIFF and
    figures); the CSV map is complete.
11. **The live overlay was not rebuilt** here (needs the forecast and GDAL); run `build_impact_overlay.py` on the server.
12. **Not done:** repository secrets, the automated deploy job, DNS and HTTPS (need the team's accounts).

---

## 6. Files added or changed in `final_stage`

| Path | What |
|---|---|
| `FINAL_STAGE.md` | this document |
| `final_pipeline/common.py` | shared helpers: spatial folds, models and search spaces, frequency ratio, grid loader with OSM distances |
| `final_pipeline/01_…07_*.py`, `04b_*.py` | the pipeline steps above |
| `final_pipeline/gee_ndvi_annual_composite.py` | Earth Engine script, not run |
| `final_pipeline/run_all.sh`, `requirements.txt` | run everything; pinned scikit-learn |
| `apps/deploy/gfs-refresh.sh`, `landslide-gfs-refresh.service`, `.timer`, `install-gfs-timer.sh` | scheduled GFS refresh |
| `data/processed/final/` | thinned table (public); OSM distances, grid designs, grid provinces (private, git-ignored) |
| `data/external/osm/` | Geofabrik download (git-ignored) |
| `results/final/` | all JSON/CSV results, logs, figures; uncertainty grid (git-ignored) |
| `results/susceptibility_map/` | the final map in the app's format (git-ignored, as before) |
| `models/final/`, `models/registry/` | final model and registry (model files git-ignored; metadata tracked) |
| `.gitignore` | whitelists the new public parts |
| `data/inventory`, `data/boundary`, `data/external` | private data copied from `data 2` so the scripts run (git-ignored) |
