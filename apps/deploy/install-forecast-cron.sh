#!/usr/bin/env bash
# Run LOCALLY once: uploads the Earth Engine service-account key to the server and installs the cron entry that
# refreshes the live forecast and impact overlay every 3 hours (the `forecast` job in docker-compose.yml).
#   apps/deploy/install-forecast-cron.sh <ssh-key> <user@host> [gee-key.json]
# The GEE key defaults to scripts/service_account/key.json and goes to /opt/landslide/secrets/gee_key.json (mode 600).
set -euo pipefail
KEY="${1:?usage: install-forecast-cron.sh <ssh-key> <user@host> [gee-key.json]}"
HOST="${2:?usage: install-forecast-cron.sh <ssh-key> <user@host> [gee-key.json]}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GEE_KEY="${3:-$ROOT/scripts/service_account/key.json}"
SSH="ssh -i $KEY -o IdentitiesOnly=yes ${SSH_EXTRA:-}"

$SSH "$HOST" 'install -m 700 -d /opt/landslide/secrets && umask 077 && cat > /opt/landslide/secrets/gee_key.json' < "$GEE_KEY"
# GFS runs appear in Earth Engine a few hours after 00/06/12/18 UTC; every 3 hours always picks up the newest one.
$SSH "$HOST" 'line="20 */3 * * * cd /opt/landslide && docker compose --profile jobs run --rm forecast > /opt/landslide/forecast.log 2>&1"
  { crontab -l 2>/dev/null | grep -v "compose --profile jobs run --rm forecast" || true; echo "$line"; } | crontab -
  crontab -l | grep forecast'
echo "Run it once now:  $SSH $HOST 'cd /opt/landslide && docker compose --profile jobs run --rm forecast'"
