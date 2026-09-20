import json
import os
import time

from src.data import fpl_client


def _payload():
    return {
        "events": [{"finished": True}, {"finished": True}, {"finished": False}],
        "teams": [{"id": 15, "name": "Man City"}],
        "elements": [
            {
                "id": 411,
                "first_name": "Erling",
                "second_name": "Haaland",
                "web_name": "Haaland",
                "team": 15,
                "minutes": 180,
                "starts": 2,
                "expected_goals": "1.50",
                "expected_assists": "0.25",
                "defensive_contribution": 1,
                "now_cost": 156,
            },
            {"first_name": "New", "second_name": "Signing", "web_name": "Signing", "team": 99,
             "minutes": None, "starts": None, "expected_goals": None, "expected_assists": None,
             "defensive_contribution": None, "now_cost": None},
        ],
    }


def test_parse_players_flattens_and_converts_types():
    players = fpl_client.parse_players(_payload())

    assert players[0] == {
        "fpl_id": 411,
        "first_name": "Erling",
        "second_name": "Haaland",
        "web_name": "Haaland",
        "fpl_team": "Man City",
        "fpl_minutes": 180,
        "fpl_starts": 2,
        "fpl_xg": 1.5,
        "fpl_xa": 0.25,
        "fpl_defensive_contribution": 1,
        "fpl_price": 15.6,
        "fpl_gameweeks": 2,
    }
    # Null stats and unknown teams don't break parsing.
    assert players[1]["fpl_minutes"] == 0
    assert players[1]["fpl_xg"] == 0.0
    assert players[1]["fpl_team"] is None


def test_finished_gameweeks_counts_only_finished():
    assert fpl_client.finished_gameweeks(_payload()) == 2
    assert fpl_client.finished_gameweeks({}) == 0


class _Response:
    def raise_for_status(self):
        pass

    def json(self):
        return _payload()


def _patch_cache(monkeypatch, tmp_path, calls):
    monkeypatch.setattr(fpl_client, "_CACHE_FILE", tmp_path / "fpl" / "bootstrap_static.json")
    monkeypatch.setattr(fpl_client, "FPL_RAW_DIR", tmp_path / "fpl")

    def fake_get(url, **kwargs):
        calls.append(url)
        return _Response()

    monkeypatch.setattr(fpl_client.requests, "get", fake_get)


def test_get_bootstrap_static_fetches_then_uses_fresh_cache(monkeypatch, tmp_path):
    calls = []
    _patch_cache(monkeypatch, tmp_path, calls)

    assert fpl_client.get_bootstrap_static() == _payload()
    assert fpl_client.get_bootstrap_static() == _payload()

    assert len(calls) == 1
    assert calls[0].endswith("/bootstrap-static/")


def test_get_bootstrap_static_refetches_when_stale_or_forced(monkeypatch, tmp_path):
    calls = []
    _patch_cache(monkeypatch, tmp_path, calls)
    fpl_client.get_bootstrap_static()

    stale = time.time() - (fpl_client.FPL_CACHE_MAX_AGE_HOURS + 1) * 3600
    os.utime(fpl_client._CACHE_FILE, (stale, stale))
    fpl_client.get_bootstrap_static()
    assert len(calls) == 2

    fpl_client.get_bootstrap_static(refresh=True)
    assert len(calls) == 3
    assert json.loads(fpl_client._CACHE_FILE.read_text()) == _payload()


def test_season_label_uses_fpl_format():
    assert fpl_client.season_label(2025) == "2025/26"
    assert fpl_client.season_label(2099) == "2099/00"


def test_aggregate_history_sums_only_requested_seasons():
    history = [
        {"season_name": "2022/23", "minutes": 2767, "starts": 33, "goals_scored": 36,
         "assists": 8, "expected_goals": "28.54", "expected_assists": "3.11"},
        {"season_name": "2023/24", "minutes": 2553, "starts": 29, "goals_scored": 27,
         "assists": 5, "expected_goals": "29.57", "expected_assists": "2.18"},
        {"season_name": "2024/25", "minutes": None, "starts": None, "goals_scored": None,
         "assists": None, "expected_goals": None, "expected_assists": None},
    ]

    out = fpl_client.aggregate_history(history, [2023, 2024])

    assert out["hist_minutes"] == 2553
    assert out["hist_starts"] == 29
    assert out["hist_goals"] == 27
    assert out["hist_assists"] == 5
    assert out["hist_xg"] == 29.57
    assert out["hist_xa"] == 2.18
    # A listed season with no minutes still counts as a season on the books.
    assert out["hist_seasons"] == 2


def test_aggregate_history_empty_when_no_matching_seasons():
    out = fpl_client.aggregate_history([{"season_name": "2019/20", "minutes": 900}], [2025])

    assert out["hist_seasons"] == 0
    assert out["hist_minutes"] == 0


def test_get_player_history_fetches_caches_and_handles_404(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fpl_client, "_HISTORY_DIR", tmp_path / "element_summary")
    monkeypatch.setattr(fpl_client, "FPL_HISTORY_DELAY_SECONDS", 0)

    class Resp:
        def __init__(self, status, body=None):
            self.status_code, self._body = status, body or {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/999/"):
            return Resp(404)
        return Resp(200, {"history_past": [{"season_name": "2025/26", "minutes": 90}]})

    monkeypatch.setattr(fpl_client.requests, "get", fake_get)

    assert fpl_client.get_player_history(411)[0]["minutes"] == 90
    assert fpl_client.get_player_history(411)[0]["minutes"] == 90  # cached
    assert fpl_client.get_player_history(999) == []  # 404 -> empty, and cached
    assert fpl_client.get_player_history(999) == []
    assert len(calls) == 2


def test_get_player_history_retries_after_rate_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(fpl_client, "_HISTORY_DIR", tmp_path / "element_summary")
    monkeypatch.setattr(fpl_client, "FPL_HISTORY_DELAY_SECONDS", 0)
    monkeypatch.setattr(fpl_client.time, "sleep", lambda s: None)
    statuses = iter([429, 200])

    class Resp:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            pass

        def json(self):
            return {"history_past": [{"season_name": "2025/26"}]}

    monkeypatch.setattr(fpl_client.requests, "get", lambda url, **kw: Resp(next(statuses)))

    assert fpl_client.get_player_history(1) == [{"season_name": "2025/26"}]


def test_get_player_history_retries_timeouts_and_server_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(fpl_client, "_HISTORY_DIR", tmp_path / "element_summary")
    monkeypatch.setattr(fpl_client, "FPL_HISTORY_DELAY_SECONDS", 0)
    monkeypatch.setattr(fpl_client.time, "sleep", lambda s: None)

    class Resp:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            pass

        def json(self):
            return {"history_past": [{"season_name": "2025/26"}]}

    outcomes = iter([fpl_client.requests.ConnectTimeout(), fpl_client.requests.ConnectionError(), Resp(503), Resp(200)])

    def fake_get(url, **kwargs):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(fpl_client.requests, "get", fake_get)

    assert fpl_client.get_player_history(7) == [{"season_name": "2025/26"}]


def test_get_player_history_gives_up_after_max_attempts(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setattr(fpl_client, "_HISTORY_DIR", tmp_path / "element_summary")
    monkeypatch.setattr(fpl_client, "FPL_HISTORY_DELAY_SECONDS", 0)
    monkeypatch.setattr(fpl_client.time, "sleep", lambda s: None)
    calls = []

    def always_timeout(url, **kwargs):
        calls.append(url)
        raise fpl_client.requests.ReadTimeout()

    monkeypatch.setattr(fpl_client.requests, "get", always_timeout)

    with pytest.raises(RuntimeError, match="Gave up"):
        fpl_client.get_player_history(7)
    assert len(calls) == fpl_client._MAX_ATTEMPTS
    # A failed fetch must not poison the cache with an empty history.
    assert not (tmp_path / "element_summary" / "7.json").exists()
