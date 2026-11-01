"""Loads pipeline outputs into memory once at process start, since none of
these files change while the API is running (they're written by separate,
independently-run scripts -- see README). Restart the API to pick up new
data after re-running a pipeline step.
"""

from functools import lru_cache
import hashlib
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


def _read_bytes(path):
    """Static layers are served exactly as stored (already minified by scripts/make_web_layers.py), so the API keeps
    one bytes copy instead of a parsed dict plus a re-serialisation on every request."""
    return path.read_bytes() if path.exists() else None


# Only what the map draws or shows in its pop-up; final_model_insample_score is left out because it is the
# in-sample score of the refitted model, not a held-out estimate.
SAMPLE_COLUMNS = ["id", "event_date", "landslide", "split", "heldout_score", "relative_score_class"]


@lru_cache(maxsize=1)
def _susceptibility_samples():
    if not paths.SUSCEPTIBILITY_SCORES_CSV.exists():
        return None
    df = pd.read_csv(paths.SUSCEPTIBILITY_SCORES_CSV)
    df["heldout_score"] = df["heldout_score"].round(3)
    columns = [c for c in SAMPLE_COLUMNS if c in df.columns]
    lon, lat = df["longitude"].round(5).tolist(), df["latitude"].round(5).tolist()
    # Standard JSON has no NaN; e.g. heldout_score is NaN for rows outside
    # that row's own CV/test split. object dtype so None survives, not "nan".
    records = df[columns].astype(object).where(pd.notna(df[columns]), None).to_dict(orient="records")
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]}, "properties": props}
                for x, y, props in zip(lon, lat, records)]
    counts = df["landslide"].value_counts().to_dict()
    return orjson.dumps({"type": "FeatureCollection", "features": features}), counts


def susceptibility_geojson():
    """Point-level susceptibility scores (training OOF + held-out test rows) as GeoJSON bytes -- the
    sampled inventory, not the 250 m map (see susceptibility_grid_index)."""
    samples = _susceptibility_samples()
    return samples[0] if samples else None


def susceptibility_sample_counts():
    """{1: landslide rows, 0: non-landslide rows}, or None when the scores file is missing."""
    samples = _susceptibility_samples()
    return samples[1] if samples else None


@lru_cache(maxsize=1)
def boundary_geojson():
    return _read_bytes(paths.BOUNDARY_PATH)


@lru_cache(maxsize=1)
def facilities_geojson():
    return _read_bytes(paths.FACILITIES_PATH)


@lru_cache(maxsize=1)
def facility_breakdown():
    if not paths.FACILITIES_PATH.exists():
        return None
    counts = {}
    for feature in _read_json(paths.FACILITIES_PATH)["features"]:
        fclass = feature["properties"].get("fclass") or "other"
        counts[fclass] = counts.get(fclass, 0) + 1
    return counts


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

    CLASSES = ["very_low", "low", "moderate", "high", "very_high"]

    def __init__(self, path):
        self.loaded = path.exists()
        if not self.loaded:
            self.lon = self.lat = self.calibrated = self.cls = None
            return
        # float32 coordinates (~1 m precision here) and int8 class codes keep the 1.14M points at ~14 MB instead of
        # ~130 MB with float64 and a Python string per row; the server has under 1 GB of RAM.
        df = pd.read_csv(path, usecols=["px_lon", "px_lat", "calibrated_probability", "susceptibility_class"],
                         dtype={"px_lon": np.float32, "px_lat": np.float32, "calibrated_probability": np.float32})
        self.lon = df["px_lon"].to_numpy()
        self.lat = df["px_lat"].to_numpy()
        self.calibrated = df["calibrated_probability"].to_numpy()
        self.cls = pd.Categorical(df["susceptibility_class"], categories=self.CLASSES).codes.astype(np.int8)

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
        lon = np.round(self.lon[idx].astype(np.float64), 5).tolist()
        lat = np.round(self.lat[idx].astype(np.float64), 5).tolist()
        prob = np.round(self.calibrated[idx].astype(np.float64), 3).tolist()
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": {"calibrated_probability": p,
                               "susceptibility_class": self.CLASSES[c] if c >= 0 else None},
            }
            for x, y, p, c in zip(lon, lat, prob, self.cls[idx].tolist())
        ]
        return features, truncated

    def nearest(self, lon, lat, max_deg=0.004):
        """The grid cell closest to (lon, lat), or None when nothing lies within ~400 m (sea, outside the area)."""
        near = np.nonzero((np.abs(self.lon - lon) <= max_deg) & (np.abs(self.lat - lat) <= max_deg))[0]
        if not len(near):
            return None
        i = near[np.argmin((self.lon[near] - lon) ** 2 + (self.lat[near] - lat) ** 2)]
        c = int(self.cls[i])
        return {"lon": round(float(self.lon[i]), 5), "lat": round(float(self.lat[i]), 5),
                "calibrated_probability": round(float(self.calibrated[i]), 3),
                "susceptibility_class": self.CLASSES[c] if c >= 0 else None}


@lru_cache(maxsize=1)
def susceptibility_grid_index():
    return _SusceptibilityGridIndex(paths.SUSCEPTIBILITY_GRID_CSV)


@lru_cache(maxsize=1)
def susceptibility_png():
    return _read_bytes(paths.SUSCEPTIBILITY_PNG)


@lru_cache(maxsize=1)
def susceptibility_png_bounds():
    """Corner coordinates plus a content hash of the PNG: the map requests the image as ...png?v=<hash>, so a new map
    is never hidden behind a browser or Cloudflare copy of the old one."""
    body = _read_bytes(paths.SUSCEPTIBILITY_PNG_BOUNDS)
    png = susceptibility_png()
    if body is None:
        return None
    bounds = orjson.loads(body)
    if png is not None:
        bounds["version"] = hashlib.sha256(png).hexdigest()[:12]
    return orjson.dumps(bounds)


@lru_cache(maxsize=1)
def tambon_boundary_geojson():
    return _read_bytes(paths.TAMBON_BOUNDARY_PATH)


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
