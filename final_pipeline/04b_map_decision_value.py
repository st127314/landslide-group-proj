"""Step 4b: map-based decision value, and the success rule re-checked with it.

04 scores each validation landslide with its own point factors (event-date values from the training table)
against the grid cells. The map, however, shows grid-cell scores, and the grid's factors at the same place can
differ (land cover of 2026 instead of the event year, ALOS/MERIT instead of SRTM/HydroSHEDS for older events).
Here each validation landslide takes the score of its own 250 m grid cell (nearest cell within 200 m), so both
sides of the comparison come from the map itself. Models are the 04 fold models (same folds, same tuned
hyperparameters, refitted deterministically).

Output: results/final/04b_map_decision_value.json
"""
import ast
import json
import time

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy.spatial import cKDTree
from sklearn.base import clone

from common import FINAL_DATA, NO_NDVI, RESULTS, FrequencyRatio, Spatial, candidates, km_xy, load_grid, score, write_json

t0 = time.time()
feats = NO_NDVI
S = Spatial(pd.read_csv(FINAL_DATA / 'landslide_event_factors_thinned.csv'))
grid = load_grid()
lat0 = grid.px_lat.mean()
dist, cell = cKDTree(km_xy(grid.px_lon, grid.px_lat, lat0)).query(km_xy(S.d.longitude, S.d.latitude, lat0), k=1)
folds = pd.read_csv(RESULTS / '04_folds_points.csv')


def restore(k, v):
    if v == 'None':
        return None
    if isinstance(v, float) and v.is_integer() and k.endswith(('depth', 'leaf', 'iter', 'estimators')):
        return int(v)
    return v


def build(name, params):
    if name == 'frequency_ratio':
        return FrequencyRatio(feats)
    return clone(candidates(feats)[name][0]).set_params(**{k: restore(k, v) for k, v in params.items()})


def pscore(m, X, chunk=50_000):
    return np.concatenate(Parallel(n_jobs=-1)(delayed(score)(m, X.iloc[i:i + chunk]) for i in range(0, len(X), chunk)))


rows = []
for name in folds.model.unique():
    for f, (tr, va) in enumerate(S.outer):
        params = ast.literal_eval(folds[(folds.model == name) & (folds.fold == f + 1)].params.iloc[0])
        m = build(name, params).fit(S.d.iloc[tr][feats], S.y[tr])
        in_va = np.where(grid.block.isin(set(S.groups[va])).to_numpy())[0]
        c = pscore(m, grid.iloc[in_va][feats])
        ls = va[(S.y[va] == 1) & (dist[va] <= 0.2)]
        ls_cell_score = pd.Series(c, index=in_va).reindex(cell[ls]).to_numpy()
        ok = ~np.isnan(ls_cell_score)
        rows.append({'model': name, 'fold': f + 1, 'n_landslides': int(ok.sum()),
                     'map_top20': round(float((ls_cell_score[ok] >= np.quantile(c, 0.8)).mean()), 4),
                     'map_top10': round(float((ls_cell_score[ok] >= np.quantile(c, 0.9)).mean()), 4),
                     'point_top20_from_04': float(folds[(folds.model == name) & (folds.fold == f + 1)].top20.iloc[0])})
    print(name, [r['map_top20'] for r in rows if r['model'] == name], round(time.time() - t0), flush=True)
df = pd.DataFrame(rows)
lr = df[df.model == 'logistic_regression'].set_index('fold')
auc = folds.pivot(index='fold', columns='model', values='roc_auc')
rule = {}
for name in [n for n in df.model.unique() if n != 'logistic_regression']:
    c = df[df.model == name].set_index('fold')
    wins = int((c.map_top20 > lr.map_top20).sum())
    gap = float(auc[name].mean() - auc['logistic_regression'].mean())
    rule[name] = {'map_top20_wins_vs_lr': wins, 'mean_map_top20_gain': round(float(c.map_top20.mean() - lr.map_top20.mean()), 4),
                  'folds_meeting_70pct': int((c.map_top20 >= 0.7).sum()), 'passes': bool(wins >= 4 and gap >= -float(auc['logistic_regression'].std()))}
passing = [n for n in rule if rule[n]['passes']]
summary = df.groupby('model')[['map_top20', 'map_top10', 'point_top20_from_04']].mean().round(4)
selected = max(passing, key=lambda n: summary.loc[n, 'map_top20']) if passing else 'logistic_regression'
write_json(RESULTS / '04b_map_decision_value.json', {'folds': rows, 'mean': summary.reset_index().to_dict('records'),
                                                    'success_rule_map_based': rule, 'selected_map_based': selected})
print(summary, '\n', json.dumps(rule, indent=1), '\nselected (map-based):', selected, round(time.time() - t0))

# ---- held-out fold, used once: the map-based selection and logistic regression, tuned on the whole training split
from sklearn.linear_model import LogisticRegression as _LR
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import RandomizedSearchCV

RS = 42


def cal_slope(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    f_ = _LR(C=1e6).fit(np.log(p / (1 - p)).reshape(-1, 1), y)
    return round(float(f_.coef_[0][0]), 3), round(float(f_.intercept_[0]), 3)


heldout, params_train = {}, {}
in_te = np.where(grid.block.isin(set(S.groups[S.test])).to_numpy())[0]
for name in dict.fromkeys([selected, 'logistic_regression']):
    if name == 'frequency_ratio':
        m, params = FrequencyRatio(feats).fit(S.d.iloc[S.train][feats], S.y[S.train]), {}
    else:
        pipe, dist_ = candidates(feats)[name]
        search = RandomizedSearchCV(clone(pipe), dist_, n_iter=8, scoring='roc_auc', cv=S.inner_splits(S.train), n_jobs=-1, random_state=RS)
        search.fit(S.d.iloc[S.train][feats], S.y[S.train])
        m = search.best_estimator_
        params = {k: (float(v) if isinstance(v, (int, float, np.integer, np.floating)) else str(v)) for k, v in search.best_params_.items()}
    s = score(m, S.d.iloc[S.test][feats])
    c = pscore(m, grid.iloc[in_te][feats])
    ls = S.test[(S.y[S.test] == 1) & (dist[S.test] <= 0.2)]
    lsc = pd.Series(c, index=in_te).reindex(cell[ls]).to_numpy()
    lsc = lsc[~np.isnan(lsc)]
    heldout[name] = {'roc_auc': round(float(roc_auc_score(S.y[S.test], s)), 4), 'pr_auc': round(float(average_precision_score(S.y[S.test], s)), 4),
                     'map_top20': round(float((lsc >= np.quantile(c, 0.8)).mean()), 4), 'map_top10': round(float((lsc >= np.quantile(c, 0.9)).mean()), 4),
                     'n_cells': int(len(in_te)), 'n_landslides': int(len(lsc))}
    if not isinstance(m, FrequencyRatio):
        heldout[name]['brier'] = round(float(brier_score_loss(S.y[S.test], s)), 4)
        heldout[name]['calibration_slope_intercept'] = cal_slope(s, S.y[S.test])
    params_train[name] = params
out = json.loads((RESULTS / '04b_map_decision_value.json').read_text())
out.update({'heldout': heldout, 'selected_params_on_training_split': params_train, 'features': feats})
write_json(RESULTS / '04b_map_decision_value.json', out)
print('held-out', json.dumps(heldout, indent=1), round(time.time() - t0))
