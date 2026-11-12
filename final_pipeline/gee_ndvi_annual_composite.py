"""NDVI annual composite from the calendar year before each event (progress report, remaining work 1).

NOT RUN in the final stage: it needs Earth Engine credentials (scripts/service_account/key.json), which were
not available on the machine used for the final-stage pipeline. Until it is run, the final model drops NDVI
(final_pipeline/04 --data points uses NO_NDVI), which removes the scar leakage at the cost of the vegetation
signal.

Why: the training NDVI is the latest valid observation in the 90 days before each recorded date, and recorded
dates are satellite-image dates on which the scar is already visible, so NDVI partly measures vegetation the
landslide has already removed. A median composite over the whole calendar year before the event year cannot
contain the scar of that event (it may still contain older scars nearby, which is legitimate susceptibility
information).

How: the same Landsat 5/7/8/9 and Sentinel-2 NDVI functions and cloud masks as scripts/gee_landslide_factors.py;
per event year Y, the median of all valid NDVI observations from Y-1-01-01 to Y-1-12-31; points of that year
are sampled at 30 m in chunks. With --grid-year YYYY the composite of that year is also exported to Google
Drive as a GeoTIFF for re-scoring the map.

Run (from the project root, with the key in place):
    python final_pipeline/gee_ndvi_annual_composite.py
    python final_pipeline/gee_ndvi_annual_composite.py --grid-year 2025
Output: data/processed/final/ndvi_annual_prev_year.csv (id, ndvi_annual_prev_year, n_obs)
Then:   merge the column into landslide_event_factors_thinned.csv as `ndvi`, add 'ndvi' back to the feature list
        in common.py (NO_NDVI -> ALL_FEATS) and rerun 04 and 05 (the registry gate in 06 must also stop blocking
        `ndvi` once it is the annual composite).
"""
import argparse
import sys
import time
from pathlib import Path

import ee
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import gee_landslide_factors as factors  # noqa: E402

OUT = ROOT / 'data/processed/final/ndvi_annual_prev_year.csv'
CHUNK = 400


def annual_ndvi(year, region):
    start, end = ee.Date.fromYMD(year, 1, 1), ee.Date.fromYMD(year + 1, 1, 1)
    coll = ee.ImageCollection([])
    for key, red, nir, sensor in [('landsat5', 'SR_B3', 'SR_B4', 5), ('landsat7', 'SR_B3', 'SR_B4', 7),
                                  ('landsat8', 'SR_B4', 'SR_B5', 8), ('landsat9', 'SR_B4', 'SR_B5', 9)]:
        scenes = ee.ImageCollection(factors.GEE_ASSETS[key]).filterBounds(region).filterDate(start, end)
        coll = coll.merge(scenes.map(lambda im, r=red, n=nir, c=sensor: factors.landsat_ndvi(im, r, n, c)))
    s2 = ee.ImageCollection(factors.GEE_ASSETS['sentinel2']).filterBounds(region).filterDate(start, end).map(factors.sentinel2_ndvi)
    ndvi = coll.merge(s2).select('NDVI')
    return ndvi.median().rename('ndvi_annual_prev_year').addBands(ndvi.count().rename('n_obs'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid-year', type=int, default=None)
    args = ap.parse_args()
    factors.initialize_gee(factors.project_path(factors.SERVICE_ACCOUNT_KEY), factors.GEE_PROJECT)
    aoi = factors.geojson_to_feature_collection(factors.project_path(factors.data_path)).geometry()
    pts = pd.read_csv(ROOT / 'data/processed/final/landslide_event_factors_thinned.csv', usecols=['id', 'event_date', 'longitude', 'latitude'])
    pts['year'] = pd.to_datetime(pts.event_date).dt.year
    done = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame(columns=['id'])
    rows = [done]
    for year, g in pts[~pts.id.isin(done.id)].groupby('year'):
        image = annual_ndvi(int(year) - 1, aoi)
        for i in range(0, len(g), CHUNK):
            part = g.iloc[i:i + CHUNK]
            fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([r.longitude, r.latitude]), {'id': r.id}) for r in part.itertuples()])
            for attempt in range(4):
                try:
                    res = image.sampleRegions(collection=fc, scale=30, geometries=False).getInfo()['features']
                    break
                except Exception as exc:   # Earth Engine time-outs: retry with back-off
                    print('retry', year, i, exc); time.sleep(20 * (attempt + 1))
            else:
                raise RuntimeError(f'failed year {year} chunk {i}')
            got = pd.DataFrame([f['properties'] for f in res])
            rows.append(got)
            pd.concat(rows, ignore_index=True).to_csv(OUT, index=False)   # resumable
            print(year, i + len(part), '/', len(g), flush=True)
    if args.grid_year:
        task = ee.batch.Export.image.toDrive(image=annual_ndvi(args.grid_year, aoi).select('ndvi_annual_prev_year').clip(aoi),
                                             description=f'ndvi_annual_{args.grid_year}', region=aoi, scale=250,
                                             crs='EPSG:4326', maxPixels=1e10)
        task.start()
        print('grid export started:', task.status())


if __name__ == '__main__':
    main()
