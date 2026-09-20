"""HTTP API over the trained model, and the only thing the frontend talks to.

The frontend never imports the pipeline; it asks this layer, so the two stay
separable.

Predictions served here are **out-of-fold**: every player is scored by a model
fitted without them. A model asked about a player it was trained on flatters
itself, and "is this player overvalued?" is exactly the question that flattery
would corrupt. Computing them costs one extra fit per fold at startup.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sklearn.model_selection import KFold

from backend import confidence
from backend.config import CALIBRATION_PATH, PROCESSED_DATASET_PATH, PROJECT_ROOT
from backend.features import add_derived_features, split_features_target
from backend.model import build_pipeline, cross_validate_model, fit_pipeline

logger = logging.getLogger(__name__)

FRONTEND_DIR = PROJECT_ROOT / "frontend"
CONFIDENCE_LEVEL = 0.8


def _out_of_fold_predictions(df: pd.DataFrame, n_splits: int = 5) -> np.ndarray:
    X, y = split_features_target(df)
    predicted = pd.Series(0.0, index=df.index)
    for train_idx, test_idx in KFold(n_splits, shuffle=True, random_state=42).split(X):
        fitted = fit_pipeline(build_pipeline(), X.iloc[train_idx], y.iloc[train_idx])
        predicted.iloc[test_idx] = fitted.predict(X.iloc[test_idx])
    return np.expm1(predicted.to_numpy())


@lru_cache(maxsize=1)
def get_state() -> dict:
    """Dataset, predictions and calibration, prepared once per process."""
    if not PROCESSED_DATASET_PATH.exists():
        raise RuntimeError(
            f"No dataset at {PROCESSED_DATASET_PATH}. "
            "Run `python -m backend.sources.build_dataset` first."
        )
    df = add_derived_features(pd.read_csv(PROCESSED_DATASET_PATH))
    df["predicted_eur"] = _out_of_fold_predictions(df)
    df["tier"] = confidence.coverage_tiers(df)
    df["gap_pct"] = (df.predicted_eur / df.market_value_eur - 1) * 100

    calibration = (
        json.loads(CALIBRATION_PATH.read_text()) if CALIBRATION_PATH.exists() else None
    )
    logger.info("API ready: %d players", len(df))
    return {"df": df, "calibration": calibration, "metrics": cross_validate_model(df)}


def _player_payload(row: pd.Series, calibration: dict | None) -> dict:
    predicted = float(row.predicted_eur)
    low = high = None
    if calibration is not None:
        low, high = confidence.interval(predicted, row.tier, calibration, CONFIDENCE_LEVEL)

    return {
        "id": int(row.name),
        "name": row["name"],
        "club": row.club,
        "position": row.position,
        "age": int(row.age),
        "nationality": row.nationality,
        "marketValueEur": float(row.market_value_eur),
        "predictedEur": predicted,
        "gapPct": float(row.gap_pct),
        "range": None if low is None else {"lowEur": float(low), "highEur": float(high)},
        # Does the market's own number fall inside the range the model allows?
        "marketInRange": None
        if low is None
        else bool(low <= row.market_value_eur <= high),
        "confidence": {
            "tier": row.tier,
            "level": CONFIDENCE_LEVEL,
            "label": confidence.TIER_LABELS[row.tier],
            "summary": None
            if calibration is None
            else confidence.describe(row.tier, calibration, CONFIDENCE_LEVEL),
        },
        "evidence": {
            "thisSeason": {
                "minutes": int(row.fpl_minutes),
                "starts": int(row.fpl_starts),
                "gameweeks": int(row.fpl_gameweeks),
                "known": bool(row.has_fpl_record),
            },
            "premierLeague": {
                "seasons": int(row.hist_seasons),
                "minutes": int(row.hist_minutes),
                "goals": int(row.hist_goals),
                "assists": int(row.hist_assists),
                "known": bool(row.has_hist_record),
            },
            "otherLeagues": {
                "seasons": int(row.nonpl_seasons),
                "minutes": int(row.nonpl_minutes),
                "goals": int(row.nonpl_goals),
                "assists": int(row.nonpl_assists),
                "known": bool(row.has_nonpl_record),
            },
        },
    }


app = FastAPI(title="PL Value Predictor", docs_url="/api/docs")


@app.get("/api/players")
def list_players() -> list[dict]:
    """Everyone, trimmed to what the search box needs. Small enough to send once."""
    df = get_state()["df"]
    return [
        {
            "id": int(i),
            "name": r["name"],
            "club": r.club,
            "position": r.position,
            "age": int(r.age),
            "marketValueEur": float(r.market_value_eur),
            "predictedEur": float(r.predicted_eur),
            "gapPct": float(r.gap_pct),
            "tier": r.tier,
        }
        for i, r in df.iterrows()
    ]


@app.get("/api/players/{player_id}")
def get_player(player_id: int) -> dict:
    state = get_state()
    df = state["df"]
    if player_id not in df.index:
        raise HTTPException(status_code=404, detail="No player with that id")
    return _player_payload(df.loc[player_id], state["calibration"])


@app.get("/api/rankings")
def rankings(limit: int = 10, min_value_eur: float = 15_000_000) -> dict:
    """Biggest disagreements between the model and the market.

    Cheap players are excluded by default: a percentage gap on a EUR300k squad
    player is noise, and would crowd out the differences worth looking at.
    """
    df = get_state()["df"]
    eligible = df[df.market_value_eur >= min_value_eur]

    def rows(frame):
        return [
            {
                "id": int(i),
                "name": r["name"],
                "club": r.club,
                "position": r.position,
                "marketValueEur": float(r.market_value_eur),
                "predictedEur": float(r.predicted_eur),
                "gapPct": float(r.gap_pct),
                "tier": r.tier,
            }
            for i, r in frame.iterrows()
        ]

    return {
        "underrated": rows(eligible.nlargest(limit, "gap_pct")),
        "overrated": rows(eligible.nsmallest(limit, "gap_pct")),
        "minValueEur": min_value_eur,
    }


@app.get("/api/meta")
def meta() -> dict:
    state = get_state()
    df, calibration = state["df"], state["calibration"]
    metrics = state["metrics"]
    tiers = {}
    for tier in confidence.TIERS:
        members = df[df.tier == tier]
        entry = {"players": int(len(members)), "label": confidence.TIER_LABELS[tier]}
        if calibration is not None:
            low, high = confidence.interval(1.0, tier, calibration, CONFIDENCE_LEVEL)
            entry |= {"lowRatio": round(float(low), 3), "highRatio": round(float(high), 3)}
        tiers[tier] = entry

    return {
        "players": int(len(df)),
        "clubs": int(df.club.nunique()),
        "seasonGameweeks": int(df.fpl_gameweeks.iloc[0]),
        "confidenceLevel": CONFIDENCE_LEVEL,
        "calibrated": calibration is not None,
        "tiers": tiers,
        "model": {
            "r2Log": round(metrics["cv_r2_log"], 3),
            "maeEur": round(metrics["cv_mae_eur"]),
            "topDecileMaeEur": round(metrics["cv_top_decile_mae_eur"]),
        },
    }


if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
