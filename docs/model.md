# How the value model works

[← Back to the README](../README.md) · [Data reference](data.md)

The README gives the overview. This page has the detail: every feature, the
fitted equation you can compute by hand, how each piece earned its place, where
the model is weak, and what was tried and turned down.

- [In one paragraph](#in-one-paragraph)
- [Features](#features)
- [Training and scoring](#training-and-scoring)
- [The fitted model](#the-fitted-model)
- [How each feature earned its place](#how-each-feature-earned-its-place)
- [Where the model is weak](#where-the-model-is-weak)
- [How confident is a prediction?](#how-confident-is-a-prediction)
- [The fee model](#the-fee-model)
- [Checked against a reader](#checked-against-a-reader)
- [Tried and rejected](#tried-and-rejected)
- [What is left](#what-is-left)

## In one paragraph

A linear regression predicts log(1 + Transfermarkt market value) from 25 numeric
features and two categories (position and club), with each player weighted by
√value. Playing time explains most of a player's value, followed by the price a
club last paid, output per 90 minutes, age, and the club itself. Every figure the
site shows is out-of-fold, averaged over 20 random splits, and comes with a range
measured from the model's own errors among players with the same kind of evidence
behind them.

## Features

All are built in [`backend/features.py`](../backend/features.py), whose docstring
records what each one was worth when it was added.

| Feature | What it is |
|---|---|
| `age`, `age_squared` | age in years, and its square: value rises and then falls |
| `age_past_23`, `age_past_29` | years past 23 and past 29 (zero before), so the curve can bend instead of being a symmetric parabola |
| `has_fpl_record` | the player is in this season's FPL list; missing from it almost always means outside the first-team squad |
| `minutes_share` | this season's minutes ÷ the minutes available so far |
| `career_minutes_share` | share of available minutes played over the last four completed seasons: PL record where there is one, otherwise the other big leagues |
| `recent_minutes_share` | the same share for the newest completed season alone |
| `below_career` | how far last season's share fell short of the career share (zero if it did not): an interrupted season, not a new level |
| `career_gi_per90` | goals + assists per 90 over the same seasons (zero below 450 minutes) |
| `gi_x_career` | goals + assists per 90 × career share: a regular who produces, not a cameo that scored |
| `xgchain_vs_position` | Understat's xGChain per 90 ÷ the average for the position group (GK 0.13, D 0.34, M 0.48, F 0.60) |
| `has_quality_record` | Understat has 450+ minutes for the player, which separates "no data" from "low" |
| `cl_matches_last` | Champions League minutes last season ÷ 90 |
| `has_transfer_fee`, `log_transfer_fee` | whether a fee is known, and its natural log |
| `years_since_fee` | how long ago that fee was paid |
| `idle_this_season` | under one match's worth of minutes this season |
| `idle_x_career`, `idle_x_fee` | idle × career share, and idle × log fee: when someone is not playing, lean on what he has done and what he cost |
| `youth_x_recent` | years short of 23 × last season's share: a teenage regular is rare and priced like it |
| `older_x_career` | years past 29 × career share: the decline is gentler for someone who kept his place |
| `backup_keeper` | a goalkeeper who has played nowhere and cost nothing: a third choice, not a prospect |
| `has_hist_record` | the player has PL minutes in the last four seasons |
| `has_any_history` | the player has a record in the PL or another covered league |
| `position`, `club` | one-hot: 12 positions, 20 clubs |

## Training and scoring

- **Target.** log(1 + market value). Values run from €50k to €220m, and the
  errors are proportional, so the log scale is the natural one.
- **Pipeline.** Standardise the numeric features, one-hot encode position and
  club, then fit a linear regression (scikit-learn).
- **Weights.** Each player counts √value times. A plain log-value regression
  optimises *relative* error, so the many cheap players outvote the few stars.
  The weights lower the euro error, overall and for the top 10%, at some cost in
  log-R².
- **Out-of-fold.** The site never shows a player a figure from a model that
  trained on him. Each player is predicted by the four-fifths of a 5-fold split
  that left him out.
- **Averaged over 20 splits.** With a single split, a player's figure depended
  on which other players happened to share his fold. A typical player moved by
  about 6% from one split to the next, and Haaland anywhere between €181m and
  €230m. The site averages 20 splits in log space, which brings the typical
  movement down to about 1% (Haaland €196–207m) and takes well under a second.

## The fitted model

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
effects run from ×1.6 (Arsenal) to ×0.6 (Hull City) against Bournemouth.
Goalkeepers who play sit at ×0.94 against attacking midfielders, and backups
well below that. The age term alone peaks at about 22, earlier than the raw
data's mid-20s, because the minutes features already carry most of what age would
otherwise say.

The same model in plain units, to compute by hand:
`value ≈ e^(12.596 + Σ coefficient × feature) × club × position`

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

**Clubs:** Arsenal ×1.63, Man City ×1.52, Man Utd ×1.42, Chelsea ×1.39,
Liverpool ×1.32, Aston Villa ×1.18, Nott'm Forest ×1.15, Crystal Palace ×1.10,
Tottenham ×1.07, Brighton ×1.06, Everton ×1.01, Bournemouth ×1.00, Newcastle
×0.96, Fulham ×0.95, Brentford ×0.94, Sunderland ×0.93, Ipswich ×0.93, Coventry
×0.92, Leeds ×0.88, Hull ×0.62.

**Positions:** defensive midfield ×1.18, centre-back ×1.11, central midfield
×1.09, centre-forward ×1.04, right winger ×1.04, left winger ×1.01, attacking
midfield ×1.00, left midfield ×0.95, goalkeeper ×0.94, right-back ×0.94,
left-back ×0.83, right midfield ×0.71.

**Worked example.** For Bruno Fernandes (xGChain 1.6× an average
midfielder's), the terms add up to 4.352, so e^16.949 ≈ €22.9m, times ×1.42 for
Man Utd: **€32.5m**. The site shows each player as valued by models fitted
without him, so its figure (€31.8m) differs slightly.

Two coefficients are negative on purpose. `age²` is the downward half of the
curve. `has_any_history` separates a player whose zeros mean "no data" from one
whose record exists and says he barely played. Dropping it costs real accuracy
(MAE €7.35m → €7.58m), so the sign is doing a job.

`starts_share` used to be a feature and was removed. It correlated 0.98 with
`minutes_share` (VIF 33), which split one effect across two coefficients and
left starts with a negative sign it did not deserve. Removing it changed nothing
measurable and made the rest readable.

## How each feature earned its place

Each row adds to the one above, 5-fold cross-validated on about 540 players:

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
MAE by €0.12m and costs €0.2m among the dearest tenth (see below).

Every change is judged over 100 paired folds (the same splits with and without
it) and reported in standard errors, because on 540 players a single split
swings R² by about 0.1.

What was learned along the way:

- **Playing time beats output.** How much a player plays, for which club, at
  what age explains most of the value. Past-season minutes was the single
  biggest gain.
- **Rates matter, totals don't.** Raw goal totals add nothing, because they are
  largely a restatement of minutes played. Goals+assists *per 90* is
  independent of playing time and does help, especially for expensive forwards.
- **Recency beats the average.** Career totals average several seasons
  together, which describes a player who has just become a regular, or just lost
  his place, badly. Adding the newest completed season *on its own*, alongside
  the career figure, was the largest gain since the FPL history went in, and it
  is the best answer found to the model under-asking for expensive players
  (top-decile predicted/actual 0.86 → 0.91).
- **Recent history only.** Extending the archive back to 2018 made things
  *worse* (R² 0.673 → 0.655, MAE €8.25m → €8.51m). Form from six years ago says
  little about today's value, and it does not reach the players who are missing
  history anyway: they are new, not old. `SEASONS` stays at four.
- **A reader spotted what the metrics could not.** Asked to mark where the model
  was wrong, squad by squad, someone flagged 25 players across four clubs. Their
  direction matched the model's own error in 24 of them, and the group they said
  was under-valued averaged 27 years old against 23.6 for the over-valued group.
  That pointed at the age curve. A plain parabola is symmetric, and the one this
  data fits peaks at 21, so it asked too much for teenagers and too little for
  players in their prime. Two hinge terms at 23 and 29 fixed the shape (MAE
  €6.76m → €6.64m, 6 standard errors).
- **A month out of the side is not evidence.** Several well-known players came
  out badly under-valued, Grealish at €9.7m against a market €20m among them.
  It looked like an age problem and was not: players aged 31+ are
  *over*-predicted at the median (ratio 1.24). The cause was that missing the
  first four gameweeks was being read as a strong signal. Two product terms,
  "not playing" × career share and × fee, tell the model to lean on history
  instead. A linear model cannot form a product of its own features, so it had
  to be built. Worth €0.24m of MAE over 100 paired folds, 7.5 standard errors.
- **A snapshot goes stale.** The Kaggle file was taken in June, and about 150
  players changed club after it, so the model was reading the fee from the move
  *before*: €41m for Elliot Anderson (Forest, 2024) instead of the €135m City
  paid, €9.4m for Morgan Rogers instead of €138m, and nothing at all for Ayyoub
  Bouaddi's €95m. This season's fees now come from each club's own transfers
  page (20 requests) and take precedence. How long ago a fee was paid counts
  too, since one from last summer says more than one from 2020. Top-10% MAE
  €14.7m → €12.4m.
- **The age curve bends differently for players who play.** A teenager who was
  a regular last season is rare and priced like it, and after 29 the decline is
  gentler for someone who has kept his place. Two products say so: (23−age)⁺ ×
  last season's minutes, and (age−29)⁺ × career minutes. Bouaddi moved from
  €33m to €72m against a market €80m (with his fee), Bruno Fernandes from
  €29.7m to €35.9m against €35m. The second term is a trade-off, taken
  knowingly: it lowers overall error (8 standard errors over 100 paired folds)
  but raises it slightly among the dearest tenth (€12.4m → €12.5m), because the
  age curve refits and young stars ease down 1–3%. It fixes the error the reader
  flagged most emphatically.
- **Not playing means different things in goal.** The model was asking €8.4m
  for Liverpool's third-choice keeper (market €500k) and €5.5m for Chelsea's:
  with no minutes and no fee, club and position were all it had. Outfield, that
  record at 19 describes a prospect; in goal it describes a backup. One flag for
  a keeper who has played nowhere and cost nothing, plus goals+assists per 90 ×
  career minutes, took the median player under €1m from 4.4× the market to 2.5×
  and lowered error overall and at the top (10 and 5 standard errors).
- **Some of the worst errors were joins, not judgement.** Name normalisation
  dropped letters it could not decompose ("Gabriel Słonina" became "sonina",
  "Đorđe Petrović" became "ore petrovic"), and FPL spells eight players
  differently from Transfermarkt ("Benjamin White", "Yehor Yarmoliuk", "Alisson
  Becker" for plain "Alisson", …). Every one of them looked idle this season, and
  some lost their whole PL history: Yarmolyuk came out at €4.8m against a market
  €32m, and Alisson, who had played every minute, at €3.5m against €15m. Letters
  are now transliterated, and a last, looser match runs only among the player's
  own club. MAE €6.36m → €6.07m (13 standard errors).
- **Last season's Champions League says what domestic minutes cannot.** Minutes
  in it (÷ 90) reached where nothing else had: Haaland from 0.82 of his market
  value to 0.91, Rice from 0.86 to 0.97, the dearest dozen from 0.96 to 1.01 on
  average, and overall MAE down €0.12m (4 standard errors over 100 paired
  folds). It is not free. It redistributes value toward clubs that played in it
  (Isak, Anderson and Rogers, whose clubs did not, ease down), and among the
  dearest tenth the error is €0.2m worse on average. Adding the Europa League
  was no better, and three seasons instead of one were worse at the top.
- **A second round of labels, and a quality score that was unfair.** Re-judging
  seven players and adding three found two patterns. Young players who play now
  (Kroupi, Rayan, Mainoo, Scott) and players back from an interrupted season
  (Isak: 20% of minutes last season against a career 53%) were both too cheap.
  The second has a fix, the shortfall of last season below the career share,
  since a season below one's own level is more often an injury than a demotion:
  MAE €6.00m → €5.96m (6 standard errors), Isak 0.80 → 0.85 of his market value.
  FPL's bonus points per 90 did even better on the aggregate (typical miss
  31% → 29%) and was still turned down. It exists only for players with a PL
  record, so newcomers from abroad have no score while everyone they are
  compared with does, and Bouaddi and Barcola, both flagged as too cheap, fell
  further. The labels test caught it.
- **A quality score that is fair to everyone.** Understat's xGChain per 90, the
  xG of every attack a player was part of, covers the PL and the five other big
  leagues the same way, so a player from Lille is measured on the same scale as
  one from Liverpool. It is divided by the position group's average, since a
  defensive midfielder is not meant to be in every attack. MAE €5.96m → €5.84m
  (6.6 standard errors), typical miss 30.9% → 28.2%, and the reader's flagged
  players moved toward his view: Kerkez 1.98 → 1.79 of his market value,
  Zubimendi 1.33 → 1.25. It needed its own matching, because Understat writes
  "O&#039;Reilly", "Smith-Rowe" and "Mathis Cherki", and several players are
  just "Gabriel".
- **Minutes describe a player; a fee prices him.** Every feature above
  describes what happened on the pitch, which left the model blind to an
  expensive signing who has barely played: it asked €28m for Geovany Quenda
  against a market €42m. Adding the last fee paid was the largest single gain
  since playing history. A fee is not the target leaking. It is a real
  transaction, agreed *before* the valuation being predicted.
- **Fallbacks beat extra columns.** Adding the non-PL record as its own feature
  made things *worse* (top-decile MAE €18.7m → €20.8m): it is zero for most of
  the squad, so it mostly added noise. Folding it into the same feature as the
  PL history (the PL record where it exists, otherwise the non-PL one) improved
  everything, and cut error for players new to the league by about 11%.

## Where the model is weak

**It shrinks toward the middle.** It is not priced for an older market: its
estimates sum to €13.15bn against the market's €13.16bn, level in aggregate, and
its median player is 4% above. What it does is shrink. Below €5m it asks a median
1.7× the market, above €20m 0.95×. That is regression to the mean, the price of
lower error when features are noisy. Three corrections were tested (linear
recalibration, isotonic recalibration and Duan smearing), and every one improved
calibration while making euro error worse. So the model keeps the shrinkage and
the interface explains it.

**The very top is the hardest place.** Haaland, at €220m, is worth nearly twice
anyone else in the league, and the model asks €200m (0.91): it pulls a lone
extreme toward the rest. The dearest tenth average 0.91 of their market value.
A premium for goals+assists per 90 above 0.5–0.7 does reach Haaland, but it
overshoots to €255–268m while making the rest of the top tenth *worse*, so it is
not used. Neither is weighting the stars more heavily, which moves him the wrong
way.

**Players with no record anywhere.** 56 players (€683m of market value) have
no record in any covered league. For them the typical miss is 48%, against 27%
for everyone else, in both directions. For the 22 who also have no known fee it
is 68%. They are labelled low confidence and given the widest range.

**It is a snapshot.** The target is Transfermarkt's valuation *today*, and the
dataset has no time dimension. Transfer-market inflation is therefore already
inside the numbers the model learns from, not something it has to correct.

## How confident is a prediction?

Every prediction carries a range measured from the model's own out-of-fold
errors, not asserted. Errors are multiplicative (the model is fitted on log
value), so the ranges are ratios:

| What backs the prediction | Players | 80% range | Label |
|---|---|---|---|
| Premier League history | 424 | ×0.55 – ×1.50 | moderate confidence |
| Other leagues only | 60 | ×0.47 – ×1.63 | moderate confidence |
| No record anywhere | 56 | ×0.30 – ×1.80 | low confidence |

```
Geovany Quenda (Chelsea, Right Winger, age 19)
  This season (FPL): 27 minutes, 0 starts
  No recent history in any covered league (prediction is weak)
  Actual value:    €42,000,000
  Predicted value: €28,557,405  (-32.0% vs actual)
  Confidence:      low confidence - no recent playing record in any covered league
  80% range:       €8,448,869 - €51,276,742
```

The ranges are checked, not just computed. Calibrated on training folds and
measured on held-out ones, the stated 50% range contains the true value 48–51% of
the time and the stated 80% range 79–80% of the time. On the site, the market's
figure falls inside the 80% range for 430 of 540 players.

Two deliberate choices:

- **There is no "high confidence" band.** Even the best-evidenced group spans
  nearly a factor of three. Calling that high would misrepresent the model.
- **The two history-backed tiers share a label**, although their measured
  spreads differ. The smaller tier holds about 60 players, far too few for that
  gap to be trusted. Splitting them would advertise a precision the sample
  cannot support.

The ranges are written to `models/confidence_calibration.json` by
`python -m backend.model`, from the same averaged out-of-fold estimates the site
shows.

## The fee model

The value model predicts Transfermarkt's valuation.
[`backend/fee_model.py`](../backend/fee_model.py) answers a different question,
what a buying club would actually pay. It learns from 5,614 paid transfers since
July 2019 (players worth €2m+), each carrying the fee and the player's market
value on the day. Fees follow the market's figure closely, but not one-for-one:

| On the day of the transfer | Typical fee ÷ market value |
|---|---|
| bought by a Premier League club | ×1.25 |
| sold by a PL club abroad | ×0.94 |
| player aged 20 or under | ×1.54 |
| aged 23–26 / 26–29 / 29–32 | ×0.78 / ×0.62 / ×0.53 |

A linear model on log fee (market value, age curve, position, PL buyer and
seller, year) beats "fee = market value" where it matters here:
- On sales by PL clubs of players worth €5m+, the typical miss is ×1.39
  against ×1.43.
- On sales to another PL club it is ×1.27 against ×1.43. There the market value
  alone runs about 20% low.

The player page shows two figures, one for a PL buyer and one for a buyer
abroad. Fees are noisy: 8 in 10 land between ×0.43 and ×2.14 of the estimate. The
model also cannot see contracts, which move a fee most after age, so the page
says so when a contract has little over a year left.

## Checked against a reader

[`backend/tests/fixtures/human_labels.csv`](../backend/tests/fixtures/human_labels.csv)
holds one reader's judgement of where the model is wrong, given squad by squad:
28 players at Arsenal, Man Utd, Liverpool, Man City and Bournemouth, over two
rounds.

```
name,club,direction,strength
```

`direction` is `under` (the model asks too little) or `over` (too much), and
`strength` runs from 1 (slight) to 3 (emphatic). These are opinions, not ground
truth, and at least one disagrees with Transfermarkt rather than with the model.
So [the test](../backend/tests/test_human_labels.py) asserts a floor rather than
perfection: at least 80% of the flagged players must still err in the direction
reported, and the two groups must stay clearly apart. It is there to catch a
change that quietly reverses what a reader already saw. Today 82% agree.

To add a round, append rows to the file and run `pytest backend/tests/test_human_labels.py`.

## Tried and rejected

- **Random forest and gradient boosting.** With matched weights, the linear
  model has the lowest euro error.
- **Past-season starts, and xG/xA per 90.** Nothing on top of actual output.
- **This season's xG/xA and defensive stats.** Still noise after four
  gameweeks.
- **Position × stat interactions, power transforms of the target, boosting on
  residuals, Duan smearing.** None helped.
- **FPL price.** Better log-R², much worse euro error.
- **Transfermarkt's peak market value**, rejected as leakage rather than as a
  weak feature. It would cut MAE to €5.6m, but 39% of players have a peak
  exactly equal to their current value, so for four in ten the "feature" is the
  answer. The same goes for the Kaggle file's `market_value_in_eur`, which
  correlates 0.98 with the target.
- **Historical valuations as training data.** About 9,800 valuations exist for
  these players over twenty years. Trained on all of them and tested on 2026:
  MAE €9.48m. Trained on 2025 alone: €8.92m. Old valuations teach the wrong
  relationship. Volume does help at constant recency (540 random rows give
  €10.98m), so it is the age of the data that hurts, not the amount.
- **Other leagues from Kaggle counted like the big five.** A minute in Denmark
  is not a minute in Spain: MAE 1.5 standard errors worse, and with a "weaker
  league" flag no better than leaving them out.
- **FPL bonus points per 90 as a quality score.** Unfair to newcomers from
  abroad (see above).

## What is left

- **Players with nothing on record.** 22 of 540 have no playing history *and*
  no transfer fee. Most are Championship players at the promoted clubs (van
  Ewijk and Rudoni at Coventry, Egeli at Ipswich), and no source the pipeline can
  reach covers the Championship. FBref blocks automated access, and
  Transfermarkt's player pages need a browser.
- **Form that a reader can see.** Kerkez sits well above his market value:
  young, a regular at Liverpool, bought for €47m a year ago, and by the market's
  reading out of form. Nothing in the numbers here measures form, and the one
  quality score that might have (FPL bonus points) could not be used fairly.
- **Young players who play now.** Kroupi, Rayan, Mainoo and Scott were flagged
  as too cheap. Three features aimed at them made nothing better.
- **Shrinkage toward the middle** was corrected three ways, and every one made
  euro error worse. The interface explains it instead.
