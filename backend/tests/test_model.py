import numpy as np
import pandas as pd

from backend.features import prepare_features
from backend.model import build_pipeline, cross_validate_model, train, value_weights


def _synthetic_df(n: int = 40, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    positions = rng.choice(["Centre-Forward", "Centre-Back", "Goalkeeper"], size=n)
    clubs = rng.choice(["A FC", "B FC", "C FC"], size=n)
    goals = rng.integers(0, 25, size=n)
    assists = rng.integers(0, 15, size=n)
    age = rng.integers(18, 35, size=n)
    appearances = rng.integers(1, 38, size=n)
    penalties = rng.integers(0, 5, size=n)

    value = 500_000 + (goals * 3_000_000) + (assists * 1_500_000) - (age * 100_000)
    value = np.clip(value, 100_000, None)

    return pd.DataFrame(
        {
            "age": age,
            "goals": goals,
            "assists": assists,
            "penalties": penalties,
            "appearances": appearances,
            "position": positions,
            "club": clubs,
            "market_value_eur": value,
        }
    )


def test_build_pipeline_has_expected_steps():
    pipeline = build_pipeline()
    assert [name for name, _ in pipeline.steps] == ["preprocess", "regressor"]


def test_train_produces_sane_metrics_and_predictions():
    df = _synthetic_df()
    pipeline, metrics = train(df)

    assert np.isfinite(metrics["r2_log"])
    assert metrics["mae_eur"] >= 0
    assert metrics["rmse_eur"] >= 0

    sample = prepare_features(df.iloc[:3])
    preds = pipeline.predict(sample)
    assert preds.shape == (3,)
    assert np.all(np.isfinite(preds))


def test_value_weights_grow_with_sqrt_of_value():
    weights = value_weights(np.array([1e6, 4e6, 9e6, 100e6]))

    assert np.all(np.diff(weights) > 0)
    # sqrt scaling: 4x the value -> 2x the weight
    assert np.isclose(weights[1] / weights[0], 2.0)


def test_cross_validate_model_reports_all_metrics():
    metrics = cross_validate_model(_synthetic_df(n=60), n_splits=3)

    assert set(metrics) == {
        "cv_r2_log",
        "cv_mae_eur",
        "cv_rmse_eur",
        "cv_top_decile_mae_eur",
        "cv_top_decile_ratio",
    }
    assert all(np.isfinite(v) for v in metrics.values())
    assert metrics["cv_top_decile_ratio"] > 0
