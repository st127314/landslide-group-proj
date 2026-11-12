"""Step 6: model registry with metadata and a promotion gate (model-level CI/CD from the progress report).

Registry layout (models/registry/, git-ignored like all trained models):
  models/registry/<version>/model.joblib       copy of the trained pipeline
  models/registry/<version>/metadata.json      features, params, data hash, sklearn version, git commit, metrics
  models/registry/index.json                   all versions with status (candidate / production / archived / rejected)
  models/registry/production.json              pointer the API can load

Promotion gate (run on every new candidate; also usable from CI):
  1. Eligibility: no blocked feature (ndvi: the 90-day NDVI captures the landslide scar, progress report 4.1)
     and the decision-value target (>= 70% of validation landslides in the top 20% of the area) met in at
     least 4 of 5 outer folds.
  2. If the current production model is not eligible (e.g. it uses a blocked feature), an eligible candidate
     replaces it.
  3. Otherwise the production model's specification is refitted on the candidate's outer folds and the
     success rule decides: higher decision value in >= 4 of 5 folds and mean ROC-AUC not lower by more than
     the production model's fold SD.

Usage:  python 06_model_registry.py            registers the progress-report model (v1) if absent and the
                                               final-stage model (models/final/) as a candidate, then gates it.
"""
import datetime as dt
import hashlib
import json
import shutil
import subprocess

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.metrics import roc_auc_score

from common import FINAL_DATA, MODELS, RESULTS, ROOT, Spatial, load_grid, score, write_json

REG = ROOT / 'models' / 'registry'
REG.mkdir(parents=True, exist_ok=True)
INDEX = REG / 'index.json'
BLOCKED_FEATURES = {'ndvi': '90-day NDVI before the image date captures the landslide scar (leakage)'}
TARGET, MIN_FOLDS = 0.70, 4


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def git_commit():
    try:
        return subprocess.run(['git', '-C', str(ROOT.parent), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip() or None
    except Exception:
        return None


def load_index():
    return json.loads(INDEX.read_text()) if INDEX.exists() else {'versions': []}


def register(model_path, meta, status='candidate'):
    idx = load_index()
    digest = sha256(model_path)
    for v in idx['versions']:
        if v['model_sha256'] == digest:
            return v['version'], idx
    version = f"v{len(idx['versions']) + 1}"
    vdir = REG / version
    vdir.mkdir(exist_ok=True)
    shutil.copy2(model_path, vdir / 'model.joblib')
    meta = {**meta, 'version': version, 'model_sha256': digest, 'registered_at': dt.datetime.now().isoformat(timespec='seconds'),
            'git_commit': git_commit(), 'status': status}
    write_json(vdir / 'metadata.json', meta)
    idx['versions'].append({k: meta[k] for k in ['version', 'model', 'status', 'model_sha256', 'registered_at']})
    write_json(INDEX, idx)
    return version, idx


def set_status(version, status, reason):
    idx = load_index()
    for v in idx['versions']:
        if v['version'] == version:
            v['status'], v['status_reason'] = status, reason
        elif status == 'production' and v['status'] == 'production':
            v['status'], v['status_reason'] = 'archived', f'replaced by {version}'
    write_json(INDEX, idx)
    if status == 'production':
        write_json(REG / 'production.json', {'version': version, 'path': f'models/registry/{version}/model.joblib', 'reason': reason})


# ---- register v1: the progress-report production model (SVM with NDVI)
old = ROOT / 'models/susceptibility/svm_rbf_landslide_susceptibility_pipeline.joblib'
old_meta = json.loads((ROOT / 'models/susceptibility/model_metadata.json').read_text())
v1, idx = register(old, {'model': 'svm_rbf', 'stage': 'progress report', 'features': old_meta['feature_columns'],
                         'data': 'data/processed/landslide_event_factors_cleaned.csv',
                         'data_sha256': sha256(ROOT / 'data/processed/landslide_event_factors_cleaned.csv'),
                         'sklearn_version': '1.9.0', 'metrics': {'heldout_roc_auc': 0.940, 'heldout_top20': 0.879}})
if not any(v['status'] == 'production' for v in idx['versions']):
    set_status(v1, 'production', 'deployed at the progress-report stage')

# ---- register the final-stage candidate
fm = json.loads((MODELS / 'final_model_metadata.json').read_text())
data_file = FINAL_DATA / ('landslide_event_factors_thinned.csv' if fm['data'] == 'points' else f"grid_design_{fm['data'].removeprefix('grid_')}.csv")
folds = pd.read_csv(RESULTS / f"04_folds_{fm['data']}.csv")
cand_folds = folds[folds.model == fm['model']].sort_values('fold').reset_index(drop=True)
map_dv = RESULTS / '04b_map_decision_value.json'
if fm['data'] == 'points' and map_dv.exists():   # the map-based decision value (04b) is the one the gate uses
    mb = pd.DataFrame(json.loads(map_dv.read_text())['folds'])
    cand_folds['top20'] = mb[mb.model == fm['model']].sort_values('fold').map_top20.to_numpy()
v2, _ = register(MODELS / f"{fm['model']}_final_pipeline.joblib",
                 {'model': fm['model'], 'stage': 'final', 'features': fm['features'], 'params': fm['params'],
                  'data': str(data_file.relative_to(ROOT)), 'data_sha256': sha256(data_file), 'sklearn_version': sklearn.__version__,
                  'metrics': {'cv_top20_folds': cand_folds.top20.tolist(), 'cv_roc_auc_folds': cand_folds.roc_auc.tolist(),
                              'heldout': fm['heldout']}})

# ---- promotion gate
prod_version = json.loads((REG / 'production.json').read_text())['version']
prod_meta = json.loads((REG / prod_version / 'metadata.json').read_text())
cand_meta = json.loads((REG / v2 / 'metadata.json').read_text())
gate = {'candidate': v2, 'production_before': prod_version}


def eligible(meta, top20_folds):
    blocked = sorted(set(meta['features']) & set(BLOCKED_FEATURES))
    meets = int(sum(v >= TARGET for v in top20_folds)) if top20_folds is not None else None
    ok = not blocked and (meets is None or meets >= MIN_FOLDS)
    return ok, {'blocked_features': blocked, 'folds_meeting_target': meets}


cand_ok, gate['candidate_eligibility'] = eligible(cand_meta, cand_folds.top20.tolist())
prod_ok, gate['production_eligibility'] = eligible(prod_meta, None)
if v2 == prod_version:
    gate['decision'], reason = 'already production', 'candidate is the production model'
elif not cand_ok:
    gate['decision'], reason = 'rejected', f"candidate not eligible: {gate['candidate_eligibility']}"
    set_status(v2, 'rejected', reason)
elif not prod_ok:
    gate['decision'], reason = 'promoted', f"production model {prod_version} is not eligible ({gate['production_eligibility']['blocked_features']} blocked); candidate meets the target in {gate['candidate_eligibility']['folds_meeting_target']} of 5 folds"
    set_status(v2, 'production', reason)
else:
    # refit the production specification on the candidate's outer folds and apply the success rule
    d = pd.read_csv(data_file)
    S = Spatial(d)
    grid = load_grid()
    prod = joblib.load(REG / prod_version / 'model.joblib')
    pf = prod_meta['features']
    p_top, p_auc = [], []
    for tr, va in S.outer:
        m = clone(prod).fit(S.d.iloc[tr][pf], S.y[tr])
        cells = grid[grid.block.isin(set(S.groups[va]))][pf]
        ls = va[S.y[va] == 1]
        p_top.append(float((score(m, S.d.iloc[ls][pf]) >= np.quantile(score(m, cells), 0.8)).mean()))
        p_auc.append(roc_auc_score(S.y[va], score(m, S.d.iloc[va][pf])))
    wins = int((cand_folds.top20.to_numpy() > np.array(p_top)).sum())
    auc_gap = float(cand_folds.roc_auc.mean() - np.mean(p_auc))
    gate['comparison'] = {'production_top20_folds': p_top, 'candidate_top20_folds': cand_folds.top20.tolist(), 'wins': wins, 'auc_gap': auc_gap}
    if wins >= 4 and auc_gap >= -float(np.std(p_auc, ddof=1)):
        gate['decision'], reason = 'promoted', f'higher decision value in {wins} of 5 folds'
        set_status(v2, 'production', reason)
    else:
        gate['decision'], reason = 'rejected', f'higher decision value in only {wins} of 5 folds'
        set_status(v2, 'rejected', reason)
gate['reason'] = reason
gate['production_after'] = json.loads((REG / 'production.json').read_text())['version']
write_json(RESULTS / '06_promotion_gate.json', gate)
print(json.dumps(gate, indent=1))
