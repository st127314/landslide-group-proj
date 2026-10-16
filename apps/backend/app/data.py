"""Loads pipeline outputs into memory once at process start, since none of
these files change while the API is running (they're written by separate,
independently-run scripts -- see README). Restart the API to pick up new
data after re-running a pipeline step.
"""

from functools import lru_cache
import json

import numpy as np
import orjson
import pandas as pd

from . import paths


def _read_json(path):
    with path.open("rb") as handle:
        return orjson.loads(handle.read())


@lru_cache(maxsize=1)
def model_metadata():
    if not paths.MODEL_METADATA_PATH.exists():
        return None
    return _read_json(paths.MODEL_METADATA_PATH)


@lru_cache(maxsize=1)
def susceptibility_geojson():
    """Point-level susceptibility scores (training OOF + held-out test rows),
    as a GeoJSON FeatureCollection -- not the full raster map (still pending;
    see /api/status)."""
    if not paths.SUSCEPTIBILITY_SCORES_CSV.exists():
        return None
    df = pd.read_csv(paths.SUSCEPTIBILITY_SCORES_CSV)
    # Standard JSON has no NaN; e.g. heldout_score is NaN for rows outside
    # that row's own CV/test split. object dtype so None survives, not "nan".
    df = df.astype(object).where(pd.notna(df), None)
    features = []
    for row in df.to_dict(orient="records"):
        lon, lat = row.pop("longitude"), row.pop("latitude")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": row,
        })
    return {"type": "FeatureCollection", "features": features}


@lru_cache(maxsize=1)
def boundary_geojson():
    if not paths.BOUNDARY_PATH.exists():
        return None
    return _read_json(paths.BOUNDARY_PATH)


@lru_cache(maxsize=1)
def facilities_geojson():
    if not paths.FACILITIES_PATH.exists():
        return None
    return _read_json(paths.FACILITIES_PATH)


@lru_cache(maxsize=1)
def worldpop_manifest():
    if not paths.WORLDPOP_MANIFEST_PATH.exists():
        return None
    return _read_json(paths.WORLDPOP_MANIFEST_PATH)


@lru_cache(maxsize=1)
def external_manifest():
    if not paths.EXTERNAL_MANIFEST_PATH.exists():
        return None
    return _read_json(paths.EXTERNAL_MANIFEST_PATH)


def _feature_bbox(feature):
    """Flat min/max over every coordinate pair, geometry-type agnostic (fine
    for a bbox prefilter -- does not need to be the exact tight bbox)."""
    min_lon = min_lat = float("inf")
    max_lon = max_lat = float("-inf")

    def walk(coords):
        nonlocal min_lon, min_lat, max_lon, max_lat
        if isinstance(coords[0], (int, float)):
            lon, lat = coords[0], coords[1]
            min_lon, max_lon = min(min_lon, lon), max(max_lon, lon)
            min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
        else:
            for item in coords:
                walk(item)

    walk(feature["geometry"]["coordinates"])
    return (min_lon, min_lat, max_lon, max_lat)


class _BuildingsIndex:
    """Buildings footprints (426k+ polygons, ~147 MB as GeoJSON) are too large
    to ship to a browser in one response. Loaded once into memory with a
    precomputed bbox per feature, so /api/impact/buildings can cheaply filter
    to whatever the map viewport is currently showing."""

    def __init__(self, path):
        self.loaded = path.exists()
        self.entries = []
        if not self.loaded:
            return
        data = _read_json(path)
        self.entries = [(_feature_bbox(f), f) for f in data["features"]]

    def query(self, bbox, limit):
        min_lon, min_lat, max_lon, max_lat = bbox
        out = []
        for (f_min_lon, f_min_lat, f_max_lon, f_max_lat), feature in self.entries:
            if f_max_lon < min_lon or f_min_lon > max_lon:
                continue
            if f_max_lat < min_lat or f_min_lat > max_lat:
                continue
            out.append(feature)
            if len(out) >= limit:
                break
        return out


@lru_cache(maxsize=1)
def buildings_index():
    return _BuildingsIndex(paths.BUILDINGS_PATH)


class _SusceptibilityGridIndex:
    """The 250 m susceptibility grid (~1.14M points) from
    scripts/predict_susceptibility_grid.py, held as numpy arrays so a bbox
    query is a cheap vectorized mask instead of a 1.14M-row Python loop.
    Like buildings, never served unfiltered -- /api/impact/susceptibility-grid
    always requires a bounding box."""

    def __init__(self, path):
        self.loaded = path.exists()
        if not self.loaded:
            self.lon = self.lat = self.raw = self.calibrated = self.cls = None
            return
        df = pd.read_csv(path)
        self.lon = df["px_lon"].to_numpy()
        self.lat = df["px_lat"].to_numpy()
        self.raw = df["raw_probability"].to_numpy()
        self.calibrated = df["calibrated_probability"].to_numpy()
        self.cls = df["susceptibility_class"].to_numpy()

    def query(self, bbox, limit):
        min_lon, min_lat, max_lon, max_lat = bbox
        mask = ((self.lon >= min_lon) & (self.lon <= max_lon) &
                (self.lat >= min_lat) & (self.lat <= max_lat))
        idx = np.nonzero(mask)[0]
        truncated = len(idx) > limit
        if truncated:
            # Even stride rather than a prefix, so a zoomed-out view isn't
            # biased toward one corner of the viewport.
            idx = idx[:: max(1, len(idx) // limit)][:limit]
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(self.lon[i]), float(self.lat[i])]},
                "properties": {
                    "raw_probability": float(self.raw[i]),
                    "calibrated_probability": float(self.calibrated[i]),
                    "susceptibility_class": str(self.cls[i]),
                },
            }
            for i in idx
        ]
        return features, truncated


@lru_cache(maxsize=1)
def susceptibility_grid_index():
    return _SusceptibilityGridIndex(paths.SUSCEPTIBILITY_GRID_CSV)


@lru_cache(maxsize=1)
def tambon_boundary_geojson():
    if not paths.TAMBON_BOUNDARY_PATH.exists():
        return None
    return _read_json(paths.TAMBON_BOUNDARY_PATH)


def live_forecast_data():
    """Deliberately NOT lru_cached: this file is overwritten by a recurring external job
    (scripts/run_live_gfs_forecast.py), so every request should see the latest run."""
    if not paths.LIVE_FORECAST_JSON.exists():
        return None
    return _read_json(paths.LIVE_FORECAST_JSON)


@lru_cache(maxsize=1)
def susceptibility_map_metadata():
    if not paths.SUSCEPTIBILITY_MAP_METADATA_PATH.exists():
        return None
    return _read_json(paths.SUSCEPTIBILITY_MAP_METADATA_PATH)


def impact_overlay_data():
    """Not cached: rebuilt by scripts/build_impact_overlay.py after each
    real-time trigger run, so every request should see the latest build."""
    if not paths.IMPACT_OVERLAY_JSON.exists():
        return None
    return _read_json(paths.IMPACT_OVERLAY_JSON)
