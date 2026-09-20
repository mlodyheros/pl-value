"""Builds the processed PL player dataset: current squads + market values
(Transfermarkt) joined with playing history (Fantasy Premier League API).

The club list comes from FPL too, so the pipeline needs no API key.
"""

from __future__ import annotations

import argparse
import difflib
import logging
from collections import Counter

import pandas as pd

from backend.config import PROCESSED_DATASET_PATH, SEASONS
from backend.sources import fpl_client
from backend.sources import transfermarkt_scraper as tm
from backend.sources.names import normalize_name

logger = logging.getLogger(__name__)

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
    fpl_data = fpl_client.get_bootstrap_static(refresh=refresh_fpl)
    club_names = fpl_client.team_names(fpl_data)
    if not club_names:
        raise RuntimeError("No PL clubs returned by the FPL API")
    gameweeks = fpl_client.finished_gameweeks(fpl_data)
    logger.info("Found %d PL clubs; %d finished gameweeks", len(club_names), gameweeks)

    squads = tm.fetch_league_squads(club_names)
    logger.info("Scraped %d players total from Transfermarkt", len(squads))

    fpl_by_full, fpl_by_web = _index_fpl_players(fpl_client.parse_players(fpl_data))

    rows = []
    fpl_unmatched = []
    for player in squads:
        fpl_player = _match_fpl(player["name"], fpl_by_full, fpl_by_web)
        if fpl_player is None:
            fpl_unmatched.append(player["name"])
        rows.append(
            {
                **player,
                **_fpl_columns(fpl_player, gameweeks),
                **_history_columns(fpl_player),
            }
        )
        if len(rows) % 100 == 0:
            logger.info(
                "Processed %d/%d players (FPL history is fetched once, then cached)",
                len(rows),
                len(squads),
            )

    if fpl_unmatched:
        logger.info(
            "%d players had no FPL record (FPL stats default to 0), e.g. %s",
            len(fpl_unmatched),
            fpl_unmatched[:10],
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
