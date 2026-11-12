"""Step 5: final production model, susceptibility map, uncertainty map and grid-size sensitivity.

1. Refit the model selected in 04 on all labelled rows (hyperparameters from its training-split search).
2. Score the whole 250 m grid (OSM distances everywhere). Classes are relative, by grid percentile: very high =
   top 10% of cells, high = next 10%, moderate = next 15%, low = next 25%, very low = remaining 40%. High plus
   very high is therefore exactly the top 20% used by the decision-value target. (Isotonic calibration made the
   held-out scores worse in the progress report, so scores are not presented as probabilities.)
3. Uncertainty: the five outer-fold models of 04 (refitted with their fold hyperparameters) each score the grid;
   the per-cell standard deviation of their percentile ranks, and whether all five put the cell in the same
   class band, show where the ranking is unstable.
4. Grid-size sensitivity: on each outer validation area, decision value with cells aggregated to 250 m, 500 m
   and 1 km (mean score per coarse cell; a landslide takes the score of its coarse cell).

Writes the map in the format scripts/build_impact_overlay.py and the app read:
  results/susceptibility_map/susceptibility_grid_points.csv, susceptibility_grid.tif, susceptibility_map_metadata.json
plus results/final/05_*.json|csv, results/final/figures/*.png and models/final/*.
"""
import argparse
import ast
import json
import time

import joblib
from joblib import Parallel, delayed
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import sklearn
from rasterio.transform import from_origin
from sklearn.base import clone

from common import (FINAL_DATA, MODELS, NO_NDVI, RESULTS, ROOT, STATIC, FrequencyRatio, Spatial, candidates,
                    load_grid, score, write_json)

ap = argparse.ArgumentParser()
ap.add_argument('--data', default='points')
ap.add_argument('--model', default=None, help='override the selected model, e.g. logistic_regression (must have held-out params in 04b)')
args = ap.parse_args()
t0 = time.time()
sel = json.loads((RESULTS / f'04_model_selection_{args.data}.json').read_text())
map_sel = RESULTS / '04b_map_decision_value.json'
if args.data == 'points' and map_sel.exists():
    # 04b re-applies the success rule with the map-based decision value (each landslide scored at its own grid
    # cell); it supersedes 04's point-based choice and holds the held-out results of its selection.
    mb = json.loads(map_sel.read_text())
    sel['selected'] = mb['selected_map_based']
    sel['selected_params_on_training_split'] = mb['selected_params_on_training_split']
    sel['heldout'] = mb['heldout']
if args.model:
    sel['selected'] = args.model
name = sel['selected']
feats = sel['features']
d = (pd.read_csv(FINAL_DATA / 'landslide_event_factors_thinned.csv') if args.data == 'points'
     else pd.read_csv(FINAL_DATA / f"grid_design_{args.data.removeprefix('grid_')}.csv"))
S = Spatial(d)
grid = load_grid()
FIG = RESULTS / 'figures'
FIG.mkdir(exist_ok=True)
BANDS = [(0.90, 'very_high'), (0.80, 'high'), (0.65, 'moderate'), (0.40, 'low'), (0.0, 'very_low')]


def build(params):
    if name == 'frequency_ratio':
        return FrequencyRatio(feats)
    pipe = clone(candidates(feats)[name][0])

    def restore(k, v):   # 04 stores numbers as float and None as the string 'None'
        if v == 'None':
            return None
        if isinstance(v, float) and v.is_integer() and k.endswith(('depth', 'leaf', 'iter', 'estimators')):
            return int(v)
        return v
    return pipe.set_params(**{k: restore(k, v) for k, v in params.items()})


def pscore(model, X, chunk=50_000):
    """score() over row chunks on all cores (an RBF SVM needs ~20 min for the 1.1 M cells on one core)."""
    parts = Parallel(n_jobs=-1)(delayed(score)(model, X.iloc[i:i + chunk]) for i in range(0, len(X), chunk))
    return np.concatenate(parts)


def band(pct):
    out = np.full(len(pct), 'very_low', dtype=object)
    for lo, lab in reversed(BANDS):
        out[pct >= lo] = lab
    return out


# ---- 1-2. final model and map
final = build(sel['selected_params_on_training_split'].get(name, {})).fit(S.d[feats], S.y)
s = pscore(final, grid[feats])
pct = pd.Series(s).rank(pct=True, method='average').to_numpy()
grid['score'] = s
grid['percentile'] = pct
grid['susceptibility_class'] = band(pct)
print('map scored', round(time.time() - t0), flush=True)

# ---- 3. uncertainty from the five outer-fold models
folds = pd.read_csv(RESULTS / f'04_folds_{args.data}.csv')
fold_scores, fold_models = [], []
for f, (tr, va) in enumerate(S.outer):
    params = ast.literal_eval(folds[(folds.model == name) & (folds.fold == f + 1)].params.iloc[0])
    m = build(params).fit(S.d.iloc[tr][feats], S.y[tr])
    fold_models.append(m)
    fold_scores.append(pscore(m, grid[feats]))
    print('fold model', f + 1, 'scored', round(time.time() - t0), flush=True)
ranks = np.vstack([pd.Series(v).rank(pct=True).to_numpy() for v in fold_scores])
grid['rank_sd'] = ranks.std(axis=0, ddof=1)
bands = np.vstack([band(r) for r in ranks])
grid['class_agreement'] = (bands == bands[0]).all(axis=0)
top_any, top_all = (ranks >= 0.8).any(axis=0), (ranks >= 0.8).all(axis=0)
unc = {'rank_sd_median': round(float(np.median(grid.rank_sd)), 4), 'rank_sd_p90': round(float(np.quantile(grid.rank_sd, 0.9)), 4),
       'share_same_class_all_five_models': round(float(grid.class_agreement.mean()), 4),
       'top20_in_all_five_models_over_top20_in_any': round(float(top_all.sum() / max(top_any.sum(), 1)), 4),
       'rank_sd_median_by_class': grid.groupby('susceptibility_class').rank_sd.median().round(4).to_dict()}
print('uncertainty', unc, round(time.time() - t0), flush=True)

# ---- 4. grid-size sensitivity on the outer validation areas (reuses the fold models' grid scores)
lat0 = grid.px_lat.mean()
sens = {}
for res_m in [250, 500, 1000]:
    vals = []
    dlon, dlat = res_m / (111_320 * np.cos(np.radians(lat0))), res_m / 110_574
    key = lambda lon, lat: np.floor(np.asarray(lon) / dlon).astype(np.int64) * 10_000_000 + np.floor(np.asarray(lat) / dlat).astype(np.int64)
    for f, (tr, va) in enumerate(S.outer):
        in_va = grid.block.isin(set(S.groups[va])).to_numpy()
        cells = grid[in_va]
        coarse = pd.Series(fold_scores[f][in_va], index=key(cells.px_lon, cells.px_lat)).groupby(level=0).mean()
        ls = va[S.y[va] == 1]
        ls_score = coarse.reindex(key(S.d.longitude.iloc[ls], S.d.latitude.iloc[ls])).to_numpy()
        ok = ~np.isnan(ls_score)
        vals.append(float((ls_score[ok] >= np.quantile(coarse.to_numpy(), 0.8)).mean()))
    sens[f'{res_m}m'] = {'top20_folds': [round(v, 4) for v in vals], 'top20_mean': round(float(np.mean(vals)), 4),
                         'note': 'a landslide takes the mean score of its coarse cell; cells are the validation blocks'}
print('grid-size sensitivity', sens, round(time.time() - t0), flush=True)

# ---- outputs
out_dir = ROOT / 'results' / 'susceptibility_map'
out_dir.mkdir(parents=True, exist_ok=True)
grid['raw_probability'] = grid['score']
grid['calibrated_probability'] = grid['percentile']   # kept for app compatibility: a relative percentile, not a probability
grid['above_threshold'] = (grid['percentile'] >= 0.8).astype(int)
cols = ['px_lon', 'px_lat', 'raw_probability', 'calibrated_probability', 'susceptibility_class', 'above_threshold']
grid[cols].to_csv(out_dir / 'susceptibility_grid_points.csv', index=False)
grid[['px_lon', 'px_lat', 'score', 'percentile', 'susceptibility_class', 'rank_sd', 'class_agreement']].to_csv(
    RESULTS / '05_susceptibility_uncertainty_grid.csv.gz', index=False, float_format='%.5f')

lon_step = 250 / (111_320 * np.cos(np.radians(lat0)))
lat_step = 250 / 110_574
minx, maxy = grid.px_lon.min(), grid.px_lat.max()
ncol = int(np.ceil((grid.px_lon.max() - minx) / lon_step)) + 1
nrow = int(np.ceil((maxy - grid.px_lat.min()) / lat_step)) + 1
col = np.clip(((grid.px_lon - minx) / lon_step).round().astype(int), 0, ncol - 1).to_numpy()
row = np.clip(((maxy - grid.px_lat) / lat_step).round().astype(int), 0, nrow - 1).to_numpy()


def raster(values):
    a = np.full((nrow, ncol), np.nan, dtype=np.float32)
    a[row, col] = values
    return a


tf = from_origin(minx - lon_step / 2, maxy + lat_step / 2, lon_step, lat_step)
with rasterio.open(out_dir / 'susceptibility_grid.tif', 'w', driver='GTiff', height=nrow, width=ncol, count=2, dtype='float32',
                   crs='EPSG:4326', transform=tf, nodata=np.nan, compress='deflate') as dst:
    dst.write(raster(grid.percentile.to_numpy(np.float32)), 1)
    dst.write(raster(grid.rank_sd.to_numpy(np.float32)), 2)
    dst.set_band_description(1, 'susceptibility percentile'); dst.set_band_description(2, 'rank SD across fold models')

class_share = grid.susceptibility_class.value_counts(normalize=True).round(4).to_dict()
(out_dir / 'susceptibility_map_metadata.json').write_text(json.dumps({
    'model': name, 'selection': f'success rule on nested spatial CV (final_pipeline/04, data={args.data})',
    'features': feats, 'point_count': int(len(grid)), 'class_rule': 'grid percentile bands: very_high >= 90th, high 80-90th, moderate 65-80th, low 40-65th, very_low < 40th',
    'class_share': class_share, 'score_interpretation': 'relative susceptibility rank; not a probability of failure',
    'calibrated_probability_column': 'grid percentile of the score (kept under this name for app compatibility)',
    'distances': 'road and river distances computed locally from OpenStreetMap for every cell (final_pipeline/01)'}, indent=2))

joblib.dump(final, MODELS / f'{name}_final_pipeline.joblib')
meta = {'model': name, 'data': args.data, 'features': feats, 'params': sel['selected_params_on_training_split'].get(name, {}),
        'n_rows': int(len(S.d)), 'sklearn_version': sklearn.__version__, 'heldout': sel['heldout'].get(name),
        'cv_summary': [r for r in sel['cv_summary'] if r['model'] == name], 'class_rule': 'grid percentile bands (see map metadata)',
        'grid_percentile_cutoffs': {lab: float(np.quantile(s, lo)) for lo, lab in BANDS if lo > 0}}
write_json(MODELS / 'final_model_metadata.json', meta)
write_json(RESULTS / '05_final_map.json', {'model': name, 'class_share': class_share, 'uncertainty': unc,
                                           'grid_size_sensitivity': sens})

# ---- figures
for col_, title, cmap, fname in [('percentile', f'Final susceptibility percentile ({name})', 'YlOrRd', 'final_susceptibility_map.png'),
                                 ('rank_sd', 'Uncertainty: SD of percentile rank across 5 fold models', 'viridis', 'final_uncertainty_map.png')]:
    fig, ax = plt.subplots(figsize=(7, 9))
    im = ax.imshow(raster(grid[col_].to_numpy(np.float32)), cmap=cmap,
                   extent=[minx, minx + ncol * lon_step, maxy - nrow * lat_step, maxy])
    ax.set_title(title, fontsize=10); ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
    fig.colorbar(im, ax=ax, shrink=0.6); fig.tight_layout(); fig.savefig(FIG / fname, dpi=130); plt.close(fig)
print('done', round(time.time() - t0))
