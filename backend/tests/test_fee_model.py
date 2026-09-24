import datetime as dt

import numpy as np
import pandas as pd
import pytest

from backend import fee_model


@pytest.fixture
def kaggle(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    n = 200
    values = rng.choice([3e6, 8e6, 20e6, 50e6], n)
    to_club = rng.choice([1, 2], n)                      # club 1 plays in the PL
    pd.DataFrame(
        {
            "player_id": np.arange(n),
            "transfer_date": rng.choice(["2021-07-01", "2023-01-15", "2025-08-01"], n),
            "from_club_id": 1,
            "to_club_id": to_club,
            # PL buyers pay 1.5x the market value, everyone else 1x.
            "transfer_fee": values * np.where(to_club == 1, 1.5, 1.0),
            "market_value_in_eur": values,
        }
    ).pipe(lambda d: pd.concat([d, pd.DataFrame({  # rows the filters must drop
        "player_id": [n, n + 1, n + 2], "transfer_date": ["2025-08-01", "2018-07-01", "2025-08-01"],
        "from_club_id": 1, "to_club_id": 2, "transfer_fee": [0, 9e6, 9e6],
        "market_value_in_eur": [9e6, 9e6, 500_000]})])).to_csv(tmp_path / "transfers.csv", index=False)
    pd.DataFrame(
        {
            "player_id": np.arange(n + 3),
            "date_of_birth": "2000-01-01",
            "position": rng.choice(["Attack", "Midfield", "Defender", "Goalkeeper"], n + 3),
        }
    ).to_csv(tmp_path / "players.csv", index=False)
    pd.DataFrame(
        {
            "current_club_id": [1, 1, 2],
            "player_club_domestic_competition_id": ["GB1", "GB1", "ES1"],
        }
    ).to_csv(tmp_path / "player_valuations.csv", index=False)
    monkeypatch.setattr(fee_model, "KAGGLE_RAW_DIR", tmp_path)
    return tmp_path


def test_without_the_files_there_is_no_fee_model(tmp_path, monkeypatch):
    monkeypatch.setattr(fee_model, "KAGGLE_RAW_DIR", tmp_path)
    assert fee_model.available() is False
    fee_model.main()  # logs and returns rather than failing a refresh


def test_training_frame_keeps_paid_recent_transfers_of_valued_players(kaggle):
    frame = fee_model.training_frame(today=dt.date(2026, 9, 22))

    assert len(frame) == 200            # the free, the pre-2019 and the EUR500k move are gone
    assert set(frame.from_pl) == {1.0}
    assert set(frame.to_pl) == {0.0, 1.0}


def test_estimate_learns_what_premier_league_buyers_pay(kaggle):
    frame = fee_model.training_frame(today=dt.date(2026, 9, 22))
    pipeline = fee_model.build_pipeline().fit(frame[fee_model.NUMERIC + fee_model.CATEGORICAL], frame.log_fee)
    calibration = fee_model.calibrate(frame, fee_model._out_of_fold(frame))
    players = pd.DataFrame({"market_value_eur": [20e6], "age": [25], "position": ["Centre-Forward"]})

    fees = fee_model.estimate(pipeline, calibration, players, today=dt.date(2026, 9, 22))

    assert fees.fee_pl_eur.iloc[0] / fees.fee_abroad_eur.iloc[0] == pytest.approx(1.5, rel=0.02)
    assert fees.fee_pl_low_eur.iloc[0] <= fees.fee_pl_eur.iloc[0] <= fees.fee_pl_high_eur.iloc[0]
