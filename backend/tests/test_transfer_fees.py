import datetime as dt

import pandas as pd
import pytest

from backend.sources import transfer_fees


@pytest.fixture
def kaggle(tmp_path, monkeypatch):
    pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4],
            "name": ["Erling Haaland", "Ben Davies", "Ben Davies", "Long Retired"],
            "date_of_birth": ["2000-07-21", "1993-04-24", "2004-01-10", "1980-01-01"],
            "last_season": [2026, 2026, 2026, 2015],
        }
    ).to_csv(tmp_path / "players.csv", index=False)
    pd.DataFrame(
        {
            "player_id": [1, 1, 2, 3, 4, 1],
            "transfer_date": ["2022-07-01", "2024-07-01", "2021-01-01",
                              "2025-08-01", "2010-01-01", "2030-01-01"],
            "transfer_fee": [60_000_000, 0, 5_000_000, 1_000_000, 100, 200_000_000],
        }
    ).to_csv(tmp_path / "transfers.csv", index=False)
    monkeypatch.setattr(transfer_fees, "KAGGLE_RAW_DIR", tmp_path)
    return tmp_path


def test_available_reports_whether_the_optional_files_are_there(tmp_path, monkeypatch):
    monkeypatch.setattr(transfer_fees, "KAGGLE_RAW_DIR", tmp_path)
    assert transfer_fees.available() is False


def test_build_index_without_the_files_is_empty_not_an_error(tmp_path, monkeypatch):
    """A clone of this repo has no Kaggle download, and must still build."""
    monkeypatch.setattr(transfer_fees, "KAGGLE_RAW_DIR", tmp_path)

    assert transfer_fees.build_index() == {}


def test_build_index_takes_the_latest_paid_fee(kaggle):
    index = transfer_fees.build_index(today=dt.date(2026, 9, 20))

    haaland = index["erling haaland"][0]
    # 2024 transfer was free and 2030 has not happened; 2022 is the latest paid one.
    assert haaland["fee_eur"] == 60_000_000
    assert haaland["fee_date"] == "2022-07-01"


def test_build_index_drops_players_who_stopped_playing(kaggle):
    assert "long retired" not in transfer_fees.build_index(today=dt.date(2026, 9, 20))


def test_lookup_uses_age_to_separate_players_sharing_a_name(kaggle):
    index = transfer_fees.build_index(today=dt.date(2026, 9, 20))

    older = transfer_fees.lookup(index, "Ben Davies", age=33)
    younger = transfer_fees.lookup(index, "Ben Davies", age=22)

    assert older["fee_eur"] == 5_000_000
    assert younger["fee_eur"] == 1_000_000


def test_lookup_refuses_an_ambiguous_name_rather_than_guessing(kaggle):
    """Attaching another player's fee would be worse than admitting ignorance."""
    index = transfer_fees.build_index(today=dt.date(2026, 9, 20))

    assert transfer_fees.lookup(index, "Ben Davies", age=None) is None
    assert transfer_fees.lookup(index, "Ben Davies", age=50) is None


def test_lookup_returns_none_for_an_unknown_player(kaggle):
    index = transfer_fees.build_index(today=dt.date(2026, 9, 20))

    assert transfer_fees.lookup(index, "Nobody At All", age=25) is None
