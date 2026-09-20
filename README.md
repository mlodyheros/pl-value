# pl-value-predictor

Predicts Premier League players' transfer market value from their on-pitch
stats, and lets you compare the model's estimate against their actual value.

- **Performance stats** (goals, assists, penalties, appearances) come from the
  [football-data.org](https://www.football-data.org/) API, aggregated over
  several recent completed seasons.
- **Market values** (the prediction target), plus each player's age, position
  and nationality, are scraped from Transfermarkt's current squad pages.
- A scikit-learn **linear regression** pipeline (on log-transformed value,
  since transfer values are heavily right-skewed) is trained on the merged
  dataset. Features: age (and age², since value peaks mid-20s), goals,
  assists, penalties, appearances, a `has_scorer_record` flag, position and club.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Get a free API key at https://www.football-data.org/client/register and put
it in `.env`:

```
FOOTBALL_DATA_API_KEY=your_key_here
```

## Usage

```bash
# 1. Build the dataset (scrapes Transfermarkt + calls football-data.org).
#    Takes a few minutes on a cold cache; raw responses are cached under
#    data/raw/ so re-runs are near-instant.
python -m src.data.build_dataset

# 2. Train the model. Prints held-out and 5-fold CV R²/MAE/RMSE and writes
#    reports/figures/pred_vs_actual.png and models/linear_regression.joblib
python -m src.model

# 3. Compare a player's predicted value against their actual value
python -m src.predict --player "Erling Haaland"

# ...or predict for a hypothetical player by hand
python -m src.predict --age 24 --position "Centre-Forward" --club "Manchester City FC" \
    --goals 20 --assists 8 --appearances 34
```

## Current performance

5-fold cross-validated on ~540 players: **R² ≈ 0.51** (on log value), **MAE ≈ €9.8m**.
Trust the CV numbers over the single 80/20 split, which swings by ~0.1 R² between
seeds at this dataset size.

Training weights players by √value. Plain log-value regression optimises
*relative* error, so cheap players outvote the stars and the top 10% of players
were predicted ~24% too low. The weighting cut overall MAE from €10.3m to €9.8m
and top-decile MAE from €32m to €26m, at the cost of ~0.04 log-R². The model
still under-predicts the very top (top-10% predicted/actual ≈ 0.80; Haaland comes
out at ~€166m vs €220m): stats alone don't capture star premium.

Also tried, and rejected: random forest / gradient boosting, position×stat
interactions, sqrt/power target transforms (unstable on log-scale R²), boosting
on residuals, and Duan smearing (removes the bias but raises overall MAE to €11.6m).

## Known limitations

- **No minutes-played data**: football-data.org's free tier doesn't expose
  it. `appearances` (played matches) from the scorers endpoint is used as the
  closest available proxy.
- **Market value is always "current"**: Transfermarkt doesn't expose reliable
  historical values through the pages this project scrapes (its season
  filters affect squad membership, not the value shown), so the model
  predicts *today's* value from *recent* performance, not a value at a
  specific past date.
- **Stats only exist for scorers**: football-data.org's scorers endpoint only
  lists players who've scored or assisted. Players outside that list (about
  half the squad: most defenders/keepers) get `0` for all performance stats
  rather than their true totals. The `has_scorer_record` feature lets the
  model tell "no data" from a genuine zero, and `build_dataset.py` logs how
  many players this affects.
- **Only 3 seasons of stats**: the free tier returns 403 for 2022, so
  `SEASONS` covers 2023-2025.
- **Fuzzy name matching**: players are joined between the two data sources by
  name (exact, falling back to fuzzy matching). This occasionally misses or
  mismatches, especially for accented names.
- **Transfermarkt scraping**: this scrapes public pages politely (delays
  between requests, cached responses) for personal/educational use. It is
  against Transfermarkt's terms of service for heavier or commercial use.

## Project layout

```
src/
  config.py                       paths, API keys, season settings
  features.py                     feature/target definitions, train-test split
  model.py                        builds/trains the sklearn pipeline
  evaluate.py                     predicted-vs-actual and residual plots
  predict.py                      CLI to compare prediction vs actual
  data/
    football_data_client.py       football-data.org API wrapper (cached, rate-limited)
    transfermarkt_scraper.py      Transfermarkt squad/value scraper (cached, rate-limited)
    build_dataset.py              orchestrates the two sources into one CSV
data/
  raw/                            cached API/HTML responses (gitignored)
  processed/pl_players.csv        the merged dataset (gitignored)
models/                           trained model artifacts (gitignored)
reports/figures/                  generated evaluation plots
tests/                            unit tests (no network calls)
```
