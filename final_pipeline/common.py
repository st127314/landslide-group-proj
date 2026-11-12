"""Shared helpers for the final-stage pipeline (final_pipeline/0*_*.py).

Mirrors the preprocessing, spatial blocks, 5 km buffer and hold-out selection of
notebooks/landslide_susceptibility_modeling.ipynb and notebooks/experiments/run_experiments.py,
so results stay comparable with the progress report. Requires scikit-learn 1.9.0: other versions
split StratifiedGroupKFold differently and change every fold.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import loguniform, randint
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, PowerTransformer
from sklearn.svm import SVC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'notebooks'))
from susc_utils import add_aspect_features, IQRClipper  # noqa: E402  (pickled pipelines import it by name)

RS = 42
BLOCK = 0.5          # degrees, spatial CV groups
BUF = 5.0            # km, training points this close to validation points are dropped
UTM = 'EPSG:32647'   # metric CRS for southern Thailand

PROCESSED = ROOT / 'data' / 'processed'
FINAL_DATA = PROCESSED / 'final'
GRID_DIR = PROCESSED / 'factor_grid_points' / 'factor_grid_points_2026-10-09'
OSM_GRID = FINAL_DATA / 'osm_distances_grid.csv.gz'
OSM_POINTS = FINAL_DATA / 'osm_distances_points.csv'
GRID_PROVINCE = FINAL_DATA / 'grid_province.csv.gz'
RESULTS = ROOT / 'results' / 'final'
MODELS = ROOT / 'models' / 'final'
for _d in (FINAL_DATA, RESULTS, MODELS):
    _d.mkdir(parents=True, exist_ok=True)

CAT_ALL = ['lithology', 'lulc', 'soil_texture']
GROUPS = {
    'terrain': ['elevation', 'slope', 'aspect', 'curvature_general', 'curvature_profile', 'tri', 'tpi', 'ls_factor'],
    'hydrology': ['upstream_area_km2', 'twi', 'spi'],
    'soil': ['soil_texture', 'soil_clay_pct', 'soil_sand_pct', 'soil_bulk_density'],
    'ndvi': ['ndvi'], 'land_cover': ['lulc'], 'lithology': ['lithology'], 'distances': ['dist_to_road', 'dist_to_river'],
}
ALL_FEATS = sum(GROUPS.values(), [])
NO_NDVI = [c for c in ALL_FEATS if c != 'ndvi']
# Factors that do not depend on the event date, so the 250 m grid (reference date 2026-10-09) describes them correctly.
STATIC = [c for c in ALL_FEATS if c not in ('ndvi', 'lulc')]
GRID_RENAME = {'TRI': 'tri', 'TPI': 'tpi', 'LS_factor': 'ls_factor', 'TWI': 'twi', 'SPI': 'spi', 'NDVI': 'ndvi', 'LULC_current': 'lulc'}


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o)))


def block_id(lon, lat):
    return (np.floor(np.asarray(lon) / BLOCK).astype(int).astype(str).astype(object) + '_'
            + np.floor(np.asarray(lat) / BLOCK).astype(int).astype(str).astype(object))


def km_xy(lon, lat, lat0):
    c = np.cos(np.deg2rad(lat0))
    return np.column_stack((np.asarray(lon) * 111.32 * c, np.asarray(lat) * 111.32))


# ---------------------------------------------------------------- models
def preprocessor(feats, kind):
    cats = [c for c in CAT_ALL if c in feats]
    nums = [c for c in feats if c not in cats]
    num_cols = [c for c in nums if c != 'aspect'] + (['aspect_sin', 'aspect_cos'] if 'aspect' in nums else [])
    if kind == 'linear':
        num = Pipeline([('imputer', SimpleImputer(strategy='median', add_indicator=True)),
                        ('clip', IQRClipper(k=1.5)), ('power', PowerTransformer(method='yeo-johnson', standardize=True))])
    else:
        num = SimpleImputer(strategy='median', add_indicator=True)
    trs = [('num', num, num_cols)]
    if cats:
        trs.append(('cat', Pipeline([('imputer', SimpleImputer(strategy='most_frequent')),
                                     ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False))]), cats))
    pre = [('aspect', FunctionTransformer(add_aspect_features))] if 'aspect' in nums else []
    return Pipeline(pre + [('columns', ColumnTransformer(trs, remainder='drop'))])


def candidates(feats):
    """{name: (pipeline, search space)}; the same search spaces as the notebook's nested search."""
    return {
        'logistic_regression': (Pipeline([('preprocess', preprocessor(feats, 'linear')),
                                          ('model', LogisticRegression(max_iter=5000, class_weight='balanced', random_state=RS))]),
                                {'model__C': loguniform(1e-2, 1e2)}),
        'svm_rbf': (Pipeline([('preprocess', preprocessor(feats, 'linear')),
                              ('model', SVC(kernel='rbf', probability=True, class_weight='balanced', random_state=RS))]),
                    {'model__C': loguniform(0.1, 50), 'model__gamma': loguniform(1e-3, 1e-1)}),
        'random_forest': (Pipeline([('preprocess', preprocessor(feats, 'tree')),
                                    ('model', RandomForestClassifier(n_estimators=300, class_weight='balanced', n_jobs=1, random_state=RS))]),
                          {'model__max_depth': [6, 10, 16, None], 'model__min_samples_leaf': randint(2, 20),
                           'model__max_features': ['sqrt', 0.3, 0.5]}),
        'gradient_boosting': (Pipeline([('preprocess', preprocessor(feats, 'tree')),
                                        ('model', HistGradientBoostingClassifier(class_weight='balanced', random_state=RS))]),
                              {'model__learning_rate': loguniform(0.02, 0.2), 'model__max_depth': randint(2, 8),
                               'model__max_iter': randint(100, 400), 'model__min_samples_leaf': randint(20, 100),
                               'model__l2_regularization': loguniform(1e-3, 10)}),
    }


def fixed_model(name, feats):
    """Fixed hyperparameters from the progress-report nested search (for experiments that vary only the data)."""
    if name == 'lr':
        m = LogisticRegression(C=0.017073967431528128, max_iter=5000, class_weight='balanced', random_state=RS)
    else:
        m = SVC(kernel='rbf', C=0.1434715951720141, gamma=0.05399484409787434, class_weight='balanced', random_state=RS)
    return Pipeline([('preprocess', preprocessor(feats, 'linear')), ('model', m)])


class FrequencyRatio:
    """Frequency-ratio baseline (same as run_experiments.py): sum of per-factor log frequency ratios."""
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
            pos, neg = b[y == 1].value_counts() + 1, b[y == 0].value_counts() + 1
            idx = pos.index.union(neg.index)
            pos, neg = pos.reindex(idx, fill_value=1), neg.reindex(idx, fill_value=1)
            self.table_[f] = np.log((pos / pos.sum()) / (neg / neg.sum()))
        return self

    def decision_function(self, X):
        return sum(self._bin(X, f).map(self.table_[f]).fillna(0.0).to_numpy() for f in self.feats)


def score(model, X):
    """A ranking score (all metrics used here are rank-based)."""
    if isinstance(model, FrequencyRatio):
        return model.decision_function(X)
    if hasattr(model, 'predict_proba') and not (isinstance(model, Pipeline) and isinstance(model[-1], SVC) and not model[-1].probability):
        return model.predict_proba(X)[:, 1]
    return model.decision_function(X)


# ---------------------------------------------------------------- spatial validation
class Spatial:
    """Hold-out fold and buffered outer folds, selected exactly as in the notebook."""
    def __init__(self, d, n_outer=5):
        self.d = d.reset_index(drop=True)
        self.y = self.d['landslide'].astype(int).to_numpy()
        self.groups = block_id(self.d.longitude, self.d.latitude)
        self.xy = km_xy(self.d.longitude, self.d.latitude, self.d.latitude.mean())
        cands = []
        for f, (tr, te) in enumerate(StratifiedGroupKFold(5, shuffle=True, random_state=RS).split(self.d, self.y, self.groups)):
            trk = self.buffered(tr, te)
            err = abs(self.y[trk].mean() - self.y.mean()) + abs(self.y[te].mean() - self.y.mean()) + abs(len(te) / len(self.y) - 0.2)
            cands.append((err, f, trk, te))
        _, self.fold, self.train, self.test = min(cands, key=lambda c: (c[0], c[1]))
        self.outer = []
        for a, b in StratifiedGroupKFold(n_outer, shuffle=True, random_state=RS).split(self.train, self.y[self.train], self.groups[self.train]):
            gtr, gva = self.train[a], self.train[b]
            self.outer.append((self.buffered(gtr, gva), gva))

    def buffered(self, tr, te):
        tr = np.asarray(tr)
        near = cKDTree(self.xy[te]).query(self.xy[tr], k=1)[0] < BUF
        return tr[~near]

    def inner_splits(self, tr, n_inner=3):
        """Buffered inner folds inside the training positions `tr` (positions returned relative to `tr`)."""
        out = []
        for a, b in StratifiedGroupKFold(n_inner, shuffle=True, random_state=RS).split(tr, self.y[tr], self.groups[tr]):
            keep = self.buffered(tr[a], tr[b])
            out.append((np.searchsorted(tr, keep) if np.all(np.diff(tr) > 0) else np.where(np.isin(tr, keep))[0], b))
        return out


# ---------------------------------------------------------------- grid
def load_grid(blocks=None, usecols=None, fill_osm=True):
    """The 250 m factor grid with training-table column names and class names.

    Road and river distances are replaced by the local OSM computation (01_osm_distances.py) for every cell:
    the Earth Engine grid export left 77% of cells empty, and where it has values they disagree with the
    training-table distances (Spearman 0.14), whereas the local computation reproduces the training values
    (Spearman 0.998). `blocks` limits the cells to those 0.5 degree blocks."""
    lith = {c['value']: c['name'] for c in json.loads((ROOT / 'scripts/glim_lithology_classes.json').read_text())['classes']}
    lulc = {c['value']: c['name'] for c in json.loads((ROOT / 'scripts/servir_landcover_classes.json').read_text())['classes']}
    parts, offset = [], 0
    for f in sorted(GRID_DIR.glob('tile_*.csv')):
        g = pd.read_csv(f, usecols=usecols)
        g['_row'] = offset + np.arange(len(g))   # position in the full grid (= row in osm_distances_grid.csv.gz)
        offset += len(g)
        if blocks is not None:
            g = g[pd.Series(block_id(g.px_lon, g.px_lat), index=g.index).isin(blocks)]
        if len(g):
            parts.append(g)
    grid = pd.concat(parts, ignore_index=True).rename(columns=GRID_RENAME)
    if 'lithology' in grid:
        grid['lithology'] = grid['lithology'].map(lith)
    if 'lulc' in grid:
        grid['lulc'] = grid['lulc'].map(lulc)
    grid['block'] = block_id(grid.px_lon, grid.px_lat)
    if fill_osm and OSM_GRID.exists():
        osm = pd.read_csv(OSM_GRID).iloc[grid['_row'].to_numpy()]
        assert np.allclose(osm.px_lon.to_numpy(), grid.px_lon.to_numpy()) and np.allclose(osm.px_lat.to_numpy(), grid.px_lat.to_numpy())
        for c in ['dist_to_road', 'dist_to_river']:
            if c in grid:
                grid[c] = osm[c].to_numpy()
    return grid


def decision_value(train_scores_fn, cells, landslide_points, top=(0.2, 0.1)):
    """Share of `landslide_points` whose score reaches the top 20% / 10% of `cells` scores."""
    c = train_scores_fn(cells)
    p = train_scores_fn(landslide_points)
    return {f'top{int(q * 100)}': round(float((p >= np.quantile(c, 1 - q)).mean()), 4) for q in top}
