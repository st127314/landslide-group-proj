"""The grid input check must catch the three ways a factor on the map has differed from the training table (blank on the
grid, a different scale, classes the model never saw), stay quiet when the two agree, and let a documented mismatch
through without hiding a new one. It is tested on small synthetic tables, because the real grid is not in the repository."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_grid_inputs import compare  # noqa: E402


def tables(n=400, seed=0):
    """A training table and a grid that describe the same places with the same values (cells 0.001 degree apart)."""
    rng = np.random.default_rng(seed)
    lon, lat = 99 + 0.001 * (np.arange(n) % 20), 8 + 0.001 * (np.arange(n) // 20)
    slope, rock = rng.uniform(1, 40, n), rng.choice(["granite", "limestone"], n)
    train = pd.DataFrame({"longitude": lon, "latitude": lat, "slope": slope, "rock": rock})
    grid = pd.DataFrame({"px_lon": lon, "px_lat": lat, "slope": slope + rng.normal(0, 0.5, n), "rock": rock})
    return train, grid


def status(train, grid, known=None):
    report = compare(train, grid, ["slope"], ["rock"], known=known or {})
    return {name: (row["status"], row.get("reasons", [])) for name, row in report["factors"].items()}


class GridInputCheckTests(unittest.TestCase):
    def test_matching_tables_pass(self):
        train, grid = tables()
        self.assertEqual(status(train, grid), {"slope": ("ok", []), "rock": ("ok", [])})
        self.assertEqual(compare(train, grid, ["slope"], ["rock"], known={})["matched_points"], len(train))

    def test_a_factor_that_is_mostly_blank_on_the_grid_fails_on_coverage(self):
        train, grid = tables()
        grid.loc[grid.index % 4 != 0, "slope"] = np.nan          # 75% blank, as the road distance was
        self.assertEqual(status(train, grid)["slope"], ("fail", ["coverage"]))

    def test_a_factor_on_another_scale_fails(self):
        train, grid = tables()
        grid["slope"] = grid["slope"] * 10                       # same ranking, wrong units
        self.assertEqual(status(train, grid)["slope"], ("fail", ["scale"]))

    def test_classes_the_model_never_saw_fail(self):
        train, grid = tables()
        grid.loc[:39, "rock"] = "basalt"                         # 10% of cells
        self.assertEqual(status(train, grid)["rock"], ("fail", ["unseen classes"]))

    def test_a_documented_mismatch_is_reported_as_known_and_does_not_hide_a_new_one(self):
        train, grid = tables()
        grid["slope"] = grid["slope"] * 10
        grid.loc[:39, "rock"] = "basalt"
        result = status(train, grid, known={"slope": "documented"})
        self.assertEqual(result["slope"][0], "known")
        self.assertEqual(result["rock"][0], "fail")

    def test_unrelated_values_at_the_same_places_are_flagged_as_weak_agreement(self):
        train, grid = tables()
        grid["slope"] = np.random.default_rng(1).permutation(grid["slope"].to_numpy())     # same distribution, shuffled in space
        self.assertEqual(status(train, grid)["slope"], ("warning", ["weak agreement at the same places"]))


if __name__ == "__main__":
    unittest.main()
