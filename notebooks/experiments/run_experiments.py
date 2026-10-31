"""Supplementary experiments E1-E7, error analysis and partial dependence for the susceptibility model.

Uses the same preprocessing, 0.5 degree spatial blocks, 5 km buffer and hold-out fold as
landslide_susceptibility_modeling.ipynb. Hyperparameters are fixed to the values chosen by the notebook's
nested search, so each experiment changes only the factor under test.

Run from the project root:
    python notebooks/experiments/run_experiments.py

Inputs: data/processed/landslide_event_factors_cleaned.csv; results/experiments/province.csv (province of each
point, from a spatial join with the province boundaries); for E4, the earlier dataset with randomly placed
negatives (path in V1_TABLE, set the environment variable V1_TABLE to point elsewhere); for the error analysis,
models/susceptibility/ and results/susceptibility_map/ produced by the notebook and predict_susceptibility_grid.py.
Outputs: results/experiments/results.json and results/experiments/errors.json.
"""
import json, os, sys, time, warnings
from pathlib import Path
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer, KNNImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, PowerTransformer, StandardScaler, TargetEncoder
from sklearn.svm import SVC
from sklearn.inspection import partial_dependence
import joblib

warnings.filterwarnings('ignore')
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results' / 'experiments'
V1_TABLE = Path(os.environ.get('V1_TABLE', ROOT.parent / 'group_proj_archive/superseded_v1/processed/landslide_event_factors_cleaned.csv'))
sys.path.insert(0, str(ROOT / 'notebooks'))
from susc_utils import add_aspect_features, IQRClipper

RS = 42; BLOCK = 0.5; BUF = 5.0
CAT_ALL = ['lithology', 'lulc', 'soil_texture']
GROUPS = {
    'terrain': ['elevation', 'slope', 'aspect', 'curvature_general', 'curvature_profile', 'tri', 'tpi', 'ls_factor'],
    'hydrology': ['upstream_area_km2', 'twi', 'spi'],
    'soil': ['soil_texture', 'soil_clay_pct', 'soil_sand_pct', 'soil_bulk_density'],
    'ndvi': ['ndvi'], 'land_cover': ['lulc'], 'lithology': ['lithology'], 'distances': ['dist_to_road', 'dist_to_river'],
}
ALL_FEATS = sum(GROUPS.values(), [])


def load(path):
    d = pd.read_csv(path)
    d = d[[c for c in ['id', 'event_date', 'longitude', 'latitude', 'landslide'] + ALL_FEATS]].reset_index(drop=True)
    return d


def prep(feats, imputer='median', numeric='clip_power', cat='onehot'):
    cats = [c for c in CAT_ALL if c in feats]
    nums = [c for c in feats if c not in cats]
    has_aspect = 'aspect' in nums
    num_cols = [c for c in nums if c != 'aspect'] + (['aspect_sin', 'aspect_cos'] if has_aspect else [])
    imp = SimpleImputer(strategy='median', add_indicator=True) if imputer == 'median' else KNNImputer(n_neighbors=10, add_indicator=True)
    steps = [('imputer', imp)]
    if imputer == 'knn':
        steps = [('scale0', StandardScaler()), ('imputer', imp)]
    if numeric == 'clip_power':
        steps += [('clip', IQRClipper(k=1.5)), ('power', PowerTransformer(method='yeo-johnson', standardize=True))]
    else:
        steps += [('scale', StandardScaler())]
    trs = [('num', Pipeline(steps), num_cols)] if num_cols else []
    if cats:
        if cat == 'onehot':
            cp = Pipeline([('imp', SimpleImputer(strategy='most_frequent')), ('enc', OneHotEncoder(handle_unknown='ignore', sparse_output=False))])
        else:  # cross-fitted target encoding (used in place of Weight-of-Evidence)
            cp = Pipeline([('imp', SimpleImputer(strategy='most_frequent')), ('enc', TargetEncoder(target_type='binary', random_state=RS)), ('sc', StandardScaler())])
        trs.append(('cat', cp, cats))
    pre = [('aspect', FunctionTransformer(add_aspect_features))] if has_aspect else []
    return Pipeline(pre + [('columns', ColumnTransformer(trs, remainder='drop'))])


def model(name, feats, **kw):
    if name == 'lr':
        m = LogisticRegression(C=0.017073967431528128, max_iter=5000, class_weight='balanced', random_state=RS)
    elif name == 'svm':
        m = SVC(kernel='rbf', C=0.1434715951720141, gamma=0.05399484409787434, class_weight='balanced', random_state=RS)
    elif name == 'rf':
        m = RandomForestClassifier(n_estimators=300, max_depth=16, min_samples_leaf=5, max_features='sqrt', class_weight='balanced', n_jobs=-1, random_state=RS)
    return Pipeline([('prep', prep(feats, **kw)), ('m', m)])


def score(pipe, X):
    return pipe.decision_function(X) if hasattr(pipe, 'decision_function') and isinstance(pipe[-1], (SVC, LogisticRegression)) else pipe.predict_proba(X)[:, 1]


class Setup:
    """Holds the notebook's hold-out split and buffered outer folds for one dataset."""
    def __init__(self, d):
        self.d = d
        self.y = d['landslide'].astype(int).to_numpy()
        self.groups = (np.floor(d.longitude / BLOCK).astype(int).astype(str) + '_' + np.floor(d.latitude / BLOCK).astype(int).astype(str)).to_numpy()
        lat = np.deg2rad(d.latitude.mean())
        self.xy = np.column_stack((d.longitude * 111.32 * np.cos(lat), d.latitude * 111.32))
        cands = []
        for f, (tr, te) in enumerate(StratifiedGroupKFold(5, shuffle=True, random_state=RS).split(d, self.y, self.groups)):
            trk = self.buffered(tr, te)
            err = abs(self.y[trk].mean() - self.y.mean()) + abs(self.y[te].mean() - self.y.mean()) + abs(len(te) / len(self.y) - 0.2)
            cands.append((err, f, trk, te))
        _, self.fold, self.train, self.test = min(cands, key=lambda c: (c[0], c[1]))
        self.outer = []
        tr_g = self.groups[self.train]
        for a, b in StratifiedGroupKFold(5, shuffle=True, random_state=RS).split(self.train, self.y[self.train], tr_g):
            gtr, gva = self.train[a], self.train[b]
            self.outer.append((self.buffered(gtr, gva), gva))

    def buffered(self, tr, te):
        near = cKDTree(self.xy[te]).query(self.xy[tr], k=1)[0] < BUF
        return np.asarray(tr)[~near]

    def cv(self, make, feats, y=None, noise=None, seed=0):
        y = self.y if y is None else y
        aucs, prs = [], []
        X = self.d
        for tr, va in self.outer:
            ytr = y[tr].copy()
            if noise:
                rng = np.random.default_rng(seed); flip = rng.random(len(ytr)) < noise; ytr[flip] = 1 - ytr[flip]
            p = make().fit(X.iloc[tr][feats], ytr)
            s = score(p, X.iloc[va][feats])
            aucs.append(roc_auc_score(y[va], s)); prs.append(average_precision_score(y[va], s))
        return {'auc_folds': [round(a, 4) for a in aucs], 'auc_mean': round(float(np.mean(aucs)), 4), 'auc_sd': round(float(np.std(aucs, ddof=1)), 4),
                'pr_mean': round(float(np.mean(prs)), 4)}


R = {}
t0 = time.time()
d2 = load(ROOT / 'data/processed/landslide_event_factors_cleaned.csv')
S2 = Setup(d2)
R['setup'] = {'n': len(d2), 'holdout_fold': int(S2.fold), 'train': int(len(S2.train)), 'test': int(len(S2.test)), 'outer_fold_sizes': [int(len(v)) for _, v in S2.outer]}
print('setup', R['setup'], flush=True)

# ---- E2: per-fold logistic regression, SVM and random forest with the baseline preprocessing
R['E2'] = {m: S2.cv(lambda m=m: model(m, ALL_FEATS), ALL_FEATS) for m in ['lr', 'svm', 'rf']}
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
grid = pd.read_csv(ROOT / 'results/susceptibility_map/susceptibility_grid_points.csv', usecols=['raw_probability'])
q80, q90 = grid.raw_probability.quantile([0.8, 0.9])
ERR['decision'] = {'top20': float((pos.heldout_score >= q80).mean()), 'top10': float((pos.heldout_score >= q90).mean()), 'n_test_landslides': int(len(pos))}
(OUT / 'errors.json').write_text(json.dumps(ERR, indent=1))
print('saved', round(time.time() - t0))
