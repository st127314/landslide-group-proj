"""Apply the trained susceptibility model to the sampled factor grid, producing
a susceptibility score per grid point plus a rasterized GeoTIFF for GIS/overlay
use.

Requires scikit-learn, joblib and GDAL. Run:
    python scripts/predict_susceptibility_grid.py

Inputs:
  - data/processed/factor_grid_points/factor_grid_points_<date>/*.csv
    (from gee_sample_factor_grid_points.py; see that script's docstring for
    why this is points on a regular 250 m grid rather than raster tiles)
  - models/susceptibility/{best_model}_landslide_susceptibility_pipeline.joblib
  - models/susceptibility/{best_model}_isotonic_calibrator.joblib
  - models/susceptibility/model_metadata.json (best_model name, feature_columns)
  - notebooks/susc_utils.py must be importable: the saved pipeline's
    FunctionTransformer references add_aspect_features from that module.

Outputs (results/susceptibility_map/):
  - susceptibility_grid_points.csv -- one row per sampled point
  - susceptibility_grid.tif -- nearest-grid-cell rasterization (EPSG:4326),
    for GIS/overlay use (tambon zonal stats, the impact-overlay app, etc.)
"""

import argparse
from pathlib import Path
import sys
import json

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "notebooks"))  # susc_utils.py, for unpickling the pipeline
import joblib  # noqa: E402  (after sys.path setup)

MODEL_ARTIFACT_DIR = PROJECT_DIR / "models" / "susceptibility"
GRID_DIR = PROJECT_DIR / "data" / "processed" / "factor_grid_points"
OUTPUT_DIR = PROJECT_DIR / "results" / "susceptibility_map"

# Grid CSV column -> trained model's expected feature name. Columns not
# listed here keep their name (elevation, slope, aspect, curvature_*,
# upstream_area_km2, dist_to_stream, soil_*, dist_to_road, dist_to_river,
# lithology already match). drainage_density/dist_to_fault/dem_source are
# sampled but were never part of the trained feature set -- dropped.
RENAME = {
    "TRI": "tri", "TPI": "tpi", "LS_factor": "ls_factor",
    "TWI": "twi", "SPI": "spi", "NDVI": "ndvi", "LULC_current": "lulc",
}
CLASS_BINS = [-0.001, 0.2, 0.4, 0.6, 0.8, 1.001]
CLASS_LABELS = ["very_low", "low", "moderate", "high", "very_high"]


def latest_grid_dir():
    candidates = sorted(GRID_DIR.glob("factor_grid_points_*"))
    if not candidates:
        raise FileNotFoundError(f"No factor_grid_points_* directories under {GRID_DIR}. The factor grid is an intermediate that is not "
                                "shipped with the submission: restore it from the archive, or regenerate it with "
                                "scripts/gee_sample_factor_grid_points.py (Earth Engine).")
    return candidates[-1]


def load_grid(grid_dir):
    frames = [pd.read_csv(f) for f in sorted(grid_dir.glob("tile_*.csv"))]
    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns=RENAME)
    return df


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid-dir", type=Path, default=None,
                        help="Defaults to the most recent data/processed/factor_grid_points/factor_grid_points_* directory.")
    parser.add_argument("--raster-scale-m", type=float, default=250,
                        help="Output raster cell size; matches the point spacing by default.")
    args = parser.parse_args()

    grid_dir = args.grid_dir or latest_grid_dir()
    print(f"Grid directory: {grid_dir}")

    metadata = json.loads((MODEL_ARTIFACT_DIR / "model_metadata.json").read_text())
    best_model = metadata["best_model"]
    feature_columns = metadata["feature_columns"]
    print(f"Model: {best_model}")

    pipeline = joblib.load(MODEL_ARTIFACT_DIR / f"{best_model}_landslide_susceptibility_pipeline.joblib")
    calibrator_path = MODEL_ARTIFACT_DIR / f"{best_model}_isotonic_calibrator.joblib"
    calibrator = joblib.load(calibrator_path) if calibrator_path.exists() else None

    df = load_grid(grid_dir)
    print(f"Loaded {len(df):,} grid points")
    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Grid is missing columns the model needs: {missing}")

    X = df[feature_columns]
    raw_proba = pipeline.predict_proba(X)[:, 1]
    df["raw_probability"] = raw_proba
    if calibrator is not None:
        df["calibrated_probability"] = calibrator.predict(raw_proba)
    else:
        df["calibrated_probability"] = raw_proba
    df["susceptibility_class"] = pd.cut(
        df["calibrated_probability"], bins=CLASS_BINS, labels=CLASS_LABELS)
    df["above_threshold"] = (df["raw_probability"] >= metadata["threshold_raw_probability"]).astype(int)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    points_path = OUTPUT_DIR / "susceptibility_grid_points.csv"
    keep_cols = ["px_lon", "px_lat", "raw_probability", "calibrated_probability",
                 "susceptibility_class", "above_threshold"]
    df[keep_cols].to_csv(points_path, index=False)
    print(f"Saved {points_path} ({len(df):,} rows)")
    print(df["susceptibility_class"].value_counts().sort_index())

    raster_path = OUTPUT_DIR / "susceptibility_grid.tif"
    write_raster(df, args.raster_scale_m, raster_path)
    print(f"Saved {raster_path}")

    summary = {
        "model": best_model,
        "selection": metadata.get("selection"),
        "grid_source": str(grid_dir.relative_to(PROJECT_DIR)),
        "point_count": int(len(df)),
        "score_interpretation": metadata.get("score_interpretation"),
        "threshold_raw_probability": metadata["threshold_raw_probability"],
        "class_bins": CLASS_BINS,
        "class_labels": CLASS_LABELS,
        "class_counts": {k: int(v) for k, v in df["susceptibility_class"].value_counts().items()},
        "limitations": [
            "Scores are relative susceptibility under 1:1 synthetic pseudo-absence sampling "
            "(see model_metadata.json's score_interpretation), not calibrated to real-world prevalence.",
            "Grid is 250 m point samples, not the model's native 30 m training resolution -- see "
            "scripts/gee_sample_factor_grid_points.py's docstring for why this is not a meaningful "
            "accuracy loss given the model's own ~28 km spatial-CV validation granularity.",
            "dist_to_fault/dist_to_road/dist_to_river are null for points beyond their 20 km search "
            "radius (much more common in this regional grid than in the training data, which sat at "
            "event locations); the trained median imputer fills these the same way it does in training.",
        ],
    }
    (OUTPUT_DIR / "susceptibility_map_metadata.json").write_text(json.dumps(summary, indent=2))
    print(f"Saved {OUTPUT_DIR / 'susceptibility_map_metadata.json'}")


def write_raster(df, scale_m, out_path):
    """Nearest-grid-cell rasterization: snap each point's (lon, lat) onto a
    single global lattice (not per-tile, since gee_sample_factor_grid_points.py
    restarts its point offset independently per tile and tiles can be
    slightly out of phase at their shared boundary) and write a GeoTIFF.
    Approximate (WGS84 degrees treated as locally-flat for the cell size),
    fine at 250 m for a regional map; not survey-grade."""
    from osgeo import gdal, osr

    lon_step = scale_m / (111_320 * np.cos(np.radians(df["px_lat"].mean())))
    lat_step = scale_m / 110_574

    min_lon, max_lon = df["px_lon"].min(), df["px_lon"].max()
    min_lat, max_lat = df["px_lat"].min(), df["px_lat"].max()
    n_cols = int(np.ceil((max_lon - min_lon) / lon_step)) + 1
    n_rows = int(np.ceil((max_lat - min_lat) / lat_step)) + 1

    col = np.clip(((df["px_lon"] - min_lon) / lon_step).round().astype(int), 0, n_cols - 1)
    # Raster rows increase downward (north at row 0); lat increases upward.
    row = np.clip(((max_lat - df["px_lat"]) / lat_step).round().astype(int), 0, n_rows - 1)

    grid = np.full((n_rows, n_cols), np.nan, dtype=np.float32)
    grid[row.to_numpy(), col.to_numpy()] = df["calibrated_probability"].to_numpy(dtype=np.float32)

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(str(out_path), n_cols, n_rows, 1, gdal.GDT_Float32,
                       options=["COMPRESS=DEFLATE", "TILED=YES"])
    ds.SetGeoTransform([min_lon - lon_step / 2, lon_step, 0, max_lat + lat_step / 2, 0, -lat_step])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float("nan"))
    band.WriteArray(grid)
    band.ComputeStatistics(False)
    ds = None


if __name__ == "__main__":
    main()
