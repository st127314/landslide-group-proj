# Forecast refresh job: GFS rainfall per tambon from Earth Engine, then the live impact overlay re-applied to it.
# Built from the repository root (it needs two files from scripts/). Same base image as the backend, so on the server
# it only adds the pip layer. Runs as a one-shot container from cron (apps/deploy/install-forecast-cron.sh).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /srv/project
COPY apps/forecast/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY scripts/run_live_gfs_forecast.py scripts/refresh_impact_overlay.py ./scripts/

CMD ["sh", "-c", "python scripts/run_live_gfs_forecast.py && python scripts/refresh_impact_overlay.py"]
