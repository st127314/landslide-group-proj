"""Builds a tiny synthetic data tree and points LANDSLIDE_ROOT at it BEFORE the app is imported,
so the API can be tested without any of the private pipeline data."""

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="landslide_fixture_"))
os.environ["LANDSLIDE_ROOT"] = str(ROOT)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _write(rel, content):
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content))


def _poly(lon, lat, d=0.001):
    return {"type": "Polygon", "coordinates": [[[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


_write("data/boundary/southern_thailand.geojson",
       _fc([{"type": "Feature", "properties": {"NAME_1": "Testprovince"}, "geometry": _poly(98.0, 7.0, 3.0)}]))
_write("data/boundary/southern_thailand_tambons.geojson",
       _fc([{"type": "Feature", "properties": {"GID_3": "T.1", "NAME_3": "Alpha"}, "geometry": _poly(99.0, 8.0, 0.5)}]))
_write("data/external/buildings_aoi.geojson", _fc([
    {"type": "Feature", "properties": {"osm_id": str(i)}, "geometry": _poly(99.0 + i * 0.01, 8.0)} for i in range(5)]))
_write("data/external/facilities_aoi.geojson", _fc([
    {"type": "Feature", "properties": {"fclass": "hospital"}, "geometry": {"type": "Point", "coordinates": [99.0, 8.0]}},
    {"type": "Feature", "properties": {"fclass": "school"}, "geometry": {"type": "Point", "coordinates": [99.1, 8.1]}}]))
_write("data/external/worldpop_manifest.json", {"stats": {"total_population": 1234.0}, "license": "CC BY 4.0"})
_write("data/external/manifest.json", {"limitations": []})
_write("models/susceptibility/model_metadata.json", {
    "best_model": "gradient_boosting", "selection": "nested spatial CV (ROC-AUC)", "best_params": {"gradient_boosting": {}},
    "threshold_raw_probability": 0.17, "threshold_calibrated_probability": 0.51,
    "feature_columns": ["elevation", "slope", "lulc"], "numeric_features": ["elevation", "slope"],
    "categorical_features": ["lulc"], "excluded_columns": ["id", "event_date", "longitude", "latitude"],
    "cv_results": [{"model": "gradient_boosting", "roc_auc_mean": 0.96, "roc_auc_std": 0.02}],
    "test_results": [{"model": "gradient_boosting", "roc_auc": 0.92}, {"model": "svm_rbf", "roc_auc": 0.96}]})
_write("models/susceptibility/landslide_sample_susceptibility_scores.csv",
       "id,event_date,longitude,latitude,landslide,split,heldout_score\nLS_1,2014-01-01,99.0,8.0,1,test,0.8\nNL_1,2014-01-01,99.1,8.1,0,test,\n")
_write("results/susceptibility_map/susceptibility_grid_points.csv",
       "px_lon,px_lat,raw_probability,calibrated_probability,susceptibility_class,above_threshold\n"
       "99.00,8.00,0.9,0.9,very_high,1\n99.10,8.10,0.1,0.05,very_low,0\n99.20,8.20,0.5,0.5,moderate,1\n")
_write("results/susceptibility_map/susceptibility_map_metadata.json", {"point_count": 3, "class_counts": {"very_high": 1}})
_write("results/live_forecast/latest.json", {
    "generated_utc": "2026-01-01T07:00:00+00:00", "gfs_run_utc": "2026-01-01T00:00:00+00:00",
    "window_start_utc": "2026-01-01T08:00:00+00:00", "window_24h_end_utc": "2026-01-02T08:00:00+00:00",
    "window_72h_end_utc": "2026-01-04T08:00:00+00:00",
    "rain_classes_mm_24h": [{"class": "light", "from_mm": 0}, {"class": "moderate", "from_mm": 10},
                            {"class": "heavy", "from_mm": 35}, {"class": "very_heavy", "from_mm": 90}],
    "summary": {"tambons": 1, "tambons_by_class_24h": {"heavy": 1}, "tambons_by_local_class_24h": {"above_p95": 1},
                "max_24h_mm": 40.0, "median_24h_mm": 40.0},
    "method": "fixture",
    "tambons": [{"GID_3": "T.1", "NAME_3": "Alpha", "NAME_2": "District", "NAME_1": "Testprovince", "lon": 99.0, "lat": 8.0,
                 "gfs_rain_24h_mm": 40.0, "gfs_rain_48h_mm": 60.0, "gfs_rain_72h_mm": 80.0,
                 "gfs_peak_hourly_mm_24h": 9.0, "rain_class_24h": "heavy",
                 "local_p75_mm": 15.0, "local_p90_mm": 25.0, "local_p95_mm": 33.0, "rain_local_class_24h": "above_p95"}],
    "limitations": ["fixture"]})
_write("results/impact_overlay/impact_overlay.json", {
    "metadata": {"generated_utc": "2026-01-01T07:00:00+00:00", "forecast_generated_utc": "2026-01-01T07:00:00+00:00",
                 "gfs_run_utc": "2026-01-01T00:00:00+00:00", "forecast_window_start_utc": "2026-01-01T08:00:00+00:00",
                 "forecast_window_24h_end_utc": "2026-01-02T08:00:00+00:00",
                 "totals": {"buildings_total": 5, "buildings_high_vh": 1, "population_total": 100, "population_high_vh": 10,
                            "facilities_total": 2, "facilities_high_vh": 1, "population_at_elevated_risk": 10,
                            "buildings_at_elevated_risk": 1, "facilities_at_elevated_risk": 1,
                            "tambons_by_live_impact_class": {"very_high": 1}, "tambons_by_rain_class_24h": {"heavy": 1}},
                 "limitations": ["fixture"]},
    "tambons": [
        {"GID_3": "T.1", "NAME_3": "Alpha", "NAME_2": "District", "NAME_1": "Testprovince", "area_km2": 10.0,
         "pct_cells_high_vh": 50.0, "susceptibility_tier": "high", "buildings_total": 5, "buildings_high_vh": 1,
         "population_total": 100, "population_high_vh": 10, "facilities_total": 2, "facilities_high_vh": 1,
         "critical_facilities_high_vh": 1, "gfs_rain_24h_mm": 40.0, "gfs_rain_48h_mm": 60.0, "gfs_rain_72h_mm": 80.0,
         "rain_class_24h": "heavy", "local_p75_mm": 15.0, "local_p90_mm": 25.0, "local_p95_mm": 33.0,
         "rain_local_class_24h": "above_p95", "live_impact_class": "very_high", "population_at_elevated_risk": 10,
         "buildings_at_elevated_risk": 1, "facilities_at_elevated_risk": 1},
        {"GID_3": "T.2", "NAME_3": "Beta", "NAME_2": "District", "NAME_1": "Testprovince", "area_km2": 8.0,
         "pct_cells_high_vh": 2.0, "susceptibility_tier": "low", "buildings_total": 9, "buildings_high_vh": 0,
         "population_total": 500, "population_high_vh": 5, "facilities_total": 1, "facilities_high_vh": 0,
         "critical_facilities_high_vh": 0, "gfs_rain_24h_mm": 5.0, "gfs_rain_48h_mm": 8.0, "gfs_rain_72h_mm": 9.0,
         "rain_class_24h": "light", "local_p75_mm": 15.0, "local_p90_mm": 25.0, "local_p95_mm": 33.0,
         "rain_local_class_24h": "below_p75", "live_impact_class": "low", "population_at_elevated_risk": 0,
         "buildings_at_elevated_risk": 0, "facilities_at_elevated_risk": 0},
        {"GID_3": "T.3", "NAME_3": "Gamma", "NAME_2": "Other", "NAME_1": "Otherprovince", "area_km2": 12.0,
         "pct_cells_high_vh": 20.0, "susceptibility_tier": "moderate", "buildings_total": 4, "buildings_high_vh": 2,
         "population_total": 300, "population_high_vh": 40, "facilities_total": 0, "facilities_high_vh": 0,
         "critical_facilities_high_vh": 0, "gfs_rain_24h_mm": 20.0, "gfs_rain_48h_mm": 30.0, "gfs_rain_72h_mm": 35.0,
         "rain_class_24h": "moderate", "local_p75_mm": 15.0, "local_p90_mm": 25.0, "local_p95_mm": 33.0,
         "rain_local_class_24h": "p75_p90", "live_impact_class": "moderate", "population_at_elevated_risk": 0,
         "buildings_at_elevated_risk": 0, "facilities_at_elevated_risk": 0},
    ],
    "provinces": []})
