import numpy as np
import pandas as pd
import pytest

from backend import confidence


def _df(n=200, seed=0):
    rng = np.random.default_rng(seed)
    goals = rng.integers(0, 20, n)
    return pd.DataFrame(
        {
            "age": rng.integers(18, 36, n),
            "position": rng.choice(["Centre-Forward", "Goalkeeper"], n),
            "club": rng.choice(["A FC", "B FC"], n),
            "has_hist_record": rng.integers(0, 2, n),
            "has_nonpl_record": rng.integers(0, 2, n),
            "hist_minutes": goals * 100,
            "hist_seasons": 1,
            "hist_goals": goals,
            "hist_assists": 0,
            "nonpl_minutes": 900,
            "nonpl_available_minutes": 3060,
            "nonpl_goals": 2,
            "nonpl_assists": 1,
            "fpl_minutes": 90,
            "fpl_starts": 1,
            "fpl_gameweeks": 4,
            "has_fpl_record": 1,
            "market_value_eur": 1_000_000 + goals * 2_000_000,
        }
    )


def test_coverage_tiers_prefer_pl_history():
    df = pd.DataFrame(
        {"has_hist_record": [1, 1, 0, 0], "has_nonpl_record": [1, 0, 1, 0]}
    )

    assert list(confidence.coverage_tiers(df)) == [
        confidence.PL_HISTORY,
        confidence.PL_HISTORY,
        confidence.NON_PL_HISTORY,
        confidence.NO_HISTORY,
    ]


def test_coverage_tiers_handles_missing_columns():
    assert list(confidence.coverage_tiers(pd.DataFrame(index=[0, 1]))) == [
        confidence.NO_HISTORY,
        confidence.NO_HISTORY,
    ]


def _calibration(low, high, tier=confidence.PL_HISTORY):
    return {
        "overall": {"n": 100, "levels": {"0.8": [low, high]}},
        tier: {"n": 100, "levels": {"0.8": [low, high]}},
    }


def test_interval_inverts_the_residual_direction():
    """residual = log(pred) - log(actual), so a positive residual means the
    model asked too much and the true value lies BELOW the prediction."""
    cal = _calibration(np.log(1.0), np.log(2.0))

    low, high = confidence.interval(100.0, confidence.PL_HISTORY, cal)

    assert low == pytest.approx(50.0)   # pred / 2
    assert high == pytest.approx(100.0)  # pred / 1


def test_interval_falls_back_to_overall_for_an_uncalibrated_tier():
    cal = _calibration(np.log(0.5), np.log(2.0))
    del cal[confidence.PL_HISTORY]

    assert confidence.interval(100.0, confidence.PL_HISTORY, cal) == pytest.approx((50.0, 200.0))


def test_spread_is_the_width_of_the_range():
    cal = _calibration(np.log(0.5), np.log(2.0))

    assert confidence.spread(confidence.PL_HISTORY, cal) == pytest.approx(4.0)


@pytest.mark.parametrize(
    "ratio, expected", [(2.0, "moderate"), (5.9, "moderate"), (6.1, "low"), (20.0, "low")]
)
def test_describe_bands(ratio, expected):
    cal = _calibration(0.0, np.log(ratio))

    described = confidence.describe(confidence.PL_HISTORY, cal)

    assert described.startswith(expected)
    assert confidence.TIER_LABELS[confidence.PL_HISTORY] in described


def test_describe_never_claims_high_confidence():
    """Even the best-evidenced tier spans >4x, so 'high' would mislead."""
    cal = _calibration(0.0, np.log(1.01))

    assert "high confidence" not in confidence.describe(confidence.PL_HISTORY, cal)


def test_calibrate_measures_every_populated_tier():
    cal = confidence.calibrate(_df(), n_splits=3)

    assert cal["overall"]["n"] == 200
    for tier in (confidence.PL_HISTORY, confidence.NON_PL_HISTORY, confidence.NO_HISTORY):
        if tier in cal:
            assert cal[tier]["n"] >= confidence.MIN_TIER_SAMPLES
            low, high = cal[tier]["levels"]["0.8"]
            assert low < high


def test_calibrate_skips_tiers_with_too_few_players():
    df = _df()
    # Leave a single non-PL-only player: far too few to quantile.
    df.loc[df.index[1:], "has_hist_record"] = 1
    df.loc[df.index[0], ["has_hist_record", "has_nonpl_record"]] = [0, 1]

    cal = confidence.calibrate(df, n_splits=3)

    assert confidence.NON_PL_HISTORY not in cal
    # ...and asking for it still yields a usable range, borrowed from overall.
    low, high = confidence.interval(100.0, confidence.NON_PL_HISTORY, cal)
    assert low < 100.0 < high or low < high


def test_calibrated_interval_contains_about_the_stated_share():
    """The 80% range has to actually contain ~80% of true values."""
    df = _df(n=300, seed=3)
    cal = confidence.calibrate(df, n_splits=5)

    from backend.features import split_features_target
    from backend.model import build_pipeline, fit_pipeline

    X, y = split_features_target(df)
    fitted = fit_pipeline(build_pipeline(), X, y)
    predicted = np.expm1(fitted.predict(X))
    tiers = confidence.coverage_tiers(df)

    inside = [
        confidence.interval(p, t, cal)[0] <= actual <= confidence.interval(p, t, cal)[1]
        for p, actual, t in zip(predicted, df.market_value_eur, tiers)
    ]

    assert 0.7 <= np.mean(inside) <= 0.95
