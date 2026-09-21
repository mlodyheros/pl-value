# pl-value-predictor

Predicts Premier League players' transfer market value from their on-pitch
stats, and lets you compare the model's estimate against their actual value.

- **This season** comes from the official
  [Fantasy Premier League API](https://fantasy.premierleague.com/api/bootstrap-static/)
  (free, no key, no registration): the club list, minutes and starts.
- **Past PL seasons** come from the
  [vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League)
  archive - one CSV per season instead of one API request per player, and it
  includes players who aren't in *this* season's FPL game. Unlike a top-scorers
  feed it covers defenders and keepers too.
- **Non-PL playing record** comes from [Understat](https://understat.com)
  (La Liga, Bundesliga, Serie A, Ligue 1, Russian league). A quarter of a PL
  squad has never played in the Premier League, and without this the model has
  nothing to go on for them.
- **Market values** (the prediction target), plus each player's age, position
  and nationality, are scraped from Transfermarkt's current squad pages.
- A scikit-learn **linear regression** pipeline (on log-transformed value,
  since transfer values are heavily right-skewed) is trained on the merged
  dataset. Features: age and age², this season's minutes share, the share of
  minutes played across past seasons and in the newest one alone, past-season
  goals+assists per 90 (from Premier League history where it exists, otherwise
  from other big leagues), data-coverage flags, position and club.

## Layout

```
backend/     data pipeline, model, and the HTTP API
frontend/    single-page interface, no build step
```

## Setup

```bash
pip install -r requirements.txt        # to run the pipeline and the app
pip install -r requirements-dev.txt    # to run the tests and the notebook
```

No API keys and no accounts: both sources are public.

## Usage

```bash
# 1. Build the dataset (FPL API + Transfermarkt scrape). Raw responses are
#    cached under data/raw/, so re-runs are near-instant (a cold build is well
#    under a minute). The season-to-date FPL response expires after 24h;
#    --refresh-fpl forces a refetch.
python -m backend.data.build_dataset

# 2. Train the model. Prints held-out and 5-fold CV R²/MAE/RMSE and writes
#    reports/figures/pred_vs_actual.png and models/linear_regression.joblib
python -m backend.model

# 3. Compare a player's predicted value against their actual value.
#    Every prediction comes with a measured range and a confidence tier.
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
| + past-season goals+assists **per 90** | 0.65 | €8.2m | €19.3m |
| + non-PL record as a **fallback** | 0.67 | €8.0m | €19.2m |
| + PL history from the season archive | 0.69 | €7.9m | €19.1m |
| + the newest season on its own | 0.70 | €7.4m | €16.7m |
| + what the club actually paid | 0.72 | €7.0m | €15.8m |
| + **"not playing" read properly** | **0.75** | **€6.7m** | **€14.9m** |

Four findings worth keeping in mind:

- **Playing time beats output.** How much a player plays, for which club, at what
  age explains most of the value. Past-season minutes was the single biggest gain.
- **Rates matter, totals don't.** Raw goal totals add nothing - they're largely a
  restatement of minutes played. Goals+assists *per 90* is independent of playing
  time and does help, especially for expensive forwards.
- **Recency beats the average.** Career totals average several seasons together,
  which describes a player who has just become a regular — or just lost their
  place — badly. Adding the newest completed season *on its own*, alongside the
  career figure, was the single largest gain since the FPL history went in, and
  it is the best answer found so far to the model under-asking for expensive
  players (top-decile predicted/actual 0.86 → 0.91).
- **Recent history only.** Extending the archive back to 2018 made things *worse*
  (R² 0.673 -> 0.655, MAE €8.25m -> €8.51m). Form from six years ago says little
  about today's value, and it doesn't reach the players who are missing history
  anyway - they're new, not old. `SEASONS` stays at four.
- **A month out of the side is not evidence.** Several well-known players came
  out badly under-valued — Alisson at €5.7m against a market €15m, Grealish at
  €9.7m against €20m. It looked like an age problem and was not: players aged
  31+ are *over*-predicted at the median (ratio 1.24). The cause was that
  missing the first four gameweeks was being read as a strong signal. Two
  product terms — "not playing" times career share, and times fee — tell the
  model to lean on history instead. A linear model cannot form a product of its
  own features, so it had to be built. Worth €0.24m of MAE over 100 paired
  folds, 7.5 standard errors.
- **Minutes describe a player; a fee prices them.** Every feature above describes
  what happened on the pitch, which left the model blind to an expensive signing
  who has barely played — it asked €28m for Geovany Quenda against a market €42m.
  Adding the last fee paid was the largest single gain since playing history.
  A fee is not the target leaking: it is a real transaction agreed *before* the
  valuation being predicted.
- **Fallbacks beat extra columns.** Adding the non-PL record as its own feature
  made things *worse* (top-decile MAE €18.7m -> €20.8m): it is zero for most of
  the squad, so it mostly added noise. Folding it into the same feature as the PL
  history - PL record where it exists, otherwise the non-PL one - improved
  everything, and cut error for players new to the league by ~11%.

Training weights players by √value. Plain log-value regression optimises *relative*
error, so cheap players outvote the stars; weighting lowers euro MAE overall and for
the top 10%, at some cost in log-R².

### The fitted model

```
log(1 + value) = 16.59
   + 2.45·z(age) − 3.10·z(age²)
   + 0.14·z(minutes_share)                              this season
   + 0.27·z(career_minutes_share) + 0.17·z(recent_minutes_share)
   + 0.17·z(career_gi_per90)
   + 0.04·z(has_fpl_record) + 0.06·z(has_hist_record) − 0.18·z(has_any_history)
   + position effect + club effect
```

`z(x)` is the standardised feature. Club effects run from ×2.2 (Arsenal) to ×0.6
(Hull City) against the baseline; goalkeepers sit ×0.68 against attacking
midfielders. The age term alone peaks at 21, earlier than the raw data's mid-20s,
because the minutes features already carry most of what age would otherwise say.

Two coefficients are negative on purpose. `age²` is the downward half of the
curve. `has_any_history` separates a player whose zeros mean "no data" from one
whose record exists and says they barely played — dropping it costs real accuracy
(MAE €7.35m → €7.58m), so the sign is doing a job.

`starts_share` used to be a feature and was removed: it correlated 0.98 with
minutes_share (VIF 33), which split one effect across two coefficients and left
starts with a negative sign it did not deserve. Removing it changed nothing
measurable and made the rest readable.

### The model shrinks toward the middle

It is not that the model is priced for an older market. Its estimates sum to
€13.4bn against the market's €13.2bn — it is 2% *above* the market in aggregate,
and its median player is 7% above. What it does is shrink: below €5m it asks
about 2.9× the market, above €20m about 0.89×.

That is regression to the mean, and it is the price of lower error when features
are noisy. Three corrections were tested — linear recalibration, isotonic
recalibration and Duan smearing — and every one improved calibration while making
euro error worse. So the model keeps the shrinkage and the interface explains it.

Note this is a snapshot: the target is Transfermarkt's valuation *today*, and the
dataset has no time dimension at all, so transfer-market inflation is already
inside the numbers the model learns from rather than something it has to correct.

The model still under-predicts the very top (top-10% predicted/actual ≈ 0.91) and
players with no PL history - about a quarter of the squad, flagged by `has_hist_record`.

Rejected as leakage, not as a weak feature: Transfermarkt's *peak* market value
(in the same Kaggle download) would cut MAE to €5.6m, but 39% of players have a
peak exactly equal to their current value — for four in ten the "feature" is the
answer. The same goes for that file's `market_value_in_eur`, which correlates
0.98 with the target.

Tried and rejected: random forest / gradient boosting (with matched weights the linear
model has the lowest euro error), past-season starts and xG/xA per 90 (nothing on top of
actual output), this season's xG/xA and defensive stats (still noise after 4 gameweeks),
position×stat interactions, power target transforms, boosting on residuals, Duan
smearing, and FPL price (better log-R², much worse euro error).

## The app

```bash
uvicorn backend.api:app --port 8000
```

Then open http://localhost:8000: search any player, or start from the players
the model and the market disagree about most. `backend/api.py` is the only thing
the frontend talks to, and it serves **out-of-fold** predictions - every player
is scored by a model fitted without them, because a model asked about a player it
trained on flatters itself, and "is this player overvalued?" is exactly the
question that flattery would corrupt.

See `frontend/README.md` for the interface itself.

## How confident is a prediction?

Every prediction carries a range, measured from the model's own out-of-fold
errors rather than asserted. Errors are multiplicative (the model is fitted on
log value), so the ranges are ratios:

| What backs the prediction | Players | 80% range | Label |
|---|---|---|---|
| Premier League history | 421 | ×0.38 – ×1.67 | moderate confidence |
| Other leagues only | 58 | ×0.48 – ×1.55 | moderate confidence |
| No record anywhere | 61 | ×0.25 – ×1.82 | low confidence |

```
Geovany Quenda (Chelsea, Right Winger, age 19)
  No recent history in any covered league (prediction is weak)
  Predicted value: €27,574,511
  Confidence:      low confidence - no recent playing record in any covered league
  80% range:       €6,878,685 - €50,089,935
```

The ranges are checked, not just computed: calibrating on training folds and
measuring on held-out ones, the stated 50% range contains the true value 48-52%
of the time and the stated 80% range 75-84% of the time.

Two deliberate choices:

- **There is no "high confidence" band.** Even the best-evidenced group spans
  more than a factor of four. Calling that high would misrepresent the model.
- **The two history-backed tiers share a label** although their measured spreads
  differ (×4.4 vs ×3.2). The smaller tier holds ~60 players, far too few for that
  gap to be real - splitting them would advertise precision the sample can't
  support, and would perversely rank players we know *less* about as safer.

Calibration is written to `models/confidence_calibration.json` by
`python -m backend.model`.

## Known limitations

- **Market value is always "current"**: Transfermarkt doesn't expose reliable
  historical values through the pages this project scrapes (its season filters
  affect squad membership, not the value shown), so the model predicts *today's*
  value from *recent* performance, not a value at a specific past date.
- **Transfer fees are an optional extra**: they come from a one-off Kaggle
  download rather than an API, so a fresh clone of this repo will not have them.
  The pipeline runs without it — every player is marked "fee unknown" and the
  model falls back on playing history. See `backend/sources/transfer_fees.py`.
- **Partial coverage for new arrivals**: Understat fills in players arriving from
  the big five leagues, but not Portugal, the Championship, the Eredivisie or
  anywhere else - so 61 players (~11%, €771m of market value) still have no record
  anywhere (`has_any_history` flags them). Their median error is ~56% against ~31%
  for everyone else, in both directions. This is the largest remaining gap, though
  closing it entirely would only move overall MAE by ~2%: these are mostly cheap
  players, so the cost shows up per-player rather than in the average. Until it
  closes, those players are labelled low confidence rather than given a falsely
  precise number.
- **Name matching across sources is guarded, not perfect**: an exact name match is
  trusted; anything looser must also agree on position group, because fuzzy
  matching alone paired a centre-back with a goalkeeper. The guard costs some
  coverage to avoid filing the wrong player's stats.
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
  confidence.py                   measured prediction ranges by data coverage
  api.py                          HTTP API; the only thing the frontend calls
  sources/
    fpl_client.py                 FPL API: clubs and this season's stats
    fpl_archive_client.py         past PL seasons, one CSV per season (cached)
    understat_client.py           Understat league data for non-PL seasons (cached)
    transfer_fees.py              fees paid, from an optional Kaggle download
    transfermarkt_scraper.py      squad/value scraper (cached, rate-limited)
    names.py                      name normalisation shared by the joins
    build_dataset.py              joins the sources into one CSV
  tests/                          unit tests (no network calls)
frontend/
  index.html, assets/             single page, no build step
notebooks/                        exploration and experiment log (executed)
data/
  raw/                            cached API/HTML responses (gitignored)
  processed/pl_players.csv        the merged dataset (gitignored)
models/                           trained model + calibration (gitignored)
reports/figures/                  generated evaluation plots
```
