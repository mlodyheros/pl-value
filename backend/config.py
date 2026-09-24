"""Shared configuration and paths for the pl-value-predictor pipeline."""

from pathlib import Path

FPL_BASE_URL = "https://fantasy.premierleague.com/api"
# FPL numbers are season-to-date, so a cached copy goes stale after a gameweek
FPL_CACHE_MAX_AGE_HOURS = 24
# Past-season PL stats come from a community archive of the FPL API, one CSV
# per season, instead of one request per player against the live API.
FPL_ARCHIVE_BASE_URL = (
    "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
)

UNDERSTAT_BASE_URL = "https://understat.com"
UNDERSTAT_DELAY_SECONDS = 1.0
# Understat's coverage. The Premier League is excluded on purpose: FPL already
# supplies it, and these features exist to describe a player's career *before*
# they arrived. Portugal, the Championship and the Eredivisie aren't covered by
# Understat at all, which is why some new arrivals still have no history.
UNDERSTAT_LEAGUES = ["La liga", "Bundesliga", "Serie A", "Ligue 1", "RFPL"]
# The quality measure reads every league Understat covers, the PL included, so
# players from abroad and from the PL are scored the same way.
UNDERSTAT_QUALITY_LEAGUES = ["EPL", *UNDERSTAT_LEAGUES]
# FPL's club names where Understat's differ, for matching a player within his club.
UNDERSTAT_TEAM_NAMES = {
    "Man City": "Manchester City",
    "Man Utd": "Manchester United",
    "Spurs": "Tottenham",
    "Nott'm Forest": "Nottingham Forest",
    "Newcastle": "Newcastle United",
    "Wolves": "Wolverhampton Wanderers",
}

TRANSFERMARKT_BASE_URL = "https://www.transfermarkt.com"
TRANSFERMARKT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# Be polite to Transfermarkt between page requests
TRANSFERMARKT_DELAY_SECONDS = 2.5
# Squad and transfer pages are refetched once they are a week old: Transfermarkt
# revalues players every few weeks, and a squad changes in the windows. Club
# search pages never go stale and are kept for good.
TRANSFERMARKT_PAGE_MAX_AGE_HOURS = 7 * 24

# Completed PL seasons (start-year) to aggregate past-season stats over.
# Transfermarkt only exposes *current* market value (its season filters don't
# actually change results), so the target is always "current value" and these
# seasons only feed the playing-history features.
SEASONS = [2022, 2023, 2024, 2025]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = PROJECT_ROOT / "models"
FIGURES_DIR = PROJECT_ROOT / "reports" / "figures"

TRANSFERMARKT_RAW_DIR = RAW_DIR / "transfermarkt"
FPL_RAW_DIR = RAW_DIR / "fpl"
UNDERSTAT_RAW_DIR = RAW_DIR / "understat"
FPL_ARCHIVE_RAW_DIR = RAW_DIR / "fpl_archive"
# Optional one-off download; see backend/sources/transfer_fees.py
KAGGLE_RAW_DIR = RAW_DIR / "kaggle"
TRANSFERMARKT_CLUB_ID_CACHE = TRANSFERMARKT_RAW_DIR / "club_ids.json"

PROCESSED_DATASET_PATH = PROCESSED_DIR / "pl_players.csv"
MODEL_PATH = MODELS_DIR / "linear_regression.joblib"
CALIBRATION_PATH = MODELS_DIR / "confidence_calibration.json"
# The second model: likely transfer fee (backend/fee_model.py).
FEE_MODEL_PATH = MODELS_DIR / "fee_model.joblib"
FEE_CALIBRATION_PATH = MODELS_DIR / "fee_calibration.json"
