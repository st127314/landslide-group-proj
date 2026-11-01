from fastapi import APIRouter

from .. import data, status

router = APIRouter(prefix="/api/overview", tags=["overview"])


def _manifest_building_count():
    """Small servers skip the 140 MB footprints layer (apps/deploy/sync-data.sh SKIP_BUILDINGS=1); the count is still
    recorded in data/external/manifest.json by download_external_data.py."""
    manifest = data.external_manifest() or {}
    return manifest.get("outputs", {}).get("buildings_aoi", {}).get("features")


@router.get("")
def overview():
    metadata = data.model_metadata()
    sample_counts = data.susceptibility_sample_counts()
    facility_counts = data.facility_breakdown()
    worldpop = data.worldpop_manifest()
    buildings = data.buildings_index()

    best_model_name = metadata.get("best_model") if metadata else None
    best_row = None
    if metadata and metadata.get("test_results"):
        best_row = next(
            (r for r in metadata["test_results"] if r.get("model") == best_model_name), None)

    return {
        "study_area": "Southern Thailand (14 provinces)",
        "landslide_events": int(sample_counts.get(1, 0)) if sample_counts is not None else None,
        "non_landslide_samples": int(sample_counts.get(0, 0)) if sample_counts is not None else None,
        "buildings_mapped": len(buildings.entries) if buildings.loaded else _manifest_building_count(),
        "facilities_mapped": sum(facility_counts.values()) if facility_counts is not None else None,
        "facility_breakdown": facility_counts or {},
        "population_estimate": (worldpop or {}).get("stats", {}).get("total_population"),
        "population_source_year": 2020,
        "best_model": best_model_name,
        "best_model_roc_auc": best_row.get("roc_auc") if best_row else None,
        "best_model_selection": metadata.get("selection") if metadata else None,
        "pipeline_status": status.pipeline_status(),
    }
