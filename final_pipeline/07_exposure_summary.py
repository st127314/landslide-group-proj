"""Step 7: weather-independent impact summary of the final map (terrain tiers and exposure).

scripts/build_impact_overlay.py also needs a live GFS forecast (Earth Engine) and GDAL, neither available for
the final-stage run, so this script recomputes the parts that do not depend on the weather with the same rules:
  * terrain tier per tambon from the share of its 250 m cells that are high or very high (< 15% low,
    15-40% moderate, >= 40% high), as in build_impact_overlay.py;
  * people (WorldPop 2020), OSM buildings and facilities on high / very-high cells, each item taking the class of
    its nearest grid cell within 400 m.
It is compared with the progress-report map (docs/METHODS.md). Run build_impact_overlay.py on the server, where
the forecast is refreshed, to rebuild the live overlay for the app.

Output: results/final/07_exposure_summary.json, 07_tambon_tiers.csv
"""
import json
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from scipy.spatial import cKDTree

from common import RESULTS, ROOT, km_xy, write_json

t0 = time.time()
HIGH = {'high', 'very_high'}
grid = pd.read_csv(ROOT / 'results/susceptibility_map/susceptibility_grid_points.csv')
lat0 = grid.px_lat.mean()
tree = cKDTree(km_xy(grid.px_lon, grid.px_lat, lat0))
cls = grid.susceptibility_class.to_numpy()
tambons = gpd.read_file(ROOT / 'data/boundary/southern_thailand_tambons.geojson').to_crs(4326)


def tambon_of(lon, lat):
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs=4326)
    j = gpd.sjoin(pts, tambons[['GID_3', 'NAME_1', 'geometry']], how='left', predicate='within')
    j = j[~j.index.duplicated()]
    return j.GID_3.to_numpy(), j.NAME_1.to_numpy()


def snap(lon, lat):
    dist, idx = tree.query(km_xy(lon, lat, lat0), k=1)
    out = cls[idx].astype(object)
    out[dist > 0.4] = None
    return out


grid['GID_3'], _ = tambon_of(grid.px_lon, grid.px_lat)
share = grid[grid.GID_3.notna()].groupby('GID_3').susceptibility_class.apply(lambda s: 100 * s.isin(HIGH).mean())
tiers = pd.cut(share, [-0.1, 15, 40, 100.1], labels=['low', 'moderate', 'high'], right=False).astype(str)
print('tiers', round(time.time() - t0), flush=True)

with rasterio.open(ROOT / 'data/external/worldpop_2020_UNadj_constrained_aoi.tif') as src:
    arr = src.read(1).astype('float64')
    nod = src.nodata
    r, c = np.nonzero((arr > 0) & (arr != nod) if nod is not None else (arr > 0))
    lon, lat = rasterio.transform.xy(src.transform, r, c)
pop = pd.DataFrame({'lon': lon, 'lat': lat, 'pop': arr[r, c]})
pop['cls'] = snap(pop.lon, pop.lat)
pop['GID_3'], pop['province'] = tambon_of(pop.lon, pop.lat)
print('population', round(time.time() - t0), flush=True)

bld = gpd.read_file(ROOT / 'data/external/buildings_aoi.geojson', columns=['geometry'])
cen = bld.to_crs('EPSG:32647').geometry.centroid.to_crs(4326)
b_cls = snap(cen.x.to_numpy(), cen.y.to_numpy())
fac = gpd.read_file(ROOT / 'data/external/facilities_aoi.geojson').to_crs(4326)
f_cls = snap(fac.geometry.x.to_numpy(), fac.geometry.y.to_numpy())
print('buildings and facilities', round(time.time() - t0), flush=True)

on_high = pop.cls.isin(HIGH)
by_prov = pop[on_high].groupby('province').pop.sum().sort_values(ascending=False).round(0)
summary = {
    'tambon_tiers': tiers.value_counts().to_dict(), 'tambons_without_cells': int(len(tambons) - len(tiers)),
    'people_on_high_very_high': int(round(pop.loc[on_high, 'pop'].sum())), 'people_total': int(round(pop['pop'].sum())),
    'buildings_on_high_very_high': int(np.isin(b_cls, list(HIGH)).sum()), 'buildings_total': int(len(b_cls)),
    'facilities_on_high_very_high': int(np.isin(f_cls, list(HIGH)).sum()), 'facilities_total': int(len(f_cls)),
    'people_on_high_very_high_by_province_top5': by_prov.head(5).astype(int).to_dict(),
    'progress_report_map_for_comparison': {'tambon_tiers': {'low': 753, 'moderate': 194, 'high': 106},
                                           'people_on_high_very_high': 71402, 'buildings_on_high_very_high': 5983,
                                           'facilities_on_high_very_high': 34},
}
pd.DataFrame({'GID_3': tiers.index, 'pct_cells_high_vh': share.round(2).to_numpy(), 'tier': tiers.to_numpy()}).to_csv(
    RESULTS / '07_tambon_tiers.csv', index=False)
write_json(RESULTS / '07_exposure_summary.json', summary)
print(json.dumps(summary, indent=1), round(time.time() - t0))
