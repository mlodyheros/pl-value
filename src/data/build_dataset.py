"""Builds the processed PL player dataset: current squads + market values
(Transfermarkt) joined with recent-seasons performance stats (football-data.org).
"""

from __future__ import annotations

import difflib
import logging

import pandas as pd

from src.config import CURRENT_SEASON, PROCESSED_DATASET_PATH, SEASONS
from src.data import football_data_client as fd
from src.data import transfermarkt_scraper as tm

logger = logging.getLogger(__name__)

_EMPTY_STATS = {"goals": 0, "assists": 0, "penalties": 0, "appearances": 0}


def _aggregate_performance_stats(seasons: list[int]) -> dict[str, dict]:
    """Sum goals/assists/penalties/appearances per player name across seasons."""
    stats: dict[str, dict] = {}
    for season in seasons:
        scorers = fd.get_scorers(season)
        logger.info("Season %s: %d scorer records", season, len(scorers))
        for entry in scorers:
            name = entry["player"]["name"]
            row = stats.setdefault(name, dict(_EMPTY_STATS))
            row["goals"] += entry.get("goals") or 0
            row["assists"] += entry.get("assists") or 0
            row["penalties"] += entry.get("penalties") or 0
            row["appearances"] += entry.get("playedMatches") or 0
    return stats


def _match_stats(name: str, stats: dict[str, dict]) -> tuple[dict, bool]:
    if name in stats:
        return stats[name], True
    close = difflib.get_close_matches(name, stats.keys(), n=1, cutoff=0.85)
    if close:
        return stats[close[0]], True
    return dict(_EMPTY_STATS), False


def build_dataset() -> pd.DataFrame:
    teams = fd.get_teams(CURRENT_SEASON)
    club_names = [team["name"] for team in teams]
    if not club_names:
        raise RuntimeError(
            "No PL clubs returned by football-data.org - check FOOTBALL_DATA_API_KEY and CURRENT_SEASON"
        )
    logger.info("Found %d PL clubs for season %s", len(club_names), CURRENT_SEASON)

    squads = tm.fetch_league_squads(club_names)
    logger.info("Scraped %d players total from Transfermarkt", len(squads))

    stats = _aggregate_performance_stats(SEASONS)

    rows = []
    unmatched = []
    for player in squads:
        player_stats, matched = _match_stats(player["name"], stats)
        if not matched:
            unmatched.append(player["name"])
        rows.append({**player, **player_stats})

    if unmatched:
        logger.info(
            "%d players had no recent scorer record (stats defaulted to 0), e.g. %s",
            len(unmatched),
            unmatched[:10],
        )

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["market_value_eur", "age", "position"])
    PROCESSED_DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESSED_DATASET_PATH, index=False)
    logger.info("Wrote %d players to %s", len(df), PROCESSED_DATASET_PATH)
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build_dataset()
