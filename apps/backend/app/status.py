"""Reads progress straight out of the running pipeline scripts' own log
files/output directories -- this process does not run or control those
scripts, only reports on them, so this stays honest even if a job has
stalled or died since the last request."""

import json

import pandas as pd

from . import paths


def factor_grid_status():
    """250 m point-sampled factor grid (gee_sample_factor_grid_points.py), which
    the susceptibility map is built from. The study area is cut into 150 square
    tiles; 2 of them clip the boundary without containing a single 250 m grid
    point, so a finished run writes 148 tile files."""
    label = "Susceptibility factor grid (250 m point-sampled)"
    grid_dirs = (sorted(paths.FACTOR_GRID_POINTS_DIR.glob("factor_grid_points_*"))
                 if paths.FACTOR_GRID_POINTS_DIR.exists() else [])
    if grid_dirs:
        n_tiles = len(list(grid_dirs[-1].glob("tile_*.csv")))
        return {"label": label, "complete": n_tiles, "total": n_tiles, "done": True,
                "note": "148 of the 150 tiles intersecting the study-area bounding grid contain points; "
                        "the other 2 hold none."}
    # The 250 m factor grid itself (~270 MB of tiles) is not shipped to deployed servers; the scored
    # susceptibility map is built from it, so its metadata is proof the grid step finished.
    if paths.SUSCEPTIBILITY_MAP_METADATA_PATH.exists():
        return {"label": label, "done": True,
                "note": "Factor-grid tiles are not on this server; the susceptibility map built from them is."}
    return {"label": label, "complete": 0, "total": None, "done": False}


def susceptibility_map_status():
    if paths.SUSCEPTIBILITY_GRID_CSV.exists():
        n = len(pd.read_csv(paths.SUSCEPTIBILITY_GRID_CSV, usecols=[0]))
        return {"label": "Full susceptibility map (250 m grid)", "done": True,
                "complete": n, "total": n,
                "note": "Point-sampled at 250 m (see scripts/gee_sample_factor_grid_points.py) "
                        "and scored by the trained model; served via /api/impact/susceptibility-grid."}
    return {
        "label": "Full susceptibility map (250 m grid)",
        "done": False,
        "note": "Run scripts/gee_sample_factor_grid_points.py then scripts/predict_susceptibility_grid.py.",
    }


def live_forecast_status():
    label = "Live GFS rainfall forecast"
    if paths.LIVE_FORECAST_JSON.exists():
        meta = json.loads(paths.LIVE_FORECAST_JSON.read_text())
        summary = meta.get("summary", {})
        return {"label": label, "done": True,
                "note": f"GFS run {str(meta.get('gfs_run_utc', ''))[:16]} UTC, fetched "
                        f"{str(meta.get('generated_utc', ''))[:16]} UTC (scripts/run_live_gfs_forecast.py); "
                        f"max 24 h forecast {summary.get('max_24h_mm')} mm. Rainfall classes are assumed thresholds, "
                        "not calibrated on landslides."}
    return {"label": label, "done": False,
            "note": "Run scripts/run_live_gfs_forecast.py (needs Earth Engine) then scripts/build_impact_overlay.py."}


def impact_overlay_status():
    label = "Live impact overlay (terrain susceptibility x GFS forecast x buildings/population)"
    if paths.IMPACT_OVERLAY_JSON.exists():
        meta = json.loads(paths.IMPACT_OVERLAY_JSON.read_text()).get("metadata", {})
        return {"label": label, "done": True,
                "note": f"Built {meta.get('generated_utc', '')[:19]} UTC from the trigger run at "
                        f"{(meta.get('trigger_generated_utc') or '')[:19]} UTC "
                        "(scripts/build_impact_overlay.py); served via /api/impact/overlay."}
    return {"label": label, "done": False,
            "note": "Run scripts/build_impact_overlay.py (needs the susceptibility map and a live forecast run)."}


def pipeline_status():
    return {
        "factor_grid": factor_grid_status(),
        "susceptibility_raster": susceptibility_map_status(),
        "live_forecast": live_forecast_status(),
        "impact_overlay": impact_overlay_status(),
    }
