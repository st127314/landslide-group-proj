"""Write slimmed copies of the static map layers served by the web app.

The source layers are far more detailed than an overview map needs, and the server has little memory, so the API
serves these lighter versions instead:

  data/boundary/southern_thailand_web.geojson   provinces simplified to ~100 m, province name only, 4-decimal coordinates
  data/external/facilities_web.geojson          facility points with type and name only, 5-decimal coordinates
  data/boundary/southern_thailand_tambons_web.geojson   1,055 tambons simplified to ~100 m as one coverage (shared
                                                borders stay shared, so no gaps open between neighbours), with the
                                                GADM id and names only; the map joins the risk figures by GID_3

Run after download_external_data.py:  python scripts/make_web_layers.py   (needs geopandas)
"""

import json
from pathlib import Path

import geopandas as gpd
from shapely import coverage_simplify, set_precision

PROJECT_DIR = Path(__file__).resolve().parent.parent
BOUNDARY_IN = PROJECT_DIR / "data" / "boundary" / "southern_thailand.geojson"
BOUNDARY_OUT = PROJECT_DIR / "data" / "boundary" / "southern_thailand_web.geojson"
FACILITIES_IN = PROJECT_DIR / "data" / "external" / "facilities_aoi.geojson"
FACILITIES_OUT = PROJECT_DIR / "data" / "external" / "facilities_web.geojson"
TAMBONS_IN = PROJECT_DIR / "data" / "boundary" / "southern_thailand_tambons.geojson"
TAMBONS_OUT = PROJECT_DIR / "data" / "boundary" / "southern_thailand_tambons_web.geojson"
SIMPLIFY_DEG = 0.001          # ~110 m: invisible at the zoom levels used for the study-area outline


def write(gdf, path, decimals):
    text = gdf.to_json(drop_id=True, to_wgs84=True)
    data = json.loads(text)
    for feature in data["features"]:
        feature["geometry"] = _round(feature["geometry"], decimals)
    path.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print(f"{path.relative_to(PROJECT_DIR)}: {len(data['features'])} features, {path.stat().st_size / 1e6:.2f} MB")


def _round(geometry, decimals):
    def walk(coords):
        if isinstance(coords[0], (int, float)):
            return [round(c, decimals) for c in coords]
        return [walk(c) for c in coords]
    geometry["coordinates"] = walk(geometry["coordinates"])
    return geometry


def main():
    provinces = gpd.read_file(BOUNDARY_IN)[["NAME_1", "geometry"]]
    provinces["geometry"] = set_precision(provinces.geometry.simplify(SIMPLIFY_DEG, preserve_topology=True), 1e-4)
    write(provinces, BOUNDARY_OUT, 4)

    facilities = gpd.read_file(FACILITIES_IN)[["fclass", "name", "geometry"]]
    write(facilities, FACILITIES_OUT, 5)

    tambons = gpd.read_file(TAMBONS_IN)[["GID_3", "NAME_3", "NAME_2", "NAME_1", "geometry"]]
    tambons["geometry"] = coverage_simplify(tambons.geometry.values, SIMPLIFY_DEG)
    write(tambons[~tambons.geometry.is_empty], TAMBONS_OUT, 4)


if __name__ == "__main__":
    main()
