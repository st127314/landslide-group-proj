"""Check that the factor grid the model is applied to agrees with the table it was trained on.

The saved pipeline guarantees that the same code runs in training and on the map. It cannot guarantee that the same
data arrive: three factor groups reached the grid from a different source, period or extraction than the training
table, and no test noticed (docs/METHODS.md, Known issues 11, 14 and 15). This script is that test. For every factor
of the model it compares the two tables in three ways:

  coverage    the share of blank values on the grid against the share in the training table;
  scale       for factors that are positive, the median on the grid against the median in the training table, taken
              at the same places (each training point and the grid cell it falls in);
  agreement   the rank correlation between the two at the same places (for categorical factors, the share of points
              whose class is the same, and the share of grid cells with a class the model never saw).

A factor FAILS on coverage, on scale or on unseen classes. Weak agreement alone is a WARNING, because a point and the
centre of its 250 m cell are up to 180 m apart and fine-scale factors (topographic position, curvature, aspect)
legitimately differ over that distance. Factors listed in KNOWN fail for a documented reason and do not stop the run;
any other failure does (exit status 1), and predict_susceptibility_grid.py refuses to score the grid.

Run from the project root:   python scripts/check_grid_inputs.py
Inputs:  data/processed/landslide_event_factors_cleaned.csv, data/processed/factor_grid_points/ (local only),
         models/susceptibility/model_metadata.json (the model's factor list)
Output:  results/experiments/grid_input_check.json
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
TRAINING_TABLE = ROOT / "data" / "processed" / "landslide_event_factors_cleaned.csv"
GRID_ROOT = ROOT / "data" / "processed" / "factor_grid_points"
METADATA = ROOT / "models" / "susceptibility" / "model_metadata.json"
OUTPUT = ROOT / "results" / "experiments" / "grid_input_check.json"
GRID_RENAME = {"TRI": "tri", "TPI": "tpi", "LS_factor": "ls_factor", "TWI": "twi", "SPI": "spi", "NDVI": "ndvi", "LULC_current": "lulc"}

MAX_EXTRA_BLANK = 0.10      # the grid may have at most this much more blank values than the training table (as a share)
MAX_MEDIAN_RATIO = 3.0      # the two medians at the same places may differ by at most this factor
MIN_AGREEMENT = 0.20        # Spearman correlation at the same places below this is reported as weak agreement
MAX_UNSEEN_CLASSES = 0.01   # share of grid cells whose class does not occur in the training table
CELL_MATCH_M = 180.0        # a training point belongs to a grid cell if the cell centre is this close (250 m cells)
# Failures that are documented and accepted for the current map. Remove an entry when its cause is fixed.
KNOWN = {
    "upstream_area_km2": "hydrology comes from a 500 m source in training and a 90 m source on the grid (METHODS, Known issue 11)",
    "spi": "hydrology comes from a 500 m source in training and a 90 m source on the grid (METHODS, Known issue 11)",
    "dist_to_road": "blank in most grid tiles and wrong where present (METHODS, Known issue 15)",
    "dist_to_river": "blank in most grid tiles and wrong where present (METHODS, Known issue 15)",
}


def _km(lon, lat, lat0):
    return np.column_stack((np.asarray(lon, float) * 111.32 * np.cos(np.deg2rad(lat0)), np.asarray(lat, float) * 111.32))


def compare(train, grid, numeric, categorical, known=KNOWN):
    """Compare `grid` (px_lon, px_lat and the factors) with `train` (longitude, latitude and the factors).
    Returns {"matched_points": n, "factors": {name: measures and a status of ok, warning, known or fail}}."""
    lat0 = float(train["latitude"].mean())
    dist, cell = cKDTree(_km(grid["px_lon"], grid["px_lat"], lat0)).query(_km(train["longitude"], train["latitude"], lat0), k=1)
    near = dist <= CELL_MATCH_M / 1000.0
    factors = {}
    for name in list(numeric) + list(categorical):
        t, g = train[name], grid[name]
        row = {"type": "numeric" if name in numeric else "categorical",
               "blank_share": {"training": round(float(t.isna().mean()), 4), "grid": round(float(g.isna().mean()), 4)}}
        reasons = []
        if row["blank_share"]["grid"] - row["blank_share"]["training"] > MAX_EXTRA_BLANK:
            reasons.append("coverage")
        here = g.to_numpy()[cell]                         # the grid value at each training point's cell
        both = near & pd.notna(here) & t.notna().to_numpy()
        row["same_place_pairs"] = int(both.sum())
        if name in numeric:
            tv, gv = t.to_numpy(float)[both], np.asarray(here[both], float)
            if len(tv) >= 30:
                row["same_place_median"] = {"training": round(float(np.median(tv)), 3), "grid": round(float(np.median(gv)), 3)}
                rho = pd.Series(tv).corr(pd.Series(gv), method="spearman")
                row["same_place_spearman"] = None if pd.isna(rho) else round(float(rho), 3)
                positive = (t.dropna() > 0).mean() >= 0.99
                if positive and row["same_place_median"]["training"] > 0:
                    ratio = max(row["same_place_median"]["grid"], 1e-12) / row["same_place_median"]["training"]
                    row["same_place_median_ratio"] = round(float(ratio), 3)
                    if not (1 / MAX_MEDIAN_RATIO <= ratio <= MAX_MEDIAN_RATIO):
                        reasons.append("scale")
                weak = row["same_place_spearman"] is not None and row["same_place_spearman"] < MIN_AGREEMENT
            else:
                weak = False
        else:
            seen = set(t.dropna().astype(str))
            row["unseen_class_share"] = round(float((~g.dropna().astype(str).isin(seen)).mean()), 4) if g.notna().any() else 0.0
            if row["unseen_class_share"] > MAX_UNSEEN_CLASSES:
                reasons.append("unseen classes")
            if both.any():
                row["same_place_class_agreement"] = round(float((pd.Series(here[both]).astype(str).to_numpy() == t.astype(str).to_numpy()[both]).mean()), 3)
            weak = False
        if reasons:
            row["status"], row["reasons"] = ("known" if name in known else "fail"), reasons
            if name in known:
                row["note"] = known[name]
        elif weak:
            row["status"], row["reasons"] = "warning", ["weak agreement at the same places"]
        else:
            row["status"] = "ok"
        factors[name] = row
    return {"matched_points": int(near.sum()), "factors": factors}


def load_grid(grid_dir):
    """The factor grid with the column names and class names of the training table."""
    grid = pd.concat([pd.read_csv(f) for f in sorted(grid_dir.glob("tile_*.csv"))], ignore_index=True).rename(columns=GRID_RENAME)
    for column, file in (("lithology", "glim_lithology_classes.json"), ("lulc", "servir_landcover_classes.json")):
        names = {c["value"]: c["name"] for c in json.loads((ROOT / "scripts" / file).read_text())["classes"]}
        grid[column] = grid[column].map(names)          # the grid stores class codes, the training table class names
    return grid


def run(grid_dir=None, write=True, quiet=False):
    """Run the check on the newest factor grid. Returns (report, names of the factors that fail without being known)."""
    meta = json.loads(METADATA.read_text())
    if grid_dir is None:
        dirs = sorted(GRID_ROOT.glob("factor_grid_points_*")) if GRID_ROOT.exists() else []
        if not dirs:
            sys.exit(f"No factor grid in {GRID_ROOT}")
        grid_dir = dirs[-1]
    train, grid = pd.read_csv(TRAINING_TABLE), load_grid(Path(grid_dir))
    report = compare(train, grid, meta["numeric_features"], meta["categorical_features"])
    counts = {s: sum(r["status"] == s for r in report["factors"].values()) for s in ("ok", "warning", "known", "fail")}
    report = {"grid": Path(grid_dir).name, "cells": int(len(grid)), "training_rows": int(len(train)), "model": meta["best_model"],
              "thresholds": {"max_extra_blank_share": MAX_EXTRA_BLANK, "max_median_ratio": MAX_MEDIAN_RATIO, "min_spearman": MIN_AGREEMENT,
                             "max_unseen_class_share": MAX_UNSEEN_CLASSES, "cell_match_m": CELL_MATCH_M},
              "summary": counts, **report}
    if write:
        OUTPUT.write_text(json.dumps(report, indent=1))
    if not quiet:
        print(f"{'factor':20s} {'status':8s} {'blank, training / grid':>22s}  {'same-place agreement':>20s}  {'median, training / grid':>26s}")
        for name, r in report["factors"].items():
            agreement = f"rho {r['same_place_spearman']:.2f}" if r.get("same_place_spearman") is not None else (
                f"{100 * r['same_place_class_agreement']:.0f}% same class" if "same_place_class_agreement" in r else "")
            medians = f"{r['same_place_median']['training']:g} / {r['same_place_median']['grid']:g}" if "same_place_median" in r else ""
            print(f"{name:20s} {r['status']:8s} {100 * r['blank_share']['training']:9.1f}% / {100 * r['blank_share']['grid']:5.1f}%  {agreement:>20s}  {medians:>26s}"
                  + (f"   {', '.join(r['reasons'])}" if r.get("reasons") else ""))
        print(f"{counts['ok']} ok, {counts['warning']} with weak agreement, {counts['known']} known mismatches, {counts['fail']} new failures"
              + (f"; wrote {OUTPUT.relative_to(ROOT)}" if write else ""))
    return report, [n for n, r in report["factors"].items() if r["status"] == "fail"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--grid-dir", type=Path, default=None, help="factor grid directory (default: the newest one)")
    args = parser.parse_args()
    _, failed = run(args.grid_dir)
    if failed:
        sys.exit("Grid inputs differ from the training table for: " + ", ".join(failed))
