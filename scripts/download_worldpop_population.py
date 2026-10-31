"""Download WorldPop constrained population for Thailand and clip to the
southern Thailand study area. Plain HTTP + local GDAL -- no Earth Engine, so
this never competes with the IMERG/factor-grid jobs for GEE quota.

Run with: python3 scripts/download_worldpop_population.py
Requires the GDAL Python bindings (osgeo).

Source: WorldPop constrained individual countries 2020, UN-adjusted, ~100 m
(Bondarenko et al., WorldPop / School of Geography and Environmental Science,
University of Southampton), CC BY 4.0. "Constrained" means population is
redistributed to built-settlement areas rather than spread evenly per admin
unit, which lines up well with overlaying against OSM building footprints.
"""

import json
from pathlib import Path
import subprocess

import numpy as np
from osgeo import gdal
import requests

gdal.UseExceptions()

PROJECT_DIR = Path(__file__).resolve().parent.parent
AOI_PATH = PROJECT_DIR / "data" / "boundary" / "southern_thailand.geojson"
OUTPUT_DIR = PROJECT_DIR / "data" / "external"
RAW_DIR = OUTPUT_DIR / "raw"
WORLDPOP_URL = ("https://data.worldpop.org/GIS/Population/"
                "Global_2000_2020_Constrained/2020/BSGM/THA/"
                "tha_ppp_2020_UNadj_constrained.tif")
RAW_PATH = RAW_DIR / "tha_ppp_2020_UNadj_constrained.tif"
CLIPPED_PATH = OUTPUT_DIR / "worldpop_2020_UNadj_constrained_aoi.tif"
MANIFEST_PATH = OUTPUT_DIR / "worldpop_manifest.json"


def download(url, path):
    if path.exists():
        print(f"Using cached {path.name}", flush=True)
        return
    partial = path.with_suffix(path.suffix + ".part")
    with requests.get(url, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(1024 ** 2):
                handle.write(chunk)
    partial.replace(path)
    print(f"Downloaded {path.name}", flush=True)


def clip_to_aoi(source_path, aoi_path, out_path):
    """gdalwarp cutline clip; nodata outside the AOI polygon (not just bbox)."""
    subprocess.run([
        "gdalwarp", "-overwrite",
        "-cutline", str(aoi_path), "-crop_to_cutline",
        "-dstnodata", "-99999",
        str(source_path), str(out_path),
    ], check=True)


def raster_stats(path):
    ds = gdal.Open(str(path))
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    array = band.ReadAsArray().astype(np.float64)
    valid = array[array != nodata] if nodata is not None else array
    valid = valid[np.isfinite(valid)]
    gt = ds.GetGeoTransform()
    pixel_area_km2 = abs(gt[1] * gt[5]) * (111_320 ** 2) / 1e6  # approx at the equator; fine for a summary
    stats = {
        "width": ds.RasterXSize, "height": ds.RasterYSize,
        "pixel_size_deg": [gt[1], gt[5]],
        "valid_pixels": int(valid.size),
        "total_population": float(valid.sum()),
        "max_pixel_population": float(valid.max()) if valid.size else None,
        "mean_pixel_population": float(valid.mean()) if valid.size else None,
    }
    ds = None
    return stats


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    download(WORLDPOP_URL, RAW_PATH)
    print("Clipping to study area...", flush=True)
    clip_to_aoi(RAW_PATH, AOI_PATH, CLIPPED_PATH)
    stats = raster_stats(CLIPPED_PATH)
    print(f"Clipped raster: {CLIPPED_PATH}", flush=True)
    print(f"Estimated population in study area: {stats['total_population']:,.0f}", flush=True)
    manifest = {
        "source_url": WORLDPOP_URL,
        "citation": ("WorldPop (School of Geography and Environmental Science, "
                     "University of Southampton); Bondarenko M, Kerr D, Sorichetta A, "
                     "Tatem, AJ. 2020. Census/projection-disaggregated gridded population "
                     "estimates adjusted to match the corresponding UNPD 2020 estimates, "
                     "2020 constrained individual countries 2020 UN adjusted (100m "
                     "resolution). WorldPop, University of Southampton. "
                     "doi:10.5258/SOTON/WP00685"),
        "license": "CC BY 4.0",
        "aoi": str(AOI_PATH.relative_to(PROJECT_DIR)),
        "output": str(CLIPPED_PATH.relative_to(PROJECT_DIR)),
        "stats": stats,
        "limitations": [
            "2020 is the most recent year WorldPop published a constrained "
            "(built-settlement-aware) estimate for Thailand; it predates any "
            "population change since, including COVID-era and post-2020 growth.",
            "Constrained layers redistribute population to mapped built-up "
            "areas, so accuracy depends on the underlying settlement layer's "
            "completeness, not just census totals.",
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved {MANIFEST_PATH}", flush=True)


if __name__ == "__main__":
    main()
