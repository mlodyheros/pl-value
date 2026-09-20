"""Feature/target definitions and train-test splitting for the value model."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

NUMERIC_FEATURES = [
    "age",
    "age_squared",
    "has_fpl_record",
    "minutes_share",
    "starts_share",
    "has_hist_record",
    "has_any_history",
    "career_minutes_share",
    "career_gi_per90",
]
CATEGORICAL_FEATURES = ["position", "club"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "market_value_eur"


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the features computed from raw columns (returns a copy).

    - ``age_squared``: value peaks in the mid-20s and falls off on both sides,
      which a straight line in age can't express (worth ~+0.1 CV R^2).
    - ``minutes_share`` / ``starts_share``: this season's FPL minutes as a
      fraction of those available, and starts per finished gameweek, so
      regulars stand out and the features stay comparable as the season goes
      on. Default to 0 when there is no FPL data (or before gameweek 1).
    - ``career_minutes_share`` / ``career_gi_per90``: how much the player has
      played, and scored/assisted per 90, in recent completed seasons. Taken
      from their Premier League history when they have one, and otherwise from
      their record in the other big European leagues (Understat). Playing
      history is the strongest signal in the model; using the non-PL record as
      a *fallback* rather than a separate feature is what makes it work, since
      a separate column would be zero for most of the squad and add noise.
      Together they cut error for players new to the league by ~11%.

    - ``hist_gi_per90``: past-season goals + assists per 90 minutes. The rate
      matters, the totals don't: raw goal counts are largely a restatement of
      minutes played, but scoring *rate* is independent of it and is what
      separates an expensive forward from a regular one (MAE EUR8.48m ->
      EUR8.16m). xG/xA per 90 adds nothing on top of actual output.
    """
    out = df.copy()
    out["age_squared"] = out["age"] ** 2

    has_fpl_columns = {"fpl_minutes", "fpl_starts", "fpl_gameweeks"} <= set(out.columns)
    gameweeks = out["fpl_gameweeks"].clip(lower=1) if has_fpl_columns else None
    if "minutes_share" not in out:
        out["minutes_share"] = out["fpl_minutes"] / (gameweeks * 90) if has_fpl_columns else 0.0
    if "starts_share" not in out:
        out["starts_share"] = out["fpl_starts"] / gameweeks if has_fpl_columns else 0.0
    if "has_fpl_record" not in out:
        out["has_fpl_record"] = 0

    if "hist_minutes_share" not in out:
        if "hist_minutes" in out and "hist_seasons" in out:
            # 38 matches x 90 minutes is a full season on the pitch.
            out["hist_minutes_share"] = out["hist_minutes"] / (out["hist_seasons"].clip(lower=1) * 3420)
        else:
            out["hist_minutes_share"] = 0.0
    if "hist_gi_per90" not in out:
        if "hist_goals" in out and "hist_assists" in out:
            # clip(lower=1): players with no history get a 0 rate, not a divide-by-zero
            out["hist_gi_per90"] = (
                (out["hist_goals"] + out["hist_assists"]) / out["hist_minutes"].clip(lower=1) * 90
            )
        else:
            out["hist_gi_per90"] = 0.0
    if "has_hist_record" not in out:
        out["has_hist_record"] = 0

    if "has_nonpl_record" not in out:
        out["has_nonpl_record"] = 0
    if "nonpl_minutes_share" not in out:
        if "nonpl_minutes" in out and "nonpl_available_minutes" in out:
            out["nonpl_minutes_share"] = (
                out["nonpl_minutes"] / out["nonpl_available_minutes"].clip(lower=1)
            )
        else:
            out["nonpl_minutes_share"] = 0.0
    if "nonpl_gi_per90" not in out:
        if "nonpl_goals" in out and "nonpl_assists" in out:
            out["nonpl_gi_per90"] = (
                (out["nonpl_goals"] + out["nonpl_assists"])
                / out["nonpl_minutes"].clip(lower=1)
                * 90
            )
        else:
            out["nonpl_gi_per90"] = 0.0

    has_pl = out["has_hist_record"] == 1
    if "career_minutes_share" not in out:
        out["career_minutes_share"] = np.where(
            has_pl, out["hist_minutes_share"], out["nonpl_minutes_share"]
        )
    if "career_gi_per90" not in out:
        out["career_gi_per90"] = np.where(has_pl, out["hist_gi_per90"], out["nonpl_gi_per90"])
    if "has_any_history" not in out:
        out["has_any_history"] = (has_pl | (out["has_nonpl_record"] == 1)).astype(int)
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
