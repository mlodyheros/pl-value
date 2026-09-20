"""Trains a linear regression pipeline to predict (log) player market value."""

from __future__ import annotations

import logging

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.config import MODEL_PATH, PROCESSED_DATASET_PATH
from src.features import CATEGORICAL_FEATURES, NUMERIC_FEATURES, train_test_split_dataset

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


def train(df: pd.DataFrame) -> tuple[Pipeline, dict]:
    X_train, X_test, y_train, y_test = train_test_split_dataset(df)

    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    y_pred_log = pipeline.predict(X_test)
    y_pred = np.expm1(y_pred_log)
    y_true = np.expm1(y_test)

    metrics = {
        "r2_log": r2_score(y_test, y_pred_log),
        "mae_eur": mean_absolute_error(y_true, y_pred),
        "rmse_eur": root_mean_squared_error(y_true, y_pred),
    }
    return pipeline, metrics


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

    from src.evaluate import plot_predictions

    plot_predictions(pipeline, df)


if __name__ == "__main__":
    main()
