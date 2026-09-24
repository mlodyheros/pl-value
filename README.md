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
  nothing to go on for them. Where Understat spells a name its own way, the same
  leagues come from the optional Kaggle download instead.
- **Market values** (the prediction target), plus each player's age, position
  and nationality, are scraped from Transfermarkt's current squad pages, and
  this season's signings and the fees paid for them from each club's transfers
  page.
- A scikit-learn **linear regression** pipeline (on log-transformed value,
  since transfer values are heavily right-skewed) is trained on the merged
  dataset. Features: a bending age curve, this season's minutes share, the share
  of minutes played across past seasons and in the newest one alone, past-season
  goals+assists per 90 (from Premier League history where it exists, otherwise
  from other big leagues), the last transfer fee paid and how long ago, terms
  for a player who is not featuring, terms for young and older regulars and
  for backup goalkeepers, output sustained over a career, data-coverage flags,
  position and club.

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
python -m backend.sources.build_dataset

# 2. Train the model. Prints held-out and 5-fold CV R²/MAE/RMSE and writes
#    reports/figures/pred_vs_actual.png and models/linear_regression.joblib
python -m backend.model

# 3. Compare a player's predicted value against their actual value.
#    Every prediction comes with a measured range and a confidence tier.
python -m backend.predict --player "Erling Haaland"

# ...or predict for a hypothetical player by hand
python -m backend.predict --age 24 --position "Centre-Forward" --club "Man City" \
    --minutes-share 0.9 --career-minutes-share 0.85 --career-gi-per90 0.8

# 4. Train the second model: what a club would likely pay (needs the Kaggle files).
python -m backend.fee_model

# Keep everything current: rebuilds and retrains only when a gameweek has
# finished or Transfermarkt's pages are a week old (see "Keeping it current").
python -m backend.refresh
```

`notebooks/01_model_exploration.ipynb` walks through the data, the model and
the experiment log behind the modelling choices (run the dataset build first).

## Current performance

5-fold cross-validated on ~540 players: **R² ≈ 0.83** (on log value), **MAE ≈ €5.9m**.
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
| + "not playing" read properly | 0.75 | €6.7m | €14.9m |
| + an age curve that bends | 0.76 | €6.6m | €14.6m |
| *the same, rebuilt at gameweek 5* | *0.76* | *€6.7m* | *€14.7m* |
| + this season's fees, from each club's page | 0.77 | €6.5m | €13.5m |
| + young regulars, and how old the fee is | 0.77 | €6.5m | €12.4m |
| + older regulars | 0.77 | €6.4m | €12.5m |
| + backup keepers, and output kept up over a career | 0.80 | €6.3m | €12.2m |
| + names that actually join | 0.82 | €6.1m | €11.7m |
| + Champions League minutes last season | 0.83 | €6.1m | €13.2m\* |
| + a season below a player's own level | 0.83 | €6.0m | €13.3m\* |
| + **attacking involvement, against the position** | **0.83** | **€5.9m** | **€13.1m**\* |

\* The top-10% column is the noisiest: it moves by up to ±€1.3m from one random
split to the next. Averaged over 20 splits, the Champions League term cuts overall
MAE by €0.12m and costs €0.2m among the dearest tenth - see below.

Findings worth keeping in mind:

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
- **A reader spotted what the metrics could not.** Asked to mark where the model
  was wrong, squad by squad, someone flagged 25 players across four clubs. Their
  direction matched the model's own error in 24 of them — and the group they said
  was under-valued averaged 27 years old against 23.6 for the over-valued group.
  That pointed at the age curve: a plain parabola is symmetric, and the one this
  data fits peaks at 21, so it asked too much for teenagers and too little for
  players in their prime. Two hinge terms at 23 and 29 fixed the shape
  (MAE €6.76m → €6.64m, 6 standard errors). The labels are kept in
  `backend/tests/fixtures/human_labels.csv` and checked by a test.
- **A month out of the side is not evidence.** Several well-known players came
  out badly under-valued — Grealish at €9.7m against a market €20m among them.
  (Alisson was the other example given here, wrongly: he had played every minute,
  and only looked idle because the join below missed him.) It looked like an age
  problem and was not: players aged
  31+ are *over*-predicted at the median (ratio 1.24). The cause was that
  missing the first four gameweeks was being read as a strong signal. Two
  product terms — "not playing" times career share, and times fee — tell the
  model to lean on history instead. A linear model cannot form a product of its
  own features, so it had to be built. Worth €0.24m of MAE over 100 paired
  folds, 7.5 standard errors.
- **A snapshot goes stale.** The Kaggle file was taken in June, and about 150
  players changed club after it — so the model was reading the fee from the move
  *before*: €41m for Elliot Anderson (Forest, 2024) instead of the €135m City
  paid, €9.4m for Morgan Rogers instead of €138m, and nothing at all for Ayyoub
  Bouaddi's €95m. This season's fees now come from each club's own transfers page
  (20 requests) and take precedence; how long ago a fee was paid counts too, since
  one from last summer says more than one from 2020. Top-10% MAE €14.7m → €12.4m.
- **The age curve bends differently for players who play.** A teenager who was a
  regular last season is rare and priced like it, and after 29 the decline is
  gentler for someone who has kept his place. Two products say so — (23−age)⁺ ×
  last season's minutes, and (age−29)⁺ × career minutes. Bouaddi moved from €33m
  to €72m against a market €80m (with his fee), Bruno Fernandes from €29.7m to
  €35.9m against €35m. The second term is a trade-off, taken knowingly: it lowers
  overall error (8 standard errors over 100 paired folds) but raises it slightly
  among the dearest tenth (€12.4m → €12.5m), because the age curve refits and
  young stars ease down 1–3%. It fixes the error the reader flagged most
  emphatically.
- **A quality score that is fair to everyone.** FPL's bonus points were turned
  down (below) because only PL players have them. Understat's xGChain per 90 - the
  xG of every attack a player was part of - covers the PL and the five other big
  leagues the same way, so a player from Lille is measured on the same scale as one
  from Liverpool; divided by his position group's average, since a defensive
  midfielder is not meant to be in every attack. MAE €5.96m → €5.84m (6.6 standard
  errors), the typical miss 30.9% → 28.2%, and the reader's flagged players moved
  toward his view (0.271 → 0.254 on the weighted measure): Kerkez 1.98 → 1.79 of his
  market value, Zubimendi 1.33 → 1.25. It needed its own matching - Understat writes
  "O&#039;Reilly", "Smith-Rowe" and "Mathis Cherki", and several players are just
  "Gabriel" - so a name shared by two Understat players is settled within the
  player's own club. It costs Bouaddi: his xGChain is an average defensive
  midfielder's, and once quality is measured his €95m fee no longer stands in for it.
- **A second round of labels, and a quality score that was unfair.** Re-judging
  seven players and adding three found two patterns: young players who play now
  (Kroupi, Rayan, Mainoo, Scott) and players back from an interrupted season (Isak,
  20% of minutes last season against a career 53%) were both too cheap. The second
  has a fix - the shortfall of last season below the career share, since a season
  below one's own level is more often an injury than a demotion: MAE €6.00m → €5.96m
  (6 standard errors), Isak 0.80 → 0.85 of his market value. FPL's bonus points per
  90, the one quality score covering every position, did even better on the
  aggregate (typical miss 31% → 29%) and was still turned down: it exists only for
  players with a PL record, so newcomers from abroad have no score while everyone
  they are compared with does, and Bouaddi and Barcola - both flagged as too cheap -
  fell further. The labels test caught it. Young players who play now remain the
  open problem; three features aimed at them made nothing better.
- **Last season's Champions League says what domestic minutes cannot.** Minutes
  in it (divided by 90) reached where nothing else had: Haaland from 0.82 of his
  market value to 0.91, Rice from 0.86 to 0.97, the dearest dozen from 0.96 to 1.01
  on average, and overall MAE down €0.12m (4 standard errors over 100 paired
  folds). It is not free. It redistributes value toward clubs that played in it -
  Isak, Anderson and Rogers, whose clubs did not, ease down - and among the dearest
  tenth the error is €0.2m worse on average. Adding the Europa League was no
  better, and three seasons instead of one were worse at the top.
- **Some of the worst errors were joins, not judgement.** Name normalisation
  dropped letters it could not decompose — "Gabriel Słonina" became "sonina",
  "Đorđe Petrović" became "ore petrovic" — and FPL spells eight players differently
  from Transfermarkt ("Benjamin White", "Yehor Yarmoliuk", "Dominic Solanke-Mitchell",
  "José María Andrés Baixauli", and "Alisson Becker" for plain "Alisson"...). Every
  one of them looked idle this season, and some lost their whole PL history:
  Yarmolyuk came out at €4.8m against a market €32m, Petrović at €8.5m against €28m,
  and Alisson — who had played every minute — at €3.5m against €15m. Letters are now transliterated, and a last,
  looser match runs only among the player's own club, where a surname that is
  someone's FPL short name — or a close spelling — is unambiguous. Kaggle's league
  records, named like Transfermarkt's, recover the big-league players Understat
  misspells (Gittens, Cho, Bahoya); adding the *other* leagues there made things
  worse, since a minute in Denmark is not a minute in Spain. MAE €6.36m → €6.15m
  (13 standard errors), and to €6.07m once Alisson was found too. A side effect
  worth knowing: with the mismatches gone, "not in FPL" now reliably means
  "outside the first-team squad", and the model prices it so — which would be
  wrong for an established player who is merely missing from the list, so the
  player page says so when it happens.
- **Not playing means different things in goal.** The model was asking €8.4m for
  Liverpool's third-choice keeper (market €500k) and €5.5m for Chelsea's: with no
  minutes and no fee, club and position were all it had. Outfield, that record at
  19 describes a prospect; in goal it describes a backup. One flag for a keeper who
  has played nowhere and cost nothing, plus goals+assists per 90 times career
  minutes (a regular who produces, not a cameo that scored), took the median player
  under €1m from 4.4× the market to 2.5× and lowered error overall and at the top
  (10 and 5 standard errors). Log-R² jumps to 0.80 because those cheap players were
  the model's worst relative misses.
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
log(1 + value) = 16.44
   + 1.22·z(age) − 1.64·z(age²) − 0.02·z(age−23)⁺ − 0.32·z(age−29)⁺
   + 0.12·z(minutes_share)                              this season
   + 0.03·z(career_minutes_share) + 0.25·z(recent_minutes_share)
   + 0.04·z(career share − last season's share)⁺
   + 0.12·z(career_gi_per90) + 0.05·z(career_gi_per90 × career_minutes)
   + 0.10·z(xGChain per 90 ÷ position average) + 0.06·z(has_quality_record)
   + 0.65·z(log_transfer_fee) − 0.64·z(has_transfer_fee) + 0.01·z(years_since_fee)
   − 0.22·z(idle) + 0.05·z(idle × career) + 0.18·z(idle × fee)
   + 0.06·z((23−age)⁺ × recent_minutes) + 0.08·z((age−29)⁺ × career_minutes)
   − 0.23·z(backup_keeper) + 0.09·z(champions_league_matches_last_season)
   + 0.16·z(has_fpl_record) + 0.12·z(has_hist_record) − 0.27·z(has_any_history)
   + position effect + club effect
```

`z(x)` is the standardised feature, so the coefficients compare importance. Club
effects run from ×1.6 (Arsenal) to ×0.6 (Hull City) against Bournemouth;
goalkeepers who play sit ×0.94 against attacking midfielders, and backups well
below that. The age term alone peaks at about 22, earlier than the raw data's
mid-20s, because the minutes features already carry most of what age would
otherwise say.

The same model in plain units, to compute by hand -
`value ≈ e^(12.596 + Σ coefficient × feature) × club × position`:

| Feature (unit) | Coefficient |
|---|---|
| age | +0.2884 |
| age² | −0.0072 |
| (age − 23), when positive | −0.0044 |
| (age − 29), when positive | −0.2030 |
| in this season's FPL list (0/1) | +1.1531 |
| share of this season's minutes (0–1) | +0.3085 |
| has a PL record (0/1) | +0.3029 |
| has any record (0/1) | −0.8696 |
| career share of minutes, last 4 seasons (0–1) | +0.1146 |
| goals + assists per 90 | +0.5295 |
| share of last season's minutes (0–1) | +0.7474 |
| career share minus last season's, when positive | +0.3008 |
| xGChain per 90 ÷ position-group average (GK 0.13, D 0.34, M 0.48, F 0.60) | +0.1940 |
| has an Understat record of 450+ minutes (0/1) | +0.1417 |
| has a transfer fee (0/1) | −1.7154 |
| ln(transfer fee in €) | +0.1038 |
| not playing this season (0/1) | −0.4333 |
| not playing × career share | +0.2321 |
| not playing × ln(fee) | +0.0224 |
| (23 − age), when positive, × last season's share | +0.1465 |
| (age − 29), when positive, × career share | +0.1042 |
| years since the fee | +0.0056 |
| backup keeper (0/1) | −1.4686 |
| goals + assists per 90 × career share | +0.4216 |
| Champions League matches last season (minutes ÷ 90) | +0.0323 |

Clubs: Arsenal ×1.63, Man City ×1.52, Man Utd ×1.42, Chelsea ×1.39, Liverpool ×1.32,
Aston Villa ×1.18, Nott'm Forest ×1.15, Crystal Palace ×1.10, Tottenham ×1.07,
Brighton ×1.06, Everton ×1.01, Bournemouth ×1.00, Newcastle ×0.96, Fulham ×0.95,
Brentford ×0.94, Sunderland ×0.93, Ipswich ×0.93, Coventry ×0.92, Leeds ×0.88, Hull ×0.62.
Positions: defensive midfield ×1.18, centre-back ×1.11, central midfield ×1.09,
centre-forward ×1.04, right winger ×1.04, left winger ×1.01, attacking midfield ×1.00,
left midfield ×0.95, goalkeeper ×0.94, right-back ×0.94, left-back ×0.83, right
midfield ×0.71. Worked through for Bruno Fernandes (xGChain 1.6× an average
midfielder's), the terms add to 4.352, so e^16.949 ≈ €22.9m, times ×1.42 for Man Utd:
**€32.5m**. (The app shows each player
as valued by a model fitted without them, so its figure differs slightly.)

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

The model still under-predicts the very top (top-10% predicted/actual ≈ 0.92) and
players with no PL history - about a quarter of the squad, flagged by `has_hist_record`.

The very top is the hardest place. Haaland, at €220m, is worth nearly twice anyone
else in the league and the model asks about €200m (0.91): it pulls a lone extreme toward
the rest. A premium for goals+assists per 90 above 0.5–0.7 does reach him — and
overshoots to €255–268m while making the rest of the top tenth *worse*, so it is not
used. Neither is weighting the stars more heavily, which moves him the wrong way.

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

Each figure is averaged over twenty random splits. With a single split, a
player's value depended on which others happened to share his fold, and moved by
about 6% from one split to the next - Haaland anywhere between €181m and €230m.
Averaged, the typical movement is about 1%, and it costs well under a second.

See `frontend/README.md` for the interface itself.

## How confident is a prediction?

Every prediction carries a range, measured from the model's own out-of-fold
errors rather than asserted. Errors are multiplicative (the model is fitted on
log value), so the ranges are ratios:

| What backs the prediction | Players | 80% range | Label |
|---|---|---|---|
| Premier League history | 424 | ×0.55 – ×1.50 | moderate confidence |
| Other leagues only | 60 | ×0.47 – ×1.63 | moderate confidence |
| No record anywhere | 56 | ×0.30 – ×1.80 | low confidence |

```
Geovany Quenda (Chelsea, Right Winger, age 19)
  No recent history in any covered league (prediction is weak)
  Predicted value: €31,509,526
  Confidence:      low confidence - no recent playing record in any covered league
  80% range:       €9,322,271 - €56,577,473
```

The ranges are checked, not just computed: calibrating on training folds and
measuring on held-out ones, the stated 50% range contains the true value 48-51%
of the time and the stated 80% range 79-80% of the time.

Two deliberate choices:

- **There is no "high confidence" band.** Even the best-evidenced group spans
  nearly a factor of three. Calling that high would misrepresent the model.
- **The two history-backed tiers share a label** although their measured spreads
  differ (×2.8 and ×3.3). The smaller tier holds ~60 players, far too few for that
  gap to be trusted - splitting them would advertise precision the sample can't
  support.

Calibration is written to `models/confidence_calibration.json` by
`python -m backend.model`.

## A second model: what a club would pay

The value model predicts Transfermarkt's valuation. `backend/fee_model.py`
answers a different question - what a buying club would actually pay - and learns
it from ~5,600 paid transfers since mid-2019 (players worth €2m+), each carrying
the fee and the player's market value on the day. Fees follow the market's figure
closely, but not one-for-one:

| On the day of the transfer | Typical fee ÷ market value |
|---|---|
| bought by a Premier League club | ×1.25 |
| sold by a PL club abroad | ×0.94 |
| player aged 20 or under | ×1.54 |
| 23–26 / 26–29 / 29–32 | ×0.78 / ×0.62 / ×0.53 |

A linear model on log fee (market value, age curve, position, PL buyer and seller,
year) beats "fee = market value" where it matters here: on sales by PL clubs of
players worth €5m+, the typical miss is ×1.39 against ×1.43, and on sales to another
PL club ×1.27 against ×1.43 - where the market value alone runs about 20% low.

The player page shows two figures, a PL buyer and a buyer abroad. Fees are noisy -
8 in 10 land between ×0.4 and ×2.1 of the estimate - and the model cannot see
contracts, which move a fee most after age; the page says so when a contract has
little over a year left.

## Keeping it current

`python -m backend.refresh` checks whether a gameweek has finished since the last
build, or Transfermarkt's squad pages are more than a week old (they are
refetched weekly now; club search pages are kept for good). If so it rebuilds the
dataset and retrains both models; if not it does nothing. The API notices a
rebuilt dataset on its next request, so the server does not need restarting.

```bash
./scripts/install_refresh_schedule.sh     # run it daily at 07:00 (macOS launchd)
./scripts/uninstall_refresh_schedule.sh   # and stop
```

On macOS, background jobs cannot read the Desktop, Documents or Downloads folders.
If the project lives in one of them, the job fails with "Operation not permitted"
(see `data/refresh.log`) until either the project moves elsewhere (recreate
`.venv` after moving it) or the Python that `.venv` points to is given Full Disk
Access in System Settings → Privacy & Security.

## What is left, and why

The interface audit that produced most of this section is worked through. Three
items were closed by measurement rather than by code, and they are the honest
edges of the project:

- **Players with nothing on record.** 22 of 540 have no playing history *and* no
  transfer fee. Their median error is 46% against 26% for everyone else. Most are
  Championship players at the promoted clubs - van Ewijk and Rudoni at Coventry,
  Egeli at Ipswich - and no source we can reach covers the Championship: FBref
  blocks automated access, and Transfermarkt's player pages need a browser.
- **Form that a reader can see.** Kerkez sits at twice his market value: young, a
  regular at Liverpool, bought for €47m a year ago - and, by the market's reading, out
  of form. Nothing in the numbers here measures form, and the one quality score
  available (FPL bonus points) could not be used fairly (above).
- **Shrinkage toward the middle** was corrected three ways (linear recalibration,
  isotonic, Duan smearing) and every one made euro error worse. It is the price of
  lower error with noisy features, so the interface explains it instead.
- **Historical valuations do not help.** ~9,800 valuations exist for these players
  over twenty years. Trained on all of it and tested on 2026: MAE €9.48m. Trained
  on 2025 alone: €8.92m. Old valuations teach the wrong relationship. Volume does
  help at constant recency (540 random rows give €10.98m), so it is the age of the
  data that hurts, not the amount.

## Known limitations

- **Market value is always "current"**: Transfermarkt doesn't expose reliable
  historical values through the pages this project scrapes (its season filters
  affect squad membership, not the value shown), so the model predicts *today's*
  value from *recent* performance, not a value at a specific past date.
- **Non-PL season length is approximated**: minutes available in a foreign league
  come from the longest season any player in it played, rather than the fixture
  list, because league lengths differ (34 vs 38 matches) and this needs no
  hard-coding per competition.
- **Transfer fees are partly an optional extra**: fees before this season come
  from a one-off Kaggle download rather than an API, so a fresh clone of this repo
  will not have them. The pipeline runs without it — those players are marked
  "fee unknown" and the model falls back on playing history. This season's fees
  are scraped with the squads and are always there. See
  `backend/sources/transfer_fees.py`.
- **Transfermarkt pages refresh weekly**: squad and transfer pages are refetched
  once they are a week old, and a failed refetch falls back to the cached copy
  with a warning. A player's valuation can therefore lag Transfermarkt's own by up
  to a week.
- **Partial coverage for new arrivals**: Understat (and Kaggle, for the names it
  misses) fills in players arriving from the big five leagues, but not Portugal,
  the Championship, the Eredivisie or anywhere else - so 56 players (~10%, €683m of
  market value) still have no record anywhere (`has_any_history` flags them). Their
  median error is ~45% against ~25% for everyone else, in both directions. Kaggle
  does hold those other leagues, but counted like the big five they made the model
  worse, and with a "weaker league" flag they were no better than leaving them out. This is the largest remaining gap, though
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
  fee_model.py                    the second model: likely transfer fee
  refresh.py                      rebuild + retrain when a gameweek has finished
  api.py                          HTTP API; the only thing the frontend calls
  sources/
    fpl_client.py                 FPL API: clubs and this season's stats
    fpl_archive_client.py         past PL seasons, one CSV per season (cached)
    understat_client.py           Understat league data: non-PL seasons, and xGChain for all (cached)
    transfer_fees.py              fees paid, from an optional Kaggle download
    kaggle_appearances.py         big-league minutes Understat's spelling misses (optional)
    transfermarkt_scraper.py      squad/value scraper (cached, rate-limited)
    names.py                      name normalisation shared by the joins
    build_dataset.py              joins the sources into one CSV
  tests/                          unit tests (no network calls)
scripts/                          install/remove the daily refresh (macOS)
frontend/
  index.html, assets/             single page, no build step (light + dark)
notebooks/                        exploration and experiment log (executed)
data/
  raw/                            cached API/HTML responses (gitignored)
  processed/pl_players.csv        the merged dataset (gitignored)
models/                           trained model + calibration (gitignored)
reports/figures/                  generated evaluation plots
```
