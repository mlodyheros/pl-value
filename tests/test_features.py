import numpy as np
import pandas as pd

from src.features import (
    FEATURE_COLUMNS,
    add_derived_features,
    prepare_features,
    split_features_target,
    train_test_split_dataset,
)


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

    assert list(X.columns) == FEATURE_COLUMNS
    assert np.allclose(y.values, np.log1p([1_000_000, 50_000_000, 5_000_000, 200_000]))


def test_train_test_split_dataset_shapes():
    df = _sample_df()
    X_train, X_test, y_train, y_test = train_test_split_dataset(
        df, test_size=0.5, random_state=0
    )

    assert len(X_train) + len(X_test) == len(df)
    assert len(y_train) + len(y_test) == len(df)


def test_add_derived_features_computes_age_squared_and_flag_without_mutating_input():
    df = _sample_df()
    out = add_derived_features(df)

    assert "age_squared" not in df.columns
    assert list(out["age_squared"]) == [400, 625, 900, 484]
    # The goalkeeper (0 goals/assists, 5 appearances) still has a record via appearances.
    assert list(out["has_scorer_record"]) == [1, 1, 1, 1]

    no_stats = df.assign(goals=0, assists=0, appearances=0)
    assert list(add_derived_features(no_stats)["has_scorer_record"]) == [0, 0, 0, 0]


def test_add_derived_features_keeps_existing_scorer_flag():
    df = _sample_df().assign(has_scorer_record=[0, 1, 0, 1])
    assert list(add_derived_features(df)["has_scorer_record"]) == [0, 1, 0, 1]


def test_prepare_features_returns_training_columns_in_order():
    assert list(prepare_features(_sample_df()).columns) == FEATURE_COLUMNS
