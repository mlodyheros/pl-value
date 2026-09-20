import numpy as np
import pandas as pd

from src import predict
from src.model import train


def _df(n=60, seed=1):
    rng = np.random.default_rng(seed)
    goals = rng.integers(0, 20, n)
    return pd.DataFrame(
        {
            "age": rng.integers(18, 36, n),
            "goals": goals,
            "assists": rng.integers(0, 10, n),
            "penalties": rng.integers(0, 3, n),
            "appearances": rng.integers(0, 38, n),
            "position": rng.choice(["Centre-Forward", "Goalkeeper"], n),
            "club": rng.choice(["A FC", "B FC"], n),
            "market_value_eur": 1_000_000 + goals * 2_000_000,
        }
    )


def test_predict_for_row_matches_pipeline_on_dataframe():
    df = _df()
    pipeline, _ = train(df)

    row = df.iloc[0]
    from src.features import prepare_features

    expected = float(np.expm1(pipeline.predict(prepare_features(df.iloc[[0]]))[0]))
    assert predict.predict_for_row(pipeline, row) == expected


def test_predict_manual_prints_prediction(monkeypatch, capsys):
    pipeline, _ = train(_df())
    monkeypatch.setattr(predict, "load_pipeline", lambda: pipeline)

    predict.predict_manual(24, "Centre-Forward", "A FC", 20, 8, 2, 34)

    assert capsys.readouterr().out.startswith("Predicted value: €")


def test_predict_player_reports_no_match(monkeypatch, tmp_path, capsys):
    csv = tmp_path / "players.csv"
    _df().assign(name="Someone").to_csv(csv, index=False)
    monkeypatch.setattr(predict, "PROCESSED_DATASET_PATH", csv)

    predict.predict_player("Nobody Real")

    assert "No player found" in capsys.readouterr().out
