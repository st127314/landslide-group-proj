"""Step 3: negative-sampling designs on the 250 m grid (environment-matched negatives, E4 extension, and the
negative-distance sensitivity analysis).

Earth Engine is not available for new point extractions, so every design draws its negatives from the 250 m
factor grid, and every landslide takes the factors of its own grid cell. Both classes therefore come from the
same layers, sources and 250 m support, and differ only in how negatives are chosen. Only date-independent
factors are used (STATIC: terrain, hydrology, soil, lithology, distances; no NDVI or land cover, which the grid
holds for 2026, not for each event date).

Designs (one negative per landslide; every negative at least 2 km from all 23,284 landslide records):
  random        anywhere in the study area
  ring_2_10     2-10 km from its landslide, same province (the current paired design)
  ring_2_5, ring_5_10, ring_10_20   sensitivity to the negative distance
  matched       same province and the same slope band (5 degrees) and elevation band (landslide deciles)

Each design is scored with the fixed logistic-regression and SVM settings on the same kind of buffered spatial
folds: ROC-AUC (depends on the negatives) and decision value (share of validation landslides in the top 20% of
the validation blocks' grid cells, which does not), so the designs can be compared on what matters for the map.

Input:  data/processed/final/landslide_event_factors_thinned.csv, the factor grid, osm_distances_grid.csv.gz
Output: data/processed/final/grid_design_<name>.csv, data/processed/final/grid_province.csv.gz,
        results/final/03_negative_designs.json
"""
import time

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.metrics import roc_auc_score

from common import (FINAL_DATA, GRID_PROVINCE, RESULTS, ROOT, RS, STATIC, Spatial, fixed_model, km_xy, load_grid,
                    score, write_json)

t0 = time.time()
rng = np.random.default_rng(RS)
MIN_KM = 2.0
DV_CELLS = 150_000   # decision-value cells per fold (random subset; quantiles are stable at this size)

# ---- grid with static factors and province
raw = {'tri': 'TRI', 'tpi': 'TPI', 'ls_factor': 'LS_factor', 'twi': 'TWI', 'spi': 'SPI'}
grid = load_grid(usecols=['px_lon', 'px_lat'] + [raw.get(c, c) for c in STATIC])
if GRID_PROVINCE.exists():
    grid['province'] = pd.read_csv(GRID_PROVINCE).province.to_numpy()
else:
    prov = gpd.read_file(ROOT / 'data/boundary/southern_thailand_tambons.geojson')[['NAME_1', 'geometry']].dissolve('NAME_1').reset_index()
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(grid.px_lon, grid.px_lat), crs=4326)
    j = gpd.sjoin_nearest(pts, prov.to_crs(4326), how='left').groupby(level=0).NAME_1.first()
    grid['province'] = j.reindex(range(len(grid))).to_numpy()
    grid[['province']].to_csv(GRID_PROVINCE, index=False)
lat0 = grid.px_lat.mean()
gxy = km_xy(grid.px_lon, grid.px_lat, lat0)
print('grid', len(grid), round(time.time() - t0), flush=True)

# ---- candidate pool: cells at least 2 km from every recorded landslide
rec = gpd.read_file(ROOT / 'data/inventory/landslide_records_all.geojson')
rxy = km_xy(rec.geometry.x, rec.geometry.y, lat0)
d_rec = cKDTree(rxy).query(gxy, k=1)[0]
pool = np.where(d_rec >= MIN_KM)[0]
print('pool', len(pool), round(time.time() - t0), flush=True)

# ---- landslides take the factors of their own grid cell
t = pd.read_csv(FINAL_DATA / 'landslide_event_factors_thinned.csv')
ls = t[t.landslide == 1].reset_index(drop=True)
lxy = km_xy(ls.longitude, ls.latitude, lat0)
dist, cell = cKDTree(gxy).query(lxy, k=1)
inside = dist <= 0.2
ls_cells = cell[inside]
print('landslides on the grid', int(inside.sum()), 'of', len(ls), flush=True)

pool_tree = cKDTree(gxy[pool])
slope_band = np.floor(grid.slope.to_numpy() / 5)
elev_edges = np.unique(np.quantile(grid.elevation.to_numpy()[ls_cells], np.linspace(0, 1, 11)))
elev_band = np.digitize(grid.elevation.to_numpy(), elev_edges[1:-1])
province = grid.province.to_numpy()


def sample_ring(lo, hi, same_province=True):
    used, out = set(), []
    for c in ls_cells:
        idx = pool[pool_tree.query_ball_point(gxy[c], hi)]
        if len(idx):
            dd = np.hypot(*(gxy[idx] - gxy[c]).T)
            idx = idx[(dd >= lo)]
            if same_province:
                idx = idx[province[idx] == province[c]]
            idx = np.array([i for i in idx if i not in used])
        if len(idx):
            pick = int(rng.choice(idx)); used.add(pick); out.append(pick)
    return np.array(out)


def sample_random():
    return rng.choice(pool, size=len(ls_cells), replace=False)


def sample_matched():
    key = pd.Series(list(zip(province[pool], slope_band[pool], elev_band[pool])))
    buckets = {k: list(rng.permutation(pool[v.to_numpy()])) for k, v in key.groupby(key).groups.items()}
    out, relaxed = [], 0
    for c in ls_cells:
        k = (province[c], slope_band[c], elev_band[c])
        if not buckets.get(k):   # relax: same slope and elevation band in any province
            relaxed += 1
            ks = [kk for kk in buckets if kk[1:] == k[1:] and buckets[kk]]
            if not ks:           # relax further: nearest slope band, same elevation band
                ks = sorted([kk for kk in buckets if kk[2] == k[2] and buckets[kk]], key=lambda kk: abs(kk[1] - k[1]))[:1]
            if not ks:
                continue
            k = ks[0]
        out.append(buckets[k].pop())
    return np.array(out), relaxed


designs, info = {}, {}
designs['random'] = sample_random()
for lo, hi in [(2, 10), (2, 5), (5, 10), (10, 20)]:
    designs[f'ring_{lo}_{hi}'] = sample_ring(lo, hi)
designs['matched'], info['matched_relaxed'] = sample_matched()
print('sampled', {k: len(v) for k, v in designs.items()}, round(time.time() - t0), flush=True)

cell_feats = grid[STATIC]
R = {'n_landslides': int(len(ls_cells)), 'pool_cells': int(len(pool)), 'features': STATIC, **info, 'designs': {}}
for name, neg in designs.items():
    rows = pd.concat([grid.iloc[ls_cells].assign(landslide=1), grid.iloc[neg].assign(landslide=0)], ignore_index=True)
    rows = rows.rename(columns={'px_lon': 'longitude', 'px_lat': 'latitude'})
    rows.to_csv(FINAL_DATA / f'grid_design_{name}.csv', index=False)
    S = Spatial(rows)
    res = {'n': int(len(rows)), 'negatives_median_elevation': float(rows.loc[rows.landslide == 0, 'elevation'].median()),
           'negatives_median_slope': float(rows.loc[rows.landslide == 0, 'slope'].median()),
           'landslides_median_elevation': float(rows.loc[rows.landslide == 1, 'elevation'].median()),
           'landslides_median_slope': float(rows.loc[rows.landslide == 1, 'slope'].median())}
    for m in ['lr', 'svm']:
        aucs, dvs = [], []
        for tr, va in S.outer:
            p = fixed_model(m, STATIC).fit(rows.iloc[tr][STATIC], S.y[tr])
            aucs.append(roc_auc_score(S.y[va], score(p, rows.iloc[va][STATIC])))
            cells = np.where(grid.block.isin(set(S.groups[va])).to_numpy())[0]
            if len(cells) > DV_CELLS:
                cells = np.random.default_rng(RS).choice(cells, DV_CELLS, replace=False)
            va_ls = va[S.y[va] == 1]
            c, q = score(p, cell_feats.iloc[cells]), score(p, rows.iloc[va_ls][STATIC])
            dvs.append(float((q >= np.quantile(c, 0.8)).mean()))
        res[m] = {'auc_folds': [round(a, 4) for a in aucs], 'auc_mean': round(float(np.mean(aucs)), 4),
                  'top20_folds': [round(v, 4) for v in dvs], 'top20_mean': round(float(np.mean(dvs)), 4),
                  'top20_sd': round(float(np.std(dvs, ddof=1)), 4)}
    R['designs'][name] = res
    print(name, {m: (res[m]['auc_mean'], res[m]['top20_mean']) for m in ['lr', 'svm']},
          'neg elev', res['negatives_median_elevation'], round(time.time() - t0), flush=True)
write_json(RESULTS / '03_negative_designs.json', R)
print('done', round(time.time() - t0))
