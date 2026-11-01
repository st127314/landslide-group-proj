# Methods, results and known issues

## 1. Study area and events

- **Study area:** 14 southern provinces of Thailand (`data/boundary/southern_thailand.geojson`), 1,055 tambons (GADM 4.1, level 3).
- **Landslide inventory:** 6,180 point events, 2000-03-14 to 2025-01-05 (`data/inventory/landslide_inventory.*`). Dates are satellite-image dates of scar-mapping layers, not occurrence dates (Known issue 2). All 23,284 southern landslide records, dated or not, are in `data/inventory/landslide_records_all.geojson` and are used to keep negatives away from real landslides.
- **Non-landslide points (paired design):** 6,180 pseudo-absences, **one per landslide** (`scripts/generate_paired_negatives.py`). Each is placed 2–10 km from its landslide (up to 22.5 km where the ring was full; 15% lie beyond 10 km), in the **same province**, at least 2 km from **every** one of the 23,284 landslide records and at least 250 m from the other negatives, and **takes its paired landslide's date**. The two classes therefore have identical year and province distributions by construction (checked: every pair matches on both), and share regional weather. Classes are 1:1.

## 2. Model 1 — landslide susceptibility

**Factors (20 used).** Terrain from ALOS AW3D30 V4.1 (SRTM 2000 for the earliest events): elevation, slope, aspect, general and profile curvature, TRI, TPI, LS-factor. Hydrology: upstream area, TWI, SPI from HydroSHEDS 15ACC (500 m) for events before 2020 and MERIT Hydro (90 m) for 2020 onward. Soil (OpenLandMap): texture class, clay, sand, bulk density. Vegetation: NDVI from the latest valid Landsat 5/7/8/9 or Sentinel-2 observation in the 90 days *before* the event day. Land cover: SERVIR Mekong RLCMS (previous year) with Dynamic World fallback. Lithology: GLiM level 1 (6 classes occur). Anthropogenic: distance to road and to river/waterway (OSM, 20 km data buffer). All temporal factors use only information from strictly before the local event day.

**Not in the model:** `dist_to_stream` (wrong scale before 2020, Known issue 5), `drainage_density` and `dist_to_fault` (94% and 71% blank), fault density and soil organic carbon (never produced). The fault layer is the GEM *active* fault database only.

**Training protocol.** 12,360 rows. Spatial blocks of 0.5° with a 5 km embargo around the hold-out fold; hold-out = one grouped fold chosen only from class share and size (2,628 test rows: 1,123 landslides, 1,505 negatives; 8,280 training rows, 4,284 / 3,996, after 1,452 rows were embargoed). Eleven algorithms were tuned with nested spatial cross-validation and the best nested-CV ROC-AUC chosen: **`svm_rbf`** (nested-CV ROC-AUC 0.934 ± 0.028). An isotonic calibrator maps raw scores to calibrated scores; stored decision threshold 0.302 (raw) / 0.529 (calibrated).

**Hold-out performance of the selected model.** ROC-AUC **0.940** (95% CI 0.932–0.948), PR-AUC 0.904, balanced accuracy 0.829, sensitivity 0.986, specificity 0.673, Cohen's κ 0.625 (`models/susceptibility/model_metadata.json`, `results/figures/3_model_comparison.png`). The cross-validation estimate (0.934) and the hold-out (0.940) now agree, and all eleven models fall within 0.87–0.94 on the hold-out (top four within 0.003 in CV), which is the pattern expected once leakage is removed. Selection used the nested CV, not the hold-out fold.

**Map.** The factor stack was point-sampled on a 250 m grid inside the boundary (148 of 150 tiles contain points; the other two clip the boundary with no grid point), scored and calibrated: 1,137,629 cells, 62.8% very low, 7.2% low, 7.4% moderate, 11.2% high, 11.4% very high (calibrated-score bins 0.2/0.4/0.6/0.8; 27.2% of cells exceed the decision threshold). Lithology and land cover are converted from the grid's numeric codes to the class names used in training before scoring. Output: `results/susceptibility_map/` (CSV and GeoTIFF).

## 3. Live rainfall forecast (GFS) — and the rainfall model that was dropped

**Live forecast** (`scripts/run_live_gfs_forecast.py`, about 10 s, no model). For each of the 1,055 tambons it sums NOAA GFS forecast rainfall over the next 24, 48 and 72 hours **counted from now** (not from the model's initialisation time), using Earth Engine's `NOAA/GFS0P25` (hourly steps to +120 h, `precipitation_rate` × 3600 s per hour, value of the 0.25° ≈ 28 km cell containing each tambon's representative point). The 24 h total is classed two ways:

- **Local classes (drive the live impact).** Against the tambon's own wet-day rainfall percentiles: below P75, P75–P90, P90–P95, above P95. The thresholds come from `scripts/compute_rain_percentiles.py`: 30 years (1991–2020) of CHIRPS daily rain, averaged onto the 0.25° GFS grid so they describe cell-average rainfall like the forecast, wet day = at least 1 mm (53% of days on average), percentiles of those wet days, sampled at each tambon's point (`data/external/rain_percentiles_24h_tambon.csv`). Typical values (median tambon): P75 15.7 mm, P90 26.6, P95 37.6, P99 66.5; the wettest Andaman-side tambons need roughly twice as much as the driest to count as unusual. A wet-day P90 is exceeded on about 5% of all days, so "above P95" means roughly 10 days a year, not an extreme event.
- **Absolute classes (kept for reference).** Light < 10 mm, moderate 10–35, heavy 35–90, very heavy ≥ 90 mm (assumed thresholds, editable in the script). `RAIN_BASIS` in `build_impact_overlay.py` switches the overlay between the two.

Neither set is calibrated on landslide records. Local percentiles say **how unusual the rain is for the place**, not whether it triggers landslides; they are built from observed CHIRPS while the forecast is GFS, which has its own biases, so the two are only roughly comparable. Latest run in the shipped results: GFS 2026-10-15 18:00 UTC, window 2026-10-16 02:00 → 10-17 02:00 UTC; heaviest forecast 18.1 mm, median 3.5 mm. Against local normal **all 1,055 tambons are below P75** (a quiet day), whereas the fixed 10 mm rule would have called 130 of them "moderate". Output: `results/live_forecast/latest.json`.

**Why there is no machine-learning rainfall trigger.** An exploratory model was fitted on IMERG antecedent rainfall (`notebooks/rainfall_trigger_threshold.ipynb`, `models/rainfall_trigger/`). It has **no skill**: nested CV picks `random_forest` (CV ROC-AUC 0.74) but the spatial hold-out gives **0.34, below chance**, and all five candidates score 0.31–0.54. That is the expected outcome here: a negative shares its landslide's date and lies within about one IMERG cell (~10 km), so rainfall is nearly identical within a pair (median absolute difference 0.44 mm for 3-day and 3.0 mm for 30-day rain; median 30-day rain 55 mm for landslides vs 58 mm for negatives; univariate ROC-AUC 0.53 / 0.51), and the landslide "dates" are satellite-image dates (Known issue 2). The earlier non-paired design gave a hold-out AUC near 0.90 (XGBoost), which most likely reflected sampling artefacts rather than rainfall. The notebook and model are kept only as this documented negative result; **the live pipeline does not use them.** Calibrating a real rainfall threshold needs true occurrence dates.

## 4. Live impact overlay

`scripts/build_impact_overlay.py` joins, per tambon:

| Input | Use |
|---|---|
| Susceptibility grid (1.14 M cells) | % of cells high/very high → **terrain tier** (< 15% low, 15–40% moderate, ≥ 40% high) |
| `results/live_forecast/latest.json` | GFS 24 / 48 / 72 h rainfall, its class against the tambon's local percentiles (and the fixed class) |
| OSM buildings (426,519), OSM facilities (3,895), WorldPop 2020 constrained (9.39 M people) | each item takes the class of its nearest grid cell (≤ 400 m); counts per class and in high/very-high |

**Live impact class** = terrain factor × 24 h local rain-class index. Terrain factor: low tier 1, moderate 2, high 3 (tier from the share of the tambon's 250 m cells that are high/very high: < 15%, 15–40%, ≥ 40%). Rain index: below P75 = 0, P75–P90 = 1, P90–P95 = 2, above P95 = 3. Product bins: 0–1 low, 2–3 moderate, 4–6 high, ≥ 7 very high:

| rain \ terrain tier | low | moderate | high |
|---|---|---|---|
| below P75 | low | low | low |
| P75–P90 | low | moderate | moderate |
| P90–P95 | moderate | high | high |
| above P95 | moderate | high | very high |

It is a product, not a sum, on purpose: rain alone creates no risk on terrain that cannot slide (flat ground never exceeds "moderate"), no unusual rain means "low" everywhere, and "very high" needs the steepest tier **and** rain above that tambon's P95. (A first version added the two scores; the what-if scenario below showed that made every tambon "high" in a heavy storm, so it was replaced.) The rule is a **transparent triage rule, not a calibrated probability and not a validated landslide forecast**: the terrain half comes from a model with a held-out ROC-AUC of 0.94, the rain half from local rainfall percentiles (not calibrated on landslides). **People at elevated risk** = people living in high/very-high susceptibility cells of tambons whose live impact class is high or very high (same definition for buildings and facilities). Two sliver tambons contain no grid cell and are `not_assessed`.

**Results for the shipped run (a quiet-weather snapshot):** all 1,053 assessed tambons are *low* (no tambon's forecast rain is unusual for its climate), 2 not assessed; nobody is at elevated risk. The terrain tiers themselves (753 low, 194 moderate, 106 high) are unaffected by the weather. Independent of the weather, 71,402 of 9,385,884 people (0.76%), 5,983 of 426,519 buildings (1.4%) and 34 of 3,895 facilities live in high/very-high susceptibility cells; largest populations: Phuket 21,320 (2.1% of the province), Nakhon Si Thammarat 13,625 (1.0%), Yala 12,998 (3.1%), Ranong 5,239 (1.5%). Phuket, Nakhon Si Thammarat, Yala and Ranong have almost no landslide training points, so these are **extrapolation** (Known issue 3). GFS cells are ~28 km wide, so neighbouring tambons often share one rainfall value.

Outputs: `results/impact_overlay/impact_overlay_by_tambon.csv`, `..._by_province.csv`, `facility_exposure.csv`, `impact_overlay.json` (served by the API).

### What-if scenario (no extra model)

`GET /api/impact/scenario?rain_24h_mm=X[&province=NAME]` (and the "What-if rainfall scenario" panel on the Early Warning page) answers "what if X mm falls in 24 hours?" It replaces the 24 h rainfall of every tambon in scope (all, or one province; other provinces keep the live forecast) with X and re-applies the rule above to the stored overlay (`apps/backend/app/scenario.py`). It uses only numbers already in `impact_overlay.json` (terrain tier, each tambon's P75/P90/P95, exposure on high/very-high ground), so it needs no Earth Engine call and answers in milliseconds; with no parameter it reproduces the overlay's own classes exactly (checked: 1,055 of 1,055 tambons identical). Input is limited to 0–1,500 mm. Examples on the shipped data:

| Scenario (24 h rain) | Tambons very high / high / moderate | People at elevated risk | Buildings | Facilities |
|---|---|---|---|---|
| live forecast (max 18 mm) | 0 / 0 / 0 | 0 | 0 | 0 |
| 30 mm, whole south | 2 / 152 / 784 | 30,879 | 2,158 | 21 |
| 50 mm, whole south | 81 / 215 / 756 | 51,537 | 5,360 | 26 |
| 100 mm (or 150, 250), whole south | 106 / 194 / 753 | 54,022 | 5,362 | 26 |
| 150 mm in Yala only | 14 / 16 / 28 | 12,525 | 6 | 8 |
| 150 mm in Phuket only | 2 / 7 / 8 | 6,353 | 1,036 | 6 |

Properties to keep in mind: a scenario applies the same rain to every tambon in scope (real storms are patchy); because classes are percentiles, they **saturate** once rain passes a tambon's P95 (about 40–70 mm in the south), so 100 mm and 250 mm give the same answer; and the exposure counts only people, buildings and facilities on high/very-high susceptibility ground (54,022 of the 71,402 such people sit in tambons that can reach "high" or above).

## 5. Changes from the initial design

| | Before | After |
|---|---|---|
| Negatives | random points, date copied from the *nearest* landslide; 1,083 (17.5%) within 2 km of an undated landslide record; 10.8% dated 2020+ vs 1.5% of landslides | paired ring sample: 0 within 2 km of any record, identical year and province distribution |
| `dist_to_stream` | in the model; ≈ 2×10⁷ for 94% of events, acting as a date proxy | excluded |
| Selected susceptibility model | gradient boosting: CV 0.961, hold-out 0.919 | `svm_rbf`: CV 0.934, hold-out 0.940 (CV and hold-out agree) |
| Rainfall component | ML trigger, hold-out AUC 0.90 (most likely a sampling artefact), driven by IMERG + a +3 h GFS nudge | none: GFS 24 h forecast rain against each tambon's CHIRPS wet-day percentiles (the ML model was shown to have no skill, 0.34) |
| People in high/very-high cells | 159,933 (1.7%) | 71,402 (0.76%) |
| Live impact class | terrain tier + ML trigger class (a sum) | terrain factor × local 24 h rain class (a product) |

The initial design's problems, found by auditing the original inventory workbook, are documented below where they still apply.

## 6. Known issues (read before citing numbers)

Listed roughly by how much they could change a conclusion.

1. **There is no calibrated rainfall threshold.** The rain classes behind the live impact are local climate percentiles (how unusual) or assumed absolute thresholds, neither calibrated on landslides, and the exploratory ML trigger has no skill (Section 3). Two causes: the paired design removes between-class rainfall differences, and the landslide "dates" are image dates (issue 2), so even an ideal design would be fitting rainfall around the wrong day. A real threshold needs true occurrence dates. The live impact class is therefore a triage aid, not a landslide forecast.
2. **The inventory dates are satellite-imagery dates of scar-mapping layers, not occurrence dates.** The original workbook (`LANDSLIDE_INVENTORY_MAP.xlsx`, not included) has no event date, only `YEAR_DATA` (Thai year 2563–2568) and free-text `REMARK`/`REMARK_2` that name the mapping layer (`SNI_scar_ge.kmz` 2,262 events, `KBI scar13.kmz` 1,851, `Scar_CHP_New.kmz` 919, `PNA_Scar08022022.kmz` 911, `Scar_PLG.kmz` 144, `Scar_Trang.kmz` 92) and an image date; `date` was parsed from that string. The 6,180 points fall on only **164 distinct dates**, 86% on 15 dates (1,568 on 2017-03-04), 72% in February–April (clear-sky imaging season). An internal audit table (not included) shows that 6,178 of 6,180 dates equal a date in the remark, but every ambiguous slash string (1,784 events) was read month-first, while Chumphon (`Scar_CHP_New`: 204 day-first vs 1 month-first strings) and Trang (136 vs 0) are day-first, so **≈ 985 events (16%) probably have day and month swapped**, and 371 day-first records were dropped by the parser and are recoverable. Rainfall cut-offs are local-midnight proxies for all 6,180 events.
3. **Landslide records exist in only 6 of the 14 provinces.** Only records with a full date were kept (6,180 of 6,921 in those provinces); ≈ 16,400 year-only or undated records elsewhere were dropped (Nakhon Si Thammarat 8,596, Yala 3,964, Ranong 2,061, Songkhla 1,555, Phuket 95, Satun 72, Narathiwat 59, Pattani 46). Landslide points: Surat Thani 2,265, Krabi 1,843, Chumphon 918, Phang Nga 910, Phatthalung 130, Trang 110, Nakhon Si Thammarat 3, Ranong 1. Negatives now sit in the same province as their landslide, which removes the "which province" shortcut inside the sample, but the **map and exposure figures for the other provinces (notably Phuket, Yala, Songkhla, Narathiwat, Pattani, Satun, and Nakhon Si Thammarat/Ranong) are extrapolation**. Date information in the workbook for the 23,369 southern records: a full date for 28%, a bare year for 37% (all Nakhon Si Thammarat), nothing usable for 35%; `YEAR_DATA` cannot fill the gaps (digitisation batch year; equals the remark year for 1.3%). A static susceptibility model does not need exact dates, so the undated records could be added to it in future.
4. **Scores are relative and the task is easy.** Pseudo-absences are lowland points (median elevation 70 m vs 323 m for landslides; slope 7° vs 29°), so a high AUC largely reflects terrain contrast between mapped scars and random flat ground. Scores rank terrain under 1:1 sampling; they are not real-world probabilities, and AUC overstates real-world skill. Spatial CV with a 5 km embargo is stricter than random CV but does not remove this.
5. **Factors not used or still imperfect.** `dist_to_stream` is excluded because the HydroSHEDS branch (all pre-2020 events) returns ≈ 2.1×10⁷ instead of metres (only ≈ 750 events from 2020 have sane values); the raw table still contains the wrong values and the extraction code was not changed. Upstream area, TWI and SPI come from the same two hydrology sources (HydroSHEDS 500 m before 2020, MERIT 90 m from 2020) but, because pairs now share dates, both classes use the same source for the same year, so this cannot act as a label leak. `drainage_density` exists only for the MERIT-era events; `dist_to_fault` is blank beyond the 20 km search and uses active faults only; fault density and organic carbon were not produced. The team's internal planning document (factor list; not included) describes the plan; where the implementation differs (GLiM lithology instead of an ADPC asset, SERVIR land cover with Dynamic World fallback), this file is authoritative.
6. **Outliers kept as sampled:** SPI up to 3.4×10⁶, general curvature down to −1,230. Tree models tolerate these; the SVM / linear branches clip them (IQR winsorising fitted on training folds).
7. **Missing values** in the cleaned table: NDVI 446, soil 132, lithology 46, slope/aspect/LS-factor/TWI/SPI 17, land cover 10, upstream area 5 (imputed inside the pipelines).
8. **Forecast uncertainty.** GFS is a global model on a ~28 km grid: it smooths local convective extremes and any single run can be wrong in timing and amount; each hour's rainfall is approximated as the instantaneous rate at that forecast hour × 3600 s; the local percentiles come from CHIRPS observations, so the comparison with GFS is approximate. The shipped live results are a snapshot of one run (2026-10-15 18:00 UTC) and must be regenerated (`run_live_gfs_forecast.py` then `build_impact_overlay.py`) to be "live".
9. **Exposure vintage.** WorldPop 2020 (constrained, UN-adjusted); OSM snapshot 2026-09-08 (completeness varies). Buildings, facilities and population inherit the class of the nearest 250 m cell.
10. **Not reproducible without credentials.** Earth Engine steps need a service-account key and project quota. Extraction was slow under quota (several requests timed out and were retried or split); the scripts are resumable and their merges are strict.

## 7. Reproducing a number

Every headline number comes from a file in `results/` or `models/`; `FILE_MANIFEST.csv` lists SHA-256 checksums so a reviewer can confirm they are looking at the files this document describes. `scripts/README.md` lists the order and commands for each step.
