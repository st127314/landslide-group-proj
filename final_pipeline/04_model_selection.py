"""Step 4: reselect the production model on the final data with the success rule.

Data (choose with --data):
  points        the thinned training table (02), event-date factors, NDVI removed (scar leakage; the annual
                NDVI composite needs Earth Engine, see gee_ndvi_annual_composite.py). Features: NO_NDVI.
  grid_<design> a grid-based design from 03 (e.g. grid_matched). Features: STATIC.

Candidates: logistic regression (baseline), frequency ratio (classic baseline, no tuning), SVM (RBF),
random forest and histogram gradient boosting, tuned by the notebook's nested search (5 buffered outer
folds, 3 buffered inner folds, 8 random-search iterations, ROC-AUC).

Per outer fold: ROC-AUC, PR-AUC and decision value (share of validation landslides in the top 20% / 10% of
the grid cells inside the validation blocks).

Success rule (from the proposal, applied on the outer folds only, never on the held-out fold):
  a candidate replaces logistic regression only if it has a higher decision value in at least 4 of 5 folds
  and its mean ROC-AUC is not lower than logistic regression's by more than logistic regression's fold SD;
  among such candidates the highest mean decision value wins. Otherwise logistic regression is kept.
The selected model and logistic regression are then refitted on the whole training split and evaluated
once on the held-out fold.

Output: results/final/04_model_selection_<data>.json, 04_folds_<data>.csv
"""
import argparse
import time

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression as _LR
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score, roc_curve
from sklearn.model_selection import RandomizedSearchCV

from common import (FINAL_DATA, NO_NDVI, RESULTS, RS, STATIC, FrequencyRatio, Spatial, candidates, fixed_model,
                    GROUPS, load_grid, score, write_json)

ap = argparse.ArgumentParser()
ap.add_argument('--data', default='points')
ap.add_argument('--n-iter', type=int, default=8)
args = ap.parse_args()
t0 = time.time()
DV_CELLS = 150_000

if args.data == 'points':
    d = pd.read_csv(FINAL_DATA / 'landslide_event_factors_thinned.csv')
    feats = NO_NDVI
else:
    d = pd.read_csv(FINAL_DATA / f"grid_design_{args.data.removeprefix('grid_')}.csv")
    feats = STATIC
S = Spatial(d)
X = S.d[feats]
grid = load_grid()
print('data', args.data, len(d), 'features', len(feats), 'holdout fold', S.fold, 'train', len(S.train), 'test', len(S.test),
      round(time.time() - t0), flush=True)


def cells_in(idx, seed=RS):
    c = np.where(grid.block.isin(set(S.groups[idx])).to_numpy())[0]
    if len(c) > DV_CELLS:
        c = np.random.default_rng(seed).choice(c, DV_CELLS, replace=False)
    return grid.iloc[c][feats]


def evaluate(model, va):
    s = score(model, X.iloc[va])
    ls = va[S.y[va] == 1]
    c, p = score(model, cells_in(va)), score(model, X.iloc[ls])
    return {'roc_auc': roc_auc_score(S.y[va], s), 'pr_auc': average_precision_score(S.y[va], s),
            'top20': float((p >= np.quantile(c, 0.8)).mean()), 'top10': float((p >= np.quantile(c, 0.9)).mean())}, s


def fit(name, tr):
    if name == 'frequency_ratio':
        return FrequencyRatio(feats).fit(X.iloc[tr], S.y[tr]), {}
    pipe, dist = candidates(feats)[name]
    search = RandomizedSearchCV(clone(pipe), dist, n_iter=args.n_iter, scoring='roc_auc', cv=S.inner_splits(tr),
                                n_jobs=-1, random_state=RS, refit=True)
    search.fit(X.iloc[tr], S.y[tr])
    return search.best_estimator_, {k: (float(v) if isinstance(v, (int, float, np.floating, np.integer)) else str(v)) for k, v in search.best_params_.items()}


names = ['logistic_regression', 'frequency_ratio', 'svm_rbf', 'random_forest', 'gradient_boosting']
rows, oof = [], {n: np.full(len(S.d), np.nan) for n in names}
for name in names:
    for f, (tr, va) in enumerate(S.outer):
        m, params = fit(name, tr)
        r, s = evaluate(m, va)
        oof[name][va] = s
        rows.append({'model': name, 'fold': f + 1, **{k: round(v, 4) for k, v in r.items()}, 'params': params})
    print(name, 'done', round(time.time() - t0), flush=True)
folds = pd.DataFrame(rows)
folds.to_csv(RESULTS / f'04_folds_{args.data}.csv', index=False)

summary = folds.groupby('model')[['roc_auc', 'pr_auc', 'top20', 'top10']].agg(['mean', 'std']).round(4)
summary.columns = [f'{a}_{b}' for a, b in summary.columns]
lr = folds[folds.model == 'logistic_regression'].set_index('fold')
lr_auc_sd = float(lr.roc_auc.std())
rule = {}
for name in names[1:]:
    c = folds[folds.model == name].set_index('fold')
    wins = int((c.top20 > lr.top20).sum())
    auc_gap = float(c.roc_auc.mean() - lr.roc_auc.mean())
    rule[name] = {'top20_wins_vs_lr': wins, 'auc_wins_vs_lr': int((c.roc_auc > lr.roc_auc).sum()),
                  'mean_top20_gain': round(float(c.top20.mean() - lr.top20.mean()), 4), 'mean_auc_gap': round(auc_gap, 4),
                  'folds_meeting_70pct': int((c.top20 >= 0.7).sum()),
                  'passes': bool(wins >= 4 and auc_gap >= -lr_auc_sd)}
passing = [n for n in rule if rule[n]['passes']]
selected = max(passing, key=lambda n: summary.loc[n, 'top20_mean']) if passing else 'logistic_regression'
print('rule', rule, 'selected', selected, round(time.time() - t0), flush=True)

# ---- held-out fold, used once
def youden(y, p):
    fpr, tpr, thr = roc_curve(y, p)
    return float(thr[np.argmax(tpr - fpr)])


def cal_slope(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    fit_ = _LR(C=1e6).fit(np.log(p / (1 - p)).reshape(-1, 1), y)
    return round(float(fit_.coef_[0][0]), 3), round(float(fit_.intercept_[0]), 3)


heldout, final_params = {}, {}
for name in dict.fromkeys([selected, 'logistic_regression']):
    m, params = fit(name, S.train)
    r, s = evaluate(m, S.test)
    thr = youden(S.y[S.train][~np.isnan(oof[name][S.train])], oof[name][S.train][~np.isnan(oof[name][S.train])])
    pred = (s >= thr).astype(int)
    pos, neg = S.y[S.test] == 1, S.y[S.test] == 0
    heldout[name] = {**{k: round(v, 4) for k, v in r.items()}, 'oof_youden_threshold': round(thr, 4),
                     'sensitivity': round(float(pred[pos].mean()), 4), 'specificity': round(float(1 - pred[neg].mean()), 4)}
    if hasattr(m, 'predict_proba'):
        heldout[name]['brier'] = round(float(brier_score_loss(S.y[S.test], s)), 4)
        heldout[name]['calibration_slope_intercept'] = cal_slope(s, S.y[S.test])
    final_params[name] = params
print('held-out', heldout, round(time.time() - t0), flush=True)

# ---- E3 rerun on the final data: leave one factor group out (fixed LR / SVM settings)
e3 = {}
for m in ['lr', 'svm']:
    e3[m] = {}
    for g, cols in [('all', [])] + [(g, c) for g, c in GROUPS.items() if any(x in feats for x in c)]:
        f_ = [c for c in feats if c not in cols]
        aucs = []
        for tr, va in S.outer:
            p = fixed_model(m, f_).fit(S.d.iloc[tr][f_], S.y[tr])
            aucs.append(roc_auc_score(S.y[va], score(p, S.d.iloc[va][f_])))
        e3[m]['all factors' if g == 'all' else f'without {g}'] = round(float(np.mean(aucs)), 4)
print('E3', e3, round(time.time() - t0), flush=True)

write_json(RESULTS / f'04_model_selection_{args.data}.json', {
    'data': args.data, 'features': feats, 'n_rows': int(len(d)), 'holdout_fold': int(S.fold),
    'n_train': int(len(S.train)), 'n_test': int(len(S.test)), 'cv_summary': summary.reset_index().to_dict('records'),
    'success_rule': rule, 'lr_auc_sd': round(lr_auc_sd, 4), 'selected': selected, 'heldout': heldout,
    'selected_params_on_training_split': final_params, 'E3_drop_group_auc': e3})
print('done', round(time.time() - t0))
