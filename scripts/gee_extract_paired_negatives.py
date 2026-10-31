"""Extract conditioning factors for the paired negatives only.

Wraps gee_landslide_factors.py (same layers, same event-date cut-offs, same
DEM / hydrology era logic) but samples just
data/inventory/non_landslide_events.geojson with label 0, so the 6,180
landslide rows already in data/processed/landslide_event_factors.csv do not have
to be re-extracted.

A run can be split into slices with --start/--count; each slice is written to its
own file (cache/paired_negative_parts/part_<start>.csv).

Resumable: every batch is flushed to disk as it arrives, and on restart each slice
reads the Event_IDs already in its file, extracts only the missing ones and APPENDS
them. If Earth Engine credentials/network fail, the run stops at once (before the
next batch) with exit code 2 and nothing already fetched is lost -- just re-run the
same command. Points Earth Engine could not return (memory-limit skips) are retried on
every re-run. `--merge` checks completeness/uniqueness and writes the output CSV.

    python scripts/gee_extract_paired_negatives.py --start 0 --count 100     # smoke test
    python scripts/gee_extract_paired_negatives.py                           # everything
    python scripts/gee_extract_paired_negatives.py --merge
"""

import argparse
import csv
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gee_landslide_factors as factors  # noqa: E402

PROJECT_DIR = factors.PROJECT_DIR
NEGATIVES_PATH = PROJECT_DIR / "data" / "inventory" / "non_landslide_events.geojson"
OUTPUT_CSV = PROJECT_DIR / "cache" / "paired_negative_event_factors.csv"  # intermediate; assemble_paired_dataset.py reads it
PARTS_DIR = PROJECT_DIR / "cache" / "paired_negative_parts"


class AppendingCsvWriter(factors.ChunkedCsvWriter):
    """ChunkedCsvWriter that appends to an existing slice file instead of truncating it."""

    def __init__(self, path, factor_names):
        self.path, self.factor_names, self.total, self.missing = path, factor_names, 0, 0
        path.parent.mkdir(parents=True, exist_ok=True)
        has_rows = path.exists() and path.stat().st_size > 0
        if has_rows:
            heal_truncated_tail(path)
        self._handle = path.open("a", newline="", encoding="utf-8")
        columns = [*factors.EVENT_PROPERTIES, "longitude", "latitude", "landslide", *factor_names,
                   "lithology_class_name", *factors.TEMPORAL_COLUMNS]
        self._writer = csv.DictWriter(self._handle, fieldnames=columns, extrasaction="ignore")
        if not has_rows:
            self._writer.writeheader()
            self._handle.flush()


def heal_truncated_tail(path):
    """If a previous run was killed mid-write, drop the incomplete last line."""
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        path.write_bytes(data[: data.rfind(b"\n") + 1])
        print(f"{path.name}: removed an incomplete last line left by an interrupted run", flush=True)


def done_event_ids(path):
    if not (path.exists() and path.stat().st_size > 0):
        return set()
    heal_truncated_tail(path)
    return set(pd.read_csv(path, usecols=["Event_ID"], dtype=str)["Event_ID"])


def credentials_ok():
    """Cheap round trip that fails fast if the key/token/network is broken."""
    try:
        factors.ee.Number(1).getInfo()
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means we must stop, not skip
        print(f"Earth Engine call failed ({exc!r}).", flush=True)
        return False


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--count", type=int, default=None, help="Rows to extract (default: all remaining).")
    p.add_argument("--slice", type=int, default=1000, help="Rows per output slice file (default 1000).")
    p.add_argument("--batch-size", type=int, default=None,
                   help="Points per Earth Engine request (default: gee_landslide_factors.SAMPLE_BATCH_SIZE = 100). "
                        "Use ~25 if requests keep timing out.")
    p.add_argument("--retry-missing", action="store_true",
                   help="Fetch every Event_ID that is still missing from ALL slice files in ONE request "
                        "(written to part_9000.csv); ignores --start/--count/--slice.")
    p.add_argument("--merge", action="store_true", help="Merge existing slice files into the output CSV and exit.")
    return p.parse_args(argv)


def merge():
    parts = sorted(PARTS_DIR.glob("part_*.csv"), key=lambda f: int(f.stem.split("_")[1]))
    if not parts:
        raise SystemExit(f"No slice files in {PARTS_DIR}")
    frame = pd.concat([pd.read_csv(f) for f in parts], ignore_index=True)
    expected = {f["properties"]["Event_ID"] for f in factors.load_geojson_features(NEGATIVES_PATH)}
    dup = int(frame["Event_ID"].duplicated().sum())
    missing = sorted(expected - set(frame["Event_ID"]))
    if dup:
        frame = frame.drop_duplicates("Event_ID", keep="last")
    print(f"{len(parts)} slice files, {len(frame)} unique rows; expected {len(expected)}; "
          f"duplicates removed: {dup}; missing: {len(missing)}")
    if missing:
        print("Missing Event_IDs (re-run the extraction to fetch them):", missing[:10], "..." if len(missing) > 10 else "")
        raise SystemExit(1)
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote {OUTPUT_CSV}")


def main(argv=None):
    args = parse_args(argv)
    if args.merge:
        return merge()

    factors.initialize_gee(factors.project_path(factors.SERVICE_ACCOUNT_KEY), factors.GEE_PROJECT)
    study_area = factors.geojson_to_feature_collection(factors.project_path(factors.data_path))
    aoi = study_area.geometry()

    srtm, alos, dem_source = factors.dem_sources(aoi)
    srtm_layers = factors.build_factor_layers(aoi, srtm)
    alos_layers = factors.build_factor_layers(aoi, alos)
    merit_layers = factors.build_factor_layers(aoi, alos, use_merit=True)
    srtm_layers["dem_source"] = factors.ee.Image.constant(1).updateMask(srtm.mask())
    alos_layers["dem_source"] = dem_source
    merit_layers["dem_source"] = dem_source

    features = factors.load_geojson_features(NEGATIVES_PATH, event_dates=True)
    end = len(features) if args.count is None else min(len(features), args.start + args.count)
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.retry_missing:
        have = set()
        for f in PARTS_DIR.glob("part_*.csv"):
            have |= done_event_ids(f)
        todo = [f for f in features if f["properties"]["Event_ID"] not in have]
        part = PARTS_DIR / "part_9000.csv"
        print(f"retry-missing: {len(todo)} points still missing -> one request", flush=True)
        if todo and credentials_ok():
            writer = AppendingCsvWriter(part, list(alos_layers))
            try:
                batch = factors.fetch_samples_chunk(todo, 0, len(todo), aoi, srtm_layers, alos_layers, merit_layers, 0)
                writer.write_batch(batch)
                print(f"retry-missing: retrieved {len(batch)}/{len(todo)} rows", flush=True)
            finally:
                writer.close()
        return
    incomplete = 0
    for lo in range(args.start, end, args.slice):
        hi = min(lo + args.slice, end)
        part = PARTS_DIR / f"part_{lo}.csv"
        done = done_event_ids(part)
        todo = [f for f in features[lo:hi] if f["properties"]["Event_ID"] not in done]
        print(f"slice {lo}-{hi}: {len(done)} already extracted, {len(todo)} to do", flush=True)
        writer = AppendingCsvWriter(part, list(alos_layers))
        try:
            step = args.batch_size or factors.SAMPLE_BATCH_SIZE
            for i in range(0, len(todo), step):
                if not credentials_ok():
                    print("Stopped before the next batch; everything fetched so far is saved. "
                          "Fix credentials/network and re-run the same command to resume.", flush=True)
                    raise SystemExit(2)
                batch = factors.fetch_samples_chunk(todo, i, min(step, len(todo) - i), aoi,
                                                    srtm_layers, alos_layers, merit_layers, 0)
                writer.write_batch(batch)
                print(f"slice {lo}-{hi}: {len(done) + i + len(batch)}/{hi - lo} rows", flush=True)
        finally:
            writer.close()
        left = len(features[lo:hi]) - len(done_event_ids(part))
        incomplete += left
        print(f"slice {lo}-{hi}: {'COMPLETE' if not left else f'{left} points still missing (re-run to retry)'}", flush=True)
    print("Done." if not incomplete else f"{incomplete} points missing in total; re-run the same command.",
          "Then run with --merge to build", OUTPUT_CSV)
    if incomplete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
