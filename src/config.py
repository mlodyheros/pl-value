"""Shared configuration and paths for the pl-value-predictor pipeline."""

from pathlib import Path

from dotenv import load_dotenv
import os

load_dotenv()

FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4"

FPL_BASE_URL = "https://fantasy.premierleague.com/api"
# FPL numbers are season-to-date, so a cached copy goes stale after a gameweek
FPL_CACHE_MAX_AGE_HOURS = 24

TRANSFERMARKT_BASE_URL = "https://www.transfermarkt.com"
TRANSFERMARKT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# football-data.org free tier: 10 requests/minute
FOOTBALL_DATA_RATE_LIMIT_SECONDS = 6.5
# Be polite to Transfermarkt between page requests
TRANSFERMARKT_DELAY_SECONDS = 2.5

# Season (start-year) used to fetch the current PL club list, e.g. 2026 = 2026/27
CURRENT_SEASON = 2026

# Completed PL seasons (start-year) to aggregate performance stats over.
# Transfermarkt only exposes *current* market value (its season filters don't
# actually change results), so the target is always "current value" and these
# seasons only feed the recent-form features (goals/assists/etc).
# 2022 is omitted: football-data.org's free tier returns 403 for it.
SEASONS = [2023, 2024, 2025]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = PROJECT_ROOT / "models"
FIGURES_DIR = PROJECT_ROOT / "reports" / "figures"

FOOTBALL_DATA_RAW_DIR = RAW_DIR / "football_data"
TRANSFERMARKT_RAW_DIR = RAW_DIR / "transfermarkt"
FPL_RAW_DIR = RAW_DIR / "fpl"
TRANSFERMARKT_CLUB_ID_CACHE = TRANSFERMARKT_RAW_DIR / "club_ids.json"

PROCESSED_DATASET_PATH = PROCESSED_DIR / "pl_players.csv"
MODEL_PATH = MODELS_DIR / "linear_regression.joblib"
