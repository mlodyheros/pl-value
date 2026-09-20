"""Scrapes current PL squads from Transfermarkt: position, age, nationality
and current market value, one request per club.

Transfermarkt has no official API and its `saison_id` filters on squad/value
pages don't actually change the market value shown (verified by hand) - only
squad *membership* is historical, values and ages are always "as of today".
So this scraper only ever pulls the *current* squad snapshot, which is the
right match for "current market value" as the prediction target.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import time

import requests
from bs4 import BeautifulSoup

from src.config import (
    TRANSFERMARKT_BASE_URL,
    TRANSFERMARKT_CLUB_ID_CACHE,
    TRANSFERMARKT_DELAY_SECONDS,
    TRANSFERMARKT_HEADERS,
    TRANSFERMARKT_RAW_DIR,
)

logger = logging.getLogger(__name__)

_last_request_time: float | None = None


def _throttle() -> None:
    global _last_request_time
    if _last_request_time is not None:
        elapsed = time.monotonic() - _last_request_time
        wait = TRANSFERMARKT_DELAY_SECONDS - elapsed
        if wait > 0:
            time.sleep(wait)
    _last_request_time = time.monotonic()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _get_html(url: str, cache_name: str, params: dict | None = None) -> str:
    TRANSFERMARKT_RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = TRANSFERMARKT_RAW_DIR / f"{cache_name}.html"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    _throttle()
    response = requests.get(
        url, headers=TRANSFERMARKT_HEADERS, params=params, timeout=15
    )
    response.raise_for_status()
    cache_file.write_text(response.text, encoding="utf-8")
    return response.text


def _load_club_id_cache() -> dict:
    if TRANSFERMARKT_CLUB_ID_CACHE.exists():
        return json.loads(TRANSFERMARKT_CLUB_ID_CACHE.read_text())
    return {}


def _save_club_id_cache(cache: dict) -> None:
    TRANSFERMARKT_CLUB_ID_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TRANSFERMARKT_CLUB_ID_CACHE.write_text(json.dumps(cache, indent=2))


def _search_query_candidates(club_name: str) -> list[str]:
    """Query variants to try, most to least specific.

    Transfermarkt's search ranking is surprisingly fragile: a trailing
    "FC"/"AFC" (as football-data.org names always have) can knock the real
    club out of the results entirely, and "&" breaks matching too. So we
    fall back progressively rather than trusting the first query.
    """
    stripped = _strip_club_suffix(club_name)
    queries = [stripped]
    if "&" in stripped:
        queries.append(stripped.replace("&", "and"))
    first_word = stripped.split()[0]
    if first_word not in queries:
        queries.append(first_word)
    return queries


def _find_club_candidates(html: str) -> list[tuple[str, str, str]]:
    """Parse the 'Clubs' results box into (name, slug, id) tuples."""
    soup = BeautifulSoup(html, "html.parser")
    for box in soup.find_all("div", class_="box"):
        heading = box.find("h2")
        if not heading or "Club" not in heading.get_text():
            continue
        table = box.find("table")
        if table is None:
            return []
        candidates = []
        for row in table.find("tbody").find_all("tr"):
            link_cell = row.find("td", class_="hauptlink")
            link = link_cell.find("a") if link_cell else None
            if link is None:
                continue
            match = re.match(r"/([\w-]+)/startseite/verein/(\d+)", link.get("href", ""))
            if match:
                candidate = (link.get_text(strip=True), match.group(1), match.group(2))
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates
    return []


def _strip_club_suffix(name: str) -> str:
    return re.sub(r"\s+(FC|AFC)$", "", name, flags=re.IGNORECASE).strip()


def _pick_best_candidate(
    club_name: str, candidates: list[tuple[str, str, str]]
) -> tuple[str, str, str]:
    """Choose the search result that best matches a football-data.org club name.

    Names are compared with the FC/AFC suffix stripped: otherwise "Crystal
    Palace FC" exactly matches an obscure lookalike club further down the
    results instead of the real "Crystal Palace" that Transfermarkt ranks first.
    Results are already ranked by Transfermarkt, so ties go to the first hit.
    """
    target = _strip_club_suffix(club_name).lower()
    for candidate in candidates:
        if _strip_club_suffix(candidate[0]).lower() == target:
            return candidate

    names = [c[0] for c in candidates]
    close = difflib.get_close_matches(club_name, names, n=1, cutoff=0.4)
    return next((c for c in candidates if c[0] == close[0]), candidates[0]) if close else candidates[0]


def resolve_club_id(club_name: str) -> dict | None:
    """Look up a club's Transfermarkt slug + numeric id via quick search."""
    cache = _load_club_id_cache()
    if club_name in cache:
        return cache[club_name]

    candidates: list[tuple[str, str, str]] = []
    for query in _search_query_candidates(club_name):
        html = _get_html(
            f"{TRANSFERMARKT_BASE_URL}/schnellsuche/ergebnis/schnellsuche",
            cache_name=f"search_{_slugify(query)}",
            params={"query": query},
        )
        candidates = _find_club_candidates(html)
        if candidates:
            break

    if not candidates:
        logger.warning("Could not resolve Transfermarkt club id for %r", club_name)
        return None

    best = _pick_best_candidate(club_name, candidates)

    entry = {"slug": best[1], "id": best[2]}
    cache[club_name] = entry
    _save_club_id_cache(cache)
    return entry


def parse_market_value(text: str) -> float | None:
    """'€45.00m' -> 45_000_000.0, '€850k' -> 850_000.0, '-' -> None."""
    text = text.strip().replace("€", "").replace(",", ".")
    if not text or text == "-":
        return None
    multiplier = 1.0
    if text.endswith("m"):
        multiplier = 1_000_000.0
        text = text[:-1]
    elif text.endswith("k"):
        multiplier = 1_000.0
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def fetch_squad(club_name: str) -> list[dict]:
    """Current squad for one club: name, position, age, nationality, market value."""
    club = resolve_club_id(club_name)
    if club is None:
        return []

    html = _get_html(
        f"{TRANSFERMARKT_BASE_URL}/{club['slug']}/kader/verein/{club['id']}",
        cache_name=f"squad_{club['id']}",
    )
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="items")
    if table is None:
        logger.warning("No squad table found for %r", club_name)
        return []

    players = []
    for row in table.find("tbody").find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 6:
            continue

        inline_rows = cells[1].find("table", class_="inline-table").find_all("tr")
        name_link = inline_rows[0].find("td", class_="hauptlink")
        if name_link is None:
            continue
        name = name_link.get_text(strip=True)
        position = inline_rows[1].get_text(strip=True) if len(inline_rows) > 1 else None

        age_text = cells[2].get_text(strip=True)
        age = int(age_text) if age_text.isdigit() else None

        flags = cells[3].find_all("img")
        nationality = flags[0].get("title") if flags else None

        market_value = parse_market_value(cells[5].get_text(strip=True))

        players.append(
            {
                "name": name,
                "position": position,
                "age": age,
                "nationality": nationality,
                "club": club_name,
                "market_value_eur": market_value,
            }
        )

    return players


def fetch_league_squads(club_names: list[str]) -> list[dict]:
    """Current squads (with market values) for every given club."""
    players = []
    for club_name in club_names:
        squad = fetch_squad(club_name)
        logger.info("Fetched %d players for %s", len(squad), club_name)
        players.extend(squad)
    return players
