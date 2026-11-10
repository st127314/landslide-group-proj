#!/usr/bin/env bash
# Run LOCALLY once: uploads the Earth Engine service-account key to the server and installs the cron entry (every 3 h) that
# refreshes the live forecast and impact overlay (run-forecast.sh: retries, checks the result, falls back to the last
# good forecast if the run fails).
#   apps/deploy/install-forecast-cron.sh <ssh-key> <user@host> [gee-key.json]
# The GEE key defaults to scripts/service_account/key.json and goes to /opt/landslide/secrets/gee_key.json (mode 600).
# It is copied over SSH only; it is never committed or put in an image.
set -euo pipefail
KEY="${1:?usage: install-forecast-cron.sh <ssh-key> <user@host> [gee-key.json]}"
HOST="${2:?usage: install-forecast-cron.sh <ssh-key> <user@host> [gee-key.json]}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GEE_KEY="${3:-$ROOT/scripts/service_account/key.json}"
SSH="ssh -i $KEY -o IdentitiesOnly=yes ${SSH_EXTRA:-}"
SCP="scp -i $KEY -o IdentitiesOnly=yes ${SSH_EXTRA:-}"
# Every 3 hours at :20 UTC. GFS issues runs at 00/06/12/18 UTC and Earth Engine has each a few hours later, so the
# dashboard picks up every new run within 3 hours of it appearing and the 5-day windows always start from "now".
CRON_SCHEDULE="${CRON_SCHEDULE:-20 */3 * * *}"

$SSH "$HOST" 'install -m 700 -d /opt/landslide/secrets && umask 077 && cat > /opt/landslide/secrets/gee_key.json' < "$GEE_KEY"
$SCP "$ROOT/apps/deploy/run-forecast.sh" "$HOST:/opt/landslide/run-forecast.sh"
$SSH "$HOST" "chmod +x /opt/landslide/run-forecast.sh
  [ \"\$(date +%Z)\" = UTC ] || echo 'WARNING: the server clock is not UTC; the cron time shifts accordingly' >&2
  line='$CRON_SCHEDULE /opt/landslide/run-forecast.sh'
  { crontab -l 2>/dev/null | grep -vE 'run-forecast.sh|compose --profile jobs run --rm forecast' || true; echo \"\$line\"; } | crontab -
  crontab -l | grep run-forecast"
echo "Run it once now:  $SSH $HOST '/opt/landslide/run-forecast.sh; tail -20 /opt/landslide/forecast.log'"
