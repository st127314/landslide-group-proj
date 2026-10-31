"""Integrity checks on the model-ready tables in data/processed/."""
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
FACTORS = PROCESSED / "landslide_event_factors_cleaned.csv"

EXPECTED_COLUMNS = [
    "id", "event_date", "longitude", "latitude", "landslide",
    "elevation", "slope", "aspect", "curvature_general", "curvature_profile", "tri", "tpi", "ls_factor",
    "upstream_area_km2", "twi", "spi",
    "soil_texture", "soil_clay_pct", "soil_sand_pct", "soil_bulk_density",
    "dist_to_road", "dist_to_river", "lithology", "ndvi", "lulc",
]


class FactorTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(FACTORS)

    def test_columns(self):
        self.assertEqual(list(self.df.columns), EXPECTED_COLUMNS)

    def test_balanced_paired_classes(self):
        counts = self.df["landslide"].value_counts().to_dict()
        self.assertEqual(counts, {1: 6180, 0: 6180})

    def test_ids_are_unique_and_match_class(self):
        self.assertTrue(self.df["id"].is_unique)
        landslides = self.df[self.df["landslide"] == 1]
        negatives = self.df[self.df["landslide"] == 0]
        self.assertTrue(landslides["id"].str.startswith("LS_").all())
        self.assertTrue(negatives["id"].str.startswith("NL_").all())

    def test_each_negative_shares_a_landslide_date(self):
        # Paired design: every negative carries the date of its landslide.
        landslide_dates = np.sort(self.df.loc[self.df["landslide"] == 1, "event_date"].to_numpy())
        negative_dates = np.sort(self.df.loc[self.df["landslide"] == 0, "event_date"].to_numpy())
        np.testing.assert_array_equal(landslide_dates, negative_dates)

    def test_dates_within_inventory_period(self):
        dates = pd.to_datetime(self.df["event_date"])
        self.assertGreaterEqual(dates.min(), pd.Timestamp("2000-01-01"))
        self.assertLessEqual(dates.max(), pd.Timestamp("2025-12-31"))

    def test_points_inside_southern_thailand(self):
        self.assertTrue(self.df["longitude"].between(97.3, 102.2).all())
        self.assertTrue(self.df["latitude"].between(5.5, 11.8).all())

    def test_physical_ranges(self):
        ranges = {
            "slope": (0, 90), "aspect": (0, 360), "ndvi": (-1, 1), "elevation": (-50, 3000),
            "soil_clay_pct": (0, 100), "soil_sand_pct": (0, 100), "twi": (0, 40),
            "dist_to_road": (0, 20_000), "dist_to_river": (0, 20_000), "upstream_area_km2": (0, None),
        }
        for column, (low, high) in ranges.items():
            values = self.df[column].dropna()
            self.assertGreaterEqual(values.min(), low, column)
            if high is not None:
                self.assertLessEqual(values.max(), high, column)

    def test_missing_values_stay_small(self):
        # Gaps are imputed inside each fold; a jump would signal a broken extraction.
        missing = self.df.isna().mean()
        self.assertLess(missing.max(), 0.05, missing[missing > 0].to_dict())
        for column in ["id", "event_date", "longitude", "latitude", "landslide", "elevation"]:
            self.assertEqual(self.df[column].isna().sum(), 0, column)

    def test_excluded_factors_are_absent(self):
        for column in ["dist_to_stream", "drainage_density", "dist_to_fault"]:
            self.assertNotIn(column, self.df.columns)


class RainfallTableTests(unittest.TestCase):
    WINDOWS = [f"rain_{days}d_mm" for days in range(1, 31)]

    def check_table(self, name):
        df = pd.read_csv(PROCESSED / name)
        self.assertEqual(len(df), 6180)
        self.assertTrue((df["rainfall_status"] == "complete").all())
        rain = df[self.WINDOWS].to_numpy()
        self.assertTrue((rain >= 0).all())
        # Accumulated rainfall can only grow as the window lengthens.
        self.assertTrue((np.diff(rain, axis=1) >= -1e-6).all())

    def test_landslide_rainfall(self):
        self.check_table("landslide_event_antecedent_rainfall.csv")

    def test_non_landslide_rainfall(self):
        self.check_table("non_landslide_event_antecedent_rainfall.csv")


if __name__ == "__main__":
    unittest.main()
