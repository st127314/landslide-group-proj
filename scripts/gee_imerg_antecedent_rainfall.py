"""Sample IMERG V07 antecedent rainfall at event points; write a separate CSV.

Run: python scripts/gee_imerg_antecedent_rainfall.py
Settings are below. No raster exports or changes to the conditioning-factor CSV.
"""

import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import time
from zoneinfo import ZoneInfo

import ee

# The GEE client has no built-in request timeout; a stalled connection can
# otherwise hang getInfo() forever instead of raising for the retry loop below
# to catch. This bounds every blocking socket call in the process.
socket.setdefaulttimeout(120)

PROJECT_DIR = Path(__file__).resolve().parent.parent
SERVICE_ACCOUNT_KEY = PROJECT_DIR / "scripts/service_account/key.json"
GEE_PROJECT = os.getenv("GEE_PROJECT")
EVENTS_PATH = PROJECT_DIR / "data/inventory/landslide_inventory.geojson"
OUTPUT_CSV = PROJECT_DIR / "data/processed/landslide_event_antecedent_rainfall.csv"
CACHE_DIR = PROJECT_DIR / "cache/imerg_cache"
IMERG_ASSET = "NASA/GPM_L3/IMERG_V07"
IMERG_BAND = "precipitation"  # mm/hour, each image represents a 30-minute interval.
IMERG_STATUS = "permanent"  # Final/reprocessed data for retrospective modelling.
EVENT_TIMEZONE = "Asia/Bangkok"
TIME_MODE = "start_of_day"  # "recorded" or "start_of_day".
EVENT_TIMES_CONFIRMED = False  # Inventory times (07:00) are placeholders, not failure times.
STEP_SECONDS = 1800
WINDOWS = [(f"{hours}h", hours) for hours in (1, 3, 6)] + [
    (f"{days}d", days * 24) for days in range(1, 31)]
# Per-point resilience: a point that keeps failing (rate limit, transient
# network error, no IMERG coverage) is retried, then skipped -- never aborts
# the whole run. Mirrors gee_landslide_factors.py's batch retry policy.
POINT_RETRY_ATTEMPTS = 4
POINT_RETRY_BACKOFF_SECONDS = 5


def initialize_gee():
    with SERVICE_ACCOUNT_KEY.open() as handle:
        key = json.load(handle)
    if key.get("type") != "service_account":
        raise ValueError("Expected a service-account JSON key.")
    project = GEE_PROJECT or key.get("project_id")
    if not project:
        raise ValueError("Set GEE_PROJECT.")
    # Pass email explicitly: older earthengine-api (e.g. 1.5.7) requires it as
    # a positional arg even with key_file set; newer versions accept either.
    ee.Initialize(credentials=ee.ServiceAccountCredentials(key["client_email"], str(SERVICE_ACCOUNT_KEY)),
                  project=project)


def event_cutoff(properties):
    """Interpret slash dates as day/month/year and explicitly localize to Thailand."""
    if TIME_MODE not in {"recorded", "start_of_day"}:
        raise ValueError("TIME_MODE must be recorded or start_of_day.")
    value = properties.get("DATE") or properties.get("date_parsed") or properties.get("date")
    if not isinstance(value, str):
        raise ValueError("Missing event DATE/date_parsed/date.")
    parsed = None
    has_time = False
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            has_time = "%H" in fmt
            break
        except ValueError:
            pass
    if parsed is None:
        raise ValueError(f"Invalid event date: {value!r}")
    if TIME_MODE == "start_of_day":
        parsed = parsed.replace(hour=0, minute=0, second=0)
        quality = "start_of_day_proxy"
    elif not has_time:
        raise ValueError("Recorded-time mode requires an event time; use start_of_day explicitly.")
    else:
        quality = "confirmed_event_time" if EVENT_TIMES_CONFIRMED else "recorded_time_unverified"
    local = parsed.replace(tzinfo=ZoneInfo(EVENT_TIMEZONE))
    utc = local.astimezone(timezone.utc)
    # Never include a half-hour interval extending beyond the event time.
    aligned = datetime.fromtimestamp(
        int(utc.timestamp()) // STEP_SECONDS * STEP_SECONDS, timezone.utc)
    return local, aligned, quality


def event_identifier(properties, index):
    return properties.get("Event_ID") or properties.get("inventory_id") or f"row-{index}"


def load_events():
    document = json.loads(EVENTS_PATH.read_text())
    if document.get("type") != "FeatureCollection":
        raise ValueError("Expected an event GeoJSON FeatureCollection.")
    events = []
    for index, feature in enumerate(document.get("features", [])):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            raise ValueError(f"Event {index} requires Point geometry.")
        lon, lat = geometry["coordinates"][:2]
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"Event {index} has invalid coordinates.")
        properties = feature.get("properties") or {}
        local, end, quality = event_cutoff(properties)
        events.append((index, properties, lon, lat, local, end, quality))
    if not events:
        raise ValueError("No event points found.")
    return events


def imerg_collection():
    collection = ee.ImageCollection(IMERG_ASSET)
    if IMERG_STATUS:
        collection = collection.filter(ee.Filter.eq("status", IMERG_STATUS))
    return collection.select(IMERG_BAND)


def fetch_series(lon, lat, end, projection):
    """Fetch the containing native IMERG grid cell; cache for resumable runs."""
    start = end - timedelta(days=30)
    request = {"asset": IMERG_ASSET, "band": IMERG_BAND, "status": IMERG_STATUS,
               "longitude": lon, "latitude": lat, "start": start.isoformat(),
               "end": end.isoformat(), "projection": projection}
    key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())["rows"]
    collection = imerg_collection().filterDate(start.isoformat(), end.isoformat()).sort("system:time_start")
    region_rows = collection.getRegion(ee.Geometry.Point([lon, lat]), crs=projection["crs"],
                                       crsTransform=projection["transform"])
    rows_query = ee.List(ee.Algorithms.If(collection.size().gt(0), region_rows,
        [["id", "longitude", "latitude", "time", IMERG_BAND]]))
    last_exc = None
    for attempt in range(1, POINT_RETRY_ATTEMPTS + 1):
        try:
            rows = rows_query.getInfo()
            break
        except Exception as exc:
            last_exc = exc
            if attempt < POINT_RETRY_ATTEMPTS:
                print(f"  getRegion failed on attempt {attempt}/{POINT_RETRY_ATTEMPTS} ({exc}); retrying...",
                      flush=True)
                time.sleep(POINT_RETRY_BACKOFF_SECONDS * attempt)
    else:
        raise last_exc
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.write_text(json.dumps({"request": request,
                                  "retrieved_utc": datetime.now(timezone.utc).isoformat(),
                                  "rows": rows}, allow_nan=False))
    partial.replace(path)
    return rows


def accumulate_windows(rows, end):
    """Integrate mm/hour × 0.5 hours; missing intervals never count as zero rain."""
    by_time = {}
    if rows:
        header, *records = rows
        time_index = header.index("time")
        rain_index = header.index(IMERG_BAND)
        for record in records:
            timestamp = int(record[time_index])
            if timestamp in by_time:
                raise ValueError(f"Duplicate IMERG timestep {timestamp}; refusing to double count.")
            if timestamp % (STEP_SECONDS * 1000):
                raise ValueError("Unexpected IMERG timestamp alignment.")
            rate = record[rain_index]
            by_time[timestamp] = (float(rate) if isinstance(rate, (int, float))
                                  and math.isfinite(rate) and rate >= 0 else None)
    end_ms = int(end.timestamp() * 1000)
    totals = {}
    for label, hours in WINDOWS:
        expected = hours * 2
        timestamps = range(end_ms - expected * STEP_SECONDS * 1000,
                           end_ms, STEP_SECONDS * 1000)
        values = [by_time.get(t) for t in timestamps]
        valid = [value for value in values if value is not None]
        totals[f"rain_{label}_mm"] = math.fsum(valid) * 0.5 if len(valid) == expected else None
        totals[f"rain_{label}_coverage_pct"] = round(100 * len(valid) / expected, 4)
    return totals


def load_completed_rows(path):
    """Read event_row indices already written by a prior (interrupted) run."""
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return {int(row["event_row"]) for row in reader if row.get("event_row", "").strip()}


def keep_successful_rows(source, target):
    """Rewrite `target` with only the rows of `source` that did not end in an error, so points that
    failed (credentials, quota, network) are retried on resume instead of being counted as done.
    Returns the event_row indices that were kept."""
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = [row for row in reader
                if row.get("event_row", "").strip() and row.get("rainfall_status") != "error"]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return {int(row["event_row"]) for row in rows}


MAX_CONSECUTIVE_ERRORS = 5  # stop instead of burning through every remaining point on a broken key/network


def main():
    events = load_events()  # Validate every date and coordinate before starting requests.
    if TIME_MODE == "recorded" and not EVENT_TIMES_CONFIRMED:
        print("Using recorded local times, flagged unverified. Current inventory times are all 07:00.")
    fields = ["event_row", "Event_ID", "DATE", "date_parsed", "inventory_id", "date",
              "longitude", "latitude", "event_time_local", "rainfall_cutoff_utc",
              "cutoff_shift_minutes", "time_quality", "imerg_asset", "imerg_status",
              "rainfall_status", "error"]
    fields += [name for label, _ in WINDOWS for name in
               (f"rain_{label}_mm", f"rain_{label}_coverage_pct")]
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    partial = OUTPUT_CSV.with_suffix(".csv.part")
    # Resume from whichever of the two (a completed prior run, or an
    # interrupted run's partial file) has progress, so restarting after a
    # crash/interruption never re-fetches points already saved to disk.
    resume_source = partial if partial.exists() else (OUTPUT_CSV if OUTPUT_CSV.exists() else None)
    completed = set()
    if resume_source:
        completed = keep_successful_rows(resume_source, partial.with_suffix(".tmp"))
        partial.with_suffix(".tmp").replace(partial)  # error rows dropped: they are retried below
        if completed:
            print(f"Resuming: {len(completed)} of {len(events)} events already saved in {resume_source}; "
                  "skipping those (rows that previously failed are retried).", flush=True)

    initialize_gee()
    projection = imerg_collection().first().select(IMERG_BAND).projection().getInfo()
    mode = "a" if completed else "w"
    with partial.open(mode, newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not completed:
            writer.writeheader()
        consecutive_errors = 0
        for index, properties, lon, lat, local, end, quality in events:
            if index in completed:
                continue
            base = {"event_row": index, "Event_ID": properties.get("Event_ID"),
                     "DATE": properties.get("DATE"), "date_parsed": properties.get("date_parsed"),
                     "inventory_id": properties.get("inventory_id"), "date": properties.get("date"),
                     "longitude": lon, "latitude": lat, "event_time_local": local.isoformat(),
                     "rainfall_cutoff_utc": end.isoformat(),
                     "cutoff_shift_minutes": (local.astimezone(timezone.utc)-end).total_seconds()/60,
                     "time_quality": quality, "imerg_asset": IMERG_ASSET,
                     "imerg_status": IMERG_STATUS or "all"}
            identifier = event_identifier(properties, index)
            try:
                rows = fetch_series(lon, lat, end, projection)
                totals = accumulate_windows(rows, end)
                complete = all(totals[f"rain_{label}_mm"] is not None for label, _ in WINDOWS)
                record = {**base, "rainfall_status": "complete" if complete else "incomplete",
                          "error": "", **totals}
                status = record["rainfall_status"]
            except Exception as exc:
                record = {**base, "rainfall_status": "error", "error": str(exc)}
                status = f"ERROR ({exc})"
            writer.writerow(record)
            handle.flush()
            print(f"[{index+1}/{len(events)}] Event {identifier}: {status}", flush=True)
            consecutive_errors = consecutive_errors + 1 if record["rainfall_status"] == "error" else 0
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"Stopping after {consecutive_errors} consecutive errors (credentials, quota or network?). "
                      f"Everything fetched so far is saved in {partial}; fix the problem and re-run the same "
                      "command to resume.", flush=True)
                raise SystemExit(2)
    partial.replace(OUTPUT_CSV)
    print(f"Saved {len(events)} event rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
