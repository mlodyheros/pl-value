# pl-value-predictor

Predicts Premier League players' transfer market value from their on-pitch
stats, and lets you compare the model's estimate against their actual value.

- **Performance stats** (goals, assists, penalties, appearances) come from the
  [football-data.org](https://www.football-data.org/) API, aggregated over
  several recent completed seasons.
- **Playing time** comes from the official
  [Fantasy Premier League API](https://fantasy.premierleague.com/api/bootstrap-static/)
  (free, no key): this season's minutes and starts, plus each player's past PL
  seasons (minutes, starts, goals, assists, xG/xA) from the per-player
  endpoint. Unlike football-data.org this covers defenders and keepers too.
- **Market values** (the prediction target), plus each player's age, position
  and nationality, are scraped from Transfermarkt's current squad pages.
- A scikit-learn **linear regression** pipeline (on log-transformed value,
  since transfer values are heavily right-skewed) is trained on the merged
  dataset. Features: age (and age², since value peaks mid-20s), goals,
  assists, penalties, appearances, this season's minutes/starts share, the share
  of minutes played in past PL seasons, flags for whether each stats source had
  a record for the player, position and club.

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
# 1. Build the dataset (scrapes Transfermarkt + calls football-data.org + FPL).
#    Takes a few minutes on a cold cache; raw responses are cached under
#    data/raw/ so re-runs are near-instant. The FPL response is season-to-date,
#    so its cache expires after 24h; add --refresh-fpl to force a refetch.
#    Per-player FPL history is one request each (~10 min cold, then cached 30d).
python -m src.data.build_dataset

# 2. Train the model. Prints held-out and 5-fold CV R²/MAE/RMSE and writes
#    reports/figures/pred_vs_actual.png and models/linear_regression.joblib
python -m src.model

# 3. Compare a player's predicted value against their actual value
python -m src.predict --player "Erling Haaland"

# ...or predict for a hypothetical player by hand
python -m src.predict --age 24 --position "Centre-Forward" --club "Manchester City FC" \
    --goals 20 --assists 8 --appearances 34 --minutes-share 0.9 --starts-share 1 \
    --hist-minutes-share 0.8
```

`notebooks/01_model_exploration.ipynb` walks through the data, the model and
the experiment log behind the modelling choices (run the dataset build first).

## Current performance

5-fold cross-validated on ~540 players: **R² ≈ 0.65** (on log value), **MAE ≈ €8.1m**.
Trust the CV numbers over the single 80/20 split, which swings by ~0.1 R² between
seeds at this dataset size.

What moved the needle (details and numbers in the notebook):

| Features | R² (log) | MAE | top-10% MAE |
|---|---|---|---|
| raw stats only | 0.36 | €11.5m | €27.2m |
| + age² (value peaks mid-20s) | 0.50 | €10.0m | €26.8m |
| + this season's playing time (FPL) | 0.58 | €9.3m | €25.2m |
| + past seasons' minutes (FPL history) | **0.65** | **€8.3m** | **€19.5m** |

Past-season minutes is the single biggest addition: it covers defenders and keepers that
football-data.org's scorers endpoint misses, and it's a settled signal rather than a few
gameweeks of noise.

Training weights players by √value. Plain log-value regression optimises *relative* error,
so cheap players outvote the stars; weighting lowers euro MAE overall (€9.0m → €8.3m) and
for the top 10% (€21.8m → €19.5m), at some cost in log-R² (0.68 → 0.65).

The model still under-predicts the very top (top-10% predicted/actual ≈ 0.88): stats alone
don't capture star premium. It also under-predicts players with no PL history (new signings
from abroad, academy players) - about a quarter of the squad, flagged by `has_hist_record`.

Tried and rejected: random forest / gradient boosting (with matched weights the linear model
has the lowest euro error), past-season starts / xG / goals (redundant once the model knows
minutes played), this season's xG/xA and defensive stats (still noise after 4 gameweeks; worth
re-testing later in the season), position×stat interactions, power target transforms, boosting
on residuals, Duan smearing, and FPL price (better log-R², much worse euro error).

Worth knowing: dropping the football-data.org stats entirely scores within noise of the
current model, so that API key is now carrying very little weight.

## Known limitations

- **No historical minutes-played data**: football-data.org's free tier doesn't
  expose it, so for the 2023-2025 seasons `appearances` (played matches) from
  the scorers endpoint is the closest proxy. Minutes for the *current* season
  come from FPL (see below).
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
- **Name matching**: players are joined across the three sources by
  accent-insensitive name (exact, short name, unique name-token subset, then
  fuzzy). ~96% of players are found in FPL; the rest (mostly loanees and
  departed players) get no playing-time data, which makes the model
  under-predict them. The `has_fpl_record` flag lets you spot them.
- **This season's FPL data is only a few gameweeks old** at the time of writing,
  so `minutes_share` is a noisy early-season signal (the past-season history
  carries most of the weight). Shares are normalised by gameweeks played so the
  feature stays comparable over time, but retrain as the season progresses.
- **No PL history for new arrivals**: the FPL history only covers seasons a
  player spent in the Premier League, so signings from abroad and academy
  players have none and get under-predicted. `has_hist_record` flags them.
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
    fpl_client.py                 FPL API: current season + per-player history (cached)
    names.py                      name normalisation shared by the joins
    transfermarkt_scraper.py      Transfermarkt squad/value scraper (cached, rate-limited)
    build_dataset.py              orchestrates the three sources into one CSV
notebooks/                        exploration and experiment log (executed, outputs included)
data/
  raw/                            cached API/HTML responses (gitignored)
  processed/pl_players.csv        the merged dataset (gitignored)
models/                           trained model artifacts (gitignored)
reports/figures/                  generated evaluation plots
tests/                            unit tests (no network calls)
```
