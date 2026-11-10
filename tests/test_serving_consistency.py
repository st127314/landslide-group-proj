"""Training and serving must describe a location with the same features: these tests tie the trained model's feature
list to the training table and to what scripts/predict_susceptibility_grid.py feeds it when the map is scored."""
import json
from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import predict_susceptibility_grid as serving  # noqa: E402

METADATA = json.loads((ROOT / "models" / "susceptibility" / "model_metadata.json").read_text())
TRAINING = ROOT / "data" / "processed" / "landslide_event_factors_cleaned.csv"
GRID_DIRS = sorted(serving.GRID_DIR.glob("factor_grid_points_*")) if serving.GRID_DIR.exists() else []
needs_grid = unittest.skipUnless(GRID_DIRS, "the 250 m factor grid is not part of the repository")

# Column names as sampled on the grid by gee_sample_factor_grid_points.py (before the serving script renames them).
GRID_COLUMNS = ["px_lon", "px_lat", "elevation", "slope", "aspect", "curvature_general", "curvature_profile", "TRI", "TPI",
                "LS_factor", "upstream_area_km2", "dist_to_stream", "drainage_density", "TWI", "SPI", "soil_texture",
                "soil_clay_pct", "soil_sand_pct", "soil_bulk_density", "dist_to_road", "dist_to_river", "dist_to_fault",
                "lithology", "dem_source", "NDVI", "LULC_current"]


class ServingConsistencyTests(unittest.TestCase):
    def test_model_features_are_the_training_table_factors(self):
        features = METADATA["feature_columns"]
        self.assertEqual(sorted(features), sorted(METADATA["numeric_features"] + METADATA["categorical_features"]))
        factors = [c for c in pd.read_csv(TRAINING, nrows=1).columns if c not in METADATA["excluded_columns"] + ["landslide"]]
        self.assertEqual(sorted(features), sorted(factors))

    def test_grid_columns_rename_to_every_model_feature(self):
        renamed = {serving.RENAME.get(c, c) for c in GRID_COLUMNS}
        self.assertEqual(set(METADATA["feature_columns"]) - renamed, set())

    def test_trained_categories_are_names_the_serving_script_can_produce(self):
        # The grid stores lithology and land cover as codes; scoring maps them through these tables. A category the
        # model was trained on but the table cannot produce would silently never be used on the map.
        train = pd.read_csv(TRAINING, usecols=["lithology", "lulc"])
        for column, table in [("lithology", "glim_lithology_classes.json"), ("lulc", "servir_landcover_classes.json")]:
            names = set(serving.class_names(table).values())
            trained = set(train[column].dropna().unique()) - {"No data"}
            self.assertEqual(trained - names, set(), column)

    def test_class_bins_cover_the_unit_interval_in_five_labels(self):
        self.assertEqual(len(serving.CLASS_BINS), len(serving.CLASS_LABELS) + 1)
        self.assertLess(serving.CLASS_BINS[0], 0)
        self.assertGreater(serving.CLASS_BINS[-1], 1)
        self.assertEqual(serving.CLASS_BINS[1:-1], [0.2, 0.4, 0.6, 0.8])

    @needs_grid
    def test_real_grid_tile_has_every_feature_with_known_class_names(self):
        tile = sorted(GRID_DIRS[-1].glob("tile_*.csv"))[0]
        self.assertEqual(list(pd.read_csv(tile, nrows=0).columns), GRID_COLUMNS)
        grid = serving.load_grid(GRID_DIRS[-1])
        self.assertEqual([c for c in METADATA["feature_columns"] if c not in grid.columns], [])
        train = pd.read_csv(TRAINING, usecols=["lithology", "lulc"])
        for column in ("lithology", "lulc"):
            self.assertEqual(set(grid[column].dropna().unique()) - set(train[column].dropna().unique()), set(), column)


if __name__ == "__main__":
    unittest.main()
