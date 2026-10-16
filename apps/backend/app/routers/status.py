from fastapi import APIRouter

from .. import status as status_module

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("")
def status():
    """Live progress of the background data-pipeline jobs (factor-grid tile
    download, rainfall extraction) and which downstream pieces (susceptibility
    raster, rainfall trigger model, combined impact overlay) are still
    pending. Read directly from the running jobs' own logs/output directories
    -- this API does not start or control them."""
    return status_module.pipeline_status()
