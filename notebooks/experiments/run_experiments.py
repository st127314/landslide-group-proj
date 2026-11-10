"""Supplementary experiments E1-E7, error analysis and partial dependence for the susceptibility model.

Uses the same preprocessing, 0.5 degree spatial blocks, 5 km buffer and hold-out fold as
landslide_susceptibility_modeling.ipynb. Hyperparameters are fixed to the values chosen by the notebook's
nested search, so each experiment changes only the factor under test.

Run from the project root:
    python notebooks/experiments/run_experiments.py

Inputs: data/processed/landslide_event_factors_cleaned.csv; results/experiments/province.csv (province of each
point, from a spatial join with the province boundaries); for E4, the earlier dataset with randomly placed
negatives (data/processed/legacy_random_negatives_factors_cleaned.csv); for the error analysis and calibration,
models/susceptibility/ produced by the notebook; for the held-out decision value, the 250 m factor grid
(data/processed/factor_grid_points/, or set FACTOR_GRID; that step is skipped if the grid is not available).
Outputs: results/experiments/results.json and results/experiments/errors.json.
"""
import json, sys, time
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.inspection import partial_dependence
from sklearn.metrics import roc_auc_score
import joblib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, OUT, V1_TABLE, FACTOR_GRID, RS, BLOCK, GROUPS, ALL_FEATS, load, model, FrequencyRatio, score, Setup

R = {}
t0 = time.time()
d2 = load(ROOT / 'data/processed/landslide_event_factors_cleaned.csv')
S2 = Setup(d2)
R['setup'] = {'n': len(d2), 'holdout_fold': int(S2.fold), 'train': int(len(S2.train)), 'test': int(len(S2.test)), 'outer_fold_sizes': [int(len(v)) for _, v in S2.outer]}
print('setup', R['setup'], flush=True)

# ---- E2: per-fold logistic regression, SVM and random forest with the baseline preprocessing
R['E2'] = {m: S2.cv(lambda m=m: model(m, ALL_FEATS), ALL_FEATS) for m in ['lr', 'svm', 'rf']}
R['E2']['frequency_ratio'] = S2.cv(lambda: FrequencyRatio(ALL_FEATS), ALL_FEATS)
print('E2', {k: v['auc_mean'] for k, v in R['E2'].items()}, round(time.time() - t0), flush=True)

# ---- E1 preprocessing
cfg = {'baseline (median, clip+power, one-hot)': {}, 'k-NN imputation': {'imputer': 'knn'},
       'no clip / power (standardise only)': {'numeric': 'standard'}, 'target encoding': {'cat': 'target'}}
R['E1'] = {m: {k: S2.cv(lambda m=m, kw=kw: model(m, ALL_FEATS, **kw), ALL_FEATS) for k, kw in cfg.items()} for m in ['lr', 'svm']}
print('E1 done', round(time.time() - t0), flush=True)

# ---- E3 ablation: cumulative groups and leave-one-group-out
order = ['terrain', 'hydrology', 'soil', 'lithology', 'land_cover', 'distances', 'ndvi']
R['E3_cumulative'] = {}; R['E3_drop'] = {}
for m in ['lr', 'svm']:
    cum, feats = {}, []
    for g in order:
        feats = feats + GROUPS[g]
        cum['+ ' + g] = S2.cv(lambda m=m, f=list(feats): model(m, f), list(feats))
    R['E3_cumulative'][m] = cum
    R['E3_drop'][m] = {}
    for g in GROUPS:
        f = [c for c in ALL_FEATS if c not in GROUPS[g]]
        R['E3_drop'][m]['without ' + g] = S2.cv(lambda m=m, f=f: model(m, f), f)
    print('E3', m, round(time.time() - t0), flush=True)

# ---- E4 negative sampling: v1 random study-area negatives vs current paired negatives (same pipeline and fold logic)
d1 = load(V1_TABLE)
S1 = Setup(d1)
R['E4'] = {'random (v1)': {m: S1.cv(lambda m=m: model(m, ALL_FEATS), ALL_FEATS) for m in ['lr', 'svm']},
           'paired (current)': {m: R['E2'][m] for m in ['lr', 'svm']},
           'class_medians': {name: {c: [float(dd.loc[dd.landslide == 1, c].median()), float(dd.loc[dd.landslide == 0, c].median())] for c in ['elevation', 'slope', 'ndvi', 'dist_to_road']}
                             for name, dd in [('random (v1)', d1), ('paired (current)', d2)]},
           'n': {'random (v1)': int(len(d1)), 'paired (current)': int(len(d2))}}
# terrain-only comparison isolates how much of the score comes from terrain contrast
R['E4']['terrain_only'] = {name: S.cv(lambda: model('lr', GROUPS['terrain']), GROUPS['terrain']) for name, S in [('random (v1)', S1), ('paired (current)', S2)]}
# which non-terrain groups separate the earlier random negatives more easily than the paired ones
R['E4']['terrain_plus_group'] = {g: {name: S.cv(lambda g=g: model('lr', GROUPS['terrain'] + GROUPS[g]), GROUPS['terrain'] + GROUPS[g])['auc_mean']
                                     for name, S in [('random (v1)', S1), ('paired (current)', S2)]}
                                 for g in ['hydrology', 'soil', 'ndvi', 'land_cover', 'lithology', 'distances']}
print('E4', round(time.time() - t0), flush=True)

# ---- E5 leave-one-province-out (5 km buffer around the held-out province)
prov = pd.read_csv(OUT / 'province.csv').set_index('id').loc[d2.id, 'province'].to_numpy()
R['E5'] = {}
for p in ['Surat Thani', 'Krabi', 'Chumphon', 'Phangnga', 'Phatthalung', 'Trang']:
    te = np.where(prov == p)[0]; tr = S2.buffered(np.where(prov != p)[0], te)
    row = {'n_test': int(len(te)), 'n_train': int(len(tr))}
    for m in ['lr', 'svm']:
        pp = model(m, ALL_FEATS).fit(d2.iloc[tr][ALL_FEATS], S2.y[tr])
        row[m] = round(roc_auc_score(S2.y[te], score(pp, d2.iloc[te][ALL_FEATS])), 4)
    R['E5'][p] = row
print('E5', R['E5'], round(time.time() - t0), flush=True)

# ---- E6 temporal: time-only vs time + 5 km buffer
dates = pd.to_datetime(d2.event_date); cut = dates.quantile(0.8)
early, late = np.where(dates <= cut)[0], np.where(dates > cut)[0]
early_buf = S2.buffered(early, late)
R['E6'] = {'cutoff': str(cut.date()), 'n_test': int(len(late)), 'n_train_time_only': int(len(early)), 'n_train_with_buffer': int(len(early_buf))}
for label, tr in [('time_only', early), ('time_plus_buffer', early_buf)]:
    for m in ['lr', 'svm']:
        pp = model(m, ALL_FEATS).fit(d2.iloc[tr][ALL_FEATS], S2.y[tr])
        R['E6'][f'{label}_{m}'] = round(roc_auc_score(S2.y[late], score(pp, d2.iloc[late][ALL_FEATS])), 4)
print('E6', R['E6'], round(time.time() - t0), flush=True)

# ---- E7 robustness: 5% label noise in training folds (5 seeds)
R['E7'] = {}
for m in ['lr', 'svm']:
    runs = [S2.cv(lambda m=m: model(m, ALL_FEATS), ALL_FEATS, noise=0.05, seed=s)['auc_mean'] for s in range(5)]
    R['E7'][m] = {'clean': R['E2'][m]['auc_mean'], 'noise5_mean': round(float(np.mean(runs)), 4), 'noise5_runs': runs}
print('E7', R['E7'], round(time.time() - t0), flush=True)

# ---- Partial dependence of the final SVM pipeline (shape of top factors)
final = joblib.load(ROOT / 'models/susceptibility/svm_rbf_landslide_susceptibility_pipeline.joblib')
sample = d2.sample(1500, random_state=RS)
feat_cols = final.feature_names_in_ if hasattr(final, 'feature_names_in_') else None
R['PD'] = {}
for f in ['ndvi', 'elevation', 'slope', 'dist_to_river']:
    pdv = partial_dependence(final, sample[list(feat_cols)] if feat_cols is not None else sample, [f], grid_resolution=25, kind='average')
    R['PD'][f] = {'grid': [float(v) for v in pdv['grid_values'][0]], 'avg': [float(v) for v in pdv['average'][0]]}
print('PD done', round(time.time() - t0), flush=True)

(OUT / 'results.json').write_text(json.dumps(R, indent=1))

# ---- Error analysis and decision value on the held-out fold of the selected model
scores = pd.read_csv(ROOT / 'models/susceptibility/landslide_sample_susceptibility_scores.csv')
meta = json.loads((ROOT / 'models/susceptibility/model_metadata.json').read_text())
t = scores[scores.split == 'test'].merge(d2.drop(columns=['event_date', 'longitude', 'latitude', 'landslide']), on='id')
t['province'] = pd.read_csv(OUT / 'province.csv').set_index('id').loc[t.id, 'province'].to_numpy()
t['pred'] = (t.heldout_score >= meta['threshold_raw_probability']).astype(int)
t['slope_band'] = pd.cut(t.slope, [-1, 10, 20, 30, 90], labels=['0-10', '10-20', '20-30', '>30'])
t['elev_band'] = pd.cut(t.elevation, [-1e3, 100, 300, 600, 3000], labels=['<100', '100-300', '300-600', '>600'])
t['road_band'] = pd.cut(t.dist_to_road, [-1, 250, 1000, 1e9], labels=['<250 m', '250-1000 m', '>1 km'])
ERR = {}
for col in ['province', 'slope_band', 'elev_band', 'road_band', 'lithology', 'lulc']:
    rows = []
    for key, g in t.groupby(col, observed=True):
        pos, neg = g[g.landslide == 1], g[g.landslide == 0]
        rows.append({col: str(key), 'n_landslide': int(len(pos)), 'miss_rate': round(float((pos.pred == 0).mean()) if len(pos) else 0.0, 3),
                     'n_neg': int(len(neg)), 'false_alarm_rate': round(float((neg.pred == 1).mean()) if len(neg) else 0.0, 3)})
    ERR[col] = rows
pos = t[t.landslide == 1]
ERR['confusion'] = {'detected': int((pos.pred == 1).sum()), 'missed': int((pos.pred == 0).sum()),
                    'false_alarms': int(((t.landslide == 0) & (t.pred == 1)).sum()), 'correct_negatives': int(((t.landslide == 0) & (t.pred == 0)).sum())}
ERR['ndvi_median'] = {'landslides': float(d2.loc[d2.landslide == 1, 'ndvi'].median()), 'negatives': float(d2.loc[d2.landslide == 0, 'ndvi'].median()),
                      'detected_test_landslides': float(pos.loc[pos.pred == 1, 'ndvi'].median()), 'missed_test_landslides': float(pos.loc[pos.pred == 0, 'ndvi'].median())}

# ---- Calibration slope on the held-out fold (raw Platt scores of the selected model, and after isotonic calibration)
from sklearn.linear_model import LogisticRegression as _LR
calibrator = joblib.load(ROOT / 'models/susceptibility' / f"{meta['best_model']}_isotonic_calibrator.joblib")
def cal_slope(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4); z = np.log(p / (1 - p)).reshape(-1, 1)
    fit = _LR(C=1e6).fit(z, y); return round(float(fit.coef_[0][0]), 3), round(float(fit.intercept_[0]), 3)
ERR['calibration'] = {'raw_slope_intercept': cal_slope(t.heldout_score.to_numpy(), t.landslide.to_numpy()),
                      'isotonic_slope_intercept': cal_slope(calibrator.predict(t.heldout_score.to_numpy()), t.landslide.to_numpy())}

# ---- Decision value on the held-out blocks only, with models trained on the training split
grid_dirs = sorted(FACTOR_GRID.glob('factor_grid_points_*')) if FACTOR_GRID.exists() else []
if grid_dirs:
    lith = {c['value']: c['name'] for c in json.loads((ROOT / 'scripts/glim_lithology_classes.json').read_text())['classes']}
    lulc = {c['value']: c['name'] for c in json.loads((ROOT / 'scripts/servir_landcover_classes.json').read_text())['classes']}
    test_blocks = set(S2.groups[S2.test])
    parts = []
    for f in sorted(grid_dirs[-1].glob('tile_*.csv')):
        g = pd.read_csv(f)
        blocks = np.floor(g.px_lon / BLOCK).astype(int).astype(str) + '_' + np.floor(g.px_lat / BLOCK).astype(int).astype(str)
        g = g[blocks.isin(test_blocks).to_numpy()]
        if len(g):
            parts.append(g)
    grid = pd.concat(parts, ignore_index=True).rename(columns={'TRI': 'tri', 'TPI': 'tpi', 'LS_factor': 'ls_factor', 'TWI': 'twi', 'SPI': 'spi', 'NDVI': 'ndvi', 'LULC_current': 'lulc'})
    grid['lithology'] = grid['lithology'].map(lith)   # grid stores class codes; the model was trained on class names
    grid['lulc'] = grid['lulc'].map(lulc)
    test_ls = S2.test[S2.y[S2.test] == 1]
    dv = {'n_cells_heldout_area': int(len(grid)), 'n_heldout_landslides': int(len(test_ls))}
    for m in ['lr', 'svm']:
        pp = model(m, ALL_FEATS).fit(d2.iloc[S2.train][ALL_FEATS], S2.y[S2.train])
        cells = score(pp, grid[ALL_FEATS]); pts = score(pp, d2.iloc[test_ls][ALL_FEATS])
        dv[m] = {'top20': round(float((pts >= np.quantile(cells, 0.8)).mean()), 4), 'top10': round(float((pts >= np.quantile(cells, 0.9)).mean()), 4)}
    ERR['decision_heldout_blocks'] = dv
    print('decision value (held-out blocks)', dv, flush=True)
print('calibration', ERR['calibration'], flush=True)
(OUT / 'errors.json').write_text(json.dumps(ERR, indent=1))
print('saved', round(time.time() - t0))
