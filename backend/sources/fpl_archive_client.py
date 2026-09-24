"""Past-season Premier League stats from the vaastav/Fantasy-Premier-League archive.

The FPL API only serves the current season, so a player's history used to come
from ``element-summary/<id>`` - one request per player, ~540 of them per build.
This archive publishes the same numbers as one CSV per season, so the whole
history is four downloads instead.

It also fixes a gap the API can't: a player who isn't in *this* season's FPL
game (injured, unregistered, just left) has no id to look up, so their Premier
League history was invisible even when they had years of it.

Past seasons never change, so the cache never expires.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from backend.config import (
    FPL_ARCHIVE_BASE_URL,
    FPL_ARCHIVE_RAW_DIR,
    TRANSFERMARKT_HEADERS,
)
from backend.sources.names import normalize_name

logger = logging.getLogger(__name__)

# Column -> the value to use when a season's file predates that column
_STAT_COLUMNS = {
    "minutes": 0,
    "starts": 0,
    "goals_scored": 0,
    "assists": 0,
    "expected_goals": 0.0,
    "expected_assists": 0.0,
    # FPL's bonus points system: credit for everything a player does on the ball,
    # defensive work included - the one quality measure that covers every position.
    "bps": 0,
}

# FPL's element_type
_POSITION_GROUPS = {1: "GK", 2: "D", 3: "M", 4: "F"}


def season_folder(start_year: int) -> str:
    """2022 -> '2022-23', the folder layout the archive uses."""
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def get_season_players(start_year: int) -> list[dict]:
    """Every FPL player's totals for one completed season."""
    FPL_ARCHIVE_RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = FPL_ARCHIVE_RAW_DIR / f"players_raw_{season_folder(start_year)}.csv"
    if not cache_file.exists():
        url = f"{FPL_ARCHIVE_BASE_URL}/{season_folder(start_year)}/players_raw.csv"
        response = requests.get(url, headers=TRANSFERMARKT_HEADERS, timeout=60)
        response.raise_for_status()
        cache_file.write_text(response.text, encoding="utf-8")

    frame = pd.read_csv(cache_file)
    if "element_type" not in frame:
        frame["element_type"] = 4
    for column, default in _STAT_COLUMNS.items():
        if column not in frame:
            # Older seasons predate 'starts' and the expected-goals columns.
            frame[column] = default
    frame = frame.fillna({column: default for column, default in _STAT_COLUMNS.items()})

    return [
        {
            "code": int(row.code),
            "name": normalize_name(f"{row.first_name} {row.second_name}"),
            "position": _POSITION_GROUPS.get(int(row.element_type), "F"),
            "season": start_year,
            "minutes": int(row.minutes),
            "starts": int(row.starts),
            "goals": int(row.goals_scored),
            "assists": int(row.assists),
            "xg": float(row.expected_goals),
            "xa": float(row.expected_assists),
            "bps": int(row.bps),
        }
        for row in frame.itertuples()
    ]


def build_index(seasons: list[int]) -> dict[str, dict]:
    """Season records keyed by FPL's stable player ``code``, and by name.

    ``code`` is the same number across seasons and matches the current
    bootstrap, so it joins exactly. The name index is only a fallback for
    players who aren't in this season's game and therefore have no code to
    join on.
    """
    by_code: dict[int, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for season in seasons:
        records = get_season_players(season)
        for record in records:
            by_code.setdefault(record["code"], []).append(record)
            by_name.setdefault(record["name"], []).append(record)
        logger.info("FPL archive %s: %d players", season_folder(season), len(records))
    return {"by_code": by_code, "by_name": by_name}


def aggregate(records: list[dict]) -> dict:
    """Sum a player's seasons into the dataset's ``hist_*`` columns."""
    return {
        "hist_minutes": sum(r["minutes"] for r in records),
        "hist_starts": sum(r["starts"] for r in records),
        "hist_goals": sum(r["goals"] for r in records),
        "hist_assists": sum(r["assists"] for r in records),
        "hist_xg": sum(r["xg"] for r in records),
        "hist_xa": sum(r["xa"] for r in records),
        "hist_bps": sum(r.get("bps", 0) for r in records),
        "hist_seasons": len(records),
    }


def _is_name_variant(name: str, other: str) -> bool:
    """Whether two spellings plausibly denote the same person.

    Deliberately narrow, because a wrong hit files someone else's entire career
    under this player. Only two shapes count: one name's words being a subset of
    the other's ("Alisson" in "Alisson Becker"), and a shortened first name with
    the same surname ("Ben White" / "Benjamin White").
    """
    words, other_words = name.split(), other.split()
    if not words or not other_words:
        return False
    if set(words) <= set(other_words) or set(other_words) <= set(words):
        return True
    return words[-1] == other_words[-1] and (
        words[0].startswith(other_words[0]) or other_words[0].startswith(words[0])
    )


def lookup(
    index: dict, code: int | None, name: str, position_group: str | None = None
) -> list[dict] | None:
    """A player's past seasons: by stable code, else by name.

    The code join is exact and always preferred. Falling back to a name is only
    needed for players missing from this season's FPL game, and a loose name
    match there would file someone else's whole career under them - so anything
    short of an exact name also has to agree on position group ('Ben White' ->
    'Benjamin White', a defender in both; but never a keeper onto a defender).
    """
    if code is not None:
        records = index["by_code"].get(int(code))
        if records:
            return records

    key = normalize_name(name)
    by_name = index["by_name"]
    if key in by_name:
        return by_name[key]
    if position_group is None:
        return None

    variants = [other for other in by_name if _is_name_variant(key, other)]
    # One player can be spelled differently from season to season ("Alisson
    # Becker", "Alisson Ramses Becker"), so judge ambiguity by player, not spelling.
    codes = {record["code"] for other in variants for record in by_name[other]}
    if len(codes) != 1:
        if codes:
            logger.debug("Rejected archive match %r -> %s (ambiguous)", name, variants)
        return None

    records = [record for other in variants for record in by_name[other]]
    if records[0].get("position") != position_group:
        logger.debug("Rejected archive match %r -> %s (position mismatch)", name, variants)
        return None
    return records
