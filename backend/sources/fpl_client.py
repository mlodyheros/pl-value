"""Client for the official Fantasy Premier League API (no key required).

One call to ``bootstrap-static`` returns every player's season-to-date
minutes, starts, expected goals/assists and defensive stats. That fills the gap
football-data.org leaves (no minutes, and only scorers listed), but it only
covers the *current* season so far.

``element-summary/<id>`` adds ``history_past``: the same stats for every past
season the player was in the FPL, including goals/assists for non-scorers.
That costs one request per player, so it is throttled and cached per player.

The bootstrap response is cached on disk and refetched once it is older than
``FPL_CACHE_MAX_AGE_HOURS``, since the numbers change every gameweek.
"""

from __future__ import annotations

import json
import logging
import time

import requests

from backend.config import (
    FPL_BASE_URL,
    FPL_CACHE_MAX_AGE_HOURS,
    FPL_HISTORY_CACHE_MAX_AGE_DAYS,
    FPL_HISTORY_DELAY_SECONDS,
    FPL_RAW_DIR,
    TRANSFERMARKT_HEADERS,
)

logger = logging.getLogger(__name__)

_CACHE_FILE = FPL_RAW_DIR / "bootstrap_static.json"
_HISTORY_DIR = FPL_RAW_DIR / "element_summary"
_last_request_time: float | None = None
_MAX_ATTEMPTS = 5
_REQUEST_TIMEOUT_SECONDS = 10


def _throttle() -> None:
    global _last_request_time
    if _last_request_time is not None:
        wait = FPL_HISTORY_DELAY_SECONDS - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
    _last_request_time = time.monotonic()


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


def team_names(data: dict) -> list[str]:
    """The season's PL clubs, as FPL names them (e.g. 'Spurs', 'Man City')."""
    return [team["name"] for team in data.get("teams", [])]


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
                "fpl_id": element.get("id"),
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


def season_label(start_year: int) -> str:
    """2025 -> '2025/26', the format FPL uses for ``season_name``."""
    return f"{start_year}/{str(start_year + 1)[-2:]}"


def get_player_history(fpl_id: int, refresh: bool = False) -> list[dict]:
    """A player's ``history_past`` (one record per past FPL season)."""
    cache_file = _HISTORY_DIR / f"{fpl_id}.json"
    if not refresh and cache_file.exists():
        age_days = (time.time() - cache_file.stat().st_mtime) / 86400
        if age_days < FPL_HISTORY_CACHE_MAX_AGE_DAYS:
            return json.loads(cache_file.read_text())["history_past"]

    url = f"{FPL_BASE_URL}/element-summary/{fpl_id}/"
    history: list[dict] | None = None
    for attempt in range(_MAX_ATTEMPTS):
        _throttle()
        try:
            response = requests.get(url, headers=TRANSFERMARKT_HEADERS, timeout=_REQUEST_TIMEOUT_SECONDS)
        except (requests.Timeout, requests.ConnectionError) as exc:
            # The API occasionally hangs a single request; a short timeout + retry is cheap.
            logger.warning("FPL request failed (%s), retrying: %s", type(exc).__name__, url)
            time.sleep(2 * (attempt + 1))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            logger.warning("FPL returned %s for %s, backing off", response.status_code, url)
            time.sleep(5 * (attempt + 1))
            continue
        if response.status_code == 404:
            history = []
            break
        response.raise_for_status()
        history = response.json().get("history_past", [])
        break
    if history is None:
        raise RuntimeError(f"Gave up on {url} after {_MAX_ATTEMPTS} attempts")

    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"history_past": history}))
    return history


def aggregate_history(history_past: list[dict], seasons: list[int]) -> dict:
    """Sum a player's past-season stats over the given season start-years."""
    wanted = {season_label(season) for season in seasons}
    rows = [row for row in history_past if row.get("season_name") in wanted]
    return {
        "hist_minutes": sum(row.get("minutes") or 0 for row in rows),
        "hist_starts": sum(row.get("starts") or 0 for row in rows),
        "hist_goals": sum(row.get("goals_scored") or 0 for row in rows),
        "hist_assists": sum(row.get("assists") or 0 for row in rows),
        "hist_xg": sum(float(row.get("expected_goals") or 0) for row in rows),
        "hist_xa": sum(float(row.get("expected_assists") or 0) for row in rows),
        "hist_seasons": len(rows),
    }
