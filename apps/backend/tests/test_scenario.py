import pytest
from fastapi.testclient import TestClient

from app import scenario
from app.main import app

client = TestClient(app)


def test_rule_table():
    # terrain factor x rain index: 0-1 low, 2-3 moderate, 4-6 high, >= 7 very high; rain below P75 never creates risk
    assert [scenario.impact_class("high", 0), scenario.impact_class("moderate", 0), scenario.impact_class("low", 0)] == ["low"] * 3
    assert scenario.impact_class("low", 3) == "moderate"       # flat ground never exceeds moderate
    assert scenario.impact_class("moderate", 3) == "high"
    assert scenario.impact_class("high", 2) == "high"
    assert scenario.impact_class("high", 3) == "very_high"
    assert scenario.impact_class("no_data", 3) == "not_assessed"
    assert scenario.impact_class("high", None) == "not_assessed"


def test_local_class_uses_each_tambons_own_percentiles():
    assert scenario.local_class_index(10, 15, 25, 33) == 0
    assert scenario.local_class_index(15, 15, 25, 33) == 1
    assert scenario.local_class_index(26, 15, 25, 33) == 2
    assert scenario.local_class_index(33, 15, 25, 33) == 3
    assert scenario.local_class_index(50, None, None, None) is None


def test_no_parameters_reproduces_the_live_overlay():
    body = client.get("/api/impact/scenario").json()
    live = {t["GID_3"]: t["live_impact_class"] for t in client.get("/api/impact/overlay").json()["tambons"]}
    assert {t["GID_3"]: t["impact_class"] for t in body["tambons"]} == live
    assert body["scenario"]["rain_24h_mm"] is None
    assert body["summary"]["population_at_elevated_risk"] == 10      # only the very-high tambon


def test_zero_rain_means_no_elevated_risk_anywhere():
    body = client.get("/api/impact/scenario?rain_24h_mm=0").json()
    assert body["summary"]["tambons_by_impact_class"] == {"low": 3}
    assert body["summary"]["population_at_elevated_risk"] == 0


def test_heavy_rain_everywhere_follows_terrain():
    body = client.get("/api/impact/scenario?rain_24h_mm=100").json()
    by_id = {t["GID_3"]: t["impact_class"] for t in body["tambons"]}
    assert by_id == {"T.1": "very_high", "T.2": "moderate", "T.3": "high"}
    assert body["summary"]["population_at_elevated_risk"] == 10 + 40    # high + very-high tambons only
    assert body["tambons"][0]["GID_3"] == "T.1"                         # ranked: class, then people at risk


def test_province_scope_leaves_other_provinces_on_the_live_forecast():
    body = client.get("/api/impact/scenario?rain_24h_mm=100&province=Otherprovince").json()
    by_id = {t["GID_3"]: t for t in body["tambons"]}
    assert by_id["T.3"]["impact_class"] == "high" and by_id["T.3"]["rain_24h_mm"] == 100.0
    assert by_id["T.1"]["impact_class"] == "very_high" and by_id["T.1"]["rain_24h_mm"] == 40.0   # live forecast
    assert by_id["T.2"]["impact_class"] == "low" and by_id["T.2"]["rain_24h_mm"] == 5.0
    assert body["summary"]["tambons_in_scope"] == 1


@pytest.mark.parametrize("query", ["rain_24h_mm=-5", "rain_24h_mm=1501", "rain_24h_mm=abc", "province=Nowhere",
                                   "limit=0", "limit=500"])
def test_invalid_input_is_rejected(query):
    assert client.get(f"/api/impact/scenario?{query}").status_code == 422


def test_limit_and_limitations():
    body = client.get("/api/impact/scenario?rain_24h_mm=100&limit=1").json()
    assert len(body["tambons"]) == 1 and body["limitations"]
