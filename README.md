# pl-value-predictor

Predicts Premier League players' transfer market value from their on-pitch
stats, and lets you compare the model's estimate against their actual value.

- **Playing history** comes from the official
  [Fantasy Premier League API](https://fantasy.premierleague.com/api/bootstrap-static/)
  (free, no key, no registration): the club list, this season's minutes and
  starts, and each player's past PL seasons (minutes, goals, assists, xG/xA).
  Unlike a top-scorers feed it covers defenders and keepers too.
- **Market values** (the prediction target), plus each player's age, position
  and nationality, are scraped from Transfermarkt's current squad pages.
- A scikit-learn **linear regression** pipeline (on log-transformed value,
  since transfer values are heavily right-skewed) is trained on the merged
  dataset. Features: age and age² (value peaks mid-20s), this season's
  minutes/starts share, the share of minutes played in past PL seasons,
  past-season goals+assists per 90, data-coverage flags, position and club.

## Layout

```
backend/     data pipeline + model (all current work)
frontend/    not built yet - see frontend/README.md
```

## Setup

```bash
pip install -r requirements.txt
```

No API keys and no accounts: both sources are public.

## Usage

```bash
# 1. Build the dataset (FPL API + Transfermarkt scrape). Raw responses are
#    cached under data/raw/, so re-runs are near-instant. Per-player FPL
#    history is one request each (~10 min cold, then cached for 30 days);
#    the season-to-date response expires after 24h (--refresh-fpl forces it).
python -m backend.data.build_dataset

# 2. Train the model. Prints held-out and 5-fold CV R²/MAE/RMSE and writes
#    reports/figures/pred_vs_actual.png and models/linear_regression.joblib
python -m backend.model

# 3. Compare a player's predicted value against their actual value
python -m backend.predict --player "Erling Haaland"

# ...or predict for a hypothetical player by hand
python -m backend.predict --age 24 --position "Centre-Forward" --club "Manchester City FC" \
    --goals 20 --assists 8 --appearances 34 --minutes-share 0.9 --starts-share 1 \
    --hist-minutes-share 0.8
```

`notebooks/01_model_exploration.ipynb` walks through the data, the model and
the experiment log behind the modelling choices (run the dataset build first).

## Current performance

5-fold cross-validated on ~540 players: **R² ≈ 0.65** (on log value), **MAE ≈ €8.2m**.
Trust the CV numbers over the single 80/20 split, which swings by ~0.1 R² between
seeds at this dataset size.

| Features | R² (log) | MAE | top-10% MAE |
|---|---|---|---|
| age + position + club only | 0.36 | €11.5m | €27.2m |
| + age² (value peaks mid-20s) | 0.50 | €10.0m | €26.8m |
| + this season's playing time | 0.58 | €9.3m | €25.2m |
| + past seasons' minutes | 0.64 | €8.5m | €19.8m |
| + past-season goals+assists **per 90** | **0.65** | **€8.2m** | **€19.3m** |

Two findings worth keeping in mind:

- **Playing time beats output.** How much a player plays, for which club, at what
  age explains most of the value. Past-season minutes was the single biggest gain.
- **Rates matter, totals don't.** Raw goal totals add nothing - they're largely a
  restatement of minutes played. Goals+assists *per 90* is independent of playing
  time and does help, especially for expensive forwards.

Training weights players by √value. Plain log-value regression optimises *relative*
error, so cheap players outvote the stars; weighting lowers euro MAE overall and for
the top 10%, at some cost in log-R².

The model still under-predicts the very top (top-10% predicted/actual ≈ 0.89) and
players with no PL history - about a quarter of the squad, flagged by `has_hist_record`.

Tried and rejected: random forest / gradient boosting (with matched weights the linear
model has the lowest euro error), past-season starts and xG/xA per 90 (nothing on top of
actual output), this season's xG/xA and defensive stats (still noise after 4 gameweeks),
position×stat interactions, power target transforms, boosting on residuals, Duan
smearing, and FPL price (better log-R², much worse euro error).

## Known limitations

- **Market value is always "current"**: Transfermarkt doesn't expose reliable
  historical values through the pages this project scrapes (its season filters
  affect squad membership, not the value shown), so the model predicts *today's*
  value from *recent* performance, not a value at a specific past date.
- **No PL history for new arrivals**: FPL history only covers seasons a player
  spent in the Premier League, so signings from abroad and academy players have
  none and get under-predicted. `has_hist_record` flags them. This is currently
  the largest source of error.
- **This season's data is only a few gameweeks old** at the time of writing, so
  `minutes_share` is a noisy early-season signal and the past-season history
  carries most of the weight. Shares are normalised by gameweeks played so the
  feature stays comparable over time, but retrain as the season progresses.
- **Name matching**: players are joined between the sources by accent-insensitive
  name (exact, short name, unique name-token subset, then fuzzy). ~96% of players
  are found in FPL; the rest (mostly loanees and departed players) get no
  playing-time data. The `has_fpl_record` flag lets you spot them.
- **Club names come from Transfermarkt** (e.g. `Man City`, not `Manchester City FC`).
  `predict` lists the valid values if you pass an unknown one.
- **Transfermarkt scraping**: this scrapes public pages politely (delays between
  requests, cached responses) for personal/educational use. It is against
  Transfermarkt's terms of service for heavier or commercial use.

## Project layout

```
backend/
  config.py                       paths and season settings
  features.py                     feature/target definitions, train-test split
  model.py                        builds/trains the sklearn pipeline
  evaluate.py                     predicted-vs-actual and residual plots
  predict.py                      CLI to compare prediction vs actual
  sources/
    fpl_client.py                 FPL API: clubs, current season, per-player history
    transfermarkt_scraper.py      squad/value scraper (cached, rate-limited)
    names.py                      name normalisation shared by the joins
    build_dataset.py              joins the sources into one CSV
  tests/                          unit tests (no network calls)
frontend/                         not built yet
notebooks/                        exploration and experiment log (executed)
data/
  raw/                            cached API/HTML responses (gitignored)
  processed/pl_players.csv        the merged dataset (gitignored)
models/                           trained model artifacts (gitignored)
reports/figures/                  generated evaluation plots
```
