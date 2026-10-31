"""Sample the current-conditions conditioning-factor stack at a regular point
grid, instead of downloading full raster tiles.

Why this exists: gee_export_factor_grid_local.py (raster tiles via
Image.getDownloadURL) is slow under a limited Earth Engine quota (several
minutes per tile).

Point-sampling via Image.reduceRegions() -- the same technique
gee_landslide_factors.py already uses for the training-event inventory -- is
roughly 10-60x faster per tile (a maximum-density inland tile took ~80 s via
chunked reduceRegions vs. ~9 min via raster download). One limitation: reduceRegions aborts with
"Collection query aborted after accumulating over 5000 elements" once a
tile's point count gets large (inland tiles can have 13,000+ points at 250m
spacing) -- NOT because of any particular band, just the points
FeatureCollection size in one synchronous call. Points are therefore chunked per tile
well under that limit (CHUNK_SIZE below) and the results concatenated, the same
pattern gee_landslide_factors.py already uses for its own request batching.

250m point spacing was chosen deliberately, not just for speed: several of
the conditioning factors (soil properties ~250m, lithology ~1km) are already
coarser than 250m at the source, so nothing real is lost there; terrain
factors (slope, curvature, TWI, ...) do have genuine finer structure that
this smooths over, and the model's own spatial cross-validation only ever
validated generalization at 0.5 deg (~55 km) spatial-block granularity (see
notebooks/landslide_susceptibility_modeling.ipynb), so 250m is not a
meaningful loss relative to what has been validated. Points sit on a
perfectly regular grid, so this reshapes losslessly into a raster later for
display/GIS overlay -- "points vs. raster" is an implementation choice here,
not a resolution choice.

Run (dry run, no sampling): python scripts/gee_sample_factor_grid_points.py --dry-run
Run (actual sampling):      python scripts/gee_sample_factor_grid_points.py
"""

import argparse
import csv
from pathlib import Path
import socket
import time

import ee
import shapely
from shapely.geometry import Point

import gee_export_factor_grid_local as g
import gee_landslide_factors as factors

# Same fix as gee_export_factor_grid_local.py: no built-in request timeout
# means a stalled connection can hang getInfo() forever otherwise.
socket.setdefaulttimeout(120)

PROJECT_DIR = factors.PROJECT_DIR
OUTPUT_DIR = PROJECT_DIR / "data" / "processed" / "factor_grid_points"
POINT_SPACING_M = 250
# Empirically safe margin under the ~5000-element reduceRegions cap (tested
# up to 13,225 points/tile in chunks of 3000 with no failures).
CHUNK_SIZE = 3000
CHUNK_RETRY_ATTEMPTS = 4
CHUNK_RETRY_BACKOFF_SECONDS = 5


def make_points(boundary_polygon, lon0, lat0, lon1, lat1, spacing_m):
    import math
    mid_lat = (lat0 + lat1) / 2
    lat_step = spacing_m / 110_574
    lon_step = spacing_m / (111_320 * max(math.cos(math.radians(mid_lat)), 0.1))
    pts = []
    lat = lat0 + lat_step / 2
    while lat < lat1:
        lon = lon0 + lon_step / 2
        while lon < lon1:
            if boundary_polygon.contains(Point(lon, lat)):
                pts.append((lon, lat))
            lon += lon_step
        lat += lat_step
    return pts


def sample_chunk(stack, chunk, scale, crs):
    """One reduceRegions call + retry, mirroring download_request()'s
    deterministic-vs-transient split in gee_export_factor_grid_local.py."""
    features = [ee.Feature(ee.Geometry.Point([lon, lat]), {"px_lon": lon, "px_lat": lat})
                for lon, lat in chunk]
    fc = ee.FeatureCollection(features)
    last_exc = None
    for attempt in range(1, CHUNK_RETRY_ATTEMPTS + 1):
        try:
            sampled = stack.reduceRegions(collection=fc, reducer=ee.Reducer.first(),
                                          scale=scale, crs=crs, tileScale=4)
            return sampled.getInfo()["features"]
        except ee.EEException as exc:
            last_exc = exc
            if "accumulating over" in str(exc):
                # Deterministic for this chunk size -- caller should shrink CHUNK_SIZE,
                # not retry identically.
                raise
            if attempt < CHUNK_RETRY_ATTEMPTS:
                time.sleep(CHUNK_RETRY_BACKOFF_SECONDS * attempt)
    raise last_exc


def sample_tile(boundary_polygon, tile, day, out_path):
    row, col, lon0, lat0, lon1, lat1 = tile
    pts = make_points(boundary_polygon, lon0, lat0, lon1, lat1, POINT_SPACING_M)
    if not pts:
        return "no_points"

    region = ee.Geometry.Rectangle([lon0, lat0, lon1, lat1], geodesic=False)
    layers = {**g.build_static_layers(region, day), **g.build_temporal_layers(region, day)}
    bands = [factors.prepare_export_band(name, image) for name, image in layers.items()]
    stack = ee.Image.cat(bands)
    band_names = list(layers.keys())

    all_props = []
    for i in range(0, len(pts), CHUNK_SIZE):
        chunk = pts[i:i + CHUNK_SIZE]
        features = sample_chunk(stack, chunk, factors.EXPORT_SCALE, factors.EXPORT_CRS)
        all_props.extend(f["properties"] for f in features)

    fieldnames = ["px_lon", "px_lat"] + band_names
    partial = out_path.with_suffix(".csv.part")
    with partial.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for props in all_props:
            writer.writerow({name: props.get(name) for name in fieldnames})
    partial.replace(out_path)
    return f"ok ({len(all_props)} points)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report tile/point counts and estimated time; sample nothing.")
    args = parser.parse_args()

    boundary_polygon = g.load_boundary_polygon()
    shapely.prepare(boundary_polygon)  # repeated .contains() below is much faster prepared
    tiles = g.tile_grid(boundary_polygon)
    day = g.reference_date_string()
    print(f"Reference date: {day}")
    print(f"Tile size: ~{g.TILE_SIZE_M/1000:.1f} km; tiles intersecting the study area: {len(tiles)}")
    print(f"Point spacing: {POINT_SPACING_M} m; chunk size: {CHUNK_SIZE}")

    if args.dry_run:
        total_points = sum(len(make_points(boundary_polygon, *t[2:], POINT_SPACING_M)) for t in tiles)
        print(f"Estimated total points: {total_points:,}")
        print("(No GEE calls made in --dry-run; point counts are computed locally.)")
        return

    factors.initialize_gee(factors.project_path(factors.SERVICE_ACCOUNT_KEY), factors.GEE_PROJECT)

    out_dir = OUTPUT_DIR / f"factor_grid_points_{day}"
    out_dir.mkdir(parents=True, exist_ok=True)

    ok = skipped = errors = 0
    for index, tile in enumerate(tiles):
        row, col = tile[0], tile[1]
        out_path = out_dir / f"tile_r{row:03d}_c{col:03d}.csv"
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"[{index+1}/{len(tiles)}] tile r{row}c{col}: skipped_existing", flush=True)
            skipped += 1
            continue
        t0 = time.time()
        try:
            status = sample_tile(boundary_polygon, tile, day, out_path)
            ok += 1
        except Exception as exc:
            status = f"ERROR: {exc!r}"
            errors += 1
        print(f"[{index+1}/{len(tiles)}] tile r{row}c{col}: {status} ({time.time()-t0:.0f}s)", flush=True)

    print(f"\nDone: {ok} sampled, {skipped} already present, {errors} errors, out of {len(tiles)} tiles.")
    print(f"Saved to {out_dir}")
    if errors:
        print("Re-run the same command to retry only the missing tiles (existing ones are skipped).")


if __name__ == "__main__":
    main()
