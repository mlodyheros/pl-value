"""Keep the numbers current: rebuild the dataset and retrain when there is
something new - a gameweek finished since the last build, or Transfermarkt's
squad pages more than a week old.

Meant to run once a day (``scripts/install_refresh_schedule.sh`` sets that up on
macOS); on a day with nothing new it only asks FPL which gameweek it is. The API
picks up a rebuilt dataset on its next request, so the server keeps running.

    python -m backend.refresh            # only when something has changed
    python -m backend.refresh --force    # rebuild regardless
"""

from __future__ import annotations

import argparse
import logging
import time

import pandas as pd

from backend.config import (
    PROCESSED_DATASET_PATH,
    TRANSFERMARKT_PAGE_MAX_AGE_HOURS,
    TRANSFERMARKT_RAW_DIR,
)
from backend.sources import fpl_client

logger = logging.getLogger(__name__)


def _built_gameweeks() -> int | None:
    if not PROCESSED_DATASET_PATH.exists():
        return None
    return int(pd.read_csv(PROCESSED_DATASET_PATH, usecols=["fpl_gameweeks"]).fpl_gameweeks.iloc[0])


def _stale_pages(now: float | None = None) -> list[str]:
    now = now or time.time()
    limit = TRANSFERMARKT_PAGE_MAX_AGE_HOURS * 3600
    return sorted(
        page.name
        for page in TRANSFERMARKT_RAW_DIR.glob("squad_*.html")
        if now - page.stat().st_mtime >= limit
    )


def reasons_to_refresh(finished_gameweeks: int, now: float | None = None) -> list[str]:
    """Why the data is out of date; empty when it is current."""
    built = _built_gameweeks()
    if built is None:
        return ["there is no dataset yet"]
    reasons = []
    if finished_gameweeks > built:
        reasons.append(f"gameweek {finished_gameweeks} has finished; the data stops at {built}")
    stale = _stale_pages(now)
    if stale:
        reasons.append(f"{len(stale)} Transfermarkt squad pages are over a week old")
    return reasons


def refresh(force: bool = False) -> bool:
    """Rebuild and retrain if anything is new. Returns whether it did."""
    fpl_data = fpl_client.get_bootstrap_static(refresh=True)
    reasons = reasons_to_refresh(fpl_client.finished_gameweeks(fpl_data))
    if not reasons and not force:
        logger.info("Nothing new since the last build; leaving the data as it is")
        return False

    logger.info("Refreshing: %s", "; ".join(reasons) or "forced")
    # Imported here so a quiet day never loads the modelling stack.
    from backend import fee_model, model
    from backend.sources.build_dataset import build_dataset

    build_dataset()
    model.main()
    fee_model.main()
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Rebuild and retrain when the data is out of date")
    parser.add_argument("--force", action="store_true", help="rebuild even if nothing has changed")
    refresh(force=parser.parse_args().force)


if __name__ == "__main__":
    main()
