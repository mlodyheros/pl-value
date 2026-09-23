import datetime as dt

import pandas as pd
import pytest

from backend.sources import kaggle_appearances as ka


@pytest.fixture
def kaggle(tmp_path, monkeypatch):
    pd.DataFrame(
        {
            "competition_id": ["L1", "BE1", "GB1"],
            "total_clubs": [18, 16, 20],
        }
    ).to_csv(tmp_path / "competitions.csv", index=False)
    pd.DataFrame(
        {
            "player_id": [1, 3],
            "name": ["Jamie Gittens", "Belgian Regular"],
            "date_of_birth": ["2004-08-08", "2000-01-01"],
        }
    ).to_csv(tmp_path / "players.csv", index=False)
    pd.DataFrame(
        {
            "player_id": [1, 1, 1, 1, 3, 1],
            "competition_id": ["L1", "L1", "L1", "CL", "BE1", "L1"],
            "date": ["2024-09-01", "2025-02-01", "2025-09-01", "2025-10-01", "2025-09-01", "2019-09-01"],
            "minutes_played": [90, 60, 80, 90, 90, 90],
            "goals": [1, 0, 1, 1, 0, 0],
            "assists": [0, 1, 0, 0, 0, 0],
        }
    ).to_csv(tmp_path / "appearances.csv", index=False)
    monkeypatch.setattr(ka, "KAGGLE_RAW_DIR", tmp_path)
    return tmp_path


def test_build_index_without_the_files_is_empty_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ka, "KAGGLE_RAW_DIR", tmp_path)
    assert ka.available() is False
    assert ka.build_index([2024, 2025]) == {}


def test_build_index_sums_covered_leagues_by_season(kaggle):
    index = ka.build_index([2024, 2025], today=dt.date(2026, 9, 22))

    # Champions League, a 2019 match and the Belgian league are all left out.
    assert index["jamie gittens"][0]["records"] == [
        {"season": 2024, "minutes": 150, "goals": 1, "assists": 1, "season_minutes": 3060},
        {"season": 2025, "minutes": 80, "goals": 1, "assists": 0, "season_minutes": 3060},
    ]
    assert "belgian regular" not in index


def test_lookup_confirms_the_player_by_age(kaggle):
    index = ka.build_index([2024, 2025], today=dt.date(2026, 9, 22))

    assert ka.lookup(index, "Jamie Gittens", 22) is not None
    assert ka.lookup(index, "Jamie Gittens", 30) is None
    assert ka.lookup(index, "Nobody Known", 22) is None
