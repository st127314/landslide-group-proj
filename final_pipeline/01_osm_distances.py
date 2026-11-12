"""Step 1: road and river distances from OpenStreetMap, computed locally.

Why: the Earth Engine grid export left dist_to_road / dist_to_river empty in 119 of 148 tiles (78% of
cells), while no training point lacks them, so the map filled them with the training median. This script also
showed that the grid's existing distance values disagree with the training-table distances, so the final
pipeline replaces the grid distances everywhere (common.load_grid).

How: the same source as the training table (Geofabrik OSM shapefiles: all road classes from
gis_osm_roads_free_1, all waterway classes from gis_osm_waterways_free_1, which is what the
`roads_buffer20km` / `waterways_buffer20km` Earth Engine assets were built from), clipped to the study area
plus 20 km, projected to UTM 47N; the nearest line is found with a shapely STRtree, capped at 20 km like
Earth Engine's searchRadius. Distances are first computed for the 12,360 training points and compared with
the Earth Engine values; the grid is then computed for every cell.

Input:  data/external/osm/thailand-free.shp.zip (https://download.geofabrik.de/asia/thailand-latest-free.shp.zip)
Output: data/processed/final/osm_distances_points.csv, osm_distances_grid.csv.gz,
        results/final/01_osm_distance_check.json
"""
import tempfile
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from common import GRID_DIR, OSM_GRID, OSM_POINTS, PROCESSED, RESULTS, ROOT, UTM, write_json

ZIP = ROOT / 'data/external/osm/thailand-free.shp.zip'
LAYERS = {'dist_to_road': 'gis_osm_roads_free_1', 'dist_to_river': 'gis_osm_waterways_free_1'}
SEARCH_M = 20_000
t0 = time.time()

aoi = gpd.read_file(ROOT / 'data/boundary/southern_thailand.geojson').to_crs(4326)
minx, miny, maxx, maxy = aoi.total_bounds
bbox = (minx - 0.2, miny - 0.2, maxx + 0.2, maxy + 0.2)   # about 20 km around the study area


def read_layer(stem):
    with zipfile.ZipFile(ZIP) as z, tempfile.TemporaryDirectory() as tmp:
        for n in z.namelist():
            if Path(n).stem == stem:
                z.extract(n, tmp)
        return gpd.read_file(Path(tmp) / f'{stem}.shp', bbox=bbox).to_crs(UTM)


trees = {}
for col, stem in LAYERS.items():
    lines = read_layer(stem)
    trees[col] = (shapely.STRtree(lines.geometry.values), lines.geometry.values)
    print(f'{stem}: {len(lines):,} lines', round(time.time() - t0), flush=True)


def distances(lon, lat):
    pts = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(UTM).values
    out = {}
    for col, (tree, geoms) in trees.items():
        d = np.full(len(pts), np.nan)
        idx, dist = tree.query_nearest(pts, max_distance=SEARCH_M, return_distance=True, all_matches=False)
        d[idx[0]] = dist
        out[col] = d
    return out


# ---- training points: validate against the Earth Engine values
t = pd.read_csv(PROCESSED / 'landslide_event_factors_cleaned.csv', usecols=['id', 'longitude', 'latitude', 'landslide', 'dist_to_road', 'dist_to_river'])
local = distances(t.longitude, t.latitude)
pts = t[['id']].copy()
check = {}
for col in LAYERS:
    pts[col] = local[col]
    ee, loc = t[col].to_numpy(), local[col]
    ok = ~np.isnan(ee) & ~np.isnan(loc)
    diff = np.abs(loc[ok] - ee[ok])
    check[col] = {'n': int(ok.sum()), 'spearman': round(float(pd.Series(ee[ok]).corr(pd.Series(loc[ok]), method='spearman')), 4),
                  'median_abs_diff_m': round(float(np.median(diff)), 1), 'p90_abs_diff_m': round(float(np.quantile(diff, 0.9)), 1),
                  'share_within_100m': round(float((diff <= 100).mean()), 4),
                  'median_ee_m': round(float(np.median(ee[ok])), 1), 'median_local_m': round(float(np.median(loc[ok])), 1)}
pts.to_csv(OSM_POINTS, index=False)
print('training-point check', check, round(time.time() - t0), flush=True)

# ---- grid: every cell
parts = []
for f in sorted(GRID_DIR.glob('tile_*.csv')):
    g = pd.read_csv(f, usecols=['px_lon', 'px_lat', 'dist_to_road', 'dist_to_river'])
    loc = distances(g.px_lon, g.px_lat)
    parts.append(pd.DataFrame({'px_lon': g.px_lon, 'px_lat': g.px_lat, 'dist_to_road': loc['dist_to_road'],
                               'dist_to_river': loc['dist_to_river'], 'ee_dist_to_road': g.dist_to_road, 'ee_dist_to_river': g.dist_to_river}))
grid = pd.concat(parts, ignore_index=True)
grid_check = {}
for col in LAYERS:
    ee, loc = grid['ee_' + col].to_numpy(), grid[col].to_numpy()
    ok = ~np.isnan(ee) & ~np.isnan(loc)
    grid_check[col] = {'cells': int(len(grid)), 'ee_missing_share': round(float(np.isnan(ee).mean()), 4),
                       'local_missing_share': round(float(np.isnan(loc).mean()), 4), 'n_compared': int(ok.sum()),
                       'spearman_where_both': round(float(pd.Series(ee[ok]).corr(pd.Series(loc[ok]), method='spearman')), 4),
                       'median_abs_diff_m_where_both': round(float(np.median(np.abs(loc[ok] - ee[ok]))), 1)}
# Same row order as the tiles (sorted), which common.load_grid relies on; distances rounded to 0.1 m.
out = grid[['px_lon', 'px_lat', 'dist_to_road', 'dist_to_river']].copy()
out[['dist_to_road', 'dist_to_river']] = out[['dist_to_road', 'dist_to_river']].round(1)
out.to_csv(OSM_GRID, index=False)
write_json(RESULTS / '01_osm_distance_check.json', {'osm_extract': ZIP.name, 'search_radius_m': SEARCH_M,
                                                     'training_points_vs_earth_engine': check, 'grid': grid_check})
print('grid check', grid_check, 'done', round(time.time() - t0), flush=True)
