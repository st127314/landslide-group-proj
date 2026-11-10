"""Re-apply the live impact rule to an existing impact overlay with the latest GFS forecast.

build_impact_overlay.py does the heavy part once: snapping 426k buildings, 3,895 facilities and the WorldPop raster to
the 250 m grid (geopandas, GDAL, ~1.5 GB of RAM). None of that changes between forecasts, and the per-tambon results
(terrain tier, exposure counts) are already stored in impact_overlay.json. This script only swaps in the new rainfall
and recomputes the impact class, the people/buildings/facilities at elevated risk, the province roll-up and the totals,
so it runs in seconds with pandas on the small server (apps/deploy: the `forecast` job).

The rule matches build_impact_overlay.py and apps/backend/app/scenario.py; keep the three identical.

Run after run_live_gfs_forecast.py:  python scripts/refresh_impact_overlay.py
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
LIVE_PATH = PROJECT_DIR / "results" / "live_forecast" / "latest.json"
OVERLAY_PATH = PROJECT_DIR / "results" / "impact_overlay" / "impact_overlay.json"

TIER_FACTOR = {"low": 1, "moderate": 2, "high": 3}
RAIN_INDEX = {"light": 0, "moderate": 1, "heavy": 2, "very_heavy": 3}                  # rain_basis "fixed"
LOCAL_INDEX = {"below_p75": 0, "p75_p90": 1, "p90_p95": 2, "above_p95": 3}              # rain_basis "percentile"
HIGH_CLASSES = ("high", "very_high")
IMPACT_ORDER = ["very_high", "high", "moderate", "low", "not_assessed"]
RAIN_COLUMNS = ["gfs_rain_24h_mm", "gfs_rain_48h_mm", "gfs_rain_72h_mm", "gfs_peak_hourly_mm_24h", "rain_class_24h",
                "local_p75_mm", "local_p90_mm", "local_p95_mm", "rain_local_class_24h"]
PROVINCE_SUMS = ["area_km2", "buildings_total", "buildings_high_vh", "population_total", "population_high_vh",
                 "facilities_total", "facilities_high_vh", "critical_facilities_total", "critical_facilities_high_vh",
                 "population_at_elevated_risk", "buildings_at_elevated_risk", "facilities_at_elevated_risk"]


def impact_class(tier, rain_index):
    if tier not in TIER_FACTOR or pd.isna(rain_index):
        return "not_assessed"
    product = TIER_FACTOR[tier] * rain_index
    return "low" if product <= 1 else "moderate" if product <= 3 else "high" if product <= 6 else "very_high"


def refresh(overlay, live):
    meta = overlay["metadata"]
    out = pd.DataFrame(overlay["tambons"]).set_index("GID_3")
    forecast = pd.DataFrame(live["tambons"]).set_index("GID_3")
    out = out.drop(columns=[c for c in RAIN_COLUMNS if c in out.columns])
    out = out.join(forecast[[c for c in RAIN_COLUMNS if c in forecast.columns]])

    if meta.get("rain_basis", "percentile") == "percentile":
        rain_idx = out["rain_local_class_24h"].map(LOCAL_INDEX)
    else:
        rain_idx = out["rain_class_24h"].map(RAIN_INDEX)
    out["live_impact_class"] = [impact_class(t, r) for t, r in zip(out["susceptibility_tier"], rain_idx)]
    elevated = out["live_impact_class"].isin(HIGH_CLASSES)
    for kind in ("population", "buildings", "facilities"):
        out[f"{kind}_at_elevated_risk"] = out[f"{kind}_high_vh"].where(elevated, 0)

    out = out.reset_index()
    rank = out["live_impact_class"].map({c: i for i, c in enumerate(IMPACT_ORDER)})
    out = out.assign(_r=rank).sort_values(["_r", "population_at_elevated_risk", "gfs_rain_24h_mm", "population_high_vh", "GID_3"],
                                          ascending=[True, False, False, False, True]).drop(columns="_r")

    sums = [c for c in PROVINCE_SUMS if c in out.columns]
    prov = out.groupby("NAME_1")[sums].sum()
    prov["tambons"] = out.groupby("NAME_1").size()
    prov["tambons_live_impact_high_or_above"] = out[out["live_impact_class"].isin(HIGH_CLASSES)] \
        .groupby("NAME_1").size().reindex(prov.index).fillna(0).astype(int)
    prov["max_rain_24h_mm"] = out.groupby("NAME_1")["gfs_rain_24h_mm"].max().round(1)
    prov["pct_population_in_high_vh"] = (100 * prov["population_high_vh"] / prov["population_total"]).round(1)
    prov = prov.reset_index().sort_values("population_high_vh", ascending=False)

    totals = dict(meta.get("totals", {}))
    for key in ("population_at_elevated_risk", "buildings_at_elevated_risk", "facilities_at_elevated_risk"):
        totals[key] = int(out[key].sum())
    totals["tambons_by_live_impact_class"] = out["live_impact_class"].value_counts().to_dict()
    totals["tambons_by_rain_class_24h"] = out["rain_class_24h"].value_counts().to_dict()
    totals["tambons_by_rain_local_class_24h"] = out["rain_local_class_24h"].value_counts().to_dict()

    meta = {**meta,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "forecast_generated_utc": live.get("generated_utc"),
            "gfs_run_utc": live.get("gfs_run_utc"),
            "forecast_window_start_utc": live.get("window_start_utc"),
            "forecast_window_24h_end_utc": live.get("window_24h_end_utc"),
            "forecast_window_72h_end_utc": live.get("window_72h_end_utc"),
            "rain_classes_mm_24h": live.get("rain_classes_mm_24h"),
            "rain_local_classes": live.get("local_classes", meta.get("rain_local_classes")),
            "totals": totals}
    return {"metadata": meta,
            "tambons": json.loads(out.round(4).to_json(orient="records")),
            "provinces": json.loads(prov.round(2).to_json(orient="records"))}


def main():
    overlay = json.loads(OVERLAY_PATH.read_text())
    live = json.loads(LIVE_PATH.read_text())
    result = refresh(overlay, live)
    # Write then rename, so the API never reads a half-written file.
    tmp = OVERLAY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=1))
    tmp.replace(OVERLAY_PATH)
    totals = result["metadata"]["totals"]
    print(f"Refreshed {OVERLAY_PATH.relative_to(PROJECT_DIR)} for GFS run {live.get('gfs_run_utc')}: "
          f"{totals['tambons_by_live_impact_class']}, {totals['population_at_elevated_risk']:,} people at elevated risk")


if __name__ == "__main__":
    main()
