"""IMERG antecedent rainfall for the paired negatives, split into slices so several workers can run in parallel.

Wraps gee_imerg_antecedent_rainfall.py (same windows, same cache, same resume logic: a slice that is
interrupted resumes from its .part file, failed points are retried, and a run stops after 5 consecutive
errors). Each slice writes cache/imerg_parts/rain_<start>.csv.

    python scripts/gee_imerg_paired_negatives.py --start 0 --count 1000     # one slice (run several in parallel)
    python scripts/gee_imerg_paired_negatives.py --merge                     # checks completeness, writes the output CSV
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gee_imerg_antecedent_rainfall as rainfall  # noqa: E402

PROJECT_DIR = rainfall.PROJECT_DIR
NEGATIVES_PATH = PROJECT_DIR / "data" / "inventory" / "non_landslide_events.geojson"
SLICES_DIR = PROJECT_DIR / "cache" / "imerg_slices"
PARTS_DIR = PROJECT_DIR / "cache" / "imerg_parts"
OUTPUT_CSV = PROJECT_DIR / "data" / "processed" / "non_landslide_event_antecedent_rainfall.csv"


def merge():
    document = json.loads(NEGATIVES_PATH.read_text())
    expected = [f["properties"]["Event_ID"] for f in document["features"]]
    frames = []
    for part in sorted(PARTS_DIR.glob("rain_*.csv"), key=lambda f: int(f.stem.split("_")[1])):
        start = int(part.stem.split("_")[1])
        frame = pd.read_csv(part)
        frame["event_row"] = frame["event_row"] + start  # slice-local index -> row in the full negatives file
        frames.append(frame)
    frame = pd.concat(frames, ignore_index=True).drop_duplicates("Event_ID", keep="last")
    missing = sorted(set(expected) - set(frame["Event_ID"]))
    bad = frame[frame["rainfall_status"] != "complete"]
    print(f"{len(frame)} rows; expected {len(expected)}; missing {len(missing)}; not complete: {len(bad)}")
    if missing or len(bad):
        print("Missing:", missing[:10], "| not complete:", bad["Event_ID"].tolist()[:10])
        raise SystemExit(1)
    order = {event_id: i for i, event_id in enumerate(expected)}
    frame = frame.assign(_o=frame["Event_ID"].map(order)).sort_values("_o").drop(columns="_o")
    frame.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote {OUTPUT_CSV}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--merge", action="store_true")
    args = p.parse_args()
    if args.merge:
        return merge()

    document = json.loads(NEGATIVES_PATH.read_text())
    features = document["features"]
    end = len(features) if args.count is None else min(len(features), args.start + args.count)
    SLICES_DIR.mkdir(parents=True, exist_ok=True)
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    slice_path = SLICES_DIR / f"slice_{args.start}.geojson"
    slice_path.write_text(json.dumps({"type": "FeatureCollection", "features": features[args.start:end]}))
    rainfall.EVENTS_PATH = slice_path
    rainfall.OUTPUT_CSV = PARTS_DIR / f"rain_{args.start}.csv"
    rainfall.main()


if __name__ == "__main__":
    main()
