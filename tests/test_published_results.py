"""The model metadata and experiment results that ship in the repository must agree with each other and with the training
table. They are what the report, the Model page and the CI/CD pipeline describe, so a retrain that changes one without
the others (or a hand edit) fails here instead of reaching the dashboard."""
import json
from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "notebooks" / "experiments"))
from common import BLOCK, BUF, ALL_FEATS  # noqa: E402

METADATA = json.loads((ROOT / "models" / "susceptibility" / "model_metadata.json").read_text())
RESULTS = json.loads((ROOT / "results" / "experiments" / "results.json").read_text())
FOLLOWUP = json.loads((ROOT / "results" / "experiments" / "followup.json").read_text())
TRAINING = pd.read_csv(ROOT / "data" / "processed" / "landslide_event_factors_cleaned.csv")


class ModelMetadataTests(unittest.TestCase):
    def test_production_model_is_the_svm_with_parameters_inside_the_searched_ranges(self):
        self.assertEqual(METADATA["best_model"], "svm_rbf")
        params = METADATA["best_params"]["svm_rbf"]
        self.assertTrue(0.1 <= params["model__C"] <= 50)
        self.assertTrue(1e-3 <= params["model__gamma"] <= 1e-1)

    def test_thresholds_are_probabilities(self):
        for key in ("threshold_raw_probability", "threshold_calibrated_probability"):
            self.assertTrue(0 < METADATA[key] < 1, key)

    def test_validation_design_matches_the_experiments(self):
        self.assertEqual(METADATA["spatial_block_deg"], BLOCK)
        self.assertEqual(METADATA["spatial_buffer_km"], BUF)

    def test_every_model_feature_is_a_column_of_the_training_table(self):
        self.assertFalse(set(METADATA["feature_columns"]) - set(TRAINING.columns))
        self.assertEqual(set(METADATA["feature_columns"]), set(METADATA["numeric_features"]) | set(METADATA["categorical_features"]))

    def test_experiment_feature_list_is_the_model_feature_list(self):
        self.assertEqual(set(ALL_FEATS), set(METADATA["feature_columns"]))


class ExperimentResultTests(unittest.TestCase):
    def test_experiments_ran_on_the_published_training_table(self):
        self.assertEqual(RESULTS["setup"]["n"], len(TRAINING))
        setup = RESULTS["setup"]
        # The outer folds partition the training rows; the held-out fold and the buffer-removed rows make up the rest.
        self.assertEqual(sum(setup["outer_fold_sizes"]), setup["train"])
        self.assertLessEqual(setup["train"] + setup["test"], setup["n"])

    def test_followup_shares_are_fractions_and_tell_one_story(self):
        shares = FOLLOWUP["F2"]
        flat = []

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("top20", "top10", "cell_top20", "cell_top10"):
                        flat.append(value)
                    else:
                        walk(value)
        walk(shares)
        self.assertTrue(flat, "no decision-value shares found in followup.json")
        for value in flat:
            for number in (value.values() if isinstance(value, dict) else [value]):
                if isinstance(number, (int, float)):
                    self.assertTrue(0 <= number <= 1, number)


if __name__ == "__main__":
    unittest.main()
