"""Experiment tracking with MLflow, kept on the local machine.

The files in models/ and results/ remain the record the report and the dashboard read. MLflow sits beside them so that
runs can be compared side by side and the selected model has a version history:

  experiment "landslide-susceptibility"   one parent run per model comparison (the validation design, the data and code
                                           versions, the selected model and its artefacts) with one child run per
                                           candidate model (tuned hyperparameters, nested-CV and hold-out metrics);
                                           the selected pipeline is registered as model "landslide-susceptibility".
  experiment "landslide-experiments"      one run per configuration of experiments E1-E7 and F1-F5.

The store is local and is not part of the git repository: mlflow.db (runs, parameters, metrics, the model registry) and
mlartifacts/ (files) in the project root.

    python notebooks/tracking.py                                  # log the saved results (seconds; no retraining)
    python notebooks/tracking.py --experiments                    # only E1-E7 and F1-F5, after the notebook has run
    mlflow ui --backend-store-uri sqlite:///mlflow.db             # then open http://127.0.0.1:5000

The modelling notebook calls log_model_comparison() in its last step, so a retrain is logged when it happens. If MLflow
is not installed the notebook says so and carries on.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "susceptibility"
RESULTS = ROOT / "results" / "experiments"
TRAINING_TABLE = ROOT / "data" / "processed" / "landslide_event_factors_cleaned.csv"
TRACKING_URI = f"sqlite:///{ROOT / 'mlflow.db'}"
ARTIFACT_ROOT = (ROOT / "mlartifacts").as_uri()
REGISTERED_MODEL = "landslide-susceptibility"
# The types inside the saved pipeline that are not plain scikit-learn estimators: the project's own two transformers
# (notebooks/susc_utils.py) and the seeded mutual-information scorer of the feature-selection step.
TRUSTED_TYPES = ["functools.partial", "numpy.dtype", "sklearn.feature_selection._mutual_info.mutual_info_classif",
                 "susc_utils.IQRClipper", "susc_utils.add_aspect_features"]


def _mlflow():
    import mlflow
    mlflow.set_tracking_uri(TRACKING_URI)
    return mlflow


def _experiment(mlflow, name):
    found = mlflow.get_experiment_by_name(name)
    return found.experiment_id if found else mlflow.create_experiment(name, artifact_location=f"{ARTIFACT_ROOT}/{name}")


def _versions():
    """What a run was computed from: the commit of the code and the checksum of the training table."""
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "unknown", False
    digest = hashlib.sha256(TRAINING_TABLE.read_bytes()).hexdigest()[:16] if TRAINING_TABLE.exists() else "missing"
    return {"git_commit": commit + ("+uncommitted" if dirty else ""), "training_table_sha256": digest}


def _numbers(row, prefix):
    return {f"{prefix}{k}": float(v) for k, v in row.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def log_model_comparison():
    """Log the notebook's model comparison from models/susceptibility/model_metadata.json. Returns the parent run id."""
    mlflow = _mlflow()
    meta = json.loads((MODEL_DIR / "model_metadata.json").read_text())
    best = meta["best_model"]
    cv = {r["model"]: r for r in meta["cv_results"]}
    test = {r["model"]: r for r in meta["test_results"]}
    versions = _versions()
    with mlflow.start_run(experiment_id=_experiment(mlflow, "landslide-susceptibility"), run_name=f"model comparison ({best})") as parent:
        mlflow.set_tags({**versions, "selection_rule": meta["selection"], "selected_model": best, "kind": "model comparison"})
        mlflow.log_params({
            "n_candidate_models": len(cv), "n_features": len(meta["feature_columns"]), "excluded_columns": ", ".join(meta["excluded_columns"]),
            "spatial_block_deg": meta["spatial_block_deg"], "spatial_buffer_km": meta["spatial_buffer_km"], "holdout_fold": meta["holdout_fold"],
            "train_rows": sum(meta["training_class_counts"].values()), "test_rows": sum(meta["test_class_counts"].values()),
            "embargoed_training_rows": meta["embargoed_training_rows"],
        })
        mlflow.log_metrics({**_numbers(cv[best], "cv_"), **_numbers(test[best], "holdout_"),
                            "threshold_raw": meta["threshold_raw_probability"], "threshold_calibrated": meta["threshold_calibrated_probability"]})
        mlflow.log_artifact(str(MODEL_DIR / "model_metadata.json"))
        figure = ROOT / "results" / "figures" / "3_model_comparison.png"
        if figure.exists():
            mlflow.log_artifact(str(figure))
        calibrator = MODEL_DIR / f"{best}_isotonic_calibrator.joblib"
        if calibrator.exists():
            mlflow.log_artifact(str(calibrator))
        _register_selected(mlflow, meta, best)
        for name in sorted(cv, key=lambda m: -cv[m]["roc_auc_mean"]):
            with mlflow.start_run(experiment_id=parent.info.experiment_id, run_name=name, nested=True):
                mlflow.set_tags({**versions, "selected": str(name == best).lower(), "kind": "candidate model"})
                mlflow.log_params({"model": name, **{k.replace("model__", "").replace("select__", "select_"): v
                                                     for k, v in meta["best_params"].get(name, {}).items()}})
                mlflow.log_metrics({**_numbers(cv[name], "cv_"), **_numbers(test.get(name, {}), "holdout_")})
        return parent.info.run_id


def _register_selected(mlflow, meta, best):
    """Store the fitted pipeline as an MLflow model and add it to the local registry (a new version on each retrain).
    The trained pipeline is not in git, so on a checkout without it only the metrics are logged."""
    pipeline_file = MODEL_DIR / f"{best}_landslide_susceptibility_pipeline.joblib"
    if not pipeline_file.exists():
        print(f"MLflow: {pipeline_file.name} is not on this machine; logged the metrics only.")
        return
    import joblib
    import mlflow.sklearn
    import pandas as pd
    sys.path.insert(0, str(ROOT / "notebooks"))          # the pipeline refers to notebooks/susc_utils.py
    pipeline = joblib.load(pipeline_file)
    example = None
    if TRAINING_TABLE.exists():         # numeric factors as floats, so the stored input schema allows missing values
        example = pd.read_csv(TRAINING_TABLE, nrows=5)[meta["feature_columns"]]
        example[meta["numeric_features"]] = example[meta["numeric_features"]].astype(float)
    options = dict(name="model", registered_model_name=REGISTERED_MODEL, input_example=example,
                   code_paths=[str(ROOT / "notebooks" / "susc_utils.py")])
    try:        # current MLflow stores scikit-learn models with skops, which loads only the types it is told to trust
        mlflow.sklearn.log_model(pipeline, skops_trusted_types=TRUSTED_TYPES, **options)
    except TypeError:       # an older MLflow, which pickles the model and has no such option
        mlflow.sklearn.log_model(pipeline, **options)


def log_experiments():
    """Log experiments E1-E7 and F1-F5 from results/experiments/*.json, one run per configuration."""
    mlflow = _mlflow()
    results = json.loads((RESULTS / "results.json").read_text())
    follow = json.loads((RESULTS / "followup.json").read_text())
    experiment_id = _experiment(mlflow, "landslide-experiments")
    versions = _versions()
    count = 0

    def run(experiment, variant, model, metrics):
        nonlocal count
        with mlflow.start_run(experiment_id=experiment_id, run_name=f"{experiment} | {variant} | {model}"):
            mlflow.set_tags({**versions, "experiment": experiment})
            mlflow.log_params({"experiment": experiment, "variant": variant, "model": model})
            mlflow.log_metrics({k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))})
        count += 1

    cv = lambda r: {"cv_roc_auc_mean": r["auc_mean"], "cv_roc_auc_sd": r["auc_sd"], "cv_pr_auc_mean": r.get("pr_mean")}
    for model, r in results["E2"].items():
        run("E2 models", "19 factors, fixed hyperparameters", model, cv(r))
    for model, variants in results["E1"].items():
        for variant, r in variants.items():
            run("E1 preprocessing", variant, model, cv(r))
    for model in results["E3_drop"]:
        for variant, r in {**results["E3_cumulative"][model], **results["E3_drop"][model], "with ndvi (leak)": results["E3_with_ndvi"][model]}.items():
            run("E3 factor groups", variant, model, cv(r))
    for design in ("random (v1)", "paired (current)"):
        for model, r in results["E4"][design].items():
            run("E4 negative sampling", design, model, cv(r))
    for province, r in results["E5"].items():
        for model in ("lr", "svm"):
            run("E5 leave one province out", province, model, {"roc_auc": r[model], "n_test": r["n_test"], "n_train": r["n_train"]})
    for model in ("lr", "svm"):
        run("E6 temporal transfer", "time only", model, {"roc_auc": results["E6"][f"time_only_{model}"]})
        run("E6 temporal transfer", "time + 5 km buffer", model, {"roc_auc": results["E6"][f"time_plus_buffer_{model}"]})
        run("E7 label noise", "5% of training labels flipped", model, {"cv_roc_auc_clean": results["E7"][model]["clean"], "cv_roc_auc_noise": results["E7"][model]["noise5_mean"]})
    for model in ("lr", "lrfs", "svm", "rf"):
        for variant in ("all_points", "thinned"):
            r = follow["F1"][model][variant]
            run("F1 near-duplicate thinning", variant, model, {**cv(r), "holdout_roc_auc": r["holdout_auc"]})
    for model in ("lr", "lrfs", "svm"):
        for variant, r in follow["F2"][model].items():
            run("F2 decision value on the map", variant, model, {**cv(r["cv"]), "holdout_roc_auc": r["holdout_auc"], "top20_point_based": r["top20"],
                                                                  "top20_cell_based": r["cell_top20"], "top10_cell_based": r["cell_top10"]})
    for model, designs in follow["F3"]["cv"].items():
        for design, r in designs.items():
            run("F3 matched negatives", design, model, cv(r))
        r = follow["F3"]["ring_model_on_matched_negatives"][model]
        run("F3 matched negatives", "trained on ring, tested on matched", model, {"cv_roc_auc_mean": r["auc_mean"], "cv_roc_auc_sd": r["auc_sd"]})
    for model in ("lr", "lrfs", "svm"):
        for variant in ("with", "without"):
            r = follow["F4"]["indicators"][model][variant]
            run("F4 missing-value indicators", f"{variant} indicators", model, {**cv(r), "holdout_roc_auc": r["holdout_auc"]})
    interval = follow["F4"]["interval"]
    run("F4 hold-out interval", "point and 0.1 degree sub-block bootstrap", interval["model"], {
        "holdout_roc_auc": interval["holdout_auc"], "point_bootstrap_low": interval["point_bootstrap"][0], "point_bootstrap_high": interval["point_bootstrap"][1],
        "sub_block_bootstrap_low": interval["sub_block_bootstrap"][0], "sub_block_bootstrap_high": interval["sub_block_bootstrap"][1]})
    for factor in ("dist_to_road", "dist_to_river"):
        r = follow["F5"][factor]
        run("F5 grid distances", factor, "none", {"tiles_without_any_value": r["tiles_without_any_value"], "cells_without_value": r["cells_without_value"],
                                                   "training_median_m": r["same_place"]["training_median_m"], "grid_median_m": r["same_place"]["grid_median_m"],
                                                   "spearman": r["same_place"]["spearman"]})
    return count


if __name__ == "__main__":
    only_experiments = "--experiments" in sys.argv[1:]      # the notebook has already logged the model comparison
    try:
        run_id = None if only_experiments else log_model_comparison()
        n = log_experiments()
    except ModuleNotFoundError as exc:
        sys.exit(f"{exc.name} is not installed: pip install mlflow")
    print(f"Logged {'the model comparison (run ' + run_id + ') and ' if run_id else ''}{n} experiment runs to {TRACKING_URI}")
    print(f"View them with: mlflow ui --backend-store-uri {TRACKING_URI}")
