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
    monkeypatch.setattr(bd.tm, "fetch_league_arrivals", lambda clubs, season: [])
    monkeypatch.setattr(bd.kaggle_appearances, "build_index", lambda seasons: {})
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
            {**_fpl("Erling", "Haaland", "Haaland", minutes=360), "fpl_id": 411,
             "fpl_code": 223094, "fpl_starts": 4, "fpl_xg": 3.3}
        ],
    )
    monkeypatch.setattr(
        bd.archive, "build_index",
        lambda seasons: {"by_code": {223094: [{"minutes": 2953, "starts": 34, "goals": 27,
                                               "assists": 7, "xg": 25.5, "xa": 2.67}]},
                         "by_name": {}},
    )
    monkeypatch.setattr(bd.tm, "fetch_league_arrivals", lambda clubs, season: [])
    monkeypatch.setattr(bd.kaggle_appearances, "build_index", lambda seasons: {})
    monkeypatch.setattr(bd, "SEASONS", [2025])
    monkeypatch.setattr(bd, "PROCESSED_DATASET_PATH", tmp_path / "out" / "players.csv")

    df = bd.build_dataset()

    # Players without a market value are dropped.
    assert list(df["name"]) == ["Erling Haaland", "Ederson"]
    assert list(df["has_fpl_record"]) == [1, 0]
    assert list(df["fpl_minutes"]) == [360, 0]
    assert list(df["fpl_gameweeks"]) == [4, 4]
    assert df.loc[0, "fpl_id"] == 411
    assert list(df["has_hist_record"]) == [1, 0]
    assert list(df["hist_minutes"]) == [2953, 0]
    assert list(df["hist_goals"]) == [27, 0]
    assert df.loc[0, "hist_xg"] == 25.5
    assert list(df["hist_seasons"]) == [1, 0]
    assert pd.read_csv(tmp_path / "out" / "players.csv").shape[0] == 2


def _us_index():
    return {
        "bradley barcola": [{"position": "F M S", "minutes": 2223, "goals": 14,
                             "assists": 9, "season_minutes": 3060}],
        "antonio sivera": [{"position": "GK", "minutes": 3060, "goals": 0,
                            "assists": 0, "season_minutes": 3060}],
        "joshua wilson-esbrand": [{"position": "D S", "minutes": 900, "goals": 0,
                                   "assists": 1, "season_minutes": 3060}],
    }


def test_match_understat_accepts_exact_name():
    assert bd._match_understat("Bradley Barcola", "Left Winger", _us_index())[0]["goals"] == 14


def test_match_understat_rejects_fuzzy_match_with_wrong_position():
    """Regression: 'Antonio Silva' (centre-back) fuzzy-matched goalkeeper
    'Antonio Sivera', filing a keeper's stats under a defender."""
    assert bd._match_understat("António Silva", "Centre-Back", _us_index()) is None


def test_match_understat_accepts_spelling_variant_when_position_agrees():
    match = bd._match_understat("Josh Wilson-Esbrand", "Left-Back", _us_index())
    assert match is not None and match[0]["assists"] == 1


def test_match_understat_returns_none_when_absent():
    assert bd._match_understat("Nobody At All", "Centre-Forward", _us_index()) is None


def test_nonpl_columns_flag_and_aggregate():
    player = {"name": "Bradley Barcola", "position": "Left Winger"}
    cols = bd._nonpl_columns(player, _us_index())
    assert cols["has_nonpl_record"] == 1
    assert cols["nonpl_minutes"] == 2223

    missing = bd._nonpl_columns({"name": "Nobody", "position": "Goalkeeper"}, _us_index())
    assert missing["has_nonpl_record"] == 0
    assert missing["nonpl_minutes"] == 0


def test_history_columns_joins_by_stable_code():
    index = {"by_code": {223094: [{"minutes": 2953, "starts": 34, "goals": 27,
                                   "assists": 7, "xg": 25.5, "xa": 2.67}]}, "by_name": {}}

    cols = bd._history_columns("Erling Haaland", "Centre-Forward", {"fpl_code": 223094}, index)

    assert cols["has_hist_record"] == 1
    assert cols["hist_minutes"] == 2953
    assert cols["hist_seasons"] == 1


def test_history_columns_falls_back_to_name_for_players_absent_from_fpl():
    """Regression: players missing from this season's FPL game have no code, so
    their years of PL history used to be invisible and they looked like newcomers."""
    index = {"by_code": {}, "by_name": {"dominic solanke": [
        {"minutes": 2000, "starts": 20, "goals": 12, "assists": 3, "xg": 10.0,
         "xa": 2.0, "position": "F"}]}}

    cols = bd._history_columns("Dominic Solanke", "Centre-Forward", None, index)

    assert cols["has_hist_record"] == 1
    assert cols["hist_goals"] == 12


def test_history_columns_empty_when_player_is_genuinely_new():
    cols = bd._history_columns("Brand New", "Centre-Back", None, {"by_code": {}, "by_name": {}})

    assert cols["has_hist_record"] == 0
    assert cols["hist_minutes"] == 0


def test_recent_columns_take_the_newest_season():
    records = [
        {"season": 2023, "minutes": 3000},
        {"season": 2025, "minutes": 900, "season_minutes": 3060},
        {"season": 2024, "minutes": 2000},
    ]

    assert bd._recent_columns(records, 3420) == {
        "recent_minutes": 900,
        "recent_available_minutes": 3060,
    }


def test_recent_columns_are_zero_when_the_newest_season_was_missed():
    """Not playing the latest season is information, not missing data."""
    assert bd._recent_columns([{"season": 2023, "minutes": 3000}], 3420) == {
        "recent_minutes": 0,
        "recent_available_minutes": 3420,
    }


def test_recent_columns_handle_no_record_at_all():
    assert bd._recent_columns(None, 3420)["recent_minutes"] == 0


def _kaggle_fee(name, age, fee, date):
    return {bd.normalize_name(name): [{"player_id": 1, "age": age, "fee_eur": fee, "fee_date": date}]}


def test_fee_columns_prefer_a_fee_paid_this_season():
    """The Kaggle file is a snapshot: a summer signing made after it still
    carries the fee from the move before."""
    player = {"name": "Elliot Anderson", "club": "Man City", "age": 23}
    arrivals = bd._index_arrivals([{"name": "Elliot Anderson", "club": "Man City", "season": 2026,
                                    "fee_kind": "fee", "fee_eur": 135e6}])

    assert bd._fee_columns(player, _kaggle_fee("Elliot Anderson", 23.8, 41.2e6, "2024-07-01"), arrivals) == {
        "transfer_fee_eur": 135e6, "transfer_fee_date": "2026-07-01", "has_transfer_fee": 1}


def test_fee_columns_keep_the_last_fee_after_a_move_that_paid_nothing():
    player = {"name": "Omar Marmoush", "club": "Spurs", "age": 27}
    kaggle = _kaggle_fee("Omar Marmoush", 27.5, 75e6, "2025-01-23")
    for kind in ("loan", "free", "loan_return", "unknown"):
        arrivals = bd._index_arrivals([{"name": "Omar Marmoush", "club": "Spurs", "season": 2026,
                                        "fee_kind": kind, "fee_eur": None}])
        assert bd._fee_columns(player, kaggle, arrivals)["transfer_fee_eur"] == 75e6


def test_fee_columns_ignore_an_arrival_at_a_different_club():
    player = {"name": "Omar Marmoush", "club": "Spurs", "age": 27}
    arrivals = bd._index_arrivals([{"name": "Omar Marmoush", "club": "Man City", "season": 2026,
                                    "fee_kind": "fee", "fee_eur": 1e6}])

    assert bd._fee_columns(player, {}, arrivals)["has_transfer_fee"] == 0


def test_nonpl_columns_fall_back_to_kaggle_when_understat_misses_the_name(monkeypatch):
    """Understat spells some names its own way; Transfermarkt's files do not."""
    monkeypatch.setattr(bd, "SEASONS", [2024, 2025])
    kaggle = {"jamie gittens": [{"age": 21.9, "records": [
        {"season": 2024, "minutes": 1700, "goals": 5, "assists": 3, "season_minutes": 3060},
        {"season": 2025, "minutes": 1670, "goals": 4, "assists": 2, "season_minutes": 3060},
    ]}]}
    player = {"name": "Jamie Gittens", "position": "Left Winger", "age": 22}

    columns = bd._nonpl_columns(player, {}, kaggle)

    assert columns["has_nonpl_record"] == 1
    assert columns["nonpl_minutes"] == 3370
    assert columns["nonpl_available_minutes"] == 6120
    assert columns["nonpl_recent_minutes"] == 1670


def test_nonpl_columns_prefer_understat_when_it_has_the_player(monkeypatch):
    monkeypatch.setattr(bd, "SEASONS", [2025])
    understat = {"bradley barcola": [{"position": "F M S", "minutes": 2223, "goals": 14,
                                      "assists": 9, "season_minutes": 3060, "season": 2025}]}
    kaggle = {"bradley barcola": [{"age": 24.0, "records": [
        {"season": 2025, "minutes": 1, "goals": 0, "assists": 0, "season_minutes": 3060}]}]}
    player = {"name": "Bradley Barcola", "position": "Left Winger", "age": 24}

    assert bd._nonpl_columns(player, understat, kaggle)["nonpl_minutes"] == 2223


def test_normalize_name_transliterates_letters_that_do_not_decompose():
    assert bd.normalize_name("Đorđe Petrović") == "djordje petrovic"
    assert bd.normalize_name("Martin Ødegaard") == "martin odegaard"
    assert bd.normalize_name("Łukasz Fabiański") == "lukasz fabianski"


def _teammate(first, second, web):
    return {**_fpl(first, second, web), "fpl_team": "Arsenal"}


def test_match_fpl_falls_back_to_a_teammate_whose_short_name_is_the_surname():
    team = [_teammate("Benjamin", "White", "White"), _teammate("William", "Saliba", "Saliba")]
    by_full, by_web = bd._index_fpl_players([])

    assert bd._match_fpl("Ben White", by_full, by_web, team)["first_name"] == "Benjamin"
    # FPL's hyphenated surname still counts as the player's surname.
    team.append(_teammate("Jamie", "Bynoe-Gittens", "Gittens"))
    assert bd._match_fpl("Jamie Gittens", by_full, by_web, team)["second_name"] == "Bynoe-Gittens"


def test_match_fpl_in_team_accepts_a_close_spelling():
    team = [_teammate("Yehor", "Yarmoliuk", "Yarmoliuk"), _teammate("Mikkel", "Damsgaard", "Damsgaard")]
    by_full, by_web = bd._index_fpl_players([])

    assert bd._match_fpl("Yegor Yarmolyuk", by_full, by_web, team)["first_name"] == "Yehor"


def test_match_fpl_in_team_refuses_when_two_teammates_fit():
    team = [_teammate("Adam", "Smith", "A.Smith"), _teammate("Brandon", "Smith", "B.Smith")]
    by_full, by_web = bd._index_fpl_players([])

    assert bd._match_fpl("Callum Smith", by_full, by_web, team) is None
    # ...and without a club to look in, nothing loose is tried at all.
    assert bd._match_fpl("Ben White", by_full, by_web, None) is None


def test_match_fpl_in_team_takes_a_single_name_as_a_first_name():
    """Transfermarkt's 'Alisson' is FPL's 'Alisson Becker', short name 'A.Becker'."""
    team = [_teammate("Alisson", "Becker", "A.Becker"), _teammate("Giorgi", "Mamardashvili", "Mamardashvili")]
    by_full, by_web = bd._index_fpl_players([])

    assert bd._match_fpl("Alisson", by_full, by_web, team)["second_name"] == "Becker"


def _us(pid, name, team, position="M S", minutes=1800, xgchain=9.0, season=2025):
    return {"id": pid, "league": "EPL", "season": season, "team": team, "position": position,
            "minutes": minutes, "goals": 0, "assists": 0, "xgchain": xgchain, "season_minutes": 3420}


def _quality_index(*records):
    index, by_id = {}, {}
    for name, record in records:
        index.setdefault(bd.us.name_key(name), []).append(record)
        by_id.setdefault(record["id"], []).append(record)
    return index, by_id


def test_quality_columns_match_by_name_and_gather_every_season_of_that_player():
    index, by_id = _quality_index(
        ("Amad Diallo Traore", _us("8127", "Amad Diallo Traore", "Manchester United", season=2024)),
        ("Amad Diallo Traore", _us("8127", "Amad Diallo Traore", "Manchester United", season=2025)),
        ("Amadou Diallo", _us("12200", "Amadou Diallo", "Newcastle United", minutes=1)),
    )
    player = {"name": "Amad Diallo", "position": "Right Winger", "fpl_team": "Man Utd"}

    assert bd._quality_columns(player, index, by_id) == {"us_minutes": 3600, "us_xgchain": 18.0}


def test_quality_columns_fall_back_to_the_players_own_club():
    """Understat's 'Mathis Cherki' is Transfermarkt's 'Rayan Cherki'."""
    index, by_id = _quality_index(
        ("Mathis Cherki", _us("1", "Mathis Cherki", "Manchester City")),
        ("Phil Foden", _us("2", "Phil Foden", "Manchester City")),
    )
    player = {"name": "Rayan Cherki", "position": "Attacking Midfield", "fpl_team": "Man City"}

    assert bd._quality_columns(player, index, by_id)["us_minutes"] == 1800


def test_quality_columns_refuse_a_name_two_players_share_when_the_club_cannot_tell():
    index, by_id = _quality_index(
        ("Danilo", _us("1", "Danilo", "Juventus", position="M S")),
        ("Danilo", _us("2", "Danilo", "Flamengo", position="M S")),
    )
    player = {"name": "Danilo", "position": "Central Midfield", "fpl_team": "Nott'm Forest"}

    assert bd._quality_columns(player, index, by_id) == {"us_minutes": 0, "us_xgchain": 0.0}


def test_quality_columns_settle_a_shared_name_within_the_club():
    """Several Understat players are just 'Gabriel'; only one plays for Arsenal."""
    index, by_id = _quality_index(
        ("Gabriel", _us("1", "Gabriel", "Arsenal", position="D S")),
        ("Gabriel", _us("2", "Gabriel", "Lecce", position="D S")),
    )
    player = {"name": "Gabriel", "position": "Centre-Back", "fpl_team": "Arsenal"}

    assert bd._quality_columns(player, index, by_id)["us_minutes"] == 1800
