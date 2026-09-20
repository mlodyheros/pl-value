"""Client for the official Fantasy Premier League API (no key required).

One call to ``bootstrap-static`` returns every player's season-to-date
minutes, starts, expected goals/assists and defensive stats. That fills the gap
football-data.org leaves (no minutes, and only scorers listed), but it only
covers the *current* season so far.

The raw response is cached on disk and refetched once it is older than
``FPL_CACHE_MAX_AGE_HOURS``, since the numbers change every gameweek.
"""

from __future__ import annotations

import json
import logging
import time

import requests

from src.config import (
    FPL_BASE_URL,
    FPL_CACHE_MAX_AGE_HOURS,
    FPL_RAW_DIR,
    TRANSFERMARKT_HEADERS,
)

logger = logging.getLogger(__name__)

_CACHE_FILE = FPL_RAW_DIR / "bootstrap_static.json"


def get_bootstrap_static(refresh: bool = False) -> dict:
    """Raw ``bootstrap-static`` payload, from cache unless stale or ``refresh``."""
    if not refresh and _CACHE_FILE.exists():
        age_hours = (time.time() - _CACHE_FILE.stat().st_mtime) / 3600
        if age_hours < FPL_CACHE_MAX_AGE_HOURS:
            return json.loads(_CACHE_FILE.read_text())
        logger.info("FPL cache is %.1fh old, refetching", age_hours)

    response = requests.get(
        f"{FPL_BASE_URL}/bootstrap-static/", headers=TRANSFERMARKT_HEADERS, timeout=30
    )
    response.raise_for_status()
    data = response.json()
    FPL_RAW_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps(data))
    return data


def finished_gameweeks(data: dict) -> int:
    return sum(1 for event in data.get("events", []) if event.get("finished"))


def parse_players(data: dict) -> list[dict]:
    """Flatten the payload into one record per FPL player."""
    teams = {team["id"]: team["name"] for team in data.get("teams", [])}
    gameweeks = finished_gameweeks(data)

    players = []
    for element in data.get("elements", []):
        players.append(
            {
                "first_name": element.get("first_name", ""),
                "second_name": element.get("second_name", ""),
                "web_name": element.get("web_name", ""),
                "fpl_team": teams.get(element.get("team")),
                "fpl_minutes": element.get("minutes") or 0,
                "fpl_starts": element.get("starts") or 0,
                # xG/xA come back as strings, e.g. "0.86"
                "fpl_xg": float(element.get("expected_goals") or 0),
                "fpl_xa": float(element.get("expected_assists") or 0),
                "fpl_defensive_contribution": element.get("defensive_contribution") or 0,
                "fpl_price": (element.get("now_cost") or 0) / 10,  # tenths of £m
                "fpl_gameweeks": gameweeks,
            }
        )
    return players


def get_players(refresh: bool = False) -> list[dict]:
    return parse_players(get_bootstrap_static(refresh))
