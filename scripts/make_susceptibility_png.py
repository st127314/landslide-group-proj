"""Render the 250 m susceptibility GeoTIFF as one coloured PNG that the web map lays over the basemap.

The map used to draw the grid as up to 8,000 points fetched per viewport, which looked spotty and made the small
server filter 1.14M points on every pan. A single image is drawn by the browser alone and is cached like any static
file. It is warped to Web Mercator first, because MapLibre stretches an image linearly between its corners.

Inputs:  results/susceptibility_map/susceptibility_grid.tif   (from predict_susceptibility_grid.py)
Outputs: results/susceptibility_map/susceptibility_web.png    RGBA, transparent outside the study area
         results/susceptibility_map/susceptibility_web.json   corner coordinates for the MapLibre image source

Run: python scripts/make_susceptibility_png.py   (needs GDAL's Python bindings)
"""

import json
import math
from pathlib import Path

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

PROJECT_DIR = Path(__file__).resolve().parent.parent
MAP_DIR = PROJECT_DIR / "results" / "susceptibility_map"
TIF_PATH = MAP_DIR / "susceptibility_grid.tif"
PNG_PATH = MAP_DIR / "susceptibility_web.png"
BOUNDS_PATH = MAP_DIR / "susceptibility_web.json"

# Same ramp as SCORE_COLOR_STOPS in apps/frontend/components/ImpactMap.tsx, so the legend still matches.
COLOR_STOPS = [(0.0, "#2563eb"), (0.4, "#eab308"), (0.6, "#f97316"), (0.8, "#dc2626"), (1.0, "#7f1d1d")]
EARTH_RADIUS = 6378137.0


def colorize(values):
    """Linear interpolation between the colour stops, per channel; NaN becomes fully transparent."""
    stops = np.array([s for s, _ in COLOR_STOPS])
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for _, c in COLOR_STOPS])
    valid = np.isfinite(values)
    v = np.clip(np.where(valid, values, 0), 0, 1)
    bands = [np.interp(v, stops, rgb[:, i]).astype(np.uint8) for i in range(3)]
    bands.append(np.where(valid, 255, 0).astype(np.uint8))
    return bands


def fill_seams(values):
    """predict_susceptibility_grid.py samples each tile on its own lattice, so tile edges leave 1-cell NaN lines.
    Fill a NaN cell only when both neighbours across it (left/right or above/below) have scores, which closes the
    seams without growing the coastline."""
    out = values.copy()
    for axis in (1, 0):
        before, after = np.roll(values, 1, axis=axis), np.roll(values, -1, axis=axis)
        gap = np.isnan(out) & np.isfinite(before) & np.isfinite(after)
        out[gap] = (before[gap] + after[gap]) / 2
    return out


def mercator_to_lonlat(x, y):
    return math.degrees(x / EARTH_RADIUS), math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2)


def main():
    source = gdal.Open(str(TIF_PATH))
    filled = gdal.GetDriverByName("MEM").CreateCopy("", source)
    filled.GetRasterBand(1).WriteArray(fill_seams(source.GetRasterBand(1).ReadAsArray()))
    source = None

    # Nearest neighbour keeps every cell at its own model score; 250 m cells stay square in Web Mercator here.
    warped = gdal.Warp("/vsimem/susceptibility_3857.tif", filled, dstSRS="EPSG:3857",
                       xRes=250, yRes=250, resampleAlg="near", srcNodata="nan", dstNodata="nan")
    values = warped.GetRasterBand(1).ReadAsArray().astype(np.float32)
    x0, dx, _, y0, _, dy = warped.GetGeoTransform()
    rows, cols = values.shape
    warped = None
    gdal.Unlink("/vsimem/susceptibility_3857.tif")

    mem = gdal.GetDriverByName("MEM").Create("", cols, rows, 4, gdal.GDT_Byte)
    for i, band in enumerate(colorize(values), start=1):
        mem.GetRasterBand(i).WriteArray(band)
    gdal.GetDriverByName("PNG").CreateCopy(str(PNG_PATH), mem, options=["ZLEVEL=9"])
    mem = None
    Path(str(PNG_PATH) + ".aux.xml").unlink(missing_ok=True)

    west, north = mercator_to_lonlat(x0, y0)
    east, south = mercator_to_lonlat(x0 + cols * dx, y0 + rows * dy)
    # MapLibre image-source order: top-left, top-right, bottom-right, bottom-left.
    corners = [[west, north], [east, north], [east, south], [west, south]]
    BOUNDS_PATH.write_text(json.dumps({"coordinates": [[round(c, 6) for c in p] for p in corners],
                                       "width": cols, "height": rows, "cell_m": 250, "source": TIF_PATH.name}))
    print(f"{PNG_PATH.relative_to(PROJECT_DIR)}: {cols} x {rows}, {PNG_PATH.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
