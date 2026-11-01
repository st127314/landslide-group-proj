"""Tests for scripts/refresh_impact_overlay.py, the light overlay refresh the server runs after each forecast."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from refresh_impact_overlay import impact_class, refresh  # noqa: E402


def tambon(gid, province, tier, pop_hv):
    return {"GID_3": gid, "NAME_3": gid, "NAME_2": "D", "NAME_1": province, "area_km2": 10.0, "susceptibility_tier": tier,
            "buildings_total": 10, "buildings_high_vh": 4, "population_total": 1000, "population_high_vh": pop_hv,
            "facilities_total": 2, "facilities_high_vh": 1, "critical_facilities_total": 1, "critical_facilities_high_vh": 1,
            "gfs_rain_24h_mm": 1.0, "rain_class_24h": "light", "rain_local_class_24h": "below_p75",
            "live_impact_class": "low", "population_at_elevated_risk": 0, "buildings_at_elevated_risk": 0,
            "facilities_at_elevated_risk": 0}


def forecast(gid, mm, local_class):
    return {"GID_3": gid, "gfs_rain_24h_mm": mm, "gfs_rain_48h_mm": mm, "gfs_rain_72h_mm": mm,
            "gfs_peak_hourly_mm_24h": 1.0, "rain_class_24h": "heavy", "local_p75_mm": 10.0, "local_p90_mm": 20.0,
            "local_p95_mm": 30.0, "rain_local_class_24h": local_class}


OVERLAY = {"metadata": {"rain_basis": "percentile", "totals": {"tambons": 3, "population_total": 3000}},
           "tambons": [tambon("A", "P1", "high", 500), tambon("B", "P1", "low", 100), tambon("C", "P2", "no_data", 0)]}
LIVE = {"gfs_run_utc": "2026-11-01T00:00:00+00:00", "generated_utc": "2026-11-01T05:00:00+00:00",
        "tambons": [forecast("A", 50.0, "above_p95"), forecast("B", 50.0, "above_p95"), forecast("C", 50.0, "above_p95")]}


class RefreshOverlayTests(unittest.TestCase):
    def test_rule_matches_the_documented_bins(self):
        self.assertEqual(impact_class("low", 1), "low")
        self.assertEqual(impact_class("moderate", 1), "moderate")
        self.assertEqual(impact_class("moderate", 3), "high")
        self.assertEqual(impact_class("high", 3), "very_high")
        self.assertEqual(impact_class("no_data", 3), "not_assessed")

    def test_new_rain_changes_classes_counts_and_rollups(self):
        out = refresh(OVERLAY, LIVE)
        by_id = {t["GID_3"]: t for t in out["tambons"]}
        self.assertEqual(by_id["A"]["live_impact_class"], "very_high")   # 3 x 3
        self.assertEqual(by_id["B"]["live_impact_class"], "moderate")    # 1 x 3
        self.assertEqual(by_id["C"]["live_impact_class"], "not_assessed")
        self.assertEqual(by_id["A"]["population_at_elevated_risk"], 500)
        self.assertEqual(by_id["B"]["population_at_elevated_risk"], 0)
        self.assertEqual(out["tambons"][0]["GID_3"], "A")                 # most severe first
        totals = out["metadata"]["totals"]
        self.assertEqual(totals["population_at_elevated_risk"], 500)
        self.assertEqual(totals["population_total"], 3000)               # exposure totals carried over
        self.assertEqual(out["metadata"]["gfs_run_utc"], LIVE["gfs_run_utc"])
        p1 = next(p for p in out["provinces"] if p["NAME_1"] == "P1")
        self.assertEqual((p1["tambons"], p1["tambons_live_impact_high_or_above"], p1["max_rain_24h_mm"]), (2, 1, 50.0))

    def test_input_overlay_is_not_modified(self):
        refresh(OVERLAY, LIVE)
        self.assertEqual(OVERLAY["tambons"][0]["live_impact_class"], "low")


if __name__ == "__main__":
    unittest.main()
