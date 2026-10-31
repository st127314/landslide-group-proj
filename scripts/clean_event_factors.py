"""Column-only cleaning of the raw event-factor table -> model-ready table.

Reproduces the steps recorded in data/processed/landslide_event_factors_cleaning_report.txt:
keep the 26 model/ID columns, lower-case the index names, turn the numeric
lithology / land-cover codes into class names (for one-hot encoding), build `id`
(Event_ID, else LS_<inventory_id>, else ROW_<n>); no rows are removed.

    python3 scripts/clean_event_factors.py RAW.csv CLEANED.csv [--drop dist_to_stream]

`--drop` removes extra columns (used to leave out `dist_to_stream`, whose
HydroSHEDS-branch values are on the wrong scale -- see docs/METHODS.md).
"""

import argparse
from pathlib import Path

import pandas as pd

RENAME = {"TRI": "tri", "TPI": "tpi", "LS_factor": "ls_factor", "TWI": "twi", "SPI": "spi", "NDVI": "ndvi",
          "lithology_class_name": "lithology", "land_cover_class_name": "lulc"}
KEEP = ["id", "event_date", "longitude", "latitude", "landslide", "elevation", "slope", "aspect",
        "curvature_general", "curvature_profile", "tri", "tpi", "ls_factor", "upstream_area_km2",
        "dist_to_stream", "twi", "spi", "soil_texture", "soil_clay_pct", "soil_sand_pct",
        "soil_bulk_density", "dist_to_road", "dist_to_river", "lithology", "ndvi", "lulc"]


def clean(raw, drop=()):
    df = raw.copy()
    ids = df["Event_ID"].astype("string")
    ls_id = "LS_" + df["inventory_id"].astype("Int64").astype("string")
    row_id = pd.Series(["ROW_%d" % i for i in range(len(df))], index=df.index, dtype="string")
    df.insert(0, "id", ids.fillna(ls_id).fillna(row_id))
    # Event_ID is numeric text for some legacy rows; the shipped table only used it for NL_xxxx ids
    df.loc[df["inventory_id"].notna(), "id"] = ls_id[df["inventory_id"].notna()]
    df = df.drop(columns=["lithology", "LULC"], errors="ignore")  # numeric codes; class names are used instead
    df = df.rename(columns=RENAME)
    df["landslide"] = df["landslide"].astype(int)
    out = df[[c for c in KEEP if c not in drop]]
    assert out["id"].is_unique, "ids must be unique"
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("raw", type=Path)
    p.add_argument("cleaned", type=Path)
    p.add_argument("--drop", nargs="*", default=[])
    a = p.parse_args()
    out = clean(pd.read_csv(a.raw), a.drop)
    out.to_csv(a.cleaned, index=False)
    print(f"{a.raw.name}: {len(out)} rows -> {a.cleaned} ({out.shape[1]} columns); class balance "
          f"{out['landslide'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
