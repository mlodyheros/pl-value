"""Client for Understat's league data (xG stats for Europe's big leagues).

This fills the gap FPL leaves: a quarter of a PL squad has never played in the
Premier League (signings from abroad, academy players), so they arrive with no
history at all and the model badly under-predicts them. Understat covers La
Liga, the Bundesliga, Serie A, Ligue 1 and the Russian league, which is where
many of those players came from.

Understat's pages no longer embed their data - the HTML is a shell that fetches
``/getLeagueData/<league>/<season>`` over AJAX. That endpoint returns 404 unless
the request carries ``X-Requested-With: XMLHttpRequest``, so this client sends it.

One request per league-season (20 in total), cached on disk: past seasons never
change, so the cache does not expire.
"""

from __future__ import annotations

import json
import logging
import time

import requests

from backend.config import (
    UNDERSTAT_BASE_URL,
    UNDERSTAT_DELAY_SECONDS,
    UNDERSTAT_LEAGUES,
    UNDERSTAT_RAW_DIR,
    TRANSFERMARKT_HEADERS,
)
from backend.sources.names import normalize_name

logger = logging.getLogger(__name__)

_last_request_time: float | None = None


def _throttle() -> None:
    global _last_request_time
    if _last_request_time is not None:
        wait = UNDERSTAT_DELAY_SECONDS - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
    _last_request_time = time.monotonic()


def _slug(league: str) -> str:
    return league.replace(" ", "_")


def get_league_players(league: str, season: int) -> list[dict]:
    """Every player's season totals for one league-season."""
    UNDERSTAT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = UNDERSTAT_RAW_DIR / f"{_slug(league)}_{season}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    url = f"{UNDERSTAT_BASE_URL}/getLeagueData/{league.replace(' ', '%20')}/{season}"
    headers = {**TRANSFERMARKT_HEADERS, "X-Requested-With": "XMLHttpRequest"}
    _throttle()
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    players = response.json().get("players", [])
    cache_file.write_text(json.dumps(players))
    return players


def _season_minutes(players: list[dict]) -> int:
    """Minutes an ever-present player would have played in this league-season.

    Leagues differ in length (34 vs 38 matches) and this avoids hard-coding it.
    """
    games = max((int(p.get("games") or 0) for p in players), default=0)
    return max(games, 1) * 90


def build_index(
    leagues: list[str] | None = None, seasons: list[int] | None = None
) -> dict[str, list[dict]]:
    """Map normalized player name -> their league-season records."""
    leagues = leagues if leagues is not None else UNDERSTAT_LEAGUES
    index: dict[str, list[dict]] = {}
    for league in leagues:
        for season in seasons or []:
            players = get_league_players(league, season)
            season_minutes = _season_minutes(players)
            for player in players:
                index.setdefault(normalize_name(player["player_name"]), []).append(
                    {
                        "league": league,
                        "season": season,
                        "position": player.get("position") or "",
                        "minutes": int(player.get("time") or 0),
                        "goals": int(player.get("goals") or 0),
                        "assists": int(player.get("assists") or 0),
                        "season_minutes": season_minutes,
                    }
                )
            logger.info("Understat %s %s: %d players", league, season, len(players))
    return index


def aggregate(records: list[dict]) -> dict:
    """Sum a player's non-PL record into the same shape as the FPL history."""
    minutes = sum(r["minutes"] for r in records)
    available = sum(r["season_minutes"] for r in records)
    return {
        "nonpl_minutes": minutes,
        "nonpl_goals": sum(r["goals"] for r in records),
        "nonpl_assists": sum(r["assists"] for r in records),
        "nonpl_seasons": len(records),
        "nonpl_available_minutes": available,
    }


def position_group(understat_position: str) -> str:
    """Understat's codes ('D S', 'F M S', 'GK') collapsed to GK/D/M/F."""
    code = (understat_position or "").upper().split()
    if "GK" in code:
        return "GK"
    if "D" in code:
        return "D"
    if "M" in code or "AM" in code or "DM" in code:
        return "M"
    return "F"


def transfermarkt_position_group(position: str) -> str:
    """Transfermarkt's position names collapsed the same way."""
    name = position or ""
    if "Goalkeeper" in name:
        return "GK"
    if "Back" in name:
        return "D"
    if "Midfield" in name:
        return "M"
    return "F"
