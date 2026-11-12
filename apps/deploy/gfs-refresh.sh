#!/usr/bin/env bash
# Scheduled refresh of the live forecast and the impact overlay (progress report, remaining work 8).
# Runs on the server, where the private data and the Earth Engine key live; the API re-reads the outputs
# on every request, so no container restart is needed. Installed by install-gfs-timer.sh (not enabled yet).
#
#   PROJECT_DIR  data/models/results mounted into the backend (default /opt/landslide/project)
#   VENV         Python env with earthengine-api, pandas, geopandas, rasterio (default /opt/landslide/venv)
#   GEE_KEY_FILE Earth Engine service-account key (default $PROJECT_DIR/scripts/service_account/key.json)
set -euo pipefail
PROJECT_DIR="${PROJECT_DIR:-/opt/landslide/project}"
VENV="${VENV:-/opt/landslide/venv}"
LOCK=/tmp/landslide-gfs-refresh.lock
exec 9>"$LOCK"
flock -n 9 || { echo "$(date -Is) previous refresh still running, skipping"; exit 0; }
cd "$PROJECT_DIR"
echo "$(date -Is) GFS forecast"
"$VENV/bin/python" scripts/run_live_gfs_forecast.py
echo "$(date -Is) impact overlay"
"$VENV/bin/python" scripts/build_impact_overlay.py
echo "$(date -Is) done"
