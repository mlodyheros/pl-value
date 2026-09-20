import numpy as np
import pandas as pd

from backend import predict
from backend.model import train


def _predicted_euros(out: str) -> float:
    """The prediction itself, ignoring the confidence range printed under it."""
    line = next(l for l in out.splitlines() if "Predicted value" in l)
    return float(line.split("€")[1].replace(",", "").strip())


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
        has_any_history=1,
        career_minutes_share=lambda d: d.goals / 20,
        career_gi_per90=lambda d: d.goals / 20,
        hist_minutes_share=lambda d: d.goals / 20,
        has_fpl_record=1,
        minutes_share=lambda d: d.goals / 20,
        starts_share=lambda d: d.goals / 20,
    )
    pipeline, _ = train(df)
    monkeypatch.setattr(predict, "load_pipeline", lambda: pipeline)

    def euros(**kwargs):
        predict.predict_manual(24, "Centre-Forward", "A FC", **kwargs)
        return _predicted_euros(capsys.readouterr().out)

    assert euros(career_minutes_share=0.95) > euros(career_minutes_share=0.05)


def test_predict_manual_playing_time_changes_prediction(monkeypatch, capsys):
    df = _df().assign(has_fpl_record=1, minutes_share=lambda d: d.goals / 20, starts_share=lambda d: d.goals / 20)
    pipeline, _ = train(df)
    monkeypatch.setattr(predict, "load_pipeline", lambda: pipeline)

    def run(**kwargs):
        predict.predict_manual(24, "Centre-Forward", "A FC", **kwargs)
        return _predicted_euros(capsys.readouterr().out)

    assert run(minutes_share=1.0, starts_share=1.0) > run(minutes_share=0.05, starts_share=0.0)


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


def test_format_confidence_without_calibration_says_so():
    lines = predict.format_confidence(_df().iloc[0], 1e6, None)

    assert len(lines) == 1 and "unknown" in lines[0]


def test_format_confidence_reports_tier_and_range():
    from backend import confidence

    df = _df().assign(has_hist_record=1, has_nonpl_record=0)
    cal = confidence.calibrate(df, n_splits=3)

    lines = predict.format_confidence(df.iloc[0], 20_000_000, cal)

    assert "Premier League history" in lines[0]
    assert "80% range" in lines[1]


def test_predict_player_prints_a_range(monkeypatch, tmp_path, capsys):
    from backend import confidence

    df = _df().assign(
        name="Someone", has_hist_record=1, has_nonpl_record=0,
        hist_seasons=2, hist_minutes=3000, hist_goals=5, hist_assists=2,
    )
    csv = tmp_path / "players.csv"
    df.to_csv(csv, index=False)
    monkeypatch.setattr(predict, "PROCESSED_DATASET_PATH", csv)
    monkeypatch.setattr(predict, "load_pipeline", lambda: train(df)[0])
    monkeypatch.setattr(predict, "load_calibration", lambda: confidence.calibrate(df, n_splits=3))

    predict.predict_player("Someone")

    out = capsys.readouterr().out
    assert "Confidence:" in out and "80% range:" in out
