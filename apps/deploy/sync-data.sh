#!/usr/bin/env bash
# Run LOCALLY (from anywhere) to upload only what the API reads to the server's data volume.
# The data is private and is never part of the git repo or the Docker images.
#   apps/deploy/sync-data.sh ~/path/to/ml.pem ubuntu@<server-ip>
set -euo pipefail
KEY="${1:?usage: sync-data.sh <key.pem> <user@host>}"
HOST="${2:?usage: sync-data.sh <key.pem> <user@host>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SSH="ssh -i $KEY -o IdentitiesOnly=yes"

# Exactly the files apps/backend/app/paths.py reads (the 270 MB factor-grid tiles are not needed).
rsync -az --partial --info=progress2 -e "$SSH" --relative \
  "$ROOT/./data/boundary/southern_thailand.geojson" \
  "$ROOT/./data/boundary/southern_thailand_tambons.geojson" \
  "$ROOT/./data/external/buildings_aoi.geojson" \
  "$ROOT/./data/external/facilities_aoi.geojson" \
  "$ROOT/./data/external/worldpop_manifest.json" \
  "$ROOT/./data/external/manifest.json" \
  "$ROOT/./models/susceptibility/model_metadata.json" \
  "$ROOT/./models/susceptibility/landslide_sample_susceptibility_scores.csv" \
  "$ROOT/./results/susceptibility_map/susceptibility_grid_points.csv" \
  "$ROOT/./results/susceptibility_map/susceptibility_map_metadata.json" \
  "$ROOT/./results/live_forecast/latest.json" \
  "$ROOT/./results/impact_overlay/impact_overlay.json" \
  "$HOST:/opt/landslide/project/"
echo "Uploaded. The API caches data in memory: restart it to pick up changes ->"
echo "  $SSH $HOST 'cd /opt/landslide && docker compose restart backend'"
