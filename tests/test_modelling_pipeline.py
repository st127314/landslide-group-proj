"""Tests for the modelling helpers, the spatial cross-validation set-up and the baseline model."""
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, PowerTransformer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "notebooks"))
from susc_utils import IQRClipper, add_aspect_features  # noqa: E402

BLOCK_DEG = 0.5
BUFFER_KM = 5.0
CATEGORICAL = ["lithology", "lulc", "soil_texture"]


def spatial_blocks(df):
    return (np.floor(df["longitude"] / BLOCK_DEG).astype(int).astype(str) + "_"
            + np.floor(df["latitude"] / BLOCK_DEG).astype(int).astype(str)).to_numpy()


def planar_km(df):
    lat = np.deg2rad(df["latitude"].mean())
    return np.column_stack((df["longitude"] * 111.32 * np.cos(lat), df["latitude"] * 111.32))


def buffered(train, test, xy, buffer_km=BUFFER_KM):
    near = cKDTree(xy[test]).query(xy[train], k=1)[0] < buffer_km
    return np.asarray(train)[~near]


def baseline_pipeline(numeric):
    numeric_cols = [c for c in numeric if c != "aspect"] + ["aspect_sin", "aspect_cos"]
    numeric_steps = Pipeline([
        ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
        ("clip", IQRClipper(k=1.5)),
        ("power", PowerTransformer(method="yeo-johnson", standardize=True)),
    ])
    categorical_steps = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
    ])
    return Pipeline([
        ("aspect", FunctionTransformer(add_aspect_features)),
        ("columns", ColumnTransformer([("num", numeric_steps, numeric_cols), ("cat", categorical_steps, CATEGORICAL)])),
        ("model", LogisticRegression(C=0.017, max_iter=5000, class_weight="balanced")),
    ])


class HelperTests(unittest.TestCase):
    def test_aspect_becomes_sine_and_cosine(self):
        out = add_aspect_features(pd.DataFrame({"aspect": [0.0, 90.0, 180.0], "slope": [1, 2, 3]}))
        self.assertNotIn("aspect", out.columns)
        np.testing.assert_allclose(out["aspect_sin"], [0, 1, 0], atol=1e-9)
        np.testing.assert_allclose(out["aspect_cos"], [1, 0, -1], atol=1e-9)
        self.assertEqual(list(out["slope"]), [1, 2, 3])

    def test_clipper_learns_bounds_from_training_data_only(self):
        clipper = IQRClipper(k=1.5).fit(np.array([[1.0], [2.0], [3.0], [4.0]]))
        # Q1 = 1.75, Q3 = 3.25, IQR = 1.5, so the bounds are 1.75 - 2.25 and 3.25 + 2.25.
        np.testing.assert_allclose(clipper.lower_, [-0.5])
        np.testing.assert_allclose(clipper.upper_, [5.5])
        np.testing.assert_allclose(clipper.transform(np.array([[-10.0], [2.5], [100.0]])), [[-0.5], [2.5], [5.5]])


class SpatialCvTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(ROOT / "data" / "processed" / "landslide_event_factors_cleaned.csv")
        cls.y = cls.df["landslide"].to_numpy()
        cls.groups = spatial_blocks(cls.df)
        cls.xy = planar_km(cls.df)
        cls.folds = list(StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42).split(cls.df, cls.y, cls.groups))

    def test_folds_never_share_a_block(self):
        for train, test in self.folds:
            self.assertFalse(set(self.groups[train]) & set(self.groups[test]))

    def test_buffer_removes_every_nearby_training_point(self):
        train, test = self.folds[0]
        kept = buffered(train, test, self.xy)
        self.assertLess(len(kept), len(train))
        distances = cKDTree(self.xy[test]).query(self.xy[kept], k=1)[0]
        self.assertGreaterEqual(distances.min(), BUFFER_KM)

    def test_baseline_beats_chance_under_spatial_cv(self):
        # Regression guard: the logistic-regression baseline scored about 0.93 ROC-AUC in nested spatial CV.
        features = [c for c in self.df.columns if c not in ("id", "event_date", "longitude", "latitude", "landslide")]
        numeric = [c for c in features if c not in CATEGORICAL]
        scores = []
        for train, test in self.folds[:3]:
            kept = buffered(train, test, self.xy)
            model = baseline_pipeline(numeric).fit(self.df.iloc[kept][features], self.y[kept])
            scores.append(roc_auc_score(self.y[test], model.predict_proba(self.df.iloc[test][features])[:, 1]))
        self.assertGreater(np.mean(scores), 0.85, scores)


if __name__ == "__main__":
    unittest.main()
