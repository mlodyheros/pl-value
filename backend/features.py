"""Feature/target definitions and train-test splitting for the value model."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

NUMERIC_FEATURES = [
    "age",
    "age_squared",
    "age_past_23",
    "age_past_29",
    "has_fpl_record",
    "minutes_share",
    "has_hist_record",
    "has_any_history",
    "career_minutes_share",
    "career_gi_per90",
    "recent_minutes_share",
    "has_transfer_fee",
    "log_transfer_fee",
    "idle_this_season",
    "idle_x_career",
    "idle_x_fee",
]
CATEGORICAL_FEATURES = ["position", "club"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET = "market_value_eur"

# One match's worth of minutes. Below this a player has effectively not featured.
ONE_MATCH_MINUTES = 90

# Knots for the age curve. A plain parabola is forced to be symmetric, and the
# one this data fits peaks at 21 - too young, so it asks too much for teenagers
# and too little for players in their late twenties. Letting the curve bend at
# these two ages fixes the shape without giving it enough freedom to wander.
AGE_KNOTS = (23, 29)


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add the features computed from raw columns (returns a copy).

    - ``age_squared`` and ``age_past_23`` / ``age_past_29``: value peaks in the
      mid-20s and falls off on both sides, which a straight line can't express.
      A parabola alone is not enough either - being symmetric, the one this data
      fits peaks at 21, so it asks too much for teenagers (median predicted /
      actual 1.13 at ages 20-23) and too little for players at their peak. Two
      hinge terms let the curve bend at 23 and 29 (MAE EUR6.76m -> EUR6.69m,
      6 standard errors over 100 paired folds; top-decile EUR15.4m -> EUR15.0m).
    - ``minutes_share``: this season's FPL minutes as a fraction of those
      available, so regulars stand out and the feature stays comparable as the
      season goes on. Defaults to 0 when there is no FPL data (or before
      gameweek 1). ``starts_share`` is still computed for exploration but is
      not a model feature: it correlates 0.98 with minutes_share, which split
      one effect across two coefficients and left starts with a negative sign
      it does not deserve. Dropping it changed nothing measurable (MAE EUR7.35m
      either way) and made the rest readable.

    ``has_any_history`` carries a negative coefficient, which looks wrong and
    is not. Given the career shares, it separates a player with no record
    anywhere - whose zeros mean "unknown" - from one whose record exists and
    says they barely played. Removing it costs real accuracy (MAE EUR7.35m ->
    EUR7.58m), so the sign is doing a job.
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
    - ``recent_minutes_share``: the same share, for the newest completed season
      alone. Career totals average several seasons together, so a player who
      has just become a regular - or just lost their place - is described badly
      by them. The latest season on its own cut error sharply (MAE EUR7.90m ->
      EUR7.37m, and EUR18.6m -> EUR16.3m among the dearest tenth), and it is
      the strongest answer found so far to the model under-asking for expensive
      players. Career and recent both earn their place: one says who a player
      has been, the other where they stand now.
    - ``log_transfer_fee`` (with ``has_transfer_fee``): what a club last paid
      for this player. Every other feature describes what happened on the
      pitch, which left the model blind to an expensive player who has barely
      played - it asked EUR28m for Geovany Quenda against a market EUR42m
      purely because minutes were all it could see. Worth MAE EUR7.35m ->
      EUR7.01m, and EUR16.3m -> EUR15.5m among the dearest tenth. A fee is not
      the target leaking: it is a real transaction agreed before the valuation
      being predicted. The file behind it is an optional download, so when it
      is missing every player is simply marked "fee unknown".
    - ``idle_this_season`` and its two products: whether the player has barely
      featured this season (under one match's worth of minutes), and that flag
      multiplied by their career share and by their fee.

      These exist because a handful of well-known players were badly
      under-valued - Alisson at EUR5.7m against a market EUR15m, Grealish at
      EUR9.7m against EUR20m - and the cause was not age, as it first appeared.
      It was that a spell out of the side four gameweeks into a season was being
      read as strong evidence. The products say: when someone is not playing,
      lean on what they have done before and what they cost. A linear model
      cannot form a product of its own features, so this had to be built.

      Worth EUR0.24m of MAE over 100 paired folds (7.5 standard errors, better
      in 81% of them). Shrinking this season's minutes toward the career figure
      was tried first and does nothing at all: that is a linear blend of two
      features the model already has, so it can already express it.
    """
    out = df.copy()
    out["age_squared"] = out["age"] ** 2
    for knot in AGE_KNOTS:
        out[f"age_past_{knot}"] = (out["age"] - knot).clip(lower=0)

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

    if "has_transfer_fee" not in out:
        out["has_transfer_fee"] = 0
    if "log_transfer_fee" not in out:
        fees = (
            pd.to_numeric(out["transfer_fee_eur"], errors="coerce").fillna(0)
            if "transfer_fee_eur" in out
            else 0.0
        )
        out["log_transfer_fee"] = np.log1p(fees)

    # Four gameweeks in, not featuring says less about a player than the
    # feature would otherwise imply; the products below restore the balance.
    if "idle_this_season" not in out:
        minutes = (
            pd.to_numeric(out["fpl_minutes"], errors="coerce").fillna(0)
            if "fpl_minutes" in out
            else pd.Series(0.0, index=out.index)
        )
        out["idle_this_season"] = (minutes < ONE_MATCH_MINUTES).astype(float)

    if "recent_minutes_share" not in out:
        if "recent_minutes" in out:
            pl_recent = out["recent_minutes"] / out["recent_available_minutes"].clip(lower=1)
            non_pl_recent = (
                out["nonpl_recent_minutes"] / out["nonpl_recent_available_minutes"].clip(lower=1)
                if "nonpl_recent_minutes" in out
                else 0.0
            )
            out["recent_minutes_share"] = np.where(has_pl, pl_recent, non_pl_recent)
        else:
            out["recent_minutes_share"] = 0.0
    if "idle_x_career" not in out:
        out["idle_x_career"] = out["idle_this_season"] * out["career_minutes_share"]
    if "idle_x_fee" not in out:
        out["idle_x_fee"] = out["idle_this_season"] * out["log_transfer_fee"]
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
