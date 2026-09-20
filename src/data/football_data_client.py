"""Thin client for the football-data.org v4 API (Premier League only).

Caches every raw JSON response to disk so repeated pipeline runs don't
re-hit the API, and sleeps between calls to respect the free-tier rate
limit (10 requests/minute).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import requests

from src.config import (
    FOOTBALL_DATA_API_KEY,
    FOOTBALL_DATA_BASE_URL,
    FOOTBALL_DATA_RATE_LIMIT_SECONDS,
    FOOTBALL_DATA_RAW_DIR,
)

logger = logging.getLogger(__name__)

COMPETITION = "PL"
_last_request_time: float | None = None


def _throttle() -> None:
    global _last_request_time
    if _last_request_time is not None:
        elapsed = time.monotonic() - _last_request_time
        wait = FOOTBALL_DATA_RATE_LIMIT_SECONDS - elapsed
        if wait > 0:
            time.sleep(wait)
    _last_request_time = time.monotonic()


def _cache_path(name: str) -> Path:
    FOOTBALL_DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    return FOOTBALL_DATA_RAW_DIR / f"{name}.json"


def _get(path: str, cache_name: str, params: dict | None = None) -> dict | None:
    cache_file = _cache_path(cache_name)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    if not FOOTBALL_DATA_API_KEY:
        raise RuntimeError(
            "FOOTBALL_DATA_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    url = f"{FOOTBALL_DATA_BASE_URL}{path}"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}

    for attempt in range(3):
        _throttle()
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if response.status_code == 429:
            logger.warning("Rate limited on %s, backing off", url)
            time.sleep(FOOTBALL_DATA_RATE_LIMIT_SECONDS * (attempt + 2))
            continue
        if response.status_code == 403:
            logger.warning("403 Forbidden for %s (likely outside free-tier access)", url)
            return None
        response.raise_for_status()
        data = response.json()
        cache_file.write_text(json.dumps(data))
        return data

    logger.error("Giving up on %s after repeated rate limiting", url)
    return None


def get_teams(season: int) -> list[dict]:
    """List of PL clubs for a season."""
    data = _get(
        f"/competitions/{COMPETITION}/teams",
        cache_name=f"teams_{season}",
        params={"season": season},
    )
    return data.get("teams", []) if data else []


def get_scorers(season: int, limit: int = 500) -> list[dict]:
    """Everyone with a goal or assist that season: goals, assists, penalties, appearances.

    The default limit of 10 (and the 100 this used to request) silently truncates
    the list; 500 comfortably covers every scorer in a 20-club season.
    """
    data = _get(
        f"/competitions/{COMPETITION}/scorers",
        cache_name=f"scorers_{season}_limit{limit}",
        params={"season": season, "limit": limit},
    )
    return data.get("scorers", []) if data else []
