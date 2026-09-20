import pandas as pd
import pytest

from backend.sources import build_dataset as bd


def test_normalize_name_strips_accents_case_and_whitespace():
    assert bd.normalize_name("  Jérémy   DOKU ") == "jeremy doku"
    assert bd.normalize_name("Mateo Kovačić") == "mateo kovacic"


def test_build_dataset_uses_fpl_club_list(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(bd.fpl_client, "get_bootstrap_static",
                        lambda refresh=False: {"events": [], "teams": [{"name": "Spurs"}, {"name": "Man City"}]})
    monkeypatch.setattr(bd.fpl_client, "parse_players", lambda data: [])
    monkeypatch.setattr(bd.tm, "fetch_league_squads", lambda clubs: seen.extend(clubs) or [])
    monkeypatch.setattr(bd, "PROCESSED_DATASET_PATH", tmp_path / "players.csv")

    with pytest.raises(KeyError):  # empty squad list -> no columns to drop on
        bd.build_dataset()
    assert seen == ["Spurs", "Man City"]


def test_build_dataset_errors_without_clubs(monkeypatch):
    monkeypatch.setattr(bd.fpl_client, "get_bootstrap_static", lambda refresh=False: {"teams": []})

    with pytest.raises(RuntimeError, match="No PL clubs"):
        bd.build_dataset()


def _fpl(first, second, web, minutes=0):
    return {"first_name": first, "second_name": second, "web_name": web, "fpl_minutes": minutes,
            "fpl_starts": 0, "fpl_xg": 0.0, "fpl_xa": 0.0, "fpl_defensive_contribution": 0,
            "fpl_price": 5.0}


def test_match_fpl_full_web_subset_and_fuzzy():
    players = [
        _fpl("Gabriel", "Magalhães", "Gabriel"),
        _fpl("Gabriel", "Jesus", "Jesus"),
        _fpl("David", "Raya Martín", "Raya"),
        _fpl("Bruno", "Fernandes", "B.Fernandes"),
        _fpl("Yeremi", "Pino", "Pino"),
        _fpl("Bruno", "Borges Fernandes", "Bruno"),
    ]
    by_full, by_web = bd._index_fpl_players(players)

    assert bd._match_fpl("Jérémy Nobody", by_full, by_web) is None
    assert bd._match_fpl("Gabriel", by_full, by_web)["second_name"] == "Magalhães"  # short name
    assert bd._match_fpl("David Raya", by_full, by_web)["second_name"] == "Raya Martín"  # subset
    assert bd._match_fpl("Bruno Fernandes", by_full, by_web)["second_name"] == "Fernandes"  # exact
    assert bd._match_fpl("Yéremy Pino", by_full, by_web)["second_name"] == "Pino"  # fuzzy


def test_match_fpl_refuses_ambiguous_subset():
    players = [_fpl("Ben", "Davies Jr", "B.Davies"), _fpl("Ben", "Davies Sr", "Bd")]
    by_full, by_web = bd._index_fpl_players(players)

    assert bd._match_fpl("Ben Davies", by_full, by_web) is None


def test_index_fpl_players_keeps_player_with_minutes_on_duplicate_name():
    players = [_fpl("Same", "Name", "A", minutes=0), _fpl("Same", "Name", "B", minutes=90)]
    by_full, _ = bd._index_fpl_players(players)

    assert by_full["same name"]["fpl_minutes"] == 90


def test_index_fpl_players_skips_ambiguous_web_names():
    players = [_fpl("A", "One", "Silva"), _fpl("B", "Two", "Silva"), _fpl("C", "Three", "Unique")]
    _, by_web = bd._index_fpl_players(players)

    assert set(by_web) == {"unique"}


def test_build_dataset_joins_stats_and_flags_unmatched(monkeypatch, tmp_path):
    monkeypatch.setattr(
        bd.tm,
        "fetch_league_squads",
        lambda clubs: [
            {"name": "Erling Haaland", "position": "Centre-Forward", "age": 26, "nationality": "Norway",
             "club": "Manchester City FC", "market_value_eur": 220e6},
            {"name": "Ederson", "position": "Goalkeeper", "age": 32, "nationality": "Brazil",
             "club": "Manchester City FC", "market_value_eur": 30e6},
            {"name": "No Value", "position": "Goalkeeper", "age": 20, "nationality": "England",
             "club": "Manchester City FC", "market_value_eur": None},
        ],
    )
    monkeypatch.setattr(bd.fpl_client, "get_bootstrap_static", lambda refresh=False: {"events": [{"finished": True}] * 4, "teams": [{"name": "Man City"}]})
    monkeypatch.setattr(
        bd.fpl_client,
        "parse_players",
        lambda data: [
            {**_fpl("Erling", "Haaland", "Haaland", minutes=360), "fpl_id": 411, "fpl_starts": 4, "fpl_xg": 3.3}
        ],
    )
    history_calls = []

    def fake_history(fpl_id):
        history_calls.append(fpl_id)
        return [{"season_name": "2025/26", "minutes": 2953, "starts": 34, "goals_scored": 27,
                 "assists": 7, "expected_goals": "25.50", "expected_assists": "2.67"}]

    monkeypatch.setattr(bd.fpl_client, "get_player_history", fake_history)
    monkeypatch.setattr(bd, "SEASONS", [2025])
    monkeypatch.setattr(bd, "PROCESSED_DATASET_PATH", tmp_path / "out" / "players.csv")

    df = bd.build_dataset()

    # Players without a market value are dropped.
    assert list(df["name"]) == ["Erling Haaland", "Ederson"]
    assert list(df["has_fpl_record"]) == [1, 0]
    assert list(df["fpl_minutes"]) == [360, 0]
    assert list(df["fpl_gameweeks"]) == [4, 4]
    assert df.loc[0, "fpl_id"] == 411
    # Past-season history is joined for matched players only (no request for Ederson).
    assert history_calls == [411]
    assert list(df["has_hist_record"]) == [1, 0]
    assert list(df["hist_minutes"]) == [2953, 0]
    assert list(df["hist_goals"]) == [27, 0]
    assert df.loc[0, "hist_xg"] == 25.5
    assert list(df["hist_seasons"]) == [1, 0]
    assert pd.read_csv(tmp_path / "out" / "players.csv").shape[0] == 2
