"""Generate paired non-landslide (pseudo-absence) points, one per landslide event.

Each negative is placed in a ring around its own landslide and takes that
landslide's date, so the two classes share the same year/season distribution,
the same province and (roughly) the same weather, and any
difference between them is attributable to local terrain.

Rules for every negative
  * ring: `--ring-min` .. `--ring-max` m (default 2-10 km) from its paired landslide,
    sampled uniformly by area;
  * at least `--exclusion` m (default 2 km) from EVERY landslide record in
    `data/inventory/landslide_records_all.geojson` (all ~23 k southern records,
    including the undated ones that are not used as training events) -- excluding
    only the 6,180 dated events would leave ~17 % of negatives within 2 km of an
    undated landslide;
  * inside the paired landslide's own province (`--any-province` to allow the whole study area);
  * at least `--min-spacing` m (default 250 m) from every other negative. (1 km is infeasible:
    the median landslide has ~680 other records within 10 km, so 750 m and 1 km leave 171 / 270
    landslides without a partner.)
If no valid point is found in the ring after `--tries` candidates, the outer
radius is widened (x1.5, up to `--ring-cap`) and the attempt repeated.

Output keeps the schema of data/inventory/non_landslide_events.geojson so the
extraction scripts read it unchanged, plus `paired_landslide_id`,
`pair_distance_km` and `source = paired_ring_same_date`.

Usage: python3 scripts/generate_paired_negatives.py
"""

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from scipy.spatial import cKDTree

PROJECT_DIR = Path(__file__).resolve().parent.parent
INVENTORY_DIR = PROJECT_DIR / "data" / "inventory"
BOUNDARY_PATH = PROJECT_DIR / "data" / "boundary" / "southern_thailand.geojson"
METRIC_CRS = "EPSG:32647"  # UTM 47N, same as the Earth Engine extraction CRS


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--landslides", type=Path, default=INVENTORY_DIR / "landslide_inventory.geojson")
    p.add_argument("--all-records", type=Path, default=INVENTORY_DIR / "landslide_records_all.geojson")
    p.add_argument("--output", type=Path, default=INVENTORY_DIR / "non_landslide_events.geojson")
    p.add_argument("--ring-min", type=float, default=2000.0)
    p.add_argument("--ring-max", type=float, default=10000.0)
    p.add_argument("--ring-cap", type=float, default=40000.0)
    p.add_argument("--exclusion", type=float, default=2000.0)
    p.add_argument("--min-spacing", type=float, default=250.0)
    p.add_argument("--tries", type=int, default=300)
    p.add_argument("--any-province", action="store_true",
                   help="Allow negatives to cross into other provinces (default: stay in the paired landslide's province).")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


class SpacingIndex:
    """Grid hash for 'is any accepted point within d metres' queries."""

    def __init__(self, cell):
        self.cell, self.cells = cell, {}

    def _key(self, x, y):
        return int(x // self.cell), int(y // self.cell)

    def too_close(self, x, y, d):
        kx, ky = self._key(x, y)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for px, py in self.cells.get((kx + i, ky + j), ()):
                    if (px - x) ** 2 + (py - y) ** 2 < d * d:
                        return True
        return False

    def add(self, x, y):
        self.cells.setdefault(self._key(x, y), []).append((x, y))


def main(argv=None):
    args = parse_args(argv)
    rng = np.random.default_rng(args.seed)

    ls = gpd.read_file(args.landslides).set_crs("EPSG:4326", allow_override=True).to_crs(METRIC_CRS)
    allrec = gpd.read_file(args.all_records).set_crs("EPSG:4326", allow_override=True).to_crs(METRIC_CRS)
    assert set(ls["inventory_id"]) <= set(allrec["inventory_id"]), "dated landslides must be in the all-records file"
    provinces = gpd.read_file(BOUNDARY_PATH).to_crs(METRIC_CRS)
    aoi = provinces.geometry.union_all()
    shapely.prepare(aoi)
    prov_geom = {}
    for name, geom in zip(provinces["NAME_1"], provinces.geometry):
        shapely.prepare(geom)
        prov_geom[name] = geom
    home = gpd.sjoin(ls[["geometry"]], provinces[["NAME_1", "geometry"]], predicate="within", how="left")
    home = home[~home.index.duplicated(keep="first")]["NAME_1"].to_numpy()  # NaN if a point falls just outside

    all_xy = np.c_[allrec.geometry.x, allrec.geometry.y]
    tree = cKDTree(all_xy)
    index = SpacingIndex(max(args.min_spacing, 1.0))

    order = rng.permutation(len(ls))  # random order so no landslide is favoured when space is tight
    features = [None] * len(ls)
    widened = failed = 0
    for n, i in enumerate(order, 1):
        row = ls.iloc[i]
        cx, cy = row.geometry.x, row.geometry.y
        region = aoi if args.any_province or not isinstance(home[i], str) else prov_geom[home[i]]
        outer, placed = args.ring_max, False
        while not placed and outer <= args.ring_cap * 1.0001:
            r = np.sqrt(rng.uniform(args.ring_min ** 2, outer ** 2, args.tries))
            th = rng.uniform(0, 2 * np.pi, args.tries)
            xs, ys = cx + r * np.cos(th), cy + r * np.sin(th)
            inside = shapely.contains_xy(region, xs, ys)
            far = tree.query(np.c_[xs, ys])[0] >= args.exclusion
            for x, y, ok in zip(xs, ys, inside & far):
                if ok and not index.too_close(x, y, args.min_spacing):
                    index.add(x, y)
                    features[i] = (x, y, float(np.hypot(x - cx, y - cy)))
                    placed = True
                    break
            if not placed:
                outer *= 1.5
                widened += 1
        if not placed:
            failed += 1
    if failed:
        raise SystemExit(f"{failed} landslides could not be paired; relax --exclusion/--min-spacing or raise --ring-cap")

    pts = gpd.GeoSeries(shapely.points([f[0] for f in features], [f[1] for f in features]),
                        crs=METRIC_CRS).to_crs("EPSG:4326")
    out = []
    for k, (row, geom, f) in enumerate(zip(ls.itertuples(), pts, features), 1):
        date = row.date.strftime("%Y-%m-%dT%H:%M:%S") if hasattr(row.date, "strftime") else str(row.date)
        out.append({
            "type": "Feature",
            "properties": {
                "Event_ID": f"NL_{k:04d}", "Geohaz_E": "NonLandslide", "DATE": date, "date_parsed": date,
                "landslide": 0, "distance_to_nearest_landslide_km": round(f[2] / 1000, 3),
                "nearest_landslide_event_id": int(row.inventory_id), "paired_landslide_id": int(row.inventory_id),
                "pair_distance_km": round(f[2] / 1000, 3), "source": "paired_ring_same_date",
            },
            "geometry": {"type": "Point", "coordinates": [round(geom.x, 8), round(geom.y, 8)]},
        })
    args.output.write_text(json.dumps({"type": "FeatureCollection", "features": out}))
    print(f"Wrote {len(out)} paired negatives to {args.output} (ring widened {widened} times, 0 failures)")


if __name__ == "__main__":
    main()
