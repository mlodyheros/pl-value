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
