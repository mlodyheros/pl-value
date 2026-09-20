"""CLI to compare the model's predicted market value against the actual value
for a player already in the dataset, or for manually-entered stats.
"""

from __future__ import annotations

import argparse

import json

import joblib
import numpy as np
import pandas as pd

from backend import confidence
from backend.config import CALIBRATION_PATH, MODEL_PATH, PROCESSED_DATASET_PATH
from backend.features import CATEGORICAL_FEATURES, prepare_features


def load_pipeline():
    return joblib.load(MODEL_PATH)


def load_calibration() -> dict | None:
    """Measured error spreads, written by `python -m backend.model`."""
    if not CALIBRATION_PATH.exists():
        return None
    return json.loads(CALIBRATION_PATH.read_text())


def format_confidence(row: pd.Series, predicted: float, calibration: dict | None) -> list[str]:
    """Lines describing how much room to leave around a prediction."""
    if calibration is None:
        return ["  Confidence:      unknown (run `python -m backend.model` to calibrate)"]
    tier = confidence.coverage_tiers(row.to_frame().T).iloc[0]
    low, high = confidence.interval(predicted, tier, calibration)
    return [
        f"  Confidence:      {confidence.describe(tier, calibration)}",
        f"  80% range:       EUR{low:,.0f} - EUR{high:,.0f}",
    ]


def known_categories(pipeline) -> dict[str, list[str]]:
    """The club/position values the pipeline was actually trained on."""
    encoder = pipeline.named_steps["preprocess"].named_transformers_["categorical"]
    return dict(zip(CATEGORICAL_FEATURES, [list(c) for c in encoder.categories_]))


def validate_categories(pipeline, **values: str) -> None:
    """Fail loudly on an unseen club/position.

    The encoder is configured with ``handle_unknown="ignore"``, which silently
    encodes an unknown value as all-zeros and returns a confident-looking but
    meaningless number - worse than an error.
    """
    known = known_categories(pipeline)
    for column, value in values.items():
        if value is not None and value not in known[column]:
            options = ", ".join(known[column])
            raise SystemExit(f"Unknown {column} {value!r}.\nKnown values: {options}")


def predict_for_row(pipeline, row: pd.Series) -> float:
    X = prepare_features(row.to_frame().T.infer_objects())
    return float(np.expm1(pipeline.predict(X)[0]))


def predict_player(name: str) -> None:
    df = pd.read_csv(PROCESSED_DATASET_PATH)
    matches = df[df["name"].str.lower() == name.lower()]
    if matches.empty:
        matches = df[df["name"].str.lower().str.contains(name.lower(), regex=False)]
    if matches.empty:
        print(f"No player found matching {name!r}")
        return

    pipeline = load_pipeline()
    calibration = load_calibration()
    for _, row in matches.iterrows():
        predicted = predict_for_row(pipeline, row)
        actual = row["market_value_eur"]
        diff_pct = (predicted - actual) / actual * 100
        print(f"\n{row['name']} ({row['club']}, {row['position']}, age {row['age']})")
        if row.get("has_fpl_record") == 1:
            print(f"  This season (FPL): {row['fpl_minutes']:.0f} minutes, {row['fpl_starts']:.0f} starts")
        if row.get("has_hist_record") == 1:
            print(
                f"  Past {row['hist_seasons']:.0f} PL season(s): {row['hist_minutes']:.0f} minutes, "
                f"{row['hist_goals']:.0f}G {row['hist_assists']:.0f}A"
            )
        elif row.get("has_nonpl_record") == 1:
            print(
                f"  Past {row['nonpl_seasons']:.0f} season(s) outside the PL: "
                f"{row['nonpl_minutes']:.0f} minutes, "
                f"{row['nonpl_goals']:.0f}G {row['nonpl_assists']:.0f}A"
            )
        else:
            print("  No recent history in any covered league (prediction is weak)")
        print(f"  Actual value:    €{actual:,.0f}")
        print(f"  Predicted value: €{predicted:,.0f}  ({diff_pct:+.1f}% vs actual)")
        for line in format_confidence(row, predicted, calibration):
            print(line.replace("EUR", "€"))


def predict_manual(
    age,
    position,
    club,
    minutes_share=None,
    career_minutes_share=None,
    career_gi_per90=None,
) -> None:
    """``minutes_share`` (0-1) is this season's playing time;
    ``career_minutes_share`` (0-1) and ``career_gi_per90`` describe recent completed
    seasons in any covered league. Omit any you don't know."""
    pipeline = load_pipeline()
    validate_categories(pipeline, position=position, club=club)
    row = prepare_features(
        pd.DataFrame(
            [
                {
                    "age": age,
                    "position": position,
                    "club": club,
                    "has_fpl_record": int(minutes_share is not None),
                    "minutes_share": minutes_share or 0.0,
                    # Supplying a career record is a claim that one exists, so
                    # the confidence tier should reflect it rather than reporting
                    # "no playing record" back at the person who just gave one.
                    "has_hist_record": int(career_minutes_share is not None),
                    "has_any_history": int(career_minutes_share is not None),
                    "career_minutes_share": career_minutes_share or 0.0,
                    "career_gi_per90": career_gi_per90 or 0.0,
                }
            ]
        )
    )
    predicted = np.expm1(pipeline.predict(row)[0])
    print(f"Predicted value: €{predicted:,.0f}")
    for line in format_confidence(row.iloc[0], predicted, load_calibration()):
        print(line.replace("EUR", "€").strip().replace("  ", " "))


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict a PL player's market value")
    parser.add_argument("--player", help="Look up a player already in the dataset by name")
    parser.add_argument("--age", type=int)
    parser.add_argument("--position", help='e.g. "Centre-Forward"')
    parser.add_argument("--club", help='e.g. "Manchester City"')
    parser.add_argument(
        "--minutes-share", type=float, help="share of this season's minutes played (0-1)"
    )
    parser.add_argument(
        "--career-minutes-share",
        type=float,
        help="share of minutes played across recent completed seasons (0-1)",
    )
    parser.add_argument(
        "--career-gi-per90", type=float, help="career goals+assists per 90 minutes"
    )
    args = parser.parse_args()

    if args.player:
        predict_player(args.player)
    elif args.age and args.position and args.club:
        predict_manual(
            args.age,
            args.position,
            args.club,
            args.minutes_share,
            args.career_minutes_share,
            args.career_gi_per90,
        )
    else:
        parser.error("Provide --player NAME, or --age/--position/--club for a manual prediction")


if __name__ == "__main__":
    main()
