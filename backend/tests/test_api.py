import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import api


def _dataset(n=120, seed=0):
    rng = np.random.default_rng(seed)
    goals = rng.integers(0, 20, n)
    has_pl = rng.integers(0, 2, n)
    return pd.DataFrame(
        {
            "name": [f"Player {i}" for i in range(n)],
            "club": rng.choice(["Man City", "Everton"], n),
            "position": rng.choice(["Centre-Forward", "Goalkeeper"], n),
            "age": rng.integers(18, 36, n),
            "nationality": rng.choice(["England", "Spain"], n),
            "market_value_eur": 1_000_000 + goals * 4_000_000,
            "fpl_minutes": 90,
            "fpl_starts": 1,
            "fpl_gameweeks": 4,
            "has_fpl_record": 1,
            "hist_minutes": goals * 100,
            "hist_starts": goals,
            "hist_goals": goals,
            "hist_assists": 1,
            "hist_seasons": has_pl,
            "has_hist_record": has_pl,
            "nonpl_minutes": 900,
            "nonpl_goals": 2,
            "nonpl_assists": 1,
            "nonpl_seasons": 1,
            "nonpl_available_minutes": 3060,
            "has_nonpl_record": 1 - has_pl,
        }
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    csv = tmp_path / "players.csv"
    _dataset().to_csv(csv, index=False)
    monkeypatch.setattr(api, "PROCESSED_DATASET_PATH", csv)
    monkeypatch.setattr(api, "CALIBRATION_PATH", tmp_path / "missing.json")

    # Calibration lives on disk; write a real one so ranges are exercised.
    from backend import confidence
    from backend.features import add_derived_features
    import json

    calibration = confidence.calibrate(add_derived_features(_dataset()), n_splits=3)
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(calibration))
    monkeypatch.setattr(api, "CALIBRATION_PATH", path)
    # The fee model is a trained artifact; these tests should not depend on one.
    monkeypatch.setattr(api.fee_model, "load", lambda: None)

    api.get_state.cache_clear()
    yield TestClient(api.app)
    api.get_state.cache_clear()


def test_meta_reports_dataset_and_model(client):
    body = client.get("/api/meta").json()

    assert body["players"] == 120
    assert body["calibrated"] is True
    assert set(body["tiers"]) <= {"pl_history", "non_pl_history", "no_history"}
    assert -1 <= body["model"]["r2Log"] <= 1
    assert body["model"]["maeEur"] > 0


def test_list_players_is_small_enough_to_send_once(client):
    players = client.get("/api/players").json()

    assert len(players) == 120
    assert set(players[0]) == {
        "id", "name", "club", "clubCode", "position", "age", "nationality",
        "marketValueEur", "predictedEur", "gapPct", "tier",
    }
    # Without a code in the data, the first three letters of the club stand in.
    assert players[0]["clubCode"] == players[0]["club"][:3].upper()


def test_player_detail_carries_range_and_evidence(client):
    player = client.get("/api/players/0").json()

    assert player["name"] == "Player 0"
    assert player["range"]["lowEur"] < player["predictedEur"] < player["range"]["highEur"]
    assert isinstance(player["marketInRange"], bool)
    assert player["confidence"]["level"] == api.CONFIDENCE_LEVEL
    assert set(player["evidence"]) == {"thisSeason", "premierLeague", "otherLeagues"}


def test_market_in_range_agrees_with_the_range_it_reports(client):
    for player_id in (0, 5, 40):
        player = client.get(f"/api/players/{player_id}").json()
        low, high = player["range"]["lowEur"], player["range"]["highEur"]
        assert player["marketInRange"] == (low <= player["marketValueEur"] <= high)


def test_unknown_player_is_404(client):
    assert client.get("/api/players/99999").status_code == 404


def test_rankings_are_sorted_and_opposed(client):
    body = client.get("/api/rankings?limit=5&min_value_eur=0").json()

    under = [p["gapPct"] for p in body["underrated"]]
    over = [p["gapPct"] for p in body["overrated"]]
    assert under == sorted(under, reverse=True)
    assert over == sorted(over)
    assert under[0] > over[0]


def test_rankings_exclude_cheap_players(client):
    body = client.get("/api/rankings?min_value_eur=30000000").json()

    assert body["minValueEur"] == 30_000_000
    for group in ("underrated", "overrated"):
        assert all(p["marketValueEur"] >= 30_000_000 for p in body[group])


def test_predictions_are_out_of_fold_not_self_scored(client, tmp_path):
    """A model scoring players it trained on flatters itself, which is exactly
    the bias that would corrupt 'is this player overvalued?'."""
    from backend.features import add_derived_features, split_features_target
    from backend.model import build_pipeline, fit_pipeline

    df = add_derived_features(_dataset())
    X, y = split_features_target(df)
    in_sample = np.expm1(fit_pipeline(build_pipeline(), X, y).predict(X))
    served = np.array([p["predictedEur"] for p in client.get("/api/players").json()])

    assert not np.allclose(in_sample, served)


def test_missing_calibration_still_serves_players(tmp_path, monkeypatch):
    csv = tmp_path / "players.csv"
    _dataset().to_csv(csv, index=False)
    monkeypatch.setattr(api, "PROCESSED_DATASET_PATH", csv)
    monkeypatch.setattr(api, "CALIBRATION_PATH", tmp_path / "nope.json")
    api.get_state.cache_clear()

    player = TestClient(api.app).get("/api/players/0").json()

    assert player["range"] is None
    assert player["marketInRange"] is None
    assert player["confidence"]["summary"] is None
    api.get_state.cache_clear()


def test_missing_dataset_answers_with_the_fix_not_a_stack_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "PROCESSED_DATASET_PATH", tmp_path / "absent.csv")
    api.get_state.cache_clear()

    response = TestClient(api.app, raise_server_exceptions=False).get("/api/meta")

    assert response.status_code == 503
    body = response.json()
    assert "build_dataset" in body["fix"]
    assert "No dataset" in body["detail"]
    api.get_state.cache_clear()


def test_rebuilding_the_dataset_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    """The state used to be cached for the life of the process, so a rebuilt
    dataset stayed invisible until someone restarted the server."""
    import os

    csv = tmp_path / "players.csv"
    frame = _dataset()
    frame.to_csv(csv, index=False)
    monkeypatch.setattr(api, "PROCESSED_DATASET_PATH", csv)
    monkeypatch.setattr(api, "CALIBRATION_PATH", tmp_path / "none.json")
    api.get_state.cache_clear()

    client = TestClient(api.app)
    assert client.get("/api/meta").json()["players"] == 120

    frame.head(40).to_csv(csv, index=False)
    os.utime(csv, (0, 0))  # any change of mtime, not just a later one

    assert client.get("/api/meta").json()["players"] == 40
    api.get_state.cache_clear()


def test_player_detail_has_no_fee_estimate_without_the_fee_model(client):
    assert client.get("/api/players/0").json()["feeEstimate"] is None


def test_player_detail_carries_the_fee_estimate_when_the_model_exists(client, monkeypatch):
    from backend import fee_model

    frame = pd.DataFrame(
        {
            "log_value": np.log([5e6, 10e6, 20e6, 40e6] * 10),
            "age": [20, 24, 28, 32] * 10,
            "to_pl": [0, 1] * 20,
            "from_pl": 1.0,
            "year": 2024.5,
            "position": ["Attack", "Goalkeeper"] * 20,
        }
    )
    frame = fee_model._add_terms(frame)
    frame["log_fee"] = frame.log_value + 0.3 * frame.to_pl
    pipeline = fee_model.build_pipeline().fit(frame[fee_model.NUMERIC + fee_model.CATEGORICAL], frame.log_fee)
    calibration = {"level": 0.8, "low": -0.8, "high": 0.8, "n": len(frame)}
    monkeypatch.setattr(api.fee_model, "load", lambda: (pipeline, calibration))
    api.get_state.cache_clear()

    fee = client.get("/api/players/0").json()["feeEstimate"]

    assert fee["premierLeagueEur"] > fee["abroadEur"] > 0
    assert fee["lowMultiple"] < 1 < fee["highMultiple"]
    assert fee["transfers"] == 40
