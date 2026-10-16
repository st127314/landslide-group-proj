"""Read-only API over the landslide-susceptibility project's pipeline
outputs (data/, models/, results/) for the Next.js frontend in
apps/frontend. Never writes into the data pipeline -- every endpoint is a GET.

Run: uvicorn app.main:app --reload --port 8000   (from apps/backend/)
Docs: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import impact, model, overview, status

app = FastAPI(
    title="Landslide Impact API",
    description="Read-only API over the landslide susceptibility / rainfall-trigger / impact pipeline outputs.",
    version="0.1.0",
)

# Dev-friendly: the Next.js dev server runs on a different port. Tighten this
# (specific origins) before deploying anywhere public.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(overview.router)
app.include_router(model.router)
app.include_router(impact.router)
app.include_router(status.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
