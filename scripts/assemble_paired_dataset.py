"""Assemble the model-ready tables once the paired negatives have been extracted.

Inputs (all produced by the extraction wrappers' --merge step, which only succeeds when every row is present):
  cache/paired_negative_event_factors.csv                                factors for the 6,180 paired negatives
  data/processed/non_landslide_event_antecedent_rainfall.csv             IMERG rainfall for the same points (written by gee_imerg_paired_negatives.py --merge)
  data/inventory/non_landslide_events.geojson                            the paired negatives (generate_paired_negatives.py)
  data/processed/landslide_event_factors.csv                             existing raw table (its landslide rows are kept)

Outputs
  data/processed/landslide_event_factors.csv           raw table: 6,180 landslides + 6,180 paired negatives (56 columns)
  data/processed/landslide_event_factors_cleaned.csv   26 columns minus `dist_to_stream` (see docs/METHODS.md, Known issue 5)
  data/processed/landslide_event_factors_cleaning_report.txt

Strict: every one of the 6,180 pairs must be present and consistent, otherwise it stops.
Idempotent: only the landslide rows of an existing raw table are reused, so it can be re-run safely.
    python3 scripts/assemble_paired_dataset.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clean_event_factors import clean  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT_DIR / "data" / "processed"
INVENTORY = PROJECT_DIR / "data" / "inventory"
DROP = ["dist_to_stream"]


def main():
    raw_old = pd.read_csv(PROCESSED / "landslide_event_factors.csv")
    landslides = raw_old[raw_old["landslide"] == 1]
    negatives = pd.read_csv(PROJECT_DIR / "cache" / "paired_negative_event_factors.csv")
    paired = json.loads((INVENTORY / "non_landslide_events.geojson").read_text())["features"]

    assert len(landslides) == 6180 and len(negatives) == 6180, (len(landslides), len(negatives))
    assert (negatives["landslide"] == 0).all()
    assert list(negatives.columns) == list(raw_old.columns), "negatives must have the raw-table schema"
    expected = [f["properties"]["Event_ID"] for f in paired]
    assert set(negatives["Event_ID"]) == set(expected), "negatives do not match the paired inventory"

    # order negatives like the inventory (NL_0001 ...), which is also landslide order
    order = {e: i for i, e in enumerate(expected)}
    negatives = negatives.assign(_o=negatives["Event_ID"].map(order)).sort_values("_o").drop(columns="_o")

    # every negative must carry the date of its paired landslide
    date_of = dict(zip(landslides["inventory_id"].astype(int), landslides["event_date"]))
    pair_dates = [date_of[int(f["properties"]["paired_landslide_id"])] for f in paired]
    assert list(negatives["event_date"]) == pair_dates, "a negative's event_date differs from its paired landslide's"

    raw = pd.concat([landslides, negatives], ignore_index=True)
    raw.to_csv(PROCESSED / "landslide_event_factors.csv", index=False)

    cleaned = clean(raw, DROP)
    cleaned.to_csv(PROCESSED / "landslide_event_factors_cleaned.csv", index=False)

    rain_l = pd.read_csv(PROCESSED / "landslide_event_antecedent_rainfall.csv")
    rain_n = pd.read_csv(PROCESSED / "non_landslide_event_antecedent_rainfall.csv")
    assert list(rain_l.columns) == list(rain_n.columns) and len(rain_n) == 6180 and len(rain_l) == 6180
    assert (rain_n["rainfall_status"] == "complete").all()
    assert set(rain_n["Event_ID"]) == set(expected)

    missing = cleaned.isna().sum()
    missing = missing[missing > 0].sort_values(ascending=False)
    removed = [c for c in raw.columns if c not in cleaned.columns and c not in
               {"TRI", "TPI", "LS_factor", "TWI", "SPI", "NDVI", "lithology_class_name", "land_cover_class_name", "LULC", "lithology"}]
    report = [
        "landslide_event_factors column-only cleaning report (paired-negatives rebuild)",
        "=" * 79, "",
        "Source: data/processed/landslide_event_factors.csv",
        "Output: data/processed/landslide_event_factors_cleaned.csv",
        f"Original shape: {raw.shape[0]} rows x {raw.shape[1]} columns",
        f"Final shape: {cleaned.shape[0]} rows x {cleaned.shape[1]} columns",
        "Rows removed: 0", "",
        "Rebuild: the 6,180 landslide rows are unchanged; the 6,180 negatives are the paired ring sample",
        "(scripts/generate_paired_negatives.py, same date and province as their landslide, >= 2 km from all",
        "23,284 landslide records). Factors were re-extracted for the negatives only.", "",
        "Columns kept: id, event_date, longitude, latitude, landslide + the model factors; index names lower-cased;",
        "numeric lithology / land-cover codes replaced by class names (`lithology`, `lulc`); id = Event_ID for",
        "negatives, LS_<inventory_id> for landslides.", "",
        f"Additionally removed from the model table: {', '.join(DROP)} (HydroSHEDS-branch values are on the wrong",
        "scale for every pre-2020 event; see docs/METHODS.md, Known issue 5).", "",
        "Removed provenance/diagnostic columns (still in the raw table):",
        *[f"- {c}" for c in removed], "",
        "Missing values retained in cleaned file:",
        *[f"- {k}: {v}" for k, v in missing.items()], "",
        "Class balance:",
        *[f"- {k}: {v}" for k, v in cleaned["landslide"].value_counts().sort_index().items()],
        f"Unique id count: {cleaned['id'].nunique()}",
    ]
    (PROCESSED / "landslide_event_factors_cleaning_report.txt").write_text("\n".join(report) + "\n")
    print(f"raw {raw.shape}, cleaned {cleaned.shape}; class balance {cleaned['landslide'].value_counts().to_dict()}")
    print("blank values:", missing.to_dict())
    print("Assembled the paired-negatives dataset.")


if __name__ == "__main__":
    main()
