import numpy as np
import pandas as pd

from src.features import split_features_target, train_test_split_dataset


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [20, 25, 30, 22],
            "goals": [1, 10, 3, 0],
            "assists": [2, 5, 1, 0],
            "penalties": [0, 2, 0, 0],
            "appearances": [15, 30, 25, 5],
            "position": ["Centre-Forward", "Centre-Forward", "Centre-Back", "Goalkeeper"],
            "club": ["A FC", "B FC", "A FC", "C FC"],
            "market_value_eur": [1_000_000, 50_000_000, 5_000_000, 200_000],
        }
    )


def test_split_features_target_log_transforms_value():
    X, y = split_features_target(_sample_df())

    assert list(X.columns) == [
        "age",
        "goals",
        "assists",
        "penalties",
        "appearances",
        "position",
        "club",
    ]
    assert np.allclose(y.values, np.log1p([1_000_000, 50_000_000, 5_000_000, 200_000]))


def test_train_test_split_dataset_shapes():
    df = _sample_df()
    X_train, X_test, y_train, y_test = train_test_split_dataset(
        df, test_size=0.5, random_state=0
    )

    assert len(X_train) + len(X_test) == len(df)
    assert len(y_train) + len(y_test) == len(df)
