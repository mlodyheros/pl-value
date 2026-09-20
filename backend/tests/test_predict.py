import numpy as np
import pandas as pd

from backend import predict
from backend.model import train


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
    from backend.features import prepare_features

    expected = float(np.expm1(pipeline.predict(prepare_features(df.iloc[[0]]))[0]))
    assert predict.predict_for_row(pipeline, row) == expected


def test_predict_manual_prints_prediction(monkeypatch, capsys):
    pipeline, _ = train(_df())
    monkeypatch.setattr(predict, "load_pipeline", lambda: pipeline)

    predict.predict_manual(24, "Centre-Forward", "A FC", minutes_share=0.9)

    assert capsys.readouterr().out.startswith("Predicted value: €")


def test_predict_player_reports_no_match(monkeypatch, tmp_path, capsys):
    csv = tmp_path / "players.csv"
    _df().assign(name="Someone").to_csv(csv, index=False)
    monkeypatch.setattr(predict, "PROCESSED_DATASET_PATH", csv)

    predict.predict_player("Nobody Real")

    assert "No player found" in capsys.readouterr().out


def test_predict_manual_history_changes_prediction(monkeypatch, capsys):
    df = _df().assign(
        has_hist_record=1,
        hist_minutes_share=lambda d: d.goals / 20,
        has_fpl_record=1,
        minutes_share=lambda d: d.goals / 20,
        starts_share=lambda d: d.goals / 20,
    )
    pipeline, _ = train(df)
    monkeypatch.setattr(predict, "load_pipeline", lambda: pipeline)

    def euros(**kwargs):
        predict.predict_manual(24, "Centre-Forward", "A FC", **kwargs)
        return float(capsys.readouterr().out.split("€")[1].replace(",", ""))

    assert euros(hist_minutes_share=0.95) > euros(hist_minutes_share=0.05)


def test_predict_manual_playing_time_changes_prediction(monkeypatch, capsys):
    df = _df().assign(has_fpl_record=1, minutes_share=lambda d: d.goals / 20, starts_share=lambda d: d.goals / 20)
    pipeline, _ = train(df)
    monkeypatch.setattr(predict, "load_pipeline", lambda: pipeline)

    def run(**kwargs):
        predict.predict_manual(24, "Centre-Forward", "A FC", **kwargs)
        return capsys.readouterr().out

    starter = run(minutes_share=1.0, starts_share=1.0)
    benched = run(minutes_share=0.05, starts_share=0.0)

    def euros(out):
        return float(out.split("€")[1].replace(",", ""))

    assert euros(starter) > euros(benched)


def test_validate_categories_rejects_unknown_club_and_lists_known():
    import pytest

    pipeline, _ = train(_df())

    assert predict.known_categories(pipeline)["club"] == ["A FC", "B FC"]
    predict.validate_categories(pipeline, club="A FC")  # known: no error

    with pytest.raises(SystemExit) as excinfo:
        predict.validate_categories(pipeline, club="Manchester City FC")
    assert "Unknown club" in str(excinfo.value)
    assert "A FC" in str(excinfo.value)


def test_predict_manual_errors_on_unknown_club_instead_of_guessing(monkeypatch):
    import pytest

    pipeline, _ = train(_df())
    monkeypatch.setattr(predict, "load_pipeline", lambda: pipeline)

    with pytest.raises(SystemExit):
        predict.predict_manual(24, "Centre-Forward", "Nowhere FC")
