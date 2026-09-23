import numpy as np
import pytest
import pandas as pd

from backend.features import (
    FEATURE_COLUMNS,
    add_derived_features,
    prepare_features,
    split_features_target,
    train_test_split_dataset,
)


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age": [20, 25, 30, 22],
            "goals": [1, 10, 3, 0],
            "assists": [2, 5, 1, 0],
            "penalties": [0, 2, 0, 0],
            "appearances": [15, 30, 25, 5],
            "position": ["Centre-Forward", "Centre-Forward", "Centre-Back", "Goalkeeper"],
            "club": ["A FC", "B FC", "A FC", "C FC"],
            "market_value_eur": [1_000_000, 50_000_000, 5_000_000, 200_000],
        }
    )


def test_split_features_target_log_transforms_value():
    X, y = split_features_target(_sample_df())

    assert list(X.columns) == FEATURE_COLUMNS
    assert np.allclose(y.values, np.log1p([1_000_000, 50_000_000, 5_000_000, 200_000]))


def test_train_test_split_dataset_shapes():
    df = _sample_df()
    X_train, X_test, y_train, y_test = train_test_split_dataset(
        df, test_size=0.5, random_state=0
    )

    assert len(X_train) + len(X_test) == len(df)
    assert len(y_train) + len(y_test) == len(df)


def test_add_derived_features_computes_age_squared_without_mutating_input():
    df = _sample_df()
    out = add_derived_features(df)

    assert "age_squared" not in df.columns
    assert list(out["age_squared"]) == [400, 625, 900, 484]


def test_prepare_features_returns_training_columns_in_order():
    assert list(prepare_features(_sample_df()).columns) == FEATURE_COLUMNS


def test_add_derived_features_fpl_shares():
    df = _sample_df().assign(
        fpl_minutes=[360, 0, 180, 90],
        fpl_starts=[4, 0, 2, 1],
        fpl_gameweeks=[4, 4, 4, 0],  # 0 finished gameweeks must not divide by zero
        has_fpl_record=[1, 1, 1, 0],
    )
    out = add_derived_features(df)

    assert list(out["minutes_share"]) == [1.0, 0.0, 0.5, 1.0]
    assert list(out["starts_share"]) == [1.0, 0.0, 0.5, 1.0]
    assert list(out["has_fpl_record"]) == [1, 1, 1, 0]


def test_add_derived_features_defaults_without_fpl_data():
    out = add_derived_features(_sample_df())

    assert (out["minutes_share"] == 0).all()
    assert (out["starts_share"] == 0).all()
    assert (out["has_fpl_record"] == 0).all()


def test_add_derived_features_keeps_supplied_shares():
    out = add_derived_features(_sample_df().assign(minutes_share=0.8, starts_share=0.5))

    assert (out["minutes_share"] == 0.8).all()
    assert (out["starts_share"] == 0.5).all()


def test_add_derived_features_hist_minutes_share():
    df = _sample_df().assign(
        hist_minutes=[3420, 6840, 0, 1710],
        hist_seasons=[1, 2, 0, 1],  # 0 seasons must not divide by zero
        has_hist_record=[1, 1, 0, 1],
    )
    out = add_derived_features(df)

    assert list(out["hist_minutes_share"]) == [1.0, 1.0, 0.0, 0.5]
    assert list(out["has_hist_record"]) == [1, 1, 0, 1]


def test_add_derived_features_defaults_without_history():
    out = add_derived_features(_sample_df())

    assert (out["hist_minutes_share"] == 0).all()
    assert (out["has_hist_record"] == 0).all()


def test_add_derived_features_keeps_supplied_hist_share():
    out = add_derived_features(_sample_df().assign(hist_minutes_share=0.7, has_hist_record=1))

    assert (out["hist_minutes_share"] == 0.7).all()


def test_add_derived_features_hist_gi_per90_is_a_rate_not_a_total():
    df = _sample_df().assign(
        hist_minutes=[3420, 1710, 0, 900],
        hist_goals=[38, 19, 5, 0],
        hist_assists=[0, 0, 0, 0],
        hist_seasons=[1, 1, 0, 1],
    )
    out = add_derived_features(df)

    # Same rate (1 per 90) despite very different totals - that is the point.
    assert out["hist_gi_per90"].iloc[0] == 1.0
    assert out["hist_gi_per90"].iloc[1] == 1.0
    # No minutes: a rate would be undefined, so it must not divide by zero.
    assert out["hist_gi_per90"].iloc[2] == 5 * 90
    assert out["hist_gi_per90"].iloc[3] == 0.0


def test_add_derived_features_defaults_gi_per90_without_history():
    assert (add_derived_features(_sample_df())["hist_gi_per90"] == 0).all()


def test_career_features_use_pl_history_when_present():
    df = _sample_df().assign(
        has_hist_record=1, hist_minutes=3420, hist_seasons=1, hist_goals=10, hist_assists=0,
        has_nonpl_record=1, nonpl_minutes=900, nonpl_available_minutes=3060,
        nonpl_goals=99, nonpl_assists=0,
    )
    out = add_derived_features(df)

    # PL history wins: the non-PL record is only ever a fallback.
    assert (out["career_minutes_share"] == 1.0).all()
    assert (out["career_gi_per90"] == 10 / 3420 * 90).all()
    assert (out["has_any_history"] == 1).all()


def test_career_features_fall_back_to_non_pl_record():
    df = _sample_df().assign(
        has_hist_record=0, hist_minutes=0, hist_seasons=0, hist_goals=0, hist_assists=0,
        has_nonpl_record=1, nonpl_minutes=1530, nonpl_available_minutes=3060,
        nonpl_goals=17, nonpl_assists=0,
    )
    out = add_derived_features(df)

    assert (out["career_minutes_share"] == 0.5).all()
    assert (out["career_gi_per90"] == 1.0).all()
    assert (out["has_any_history"] == 1).all()


def test_career_features_zero_for_players_with_no_history_anywhere():
    out = add_derived_features(_sample_df())

    assert (out["career_minutes_share"] == 0).all()
    assert (out["career_gi_per90"] == 0).all()
    assert (out["has_any_history"] == 0).all()


def test_recent_minutes_share_uses_the_newest_pl_season():
    df = _sample_df().assign(
        has_hist_record=1, has_nonpl_record=0,
        hist_minutes=0, hist_seasons=1, hist_goals=0, hist_assists=0,
        recent_minutes=[3420, 1710, 0, 342],
        recent_available_minutes=3420,
    )
    out = add_derived_features(df)

    assert list(out["recent_minutes_share"]) == [1.0, 0.5, 0.0, 0.1]


def test_recent_minutes_share_falls_back_to_the_non_pl_season():
    df = _sample_df().assign(
        has_hist_record=0, has_nonpl_record=1,
        hist_minutes=0, hist_seasons=0, hist_goals=0, hist_assists=0,
        recent_minutes=0, recent_available_minutes=3420,
        nonpl_recent_minutes=1530, nonpl_recent_available_minutes=3060,
        nonpl_minutes=1530, nonpl_available_minutes=3060, nonpl_goals=0, nonpl_assists=0,
    )
    out = add_derived_features(df)

    assert (out["recent_minutes_share"] == 0.5).all()


def test_recent_minutes_share_defaults_without_season_columns():
    assert (add_derived_features(_sample_df())["recent_minutes_share"] == 0).all()


def test_transfer_fee_feature_is_logged_and_flagged():
    df = _sample_df().assign(transfer_fee_eur=[60_000_000, None, 0, 1_000_000],
                             has_transfer_fee=[1, 0, 0, 1])
    out = add_derived_features(df)

    assert out["log_transfer_fee"].iloc[0] == pytest.approx(np.log1p(60_000_000))
    assert out["log_transfer_fee"].iloc[1] == 0.0  # missing means unknown, not zero-valued
    assert list(out["has_transfer_fee"]) == [1, 0, 0, 1]


def test_transfer_fee_defaults_when_the_optional_source_is_absent():
    out = add_derived_features(_sample_df())

    assert (out["log_transfer_fee"] == 0).all()
    assert (out["has_transfer_fee"] == 0).all()


def test_idle_flag_marks_players_under_one_match_of_minutes():
    df = _sample_df().assign(
        fpl_minutes=[0, 89, 90, 450], fpl_starts=0, fpl_gameweeks=4, has_fpl_record=1
    )
    out = add_derived_features(df)

    assert list(out["idle_this_season"]) == [1.0, 1.0, 0.0, 0.0]


def test_idle_products_lean_on_history_and_fee_when_not_playing():
    """A linear model cannot form a product of its own features, so these carry
    "when someone is not playing, weigh what they did before"."""
    df = _sample_df().assign(
        fpl_minutes=[0, 450, 0, 450], fpl_starts=0, fpl_gameweeks=4, has_fpl_record=1,
        has_hist_record=1, hist_minutes=3420, hist_seasons=1, hist_goals=0, hist_assists=0,
        recent_minutes=3420, recent_available_minutes=3420,
        transfer_fee_eur=50_000_000, has_transfer_fee=1,
    )
    out = add_derived_features(df)

    # Idle players carry their career share and fee; the others carry zero.
    assert out["idle_x_career"].iloc[0] == out["career_minutes_share"].iloc[0]
    assert out["idle_x_career"].iloc[1] == 0.0
    assert out["idle_x_fee"].iloc[0] == pytest.approx(np.log1p(50_000_000))
    assert out["idle_x_fee"].iloc[3] == 0.0


def test_idle_features_default_without_fpl_columns():
    out = add_derived_features(_sample_df())

    assert (out["idle_this_season"] == 1.0).all()  # no minutes recorded at all
    assert (out["idle_x_fee"] == 0).all()          # ...and no fee to lean on


def _played(position, career, recent, now, fee=0):
    return {"position": position, "age": 26, "career_minutes_share": career,
            "recent_minutes_share": recent, "minutes_share": now, "has_transfer_fee": fee,
            "career_gi_per90": 0.5}


def test_backup_keeper_marks_only_a_keeper_who_plays_nowhere_and_cost_nothing():
    df = add_derived_features(pd.DataFrame([
        _played("Goalkeeper", 0.0, 0.0, 0.0),            # third choice
        _played("Goalkeeper", 0.9, 0.95, 1.0),           # the starter
        _played("Goalkeeper", 0.0, 0.0, 0.0, fee=1),     # just bought: a signing, not a backup
        _played("Goalkeeper", 0.0, 0.3, 0.0),            # played last season
        _played("Centre-Back", 0.0, 0.0, 0.0),           # outfield: a prospect, not a backup
    ]))

    assert list(df["backup_keeper"]) == [1.0, 0.0, 0.0, 0.0, 0.0]


def test_gi_x_career_weighs_the_rate_by_how_much_was_played():
    df = add_derived_features(pd.DataFrame([
        _played("Centre-Forward", 0.9, 0.9, 0.9),
        _played("Centre-Forward", 0.05, 0.05, 0.05),
    ]))

    assert df["gi_x_career"].tolist() == pytest.approx([0.45, 0.025])
