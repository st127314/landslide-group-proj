#!/usr/bin/env bash
# Run the whole final-stage pipeline in order (about 2 hours on 4 cores; 03 and 04 take most of it).
# Needs scikit-learn==1.9.0 (other versions split the spatial folds differently) and the packages in
# final_pipeline/requirements.txt, the factor grid in data/processed/factor_grid_points/ and the
# Geofabrik extract in data/external/osm/thailand-free.shp.zip.
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python}"
LOG=../results/final
mkdir -p "$LOG"
run() { echo "== $1"; "$PY" -W ignore -u "$@" > "$LOG/${1%.py}_log.txt" 2>&1; tail -n 3 "$LOG/${1%.py}_log.txt"; }
run 01_osm_distances.py
run 02_thin_duplicates.py
run 03_negative_designs.py
run 04_model_selection.py --data points
run 04b_map_decision_value.py
run 05_final_model_map.py --data points
run 07_exposure_summary.py
run 06_model_registry.py
