# Data dictionary

All coordinates are WGS 84 (EPSG:4326) unless stated. Missing values are blank. Row counts and checksums: `../FILE_MANIFEST.csv`. How each factor was derived: `../docs/METHODS.md` §2 and `../docs/DATA_SOURCES.md`.

## data/inventory/

**`landslide_inventory.csv` / `.geojson`** — 6,180 landslide points.
| Column | Meaning |
|---|---|
| `inventory_id` | Unique event id (joins to `landslide_event_antecedent_rainfall.csv`) |
| `latitude`, `longitude` | Event location |
| `date` | Event date (day resolution), 2000-03-14 … 2025-01-05 |
| `remark_year_mismatch` | Source-record flag: remark year differed from recorded date |

**`non_landslide_events.geojson`** — 6,180 paired pseudo-absence points, one per landslide (`scripts/generate_paired_negatives.py`). Each lies 2–10 km from its landslide (up to 22.5 km where the ring was full), in the same province, ≥ 2 km from all 23,284 landslide records and ≥ 250 m from the other negatives, and **takes its paired landslide's date**.
| Property | Meaning |
|---|---|
| `Event_ID` | `NL_0001` … (same order as the landslides) |
| `Geohaz_E` | Always `NonLandslide` |
| `DATE`, `date_parsed` | The paired landslide's date |
| `landslide` | 0 |
| `paired_landslide_id`, `nearest_landslide_event_id` | `inventory_id` of the paired landslide (both fields hold the same value) |
| `pair_distance_km`, `distance_to_nearest_landslide_km` | Distance to the paired landslide (same value in both) |
| `source` | `paired_ring_same_date` |

**`landslide_records_all.geojson`** — all 23,284 southern landslide records (`inventory_id`, `latitude`, `longitude`, `date` = year-only placeholder for undated records, `date_precision`, `remark_year_mismatch`). Used only as the exclusion set when generating negatives; most records are undated and are not training events.

## data/processed/

**`landslide_event_factors_cleaned.csv`** — model-ready table, 12,360 rows (6,180 per class) × 25 columns; the input of `notebooks/landslide_susceptibility_modeling.ipynb`.
| Column | Unit / values | Meaning |
|---|---|---|
| `id` | text | `Event_ID` for non-landslides, else `LS_<inventory_id>` |
| `event_date` | date | Event (or borrowed) date; temporal factors use data strictly before it |
| `longitude`, `latitude` | deg | Location |
| `landslide` | 0 / 1 | Label |
| `elevation` | m | ALOS AW3D30 (SRTM for the earliest events) |
| `slope`, `aspect` | deg | From the DEM |
| `curvature_general`, `curvature_profile` | DEM-derived index | Convolution-kernel curvatures |
| `tri`, `tpi` | DEM-derived index | Terrain ruggedness / topographic position index |
| `ls_factor` | – | Slope length–steepness factor |
| `upstream_area_km2` | km² | Contributing area (HydroSHEDS < 2020, MERIT ≥ 2020) |
| `twi`, `spi` | – | Topographic wetness / stream power index |
| `soil_texture` | USDA texture-class code (1–9 occur) | OpenLandMap texture class |
| `soil_clay_pct`, `soil_sand_pct` | % | OpenLandMap |
| `soil_bulk_density` | OpenLandMap raw units | See the OpenLandMap asset description |
| `dist_to_road`, `dist_to_river` | m | Nearest OSM road / river-or-waterway (≤ 20 km search) |
| `lithology` | text | GLiM level-1 class (6 occur) |
| `ndvi` | −1…1 | Latest valid NDVI in the 90 days before the event day |
| `lulc` | text | Land-cover class (SERVIR, Dynamic World fallback) |

`dist_to_stream` is deliberately **not** in this table (its pre-2020 values are on the wrong scale, see `../docs/METHODS.md`); it remains in the raw table. Blank counts: ndvi 446, soil 132, lithology 46, slope/aspect/ls_factor/twi/spi 17, lulc 10, upstream_area_km2 5. `landslide_event_factors_cleaning_report.txt` lists every cleaning step and the 27 columns dropped relative to the raw table.

**`landslide_event_factors.csv`** — the raw Earth Engine sample (12,360 × 56): everything above plus provenance columns (`ndvi_observation_date`, `ndvi_sensor`, `ndvi_status`, `land_cover_source`, `hydrology_reference`, `terrain_reference`, `temporal_policy`, resolutions, …) and the columns left out of the model table: `drainage_density`, `dist_to_fault` and `dist_to_stream`.

**`landslide_event_antecedent_rainfall.csv`**, **`non_landslide_event_antecedent_rainfall.csv`** — 6,180 rows each. IMERG V07 rainfall before the cut-off.
| Column | Meaning |
|---|---|
| `event_row` | Row index in the source event file |
| `inventory_id` / `Event_ID`, `date`, `longitude`, `latitude` | Event identifiers (`inventory_id` is empty in the non-landslide file) |
| `event_time_local`, `rainfall_cutoff_utc` | Local-midnight event time and the UTC cut-off used |
| `time_quality` | `start_of_day_proxy` for every row (no time-of-day available) |
| `rain_1h_mm`, `rain_3h_mm`, `rain_6h_mm`, `rain_1d_mm` … `rain_30d_mm` | Accumulated rainfall before the cut-off |
| `*_coverage_pct` | Share of expected half-hour IMERG slots present for that window |
| `imerg_status`, `rainfall_status`, `error` | Extraction status (all `permanent` / `complete`) |

**`factor_grid_points/`** *(archived, not in this folder)* — the 250 m factor grid behind the susceptibility map: 148 tile CSVs, 1,137,629 points (`px_lon`, `px_lat` and every conditioning factor), sampled from Earth Engine for the 2026-10-09 run. It is an intermediate: the scored map is `results/susceptibility_map/`. To re-run `scripts/predict_susceptibility_grid.py`, restore the folder to `data/processed/factor_grid_points/` or regenerate it with `scripts/gee_sample_factor_grid_points.py`.

## data/boundary/
- `southern_thailand.geojson` — 14 province polygons (study area).
- `southern_thailand_tambons.geojson` — 1,055 tambons: `GID_3`, `NAME_3`, `NAME_2` (district), `NAME_1` (province), `area_km2`, `sample_lon`, `sample_lat`.
- `southern_thailand_tambon_points.csv` — one representative point per tambon (same fields) used for rainfall sampling.

## data/external/
GeoJSON layers clipped to the study area. (The roads / rivers / waterways / faults / lithology source layers, each as `*_aoi` and `*_buffer20km`, were only inputs for uploading Earth Engine assets; they are archived and can be re-created with `scripts/download_external_data.py`; `manifest.json` still describes them.) Shipped layers:
| File | Content | Key fields |
|---|---|---|
| `buildings_aoi.geojson` | 426,519 OSM building footprints | `osm_id`, `fclass`, `type`, `name` |
| `facilities_aoi.geojson` | 3,895 OSM points (health, schools, emergency, transport, worship…) | `osm_id`, `fclass`, `name` |
| `worldpop_2020_UNadj_constrained_aoi.tif` | Population per ~100 m pixel, 2020; total 9,385,883 | band 1, no-data −99999 |
| `rain_percentiles_24h_tambon.csv`, `rain_percentiles_24h_meta.json` | Per-tambon wet-day 24 h rainfall percentiles from CHIRPS 1991–2020 averaged onto the 0.25° GFS grid (wet day ≥ 1 mm); 1,055 rows | `GID_3`, `NAME_*`, `wet_p75_mm`, `wet_p90_mm`, `wet_p95_mm`, `wet_p99_mm`, `wet_day_fraction` |
| `manifest.json`, `validation.json`, `worldpop_manifest.json` | Counts, extents, checks, sources | |

## models/
- `susceptibility/*_pipeline.joblib`, `*_isotonic_calibrator.joblib` — scikit-learn pipeline + isotonic calibrator for the selected model (`svm_rbf`). Loading needs `notebooks/susc_utils.py` on `sys.path`.
- `susceptibility/model_metadata.json` — selection method, parameters, features, CV and hold-out metrics for all 11 candidates, threshold, limitations. The model uses 20 factors (no `dist_to_stream`).
- `susceptibility/landslide_sample_susceptibility_scores.csv` — `id`, `event_date`, `longitude`, `latitude`, `landslide`, `split` (train / test / embargoed), `heldout_score` (out-of-fold score for retained training rows, hold-out score for test rows; empty for embargoed rows), `final_model_insample_score`, `relative_score_class` (descriptive bins of the calibrated held-out score; blank where there is none).
- `rainfall_trigger/` — rainfall-trigger pipeline (`random_forest`), calibrator and metadata (13 features, metrics, limitations). **Its hold-out ROC-AUC is 0.34, below chance: the model has no skill and is not used by the live pipeline** (paired same-date negatives, image-date landslide dates; see `../docs/METHODS.md`).

## results/
- `susceptibility_map/susceptibility_grid_points.csv` — `px_lon`, `px_lat`, `raw_probability`, `calibrated_probability` (0.00–0.93), `susceptibility_class` (`very_low` < 0.2 ≤ `low` < 0.4 ≤ `moderate` < 0.6 ≤ `high` < 0.8 ≤ `very_high`), `above_threshold` (1 if raw score ≥ 0.302; 25.5% of cells). `susceptibility_grid.tif` is the same calibrated score rasterised to 1,968 × 2,396 cells (float32, EPSG:4326, no-data NaN); `susceptibility_map_metadata.json` has class counts and limitations.
- `live_forecast/latest.json` — GFS run metadata (`gfs_run_utc`, `generated_utc`, `window_start_utc`, `window_24h_end_utc`, `window_72h_end_utc`, `forecast_hours_used`), the assumed `rain_classes_mm_24h`, a `summary`, `method`, `limitations` and, per tambon: `gfs_rain_24h_mm`, `gfs_rain_48h_mm`, `gfs_rain_72h_mm` (forecast totals counted from now), `gfs_peak_hourly_mm_24h`, `rain_class_24h` (absolute: `light` < 10 mm, `moderate` 10–35, `heavy` 35–90, `very_heavy` ≥ 90), `local_p75_mm`, `local_p90_mm`, `local_p95_mm` (the tambon's wet-day percentiles) and `rain_local_class_24h` (`below_p75`, `p75_p90`, `p90_p95`, `above_p95`; this one drives the live impact).
- `impact_overlay/impact_overlay_by_tambon.csv` (1,055 rows):
  | Column group | Meaning |
  |---|---|
  | `GID_3`, `NAME_*`, `area_km2` | Tambon identifiers |
  | `grid_cells`, `mean_susceptibility`, `pct_cells_high_vh` | Susceptibility summary; `susceptibility_tier` = low (< 15%), moderate (15–40%), high (≥ 40%), `no_data` |
  | `buildings_*`, `population_*`, `facilities_*` | `_total`, `_high_vh` (high + very high cells) and one column per susceptibility class |
  | `critical_facilities_*` | Health + police/fire/courthouse only |
  | `gfs_rain_24h_mm`, `gfs_rain_48h_mm`, `gfs_rain_72h_mm`, `gfs_peak_hourly_mm_24h`, `rain_class_24h`, `local_p75_mm`, `local_p90_mm`, `local_p95_mm`, `rain_local_class_24h` | From `live_forecast/latest.json` |
  | `live_impact_class` | Terrain factor (low 1, moderate 2, high 3) × 24 h rain-class index (0–3; local percentile classes, `RAIN_BASIS` in the script): 0–1 low, 2–3 moderate, 4–6 high, ≥ 7 very_high; `not_assessed` for tambons without a grid cell. A triage rule, not a probability. |
  | `population_at_elevated_risk`, `buildings_at_elevated_risk`, `facilities_at_elevated_risk` | `*_high_vh` counts for tambons whose live impact class is high or very_high, else 0 |
- `impact_overlay/impact_overlay_by_province.csv` — sums per province plus `pct_population_in_high_vh`, `population_at_elevated_risk`, `tambons_live_impact_high_or_above` and `max_rain_24h_mm`.
- `impact_overlay/facility_exposure.csv` — one row per facility with `category`, its tambon, susceptibility class/score and tambon classes.
- `impact_overlay/impact_overlay.json` — the above plus metadata and limitations (served by `/api/impact/overlay`).
- `figures/` — four PNGs (susceptibility map, combined-class maps, model comparison, exposed population by province).
