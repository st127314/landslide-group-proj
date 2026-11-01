# Earth Engine factor extraction

Install the dependencies from the project root:

```bash
pip install -r requirements.txt
```

IMERG antecedent rainfall extraction is described in [README-imerg.md](README-imerg.md).

The script uses `scripts/service_account/key.json`, with no interactive authentication.
To rotate or switch the service account, overwrite `scripts/service_account/key.json`
with the new key's content; no script changes are needed, because the service-account
email and GEE project are both read from the key file itself (`project_id`), not hardcoded.
If `GEE_PROJECT` is omitted, it uses the key's `project_id`.
The Cloud project must be registered for Earth Engine with the API enabled, and
the service account must have permission to use the project and read its assets.
See [Earth Engine service accounts](https://developers.google.com/earth-engine/guides/service_account).

Edit the configuration at the top of `gee_landslide_factors.py`:

- `SERVICE_ACCOUNT_KEY`: service-account JSON key path.
- `GEE_PROJECT`: Cloud project ID, or `None` to use the key's project.
- `EXPORT_BUCKET`: existing Cloud Storage bucket name; only required with `--export`.
- `SAMPLE_CSV`: local CSV destination for sampled event factors.
- `GEE_ASSETS`: central IDs for ALOS/SRTM, MERIT/HydroSHEDS, Dynamic World, Sentinel-2, Landsat 5/7/8/9, annual SERVIR
  land cover, soils, and uploaded vectors. Roads, rivers and faults are sampled as
  distance factors when their table IDs are configured; otherwise they are omitted
  with a message. `GEE_ASSETS["lithology"]` points to the GLiM level-1 lithology table
  produced by `download_external_data.py` (`data/external/lithology_buffer20km.geojson`,
  see `data/external/README.md`) and uploaded as an Earth Engine table asset. If the ID
  is unset, the lithology factor is omitted with a message rather than failing the run.
- The `projects/ee-…` asset IDs in `GEE_ASSETS` belong to the team's Earth Engine
  project. Other users must upload their own copies of these input assets and set
  the IDs in `GEE_ASSETS`.
- `GEE_ASSETS["land_cover"]`: annual local/SERVIR collection with `lc` band and
  `system:time_start`; the configured asset contains 2000–2023 maps.
  An unset ID, missing previous-year image, masked pixel, or invalid class triggers
  Dynamic World fallback. Permission/service errors remain errors rather than being
  mistaken for missing coverage.
- `NDVI_LOOKBACK_DAYS`: maximum age of NDVI observations (90 days by default).
- `EVENT_TIMEZONE`: Asia/Bangkok; slash dates are parsed as day/month/year.
- `EXPORT_REFERENCE_DATE`: optional YYYY-MM-DD cutoff for temporal raster exports.

Project and bucket settings also read `GEE_PROJECT` and `GEE_EXPORT_BUCKET`
from the environment by default. The key path is configured directly in the script.
The default run samples point values and saves `data/processed/landslide_event_factors.csv`.
It does not submit any Earth Engine batch exports and needs no bucket:

```bash
python scripts/gee_landslide_factors.py
```

The default GeoJSON inputs are:

- Study area: `data/boundary/southern_thailand.geojson`, converted to `study_area`
  (an `ee.FeatureCollection`); its geometry becomes the clipping/export AOI.
- Events: `data/inventory/landslide_inventory.geojson`, converted to `landslide_events`.
  Only events within the study area are sampled. `reduceRegions` with a `first`
  reducer retains a row per point, including missing values. Sampling uses
  grids appropriate to each factor in `EXPORT_CRS`; source resolutions remain
  recorded rather than being inferred from the output grid. The CSV includes event metadata, coordinates, `landslide=1`, and factor
  values. Rainfall properties such as `sum_d0` through `sum_d30` are excluded.
  Missing factors are blank and the script reports the number of affected rows.
  Non-landslide (`landslide=0`) rows are included automatically when
  `data/inventory/non_landslide_events.geojson` exists; see
  the paired-negatives section below.

Edit `data_path` and `landslide_events_path` to change these. Relative paths are resolved from the
project directory even when running from another working directory. Both inputs
must use longitude/latitude WGS84 coordinates.

Optionally also export static factor GeoTIFFs to an existing Cloud Storage bucket
that the service account can write to:

```bash
export GEE_EXPORT_BUCKET="your-bucket-name"
python scripts/gee_landslide_factors.py --export
```

To also export NDVI and land cover rasters, set `EXPORT_REFERENCE_DATE` at the
script top. Those two rasters use that explicit date; the event CSV always uses
individual event dates. Without it, `--export` exports all three static source combinations, with
`srtm_`, `alos_`, and `merit_` prefixes. Set a reference date to avoid redundant exports.

Outputs use the prefix `landslide_susceptibility_factors/`. The script prints
submitted task IDs; submission does not mean the exports have finished.
Exports use Cloud Storage because service accounts cannot own personal Drive
files and have no Drive storage quota. See
[Google's service-account storage note](https://developers.google.com/workspace/drive/api/guides/about-shareddrives)
and [Earth Engine Cloud Storage exports](https://developers.google.com/earth-engine/apidocs/export-image-tocloudstorage).

Factors are point-sampled at each event; no buffer (neighbourhood) statistics are computed.

The CSV is retrieved synchronously in batches of `SAMPLE_BATCH_SIZE` points; failing
batches are retried and then split. Several factor formulas are approximations;
offline checks do not validate their scientific accuracy or the suitability of
imagery dates.

## Event-time extraction

Events span 2000–2025. Dates are normalized from `date_parsed`, falling
back to `DATE` only if the former is absent. Missing/invalid dates stop the run.
Because the inventory's 07:00 times may be defaults, the cutoff is midnight at
the start of the event day in Thailand. Same-day and later imagery is excluded.

| Factor | Temporal handling |
| --- | --- |
| NDVI | Latest valid Sentinel-2 surface-reflectance pixel in the preceding 90 days; falls back to the latest valid Landsat 5/7/8/9 pixel in that same window. Landsat uses Collection 2 surface-reflectance scaling, cloud/shadow/snow/fill/saturation masks, and rejects negative reflectances. |
| Land cover | Prefer the previous calendar year’s local/SERVIR 30 m class. Fall back per pixel to a valid pre-event Dynamic World 10 m class from the preceding 365 days (confidence ≥0.6). No MODIS fallback. |
| Terrain | ALOS AW3D30 V4.1, 30 m, for events on/after 2011-05-13; SRTM 30 m for older events and missing ALOS pixels. Only ALOS MSK=0 is retained, excluding void fills from uncertain/later sources. |
| Hydrology | MERIT Hydro (~90 m, 2019 model) for events from 2020; HydroSHEDS (~500 m) earlier. Both are static models, not event-date observations. |
| Soils | Static OpenLandMap estimates, explicitly flagged `static_model_not_event_dated`; no historical soil series is substituted or claimed. |
| Uploaded roads/rivers | Current OpenStreetMap snapshots are used. Distances use the buffered table geometry and a 20 km search radius; pixels beyond this radius are missing. |
| Uploaded faults | Static mapped fault traces, when configured. |
| Uploaded lithology | Static GLiM v1.1 (Hartmann and Moosdorf, 2012) level-1 rock-type polygons, when configured; not an event-dated observation. |

The NDVI composite selects the latest *valid pixel*, not the latest scene that
merely overlaps the point. When no valid pixel exists within the lookback window,
NDVI remains blank with `no_valid_prior_pixel`; no later imagery or unlimited
lookback is used. Land cover stays blank if neither the previous-year local map nor valid prior Dynamic World coverage exists.

CSV provenance includes the cutoff, NDVI observation timestamp, age in days,
valid-observation count for the selected sensor family, sensor code (2 = Sentinel-2; 5/7/8/9 = Landsat), requested local land-cover year, and status columns.
These provenance fields and event dates are metadata, not default model predictors.
This is retrospective extraction using pre-event observations, not a claim that
all reprocessed products were already published on the event date. Landsat sensor
differences and the static soil assumption should be considered in model validation.

Sources: [Landsat processing](https://developers.google.com/earth-engine/guides/landsat),
[SERVIR class definitions](https://landcovermapping.org/static/app/config/settings.js),
[SRTM](https://developers.google.com/earth-engine/datasets/catalog/USGS_SRTMGL1_003).

Offline regression checks:

```bash
python -m unittest discover -s tests -p 'test_temporal_factors.py'
```

Sentinel-2 takes priority even when Landsat has a newer valid observation. The
fallback is evaluated at each sampled pixel, not merely from scene availability.
Sentinel-2 uses B8/B4 and SCL classes 4/5/6 (clear vegetation/bare soil/water).
Clouds, shadows, snow, defective and uncertain pixels are excluded. The harmonized
surface-reflectance collection starts in March 2017 with incomplete early coverage;
older events and cloudy/missing Sentinel-2 pixels therefore use Landsat. If both
sources are missing, NDVI stays blank. Temporal rasters are sampled on a 10 m grid to preserve Sentinel-2/Dynamic World detail.
Landsat and SERVIR pixels are nearest-neighbor sampled on that grid; their
information content remains 30 m. Soils use a 250 m grid, hydrology 90/500 m,
and terrain and vector distances 30 m.
See [Sentinel-2 SR documentation](https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED).

## Resolution and source selection

ALOS AW3D30 is natively **30 m**, not 12.5 m. Its acquisition period spans 2006–2011;
the conservative switch date prevents use for earlier events. Terrain derivatives
are recomputed for each DEM baseline, including the slope used by TWI/SPI. ALOS/SRTM
seams and changes since acquisition remain limitations. `dem_source` is 1=SRTM,
2=ALOS at the sampled cell; neighborhood-derived factors can involve both sources.
See [ALOS V4.1](https://developers.google.com/earth-engine/datasets/catalog/JAXA_ALOS_AW3D30_V4_1).

`LULC` contains the selected source's **native class code**. `LULC_SERVIR` preserves
only the local value (blank on fallback). `land_cover_source` is 1=SERVIR,
2=Dynamic World. Codes from these two legends are not interchangeable. Use
`land_cover_class_key` (e.g. `servir:6` or `dynamic_world:1`) as a categorical
model input, not an unlabeled mixed integer column. `land_cover_class_name`
provides the source's own class label. No artificial forest-subtype crosswalk is made.

`land_cover_year` records the requested previous-year SERVIR map, including when
that map is absent. `land_cover_observation_ms` is populated only for selected
Dynamic World pixels; the annual local map has no exact single observation time.
`land_cover_resolution_m` reports 30 or 10 m respectively. Earlier-year local maps
are not substituted silently when the requested year is absent. Both sources
continue to respect the pre-event observation policy.

Hydrology reports `upstream_area_km2`.
MERIT supplies km² directly; HydroSHEDS counts are approximately converted using
local native cell area. TWI uses log(specific catchment area / tan(slope)); SPI uses
specific catchment area × tan(slope), with catchment area approximated by upstream
area divided by grid width. Stream threshold is 100 km²; drainage density approximates line length
per area (m/m²). Tune and validate before modelling. `hydrology_reference` and
`hydrology_resolution_m` record the selection. MERIT is treated as a 2019 static
model for post-2019 events, not as an annually updated historical reconstruction.
See [MERIT Hydro](https://developers.google.com/earth-engine/datasets/catalog/MERIT_Hydro_v1_0_1).

Older land cover and soils remain constrained by source coverage and native resolution.

`lithology` is the numeric `litho_code` (this project's own integer assignment,
see `scripts/glim_lithology_classes.json`) sampled by pixel from the uploaded
GLiM polygons via `reduceToImage`; `lithology_class_name` is its decoded level-1
rock-type name (e.g. "Carbonate sedimentary rocks"). GLiM's own polygon
resolution (~1:3,750,000) is far coarser than the other 30 m factors; the sampled
value reflects which mapped rock unit contains the point, not a resolved grid.

## SERVIR class codes from the website JavaScript

Extracted from `landCoverClasses` in
[settings.js](https://landcovermapping.org/static/app/config/settings.js), referenced
by the website's land-cover controller. The checked-in
`servir_landcover_classes.json` retains codes, JavaScript class names, colors, source URL,
retrieval date and source checksum. Codes 0/255 are treated as unavailable, not classes.

| Value | JavaScript class name |
| --- | --- |
| 1 | aquaculture |
| 2 | barren |
| 3 | cropland |
| 4 | cropPlantation |
| 5 | deciduous |
| 6 | evergreen |
| 7 | floodedForest |
| 8 | forestPlantation |
| 9 | grass |
| 10 | mangrove |
| 11 | otherForest |
| 12 | palm |
| 13 | rice |
| 14 | rubber |
| 15 | shrub |
| 16 | urban |
| 17 | water |
| 18 | wetland |
| 19 | snow |

# Non-landslide (pseudo-absence) samples: the paired design

The final negatives are produced by four scripts, run in this order (see `docs/METHODS.md` for why):

```bash
python3 scripts/generate_paired_negatives.py                  # local, no Earth Engine: writes data/inventory/non_landslide_events.geojson
python scripts/gee_extract_paired_negatives.py [--start N --count M --slice M --batch-size B]   # Earth Engine: factors -> data/cache/paired_negative_parts/
python scripts/gee_extract_paired_negatives.py --merge        # strict: stops unless all 6,180 rows are present
python scripts/gee_imerg_paired_negatives.py --start N --count M   # Earth Engine: IMERG rainfall slices (run several in parallel)
python scripts/gee_imerg_paired_negatives.py --merge          # strict: writes data/processed/non_landslide_event_antecedent_rainfall.csv
python3 scripts/assemble_paired_dataset.py                    # raw + cleaned tables (drops dist_to_stream), all consistency checks
```

**`generate_paired_negatives.py`** (needs `geopandas`, `shapely`, `scipy`) creates one negative per landslide: it is placed in a
2-10 km ring around its landslide (widened in x1.5 steps, capped at 40 km, only where the ring is full; at most
22.5 km was needed), inside the *same province*, at least
2 km from **every** one of the 23,284 landslide records in `data/inventory/landslide_records_all.geojson` (dated or not) and at
least 250 m from other negatives, and it **takes its paired landslide's date**. Pairs therefore share the same year
distribution, province and regional weather. (1 km spacing is infeasible: the median landslide has ~680 other records within 10 km.)

**Extraction** reuses `gee_landslide_factors.py` (same layers and event-date cut-offs) for the negatives only, and
`gee_imerg_antecedent_rainfall.py` for rainfall. Both wrappers are resumable (rows already saved are skipped on restart,
a partial last line is repaired, credential failures stop the run before the next batch) and have strict merges.
Earth Engine requests that time out are retried and split automatically; if a batch of N points keeps timing out use
`--batch-size` smaller, or `--retry-missing` to fetch every still-missing point in a single request.

`gee_landslide_factors.py` also reads `data/inventory/non_landslide_events.geojson` if it exists and would
re-extract both classes together; the paired workflow above exists so the landslide rows do not have to be re-extracted.

## Alternative negative sampling (not used)

A nearest-event design (uniformly random points, each given the date of the *nearest* landslide) and its
rainfall-verification script are archived outside the submission tree. That design produced negatives with a very
different year/province mix, 17.5% of which lay within 2 km of an undated landslide record, so the paired design above
is used instead. See `docs/METHODS.md`.

# Live forecast and impact overlay

```bash
python scripts/compute_rain_percentiles.py    # Earth Engine, ~1 min, one-off: per-tambon wet-day rainfall percentiles (CHIRPS 1991-2020) -> data/external/rain_percentiles_24h_tambon.csv
python scripts/run_live_gfs_forecast.py       # Earth Engine, ~10 s: GFS 24/48/72 h rainfall per tambon -> results/live_forecast/latest.json
python3 scripts/build_impact_overlay.py       # local: joins forecast + susceptibility + exposure -> results/impact_overlay/
python3 scripts/make_figures.py               # local: report figures -> results/figures/
```

`run_live_gfs_forecast.py` uses `NOAA/GFS0P25` (hourly forecast images, `precipitation_rate` x 3600 s per hour). It sums the hours
from the first forecast hour still in the future for 24, 48 and 72 h, samples the 0.25 deg cell containing each tambon's
representative point, and classes the 24 h total two ways: against the tambon's own wet-day rainfall percentiles (below P75, P75-P90, P90-P95, above
P95; from `compute_rain_percentiles.py`, which averages 30 years of CHIRPS daily rain onto the 0.25 deg GFS grid) and against fixed
mm thresholds (`RAIN_CLASSES`: light < 10, moderate 10-35, heavy 35-90, very heavy >= 90). `RAIN_BASIS` in `build_impact_overlay.py`
chooses which drives the live impact (default: percentiles). Neither is calibrated on landslide records.
No model and no landslide data are involved. Re-run it (and then `build_impact_overlay.py`) whenever you want a fresh forecast; it
takes seconds, so it can run from cron. `build_impact_overlay.py` needs geopandas, scipy and GDAL; the
forecast script needs `earthengine-api` and `pandas`.

The rainfall model in `notebooks/rainfall_trigger_threshold.ipynb` (IMERG antecedent rainfall) is an exploratory negative result
(hold-out ROC-AUC 0.34) and is not used by this pipeline; see `docs/METHODS.md`.
