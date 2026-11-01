"""Export the current-conditions conditioning-factor stack as local GeoTIFF
tiles -- no Cloud Storage bucket required.

Earth Engine's only bulk-export destinations are Cloud Storage, Drive, or a
GEE asset; there is no "export to local disk". This instead downloads the
same aligned factor stack built in gee_landslide_factors.py directly via
Image.getDownloadURL(), one small tile at a time (a single request over the
whole study area would be tens of GB and exceed GEE's per-request limit).

Run (dry run, no downloads): python scripts/gee_export_factor_grid_local.py --dry-run
Run (actual download):       python scripts/gee_export_factor_grid_local.py
"""

import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import socket
import time
import urllib.error
import urllib.request

import ee
from shapely.geometry import box, shape

# As in gee_imerg_antecedent_rainfall.py: the GEE client (and the urllib
# download below) have no built-in request timeout, so a stalled connection
# can hang getInfo()/urlopen() forever instead of raising for the retry loops
# to catch.
socket.setdefaulttimeout(120)

import gee_landslide_factors as factors

PROJECT_DIR = factors.PROJECT_DIR
OUTPUT_DIR = PROJECT_DIR / "data" / "cache" / "factor_grid_local"
# None = today (UTC date), i.e. the most recent available NDVI/land-cover
# snapshot -- a susceptibility map has no single historical event date, so it
# uses present-day conditions. Set an explicit "YYYY-MM-DD" to pin it instead.
REFERENCE_DATE = None
# ~960x960 px per tile at 30 m/px per band. The per-request "User memory
# limit exceeded" failure tracks band count (and, to a lesser extent, tile
# size) per request, not pixel count alone -- so tile size here is chosen for
# total request count (fewer, larger tiles under a limited Earth Engine
# quota), while
# download_band_group() below adapts the per-request band count to whatever
# that limit actually is for a given tile/band combination.
TILE_SIZE_M = 28800
TILE_RETRY_ATTEMPTS = 4
TILE_RETRY_BACKOFF_SECONDS = 5
# Every request costs ~1 min under a limited Earth Engine quota whether it
# succeeds or fails, so start at a size that mostly succeeds (4 bands: 4 of 6 groups
# passed at this tile size) and only halve the groups that fail.
INITIAL_BAND_GROUP_SIZE = 4


def reference_date_string():
    return REFERENCE_DATE or datetime.now(timezone.utc).date().isoformat()


def load_boundary_polygon():
    """Local WGS84 boundary geometry, used only for client-side tile-vs-land
    filtering with shapely -- no GEE round trip needed to skip ocean tiles."""
    features = factors.load_geojson_features(factors.project_path(factors.data_path))
    geometries = [shape(feature["geometry"]) for feature in features]
    polygon = geometries[0]
    for geometry in geometries[1:]:
        polygon = polygon.union(geometry)
    return polygon


def build_static_layers(aoi, day):
    """Mirrors gee_landslide_factors.main()'s EXPORT_REFERENCE_DATE branch:
    pick whichever DEM/hydrology baseline was valid on the reference date.
    These bands are plain rasters (no ImageCollection.filterBounds over a
    large scene archive), so building them once against the whole AOI is
    cheap regardless of tile size."""
    srtm, alos, dem_source = factors.dem_sources(aoi)
    if day < factors.ALOS_EARLIEST_EVENT:
        layers = factors.build_factor_layers(aoi, srtm)
        layers["dem_source"] = ee.Image.constant(1).updateMask(srtm.mask())
    elif day < factors.MERIT_EARLIEST_EVENT:
        layers = factors.build_factor_layers(aoi, alos)
        layers["dem_source"] = dem_source
    else:
        layers = factors.build_factor_layers(aoi, alos, use_merit=True)
        layers["dem_source"] = dem_source
    return layers


def build_temporal_layers(tile_geom, day):
    """NDVI/land-cover for one tile only.

    temporal_images() filters Landsat/Sentinel-2 by ImageCollection.filterBounds(region)
    then builds a qualityMosaic -- that's real, expensive server-side
    computation, unlike the static bands above. Scoping `region` to one small
    tile (instead of the whole AOI) keeps each request's collection small
    enough to fit Earth Engine's interactive getDownloadURL memory limit;
    passing the full AOI here reliably hit "User memory limit exceeded" on
    every tile, even a ~9 km one, because the mosaic was rebuilt over every
    scene touching the entire study area before being clipped down.
    """
    _, cutoff = factors.normalize_event_date({"date_parsed": day})
    temporal, _ = factors.temporal_images(cutoff, day, tile_geom, use_latest_landcover=True)
    return {"NDVI": temporal.select("NDVI"), "LULC_current": temporal.select("LULC")}


def build_stack_image(layers, clip_geom):
    bands = [factors.prepare_export_band(name, image) for name, image in layers.items()]
    return ee.Image.cat(bands).clip(clip_geom)


def tile_grid(boundary_polygon):
    """Rectangular tiles in WGS84 degrees, sized to ~TILE_SIZE_M on the
    ground; longitude step is latitude-dependent so tiles stay roughly
    square. Only tiles that actually intersect the study-area polygon are
    kept -- ocean/out-of-AOI tiles are skipped without ever calling GEE."""
    min_lon, min_lat, max_lon, max_lat = boundary_polygon.bounds
    lat_step = TILE_SIZE_M / 110_574
    tiles = []
    lat = min_lat
    row = 0
    while lat < max_lat:
        lat_next = min(lat + lat_step, max_lat)
        mid_lat = (lat + lat_next) / 2
        lon_step = TILE_SIZE_M / (111_320 * max(math.cos(math.radians(mid_lat)), 0.1))
        lon = min_lon
        col = 0
        while lon < max_lon:
            lon_next = min(lon + lon_step, max_lon)
            cell = box(lon, lat, lon_next, lat_next)
            if boundary_polygon.intersects(cell):
                tiles.append((row, col, lon, lat, lon_next, lat_next))
            lon = lon_next
            col += 1
        lat = lat_next
        row += 1
    return tiles


def band_group_path(out_dir, row, col, band_items):
    names = "-".join(name for name, _ in band_items)
    return out_dir / f"tile_r{row:03d}_c{col:03d}__{names}.tif"


def download_request(stack_image, region, out_path):
    """One getDownloadURL + fetch. Distinguishes the deterministic "User
    memory limit exceeded" error (retrying the identical request would just
    fail again) from transient errors (worth a retry+backoff first) -- same
    split gee_landslide_factors.py's fetch_samples_chunk makes for batch
    memory-limit errors."""
    last_exc = None
    for attempt in range(1, TILE_RETRY_ATTEMPTS + 1):
        try:
            url = stack_image.getDownloadURL({
                "region": region, "scale": factors.EXPORT_SCALE, "crs": factors.EXPORT_CRS,
                "format": "GEO_TIFF",
            })
            with urllib.request.urlopen(url, timeout=180) as response:
                data = response.read()
            if len(data) == 0:
                raise ValueError("Empty response body.")
            partial = out_path.with_suffix(".tif.part")
            partial.write_bytes(data)
            partial.replace(out_path)
            return "ok"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            last_exc = f"HTTP {exc.code}: {body[:200].strip()}"
            if "memory limit" in body.lower():
                break
            if attempt < TILE_RETRY_ATTEMPTS:
                time.sleep(TILE_RETRY_BACKOFF_SECONDS * attempt)
        except Exception as exc:
            last_exc = repr(exc)
            if attempt < TILE_RETRY_ATTEMPTS:
                time.sleep(TILE_RETRY_BACKOFF_SECONDS * attempt)
    return f"ERROR: {last_exc}"


def download_band_group(band_items, region, tile_aoi, row, col, out_dir):
    """Download one tile's band_items as a single request; on failure, split
    in half and recurse (a smaller group is less likely to hit the memory
    limit); a single band that still fails is skipped (logged), not retried
    forever. The safe request size isn't a fixed constant -- it depends on
    which bands and how large the tile is (confirmed empirically: the same
    4-band chunk size that worked at one tile size partially failed at a
    larger one) -- so this adapts per band-group/tile combo instead of
    needing the chunk size hand-tuned for every tile-size change."""
    out_path = band_group_path(out_dir, row, col, band_items)
    if out_path.exists() and out_path.stat().st_size > 0:
        return ["skipped_existing"]
    stack_image = build_stack_image(dict(band_items), tile_aoi)
    status = download_request(stack_image, region, out_path)
    if status == "ok":
        return ["ok"]
    if len(band_items) > 1:
        half = len(band_items) // 2
        return (download_band_group(band_items[:half], region, tile_aoi, row, col, out_dir) +
                download_band_group(band_items[half:], region, tile_aoi, row, col, out_dir))
    return [status]


def download_tile(day, tile, aoi, out_dir):
    """Builds the whole stack (static + temporal) scoped to this tile's own
    small footprint -- not just NDVI. dem_sources()/build_factor_layers()
    also mosaic/filter image collections by whatever `aoi` they're given, so
    passing the full study area here hits the same "User memory limit
    exceeded" wall as an unscoped NDVI collection did; a tile-sized aoi keeps
    every one of those collection queries small. The band-group split/retry
    in download_band_group then handles the remaining per-request limit."""
    row, col, lon0, lat0, lon1, lat1 = tile
    region = ee.Geometry.Rectangle([lon0, lat0, lon1, lat1], geodesic=False)
    tile_aoi = region.intersection(aoi, maxError=1)
    layers = {**build_static_layers(tile_aoi, day), **build_temporal_layers(tile_aoi, day)}
    items = list(layers.items())
    statuses = []
    for i in range(0, len(items), INITIAL_BAND_GROUP_SIZE):
        statuses += download_band_group(items[i:i + INITIAL_BAND_GROUP_SIZE],
                                        region, tile_aoi, row, col, out_dir)
    errors = [s for s in statuses if s not in ("ok", "skipped_existing")]
    if errors:
        return f"partial_error ({len(errors)}/{len(statuses)} band-groups failed): {errors[0]}"
    if all(s == "skipped_existing" for s in statuses):
        return "skipped_existing"
    return "ok"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Only report the tile grid size/estimated volume; download nothing.")
    args = parser.parse_args()

    boundary_polygon = load_boundary_polygon()
    tiles = tile_grid(boundary_polygon)
    day = reference_date_string()
    print(f"Reference date: {day}")
    print(f"Tile size: ~{TILE_SIZE_M/1000:.1f} km; tiles intersecting the study area: {len(tiles)}")

    factors.initialize_gee(factors.project_path(factors.SERVICE_ACCOUNT_KEY), factors.GEE_PROJECT)
    study_area = factors.geojson_to_feature_collection(factors.project_path(factors.data_path))
    aoi = study_area.geometry()
    # Band names only, for bands.txt/estimation -- defining this graph against
    # the whole AOI is cheap (no getInfo/download); only per-tile evaluation
    # (in download_tile, using a tile-sized aoi) needs to stay small.
    band_names = list(build_static_layers(aoi, day).keys()) + ["NDVI", "LULC_current"]

    if args.dry_run:
        px_per_tile = (TILE_SIZE_M / factors.EXPORT_SCALE) ** 2
        bytes_per_tile = px_per_tile * len(band_names) * 4
        total_gb = bytes_per_tile * len(tiles) / 1e9
        print(f"Bands ({len(band_names)}): {band_names}")
        print(f"Estimated ~{bytes_per_tile/1e6:.1f} MB/tile, ~{total_gb:.1f} GB total across {len(tiles)} tiles.")
        return

    out_dir = OUTPUT_DIR / f"factor_stack_{day}"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Each file's own name lists exactly which bands it holds
    # (tile_rXXX_cYYY__band1-band2-....tif), since download_band_group()
    # splits adaptively rather than at one fixed chunk size -- bands.txt is
    # just the full reference list/order.
    (out_dir / "bands.txt").write_text("\n".join(band_names) + "\n")

    ok = skipped = errors = 0
    for index, tile in enumerate(tiles):
        status = download_tile(day, tile, aoi, out_dir)
        if status == "ok":
            ok += 1
        elif status == "skipped_existing":
            skipped += 1
        else:
            errors += 1
        print(f"[{index+1}/{len(tiles)}] tile r{tile[0]}c{tile[1]}: {status}", flush=True)
    print(f"\nDone: {ok} fully downloaded, {skipped} already present, {errors} with at least one failed band-group, "
          f"out of {len(tiles)} tiles.")
    print(f"Saved to {out_dir}")
    if errors:
        print("Re-run the same command to retry only the missing/failed band-groups (existing ones are skipped).")


if __name__ == "__main__":
    main()
