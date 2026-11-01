#!/usr/bin/env bash
# Pack the 426k OSM building footprints into one PMTiles vector-tile archive for the web map.
#
# The GeoJSON (~147 MB) needs ~1.4 GB of RAM to serve by bounding box, which the small server cannot spare. A
# PMTiles file is read with HTTP range requests: the browser fetches only the tiles in view and the API just
# streams byte ranges of one file (/api/impact/buildings.pmtiles).
#
# Zoom 12-15 (buildings are invisible below 12); tippecanoe adds deeper zooms if dense areas would still drop
# footprints. Only `type` and `name` are kept for the map pop-up.
#
# Run after download_external_data.py:  scripts/make_buildings_tiles.sh   (needs tippecanoe >= 2.17: brew install tippecanoe)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
tippecanoe -q --force -o "$ROOT/data/external/buildings.pmtiles" -l buildings -Z12 -z15 \
  -y type -y name --drop-densest-as-needed --extend-zooms-if-still-dropping \
  "$ROOT/data/external/buildings_aoi.geojson"
ls -lh "$ROOT/data/external/buildings.pmtiles"
