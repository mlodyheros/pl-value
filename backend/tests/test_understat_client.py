import json

import pytest

from backend.sources import understat_client as us


def _players():
    return [
        {"id": "8200", "player_name": "Bradley Barcola", "team_title": "Paris Saint Germain",
         "position": "F M S", "time": "2223", "games": "34", "goals": "14", "assists": "9",
         "xG": "11.2", "xA": "7.1", "xGChain": "25.5"},
        {"player_name": "Antonio Sivera", "position": "GK", "time": "3060", "games": "34",
         "goals": "0", "assists": "0", "xG": "0", "xA": "0"},
        {"player_name": "Sub Stitute", "position": "S", "time": None, "games": "2",
         "goals": None, "assists": None, "xG": "0", "xA": "0"},
    ]


@pytest.mark.parametrize(
    "code, expected",
    [("GK", "GK"), ("GK S", "GK"), ("D S", "D"), ("D M S", "D"), ("M S", "M"),
     ("F M S", "M"), ("F S", "F"), ("S", "F"), ("", "F")],
)
def test_position_group(code, expected):
    assert us.position_group(code) == expected


@pytest.mark.parametrize(
    "position, expected",
    [("Goalkeeper", "GK"), ("Centre-Back", "D"), ("Left-Back", "D"),
     ("Central Midfield", "M"), ("Attacking Midfield", "M"),
     ("Centre-Forward", "F"), ("Right Winger", "F")],
)
def test_transfermarkt_position_group(position, expected):
    assert us.transfermarkt_position_group(position) == expected


def test_position_groups_disagree_for_the_silva_sivera_case():
    """The real false positive this guard exists to stop."""
    assert us.transfermarkt_position_group("Centre-Back") != us.position_group("GK")


def test_season_minutes_uses_the_longest_season_played():
    # 34-game league -> an ever-present plays 3060 minutes, not the PL's 3420.
    assert us._season_minutes(_players()) == 3060
    assert us._season_minutes([]) == 90  # never zero: it is a divisor


def test_build_index_normalises_names_and_flattens(monkeypatch):
    monkeypatch.setattr(us, "get_league_players", lambda league, season: _players())

    index = us.build_index(leagues=["Ligue 1"], seasons=[2024])

    assert set(index) == {"bradley barcola", "antonio sivera", "sub stitute"}
    record = index["bradley barcola"][0]
    assert record == {
        "id": "8200", "league": "Ligue 1", "season": 2024, "team": "Paris Saint Germain",
        "position": "F M S", "minutes": 2223, "goals": 14, "assists": 9, "xgchain": 25.5,
        "season_minutes": 3060,
    }
    # Null stats must not break parsing.
    assert index["sub stitute"][0]["minutes"] == 0


def test_build_index_accumulates_across_leagues_and_seasons(monkeypatch):
    monkeypatch.setattr(us, "get_league_players", lambda league, season: _players()[:1])

    index = us.build_index(leagues=["Ligue 1", "Serie A"], seasons=[2023, 2024])

    assert len(index["bradley barcola"]) == 4


def test_aggregate_sums_minutes_and_available_minutes():
    records = [
        {"minutes": 1431, "goals": 5, "assists": 3, "season_minutes": 3060},
        {"minutes": 2223, "goals": 14, "assists": 9, "season_minutes": 3060},
    ]

    assert us.aggregate(records) == {
        "nonpl_minutes": 3654, "nonpl_goals": 19, "nonpl_assists": 12,
        "nonpl_seasons": 2, "nonpl_available_minutes": 6120,
    }


def test_get_league_players_sends_ajax_header_and_caches(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(us, "UNDERSTAT_RAW_DIR", tmp_path)
    monkeypatch.setattr(us, "UNDERSTAT_DELAY_SECONDS", 0)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"players": _players()}

    def fake_get(url, headers=None, **kwargs):
        calls.append((url, headers))
        return Resp()

    monkeypatch.setattr(us.requests, "get", fake_get)

    first = us.get_league_players("La liga", 2024)
    second = us.get_league_players("La liga", 2024)

    assert first == second
    assert len(calls) == 1  # second call served from disk
    # Without this header Understat answers 404.
    assert calls[0][1]["X-Requested-With"] == "XMLHttpRequest"
    assert json.loads((tmp_path / "La_liga_2024.json").read_text()) == _players()


@pytest.mark.parametrize(
    "name, expected",
    [("Nico O&#039;Reilly", "nico o'reilly"), ("Emile Smith-Rowe", "emile smith rowe"),
     ("Rayan Aït-Nouri", "rayan ait nouri"), ("  Jérémy   DOKU ", "jeremy doku")],
)
def test_name_key_unescapes_and_treats_hyphens_as_spaces(name, expected):
    assert us.name_key(name) == expected
