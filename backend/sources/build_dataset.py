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
from backend.sources import fpl_archive_client as archive
from backend.sources import fpl_client
from backend.sources import kaggle_appearances
from backend.sources import transfer_fees
from backend.sources import transfermarkt_scraper as tm
from backend.sources import understat_client as us
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
_EMPTY_NONPL = {
    "nonpl_minutes": 0,
    "nonpl_goals": 0,
    "nonpl_assists": 0,
    "nonpl_seasons": 0,
    "nonpl_available_minutes": 0,
}
# A full Premier League season on the pitch.
_PL_SEASON_MINUTES = 3420
_FPL_FUZZY_CUTOFF = 0.88
_UNDERSTAT_FUZZY_CUTOFF = 0.88


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


# Within one club a looser spelling match is safe; across the league it is not.
_FPL_TEAM_FUZZY_CUTOFF = 0.75


def _name_tokens(name: str) -> set[str]:
    """Tokens of a normalized name, hyphenated parts included ('bynoe-gittens')."""
    key = normalize_name(name)
    return set(key.replace("-", " ").split()) | set(key.split())


def _match_fpl_in_team(name: str, teammates: list[dict]) -> dict | None:
    """Last resort, within the player's own club only.

    The two sources spell a few players differently enough that no global rule
    is safe: 'Ben White' is 'Benjamin White', 'Yegor Yarmolyuk' is 'Yehor
    Yarmoliuk', 'Chema Andrés' is 'José María Andrés Baixauli', 'Dominic
    Solanke' is 'Dominic Solanke-Mitchell'. Missing them cost each player this
    season's minutes - and some their whole PL history - so they looked idle.
    Inside one squad of ~30, a surname that is someone's FPL short name, or a
    close spelling of a full name, identifies them - provided exactly one
    teammate fits. So does a single name that is a teammate's first name:
    Transfermarkt's 'Alisson' is FPL's 'Alisson Becker' ('A.Becker'), and missing
    him had the model valuing a keeper who played every minute as if he never
    played at all.
    """
    tokens = normalize_name(name).split()
    if len(tokens) == 1:
        by_first_name = [p for p in teammates if tokens[0] in _name_tokens(p["first_name"])]
        if len(by_first_name) == 1:
            return by_first_name[0]

    surname = tokens[-1] if tokens else ""
    by_short_name = [
        p for p in teammates
        if surname and (
            normalize_name(p["web_name"]) == surname
            or surname in _name_tokens(p["second_name"])
        )
    ]
    if len(by_short_name) == 1:
        return by_short_name[0]

    fulls = {normalize_name(f"{p['first_name']} {p['second_name']}"): p for p in teammates}
    close = difflib.get_close_matches(
        normalize_name(name), fulls.keys(), n=2, cutoff=_FPL_TEAM_FUZZY_CUTOFF
    )
    return fulls[close[0]] if len(close) == 1 else None


def _match_fpl(
    name: str, by_full: dict, by_web: dict, teammates: list[dict] | None = None
) -> dict | None:
    """Full name, short name (Transfermarkt's 'Gabriel'), unique name-token
    subset (Transfermarkt's 'David Raya' vs FPL's 'David Raya Martin'), fuzzy,
    and finally a looser match inside the player's own club."""
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
    if close:
        return by_full[close[0]]
    return _match_fpl_in_team(name, teammates) if teammates else None


def _match_understat(name: str, position: str, index: dict) -> list[dict] | None:
    """Find a player's non-PL record, refusing any match that isn't certain.

    An exact name match is trusted. Anything looser has to agree on position
    group as well: without that guard the fuzzy matcher pairs (real examples)
    centre-back "Antonio Silva" with goalkeeper "Antonio Sivera", and silently
    files a keeper's numbers under a defender.
    """
    key = normalize_name(name)
    if key in index:
        return index[key]

    candidate = None
    tokens = set(key.split())
    if len(tokens) >= 2:
        supersets = [k for k in index if tokens <= set(k.split())]
        if len(supersets) == 1:
            candidate = supersets[0]
    if candidate is None:
        close = difflib.get_close_matches(key, index.keys(), n=1, cutoff=_UNDERSTAT_FUZZY_CUTOFF)
        candidate = close[0] if close else None
    if candidate is None:
        return None

    wanted = us.transfermarkt_position_group(position)
    if us.position_group(index[candidate][0]["position"]) != wanted:
        logger.debug("Rejected Understat match %r -> %r (position mismatch)", name, candidate)
        return None
    return index[candidate]


def _nonpl_columns(player: dict, index: dict, kaggle: dict | None = None) -> dict:
    """Non-PL playing record, only for players with no PL history to speak of.

    Understat first. When it cannot find the player - it spells some names its
    own way - the same leagues from the Kaggle files, whose names come from
    Transfermarkt like ours.
    """
    records = _match_understat(player["name"], player.get("position", ""), index)
    if not records and kaggle:
        records = kaggle_appearances.lookup(kaggle, player["name"], player.get("age"))
    if not records:
        return {**_EMPTY_NONPL, "has_nonpl_record": 0, "nonpl_recent_minutes": 0,
                "nonpl_recent_available_minutes": _PL_SEASON_MINUTES}
    recent = _recent_columns(records, _PL_SEASON_MINUTES)
    return {
        **us.aggregate(records),
        "has_nonpl_record": 1,
        "nonpl_recent_minutes": recent["recent_minutes"],
        "nonpl_recent_available_minutes": recent["recent_available_minutes"],
    }


def _europe_columns(player: dict, kaggle: dict) -> dict:
    """Champions League minutes in the newest completed season."""
    return {
        "cl_minutes_last": kaggle_appearances.champions_league_minutes(
            kaggle, player["name"], player.get("age"), max(SEASONS)
        )
    }


def _fpl_columns(player: dict | None, gameweeks: int) -> dict:
    if player is None:
        return {
            **_EMPTY_FPL,
            "fpl_id": None,
            "fpl_code": None,
            "fpl_gameweeks": gameweeks,
            "has_fpl_record": 0,
        }
    values = {key: player[key] for key in _EMPTY_FPL}
    return {
        **values,
        "fpl_id": player.get("fpl_id"),
        # stable across seasons; joins to the season archive exactly
        "fpl_code": player.get("fpl_code"),
        "fpl_gameweeks": gameweeks,
        "has_fpl_record": 1,
    }


def _recent_columns(records: list[dict] | None, season_minutes: int) -> dict:
    """Minutes in the newest season we cover, and how many were available.

    Career totals average several seasons together, which describes a player
    who has just become a regular - or just stopped being one - badly. The most
    recent completed season is the sharper statement of where they stand now.
    """
    newest = max(SEASONS)
    for record in records or []:
        if record.get("season") == newest:
            return {
                "recent_minutes": record["minutes"],
                "recent_available_minutes": record.get("season_minutes", season_minutes),
            }
    return {"recent_minutes": 0, "recent_available_minutes": season_minutes}


def _index_arrivals(arrivals: list[dict]) -> dict:
    """This season's arrivals, keyed the way squad players can find them."""
    return {(a["club"], normalize_name(a["name"])): a for a in arrivals}


def _fee_columns(player: dict, index: dict, arrivals: dict | None = None) -> dict:
    """The most recent fee paid for this player.

    A fee paid for them this season comes first. The Kaggle file is a snapshot,
    so a player signed after it was taken is either missing from it or, worse,
    carries the fee from the move before: Elliot Anderson joined City for
    EUR135m while the model was still reading the EUR41m Forest paid in 2024,
    and Ayyoub Bouaddi's EUR95m was not there at all. A loan, a free move or a
    return from loan pays nothing new, so for those the last fee on file stands.
    """
    arrival = (arrivals or {}).get((player.get("club"), normalize_name(player["name"])))
    if arrival is not None and arrival["fee_kind"] == "fee":
        return {
            "transfer_fee_eur": arrival["fee_eur"],
            # The club's page gives the season, not the day.
            "transfer_fee_date": f"{arrival['season']}-07-01",
            "has_transfer_fee": 1,
        }
    match = transfer_fees.lookup(index, player["name"], player.get("age"))
    if match is None:
        return {"transfer_fee_eur": None, "transfer_fee_date": None, "has_transfer_fee": 0}
    return {
        "transfer_fee_eur": match["fee_eur"],
        "transfer_fee_date": match["fee_date"],
        "has_transfer_fee": 1,
    }


def _history_columns(name: str, position: str, player: dict | None, index: dict) -> dict:
    """Past PL seasons over ``SEASONS``.

    Joined on FPL's stable player code where we have one. Players missing from
    this season's FPL game have no code, so they fall back to an exact name
    match - which is how long-serving players like Dominic Solanke get their
    history back instead of looking like newcomers.
    """
    records = archive.lookup(
        index,
        player.get("fpl_code") if player else None,
        name,
        us.transfermarkt_position_group(position),
    )
    history = archive.aggregate(records) if records else _EMPTY_HIST
    return {
        **history,
        "has_hist_record": int(history["hist_seasons"] > 0),
        **_recent_columns(records, _PL_SEASON_MINUTES),
    }


def build_dataset(refresh_fpl: bool = False) -> pd.DataFrame:
    fpl_data = fpl_client.get_bootstrap_static(refresh=refresh_fpl)
    club_names = fpl_client.team_names(fpl_data)
    if not club_names:
        raise RuntimeError("No PL clubs returned by the FPL API")
    gameweeks = fpl_client.finished_gameweeks(fpl_data)
    logger.info("Found %d PL clubs; %d finished gameweeks", len(club_names), gameweeks)

    # Club by club, so each player carries the FPL name of their club: the
    # last-resort name match only looks among that club's FPL players.
    squads = [
        {**player, "fpl_team": club_name}
        for club_name in club_names
        for player in tm.fetch_league_squads([club_name])
    ]
    logger.info("Scraped %d players total from Transfermarkt", len(squads))
    # The season being played now: the one after the last completed.
    arrivals = _index_arrivals(tm.fetch_league_arrivals(club_names, max(SEASONS) + 1))
    logger.info("Transfermarkt: %d arrivals this season", len(arrivals))

    fpl_players = fpl_client.parse_players(fpl_data)
    fpl_by_full, fpl_by_web = _index_fpl_players(fpl_players)
    fpl_by_team: dict[str, list[dict]] = {}
    for fpl_player in fpl_players:
        fpl_by_team.setdefault(fpl_player.get("fpl_team"), []).append(fpl_player)
    pl_history = archive.build_index(SEASONS)
    understat = us.build_index(seasons=SEASONS)
    fees = transfer_fees.build_index()
    kaggle_leagues = kaggle_appearances.build_index(SEASONS)
    logger.info("Understat: indexed %d players outside the PL", len(understat))

    rows = []
    fpl_unmatched = []
    for player in squads:
        fpl_player = _match_fpl(
            player["name"], fpl_by_full, fpl_by_web, fpl_by_team.get(player.get("fpl_team"))
        )
        if fpl_player is None:
            fpl_unmatched.append(player["name"])
        rows.append(
            {
                **player,
                **_fpl_columns(fpl_player, gameweeks),
                **_history_columns(player["name"], player.get("position", ""), fpl_player, pl_history),
                **_nonpl_columns(player, understat, kaggle_leagues),
                **_europe_columns(player, kaggle_leagues),
                **_fee_columns(player, fees, arrivals),
            }
        )
    if fpl_unmatched:
        logger.info(
            "%d players had no FPL record (FPL stats default to 0), e.g. %s",
            len(fpl_unmatched),
            fpl_unmatched[:10],
        )

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["market_value_eur", "age", "position"])
    # How old each fee is on the day of this snapshot, like every other column.
    fee_dates = pd.to_datetime(df["transfer_fee_date"], errors="coerce")
    df["transfer_fee_years"] = ((pd.Timestamp.today().normalize() - fee_dates).dt.days / 365.25).round(2)
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
