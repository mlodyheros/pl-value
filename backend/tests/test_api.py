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
        "id", "name", "club", "position", "age",
        "marketValueEur", "predictedEur", "gapPct", "tier",
    }


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
