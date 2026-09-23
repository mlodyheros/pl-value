"""League minutes from the Transfermarkt datasets on Kaggle, for the players
Understat cannot find.

Understat spells some names its own way, and a player it fails to match looks
like a newcomer with no record anywhere: Jamie Gittens, two seasons a regular
in the Bundesliga, came through as a blank, and so did Mohamed-Ali Cho and
Jean-Mattéo Bahoya. These files come from Transfermarkt - the same site the
squads are scraped from - so the names agree.

Only the leagues Understat itself covers are read. Minutes in the Belgian or
Danish league are not comparable to minutes in La Liga, and counting them as if
they were made the model worse (tested: MAE up 1.5 standard errors, 4 among the
dearest tenth). Recovering the missed big-league players, on the other hand,
cut MAE by 9 standard errors over 100 paired folds.

**Optional**, like ``transfer_fees``: it needs players.csv, appearances.csv and
competitions.csv from https://www.kaggle.com/datasets/davidcariboo/player-scores
in ``data/raw/kaggle/``. Without them every lookup simply finds nothing.
"""

from __future__ import annotations

import datetime as dt
import logging

import numpy as np
import pandas as pd

from backend.config import KAGGLE_RAW_DIR
from backend.sources.names import normalize_name

logger = logging.getLogger(__name__)

APPEARANCES_FILE = "appearances.csv"
PLAYERS_FILE = "players.csv"
COMPETITIONS_FILE = "competitions.csv"

# Transfermarkt's codes for the leagues in config.UNDERSTAT_LEAGUES.
LEAGUES = ("ES1", "L1", "IT1", "FR1", "RU1")
# Same guard as transfer_fees: surnames repeat across tens of thousands of players.
_AGE_TOLERANCE_YEARS = 1.2


def available() -> bool:
    return all(
        (KAGGLE_RAW_DIR / name).exists()
        for name in (APPEARANCES_FILE, PLAYERS_FILE, COMPETITIONS_FILE)
    )


def _season_minutes() -> dict[str, int]:
    """A full season on the pitch in each league: every club plays the rest twice."""
    competitions = pd.read_csv(
        KAGGLE_RAW_DIR / COMPETITIONS_FILE, usecols=["competition_id", "total_clubs"]
    )
    competitions = competitions[competitions.competition_id.isin(LEAGUES)].dropna()
    return {
        row.competition_id: int(2 * (row.total_clubs - 1) * 90)
        for row in competitions.itertuples()
    }


def _league_seasons(seasons: list[int]) -> pd.DataFrame:
    """Minutes, goals and assists per player and season in the covered leagues."""
    columns = ["player_id", "competition_id", "date", "minutes_played", "goals", "assists"]
    parts = [
        chunk[chunk.competition_id.isin(LEAGUES)]
        for chunk in pd.read_csv(
            KAGGLE_RAW_DIR / APPEARANCES_FILE, usecols=columns, chunksize=500_000
        )
    ]
    apps = pd.concat(parts, ignore_index=True)
    date = pd.to_datetime(apps.date, errors="coerce")
    apps = apps[date.notna()].copy()
    date = date[date.notna()]
    # Seasons run July to June and are named after the year they start.
    apps["season"] = np.where(date.dt.month >= 7, date.dt.year, date.dt.year - 1)
    apps = apps[apps.season.isin(seasons)]
    apps["season_minutes"] = apps.competition_id.map(_season_minutes())
    # A player who moved between two of these leagues mid-season still had
    # only one season's worth of minutes available.
    return (
        apps.groupby(["player_id", "season"])
        .agg(
            minutes=("minutes_played", "sum"),
            goals=("goals", "sum"),
            assists=("assists", "sum"),
            season_minutes=("season_minutes", "max"),
        )
        .reset_index()
    )


def build_index(seasons: list[int], today: dt.date | None = None) -> dict[str, list[dict]]:
    """Map normalized name -> candidates, each with an age and league-season records.

    Records have the same shape as Understat's (season, minutes, goals, assists,
    season_minutes), so they aggregate the same way.
    """
    if not available():
        logger.info("No Kaggle appearances in %s; Understat alone covers non-PL records.", KAGGLE_RAW_DIR)
        return {}

    today = today or dt.date.today()
    per_season = _league_seasons(seasons)
    records = {
        int(player_id): [
            {
                "season": int(r.season),
                "minutes": int(r.minutes),
                "goals": int(r.goals),
                "assists": int(r.assists),
                "season_minutes": int(r.season_minutes),
            }
            for r in group.itertuples()
        ]
        for player_id, group in per_season.groupby("player_id")
    }

    players = pd.read_csv(
        KAGGLE_RAW_DIR / PLAYERS_FILE, usecols=["player_id", "name", "date_of_birth"]
    )
    players = players[players.player_id.isin(records.keys())]
    born = pd.to_datetime(players.date_of_birth, errors="coerce")
    players = players.assign(age=(pd.Timestamp(today) - born).dt.days / 365.25).dropna(subset=["age"])

    index: dict[str, list[dict]] = {}
    for row in players.itertuples():
        index.setdefault(normalize_name(str(row.name)), []).append(
            {"age": float(row.age), "records": records[int(row.player_id)]}
        )
    logger.info("Kaggle appearances: %d players in the leagues Understat covers", len(index))
    return index


def lookup(index: dict, name: str, age: float | None) -> list[dict] | None:
    """This player's league-season records, confirmed by age.

    Without an age to check, a shared name would attach someone else's career,
    so an ambiguous name returns nothing.
    """
    candidates = index.get(normalize_name(name))
    if not candidates:
        return None
    if age is None or pd.isna(age):
        return candidates[0]["records"] if len(candidates) == 1 else None
    agreeing = [c for c in candidates if abs(c["age"] - age) <= _AGE_TOLERANCE_YEARS]
    return agreeing[0]["records"] if len(agreeing) == 1 else None
