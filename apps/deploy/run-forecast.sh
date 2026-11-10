#!/usr/bin/env bash
# Runs ON THE SERVER (from cron, every 3 hours): refreshes the GFS forecast and the live impact overlay, and falls back to
# the last good copies if anything goes wrong, so the dashboard never shows a half-updated or empty forecast.
#
#   1. snapshot the current latest.json + impact_overlay.json
#   2. run the `forecast` job (up to ATTEMPTS times, each limited to LIMIT seconds; Earth Engine fails now and then)
#   3. accept the result only if both files are complete, agree on the GFS run and are not older than the snapshot
#   4. otherwise put the snapshot back (the API keeps serving the previous forecast, dated as such) and exit non-zero
#
# Log: /opt/landslide/forecast.log (appended; LANDSLIDE_DIR overrides the install directory for tests).  Marker files: forecast.last_ok / forecast.last_failed (timestamp + reason).
set -uo pipefail
APP="${LANDSLIDE_DIR:-/opt/landslide}"
cd "$APP"

RESULTS="${DATA_ROOT:-$APP/project}/results"
LIVE="$RESULTS/live_forecast/latest.json"
OVERLAY="$RESULTS/impact_overlay/impact_overlay.json"
SNAP="$APP/forecast-last-good"
LOG="$APP/forecast.log"
ATTEMPTS="${ATTEMPTS:-3}"
WAIT="${WAIT:-300}"          # seconds between attempts
LIMIT="${LIMIT:-900}"        # seconds one attempt may take

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }

# Never two runs at once (a slow run must not collide with the next cron start).
if command -v flock >/dev/null 2>&1; then
  exec 9> "$APP/forecast.lock"
  flock -n 9 || { log "another forecast run is still going; skipping"; exit 0; }
else
  log "flock not installed: running without the overlap guard"
fi

# Prints the GFS run when both files are complete and consistent, else a reason on stderr and exit 1.
check() {
  python3 - "$LIVE" "$OVERLAY" <<'PY'
import json, sys
try:
    live = json.load(open(sys.argv[1])); overlay = json.load(open(sys.argv[2]))
    run = live["gfs_run_utc"]
    n = len(live["tambons"])
    assert n >= 1000, f"only {n} tambons in the forecast"
    assert len(overlay["tambons"]) == n, f"overlay has {len(overlay['tambons'])} tambons, forecast {n}"
    assert overlay["metadata"]["gfs_run_utc"] == run, "overlay and forecast are from different GFS runs"
    assert any(t.get("gfs_rain_24h_mm") is not None for t in live["tambons"]), "no rainfall values"
    print(run)
except Exception as exc:  # noqa: BLE001 - report any problem as a failed check
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr); sys.exit(1)
PY
}

restore() {
  [ -f "$SNAP/latest.json" ] && [ -f "$SNAP/impact_overlay.json" ] || { log "no snapshot to restore"; return 1; }
  cp -p "$SNAP/latest.json" "$LIVE.restore" && mv "$LIVE.restore" "$LIVE"
  cp -p "$SNAP/impact_overlay.json" "$OVERLAY.restore" && mv "$OVERLAY.restore" "$OVERLAY"
}

before=$(check 2>/dev/null) || before=""
if [ -n "$before" ]; then
  mkdir -p "$SNAP" && cp -p "$LIVE" "$SNAP/latest.json" && cp -p "$OVERLAY" "$SNAP/impact_overlay.json"
  log "start: serving GFS run $before"
else
  log "start: the files being served are missing or inconsistent ($(check 2>&1 >/dev/null | head -1))"
fi

reason="not started"
for attempt in $(seq 1 "$ATTEMPTS"); do
  log "attempt $attempt/$ATTEMPTS"
  if timeout "$LIMIT" docker compose --profile jobs run --rm forecast >> "$LOG" 2>&1; then
    after=$(check 2>&1) && {
      if [ -n "$before" ] && [[ "$after" < "$before" ]]; then
        reason="new GFS run $after is older than the one being served ($before)"
      else
        log "OK: now serving GFS run $after"
        date -u +%FT%TZ > "$APP/forecast.last_ok"
        rm -f "$APP/forecast.last_failed"
        exit 0
      fi
    } || reason="result failed the check: $after"
  else
    reason="job exited with status $? (timeout is $LIMIT s)"
  fi
  log "attempt $attempt failed: $reason"
  [ "$attempt" -lt "$ATTEMPTS" ] && sleep "$WAIT"
done

# Every attempt failed: fall back to the previous forecast and overlay.
if [ -n "$before" ] && restore; then
  log "FALLBACK: kept GFS run $before after $ATTEMPTS failed attempts ($reason)"
else
  log "FAILED with no good previous forecast to fall back to ($reason)"
fi
printf '%s %s\n' "$(date -u +%FT%TZ)" "$reason" > "$APP/forecast.last_failed"
exit 1
