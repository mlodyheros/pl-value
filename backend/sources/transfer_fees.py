"""What clubs actually paid, from the Transfermarkt datasets published on Kaggle.

Every other feature here describes what a player did on the pitch. That leaves
the model blind to a specific, expensive kind of player: the one a club has just
bought for a fortune and who has barely played. It valued Geovany Quenda at
EUR28m against a market EUR42m, and Luka Vuskovic at EUR13m against EUR60m,
because minutes are all it could see.

A fee is not the target leaking. It is a real transaction, agreed before the
valuation we predict, and it is the single most useful thing this project has
added since playing history.

It is a snapshot, though, and a squad changes after it is taken. Fees paid
this season are therefore read from each club's own Transfermarkt transfers
page as well (``transfermarkt_scraper.fetch_arrivals``), and those win when both
exist - see ``build_dataset._fee_columns``.

**This source is optional.** It is a one-off download rather than an API, so a
clone of this repository will not have it, and the pipeline has to run without
it - every player simply gets "fee unknown" and the model falls back on what it
had before. Get it from
https://www.kaggle.com/datasets/davidcariboo/player-scores and put players.csv
and transfers.csv in ``data/raw/kaggle/``.
"""

from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from backend.config import KAGGLE_RAW_DIR
from backend.sources.names import normalize_name

logger = logging.getLogger(__name__)

PLAYERS_FILE = "players.csv"
TRANSFERS_FILE = "transfers.csv"

# Name matches are confirmed against age, because these files carry tens of
# thousands of players and surnames repeat.
_AGE_TOLERANCE_YEARS = 1.2
# Players whose last recorded season is older than this are stale duplicates of
# a name we care about, not the player themselves.
_EARLIEST_LAST_SEASON = 2025


def available() -> bool:
    return (KAGGLE_RAW_DIR / PLAYERS_FILE).exists() and (
        KAGGLE_RAW_DIR / TRANSFERS_FILE
    ).exists()


def _index_players(today: dt.date) -> pd.DataFrame:
    players = pd.read_csv(
        KAGGLE_RAW_DIR / PLAYERS_FILE,
        usecols=["player_id", "name", "date_of_birth", "last_season"],
    )
    players = players[players.last_season >= _EARLIEST_LAST_SEASON].copy()
    players["key"] = players.name.astype(str).map(normalize_name)
    born = pd.to_datetime(players.date_of_birth, errors="coerce")
    players["age"] = (pd.Timestamp(today) - born).dt.days / 365.25
    return players.dropna(subset=["age"])


def _latest_fees(today: dt.date) -> pd.DataFrame:
    transfers = pd.read_csv(
        KAGGLE_RAW_DIR / TRANSFERS_FILE,
        usecols=["player_id", "transfer_date", "transfer_fee"],
    )
    transfers["date"] = pd.to_datetime(transfers.transfer_date, errors="coerce")
    # Some rows carry dates years in the future; a fee not yet paid is not evidence.
    transfers = transfers[(transfers.date <= pd.Timestamp(today)) & (transfers.transfer_fee > 0)]
    latest = transfers.sort_values("date").groupby("player_id").tail(1)
    return latest.set_index("player_id")[["transfer_fee", "date"]]


def build_index(today: dt.date | None = None) -> dict[str, dict]:
    """Map normalized player name -> their most recent fee.

    Returns an empty index when the files are absent, which leaves every player
    marked "fee unknown" rather than failing the build.
    """
    if not available():
        logger.info(
            "No Kaggle transfer data in %s; fees will be unknown. See %s.",
            KAGGLE_RAW_DIR,
            "backend/sources/transfer_fees.py",
        )
        return {}

    today = today or dt.date.today()
    players = _index_players(today)
    fees = _latest_fees(today)

    index: dict[str, dict] = {}
    for row in players.itertuples():
        if row.player_id not in fees.index:
            continue
        fee = fees.loc[row.player_id]
        entry = {
            "player_id": int(row.player_id),
            "age": float(row.age),
            "fee_eur": float(fee.transfer_fee),
            "fee_date": fee.date.date().isoformat(),
        }
        # Keep every candidate for a name; lookup() picks on age.
        index.setdefault(row.key, []).append(entry)

    logger.info("Transfer fees: indexed %d names", len(index))
    return index


def lookup(index: dict, name: str, age: float | None) -> dict | None:
    """The fee for this player, confirmed by age.

    Without an age to check against, a shared surname would attach someone
    else's fee, so an ambiguous name returns nothing.
    """
    candidates = index.get(normalize_name(name))
    if not candidates:
        return None
    if age is None or pd.isna(age):
        return candidates[0] if len(candidates) == 1 else None

    agreeing = [c for c in candidates if abs(c["age"] - age) <= _AGE_TOLERANCE_YEARS]
    return agreeing[0] if len(agreeing) == 1 else None
