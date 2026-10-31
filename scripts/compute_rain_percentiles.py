"""Per-tambon 24-hour rainfall percentile thresholds from a 30-year daily record (Earth Engine, CHIRPS).

Why: a fixed "35 mm = heavy" means the same everywhere, but what counts as unusual rain differs between the dry east
coast and the very wet Andaman side. This builds, for every tambon, the rainfall amounts that are exceeded on only 25%,
10%, 5% and 1% of its WET days, so the live forecast can be judged against local climate (the same idea as the per-tambon
P60-P95 thresholds used by national screening tools). Nothing here uses landslide records: the thresholds describe how
unusual the rain is, not whether it triggers landslides.

Method
  * Data: UCSB-CHG/CHIRPS/DAILY (0.05 deg, mm/day), 1991-01-01 .. 2020-12-31 (a standard 30-year climate normal).
  * Each daily image is averaged onto the 0.25 deg (~27.8 km) GFS grid, so the thresholds describe cell-average rainfall
    like the GFS forecast (a point value at 5 km would be far more extreme than a 28 km forecast cell).
  * Wet day = cell-average >= 1 mm. Percentiles P75, P90, P95, P99 of the wet days are taken per cell, sampled at each
    tambon's representative point. The share of all days that are wet is stored too, so "P90 of wet days" can be read
    as "exceeded on about <wet share x 10> % of all days".

Run:   python scripts/compute_rain_percentiles.py            (needs earthengine-api, pandas; Earth Engine credentials)
Output: data/external/rain_percentiles_24h_tambon.csv and rain_percentiles_24h_meta.json
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import ee
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
SERVICE_ACCOUNT_KEY = PROJECT_DIR / "scripts" / "service_account" / "key.json"
TAMBON_POINTS_CSV = PROJECT_DIR / "data" / "boundary" / "southern_thailand_tambon_points.csv"
OUT_CSV = PROJECT_DIR / "data" / "external" / "rain_percentiles_24h_tambon.csv"
OUT_META = PROJECT_DIR / "data" / "external" / "rain_percentiles_24h_meta.json"
START, END = "1991-01-01", "2021-01-01"     # END is exclusive
PERCENTILES = [75, 90, 95, 99]
WET_MM = 1.0
GFS_SCALE_M = 27830
BATCH = 300


def main():
    key = json.loads(SERVICE_ACCOUNT_KEY.read_text())
    ee.Initialize(credentials=ee.ServiceAccountCredentials(key["client_email"], str(SERVICE_ACCOUNT_KEY)),
                  project=os.getenv("GEE_PROJECT") or key["project_id"])

    daily = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterDate(START, END).select("precipitation")
    n_days = daily.size().getInfo()
    print(f"CHIRPS daily images {START}..{END}: {n_days}", flush=True)

    def to_gfs_grid(img):
        return (img.reduceResolution(reducer=ee.Reducer.mean(), maxPixels=1024)
                .reproject(crs="EPSG:4326", scale=GFS_SCALE_M).rename("rain"))

    cells = daily.map(to_gfs_grid)
    wet = cells.map(lambda im: im.updateMask(im.gte(WET_MM)))
    pct = wet.reduce(ee.Reducer.percentile(PERCENTILES))                      # bands rain_p75 .. rain_p99
    wet_share = cells.map(lambda im: im.gte(WET_MM).rename("wet")).mean().rename("wet_day_fraction")
    stack = ee.Image.cat([pct, wet_share])

    tambons = pd.read_csv(TAMBON_POINTS_CSV)
    rows = []
    for i in range(0, len(tambons), BATCH):
        chunk = tambons.iloc[i:i + BATCH]
        pts = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([r.sample_lon, r.sample_lat]), {"GID_3": r.GID_3})
                                    for r in chunk.itertuples()])
        out = stack.reduceRegions(collection=pts, reducer=ee.Reducer.first(), scale=GFS_SCALE_M, tileScale=8).getInfo()
        for f in out["features"]:
            p = f["properties"]
            rows.append({"GID_3": p["GID_3"], **{f"wet_p{q}_mm": p.get(f"rain_p{q}") for q in PERCENTILES},
                         "wet_day_fraction": p.get("wet_day_fraction")})
        print(f"[{min(i + BATCH, len(tambons))}/{len(tambons)}] sampled", flush=True)

    table = tambons[["GID_3", "NAME_3", "NAME_2", "NAME_1"]].merge(pd.DataFrame(rows), on="GID_3", how="left")
    cols = [f"wet_p{q}_mm" for q in PERCENTILES] + ["wet_day_fraction"]
    table[cols] = table[cols].round(3)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT_CSV, index=False)
    OUT_META.write_text(json.dumps({
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": "UCSB-CHG/CHIRPS/DAILY", "period": f"{START} to 2020-12-31", "daily_images": n_days,
        "grid": "0.05 deg daily images averaged onto the 0.25 deg (~27.8 km) GFS grid",
        "wet_day_definition_mm": WET_MM, "percentiles_of_wet_days": PERCENTILES,
        "missing_tambons": int(table[cols[0]].isna().sum()),
        "note": "Percentiles describe how unusual a 24 h rainfall is for each tambon (local climate); they are not "
                "calibrated on landslide records.",
    }, indent=2))
    print(table[cols].describe().round(2).to_string())
    print(f"Saved {OUT_CSV} ({len(table)} tambons, {int(table[cols[0]].isna().sum())} without values)")


if __name__ == "__main__":
    main()
