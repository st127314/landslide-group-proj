"""Live rainfall forecast per tambon from NOAA GFS (Earth Engine), for the live-impact view.

For every tambon sample point this sums GFS forecast rainfall over the next 24 / 48 / 72 hours (counted from now,
not from the model initialisation time) and classifies the 24-hour total two ways:

  * absolute classes (`RAIN_CLASSES` below): light < 10 mm, moderate 10-35, heavy 35-90, very heavy >= 90 mm;
  * local classes: against the tambon's own wet-day rainfall percentiles (P75 / P90 / P95) from 30 years of CHIRPS
    (data/external/rain_percentiles_24h_tambon.csv, built by compute_rain_percentiles.py): below P75, P75-P90,
    P90-P95, above P95. This says how unusual the rain is for that place.

It involves no machine-learning model and no landslide records. Neither set of thresholds is calibrated on this
project's landslide inventory (its dates cannot support a calibration, see docs/METHODS.md), so the result feeds a
transparent triage rule, not a validated landslide forecast. `build_impact_overlay.py` chooses which classes drive the
live impact (`RAIN_BASIS`, default: local percentiles).

How rainfall is computed. The `NOAA/GFS0P25` collection holds one image per forecast hour (hourly to +120 h) with
`precipitation_rate` (kg/m^2/s = mm/s, an instantaneous rate). Each hour's rainfall is approximated as
rate x 3600 s and the hours are summed. GFS cells are 0.25 deg (~28 km), so a tambon gets the value of the cell that
contains its representative point; local convective extremes are smoothed out.

Run:   python scripts/run_live_gfs_forecast.py          (needs earthengine-api, pandas; Earth Engine credentials)
Then:  python3 scripts/build_impact_overlay.py          (joins this with susceptibility and exposure)
Output: results/live_forecast/latest.json
"""

import json
import math
import os
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

import ee
import pandas as pd

socket.setdefaulttimeout(120)

PROJECT_DIR = Path(__file__).resolve().parent.parent
SERVICE_ACCOUNT_KEY = PROJECT_DIR / "scripts" / "service_account" / "key.json"
TAMBON_POINTS_CSV = PROJECT_DIR / "data" / "boundary" / "southern_thailand_tambon_points.csv"
OUTPUT_DIR = PROJECT_DIR / "results" / "live_forecast"
GFS_ASSET = "NOAA/GFS0P25"
WINDOWS_H = (24, 48, 72)
HOURLY_LIMIT_H = 120          # GFS images are hourly up to +120 h on Earth Engine
SAMPLE_BATCH = 400
# 24-hour rainfall classes, in mm: (lower bound inclusive, name). Daily-rainfall categories of this kind are
# widely used; they are ASSUMED thresholds here -- edit as needed.
RAIN_CLASSES = [(0.0, "light"), (10.0, "moderate"), (35.0, "heavy"), (90.0, "very_heavy")]
PERCENTILE_CSV = PROJECT_DIR / "data" / "external" / "rain_percentiles_24h_tambon.csv"
LOCAL_CLASSES = ["below_p75", "p75_p90", "p90_p95", "above_p95"]


def rain_class(mm):
    name = RAIN_CLASSES[0][1]
    for lower, label in RAIN_CLASSES:
        if mm >= lower:
            name = label
    return name


def local_class(mm, p75, p90, p95):
    """Class of a 24 h total against the tambon's own wet-day percentiles; None when no thresholds exist."""
    if mm is None or p75 is None or p90 is None or p95 is None or pd.isna(p75):
        return None
    if mm >= p95:
        return LOCAL_CLASSES[3]
    if mm >= p90:
        return LOCAL_CLASSES[2]
    if mm >= p75:
        return LOCAL_CLASSES[1]
    return LOCAL_CLASSES[0]


def initialize_gee():
    key = json.loads(SERVICE_ACCOUNT_KEY.read_text())
    project = os.getenv("GEE_PROJECT") or key["project_id"]
    ee.Initialize(credentials=ee.ServiceAccountCredentials(key["client_email"], str(SERVICE_ACCOUNT_KEY)),
                  project=project)


def latest_gfs_run(now):
    """Most recent GFS initialisation (creation_time) with forecast images on Earth Engine."""
    window = ee.ImageCollection(GFS_ASSET).filterDate((now - timedelta(days=2)).isoformat(),
                                                      (now + timedelta(days=20)).isoformat())
    creation_ms = window.aggregate_max("creation_time").getInfo()
    run = window.filter(ee.Filter.eq("creation_time", creation_ms))
    return run, datetime.fromtimestamp(creation_ms / 1000, tz=timezone.utc)


def accumulation_image(run, first_hour, last_hour):
    """Sum of hourly rainfall (rate x 3600) over forecast hours first_hour..last_hour, in mm."""
    hours = run.filter(ee.Filter.And(ee.Filter.gte("forecast_hours", first_hour),
                                     ee.Filter.lte("forecast_hours", last_hour)))
    return hours.select("precipitation_rate").map(lambda img: img.multiply(3600)).sum()


def main():
    initialize_gee()
    now = datetime.now(timezone.utc)
    run, init = latest_gfs_run(now)
    # first forecast hour that is still in the future, so "next 24 h" really starts now
    start_hour = max(1, math.ceil((now - init).total_seconds() / 3600))
    if start_hour + max(WINDOWS_H) > HOURLY_LIMIT_H:
        raise SystemExit(f"GFS run {init.isoformat()} is too old: needs hourly steps to +{start_hour + max(WINDOWS_H)} h")
    print(f"GFS run {init.isoformat()} | now {now.isoformat()} | first future forecast hour +{start_hour} h", flush=True)

    bands = [accumulation_image(run, start_hour, start_hour + h - 1).rename(f"rain_{h}h_mm") for h in WINDOWS_H]
    peak = run.filter(ee.Filter.And(ee.Filter.gte("forecast_hours", start_hour),
                                    ee.Filter.lte("forecast_hours", start_hour + WINDOWS_H[0] - 1))
                      ).select("precipitation_rate").map(lambda img: img.multiply(3600)).max().rename("peak_hourly_mm_24h")
    stack = ee.Image.cat(bands + [peak])

    tambons = pd.read_csv(TAMBON_POINTS_CSV)
    rows = []
    for i in range(0, len(tambons), SAMPLE_BATCH):
        chunk = tambons.iloc[i:i + SAMPLE_BATCH]
        points = ee.FeatureCollection([
            ee.Feature(ee.Geometry.Point([r.sample_lon, r.sample_lat]), {"GID_3": r.GID_3}) for r in chunk.itertuples()])
        sampled = stack.reduceRegions(collection=points, reducer=ee.Reducer.first(), scale=27_830, tileScale=4).getInfo()
        for feature in sampled["features"]:
            p = feature["properties"]
            rows.append({"GID_3": p["GID_3"], **{k: p.get(k) for k in
                         [f"rain_{h}h_mm" for h in WINDOWS_H] + ["peak_hourly_mm_24h"]}})
        print(f"[{min(i + SAMPLE_BATCH, len(tambons))}/{len(tambons)}] sampled", flush=True)

    values = pd.DataFrame(rows).set_index("GID_3")
    pctl = pd.read_csv(PERCENTILE_CSV).set_index("GID_3") if PERCENTILE_CSV.exists() else None
    if pctl is None:
        print(f"WARNING: {PERCENTILE_CSV.name} not found; local percentile classes will be empty "
              "(run scripts/compute_rain_percentiles.py)", flush=True)
    results = []
    for r in tambons.itertuples():
        v = values.loc[r.GID_3]
        mm = {k: (None if pd.isna(v[k]) else round(max(0.0, float(v[k])), 2)) for k in values.columns}
        r24 = mm["rain_24h_mm"]
        th = pctl.loc[r.GID_3] if pctl is not None and r.GID_3 in pctl.index else None
        p75, p90, p95 = ((float(th["wet_p75_mm"]), float(th["wet_p90_mm"]), float(th["wet_p95_mm"])) if th is not None
                         else (None, None, None))
        results.append({
            "GID_3": r.GID_3, "NAME_3": r.NAME_3 if isinstance(r.NAME_3, str) else None,
            "NAME_2": r.NAME_2, "NAME_1": r.NAME_1, "lon": r.sample_lon, "lat": r.sample_lat,
            "gfs_rain_24h_mm": r24, "gfs_rain_48h_mm": mm["rain_48h_mm"], "gfs_rain_72h_mm": mm["rain_72h_mm"],
            "gfs_peak_hourly_mm_24h": mm["peak_hourly_mm_24h"],
            "rain_class_24h": rain_class(r24) if r24 is not None else "no_data",
            "local_p75_mm": p75, "local_p90_mm": p90, "local_p95_mm": p95,
            "rain_local_class_24h": local_class(r24, p75, p90, p95) or "no_data",
        })

    counts = pd.Series([t["rain_class_24h"] for t in results]).value_counts().to_dict()
    local_counts = pd.Series([t["rain_local_class_24h"] for t in results]).value_counts().to_dict()
    r24s = sorted(t["gfs_rain_24h_mm"] for t in results if t["gfs_rain_24h_mm"] is not None)
    out = {
        "generated_utc": now.isoformat(),
        "gfs_run_utc": init.isoformat(),
        "window_start_utc": (init + timedelta(hours=start_hour)).isoformat(),
        "window_24h_end_utc": (init + timedelta(hours=start_hour + 24)).isoformat(),
        "window_72h_end_utc": (init + timedelta(hours=start_hour + 72)).isoformat(),
        "forecast_hours_used": {"first": start_hour, "last_24h": start_hour + 23, "last_72h": start_hour + 71},
        "rain_classes_mm_24h": [{"class": name, "from_mm": lower} for lower, name in RAIN_CLASSES],
        "local_classes": {"names": LOCAL_CLASSES, "thresholds_file": "data/external/rain_percentiles_24h_tambon.csv",
                          "meaning": "24 h forecast vs the tambon's own wet-day (>= 1 mm) 24 h rainfall percentiles P75/P90/P95, "
                                     "CHIRPS 1991-2020 averaged onto the 0.25 deg GFS grid"},
        "summary": {"tambons": len(results), "tambons_by_class_24h": counts, "tambons_by_local_class_24h": local_counts,
                    "max_24h_mm": r24s[-1] if r24s else None, "median_24h_mm": r24s[len(r24s) // 2] if r24s else None},
        "method": "Sum over forecast hours of GFS precipitation_rate x 3600 s from the first future forecast hour; "
                  "value of the 0.25 deg cell containing each tambon's representative point; the 24 h total is "
                  "classed against fixed mm thresholds and against the tambon's wet-day rainfall percentiles.",
        "limitations": [
            "GFS is a global weather model on a 0.25 degree (~28 km) grid: local convective extremes are smoothed, "
            "and any single forecast run can be wrong in timing and amount.",
            "Hourly rainfall is approximated as the instantaneous rate at each forecast hour x 3600 s.",
            "The rainfall classes (absolute mm and local percentiles) are not calibrated on landslide records (this "
            "project's inventory dates are satellite-image dates and cannot support a calibration). Local percentiles "
            "say how unusual the rain is for the place, not whether it triggers landslides. The live-impact class is "
            "a transparent triage rule, not a validated landslide forecast.",
            "Local percentiles come from CHIRPS (observed) while the forecast is GFS (model): GFS has its own biases, "
            "so the two are only roughly comparable.",
        ],
        "tambons": results,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "latest.json"
    partial = path.with_suffix(".json.part")   # atomic write: the API reads this file on every request
    partial.write_text(json.dumps(out, indent=2))
    partial.replace(path)
    print(f"Saved {path}: {len(results)} tambons, 24 h classes {counts}, max {out['summary']['max_24h_mm']} mm")


if __name__ == "__main__":
    main()
