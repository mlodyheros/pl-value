"""Builds the processed PL player dataset: current squads + market values
(Transfermarkt) joined with recent-seasons performance stats (football-data.org).
"""

from __future__ import annotations

import argparse
import difflib
import logging
from collections import Counter

import pandas as pd

from src.config import CURRENT_SEASON, PROCESSED_DATASET_PATH, SEASONS
from src.data import football_data_client as fd
from src.data import fpl_client
from src.data import transfermarkt_scraper as tm
from src.data.names import normalize_name

logger = logging.getLogger(__name__)

_EMPTY_STATS = {"goals": 0, "assists": 0, "penalties": 0, "appearances": 0}
_EMPTY_FPL = {
    "fpl_minutes": 0,
    "fpl_starts": 0,
    "fpl_xg": 0.0,
    "fpl_xa": 0.0,
    "fpl_defensive_contribution": 0,
    "fpl_price": 0.0,
}
_EMPTY_HIST = {
    "hist_minutes": 0,
    "hist_starts": 0,
    "hist_goals": 0,
    "hist_assists": 0,
    "hist_xg": 0.0,
    "hist_xa": 0.0,
    "hist_seasons": 0,
}
_FPL_FUZZY_CUTOFF = 0.88


def _aggregate_performance_stats(seasons: list[int]) -> dict[str, dict]:
    """Sum goals/assists/penalties/appearances per player name across seasons."""
    stats: dict[str, dict] = {}
    for season in seasons:
        scorers = fd.get_scorers(season)
        logger.info("Season %s: %d scorer records", season, len(scorers))
        for entry in scorers:
            name = normalize_name(entry["player"]["name"])
            row = stats.setdefault(name, dict(_EMPTY_STATS))
            row["goals"] += entry.get("goals") or 0
            row["assists"] += entry.get("assists") or 0
            row["penalties"] += entry.get("penalties") or 0
            row["appearances"] += entry.get("playedMatches") or 0
    return stats


def _match_stats(name: str, stats: dict[str, dict]) -> tuple[dict, bool]:
    """Look up a player's stats by (normalized) name, falling back to fuzzy match."""
    name = normalize_name(name)
    if name in stats:
        return stats[name], True
    close = difflib.get_close_matches(name, stats.keys(), n=1, cutoff=0.85)
    if close:
        return stats[close[0]], True
    return dict(_EMPTY_STATS), False


def _index_fpl_players(players: list[dict]) -> tuple[dict, dict]:
    """Lookups by normalized full name and by (unique-only) short web name."""
    by_full: dict[str, dict] = {}
    for player in players:
        key = normalize_name(f"{player['first_name']} {player['second_name']}")
        # Same name twice (rare): keep whoever has actually played.
        if key not in by_full or player["fpl_minutes"] > by_full[key]["fpl_minutes"]:
            by_full[key] = player

    web_counts = Counter(normalize_name(p["web_name"]) for p in players)
    by_web = {
        normalize_name(p["web_name"]): p
        for p in players
        if web_counts[normalize_name(p["web_name"])] == 1
    }
    return by_full, by_web


def _match_fpl(name: str, by_full: dict, by_web: dict) -> dict | None:
    """Full name, short name (Transfermarkt's 'Gabriel'), unique name-token
    subset (Transfermarkt's 'David Raya' vs FPL's 'David Raya Martin'), then fuzzy."""
    key = normalize_name(name)
    if key in by_full:
        return by_full[key]
    if key in by_web:
        return by_web[key]

    tokens = set(key.split())
    if len(tokens) >= 2:
        supersets = [p for full, p in by_full.items() if tokens <= set(full.split())]
        if len(supersets) == 1:
            return supersets[0]
    close = difflib.get_close_matches(key, by_full.keys(), n=1, cutoff=_FPL_FUZZY_CUTOFF)
    return by_full[close[0]] if close else None


def _fpl_columns(player: dict | None, gameweeks: int) -> dict:
    if player is None:
        return {**_EMPTY_FPL, "fpl_id": None, "fpl_gameweeks": gameweeks, "has_fpl_record": 0}
    values = {key: player[key] for key in _EMPTY_FPL}
    return {**values, "fpl_id": player.get("fpl_id"), "fpl_gameweeks": gameweeks, "has_fpl_record": 1}


def _history_columns(player: dict | None) -> dict:
    """Past-season FPL stats over ``SEASONS`` for a matched FPL player."""
    history = _EMPTY_HIST
    if player is not None and player.get("fpl_id") is not None:
        history = fpl_client.aggregate_history(
            fpl_client.get_player_history(player["fpl_id"]), SEASONS
        )
    return {**history, "has_hist_record": int(history["hist_seasons"] > 0)}


def build_dataset(refresh_fpl: bool = False) -> pd.DataFrame:
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

    fpl_data = fpl_client.get_bootstrap_static(refresh=refresh_fpl)
    gameweeks = fpl_client.finished_gameweeks(fpl_data)
    fpl_by_full, fpl_by_web = _index_fpl_players(fpl_client.parse_players(fpl_data))
    logger.info("FPL: %d finished gameweeks", gameweeks)

    rows = []
    unmatched = []
    fpl_unmatched = []
    for player in squads:
        player_stats, matched = _match_stats(player["name"], stats)
        if not matched:
            unmatched.append(player["name"])
        fpl_player = _match_fpl(player["name"], fpl_by_full, fpl_by_web)
        if fpl_player is None:
            fpl_unmatched.append(player["name"])
        rows.append(
            {
                **player,
                **player_stats,
                "has_scorer_record": int(matched),
                **_fpl_columns(fpl_player, gameweeks),
                **_history_columns(fpl_player),
            }
        )
        if len(rows) % 100 == 0:
            logger.info("Processed %d/%d players (FPL history is fetched once, then cached)", len(rows), len(squads))

    if fpl_unmatched:
        logger.info(
            "%d players had no FPL record (FPL stats default to 0), e.g. %s",
            len(fpl_unmatched),
            fpl_unmatched[:10],
        )

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
    parser = argparse.ArgumentParser(description="Build the processed PL player dataset")
    parser.add_argument(
        "--refresh-fpl",
        action="store_true",
        help="ignore the cached FPL response and refetch it",
    )
    build_dataset(refresh_fpl=parser.parse_args().refresh_fpl)
