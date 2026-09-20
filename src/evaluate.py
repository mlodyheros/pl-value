"""Diagnostic plots for the trained player value model."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from src.config import FIGURES_DIR
from src.features import split_features_target, train_test_split_dataset


def plot_predictions(pipeline: Pipeline, df: pd.DataFrame) -> None:
    """Predicted-vs-actual and residual plots; held-out players are highlighted
    so the fit on training data isn't mistaken for generalisation."""
    X, y_log = split_features_target(df)
    y_true = np.expm1(y_log)
    y_pred = np.expm1(pipeline.predict(X))
    is_test = X.index.isin(train_test_split_dataset(df)[1].index)

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))

    axes[0].scatter(y_true[~is_test] / 1e6, y_pred[~is_test] / 1e6, alpha=0.3, s=20, label="train")
    axes[0].scatter(y_true[is_test] / 1e6, y_pred[is_test] / 1e6, alpha=0.8, s=24, label="held-out")
    axes[0].legend()
    max_val = max(y_true.max(), y_pred.max()) / 1e6
    axes[0].plot([0, max_val], [0, max_val], "r--", linewidth=1)
    axes[0].set_xlabel("Actual value (€m)")
    axes[0].set_ylabel("Predicted value (€m)")
    axes[0].set_title("Predicted vs actual market value")

    residuals = (y_pred - y_true) / 1e6
    axes[1].scatter(y_true[~is_test] / 1e6, residuals[~is_test], alpha=0.3, s=20)
    axes[1].scatter(y_true[is_test] / 1e6, residuals[is_test], alpha=0.8, s=24)
    axes[1].axhline(0, color="r", linestyle="--", linewidth=1)
    axes[1].set_xlabel("Actual value (€m)")
    axes[1].set_ylabel("Residual (€m)")
    axes[1].set_title("Residuals")

    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "pred_vs_actual.png", dpi=150)
    plt.close(fig)
