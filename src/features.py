"""Feature/target definitions and train-test splitting for the value model."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

NUMERIC_FEATURES = [
    "age",
    "age_squared",
    "goals",
    "assists",
    "penalties",
    "appearances",
    "has_scorer_record",
]
CATEGORICAL_FEATURES = ["position", "club"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "market_value_eur"


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the features computed from raw columns (returns a copy).

    - ``age_squared``: value peaks in the mid-20s and falls off on both sides,
      which a straight line in age can't express (worth ~+0.1 CV R^2).
    - ``has_scorer_record``: football-data.org only lists players with a goal
      or assist, so a 0 for a player missing from it means "no data", not
      "played and didn't score". Derived from the stats when not supplied
      (e.g. hand-entered players), so it always agrees with the CSV definition.
    """
    out = df.copy()
    out["age_squared"] = out["age"] ** 2
    if "has_scorer_record" not in out:
        out["has_scorer_record"] = (
            (out["goals"] > 0) | (out["assists"] > 0) | (out["appearances"] > 0)
        ).astype(int)
    return out


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """Model input columns, in training order."""
    return add_derived_features(df)[FEATURE_COLUMNS]


def split_features_target(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Market values are heavily right-skewed, so the target is log1p(value)."""
    X = prepare_features(df)
    y = np.log1p(df[TARGET])
    return X, y


def train_test_split_dataset(
    df: pd.DataFrame, test_size: float = 0.2, random_state: int = 42
):
    X, y = split_features_target(df)
    return train_test_split(X, y, test_size=test_size, random_state=random_state)
