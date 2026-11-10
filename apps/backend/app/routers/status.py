from fastapi import APIRouter

from .. import status as status_module

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("")
def status():
    """What each pipeline step last produced (factor grid, susceptibility map, live forecast, impact overlay), read
    from the output files; this API does not start or control the jobs."""
    return status_module.pipeline_status()
