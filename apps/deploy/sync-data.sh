#!/usr/bin/env bash
# Run LOCALLY (from anywhere) to upload only what the API reads to the server's data volume.
# The data is private and is never part of the git repo or the Docker images.
#   apps/deploy/sync-data.sh ~/path/to/key.pem user@host
#   SKIP_BUILDINGS=1 apps/deploy/sync-data.sh key.pem user@host     # small servers (see below)
#   SSH_EXTRA="-o UserKnownHostsFile=/path/known_hosts -o StrictHostKeyChecking=yes" ...   # pin the host key
#
# SKIP_BUILDINGS=1 leaves out the 426k building footprints as GeoJSON (140 MB) and the unused tambon polygons.
# Loading that GeoJSON takes the API about 1.4 GB of RAM, so a server with < 4 GB should skip it. The map does not need
# it: buildings are drawn from data/external/buildings.pmtiles (20 MB vector tiles, always uploaded); only the
# bounding-box endpoint /api/impact/buildings then reports them as unavailable.
set -euo pipefail
KEY="${1:?usage: sync-data.sh <key.pem> <user@host>}"
HOST="${2:?usage: sync-data.sh <key.pem> <user@host>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SSH="ssh -i $KEY -o IdentitiesOnly=yes ${SSH_EXTRA:-}"

# Exactly the files apps/backend/app/paths.py reads (the 270 MB factor grid is not needed).
FILES=(
  "data/boundary/southern_thailand_web.geojson"   # slimmed by scripts/make_web_layers.py
  "data/external/facilities_web.geojson"
  "data/external/worldpop_manifest.json"
  "data/boundary/southern_thailand_tambon_points.csv"   # forecast job inputs
  "data/external/rain_percentiles_24h_tambon.csv"
  "data/external/manifest.json"
  "data/external/buildings.pmtiles"                     # 20 MB vector tiles, served by range requests
  "models/susceptibility/model_metadata.json"
  "models/susceptibility/landslide_sample_susceptibility_scores.csv"
  "results/susceptibility_map/susceptibility_grid_points.csv"
  "results/susceptibility_map/susceptibility_map_metadata.json"
  "results/susceptibility_map/susceptibility_web.png"    # from scripts/make_susceptibility_png.py
  "results/susceptibility_map/susceptibility_web.json"
  "results/live_forecast/latest.json"
  "results/impact_overlay/impact_overlay.json"
)
if [ "${SKIP_BUILDINGS:-0}" != "1" ]; then
  FILES+=("data/external/buildings_aoi.geojson" "data/boundary/southern_thailand_tambons.geojson")
fi
# Run from the project root with relative paths: --relative then recreates exactly data/..., models/..., results/...
# (macOS's bundled rsync ignores the "/./" path marker and would recreate the absolute path instead).
cd "$ROOT"
rsync -az --partial --progress -e "$SSH" --relative "${FILES[@]}" "$HOST:/opt/landslide/project/"
echo "Uploaded ${#FILES[@]} files. The API caches data in memory: restart it to pick up changes ->"
echo "  $SSH $HOST 'cd /opt/landslide && docker compose restart backend'"
