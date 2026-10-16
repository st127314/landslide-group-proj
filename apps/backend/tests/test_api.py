from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
BBOX = "min_lon=98.9&min_lat=7.9&max_lon=99.5&max_lat=8.5"


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_overview_counts_fixture_data():
    body = client.get("/api/overview").json()
    assert body["landslide_events"] == 1 and body["non_landslide_samples"] == 1
    assert body["buildings_mapped"] == 5 and body["facilities_mapped"] == 2
    assert body["population_estimate"] == 1234.0
    assert body["best_model"] == "gradient_boosting"
    assert all(job["done"] for job in body["pipeline_status"].values())


def test_model_endpoints():
    assert client.get("/api/model").json()["best_model"] == "gradient_boosting"
    models = {m["model"] for m in client.get("/api/model/comparison").json()["models"]}
    assert models == {"gradient_boosting", "svm_rbf"}


def test_boundary_and_tambons_are_geojson():
    for path in ("/api/impact/boundary", "/api/impact/tambons", "/api/impact/facilities"):
        assert client.get(path).json()["type"] == "FeatureCollection"


def test_buildings_require_bbox_and_respect_limit():
    assert client.get("/api/impact/buildings").status_code == 422
    body = client.get(f"/api/impact/buildings?{BBOX}&limit=2").json()
    assert len(body["features"]) == 2 and body["truncated"] is True
    far = client.get("/api/impact/buildings?min_lon=0&min_lat=0&max_lon=1&max_lat=1").json()
    assert far["features"] == [] and far["truncated"] is False


def test_susceptibility_grid_bbox_query():
    body = client.get(f"/api/impact/susceptibility-grid?{BBOX}").json()
    assert len(body["features"]) == 3
    assert {f["properties"]["susceptibility_class"] for f in body["features"]} == {"very_high", "very_low", "moderate"}
    assert client.get("/api/impact/susceptibility-grid/metadata").json()["point_count"] == 3


def test_overlay_and_live_forecast():
    assert set(client.get("/api/impact/overlay").json()) == {"metadata", "tambons", "provinces"}
    forecast = client.get("/api/impact/live-forecast").json()
    assert forecast["tambons"][0]["rain_class_24h"] == "heavy"
    assert forecast["tambons"][0]["rain_local_class_24h"] == "above_p95"
    assert forecast["summary"]["max_24h_mm"] == 40.0
    assert client.get("/api/impact/realtime-trigger").status_code == 404   # old endpoint is gone


def test_status_lists_the_live_forecast():
    body = client.get("/api/status").json()
    assert set(body) == {"factor_grid", "susceptibility_raster", "live_forecast", "impact_overlay"}
    assert body["live_forecast"]["done"] is True


def test_missing_data_returns_404_not_500(monkeypatch, tmp_path):
    from app import data, paths

    monkeypatch.setattr(paths, "IMPACT_OVERLAY_JSON", tmp_path / "nope.json")
    assert client.get("/api/impact/overlay").status_code == 404
    monkeypatch.setattr(paths, "LIVE_FORECAST_JSON", tmp_path / "nope.json")
    assert client.get("/api/impact/live-forecast").status_code == 404
    monkeypatch.setattr(paths, "MODEL_METADATA_PATH", tmp_path / "nope.json")
    data.model_metadata.cache_clear()
    try:
        assert client.get("/api/model").status_code == 404
    finally:
        data.model_metadata.cache_clear()


def test_api_is_read_only():
    assert client.post("/api/model", json={}).status_code in (405, 403)
