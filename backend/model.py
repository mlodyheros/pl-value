"""Trains a linear regression pipeline to predict (log) player market value."""

from __future__ import annotations

import logging

import json

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from backend.config import CALIBRATION_PATH, MODEL_PATH, PROCESSED_DATASET_PATH
from backend.features import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    split_features_target,
    train_test_split_dataset,
)

logger = logging.getLogger(__name__)


def build_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        [
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", drop="first"),
                CATEGORICAL_FEATURES,
            ),
        ]
    )
    return Pipeline([("preprocess", preprocessor), ("regressor", LinearRegression())])


def value_weights(values: np.ndarray) -> np.ndarray:
    """Training weights that grow with the square root of a player's value.

    Fitting log-value with equal weights optimises *relative* error, so the
    dozens of cheap players outvote the handful of stars and the top decile is
    predicted ~24% too low. Weighting by sqrt(value) trades a little log-scale
    R^2 for lower euro error overall (MAE 10.3m -> 9.8m) and on stars (32m -> 26m).
    """
    values = np.asarray(values, dtype=float)
    return np.sqrt(values / values.mean())


def fit_pipeline(pipeline: Pipeline, X: pd.DataFrame, y_log: pd.Series) -> Pipeline:
    weights = value_weights(np.expm1(y_log))
    return pipeline.fit(X, y_log, regressor__sample_weight=weights)


def train(df: pd.DataFrame) -> tuple[Pipeline, dict]:
    X_train, X_test, y_train, y_test = train_test_split_dataset(df)

    pipeline = fit_pipeline(build_pipeline(), X_train, y_train)

    y_pred_log = pipeline.predict(X_test)
    y_pred = np.expm1(y_pred_log)
    y_true = np.expm1(y_test)

    metrics = {
        "r2_log": r2_score(y_test, y_pred_log),
        "mae_eur": mean_absolute_error(y_true, y_pred),
        "rmse_eur": root_mean_squared_error(y_true, y_pred),
    }
    return pipeline, metrics


def cross_validate_model(df: pd.DataFrame, n_splits: int = 5, random_state: int = 42) -> dict:
    """K-fold out-of-sample metrics.

    With only a few hundred players a single 80/20 split is noisy (R^2 swings
    by ~0.1 between seeds), so this is the number to trust when comparing changes.
    """
    X, y = split_features_target(df)
    cv = KFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    y_pred_log = pd.Series(0.0, index=y.index)
    for train_idx, test_idx in cv.split(X):
        fitted = fit_pipeline(build_pipeline(), X.iloc[train_idx], y.iloc[train_idx])
        y_pred_log.iloc[test_idx] = fitted.predict(X.iloc[test_idx])
    y_true, y_pred = np.expm1(y), np.expm1(y_pred_log)

    # Mean predicted/actual for the most valuable 10% of players; 1.0 = unbiased.
    top = y_true >= y_true.quantile(0.9)
    return {
        "cv_r2_log": r2_score(y, y_pred_log),
        "cv_mae_eur": mean_absolute_error(y_true, y_pred),
        "cv_rmse_eur": root_mean_squared_error(y_true, y_pred),
        "cv_top_decile_mae_eur": mean_absolute_error(y_true[top], y_pred[top]),
        "cv_top_decile_ratio": float((y_pred[top] / y_true[top]).mean()),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    df = pd.read_csv(PROCESSED_DATASET_PATH)
    pipeline, metrics = train(df)

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)

    logger.info("Trained on %d players", len(df))
    logger.info("R^2 (log-value): %.3f", metrics["r2_log"])
    logger.info("MAE: €%.0f", metrics["mae_eur"])
    logger.info("RMSE: €%.0f", metrics["rmse_eur"])

    cv_metrics = cross_validate_model(df)
    logger.info("5-fold CV R^2 (log-value): %.3f", cv_metrics["cv_r2_log"])
    logger.info("5-fold CV MAE: €%.0f", cv_metrics["cv_mae_eur"])
    logger.info("5-fold CV RMSE: €%.0f", cv_metrics["cv_rmse_eur"])
    logger.info("5-fold CV top-10%% MAE: €%.0f", cv_metrics["cv_top_decile_mae_eur"])
    logger.info("5-fold CV top-10%% predicted/actual: %.2f", cv_metrics["cv_top_decile_ratio"])

    from backend import confidence

    calibration = confidence.calibrate(df)
    CALIBRATION_PATH.write_text(json.dumps(calibration, indent=2))
    for tier in confidence.TIERS:
        low, high = confidence.interval(1.0, tier, calibration)
        logger.info(
            "80%% range, %s: x%.2f to x%.2f (n=%s)",
            tier,
            low,
            high,
            calibration.get(tier, {}).get("n", "borrowed"),
        )

    from backend.evaluate import plot_predictions

    plot_predictions(pipeline, df)


if __name__ == "__main__":
    main()
