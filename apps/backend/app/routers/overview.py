from fastapi import APIRouter

from .. import data, status

router = APIRouter(prefix="/api/overview", tags=["overview"])


@router.get("")
def overview():
    metadata = data.model_metadata()
    susceptibility = data.susceptibility_geojson()
    facilities = data.facilities_geojson()
    worldpop = data.worldpop_manifest()
    buildings = data.buildings_index()

    best_model_name = metadata.get("best_model") if metadata else None
    best_row = None
    if metadata and metadata.get("test_results"):
        best_row = next(
            (r for r in metadata["test_results"] if r.get("model") == best_model_name), None)

    facility_counts = {}
    if facilities:
        for feature in facilities["features"]:
            fclass = feature["properties"].get("fclass", "other")
            facility_counts[fclass] = facility_counts.get(fclass, 0) + 1

    return {
        "study_area": "Southern Thailand (14 provinces)",
        "landslide_events": sum(
            1 for f in (susceptibility or {}).get("features", [])
            if f["properties"].get("landslide") == 1) if susceptibility else None,
        "non_landslide_samples": sum(
            1 for f in (susceptibility or {}).get("features", [])
            if f["properties"].get("landslide") == 0) if susceptibility else None,
        "buildings_mapped": len(buildings.entries) if buildings.loaded else None,
        "facilities_mapped": len(facilities["features"]) if facilities else None,
        "facility_breakdown": facility_counts,
        "population_estimate": (worldpop or {}).get("stats", {}).get("total_population"),
        "population_source_year": 2020,
        "best_model": best_model_name,
        "best_model_roc_auc": best_row.get("roc_auc") if best_row else None,
        "best_model_selection": metadata.get("selection") if metadata else None,
        "pipeline_status": status.pipeline_status(),
    }
