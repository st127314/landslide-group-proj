"""Clip the nationwide ADM_ADM_3 (tambon/sub-district) layer to the southern
Thailand study area, and compute one representative sample point per tambon
(for the real-time rainfall pipeline -- a whole-polygon reduceRegions call
per refresh would be far more Earth Engine work than one point per tambon,
and tambons are small enough that a representative point is an adequate
proxy for "rainfall over this tambon").

Run with: python3 scripts/clip_tambon_boundaries.py

Input: data/raw/gadm41_THA.gpkg (GADM 4.1 Thailand, not shipped -- download from
https://gadm.org/download_country.html, GeoPackage). Outputs go to data/boundary/.
"""

from pathlib import Path

import geopandas as gpd

PROJECT_DIR = Path(__file__).resolve().parent.parent
GADM_PATH = PROJECT_DIR / "data" / "raw" / "gadm41_THA.gpkg"
AOI_PATH = PROJECT_DIR / "data" / "boundary" / "southern_thailand.geojson"
OUTPUT_DIR = PROJECT_DIR / "data" / "boundary"
METRIC_CRS = "EPSG:32647"


def main():
    aoi = gpd.read_file(AOI_PATH).to_crs("EPSG:4326")
    aoi.geometry = aoi.geometry.make_valid()
    aoi_union = aoi.geometry.union_all()

    print("Reading ADM_ADM_3 (this is a large nationwide layer)...")
    tambons = gpd.read_file(GADM_PATH, layer="ADM_ADM_3", bbox=aoi_union.bounds).to_crs("EPSG:4326")
    print(f"Read {len(tambons):,} candidate tambons by bbox")

    tambons = tambons[tambons.geometry.intersects(aoi_union)].copy()
    print(f"{len(tambons):,} tambons intersect the study area")

    # representative_point() is guaranteed inside the polygon (unlike
    # centroid, which can fall outside for a concave/multi-part tambon) --
    # important since this point drives the per-tambon GFS and CHIRPS sampling.
    sample_points = tambons.geometry.representative_point()
    tambons["sample_lon"] = sample_points.x
    tambons["sample_lat"] = sample_points.y
    tambons["area_km2"] = tambons.geometry.to_crs(METRIC_CRS).area / 1e6

    name_col = "NAME_3" if "NAME_3" in tambons.columns else None
    district_col = "NAME_2" if "NAME_2" in tambons.columns else None
    province_col = "NAME_1" if "NAME_1" in tambons.columns else None
    keep_cols = [c for c in ["GID_3", name_col, district_col, province_col,
                             "area_km2", "sample_lon", "sample_lat", "geometry"] if c]
    tambons = tambons[keep_cols]

    out_geojson = OUTPUT_DIR / "southern_thailand_tambons.geojson"
    tambons.to_file(out_geojson, driver="GeoJSON")
    print(f"Saved {out_geojson} ({len(tambons):,} tambons)")

    points_path = OUTPUT_DIR / "southern_thailand_tambon_points.csv"
    tambons.drop(columns="geometry").to_csv(points_path, index=False)
    print(f"Saved {points_path}")


if __name__ == "__main__":
    main()
