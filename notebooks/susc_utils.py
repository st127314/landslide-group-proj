"""Helpers imported by the notebook. Kept in a module so the saved joblib pipeline can be
unpickled from any script that has this file on its path."""
import numpy as np


def add_aspect_features(data):
    """Replace circular `aspect` (degrees) by sin/cos components."""
    data = data.copy()
    rad = np.deg2rad(data['aspect'])
    data['aspect_sin'] = np.sin(rad)
    data['aspect_cos'] = np.cos(rad)
    return data.drop(columns='aspect')


from sklearn.base import BaseEstimator, TransformerMixin


class IQRClipper(BaseEstimator, TransformerMixin):
    """Winsorise each column to [Q1 - k*IQR, Q3 + k*IQR]; bounds are learned on the training data only."""

    def __init__(self, k=1.5):
        self.k = k

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        q1, q3 = np.nanpercentile(X, [25, 75], axis=0)
        iqr = q3 - q1
        self.lower_ = q1 - self.k * iqr
        self.upper_ = q3 + self.k * iqr
        return self

    def transform(self, X):
        return np.clip(np.asarray(X, dtype=float), self.lower_, self.upper_)

    def get_feature_names_out(self, input_features=None):
        return np.asarray(input_features, dtype=object)
