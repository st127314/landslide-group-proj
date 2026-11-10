"""Live impact overlay: terrain susceptibility x GFS forecast rainfall x exposure, per tambon.

Joins three finished products:

  1. Terrain susceptibility  -- 250 m scored grid (predict_susceptibility_grid.py; hold-out ROC-AUC 0.94)
  2. Forecast rainfall       -- NOAA GFS 24 / 48 / 72 h totals per tambon (run_live_gfs_forecast.py)
  3. Exposure                -- OSM building footprints, OSM critical facilities and the WorldPop 2020
                                constrained population raster

Every exposure item (building centroid, facility point, populated 100 m pixel) inherits the susceptibility class of
its nearest 250 m grid cell (within MAX_SNAP_M); items with no cell that close (sea, outside the grid) are counted in
the totals but not in any susceptibility class.

Live impact class (a transparent triage rule, NOT a calibrated probability): the tambon's terrain factor (1 / 2 / 3 for
a low / moderate / high tier, from the share of its cells classed high/very_high) MULTIPLIED by the index (0..3) of its
24 h rainfall class, binned by impact_class_from_product() below (0-1 low, 2-3 moderate, 4-6 high, >= 7 very high). A
product, not a sum: rain alone creates no risk on terrain that cannot slide, and "very high" needs steep terrain AND rain
above the tambon's P95. RAIN_BASIS chooses the rainfall classes: "percentile" (default) = the forecast against the tambon's
own wet-day rainfall percentiles (below P75, P75-P90, P90-P95, above P95; CHIRPS 1991-2020), "fixed" = absolute mm
classes (light / moderate / heavy / very heavy). Neither is calibrated on landslide records; see docs/METHODS.md.

"People at elevated risk" = people living in high/very-high susceptibility cells of tambons whose live impact class
is high or very_high.

Run (needs geopandas, scipy and GDAL):
    python3 scripts/build_impact_overlay.py
Outputs go to results/impact_overlay/.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from osgeo import gdal
from scipy.spatial import cKDTree

gdal.UseExceptions()

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
RESULTS_DIR = PROJECT_DIR / "results"

TAMBONS_PATH = DATA_DIR / "boundary" / "southern_thailand_tambons.geojson"
GRID_PATH = RESULTS_DIR / "susceptibility_map" / "susceptibility_grid_points.csv"
LIVE_PATH = RESULTS_DIR / "live_forecast" / "latest.json"
BUILDINGS_PATH = DATA_DIR / "external" / "buildings_aoi.geojson"
FACILITIES_PATH = DATA_DIR / "external" / "facilities_aoi.geojson"
POPULATION_PATH = DATA_DIR / "external" / "worldpop_2020_UNadj_constrained_aoi.tif"
OUTPUT_DIR = RESULTS_DIR / "impact_overlay"

HIGH_CLASSES = ("high", "very_high")
CLASS_ORDER = ["very_low", "low", "moderate", "high", "very_high"]
MAX_SNAP_M = 400.0  # just over one 250 m cell diagonal (~354 m), to tolerate cell-centre offsets

# Susceptibility tier from % of a tambon's grid cells that are high/very_high.
TIER_BREAKS = [15.0, 40.0]  # <15 % -> 0 (low), 15-40 % -> 1 (moderate), >=40 % -> 2 (high)
TIER_NAMES = ["low", "moderate", "high"]
# terrain factor (1-3) x 24 h rain-class index (0-3) -> live impact class (keep apps/backend/app/scenario.py identical)
TIER_FACTOR = {"low": 1, "moderate": 2, "high": 3}


def impact_class_from_product(product):
    if pd.isna(product):
        return "not_assessed"
    return "low" if product <= 1 else "moderate" if product <= 3 else "high" if product <= 6 else "very_high"
RAIN_INDEX = {"light": 0, "moderate": 1, "heavy": 2, "very_heavy": 3}                  # RAIN_BASIS = "fixed"
LOCAL_INDEX = {"below_p75": 0, "p75_p90": 1, "p90_p95": 2, "above_p95": 3}              # RAIN_BASIS = "percentile"
RAIN_BASIS = "percentile"   # or "fixed"
IMPACT_ORDER = ["very_high", "high", "moderate", "low", "not_assessed"]

FACILITY_CATEGORY = {
    **dict.fromkeys(["hospital", "clinic", "doctors", "pharmacy", "dentist", "nursing_home", "veterinary"], "health"),
    **dict.fromkeys(["school", "kindergarten", "college", "university"], "education"),
    **dict.fromkeys(["police", "fire_station", "courthouse"], "emergency_government"),
    **dict.fromkeys(["railway_station", "railway_halt", "bus_station", "ferry_terminal", "airport"], "transport"),
    **dict.fromkeys(["buddhist", "muslim", "muslim_sunni", "christian", "christian_orthodox", "taoist",
                     "hindu", "sikh"], "worship"),
    **dict.fromkeys(["post_office", "community_centre"], "community"),
}

# Approximate metres per degree for the snapping KD-tree (latitude ~7 N).
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * np.cos(np.radians(7.0))


def log(msg):
    print(msg, flush=True)


def to_xy(lon, lat):
    return np.column_stack([np.asarray(lon) * M_PER_DEG_LON, np.asarray(lat) * M_PER_DEG_LAT])


def tambon_lookup(lon, lat, tambons):
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(lon, lat), crs="EPSG:4326")
    joined = gpd.sjoin(pts, tambons[["GID_3", "geometry"]], how="left", predicate="within")
    joined = joined[~joined.index.duplicated(keep="first")]
    return joined["GID_3"].to_numpy()


class GridSnapper:
    """Nearest-250 m-grid-cell lookup for exposure items."""

    def __init__(self, grid):
        self.tree = cKDTree(to_xy(grid["px_lon"], grid["px_lat"]))
        self.cls = grid["susceptibility_class"].to_numpy()
        self.prob = grid["calibrated_probability"].to_numpy()

    def snap(self, lon, lat):
        dist, idx = self.tree.query(to_xy(lon, lat), distance_upper_bound=MAX_SNAP_M)
        ok = np.isfinite(dist)
        cls = np.full(len(dist), None, dtype=object)
        prob = np.full(len(dist), np.nan)
        cls[ok] = self.cls[idx[ok]]
        prob[ok] = self.prob[idx[ok]]
        return cls, prob


def per_tambon_counts(df, prefix, weight=None):
    """total / in-high-class / per-class counts per tambon for exposure frame `df`
    with columns GID_3, susc_class (and optional weight column)."""
    w = df[weight] if weight else pd.Series(1.0, index=df.index)
    d = df.assign(_w=w)
    d = d[d["GID_3"].notna()]
    total = d.groupby("GID_3")["_w"].sum().rename(f"{prefix}_total")
    high = d[d["susc_class"].isin(HIGH_CLASSES)].groupby("GID_3")["_w"].sum().rename(f"{prefix}_high_vh")
    by_class = d.pivot_table(index="GID_3", columns="susc_class", values="_w", aggfunc="sum", fill_value=0.0)
    by_class = by_class.reindex(columns=CLASS_ORDER, fill_value=0.0)
    by_class.columns = [f"{prefix}_{c}" for c in by_class.columns]
    return pd.concat([total, high, by_class], axis=1)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in (TAMBONS_PATH, GRID_PATH, LIVE_PATH, BUILDINGS_PATH, FACILITIES_PATH, POPULATION_PATH):
        if not p.exists():
            sys.exit(f"Missing input: {p}")

    log("Loading tambons and susceptibility grid ...")
    tambons = gpd.read_file(TAMBONS_PATH).to_crs("EPSG:4326")
    grid = pd.read_csv(GRID_PATH)
    snapper = GridSnapper(grid)

    log("Assigning grid cells to tambons ...")
    grid["GID_3"] = tambon_lookup(grid["px_lon"], grid["px_lat"], tambons)
    g = grid[grid["GID_3"].notna()]
    susc = g.groupby("GID_3").agg(
        grid_cells=("calibrated_probability", "size"),
        mean_susceptibility=("calibrated_probability", "mean"),
        pct_cells_high_vh=("susceptibility_class", lambda s: 100.0 * s.isin(HIGH_CLASSES).mean()),
    )

    log("Buildings ...")
    bld = gpd.read_file(BUILDINGS_PATH)
    cen = bld.to_crs("EPSG:32647").geometry.centroid.to_crs("EPSG:4326")
    bdf = pd.DataFrame({"lon": cen.x.to_numpy(), "lat": cen.y.to_numpy()})
    bdf["GID_3"] = tambon_lookup(bdf["lon"], bdf["lat"], tambons)
    bdf["susc_class"], _ = snapper.snap(bdf["lon"], bdf["lat"])
    del bld, cen
    log(f"  {len(bdf):,} buildings, {bdf['GID_3'].notna().sum():,} inside a tambon")

    log("Facilities ...")
    fac = gpd.read_file(FACILITIES_PATH).to_crs("EPSG:4326")
    fdf = pd.DataFrame({"osm_id": fac["osm_id"], "name": fac["name"], "fclass": fac["fclass"],
                        "lon": fac.geometry.x, "lat": fac.geometry.y})
    fdf["category"] = fdf["fclass"].map(FACILITY_CATEGORY).fillna("other")
    fdf["GID_3"] = tambon_lookup(fdf["lon"], fdf["lat"], tambons)
    fdf["susc_class"], fdf["susceptibility_probability"] = snapper.snap(fdf["lon"], fdf["lat"])

    log("Population raster ...")
    ds = gdal.Open(str(POPULATION_PATH))
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray().astype("float64")
    nodata = band.GetNoDataValue()
    x0, dx, _, y0, _, dy = ds.GetGeoTransform()
    valid = (arr > 0) & (arr != nodata) if nodata is not None else (arr > 0)
    rows, cols = np.nonzero(valid)
    pdf = pd.DataFrame({"lon": x0 + (cols + 0.5) * dx, "lat": y0 + (rows + 0.5) * dy, "pop": arr[rows, cols]})
    pdf["GID_3"] = tambon_lookup(pdf["lon"], pdf["lat"], tambons)
    pdf["susc_class"], _ = snapper.snap(pdf["lon"], pdf["lat"])
    log(f"  {len(pdf):,} populated pixels, {pdf['pop'].sum():,.0f} people "
        f"({pdf.loc[pdf['GID_3'].notna(), 'pop'].sum():,.0f} inside a tambon)")

    log("Aggregating per tambon ...")
    out = tambons[["GID_3", "NAME_3", "NAME_2", "NAME_1", "area_km2"]].set_index("GID_3")
    out = out.join(susc)
    out = out.join(per_tambon_counts(bdf, "buildings"))
    out = out.join(per_tambon_counts(pdf, "population", weight="pop"))
    out = out.join(per_tambon_counts(fdf, "facilities"))
    crit = fdf[fdf["category"].isin(["health", "emergency_government"])]
    out = out.join(per_tambon_counts(crit, "critical_facilities")[["critical_facilities_total", "critical_facilities_high_vh"]])
    count_cols = [c for c in out.columns if c.split("_")[0] in {"buildings", "population", "facilities", "critical"}]
    out[count_cols] = out[count_cols].fillna(0.0)
    for c in count_cols:
        if not c.startswith("population"):
            out[c] = out[c].astype(int)
        else:
            out[c] = out[c].round(0).astype(int)

    out["susceptibility_tier"] = pd.cut(out["pct_cells_high_vh"], [-0.1] + TIER_BREAKS + [100.1],
                                        labels=TIER_NAMES, right=False).astype("object")
    tier_idx = out["susceptibility_tier"].map({n: i for i, n in enumerate(TIER_NAMES)})
    # A few sliver tambons on the boundary contain no 250 m grid cell: flag, don't guess.
    out["susceptibility_tier"] = out["susceptibility_tier"].fillna("no_data")
    out["NAME_3"] = out["NAME_3"].fillna("(unnamed)")

    log("Joining the GFS forecast ...")
    live = json.loads(LIVE_PATH.read_text())
    fc = pd.DataFrame(live["tambons"]).set_index("GID_3")
    out = out.join(fc[["gfs_rain_24h_mm", "gfs_rain_48h_mm", "gfs_rain_72h_mm", "gfs_peak_hourly_mm_24h", "rain_class_24h",
                       "local_p75_mm", "local_p90_mm", "local_p95_mm", "rain_local_class_24h"]])
    if RAIN_BASIS == "percentile":
        rain_idx = out["rain_local_class_24h"].map(LOCAL_INDEX)
    else:
        rain_idx = out["rain_class_24h"].map(RAIN_INDEX)
    out["live_impact_class"] = (out["susceptibility_tier"].map(TIER_FACTOR) * rain_idx).map(impact_class_from_product)
    elevated = out["live_impact_class"].isin(HIGH_CLASSES)
    out["population_at_elevated_risk"] = np.where(elevated, out["population_high_vh"], 0)
    out["buildings_at_elevated_risk"] = np.where(elevated, out["buildings_high_vh"], 0)
    out["facilities_at_elevated_risk"] = np.where(elevated, out["facilities_high_vh"], 0)

    out = out.reset_index()
    impact_rank = out["live_impact_class"].map({c: i for i, c in enumerate(IMPACT_ORDER)})
    out = out.assign(_r=impact_rank).sort_values(["_r", "population_at_elevated_risk", "gfs_rain_24h_mm", "population_high_vh", "GID_3"],
                                                 ascending=[True, False, False, False, True]).drop(columns="_r")

    # Province-level roll-up
    sum_cols = ["area_km2", "buildings_total", "buildings_high_vh", "population_total", "population_high_vh",
                "facilities_total", "facilities_high_vh", "critical_facilities_total", "critical_facilities_high_vh",
                "population_at_elevated_risk", "buildings_at_elevated_risk", "facilities_at_elevated_risk"]
    prov = out.groupby("NAME_1")[sum_cols].sum()
    prov["tambons"] = out.groupby("NAME_1").size()
    prov["tambons_live_impact_high_or_above"] = out[out["live_impact_class"].isin(HIGH_CLASSES)] \
        .groupby("NAME_1").size().reindex(prov.index).fillna(0).astype(int)
    prov["max_rain_24h_mm"] = out.groupby("NAME_1")["gfs_rain_24h_mm"].max().round(1)
    prov["pct_population_in_high_vh"] = (100 * prov["population_high_vh"] / prov["population_total"]).round(1)
    prov = prov.reset_index().sort_values("population_high_vh", ascending=False)

    fac_out = fdf[["osm_id", "name", "fclass", "category", "lon", "lat", "GID_3", "susc_class",
                   "susceptibility_probability"]].rename(columns={"susc_class": "susceptibility_class"})
    fac_out = fac_out.merge(out[["GID_3", "NAME_3", "NAME_2", "NAME_1", "rain_class_24h", "live_impact_class"]],
                            on="GID_3", how="left")

    out.round(4).to_csv(OUTPUT_DIR / "impact_overlay_by_tambon.csv", index=False)
    prov.round(2).to_csv(OUTPUT_DIR / "impact_overlay_by_province.csv", index=False)
    fac_out.round(5).to_csv(OUTPUT_DIR / "facility_exposure.csv", index=False)

    totals = {
        "tambons": int(len(out)),
        "buildings_total": int(out["buildings_total"].sum()),
        "buildings_high_vh": int(out["buildings_high_vh"].sum()),
        "population_total": int(out["population_total"].sum()),
        "population_high_vh": int(out["population_high_vh"].sum()),
        "facilities_total": int(out["facilities_total"].sum()),
        "facilities_high_vh": int(out["facilities_high_vh"].sum()),
        "population_at_elevated_risk": int(out["population_at_elevated_risk"].sum()),
        "buildings_at_elevated_risk": int(out["buildings_at_elevated_risk"].sum()),
        "facilities_at_elevated_risk": int(out["facilities_at_elevated_risk"].sum()),
        "tambons_by_live_impact_class": out["live_impact_class"].value_counts().to_dict(),
        "tambons_by_rain_class_24h": out["rain_class_24h"].value_counts().to_dict(),
        "tambons_by_rain_local_class_24h": out["rain_local_class_24h"].value_counts().to_dict(),
    }
    metadata = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "forecast_generated_utc": live.get("generated_utc"),
        "gfs_run_utc": live.get("gfs_run_utc"),
        "forecast_window_start_utc": live.get("window_start_utc"),
        "forecast_window_24h_end_utc": live.get("window_24h_end_utc"),
        "forecast_window_72h_end_utc": live.get("window_72h_end_utc"),
        "susceptibility_grid_points": int(len(grid)),
        "totals": totals,
        "tier_breaks_pct_cells_high_vh": TIER_BREAKS,
        "rain_basis": RAIN_BASIS,
        "rain_classes_mm_24h": live.get("rain_classes_mm_24h"),
        "rain_local_classes": live.get("local_classes"),
        "live_impact_rule": {"formula": "terrain factor x rain class index", "terrain_factor": TIER_FACTOR,
                             "rain_class_index": LOCAL_INDEX if RAIN_BASIS == "percentile" else RAIN_INDEX,
                             "bins": {"low": "0-1", "moderate": "2-3", "high": "4-6", "very_high": ">= 7"}},
        "max_snap_m": MAX_SNAP_M,
        "limitations": [
            "The live impact class is a transparent triage rule (terrain factor x forecast 24 h rain-class index), not a "
            "calibrated probability or a validated landslide forecast. Rain classes are local wet-day percentiles of "
            "the forecast (how unusual the rain is for the tambon) or fixed mm classes; neither is calibrated on landslide "
            "records, whose dates (satellite-image dates) cannot support a calibration.",
            "Terrain susceptibility is a relative ranking from a model trained on 1:1 pseudo-absences "
            "(held-out ROC-AUC 0.94); exposure figures for provinces with almost no training landslides "
            "(Phuket, Yala, Songkhla, Narathiwat, Pattani, Satun, Nakhon Si Thammarat, Ranong) are extrapolation.",
            "Exposure items inherit the class of the nearest 250 m grid cell (<= %d m); items with no nearby cell are in "
            "the totals but in no susceptibility class." % MAX_SNAP_M,
            "Population is WorldPop 2020 constrained (UN-adjusted); buildings and facilities are an OSM snapshot "
            "(2026-09-08) and may be incomplete.",
        ] + live.get("limitations", []),
    }
    (OUTPUT_DIR / "impact_overlay.json").write_text(json.dumps({
        "metadata": metadata,
        "tambons": json.loads(out.round(4).to_json(orient="records")),
        "provinces": json.loads(prov.round(2).to_json(orient="records")),
    }, indent=1))
    log(json.dumps(totals, indent=1))
    log(f"Saved outputs to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
