"""CLI to compare the model's predicted market value against the actual value
for a player already in the dataset, or for manually-entered stats.
"""

from __future__ import annotations

import argparse

import joblib
import numpy as np
import pandas as pd

from src.config import MODEL_PATH, PROCESSED_DATASET_PATH
from src.features import prepare_features


def load_pipeline():
    return joblib.load(MODEL_PATH)


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
    for _, row in matches.iterrows():
        predicted = predict_for_row(pipeline, row)
        actual = row["market_value_eur"]
        diff_pct = (predicted - actual) / actual * 100
        print(f"\n{row['name']} ({row['club']}, {row['position']}, age {row['age']})")
        print(
            f"  Stats: {row['goals']}G {row['assists']}A, "
            f"{row['appearances']} appearances (recent seasons)"
        )
        if row.get("has_fpl_record") == 1:
            print(f"  This season (FPL): {row['fpl_minutes']:.0f} minutes, {row['fpl_starts']:.0f} starts")
        print(f"  Actual value:    €{actual:,.0f}")
        print(f"  Predicted value: €{predicted:,.0f}  ({diff_pct:+.1f}% vs actual)")


def predict_manual(
    age,
    position,
    club,
    goals,
    assists,
    penalties,
    appearances,
    minutes_share=None,
    starts_share=None,
) -> None:
    """``minutes_share``/``starts_share`` (0-1) are this season's FPL playing time;
    omit both if unknown."""
    pipeline = load_pipeline()
    row = prepare_features(
        pd.DataFrame(
            [
                {
                    "age": age,
                    "goals": goals,
                    "assists": assists,
                    "penalties": penalties,
                    "appearances": appearances,
                    "position": position,
                    "club": club,
                    "has_fpl_record": int(minutes_share is not None or starts_share is not None),
                    "minutes_share": minutes_share or 0.0,
                    "starts_share": starts_share or 0.0,
                }
            ]
        )
    )
    predicted = np.expm1(pipeline.predict(row)[0])
    print(f"Predicted value: €{predicted:,.0f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict a PL player's market value")
    parser.add_argument("--player", help="Look up a player already in the dataset by name")
    parser.add_argument("--age", type=int)
    parser.add_argument("--position", help='e.g. "Centre-Forward"')
    parser.add_argument("--club", help='e.g. "Manchester City FC"')
    parser.add_argument("--goals", type=int, default=0)
    parser.add_argument("--assists", type=int, default=0)
    parser.add_argument("--penalties", type=int, default=0)
    parser.add_argument("--appearances", type=int, default=0)
    parser.add_argument(
        "--minutes-share", type=float, help="share of this season's minutes played (0-1)"
    )
    parser.add_argument(
        "--starts-share", type=float, help="starts per gameweek this season (0-1)"
    )
    args = parser.parse_args()

    if args.player:
        predict_player(args.player)
    elif args.age and args.position and args.club:
        predict_manual(
            args.age,
            args.position,
            args.club,
            args.goals,
            args.assists,
            args.penalties,
            args.appearances,
            args.minutes_share,
            args.starts_share,
        )
    else:
        parser.error("Provide --player NAME, or --age/--position/--club for a manual prediction")


if __name__ == "__main__":
    main()
