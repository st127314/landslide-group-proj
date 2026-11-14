"""Follow-up experiments F0-F5, run after the progress report to close its open questions.

F0  Permutation importance of the selected model on the held-out fold (drop in ROC-AUC when one factor is shuffled).
F1  Near-duplicate thinning. Landslide points closer than 30 m to an earlier one (and their paired negatives) are
    removed and the model comparison is repeated, to see how much double-counted scars flatter the scores.
F2  Decision value on the map, by factor set. Each held-out landslide is represented by the 250 m grid cell it falls
    in and ranked among all cells of the held-out area, which is how a user meets the map. The factor sets remove, in
    turn, the groups whose grid values do not match the training values: hydrology (500 m source in training, 90 m
    on the grid) and the road and river distances (F5). "with_ndvi" is the earlier 20-factor model, kept for
    comparison. The script also records how far the grid's NDVI, hydrology and distance values sit from the training
    values.
F3  Environment-matched negatives on the 250 m grid. The paired negatives are lowland points, so part of the score is
    a hillslope-versus-lowland contrast. Here both classes are grid cells, described by the same static factors from
    the same sources (no NDVI or land cover, which postdate the events on the grid):
      positives   the grid cell nearest each landslide (within 180 m), one row per cell;
      ring        one negative per positive: a random cell 2-10 km away in the same province (the current design);
      matched     one negative per positive: the cell in the same province with the closest slope and elevation
                  (within 5 degrees and 100 m), used once.
    All negatives lie at least 2 km from every one of the 23,284 landslide records. Besides cross-validating each
    design, a model trained on the ring design is tested on the matched negatives, which asks the practical question:
    does a map trained against easy negatives still rank landslide cells above comparable slopes?
F4  The three points of the team's final review (docs/METHODS.md, Known issues 7 and 14):
      NDVI          how well NDVI alone separates the classes, overall and on slopes above 20 degrees; the event date
                    is an image date, so the 90-day NDVI window already contains the scar;
      indicators    cross-validation with the missing-value indicators switched off (missing soil values are more
                    common among negatives, so an indicator could encode the sampling);
      interval      the held-out ROC-AUC interval from resampling points, and from resampling 0.1 degree sub-blocks
                    of the held-out fold. The fold has only three 0.5 degree blocks, so neither interval replaces
                    the spread across the outer folds of the nested cross-validation.
F5  Road and river distances on the 250 m grid. Most tiles have no value at all, and where there is one it does not
    agree with the training table at the same place.

Same folds, buffer and fixed hyperparameters as run_experiments.py. Run from the project root (a few minutes):
    python notebooks/experiments/run_followup_experiments.py
Needs data/processed/factor_grid_points/ (F2, F3, F5) and geopandas (F3).
Output: results/experiments/followup.json
"""
import json, sys, time
from pathlib import Path
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, OUT, FACTOR_GRID, RS, BLOCK, BUF, GROUPS, ALL_FEATS, WITH_NDVI, load, model, score, Setup

NEAR_DUPLICATE_M = 30.0
CELL_MATCH_M = 180.0        # just over half the diagonal of a 250 m cell
SUB_BLOCK = 0.1             # degrees; sub-blocks of the held-out fold resampled for the F4 interval
SELECTED = 'lrfs'           # logistic regression with feature selection, chosen by the nested search
EXCLUSION_KM = 2.0          # negatives keep this distance from every landslide record
RING_KM = (2.0, 10.0)
CALIPER = {'slope': 5.0, 'elevation': 100.0}
STATIC_GROUPS = ['terrain', 'hydrology', 'soil', 'lithology', 'distances']
STATIC_FEATS = sum((GROUPS[g] for g in STATIC_GROUPS), [])
GRID_RENAME = {'TRI': 'tri', 'TPI': 'tpi', 'LS_factor': 'ls_factor', 'TWI': 'twi', 'SPI': 'spi', 'NDVI': 'ndvi', 'LULC_current': 'lulc'}

R = {}
t0 = time.time()
rng = np.random.default_rng(RS)
d = load(ROOT / 'data/processed/landslide_event_factors_cleaned.csv')
S = Setup(d)


def km_xy(lon, lat, lat0):
    return np.column_stack((np.asarray(lon) * 111.32 * np.cos(np.deg2rad(lat0)), np.asarray(lat) * 111.32))


def holdout_auc(setup, name, feats):
    p = model(name, feats).fit(setup.d.iloc[setup.train][feats], setup.y[setup.train])
    return round(float(roc_auc_score(setup.y[setup.test], score(p, setup.d.iloc[setup.test][feats]))), 4), p


# ---- F0 permutation importance on the held-out fold
selected = model(SELECTED, ALL_FEATS).fit(d.iloc[S.train][ALL_FEATS], S.y[S.train])
imp = permutation_importance(selected, d.iloc[S.test][ALL_FEATS], S.y[S.test], scoring='roc_auc', n_repeats=10, random_state=RS, n_jobs=-1)
R['F0'] = {f: {'mean': round(float(m), 4), 'sd': round(float(sd), 4)}
           for f, m, sd in sorted(zip(ALL_FEATS, imp.importances_mean, imp.importances_std), key=lambda r: -r[1])}
# The inputs the selection step keeps (numeric factors, aspect as sine and cosine, one column per category).
columns = selected.named_steps['prep'].named_steps['columns']
kept = selected.named_steps['select'].get_support()
R['selected_inputs'] = {'candidates': int(len(kept)), 'kept': [n.split('__', 1)[1] for n, k in zip(columns.get_feature_names_out(), kept) if k]}
print('F0', list(R['F0'].items())[:5], R['selected_inputs'], round(time.time() - t0), flush=True)

# ---- F1 near-duplicate thinning
pairs = {f['properties']['Event_ID']: f"LS_{f['properties']['paired_landslide_id']}"
         for f in json.loads((ROOT / 'data/inventory/non_landslide_events.geojson').read_text())['features']}
ls = d[d.landslide == 1]
xy = km_xy(ls.longitude, ls.latitude, d.latitude.mean())
tree = cKDTree(xy)
drop = set()
for i, j in sorted(tree.query_pairs(NEAR_DUPLICATE_M / 1000.0)):
    if ls.id.iloc[i] not in drop:
        drop.add(ls.id.iloc[j])          # keep the earlier row of each close pair
keep = ~(d.id.isin(drop) | d.id.map(pairs).isin(drop))
d_thin = d[keep].reset_index(drop=True)
S_thin = Setup(d_thin)
R['F1'] = {'near_duplicate_m': NEAR_DUPLICATE_M, 'close_pairs': int(len(tree.query_pairs(NEAR_DUPLICATE_M / 1000.0))),
           'landslides_removed': int(len(drop)), 'rows_before': int(len(d)), 'rows_after': int(len(d_thin)),
           'holdout_rows': {'before': int(len(S.test)), 'after': int(len(S_thin.test))}}
for m in ['lr', 'lrfs', 'svm', 'rf']:
    R['F1'][m] = {'all_points': {**S.cv(lambda m=m: model(m, ALL_FEATS), ALL_FEATS), 'holdout_auc': holdout_auc(S, m, ALL_FEATS)[0]},
                  'thinned': {**S_thin.cv(lambda m=m: model(m, ALL_FEATS), ALL_FEATS), 'holdout_auc': holdout_auc(S_thin, m, ALL_FEATS)[0]}}
print('F1', {m: (R['F1'][m]['all_points']['auc_mean'], R['F1'][m]['thinned']['auc_mean']) for m in ['lr', 'lrfs', 'svm', 'rf']}, round(time.time() - t0), flush=True)

# ---- the 250 m factor grid (F2 decision value, F3)
grid_dirs = sorted(FACTOR_GRID.glob('factor_grid_points_*')) if FACTOR_GRID.exists() else []
if not grid_dirs:
    sys.exit('The 250 m factor grid is needed for F2 and F3 (data/processed/factor_grid_points/).')
lith = {c['value']: c['name'] for c in json.loads((ROOT / 'scripts/glim_lithology_classes.json').read_text())['classes']}
lulc = {c['value']: c['name'] for c in json.loads((ROOT / 'scripts/servir_landcover_classes.json').read_text())['classes']}
grid = pd.concat([pd.read_csv(f).assign(tile=f.stem) for f in sorted(grid_dirs[-1].glob('tile_*.csv'))], ignore_index=True).rename(columns=GRID_RENAME)
grid['lithology'] = grid['lithology'].map(lith)     # the grid stores class codes; the models were trained on class names
grid['lulc'] = grid['lulc'].map(lulc)
grid['block'] = np.floor(grid.px_lon / BLOCK).astype(int).astype(str) + '_' + np.floor(grid.px_lat / BLOCK).astype(int).astype(str)
print('grid', len(grid), round(time.time() - t0), flush=True)

# ---- F2 decision value on the held-out blocks of the grid, by factor set
no_hydro = [c for c in ALL_FEATS if c not in GROUPS['hydrology']]
no_dist = [c for c in ALL_FEATS if c not in GROUPS['distances']]
no_hydro_dist = [c for c in no_hydro if c not in GROUPS['distances']]
FACTOR_SETS = [('all_factors', ALL_FEATS), ('with_ndvi', WITH_NDVI), ('without_hydrology', no_hydro), ('without_distances', no_dist),
               ('without_hydrology_distances', no_hydro_dist), ('terrain_only', GROUPS['terrain'])]
quartiles = lambda v: [round(float(x), 3) for x in np.nanquantile(v, [0.25, 0.5, 0.75])]
held = grid[grid.block.isin(set(S.groups[S.test]))].reset_index(drop=True)
test_ls = S.test[S.y[S.test] == 1]
# Two ways to place a held-out landslide in the ranking of held-out cells:
#   point  its own factor values from the training table (as in run_experiments.py);
#   cell   the grid cell it falls in, i.e. the map a user would actually look at. Only this one compares like with like:
#          the training table and the grid take hydrology and the distances from different sources.
lat_h = held.px_lat.mean()
cell_dist, cell_of = cKDTree(km_xy(held.px_lon, held.px_lat, lat_h)).query(km_xy(d.longitude.iloc[test_ls], d.latitude.iloc[test_ls], lat_h), k=1)
on_grid = cell_dist <= CELL_MATCH_M / 1000.0
R['F2'] = {'n_cells_heldout_area': int(len(held)), 'n_heldout_landslides': int(len(test_ls)),
           'n_heldout_landslides_on_grid': int(on_grid.sum()),
           'quartiles_training_vs_grid': {c: {'training': quartiles(d[c]), 'grid': quartiles(grid[c])}
                                          for c in ['ndvi'] + GROUPS['hydrology'] + GROUPS['distances']},
           'ndvi_below_0.6': {'training': round(float((d.ndvi < 0.6).mean()), 3), 'grid': round(float((grid.ndvi < 0.6).mean()), 3)}}
for m in ['lr', 'lrfs', 'svm']:
    row = {}
    for label, feats in FACTOR_SETS:
        if m == 'lrfs' and label not in ('all_factors', 'with_ndvi'):
            continue        # the selection step keeps a fixed number of inputs, tuned on the full factor set
        auc, p = holdout_auc(S, m, feats)
        cells, pts = score(p, held[feats]), score(p, d.iloc[test_ls][feats])
        own = cells[cell_of[on_grid]]
        row[label] = {'cv': S.cv(lambda m=m, f=feats: model(m, f), feats), 'holdout_auc': auc,
                      'top20': round(float((pts >= np.quantile(cells, 0.8)).mean()), 5),
                      'top10': round(float((pts >= np.quantile(cells, 0.9)).mean()), 5),
                      'cell_top20': round(float((own >= np.quantile(cells, 0.8)).mean()), 5),
                      'cell_top10': round(float((own >= np.quantile(cells, 0.9)).mean()), 5)}
    R['F2'][m] = row
R['F2']['selected'] = SELECTED
print('F2', {m: {k: (v['holdout_auc'], v['top20'], v['cell_top20']) for k, v in R['F2'][m].items()} for m in R['F2'] if m in ('lr', 'lrfs', 'svm')}, round(time.time() - t0), flush=True)

# ---- F4 the three points of the final review: NDVI leak, missing-value indicators, the held-out interval
yv, has_ndvi, steep = S.y, d.ndvi.notna().to_numpy(), (d.slope > 20).to_numpy()
missing = lambda c: {'landslides': round(float(d.loc[d.landslide == 1, c].isna().mean()), 4), 'negatives': round(float(d.loc[d.landslide == 0, c].isna().mean()), 4)}
R['F4'] = {'ndvi': {'median': {'landslides': round(float(d.ndvi[yv == 1].median()), 3), 'negatives': round(float(d.ndvi[yv == 0].median()), 3)},
                    'auc_alone_all': round(float(roc_auc_score(yv[has_ndvi], -d.ndvi[has_ndvi])), 4),
                    'auc_alone_slope_above_20': round(float(roc_auc_score(yv[has_ndvi & steep], -d.ndvi[has_ndvi & steep])), 4),
                    'n_slope_above_20': int((has_ndvi & steep).sum()),
                    'distinct_landslide_dates': int(pd.to_datetime(d.event_date[yv == 1]).nunique())},
           'indicators': {'missing_share': {c: missing(c) for c in ['soil_clay_pct', 'lithology', 'slope']}}}
# In the linear pipelines the indicators pass through the outlier clipping, which sets a column that is almost always
# zero to a constant, so they cannot carry information to the model. Recorded here because it explains the result.
numeric = columns.named_transformers_['num']
n_ind = len(numeric.named_steps['imputer'].indicator_.features_)
with_aspect = selected.named_steps['prep'].named_steps['aspect'].transform(d.iloc[S.train][ALL_FEATS])
after = numeric.transform(with_aspect[columns.transformers_[0][2]])[:, -n_ind:]
R['F4']['indicators']['indicator_columns'] = int(n_ind)
R['F4']['indicators']['constant_after_clipping'] = bool((after.std(axis=0) == 0).all())
for m in ['lr', 'lrfs', 'svm']:
    off = model(m, ALL_FEATS, indicators=False).fit(d.iloc[S.train][ALL_FEATS], S.y[S.train])
    R['F4']['indicators'][m] = {'with': {**R['F2'][m]['all_factors']['cv'], 'holdout_auc': R['F2'][m]['all_factors']['holdout_auc']},
                                'without': {**S.cv(lambda m=m: model(m, ALL_FEATS, indicators=False), ALL_FEATS),
                                            'holdout_auc': round(float(roc_auc_score(S.y[S.test], score(off, d.iloc[S.test][ALL_FEATS]))), 4)}}
# The interval: resample points (what the notebook reports), then resample 0.1 degree sub-blocks of the held-out fold.
te_scores, te_y = score(selected, d.iloc[S.test][ALL_FEATS]), S.y[S.test]
sub = (np.floor(d.longitude.iloc[S.test] / SUB_BLOCK).astype(int).astype(str) + '_' + np.floor(d.latitude.iloc[S.test] / SUB_BLOCK).astype(int).astype(str)).to_numpy()
members = [np.nonzero(sub == b)[0] for b in np.unique(sub)]
boot = np.random.default_rng(RS)
def interval(draw, n=2000):
    aucs = []
    while len(aucs) < n:
        idx = draw()
        if 0 < te_y[idx].mean() < 1:
            aucs.append(roc_auc_score(te_y[idx], te_scores[idx]))
    return [round(float(v), 4) for v in np.quantile(aucs, [0.025, 0.975])]
R['F4']['interval'] = {'model': SELECTED, 'holdout_auc': round(float(roc_auc_score(te_y, te_scores)), 4),
                       'blocks_in_holdout': int(len(set(S.groups[S.test]))),
                       'points_per_block': sorted((int(v) for v in pd.Series(S.groups[S.test]).value_counts()), reverse=True),
                       'landslides_per_block': sorted((int(te_y[S.groups[S.test] == b].sum()) for b in set(S.groups[S.test])), reverse=True),
                       'point_bootstrap': interval(lambda: boot.integers(0, len(te_y), len(te_y))),
                       'sub_block_deg': SUB_BLOCK, 'sub_blocks': int(len(members)),
                       'sub_block_bootstrap': interval(lambda: np.concatenate([members[k] for k in boot.integers(0, len(members), len(members))])),
                       'nested_cv': R['F2'][SELECTED]['all_factors']['cv']}
print('F4', R['F4']['ndvi'], {m: (v['with']['auc_mean'], v['without']['auc_mean']) for m, v in R['F4']['indicators'].items() if m in ('lr', 'lrfs', 'svm')},
      R['F4']['interval'], round(time.time() - t0), flush=True)

# ---- F5 road and river distances on the grid
tiles = grid.groupby('tile')
tr_tree_xy = km_xy(grid.px_lon, grid.px_lat, d.latitude.mean())
near_d, near_i = cKDTree(tr_tree_xy).query(km_xy(d.longitude, d.latitude, d.latitude.mean()), k=1)
R['F5'] = {'tiles': int(tiles.ngroups), 'cells': int(len(grid))}
for c in GROUPS['distances']:
    g = grid[c].to_numpy()[near_i]
    ok = (near_d <= CELL_MATCH_M / 1000.0) & ~np.isnan(g) & d[c].notna().to_numpy()
    R['F5'][c] = {'tiles_without_any_value': int((tiles[c].count() == 0).sum()),
                  'cells_without_value': round(float(grid[c].isna().mean()), 4),
                  'quartiles_m': {'training': quartiles(d[c]), 'grid_where_present': quartiles(grid[c])},
                  'same_place': {'pairs': int(ok.sum()), 'training_median_m': round(float(d[c][ok].median()), 1), 'grid_median_m': round(float(np.median(g[ok])), 1),
                                 'spearman': round(float(pd.Series(d[c].to_numpy()[ok]).corr(pd.Series(g[ok]), method='spearman')), 3)}}
print('F5', R['F5'], round(time.time() - t0), flush=True)

# ---- F3 environment-matched negatives on the grid
import geopandas as gpd

provinces = gpd.read_file(ROOT / 'data/boundary/southern_thailand.geojson')[['NAME_1', 'geometry']]
pts = gpd.GeoDataFrame(grid[['px_lon', 'px_lat']], geometry=gpd.points_from_xy(grid.px_lon, grid.px_lat), crs='EPSG:4326')
joined = gpd.sjoin(pts, provinces, how='left', predicate='within')
grid['province'] = joined[~joined.index.duplicated()]['NAME_1'].reindex(grid.index).to_numpy()
lat0 = grid.px_lat.mean()
gxy = km_xy(grid.px_lon, grid.px_lat, lat0)
gtree = cKDTree(gxy)

records = json.loads((ROOT / 'data/inventory/landslide_records_all.geojson').read_text())['features']
rxy = km_xy([f['geometry']['coordinates'][0] for f in records], [f['geometry']['coordinates'][1] for f in records], lat0)
far = cKDTree(rxy).query(gxy, k=1)[0] >= EXCLUSION_KM
usable = grid[STATIC_FEATS].notna().sum(axis=1).to_numpy() >= len(STATIC_FEATS) - 2    # allow the pipeline to impute a little

dist, cell = gtree.query(km_xy(ls.longitude, ls.latitude, lat0), k=1)
pos_cells = np.unique(cell[(dist <= CELL_MATCH_M / 1000.0)])
pos_cells = pos_cells[usable[pos_cells] & grid.province.notna().to_numpy()[pos_cells]]
eligible = far & usable
eligible[pos_cells] = False

slope, elev, prov = grid.slope.to_numpy(), grid.elevation.to_numpy(), grid.province.to_numpy()
s_sd, e_sd = np.nanstd(slope[pos_cells]), np.nanstd(elev[pos_cells])
ring_neg, match_neg = {}, {}
used_ring, used_match = set(), set()
by_prov = {}
for p in pd.unique(prov[pos_cells]):
    idx = np.nonzero(eligible & (prov == p) & ~np.isnan(slope) & ~np.isnan(elev))[0]
    by_prov[p] = (idx, cKDTree(np.column_stack((slope[idx] / s_sd, elev[idx] / e_sd))))
for c in rng.permutation(pos_cells):
    # ring negative: the paired design, on the grid
    near = np.asarray(gtree.query_ball_point(gxy[c], RING_KM[1]), dtype=int)
    near = near[eligible[near] & (prov[near] == prov[c]) & (np.linalg.norm(gxy[near] - gxy[c], axis=1) >= RING_KM[0])]
    near = [n for n in rng.permutation(near) if n not in used_ring]
    if near:
        ring_neg[c] = near[0]; used_ring.add(near[0])
    # matched negative: closest slope and elevation in the province, within the calipers, used once
    if np.isnan(slope[c]) or np.isnan(elev[c]):
        continue
    idx, tr = by_prov[prov[c]]
    if not len(idx):
        continue
    _, nn = tr.query([slope[c] / s_sd, elev[c] / e_sd], k=min(200, len(idx)))
    for n in idx[np.atleast_1d(nn)]:
        if n not in used_match and abs(slope[n] - slope[c]) <= CALIPER['slope'] and abs(elev[n] - elev[c]) <= CALIPER['elevation']:
            match_neg[c] = n; used_match.add(n); break
both = [c for c in pos_cells if c in ring_neg and c in match_neg]     # same positives in both designs


def design(neg):
    rows = np.concatenate((both, [neg[c] for c in both]))
    out = grid.iloc[rows][['px_lon', 'px_lat'] + STATIC_FEATS].rename(columns={'px_lon': 'longitude', 'px_lat': 'latitude'}).reset_index(drop=True)
    out['landslide'] = np.r_[np.ones(len(both), int), np.zeros(len(both), int)]
    out['pair'] = np.r_[np.arange(len(both)), np.arange(len(both))]
    return out


def medians(dd):
    return {c: [round(float(dd.loc[dd.landslide == 1, c].median()), 1), round(float(dd.loc[dd.landslide == 0, c].median()), 1)] for c in ['slope', 'elevation']}


ring, matched = design(ring_neg), design(match_neg)
S_ring, S_match = Setup(ring), Setup(matched)
R['F3'] = {'landslide_points': int(len(ls)), 'positive_cells': int(len(pos_cells)), 'pairs_in_both_designs': int(len(both)),
           'without_match_in_caliper': int(len(pos_cells) - len([c for c in pos_cells if c in match_neg])),
           'factors': STATIC_FEATS, 'medians_landslide_vs_negative': {'ring': medians(ring), 'matched': medians(matched)},
           'pair_distance_km_median': {'ring': round(float(np.median([np.linalg.norm(gxy[ring_neg[c]] - gxy[c]) for c in both])), 1),
                                       'matched': round(float(np.median([np.linalg.norm(gxy[match_neg[c]] - gxy[c]) for c in both])), 1)},
           'cv': {}, 'ring_model_on_matched_negatives': {}}
for m in ['lr', 'svm', 'rf']:
    R['F3']['cv'][m] = {'ring': S_ring.cv(lambda m=m: model(m, STATIC_FEATS), STATIC_FEATS),
                        'matched': S_match.cv(lambda m=m: model(m, STATIC_FEATS), STATIC_FEATS)}
    # train on the ring design, validate on that fold's landslide cells against their matched negatives
    aucs = []
    mxy = np.column_stack((matched.longitude * 111.32 * np.cos(np.deg2rad(ring.latitude.mean())), matched.latitude * 111.32))   # S_ring's projection
    for tr, va in S_ring.outer:
        p = model(m, STATIC_FEATS).fit(ring.iloc[tr][STATIC_FEATS], S_ring.y[tr])
        va_pairs = ring.pair.to_numpy()[va][S_ring.y[va] == 1]
        pos = matched[(matched.landslide == 1) & matched.pair.isin(va_pairs)]
        neg = matched[(matched.landslide == 0) & matched.pair.isin(va_pairs)]
        clear = cKDTree(S_ring.xy[tr]).query(mxy[neg.index], k=1)[0] >= BUF     # keep the 5 km buffer from training rows
        neg = neg[clear]
        y = np.r_[np.ones(len(pos)), np.zeros(len(neg))]
        aucs.append(roc_auc_score(y, np.r_[score(p, pos[STATIC_FEATS]), score(p, neg[STATIC_FEATS])]))
    R['F3']['ring_model_on_matched_negatives'][m] = {'auc_folds': [round(a, 4) for a in aucs], 'auc_mean': round(float(np.mean(aucs)), 4),
                                                       'auc_sd': round(float(np.std(aucs, ddof=1)), 4)}
R['F3']['terrain_only_lr'] = {'ring': S_ring.cv(lambda: model('lr', GROUPS['terrain']), GROUPS['terrain']),
                              'matched': S_match.cv(lambda: model('lr', GROUPS['terrain']), GROUPS['terrain'])}
print('F3', {m: {k: v['auc_mean'] for k, v in R['F3']['cv'][m].items()} for m in R['F3']['cv']},
      {m: v['auc_mean'] for m, v in R['F3']['ring_model_on_matched_negatives'].items()}, round(time.time() - t0), flush=True)

(OUT / 'followup.json').write_text(json.dumps(R, indent=1))
print('saved', round(time.time() - t0))
