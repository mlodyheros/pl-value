"""How much to trust a prediction, measured rather than asserted.

The model returns one number for every player, but it is not equally sure of
all of them. Players with years of Premier League history behind them are
predicted from a lot of evidence; a summer signing from a league none of our
sources cover is predicted from age, position and club alone, and is routinely
wrong by a factor of four.

So predictions are grouped by *what data backed them*, and each group gets an
interval measured from that group's own out-of-fold errors. Errors are
multiplicative (the model is fitted on log value), so the intervals are ratios:
a prediction of EUR20m in a group whose errors span x0.5-x2 means "somewhere
between EUR10m and EUR40m".

Nothing here changes a prediction. It only says how much room to leave around it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.features import split_features_target

# Ordered most to least evidence.
PL_HISTORY = "pl_history"
NON_PL_HISTORY = "non_pl_history"
NO_HISTORY = "no_history"
TIERS = (PL_HISTORY, NON_PL_HISTORY, NO_HISTORY)

TIER_LABELS = {
    PL_HISTORY: "backed by Premier League history",
    NON_PL_HISTORY: "backed by other leagues only",
    NO_HISTORY: "no recent playing record in any covered league",
}

# Below this, a tier's own errors are too few to quantile reliably, so it
# borrows the overall distribution instead of inventing a precise-looking one.
MIN_TIER_SAMPLES = 30

DEFAULT_LEVELS = (0.5, 0.8)
_OVERALL = "overall"


def coverage_tiers(df: pd.DataFrame) -> pd.Series:
    """Which evidence backs each player's prediction."""
    has_pl = df.get("has_hist_record", pd.Series(0, index=df.index)) == 1
    has_non_pl = df.get("has_nonpl_record", pd.Series(0, index=df.index)) == 1
    return pd.Series(
        np.where(has_pl, PL_HISTORY, np.where(has_non_pl, NON_PL_HISTORY, NO_HISTORY)),
        index=df.index,
    )


def _quantiles(residuals: np.ndarray, levels) -> dict:
    out = {}
    for level in levels:
        tail = (1 - level) / 2
        low, high = np.quantile(residuals, [tail, 1 - tail])
        out[str(level)] = [float(low), float(high)]
    return out


def calibrate(
    df: pd.DataFrame,
    n_splits: int = 5,
    random_state: int = 42,
    levels=DEFAULT_LEVELS,
) -> dict:
    """Measure each tier's error spread from out-of-fold predictions.

    Out-of-fold matters: errors measured on the training data would look far
    smaller than the ones real predictions actually make. They are the same
    averaged out-of-fold figures the app serves, so the ranges fit the numbers
    they are drawn around.
    """
    from backend.model import out_of_fold_predictions

    _, y = split_features_target(df)
    predicted = np.log1p(out_of_fold_predictions(df, n_splits=n_splits, random_state=random_state))

    # log(predicted) - log(actual); positive means the model asked too much.
    residuals = predicted - y.to_numpy()
    tiers = coverage_tiers(df).to_numpy()

    calibration = {_OVERALL: {"n": len(residuals), "levels": _quantiles(residuals, levels)}}
    for tier in TIERS:
        tier_residuals = residuals[tiers == tier]
        if len(tier_residuals) < MIN_TIER_SAMPLES:
            continue
        calibration[tier] = {
            "n": int(len(tier_residuals)),
            "levels": _quantiles(tier_residuals, levels),
        }
    return calibration


def interval(
    prediction_eur: float, tier: str, calibration: dict, level: float = 0.8
) -> tuple[float, float]:
    """Plausible range around a prediction, from that tier's measured errors."""
    entry = calibration.get(tier) or calibration[_OVERALL]
    bounds = entry["levels"].get(str(level)) or calibration[_OVERALL]["levels"][str(level)]
    low, high = bounds
    # residual = log(pred) - log(actual), so actual = pred / exp(residual).
    return prediction_eur / np.exp(high), prediction_eur / np.exp(low)


def spread(tier: str, calibration: dict, level: float = 0.8) -> float:
    """How many times wider the high end of the range is than the low end."""
    low, high = interval(1.0, tier, calibration, level)
    return high / low


def describe(tier: str, calibration: dict, level: float = 0.8) -> str:
    """A short, scannable summary of how wide this tier's range is.

    The bands are deliberately coarse. The measured spread of the two
    history-backed tiers differs (about x4.4 against x3.2), but the smaller
    tier holds only ~60 players, which is far too few for that gap to mean
    anything - splitting them would advertise a precision the sample does not
    support, and would oddly rank players we know less about as safer.

    There is no "high confidence" band on purpose: even the best-evidenced
    group spans more than a factor of four, and calling that high would
    misrepresent the model.
    """
    ratio = spread(tier, calibration, level)
    strength = "moderate confidence" if ratio < 6 else "low confidence"
    return f"{strength} - {TIER_LABELS[tier]}"
