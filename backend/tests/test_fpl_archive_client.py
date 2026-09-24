import pandas as pd
import pytest

from backend.sources import fpl_archive_client as archive


def _csv(tmp_path, season="2024-25", **overrides):
    frame = pd.DataFrame(
        {
            "code": [223094, 1],
            "first_name": ["Erling", "Some"],
            "second_name": ["Haaland", "Body"],
            "minutes": [2736, 0],
            "starts": [31, 0],
            "goals_scored": [22, 0],
            "assists": [3, 0],
            "expected_goals": [21.9, 0.0],
            "expected_assists": [2.04, 0.0],
            "bps": [792, 0],
            "element_type": [4, 2],
            **overrides,
        }
    )
    path = tmp_path / f"players_raw_{season}.csv"
    frame.to_csv(path, index=False)
    return path


@pytest.mark.parametrize("year, folder", [(2022, "2022-23"), (2025, "2025-26"), (2099, "2099-00")])
def test_season_folder(year, folder):
    assert archive.season_folder(year) == folder


def test_get_season_players_reads_cache_without_network(monkeypatch, tmp_path):
    _csv(tmp_path)
    monkeypatch.setattr(archive, "FPL_ARCHIVE_RAW_DIR", tmp_path)
    monkeypatch.setattr(archive.requests, "get", lambda *a, **k: pytest.fail("should not fetch"))

    players = archive.get_season_players(2024)

    assert players[0] == {
        "code": 223094, "name": "erling haaland", "position": "F", "season": 2024,
        "minutes": 2736, "starts": 31, "goals": 22, "assists": 3, "xg": 21.9, "xa": 2.04,
        "bps": 792,
    }


def test_get_season_players_tolerates_old_seasons_missing_columns(monkeypatch, tmp_path):
    """Earlier seasons predate 'starts' and the expected-goals columns."""
    path = _csv(tmp_path, season="2018-19")
    frame = pd.read_csv(path).drop(columns=["starts", "expected_goals", "expected_assists"])
    frame.to_csv(path, index=False)
    monkeypatch.setattr(archive, "FPL_ARCHIVE_RAW_DIR", tmp_path)

    player = archive.get_season_players(2018)[0]

    assert player["starts"] == 0 and player["xg"] == 0.0
    assert player["minutes"] == 2736  # the columns that exist are still read


def test_get_season_players_downloads_and_caches(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(archive, "FPL_ARCHIVE_RAW_DIR", tmp_path / "cache")
    text = _csv(tmp_path).read_text()

    class Resp:
        def raise_for_status(self):
            pass

        @property
        def text(self):
            return text

    def fake_get(url, **kwargs):
        calls.append(url)
        return Resp()

    monkeypatch.setattr(archive.requests, "get", fake_get)

    archive.get_season_players(2024)
    archive.get_season_players(2024)

    assert len(calls) == 1
    assert calls[0].endswith("/2024-25/players_raw.csv")


def test_build_index_keys_by_code_and_name(monkeypatch, tmp_path):
    _csv(tmp_path, season="2023-24")
    _csv(tmp_path, season="2024-25")
    monkeypatch.setattr(archive, "FPL_ARCHIVE_RAW_DIR", tmp_path)

    index = archive.build_index([2023, 2024])

    assert len(index["by_code"][223094]) == 2
    assert len(index["by_name"]["erling haaland"]) == 2


def test_aggregate_sums_seasons():
    records = [
        {"minutes": 2736, "starts": 31, "goals": 22, "assists": 3, "xg": 21.9, "xa": 2.0, "bps": 792},
        {"minutes": 2553, "starts": 29, "goals": 27, "assists": 5, "xg": 29.6, "xa": 2.2, "bps": 810},
    ]

    assert archive.aggregate(records) == {
        "hist_minutes": 5289, "hist_starts": 60, "hist_goals": 49,
        "hist_assists": 8, "hist_xg": 51.5, "hist_seasons": 2,
        "hist_xa": pytest.approx(4.2), "hist_bps": 1602,
    }


def test_lookup_prefers_code_over_name():
    index = {"by_code": {7: [{"minutes": 1}]}, "by_name": {"someone else": [{"minutes": 2}]}}

    assert archive.lookup(index, 7, "Someone Else")[0]["minutes"] == 1


def test_lookup_falls_back_to_exact_name_only():
    index = {"by_code": {}, "by_name": {"dominic solanke": [{"minutes": 2000}]}}

    assert archive.lookup(index, None, "Dominic Solanke")[0]["minutes"] == 2000
    assert archive.lookup(index, 99, "Dominic Solanke")[0]["minutes"] == 2000  # unknown code
    # Without a position to check against, a near-miss must not match at all.
    assert archive.lookup(index, None, "Dominic Solank") is None


def test_lookup_accepts_name_variant_when_position_agrees():
    """Regression: 'Ben White' is 'Benjamin White' in the archive, so years of
    PL history were invisible and he looked like a newcomer."""
    index = {"by_code": {},
             "by_name": {"benjamin white": [{"code": 1, "minutes": 3000, "position": "D"}]}}

    assert archive.lookup(index, None, "Ben White", "D")[0]["minutes"] == 3000


def test_lookup_rejects_name_variant_when_position_disagrees():
    index = {"by_code": {},
             "by_name": {"benjamin white": [{"code": 1, "minutes": 3000, "position": "GK"}]}}

    assert archive.lookup(index, None, "Ben White", "D") is None


def test_lookup_merges_spellings_of_the_same_player():
    """'Alisson Becker' and 'Alisson Ramses Becker' are one player across seasons."""
    index = {"by_code": {}, "by_name": {
        "alisson becker": [{"code": 7, "minutes": 3420, "position": "GK"}],
        "alisson ramses becker": [{"code": 7, "minutes": 3060, "position": "GK"}],
    }}

    records = archive.lookup(index, None, "Alisson", "GK")

    assert sum(r["minutes"] for r in records) == 6480


def test_lookup_rejects_variants_belonging_to_different_players():
    index = {"by_code": {}, "by_name": {
        "danny ward": [{"code": 1, "minutes": 90, "position": "GK"}],
        "dan ward": [{"code": 2, "minutes": 90, "position": "GK"}],
    }}

    assert archive.lookup(index, None, "Ward", "GK") is None


@pytest.mark.parametrize(
    "name, other, expected",
    [
        ("ben white", "benjamin white", True),
        ("alisson", "alisson ramses becker", True),
        ("mo salah", "mohamed salah", True),   # 'mo' is a prefix of 'mohamed'
        ("ben white", "ben foster", False),    # different surname
        ("ben white", "adam white", False),    # first name is not a shortening
        # Nicknames are NOT handled: 'joseph' starts with 'jos', not 'joe'.
        # Covering them would need a nickname list and would risk false matches.
        ("joe gomez", "joseph gomez", False),
    ],
)
def test_is_name_variant(name, other, expected):
    assert archive._is_name_variant(name, other) is expected
