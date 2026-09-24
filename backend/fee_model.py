"""A second model: what a club would likely pay, learned from real transfer fees.

The value model predicts Transfermarkt's valuation. This one answers a
different question - what a buying club would actually pay - and learns it from
the paid transfers since mid-2019 in the Kaggle transfer file, each of which
carries the fee alongside the player's market value on the day.

Fees follow the market's figure closely (log fee rises ~0.97 with log value),
but not one-for-one. Premier League buyers pay a premium over everyone else,
young players go for more than their valuation and older ones for less. On
sales by Premier League clubs of players worth EUR5m+ (5-fold, 4 repeats), the
typical miss is x1.36 against x1.43 for "fee = market value"; on sales to
another PL club it is x1.27 against x1.43, where the market value alone runs
about 20% low.

It is kept deliberately simple, because fees are noisy - 80% land between
roughly x0.4 and x2.5 of the estimate - and it cannot see the thing that moves a
fee most after age: the contract. A player with a year left sells cheaper, and
nothing in the transfer file says who had a year left.

**Optional**, like the other Kaggle sources: it needs transfers.csv,
players.csv and player_valuations.csv in ``data/raw/kaggle/``. Without them
there is no fee estimate, and the app simply leaves it out.
"""

from __future__ import annotations

import datetime as dt
import json
import logging

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from backend.config import FEE_CALIBRATION_PATH, FEE_MODEL_PATH, KAGGLE_RAW_DIR
from backend.sources.understat_client import transfermarkt_position_group

logger = logging.getLogger(__name__)

TRANSFERS_FILE = "transfers.csv"
PLAYERS_FILE = "players.csv"
VALUATIONS_FILE = "player_valuations.csv"

NUMERIC = ["log_value", "age", "age_past_23", "age_past_29", "to_pl", "from_pl", "year"]
CATEGORICAL = ["position"]
PREMIER_LEAGUE = "GB1"
# The market that matters for this app. Earlier fees are a different era.
EARLIEST_TRANSFER = "2019-07-01"
# Cheap moves are a different market; fitting them made the estimates for
# players worth tens of millions worse, not better.
MIN_VALUE_EUR = 2_000_000
LEVEL = 0.8

# Kaggle's four position groups, from the GK/D/M/F grouping of Transfermarkt's names.
_KAGGLE_POSITION = {"GK": "Goalkeeper", "D": "Defender", "M": "Midfield", "F": "Attack"}


def available() -> bool:
    return all(
        (KAGGLE_RAW_DIR / name).exists() for name in (TRANSFERS_FILE, PLAYERS_FILE, VALUATIONS_FILE)
    )


def _add_terms(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["age_past_23"] = (out["age"] - 23).clip(lower=0)
    out["age_past_29"] = (out["age"] - 29).clip(lower=0)
    return out


def _club_leagues() -> pd.Series:
    """Club id -> the domestic league it has most often been valued in."""
    valuations = pd.read_csv(
        KAGGLE_RAW_DIR / VALUATIONS_FILE,
        usecols=["current_club_id", "player_club_domestic_competition_id"],
    ).dropna()
    return valuations.groupby("current_club_id").player_club_domestic_competition_id.agg(
        lambda leagues: leagues.mode().iat[0]
    )


def training_frame(today: dt.date | None = None) -> pd.DataFrame:
    """Paid transfers with the market value, age and leagues at the time."""
    today = today or dt.date.today()
    transfers = pd.read_csv(
        KAGGLE_RAW_DIR / TRANSFERS_FILE,
        usecols=["player_id", "transfer_date", "from_club_id", "to_club_id", "transfer_fee", "market_value_in_eur"],
    )
    transfers["date"] = pd.to_datetime(transfers.transfer_date, errors="coerce")
    transfers = transfers[
        (transfers.transfer_fee > 0)
        & (transfers.market_value_in_eur >= MIN_VALUE_EUR)
        & (transfers.date >= EARLIEST_TRANSFER)
        & (transfers.date <= pd.Timestamp(today))
    ]
    players = pd.read_csv(KAGGLE_RAW_DIR / PLAYERS_FILE, usecols=["player_id", "date_of_birth", "position"])
    frame = transfers.merge(players, on="player_id", how="inner")
    frame["age"] = (frame.date - pd.to_datetime(frame.date_of_birth, errors="coerce")).dt.days / 365.25
    frame = frame[frame.age.between(15, 40) & frame.position.isin(_KAGGLE_POSITION.values())]

    leagues = _club_leagues()
    frame["from_pl"] = (frame.from_club_id.map(leagues) == PREMIER_LEAGUE).astype(float)
    frame["to_pl"] = (frame.to_club_id.map(leagues) == PREMIER_LEAGUE).astype(float)
    frame["log_value"] = np.log(frame.market_value_in_eur)
    frame["year"] = frame.date.dt.year + frame.date.dt.dayofyear / 366
    frame["log_fee"] = np.log(frame.transfer_fee)
    return _add_terms(frame).reset_index(drop=True)


def build_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "preprocess",
                ColumnTransformer(
                    [
                        ("numeric", StandardScaler(), NUMERIC),
                        ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
                    ]
                ),
            ),
            ("regressor", LinearRegression()),
        ]
    )


def _out_of_fold(frame: pd.DataFrame, n_splits: int = 5) -> np.ndarray:
    predicted = np.zeros(len(frame))
    for train_idx, test_idx in KFold(n_splits, shuffle=True, random_state=0).split(frame):
        fitted = build_pipeline().fit(frame.iloc[train_idx][NUMERIC + CATEGORICAL], frame.log_fee.iloc[train_idx])
        predicted[test_idx] = fitted.predict(frame.iloc[test_idx][NUMERIC + CATEGORICAL])
    return predicted


def evaluate(frame: pd.DataFrame, predicted_log: np.ndarray) -> dict:
    """Typical miss on the sales that matter here, against 'fee = market value'."""
    sold_by_pl = ((frame.from_pl == 1) & (frame.market_value_in_eur >= 5e6)).to_numpy()
    actual = frame.log_fee.to_numpy()

    def typical(pred: np.ndarray, mask: np.ndarray) -> float:
        return float(np.exp(np.median(np.abs(pred[mask] - actual[mask]))))

    within_pl = sold_by_pl & (frame.to_pl == 1).to_numpy()
    naive = frame.log_value.to_numpy()
    return {
        "transfers": int(len(frame)),
        "typical_miss_pl_sales": typical(predicted_log, sold_by_pl),
        "typical_miss_pl_sales_naive": typical(naive, sold_by_pl),
        "typical_miss_pl_to_pl": typical(predicted_log, within_pl),
        "typical_miss_pl_to_pl_naive": typical(naive, within_pl),
    }


def calibrate(frame: pd.DataFrame, predicted_log: np.ndarray, level: float = LEVEL) -> dict:
    """Out-of-fold residual quantiles: the range a fee lands in, around the estimate."""
    residuals = frame.log_fee.to_numpy() - predicted_log
    tail = (1 - level) / 2
    low, high = np.quantile(residuals, [tail, 1 - tail])
    return {"level": level, "low": float(low), "high": float(high), "n": int(len(frame))}


def estimate(pipeline: Pipeline, calibration: dict, players: pd.DataFrame, today: dt.date | None = None) -> pd.DataFrame:
    """Likely fee for each current PL player: to another PL club, and abroad.

    Anchored on the player's current market value, as the model was trained on
    the market value at the time of each transfer.
    """
    today = today or dt.date.today()
    year = today.year + today.timetuple().tm_yday / 366
    base = pd.DataFrame(
        {
            "log_value": np.log(players["market_value_eur"].astype(float)),
            "age": players["age"].astype(float),
            "from_pl": 1.0,
            "year": year,
            "position": players["position"].map(
                lambda p: _KAGGLE_POSITION[transfermarkt_position_group(p)]
            ),
        },
        index=players.index,
    )
    out = pd.DataFrame(index=players.index)
    for column, to_pl in (("fee_pl_eur", 1.0), ("fee_abroad_eur", 0.0)):
        frame = _add_terms(base.assign(to_pl=to_pl))
        out[column] = np.exp(pipeline.predict(frame[NUMERIC + CATEGORICAL]))
    out["fee_pl_low_eur"] = out.fee_pl_eur * np.exp(calibration["low"])
    out["fee_pl_high_eur"] = out.fee_pl_eur * np.exp(calibration["high"])
    return out


def load() -> tuple[Pipeline, dict] | None:
    if not (FEE_MODEL_PATH.exists() and FEE_CALIBRATION_PATH.exists()):
        return None
    return joblib.load(FEE_MODEL_PATH), json.loads(FEE_CALIBRATION_PATH.read_text())


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not available():
        logger.info("No Kaggle transfer files in %s; skipping the fee model.", KAGGLE_RAW_DIR)
        return
    frame = training_frame()
    predicted = _out_of_fold(frame)
    metrics = evaluate(frame, predicted)
    calibration = calibrate(frame, predicted)
    pipeline = build_pipeline().fit(frame[NUMERIC + CATEGORICAL], frame.log_fee)

    FEE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, FEE_MODEL_PATH)
    FEE_CALIBRATION_PATH.write_text(json.dumps({**calibration, "metrics": metrics}, indent=2))
    logger.info("Fee model: %d transfers", metrics["transfers"])
    logger.info(
        "Sales by PL clubs (EUR5m+): typical miss x%.2f (fee = market value: x%.2f)",
        metrics["typical_miss_pl_sales"],
        metrics["typical_miss_pl_sales_naive"],
    )
    logger.info(
        "PL club to PL club: typical miss x%.2f (fee = market value: x%.2f)",
        metrics["typical_miss_pl_to_pl"],
        metrics["typical_miss_pl_to_pl_naive"],
    )
    logger.info("%.0f%% of fees land between x%.2f and x%.2f of the estimate",
                calibration["level"] * 100, np.exp(calibration["low"]), np.exp(calibration["high"]))


if __name__ == "__main__":
    main()
