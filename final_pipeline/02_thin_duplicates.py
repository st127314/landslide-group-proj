"""Step 2: remove near-duplicate landslides (the progress report found 337 pairs within 30 m).

Landslides closer than 30 m to each other are grouped (single-linkage, so chains form one group); each group
keeps its earliest-dated record (ties: lowest id). Every dropped landslide also loses its paired non-landslide
point (pairing from data/inventory/non_landslide_events.geojson), so the classes stay balanced and every
remaining negative still has its landslide.

Input:  data/processed/landslide_event_factors_cleaned.csv, data/inventory/non_landslide_events.geojson
Output: data/processed/final/landslide_event_factors_thinned.csv, results/final/02_thinning.json
"""
import json

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from common import FINAL_DATA, PROCESSED, RESULTS, ROOT, km_xy, write_json

RADIUS_KM = 0.030

d = pd.read_csv(PROCESSED / 'landslide_event_factors_cleaned.csv')
pairs = {f['properties']['Event_ID']: f"LS_{f['properties']['paired_landslide_id']}"
         for f in json.loads((ROOT / 'data/inventory/non_landslide_events.geojson').read_text())['features']}

ls = d[d.landslide == 1].reset_index(drop=True)
xy = km_xy(ls.longitude, ls.latitude, d.latitude.mean())
close = np.array(sorted(cKDTree(xy).query_pairs(RADIUS_KM)))
n_pairs = len(close)
graph = coo_matrix((np.ones(len(close)), (close[:, 0], close[:, 1])), shape=(len(ls), len(ls)))
_, label = connected_components(graph, directed=False)
ls['group'] = label
ls['num'] = ls.id.str[3:].astype(int)
keep = ls.sort_values(['group', 'event_date', 'num']).groupby('group').head(1).id
dropped_ls = set(ls.id) - set(keep)

neg = d[d.landslide == 0]
unpaired = [i for i in neg.id if i not in pairs]
dropped_neg = {i for i in neg.id if pairs.get(i) in dropped_ls}
out = d[~d.id.isin(dropped_ls | dropped_neg)].reset_index(drop=True)
out.to_csv(FINAL_DATA / 'landslide_event_factors_thinned.csv', index=False)

sizes = pd.Series(label).value_counts()
summary = {'radius_m': RADIUS_KM * 1000, 'landslide_pairs_within_radius': int(n_pairs),
           'duplicate_groups': int((sizes > 1).sum()), 'largest_group': int(sizes.max()),
           'landslides_dropped': len(dropped_ls), 'negatives_dropped': len(dropped_neg), 'negatives_without_pair_info': len(unpaired),
           'rows_before': int(len(d)), 'rows_after': int(len(out)), 'class_counts_after': out.landslide.value_counts().to_dict()}
write_json(RESULTS / '02_thinning.json', summary)
print(summary)
