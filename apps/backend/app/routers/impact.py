from fastapi import APIRouter, HTTPException, Query

from .. import data, scenario as scenario_logic

router = APIRouter(prefix="/api/impact", tags=["impact"])

DEFAULT_BUILDINGS_LIMIT = 5000
MAX_BUILDINGS_LIMIT = 20000


@router.get("/boundary")
def boundary():
    geojson = data.boundary_geojson()
    if geojson is None:
        raise HTTPException(status_code=404, detail="Boundary file not found.")
    return geojson


@router.get("/susceptibility")
def susceptibility():
    """Point-level susceptibility scores (the sampled landslide/non-landslide
    inventory, scored by the trained model). NOT the full raster susceptibility
    map -- that still needs the factor-grid download + a grid prediction script
    to finish; see /api/status."""
    geojson = data.susceptibility_geojson()
    if geojson is None:
        raise HTTPException(status_code=404, detail="Susceptibility scores not found. Run the modeling notebook first.")
    return geojson


@router.get("/facilities")
def facilities():
    geojson = data.facilities_geojson()
    if geojson is None:
        raise HTTPException(status_code=404, detail="Facilities layer not found. Run download_external_data.py first.")
    return geojson


@router.get("/buildings")
def buildings(
    min_lon: float = Query(..., description="Map viewport bounding box (WGS84)"),
    min_lat: float = Query(...),
    max_lon: float = Query(...),
    max_lat: float = Query(...),
    limit: int = Query(DEFAULT_BUILDINGS_LIMIT, le=MAX_BUILDINGS_LIMIT),
):
    """Buildings footprints are ~426k polygons (~147 MB as GeoJSON) -- far too
    large to send in one response, so this always requires a bounding box
    (typically the current map viewport) and caps how many features come
    back. Zoom in / pan to a smaller area if `truncated` is true."""
    index = data.buildings_index()
    if not index.loaded:
        raise HTTPException(status_code=404, detail="Buildings layer not found. Run download_external_data.py first.")
    features = index.query((min_lon, min_lat, max_lon, max_lat), limit + 1)
    truncated = len(features) > limit
    return {
        "type": "FeatureCollection",
        "features": features[:limit],
        "truncated": truncated,
    }


@router.get("/susceptibility-grid")
def susceptibility_grid(
    min_lon: float = Query(..., description="Map viewport bounding box (WGS84)"),
    min_lat: float = Query(...),
    max_lon: float = Query(...),
    max_lat: float = Query(...),
    limit: int = Query(DEFAULT_BUILDINGS_LIMIT, le=MAX_BUILDINGS_LIMIT),
):
    """The full 250 m susceptibility map (~1.14M points from
    scripts/predict_susceptibility_grid.py), bbox-queried like /buildings --
    this is the actual susceptibility *map*, as opposed to /susceptibility's
    point-level training/test samples."""
    index = data.susceptibility_grid_index()
    if not index.loaded:
        raise HTTPException(status_code=404,
                            detail="Susceptibility grid not found. Run scripts/predict_susceptibility_grid.py first.")
    features, truncated = index.query((min_lon, min_lat, max_lon, max_lat), limit)
    return {"type": "FeatureCollection", "features": features, "truncated": truncated}


@router.get("/susceptibility-grid/metadata")
def susceptibility_grid_metadata():
    metadata = data.susceptibility_map_metadata()
    if metadata is None:
        raise HTTPException(status_code=404, detail="Susceptibility map metadata not found.")
    return metadata


@router.get("/tambons")
def tambons():
    """Tambon (sub-district) polygons clipped to the study area, for
    choropleth rendering alongside /live-forecast."""
    geojson = data.tambon_boundary_geojson()
    if geojson is None:
        raise HTTPException(status_code=404, detail="Tambon boundary not found. Run scripts/clip_tambon_boundaries.py first.")
    return geojson


@router.get("/live-forecast")
def live_forecast():
    """GFS forecast rainfall per tambon (next 24 / 48 / 72 h from now) with its 24 h rainfall class, from
    scripts/run_live_gfs_forecast.py (run periodically -- this endpoint only reads the latest output, never
    calls Earth Engine on the request path). The rainfall classes are assumed thresholds; read `limitations`."""
    result = data.live_forecast_data()
    if result is None:
        raise HTTPException(status_code=404,
                            detail="No live forecast yet. Run scripts/run_live_gfs_forecast.py.")
    return result


@router.get("/overlay")
def overlay():
    """Live impact overlay per tambon and province: terrain susceptibility tier x GFS 24 h forecast rainfall class
    x exposed buildings, facilities and population, from scripts/build_impact_overlay.py. `metadata.limitations`
    explains why the live impact class is a transparent triage rule, not a calibrated probability."""
    result = data.impact_overlay_data()
    if result is None:
        raise HTTPException(status_code=404,
                            detail="No impact overlay yet. Run scripts/build_impact_overlay.py.")
    return result


@router.get("/scenario")
def scenario(
    rain_24h_mm: float | None = Query(None, ge=0, le=scenario_logic.MAX_RAIN_24H_MM,
                                       description="What-if 24 h rainfall in mm; omit for the live GFS forecast"),
    province: str | None = Query(None, description="Apply the rainfall to this province only (exact English name)"),
    limit: int = Query(25, ge=1, le=200),
):
    """What-if rainfall scenario on the live-impact overlay: replaces the 24 h rainfall of every tambon in scope
    (all tambons, or one province) with `rain_24h_mm`, then re-applies the overlay's rule (terrain tier + the rain
    class against each tambon's own wet-day percentiles). Runs in memory on the stored overlay: no Earth Engine
    call, no model, no assistant. See `limitations` in the response."""
    overlay = data.impact_overlay_data()
    if overlay is None:
        raise HTTPException(status_code=404, detail="No impact overlay yet. Run scripts/build_impact_overlay.py.")
    known = {t.get("NAME_1") for t in overlay["tambons"]}
    if province is not None and province not in known:
        raise HTTPException(status_code=422, detail=f"Unknown province {province!r}. Known: {sorted(k for k in known if k)}")
    return scenario_logic.run(overlay, rain_24h_mm, province, limit)


@router.get("/population")
def population():
    """Summary stats only (total/mean/max population in the study area).
    The raster itself (data/external/worldpop_2020_UNadj_constrained_aoi.tif) is
    not tiled/served yet -- a raster tile server (e.g. titiler) is the
    straightforward way to add it to the map later."""
    manifest = data.worldpop_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="WorldPop manifest not found. Run download_worldpop_population.py first.")
    return manifest
