from fastapi import APIRouter, HTTPException

from .. import data

router = APIRouter(prefix="/api/model", tags=["model"])


@router.get("")
def model_info():
    """Full model_metadata.json from the susceptibility-modeling notebook:
    the selected model, its hyperparameters, nested-CV results per candidate
    model, held-out test results, thresholds, and feature lists. See
    notebooks/landslide_susceptibility_modeling.ipynb for the methodology
    that produced this (nested spatial cross-validation, calibration,
    temporal hold-out check)."""
    metadata = data.model_metadata()
    if metadata is None:
        raise HTTPException(status_code=404, detail="Model metadata not found. Run the modeling notebook first.")
    return metadata


@router.get("/comparison")
def model_comparison():
    """cv_results (nested spatial CV, used for model selection) alongside
    test_results (single held-out evaluation), keyed by model name for an
    easy side-by-side table."""
    metadata = data.model_metadata()
    if metadata is None:
        raise HTTPException(status_code=404, detail="Model metadata not found.")
    cv_by_model = {r["model"]: r for r in metadata.get("cv_results", [])}
    test_by_model = {r["model"]: r for r in metadata.get("test_results", [])}
    names = sorted(set(cv_by_model) | set(test_by_model))
    return {
        "best_model": metadata.get("best_model"),
        "models": [
            {"model": name, "cv": cv_by_model.get(name), "test": test_by_model.get(name)}
            for name in names
        ],
    }
