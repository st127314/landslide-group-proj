"""Extract landslide conditioning factors using a GEE service account.

Edit the configuration below before running. See scripts/README.md for setup.
"""

import argparse
import csv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import os
from pathlib import Path
import socket
import time

import ee

# The GEE client has no built-in request timeout; a stalled connection can
# otherwise hang getInfo() forever instead of raising for a retry loop to
# catch (see gee_imerg_antecedent_rainfall.py, and a 1.5+ hour hang observed
# in gee_export_factor_grid_local.py, which imports this module). Harmless
# when this script is imported rather than run directly -- importers that
# want a different timeout can override it after the import.
socket.setdefaulttimeout(120)

PROJECT_DIR = Path(__file__).resolve().parent.parent
# Configuration: edit these values here, or use the existing environment variables.
GEE_PROJECT = os.getenv("GEE_PROJECT")  # None uses the project_id from the key.
SERVICE_ACCOUNT_KEY = PROJECT_DIR / "scripts" / "service_account" / "key.json"
EXPORT_BUCKET = os.getenv("GEE_EXPORT_BUCKET", "")

# Paths are resolved from the project directory, independent of the working directory.
data_path = PROJECT_DIR / "data" / "boundary" / "southern_thailand.geojson"
# Event data lives in data/inventory/; edit this path for another directory.
landslide_events_path = PROJECT_DIR / "data" / "inventory" / "landslide_inventory.geojson"
# Pseudo-absence points from generate_paired_negatives.py; same Point/date
# schema as landslide_events_path, sampled with the same temporal policy below.
non_landslide_events_path = PROJECT_DIR / "data" / "inventory" / "non_landslide_events.geojson"

SAMPLE_CSV = PROJECT_DIR / "data" / "processed" / "landslide_event_factors.csv"
# Points per getInfo() call; batches that fail are automatically retried, then
# (if they still fail) split into smaller batches -- see fetch_samples_chunk.
SAMPLE_BATCH_SIZE = 100
# Attempts at a given batch size before splitting it in half (or, for a lone
# point, giving up and skipping just that record).
BATCH_RETRY_ATTEMPTS = 3
BATCH_RETRY_BACKOFF_SECONDS = 5
# Explicit metadata selection excludes existing rainfall columns (sum_d0, etc.).
# Event_ID/DATE (rainfall-annotated inventory schema) and inventory_id/date (the
# southern-Thailand point inventory) are alternate schemas; missing keys are
# silently omitted per feature by toDictionary(), not an error.
EVENT_PROPERTIES = ["Event_ID", "DATE", "date_parsed", "event_date", "event_cutoff", "inventory_id", "date"]
EVENT_TIMEZONE = "Asia/Bangkok"
NDVI_LOOKBACK_DAYS = 90
ALOS_EARLIEST_EVENT = "2011-05-13"  # Conservative end of PRISM acquisition period.
MERIT_EARLIEST_EVENT = "2020-01-01"  # Use the 2019 static model only for later events.
LAND_COVER_LOOKBACK_DAYS = 365
LAND_COVER_MIN_CONFIDENCE = 0.6
# Sampling/export grids do not increase the information content of source rasters.
NATIVE_SCALES = {"terrain": 30, "sentinel2": 10, "landsat": 30,
                 "dynamic_world": 10, "servir": 30, "soil": 250, "hydrology": 500, "merit": 90}
# Optional date for full NDVI/LULC raster exports; point samples always use event dates.
EXPORT_REFERENCE_DATE = None  # e.g. "2020-01-15"
TEMPORAL_COLUMNS = [
    "NDVI", "ndvi_observation_ms", "ndvi_observation_date", "ndvi_sensor",
    "ndvi_age_days", "ndvi_valid_observations", "ndvi_status",
    "LULC_SERVIR", "land_cover_year", "land_cover_status", "temporal_policy",
    "LULC", "land_cover_class_name", "land_cover_class_key", "land_cover_source", "land_cover_resolution_m", "land_cover_observation_ms",
    "ndvi_resolution_m", "hydrology_reference", "hydrology_resolution_m", "terrain_reference", "soil_temporal_status", "roads_rivers_temporal_status",
]

EXPORT_SCALE = 30
EXPORT_CRS = "EPSG:32647"
EXPORT_PREFIX = "landslide_susceptibility_factors"

# Central source dataset IDs
GEE_ASSETS = {
    "dem": "JAXA/ALOS/AW3D30/V4_1",
    "dem_fallback": "USGS/SRTMGL1_003",
    "land_cover_fine": "GOOGLE/DYNAMICWORLD/V1",
    "flow_accumulation": "WWF/HydroSHEDS/15ACC",
    "hydrology_fine": "MERIT/Hydro/v1_0_1",
    "sentinel2": "COPERNICUS/S2_SR_HARMONIZED",
    "landsat5": "LANDSAT/LT05/C02/T1_L2",
    "landsat7": "LANDSAT/LE07/C02/T1_L2",
    "landsat8": "LANDSAT/LC08/C02/T1_L2",
    "landsat9": "LANDSAT/LC09/C02/T1_L2",
    "soil_texture": "OpenLandMap/SOL/SOL_TEXTURE-CLASS_USDA-TT_M/v02",
    "soil_clay": "OpenLandMap/SOL/SOL_CLAY-WFRACTION_USDA-3A1A1A_M/v02",
    "soil_sand": "OpenLandMap/SOL/SOL_SAND-WFRACTION_USDA-3A1A1A_M/v02",
    "soil_bulk_density": "OpenLandMap/SOL/SOL_BULKDENS-FINEEARTH_USDA-4A1H_M/v02",
    "land_cover": "projects/servir-mekong/RLCMSV2/lc_rlcms_logical_v6_remap",
    "lithology": "projects/ee-kamalhosenadpc/assets/lithology_buffer20km",
    "faults": "projects/ee-kamalhosenadpc/assets/faults_buffer20km",
    "roads": "projects/ee-kamalhosenadpc/assets/roads_buffer20km",
    "rivers": "projects/ee-kamalhosenadpc/assets/waterways_buffer20km",
}


# Native SERVIR codes copied from the site's JavaScript landCoverClasses definition.
SERVIR_CLASS_FILE = Path(__file__).with_name("servir_landcover_classes.json")
SERVIR_CLASSES = {entry["value"]: entry["name"]
                  for entry in json.loads(SERVIR_CLASS_FILE.read_text())["classes"]}
DYNAMIC_WORLD_CLASSES = dict(enumerate([
    "water", "trees", "grass", "flooded_vegetation", "crops",
    "shrub_and_scrub", "built", "bare", "snow_and_ice",
]))

# GLiM level-1 lithology classes; litho_code is this project's own integer
# assignment, baked into the uploaded asset's attribute table (see
# download_external_data.py) since GLiM ships only a two-letter code.
GLIM_CLASS_FILE = Path(__file__).with_name("glim_lithology_classes.json")
GLIM_CLASSES = {entry["value"]: entry["name"]
               for entry in json.loads(GLIM_CLASS_FILE.read_text())["classes"]}


def prefer_local_landcover(local, dynamic):
    """Keep native class codes; source codes are 1=SERVIR and 2=Dynamic World."""
    local = local.updateMask(local.gte(1).And(local.lte(19)))
    fine = dynamic.select("LULC")
    preferred = local.rename("LULC").unmask(fine, sameFootprint=False)
    source = ee.Image.constant(1).updateMask(local.mask()).unmask(
        ee.Image.constant(2).updateMask(fine.mask()), sameFootprint=False).rename("land_cover_source")
    resolution = source.remap([1,2], [30,10]).rename("land_cover_resolution_m")
    timestamp = dynamic.select("land_cover_observation_ms").updateMask(source.eq(2))
    return preferred.addBands([source, resolution, timestamp])


def project_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path


def initialize_gee(key_path, project=None):
    """Use the service account in a JSON key; never fall back to user credentials."""
    with key_path.open(encoding="utf-8") as handle:
        key = json.load(handle)
    if key.get("type") != "service_account":
        raise ValueError("The credential file must be a service account JSON key.")
    project = project or key.get("project_id")
    if not project:
        raise ValueError("Set GEE_PROJECT in the configuration or environment.")
    # Pass email explicitly: older earthengine-api (e.g. 1.5.7, seen on one
    # deployment host) requires it as a positional arg even with key_file set;
    # newer versions accept it either way, so this is safe everywhere.
    credentials = ee.ServiceAccountCredentials(key["client_email"], str(key_path))
    ee.Initialize(credentials=credentials, project=project)
    print(f"Initialized Earth Engine project: {project}")
    return project


def normalize_event_date(properties):
    """Input slash dates are day/month/year. Exclude the entire local event day."""
    # "date" is the southern-Thailand point inventory's ISO-format field.
    value = properties.get("date_parsed") or properties.get("DATE") or properties.get("date")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing event date")
    value = value.strip()
    parsed = None
    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S",
                "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt)
            break
        except ValueError:
            pass
    if parsed is None:
        raise ValueError(f"Unsupported event date: {value!r}")
    # 07:00 in this inventory may be a default timestamp; do not assume it is
    # the actual failure time. Local midnight is the conservative cutoff.
    cutoff = datetime.combine(parsed.date(), datetime.min.time(), ZoneInfo(EVENT_TIMEZONE))
    return cutoff.date().isoformat(), cutoff.isoformat()


def load_geojson_features(path, event_dates=False):
    """Read+validate a WGS84 GeoJSON FeatureCollection/Feature client-side,
    returning the raw feature dicts without building any Earth Engine object."""
    with path.open(encoding="utf-8") as handle:
        geojson = json.load(handle)
    crs = geojson.get("crs")
    if crs:
        name = crs.get("properties", {}).get("name", "")
        if name not in {"urn:ogc:def:crs:OGC:1.3:CRS84", "EPSG:4326",
                        "urn:ogc:def:crs:EPSG::4326"}:
            raise ValueError(f"{path}: reproject GeoJSON to WGS84 (EPSG:4326) first.")
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features", [])
    elif geojson.get("type") == "Feature":
        features = [geojson]
    else:
        raise ValueError(f"{path}: expected a GeoJSON FeatureCollection or Feature.")
    if not features:
        raise ValueError(f"{path}: no features found.")
    for index, feature in enumerate(features):
        if feature.get("type") != "Feature" or not feature.get("geometry"):
            raise ValueError(f"{path}: feature {index} has no valid geometry.")
        if event_dates:
            if feature["geometry"]["type"] != "Point":
                raise ValueError(f"{path}: event {index} must have Point geometry.")
            properties = feature.setdefault("properties", {})
            try:
                properties["event_date"], properties["event_cutoff"] = normalize_event_date(properties)
            except ValueError as exc:
                raise ValueError(f"{path}: event {index}: {exc}") from exc
    print(f"Loaded {len(features)} features from {path}")
    return features


def geojson_to_feature_collection(path, event_dates=False):
    """Read a WGS84 GeoJSON FeatureCollection or Feature into Earth Engine."""
    features = load_geojson_features(path, event_dates=event_dates)
    # Drop the optional top-level CRS metadata; these inputs use lon/lat WGS84.
    return ee.FeatureCollection({"type": "FeatureCollection", "features": features})


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true",
                        help="Also submit full factor GeoTIFF exports to Cloud Storage.")
    return parser.parse_args(argv)


def masked_image(names):
    return ee.Image.constant([0] * len(names)).rename(names).toDouble().updateMask(ee.Image(0))


def landsat_ndvi(image, red_band, nir_band, sensor):
    # QA bits 0..5: fill, dilated cloud, cirrus (L8/9), cloud, shadow, snow.
    good = image.select("QA_PIXEL").bitwiseAnd(63).eq(0).And(
        image.select("QA_RADSAT").eq(0))
    red = image.select(red_band).multiply(0.0000275).add(-0.2)
    nir = image.select(nir_band).multiply(0.0000275).add(-0.2)
    denominator = nir.add(red)
    good = good.And(red.gte(0)).And(nir.gte(0)).And(denominator.gt(0))
    ndvi = nir.subtract(red).divide(denominator).rename("NDVI").updateMask(good)
    date = ee.Image.constant(image.date().millis()).rename("ndvi_observation_ms")
    source = ee.Image.constant(sensor).rename("ndvi_sensor")
    return ndvi.addBands([date, source]).updateMask(ndvi.mask()).toDouble()


def sentinel2_ndvi(image):
    # Retain clear vegetation, bare soil and water; exclude uncertain/cloud pixels.
    scl = image.select("SCL")
    good = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6))
    red = image.select("B4").multiply(0.0001)
    nir = image.select("B8").multiply(0.0001)
    good = good.And(nir.add(red).gt(0))
    ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI").updateMask(good)
    date = ee.Image.constant(image.date().millis()).rename("ndvi_observation_ms")
    source = ee.Image.constant(2).rename("ndvi_sensor")
    return ndvi.addBands([date, source]).updateMask(ndvi.mask()).toDouble()


def preferred_ndvi(sentinel, landsat):
    """Prefer Sentinel-2 per valid pixel, even if a Landsat pixel is newer."""
    schema = ["NDVI", "ndvi_observation_ms", "ndvi_sensor"]
    fallback = ee.ImageCollection.fromImages([masked_image(schema)])
    s2 = sentinel.merge(fallback)
    ls = landsat.merge(fallback)
    s2_latest = s2.qualityMosaic("ndvi_observation_ms")
    ls_latest = ls.qualityMosaic("ndvi_observation_ms")
    latest = s2_latest.unmask(ls_latest, sameFootprint=False)
    s2_count = s2.select("NDVI").count().unmask(0)
    ls_count = ls.select("NDVI").count().unmask(0)
    count = ls_count.where(s2_count.gt(0), s2_count).rename("ndvi_valid_observations")
    return latest, count


def temporal_images(cutoff, event_date, region, use_latest_landcover=False):
    """Temporal rasters contain only observations before the local event day.

    use_latest_landcover=True skips the year-1 anti-leakage rule below and
    uses the most recent available RLCMS classification instead -- only
    correct for a present-day map with no specific event to leak information
    about (see gee_export_factor_grid_local.py); training/point-sampling
    callers must keep the default so no event sees a land-cover map from its
    own or a later year."""
    cutoff = ee.Date(cutoff)
    start = cutoff.advance(-NDVI_LOOKBACK_DAYS, "day")
    collection = ee.ImageCollection([])
    for key, red, nir, sensor in [
        ("landsat5", "SR_B3", "SR_B4", 5), ("landsat7", "SR_B3", "SR_B4", 7),
        ("landsat8", "SR_B4", "SR_B5", 8), ("landsat9", "SR_B4", "SR_B5", 9),
    ]:
        scenes = ee.ImageCollection(GEE_ASSETS[key]).filterBounds(region).filterDate(start, cutoff)
        processed = scenes.map(lambda image, r=red, n=nir, code=sensor:
                               landsat_ndvi(image, r, n, code))
        collection = collection.merge(processed)
    sentinel = ee.ImageCollection(GEE_ASSETS["sentinel2"]).filterBounds(region).filterDate(
        start, cutoff).map(sentinel2_ndvi)
    latest, count = preferred_ndvi(sentinel, collection)
    age = ee.Image.constant(cutoff.millis()).subtract(
        latest.select("ndvi_observation_ms")).divide(86400000).rename("ndvi_age_days")
    local_asset = GEE_ASSETS.get("land_cover")
    if use_latest_landcover:
        # No event to leak information about: use whichever RLCMS year is
        # most recently published, for the best-available current land cover.
        annual = (ee.ImageCollection(local_asset).filterBounds(region)
                  .select(["lc"], ["LULC_SERVIR"]).sort("system:time_start", False)
                  if local_asset and local_asset != "None" else ee.ImageCollection([]))
    else:
        # Annual maps may use the entire labelled year: never use the event-year map.
        year = ee.Number.parse(ee.String(event_date).slice(0, 4)).subtract(1)
        year_start = ee.Date.fromYMD(year, 1, 1)
        annual = (ee.ImageCollection(local_asset).filterDate(
            year_start, year_start.advance(1, "year")).select(["lc"], ["LULC_SERVIR"])
            if local_asset and local_asset != "None" else ee.ImageCollection([]))
    local = ee.Image(ee.Algorithms.If(
        annual.size().gt(0), annual.first(), masked_image(["LULC_SERVIR"])))
    # Only codes defined by the site's legend are valid; 0/255 are not classes.
    local = local.updateMask(local.gte(1).And(local.lte(19)))
    if use_latest_landcover:
        year = ee.Number(ee.Algorithms.If(
            annual.size().gt(0),
            ee.Date(ee.Image(annual.first()).get("system:time_start")).get("year"), -1))
    def prepare_landcover(image):
        confidence = image.select(["water", "trees", "grass", "flooded_vegetation",
                                   "crops", "shrub_and_scrub", "built", "bare", "snow_and_ice"]).reduce(ee.Reducer.max())
        label = image.select("label").rename("LULC").updateMask(
            confidence.gte(LAND_COVER_MIN_CONFIDENCE))
        timestamp = ee.Image.constant(image.date().millis()).rename("land_cover_observation_ms")
        return label.addBands(timestamp).updateMask(label.mask()).toDouble()

    dw = ee.ImageCollection(GEE_ASSETS["land_cover_fine"]).filterBounds(region).filterDate(
        cutoff.advance(-LAND_COVER_LOOKBACK_DAYS, "day"), cutoff).map(prepare_landcover)
    dw = dw.merge(ee.ImageCollection.fromImages([
        masked_image(["LULC", "land_cover_observation_ms"])]))
    fine = dw.qualityMosaic("land_cover_observation_ms")
    preferred = prefer_local_landcover(local, fine)
    ndvi_resolution = latest.select("ndvi_sensor").remap([2,5,7,8,9], [10,30,30,30,30]).rename("ndvi_resolution_m")
    return latest.addBands([count, age, local, preferred, ndvi_resolution]), year


def sample_event_factors(layers, events, terrain_reference="SRTM_February_2000_baseline",
                         use_merit=False, landslide_label=1):
    """One row per point; nulls retain missing historical observations.

    landslide_label=0 samples non-landslide (pseudo-absence) points using the
    same pre-event temporal cutoff logic, so both classes see comparable
    sensor coverage/season instead of a fixed "current day" snapshot.
    """
    def event_metadata(feature):
        coordinates = feature.geometry().coordinates()
        return ee.Feature(feature.geometry(), feature.toDictionary(EVENT_PROPERTIES)).set({
            "longitude": coordinates.get(0), "latitude": coordinates.get(1),
            "landslide": landslide_label,
            "temporal_policy": "strictly_before_local_event_day",
            "terrain_reference": terrain_reference,
            "hydrology_reference": "MERIT_2019_static_model" if use_merit else "HydroSHEDS_static_baseline",
            "hydrology_resolution_m": 90 if use_merit else 500,
            "soil_temporal_status": "static_model_not_event_dated",
            "roads_rivers_temporal_status": "current_snapshot_allowed_if_configured",
        })

    samples = events.map(event_metadata)
    # Sample soils/hydrology on their own grids rather than forcing 30 m detail.
    groups = {}
    for name, image in layers.items():
        scale = NATIVE_SCALES["soil"] if name.startswith("soil_") else (
            NATIVE_SCALES["merit" if use_merit else "hydrology"] if name in {"upstream_area_km2", "dist_to_stream", "drainage_density"}
            else NATIVE_SCALES["terrain"])
        groups.setdefault(scale, []).append(image.rename(name))
    for scale, images in groups.items():
        samples = ee.Image.cat(images).reduceRegions(
            collection=samples, reducer=ee.Reducer.first(), scale=scale,
            crs=EXPORT_CRS, tileScale=4)

    def add_temporal(feature):
        image, year = temporal_images(feature.get("event_cutoff"), feature.get("event_date"),
                                      feature.geometry())
        values = image.reduceRegion(reducer=ee.Reducer.first(), geometry=feature.geometry(),
                                    scale=NATIVE_SCALES["sentinel2"], crs=EXPORT_CRS, tileScale=4)
        return feature.set(values).set("land_cover_year", year)

    return samples.map(add_temporal)


def _event_identifier(feature_list, offset):
    props = feature_list[offset].get("properties", {})
    return props.get("inventory_id", props.get("Event_ID", f"list-index-{offset}"))


def fetch_samples_chunk(feature_list, offset, count, aoi, srtm_layers, alos_layers, merit_layers, label):
    """getInfo() one slice of sampled events.

    The slice is cut from the raw client-side event list, before
    sample_by_dem_era builds the per-era reduceRegions/temporal-mosaic graph:
    reduceRegions and .map() already span whatever collection they're given,
    so slicing the *output* samples collection (or an already-built
    ee.FeatureCollection's server-side toList()) would not reduce server-side
    work -- Earth Engine still has to evaluate every input feature's temporal
    factors to produce the requested slice. Cutting the input list itself is
    what actually shrinks the computation, and needs no getInfo() round trip
    to know how many events there are.

    Resilience, in order: a "User memory limit exceeded" error is deterministic
    for a given slice size -- retrying the identical request would just fail
    again -- so it goes straight to halving. Any other (likely transient)
    error is retried up to BATCH_RETRY_ATTEMPTS times with a backoff first.
    Once retries are exhausted, a slice of more than one point is split in
    half and recursed (a smaller slice is less likely to hit the memory
    limit); a single point that still fails is skipped (logged) instead of
    aborting the whole run.
    """
    chunk = ee.FeatureCollection({
        "type": "FeatureCollection", "features": feature_list[offset:offset + count],
    }).filterBounds(aoi)
    chunk_samples = sample_by_dem_era(chunk, srtm_layers, alos_layers, merit_layers, landslide_label=label)
    last_exc = None
    for attempt in range(1, BATCH_RETRY_ATTEMPTS + 1):
        try:
            return chunk_samples.getInfo()["features"]
        except Exception as exc:
            last_exc = exc
            is_memory_limit = (isinstance(exc, ee.ee_exception.EEException)
                               and "memory limit" in str(exc).lower())
            if is_memory_limit:
                break
            if attempt < BATCH_RETRY_ATTEMPTS:
                print(f"Batch of {count} at offset {offset} failed on attempt {attempt}/"
                      f"{BATCH_RETRY_ATTEMPTS} ({exc}); retrying...", flush=True)
                time.sleep(BATCH_RETRY_BACKOFF_SECONDS)
    if count > 1:
        half = count // 2
        print(f"Batch of {count} at offset {offset} still failing ({last_exc}); "
              f"splitting into {half} + {count - half}", flush=True)
        return (fetch_samples_chunk(feature_list, offset, half, aoi, srtm_layers, alos_layers, merit_layers, label) +
                fetch_samples_chunk(feature_list, offset + half, count - half, aoi, srtm_layers, alos_layers, merit_layers, label))
    identifier = _event_identifier(feature_list, offset)
    print(f"SKIPPING point at offset {offset} (id={identifier}, landslide={label}): "
          f"{last_exc}", flush=True)
    return []


def retrieve_all_samples(event_groups, aoi, srtm_layers, alos_layers, merit_layers, factor_names, path):
    """event_groups: [(feature_list, landslide_label), ...] of raw client-side
    event features (see load_geojson_features). Batches at the raw event
    level so each request's temporal-factor computation graph stays small
    enough for Earth Engine's per-request memory limit, and writes each
    retrieved batch to path immediately via ChunkedCsvWriter so a run that's
    interrupted partway keeps everything retrieved so far."""
    writer = ChunkedCsvWriter(path, factor_names)
    retrieved = 0
    for feature_list, label in event_groups:
        total = len(feature_list)
        for offset in range(0, total, SAMPLE_BATCH_SIZE):
            count = min(SAMPLE_BATCH_SIZE, total - offset)
            batch = fetch_samples_chunk(
                feature_list, offset, count, aoi, srtm_layers, alos_layers, merit_layers, label)
            writer.write_batch(batch)
            retrieved += len(batch)
            print(f"Retrieved {retrieved} sample rows so far "
                  f"(landslide={label}, {offset + count}/{total})...", flush=True)
    writer.close()


def annotate_feature(feature):
    """Validate and enrich one retrieved feature's properties in place."""
    props = feature.setdefault("properties", {})
    litho_code = props.get("lithology")
    if litho_code is not None:
        if litho_code not in GLIM_CLASSES:
            raise ValueError(f"Unknown lithology code: {litho_code}")
        props["lithology_class_name"] = GLIM_CLASSES[litho_code]
    observed = props.get("ndvi_observation_ms")
    props["ndvi_status"] = "ok" if props.get("NDVI") is not None else "no_valid_prior_pixel"
    props["land_cover_status"] = "ok" if props.get("LULC") is not None else "no_valid_prior_pixel"
    code, source = props.get("LULC"), props.get("land_cover_source")
    if code is not None:
        legend = SERVIR_CLASSES if source == 1 else DYNAMIC_WORLD_CLASSES if source == 2 else {}
        if code not in legend:
            raise ValueError(f"Unknown land-cover code/source: {code}/{source}")
        props["land_cover_class_name"] = legend[code]
        prefix = "servir" if source == 1 else "dynamic_world"
        props["land_cover_class_key"] = f"{prefix}:{int(code)}"
    if observed is not None:
        cutoff = datetime.fromisoformat(props["event_cutoff"])
        observation = datetime.fromtimestamp(observed / 1000, ZoneInfo(EVENT_TIMEZONE))
        if not cutoff - timedelta(days=NDVI_LOOKBACK_DAYS) <= observation < cutoff:
            raise ValueError("NDVI observation violates the pre-event time window.")
        props["ndvi_observation_date"] = observation.isoformat()
    if props.get("land_cover_year") != int(props["event_date"][:4]) - 1:
        raise ValueError("Land-cover year must precede the event year.")
    landcover_time = props.get("land_cover_observation_ms")
    if landcover_time is not None:
        cutoff = datetime.fromisoformat(props["event_cutoff"])
        observation = datetime.fromtimestamp(landcover_time / 1000, ZoneInfo(EVENT_TIMEZONE))
        if not cutoff - timedelta(days=LAND_COVER_LOOKBACK_DAYS) <= observation < cutoff:
            raise ValueError("Land-cover observation violates the pre-event time window.")


def save_event_samples(features, factor_names, path):
    """Write a complete, already-retrieved feature list to CSV in one shot.

    For large inventories, prefer ChunkedCsvWriter via retrieve_all_samples,
    which writes each batch as it's retrieved instead of holding everything
    in memory until the very end.
    """
    columns = [*EVENT_PROPERTIES, "longitude", "latitude", "landslide", *factor_names,
               "lithology_class_name", *TEMPORAL_COLUMNS]
    for feature in features:
        annotate_feature(feature)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(feature.get("properties", {}) for feature in features)
    missing = sum(any(feature.get("properties", {}).get(name) is None
                      for name in [*factor_names, "NDVI", "LULC"]) for feature in features)
    print(f"Saved {len(features)} event rows to {path}; {missing} rows have missing factors.")


class ChunkedCsvWriter:
    """Writes retrieved sample batches to CSV as they arrive.

    A multi-thousand-point inventory can take hours to retrieve; holding
    every feature in memory and writing once at the end means a crash or
    interruption near the finish loses the whole run. Each batch is flushed
    to disk as soon as it's fetched instead.
    """

    def __init__(self, path, factor_names):
        self.path = path
        self.factor_names = factor_names
        self.total = 0
        self.missing = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("w", newline="", encoding="utf-8")
        columns = [*EVENT_PROPERTIES, "longitude", "latitude", "landslide", *factor_names,
                   "lithology_class_name", *TEMPORAL_COLUMNS]
        self._writer = csv.DictWriter(self._handle, fieldnames=columns, extrasaction="ignore")
        self._writer.writeheader()

    def write_batch(self, features):
        for feature in features:
            annotate_feature(feature)
        self._writer.writerows(feature.get("properties", {}) for feature in features)
        self._handle.flush()
        self.total += len(features)
        self.missing += sum(any(feature.get("properties", {}).get(name) is None
                                for name in [*self.factor_names, "NDVI", "LULC"]) for feature in features)

    def close(self):
        self._handle.close()
        print(f"Saved {self.total} event rows to {self.path}; {self.missing} rows have missing factors.")


def dem_sources(aoi):
    srtm = ee.Image(GEE_ASSETS["dem_fallback"]).select("elevation")
    def valid_alos(tile):
        # Exclude void fills of uncertain/later acquisition dates.
        return tile.select("DSM").updateMask(tile.select("MSK").eq(0)).rename("elevation")
    alos = ee.ImageCollection(GEE_ASSETS["dem"]).filterBounds(aoi).map(valid_alos).mosaic()
    alos = alos.setDefaultProjection(EXPORT_CRS, None, 30)
    source = ee.Image.constant(2).updateMask(alos.mask()).unmask(
        ee.Image.constant(1).updateMask(srtm.mask()), sameFootprint=False).rename("dem_source")
    return srtm, alos.unmask(srtm, sameFootprint=False), source


def build_factor_layers(aoi, dem, use_merit=False):
    # ---------------------------------------------------------------------------
    # TOPOGRAPHIC FACTORS (from DEM)
    # ---------------------------------------------------------------------------
    dem = dem.clip(aoi)
    dem = dem.setDefaultProjection(EXPORT_CRS, None, EXPORT_SCALE).rename("elevation")

    terrain = ee.Terrain.products(dem)
    slope = terrain.select("slope").rename("slope")
    aspect = terrain.select("aspect").rename("aspect")
    hillshade = terrain.select("hillshade").rename("hillshade")

    # Plan / profile curvature via second-derivative kernels (Zevenbergen-Thorne
    # approximation). For publication-grade curvature, cross-check in SAGA GIS.
    kernel_size = 3
    laplacian_kernel = ee.Kernel.laplacian8(normalize=False)
    general_curvature = dem.convolve(laplacian_kernel).rename("curvature_general")

    # Profile curvature (curvature along slope direction) - approximate via
    # second derivative of slope in the direction of steepest descent.
    dz_dx = dem.convolve(ee.Kernel.fixed(3, 3, [[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]])).divide(8)
    dz_dy = dem.convolve(ee.Kernel.fixed(3, 3, [[-1, -2, -1], [0, 0, 0], [1, 2, 1]])).divide(8)
    profile_curvature = dz_dx.pow(2).add(dz_dy.pow(2)).sqrt().rename("curvature_profile")

    # Terrain Ruggedness Index (TRI) - mean absolute elevation difference to neighbors
    tri = dem.subtract(dem.focalMean(radius=1, kernelType="square", units="pixels")) \
             .abs().focalMean(radius=1, kernelType="square", units="pixels") \
             .rename("TRI")

    # Topographic Position Index (TPI) - elevation minus mean of surrounding cells
    tpi = dem.subtract(dem.focalMean(radius=3, kernelType="circle", units="pixels")).rename("TPI")

    # LS-factor (slope length-steepness, RUSLE-style approximation)
    slope_rad = slope.multiply(3.14159265).divide(180)
    ls_factor = (slope_rad.sin().divide(0.0896)).pow(1.3) \
        .multiply((dem.focalMax(radius=5, units="pixels").subtract(dem)).divide(22.13).pow(0.4)) \
        .rename("LS_factor")

    topo_stack = dem.addBands([slope, aspect, general_curvature, profile_curvature,
                                tri, tpi, ls_factor])

    # ---------------------------------------------------------------------------
    # HYDROLOGICAL FACTORS (HydroSHEDS flow accumulation, avoids manual
    #    flow-routing in GEE which is unreliable at scale)
    # ---------------------------------------------------------------------------
    # Normalize source units: MERIT upa is km²; HydroSHEDS stores upstream cells.
    hydro = ee.Image(GEE_ASSETS["hydrology_fine"] if use_merit else GEE_ASSETS["flow_accumulation"])
    grid = hydro.select("upa").projection() if use_merit else hydro.projection()
    cell_area = ee.Image.pixelArea().reproject(grid)
    upstream_area = (hydro.select("upa") if use_merit else
                     hydro.multiply(cell_area).divide(1e6)).rename("upstream_area_km2")
    flow_area_m2 = upstream_area.multiply(1e6).max(cell_area)
    streams = upstream_area.gt(100).selfMask()  # 100 km² contributing-area threshold; tune locally.
    grid_width = cell_area.sqrt()
    distance_to_stream = streams.unmask(0).fastDistanceTransform(256).sqrt().multiply(
        grid_width).rename("dist_to_stream").clip(aoi)
    drainage_density = streams.unmask(0).multiply(grid_width).reduceNeighborhood(
        reducer=ee.Reducer.sum(),
        kernel=ee.Kernel.circle(radius=500, units="meters", normalize=False)).divide(
            3.14159265 * 500 * 500).rename("drainage_density").clip(aoi)
    # Approximate specific catchment area A / grid width (m); shared units across sources.
    specific_area = flow_area_m2.divide(grid_width)
    slope_rad_safe = slope_rad.max(0.001)
    twi = specific_area.log().subtract(slope_rad_safe.tan().log()).rename("TWI")
    spi = specific_area.multiply(slope_rad_safe.tan()).rename("SPI")

    # NDVI and annual land cover are selected separately for each event below.

    # ---------------------------------------------------------------------------
    # SOIL FACTORS (OpenLandMap, 250 m, 0 cm depth band = surface)
    # ---------------------------------------------------------------------------
    soil_texture = ee.Image(GEE_ASSETS["soil_texture"]) \
        .select("b0").rename("soil_texture").clip(aoi)
    soil_clay = ee.Image(GEE_ASSETS["soil_clay"]) \
        .select("b0").rename("soil_clay_pct").clip(aoi)
    soil_sand = ee.Image(GEE_ASSETS["soil_sand"]) \
        .select("b0").rename("soil_sand_pct").clip(aoi)
    soil_bulkdensity = ee.Image(GEE_ASSETS["soil_bulk_density"]) \
        .select("b0").rename("soil_bulk_density").clip(aoi)

    soil_stack = soil_texture.addBands([soil_clay, soil_sand, soil_bulkdensity])

    # ---------------------------------------------------------------------------
    # SAMPLE FACTORS AT EVENT POINTS; OPTIONALLY EXPORT FULL RASTERS
    # ---------------------------------------------------------------------------
    export_layers = {
        "elevation": dem,
        "slope": slope,
        "aspect": aspect,
        "curvature_general": general_curvature,
        "curvature_profile": profile_curvature,
        "TRI": tri,
        "TPI": tpi,
        "LS_factor": ls_factor,
        "upstream_area_km2": upstream_area.clip(aoi),
        "dist_to_stream": distance_to_stream,
        "drainage_density": drainage_density,
        "TWI": twi,
        "SPI": spi,
        "soil_texture": soil_texture,
        "soil_clay_pct": soil_clay,
        "soil_sand_pct": soil_sand,
        "soil_bulk_density": soil_bulkdensity,
    }

    # Uploaded OSM snapshots are explicitly allowed to be current. Keep the
    # buffered vector extent when computing distances, then clip the result.
    # FeatureCollection.distance() scales with how many features it has to
    # consider, not with the output size: without a spatial pre-filter it
    # walks the *entire* unfiltered vector layer for every request, which
    # reliably exceeds Earth Engine's interactive memory limit even for a
    # small output tile (see gee_export_factor_grid_local.py). Filtering to
    # a search-radius buffer around aoi first fixes that and never changes
    # the result, since features farther than searchRadius can't affect it.
    for key, name in [("roads", "dist_to_road"), ("rivers", "dist_to_river"),
                      ("faults", "dist_to_fault")]:
        asset_id = GEE_ASSETS[key]
        if asset_id and asset_id != "None":
            nearby = ee.FeatureCollection(asset_id).filterBounds(aoi.buffer(20_000, 100))
            export_layers[name] = nearby.distance(
                searchRadius=20_000, maxError=10).rename(name).clip(aoi)
        else:
            print(f"{key}: asset not configured; distance factor omitted.")

    lithology_id = GEE_ASSETS["lithology"]
    if lithology_id and lithology_id != "None":
        # Without an explicit projection, reduceToImage rasterizes at GEE's
        # default (near-native-resolution) pyramid level, which is far finer
        # than GLiM's ~1:3,750,000 source precision and can exceed the
        # server's per-request memory limit. 1 km reflects that source scale.
        # Pre-filtering to aoi for the same reason as the distance layers above.
        export_layers["lithology"] = ee.FeatureCollection(lithology_id).filterBounds(aoi).reduceToImage(
            properties=["litho_code"], reducer=ee.Reducer.first()).toInt().rename(
            "lithology").reproject(crs=EXPORT_CRS, scale=1000).clip(aoi)
    else:
        print("lithology: asset not configured; lithology factor omitted.")

    return export_layers


# Bands whose values are discrete class codes; these must never be
# interpolated when resampled onto the shared export grid below -- only
# continuous physical quantities get bilinear resampling.
CATEGORICAL_EXPORT_BANDS = {"lithology", "soil_texture", "dem_source", "land_cover_source"}


def prepare_export_band(name, image):
    """Reproject one factor band onto the shared EXPORT_CRS/EXPORT_SCALE grid.

    Every band in a stack must share one grid (CRS, scale, and pixel
    alignment) before ee.Image.cat: left alone, each band keeps its own
    native projection (elevation at 30 m, soil at 250 m, hydrology at 90/500 m,
    NDVI/LULC at 10 m, lithology at 1 km) and GEE resamples each
    inconsistently at export time, so the output bands would not line up
    pixel-for-pixel. Categorical class rasters (lithology, soil texture,
    dem_source, land-cover codes) keep nearest-neighbor (the default) so a
    resample never invents a fractional class; continuous physical
    quantities use bilinear.
    """
    categorical = name in CATEGORICAL_EXPORT_BANDS or "LULC" in name
    prepared = image if categorical else image.resample("bilinear")
    return prepared.reproject(crs=EXPORT_CRS, scale=EXPORT_SCALE).rename(name)


def export_factor_stack(group_name, layers, aoi):
    """Combine one baseline's factor layers into a single aligned multi-band
    GeoTIFF: one export run yields one raster stack ready to feed a trained
    model pixel-by-pixel, instead of one file per band at mismatched
    resolutions."""
    bands = [prepare_export_band(name, image) for name, image in layers.items()]
    stack = ee.Image.cat(bands).clip(aoi)
    return ee.batch.Export.image.toCloudStorage(
        image=stack,
        description=f"landslide_{group_name}",
        bucket=EXPORT_BUCKET,
        fileNamePrefix=f"{EXPORT_PREFIX}/{group_name}",
        region=aoi,
        scale=EXPORT_SCALE,
        crs=EXPORT_CRS,
        maxPixels=1e13,
    )


def sample_by_dem_era(events_in_aoi, srtm_layers, alos_layers, merit_layers, landslide_label=1):
    """Split points by DEM-era availability and sample each era's factor stack.

    Both landslide and non-landslide points use identical event-date cutoffs
    here, so the non-landslide class sees the same DEM/hydrology baselines and
    pre-event NDVI/land-cover lookback windows as the landslide class for a
    point falling in the same period, rather than a fixed present-day snapshot.
    """
    early = events_in_aoi.filter(ee.Filter.lt("event_date", ALOS_EARLIEST_EVENT))
    later = events_in_aoi.filter(ee.Filter.gte("event_date", ALOS_EARLIEST_EVENT)).filter(
        ee.Filter.lt("event_date", MERIT_EARLIEST_EVENT))
    recent = events_in_aoi.filter(ee.Filter.gte("event_date", MERIT_EARLIEST_EVENT))
    return sample_event_factors(srtm_layers, early, landslide_label=landslide_label).merge(
        sample_event_factors(alos_layers, later, "ALOS_2006_2011_with_SRTM_gap_fallback",
                             landslide_label=landslide_label)).merge(
        sample_event_factors(merit_layers, recent, "ALOS_2006_2011_with_SRTM_gap_fallback",
                             use_merit=True, landslide_label=landslide_label))


def main(argv=None):
    args = parse_args(argv)
    if args.export and not EXPORT_BUCKET:
        raise ValueError("Set EXPORT_BUCKET or GEE_EXPORT_BUCKET before using --export.")
    if not SERVICE_ACCOUNT_KEY:
        raise ValueError("Set SERVICE_ACCOUNT_KEY to your service-account JSON key path.")
    initialize_gee(project_path(SERVICE_ACCOUNT_KEY), GEE_PROJECT)

    study_area = geojson_to_feature_collection(project_path(data_path))
    aoi = study_area.geometry()
    # filterBounds happens per-batch inside fetch_samples_chunk, once each
    # chunk is an ee.FeatureCollection.
    landslide_features = load_geojson_features(project_path(landslide_events_path), event_dates=True)

    srtm, alos, dem_source = dem_sources(aoi)
    srtm_layers = build_factor_layers(aoi, srtm)
    alos_layers = build_factor_layers(aoi, alos)
    merit_layers = build_factor_layers(aoi, alos, use_merit=True)
    srtm_layers["dem_source"] = ee.Image.constant(1).updateMask(srtm.mask())
    alos_layers["dem_source"] = dem_source
    merit_layers["dem_source"] = dem_source
    event_groups = [(landslide_features, 1)]

    non_landslide_path = project_path(non_landslide_events_path)
    if non_landslide_path.exists():
        non_landslide_features = load_geojson_features(non_landslide_path, event_dates=True)
        event_groups.append((non_landslide_features, 0))
    else:
        print(f"{non_landslide_path}: not found; skipping non-landslide samples. "
              "Run generate_paired_negatives.py first.")

    export_layers = alos_layers
    retrieve_all_samples(event_groups, aoi, srtm_layers, alos_layers, merit_layers,
                         list(export_layers), SAMPLE_CSV)
    if not args.export:
        print("Raster exports disabled. Use --export to submit GeoTIFF exports.")
        return

    if EXPORT_REFERENCE_DATE:
        reference_layers = dict(srtm_layers if EXPORT_REFERENCE_DATE < ALOS_EARLIEST_EVENT else
                                alos_layers if EXPORT_REFERENCE_DATE < MERIT_EARLIEST_EVENT else merit_layers)
        day, cutoff = normalize_event_date({"date_parsed": EXPORT_REFERENCE_DATE})
        temporal, _ = temporal_images(cutoff, day, aoi, use_latest_landcover=True)
        reference_layers["NDVI"] = temporal.select("NDVI")
        reference_layers["LULC_current"] = temporal.select("LULC")
        export_groups = {f"factor_stack_{day}": reference_layers}
    else:
        export_groups = {"srtm_factor_stack": srtm_layers, "alos_factor_stack": alos_layers,
                         "merit_factor_stack": merit_layers}
        print("Exporting one combined GeoTIFF per DEM-era baseline; set EXPORT_REFERENCE_DATE for a single dated stack.")

    tasks = []
    for group_name, layers in export_groups.items():
        task = export_factor_stack(group_name, layers, aoi)
        task.start()
        tasks.append(task)
        print(f"Started export: {group_name} ({len(layers)} bands, {EXPORT_SCALE} m, {EXPORT_CRS})")

    print(f"\n{len(tasks)} export task(s) submitted to gs://{EXPORT_BUCKET}/{EXPORT_PREFIX}/")
    print(f"Each GeoTIFF is a single multi-band stack, every band already reprojected onto the same "
          f"{EXPORT_SCALE} m / {EXPORT_CRS} grid -- ready to feed a trained model pixel-by-pixel to "
          "build a susceptibility map.")
    print("Task IDs (query ee.data.getTaskStatus using the same service account):")
    for task in tasks:
        print(task.id)


if __name__ == "__main__":
    main()
