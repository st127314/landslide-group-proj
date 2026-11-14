"""Shared set-up for the experiment scripts: preprocessing, the reference models with the hyperparameters chosen by the
notebook's nested search (read from models/susceptibility/model_metadata.json, so a retrain carries over), the
frequency-ratio baseline, and the notebook's hold-out split and buffered spatial folds (0.5 degree blocks, 5 km
buffer). Imported by run_experiments.py and run_followup_experiments.py.

NDVI is loaded but is not a model factor: it was measured after the scar formed (docs/METHODS.md, Known issue 14).
The experiments that need it (the leakage check, the comparison with the earlier model) ask for WITH_NDVI."""
import json, os, sys, time, warnings
from pathlib import Path
import numpy as np, pandas as pd
from scipy.spatial import cKDTree
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer, KNNImputer
from functools import partial
from sklearn.feature_selection import SelectKBest, mutual_info_classif
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
V1_TABLE = ROOT / 'data/processed/legacy_random_negatives_factors_cleaned.csv'
FACTOR_GRID = Path(os.environ.get('FACTOR_GRID', ROOT / 'data/processed/factor_grid_points'))
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
ALL_FEATS = [c for c in sum(GROUPS.values(), []) if c != 'ndvi']      # the 19 factors of the model
WITH_NDVI = ALL_FEATS + ['ndvi']                                       # the 20 factors of the earlier model
PARAMS = json.loads((ROOT / 'models/susceptibility/model_metadata.json').read_text())['best_params']


def load(path):
    d = pd.read_csv(path)
    d = d[[c for c in ['id', 'event_date', 'longitude', 'latitude', 'landslide'] + WITH_NDVI]].reset_index(drop=True)
    return d


def prep(feats, imputer='median', numeric='clip_power', cat='onehot', indicators=True):
    cats = [c for c in CAT_ALL if c in feats]
    nums = [c for c in feats if c not in cats]
    has_aspect = 'aspect' in nums
    num_cols = [c for c in nums if c != 'aspect'] + (['aspect_sin', 'aspect_cos'] if has_aspect else [])
    imp = SimpleImputer(strategy='median', add_indicator=indicators) if imputer == 'median' else KNNImputer(n_neighbors=10, add_indicator=indicators)
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
    """lr, svm, rf: the reference models. lrfs: logistic regression after mutual-information feature selection, the model
    selected by the nested search (the selection is seeded here; it keeps at most the selected number of inputs)."""
    if name == 'lr':
        m = LogisticRegression(C=PARAMS['logistic_regression']['model__C'], max_iter=5000, class_weight='balanced', random_state=RS)
    elif name == 'lrfs':
        p = PARAMS['logistic_regression_feature_selected']
        m = LogisticRegression(C=p['model__C'], max_iter=5000, class_weight='balanced', random_state=RS)
        select = SelectKBest(partial(mutual_info_classif, random_state=RS), k=p['select__k'])
        return Pipeline([('prep', prep(feats, **kw)), ('select', select), ('m', m)])
    elif name == 'svm':
        p = PARAMS['svm_rbf']
        m = SVC(kernel='rbf', C=p['model__C'], gamma=p['model__gamma'], class_weight='balanced', random_state=RS)
    elif name == 'rf':
        p = PARAMS['random_forest']
        m = RandomForestClassifier(n_estimators=300, max_depth=p['model__max_depth'], min_samples_leaf=p['model__min_samples_leaf'],
                                   max_features=p['model__max_features'], class_weight='balanced', n_jobs=-1, random_state=RS)
    return Pipeline([('prep', prep(feats, **kw)), ('m', m)])


class FrequencyRatio:
    """Frequency-ratio baseline: each factor is binned (numeric factors into training deciles, categorical factors
    by class); a bin's ratio is its share among landslides over its share among non-landslides, and a location's
    score is the sum of the log ratios of its bins."""
    def __init__(self, feats, bins=10):
        self.feats, self.bins = feats, bins

    def _bin(self, X, f):
        if f in CAT_ALL:
            return X[f].astype(str).fillna('missing')
        return pd.cut(X[f], self.edges_[f], include_lowest=True).astype(str).fillna('missing')

    def fit(self, X, y):
        self.edges_, self.table_ = {}, {}
        y = np.asarray(y)
        for f in self.feats:
            if f not in CAT_ALL:
                edges = np.unique(np.nanquantile(X[f], np.linspace(0, 1, self.bins + 1)))
                edges[0], edges[-1] = -np.inf, np.inf
                self.edges_[f] = edges
            b = self._bin(X, f)
            pos = b[y == 1].value_counts() + 1
            neg = b[y == 0].value_counts() + 1
            idx = pos.index.union(neg.index)
            pos, neg = pos.reindex(idx, fill_value=1), neg.reindex(idx, fill_value=1)
            self.table_[f] = np.log((pos / pos.sum()) / (neg / neg.sum()))
        return self

    def decision_function(self, X):
        return sum(self._bin(X, f).map(self.table_[f]).fillna(0.0).to_numpy() for f in self.feats)


def score(pipe, X):
    if isinstance(pipe, FrequencyRatio):
        return pipe.decision_function(X)
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
