# The data

[← Back to the README](../README.md) · [Model notes](model.md)

Where the numbers come from, how they are matched to each other, what every
column of the dataset means, and how it all stays current.

- [Where everything lives](#where-everything-lives)
- [The sources](#the-sources)
- [How the sources are joined](#how-the-sources-are-joined)
- [The dataset, column by column](#the-dataset-column-by-column)
- [Trained models](#trained-models)
- [Keeping it current](#keeping-it-current)
- [Known gaps](#known-gaps)

## Where everything lives

There is no database server. The pipeline writes plain files and the API reads
them. None of them are in git; they are built on your machine by
`python -m backend.sources.build_dataset` and `python -m backend.model`.

```
data/
  raw/                              every response exactly as fetched
    fpl/bootstrap_static.json       this season, from the FPL API
    fpl_archive/players_raw_<season>.csv   one per past PL season
    understat/<League>_<season>.json       one per league and season
    transfermarkt/
      squad_<club id>.html          squads and market values
      transfers_<club id>_<season>.html    this season's arrivals and fees
      search_<club>.html, club_ids.json    how each club's page was found
    kaggle/                         the optional CSVs you download yourself
  processed/
    pl_players.csv                  the dataset: one row per player
models/
  linear_regression.joblib          the value model
  confidence_calibration.json       the 50% and 80% ranges for each evidence tier
  fee_model.joblib                  the fee model
  fee_calibration.json              its 80% range and accuracy
reports/figures/pred_vs_actual.png  predicted against actual, redrawn on each training run (not in git)
```

Deleting `data/raw/` forces a full refetch. Deleting `data/processed/` or
`models/` only means rebuilding them from the cache, which takes seconds.

## The sources

### Fantasy Premier League API (required)

`https://fantasy.premierleague.com/api/bootstrap-static/`, public and keyless.
It provides:
- the list of the 20 clubs, so the pipeline needs no other club list
- each player's minutes, starts, xG, xA and defensive contribution this season
- how many gameweeks have finished

The numbers are season-to-date, so the cached copy is refetched once it is 24
hours old (`--refresh-fpl` forces it). Code:
[`fpl_client.py`](../backend/sources/fpl_client.py).

### FPL season archive (required)

[vaastav/Fantasy-Premier-League](https://github.com/vaastav/Fantasy-Premier-League)
keeps a CSV per season of what the FPL API said at the end of it. The pipeline
reads the four most recent completed seasons (`SEASONS` in
[`config.py`](../backend/config.py): 2022/23 to 2025/26). This covers minutes,
starts, goals, assists, xG, xA and bonus points. It is one request per season
instead of one per player, and it includes players who are not in this season's
FPL game. Completed seasons do not change, so each file is fetched once. Code:
[`fpl_archive_client.py`](../backend/sources/fpl_archive_client.py).

### Understat (required)

[Understat](https://understat.com) provides two things:
- **A record before the Premier League:** minutes, goals, assists and xG in La
  Liga, the Bundesliga, Serie A, Ligue 1 and the Russian league. A quarter of
  every squad has never played in the Premier League, and without this the model
  has nothing to go on for them.
- **The quality measure:** xGChain in those leagues and the Premier League. That
  is the xG of every attack a player took part in, measured the same way in
  every league.

One page per league and season, one second apart, each kept for good. Code:
[`understat_client.py`](../backend/sources/understat_client.py).

### Transfermarkt (required)

Transfermarkt's public squad pages give every current squad with each player's
**market value** (the number the model predicts), age, position, nationality and
contract. Each club's transfers page gives this season's arrivals and the fees
paid. The pages are read politely, one request every 2.5 seconds with a browser
user agent. Squad and transfer pages are refetched once they are a week old, and
if a refetch fails, the cached copy is used with a warning. Code:
[`transfermarkt_scraper.py`](../backend/sources/transfermarkt_scraper.py).

### Kaggle: Transfermarkt datasets (optional)

The [player-scores dataset](https://www.kaggle.com/datasets/davidcariboo/player-scores)
is a free download, and the pipeline runs without it. Put these files in
`data/raw/kaggle/`:

| File | Used for |
|---|---|
| `players.csv` | names and dates of birth, to confirm a match by age |
| `transfers.csv` | fees paid before this season; the 5,614 transfers the fee model learns from |
| `player_valuations.csv` | which league each club plays in, for the fee model |
| `appearances.csv` | Champions League minutes, and league minutes where Understat spells a name differently |
| `competitions.csv` | how long a season is in each league |

Without them:
- players' earlier fees are unknown, and the model leans on playing history
  instead
- nobody has Champions League minutes
- there is no fee estimate on player pages

This season's fees still come from Transfermarkt directly. Code:
[`transfer_fees.py`](../backend/sources/transfer_fees.py),
[`kaggle_appearances.py`](../backend/sources/kaggle_appearances.py).

## How the sources are joined

Transfermarkt's squad list is the spine: one row per player in a current squad.
Everything else is attached to it by name, and names are where joins go wrong.

**Normalising.** Names are lower-cased, stripped of accents and transliterated,
because some letters have no accent to strip: Ł → l, Đ → dj, Ø → o, ß → ss.
Without transliteration, "Gabriel Słonina" became "sonina" and "Đorđe Petrović"
became "ore petrovic". Code: [`names.py`](../backend/sources/names.py).

**FPL (this season).** Tried in order, stopping at the first that finds exactly
one player:
1. the full name
2. FPL's short name, when no other player has it (Transfermarkt's "Gabriel")
3. a unique superset of the name's words (Transfermarkt's "David Raya", FPL's
   "David Raya Martin")
4. a close spelling
5. a last, looser rule **only among the player's own club**, where a surname,
   a first name or a near spelling is unambiguous: "Ben White" → "Benjamin
   White", "Alisson" → "Alisson Becker", "Dominic Solanke" → "Dominic
   Solanke-Mitchell"

11 of 540 players are not in this season's FPL list. For almost everyone that
means outside the first-team squad, and the model reads it so.

**FPL archive (past seasons).** Joined on FPL's player code, which is stable
across seasons, so it is exact. Players missing from this season's game fall
back to their name. Anything looser than an exact name must also agree on
position group, so a keeper's career is never filed under a defender.

**Understat.** An exact name is trusted. Anything looser must agree on position
group. Without that, the fuzzy matcher paired centre-back "Antonio Silva" with
goalkeeper "Antonio Sivera". For the quality measure, records are grouped by
Understat's own id, since a name can belong to two players. A name several
players share ("Gabriel"), or one Understat writes differently ("Mathis Cherki"),
is settled within the player's own club, using only the seasons he spent there.

**Kaggle.** Matched by name, then confirmed by date of birth: the ages must agree
within 1.2 years, because surnames repeat across tens of thousands of players.

**Transfer fees.** A fee paid this season, from the club's own transfers page,
wins over the Kaggle snapshot. The snapshot was taken before the summer window
and would otherwise give a player's *previous* fee: €41m for Elliot Anderson
instead of the €135m City paid.

## The dataset, column by column

`data/processed/pl_players.csv` has 540 rows, one per player in a current
Premier League squad, and 46 columns. Players without a Transfermarkt value, age
or position are dropped. Zeros mean "none on record" unless a `has_…` flag says
the record is missing altogether.

**Who the player is.** All from Transfermarkt:

| Column | Meaning |
|---|---|
| `name` | as Transfermarkt writes it |
| `position` | one of 12, e.g. `Centre-Forward`, `Defensive Midfield`, `Goalkeeper` |
| `age` | in years, on the day of the build |
| `nationality` | first nationality listed |
| `club` | Transfermarkt's club name |
| `market_value_eur` | **the target**: Transfermarkt's current valuation, in euros |
| `contract_expiry` | end of the current contract (missing for 27 players) |
| `fpl_team`, `club_code` | the club's FPL name and three-letter code |

**This season.** From the FPL API:

| Column | Meaning |
|---|---|
| `fpl_minutes`, `fpl_starts` | minutes and starts so far |
| `fpl_xg`, `fpl_xa` | expected goals and assists so far |
| `fpl_defensive_contribution` | FPL's defensive actions count |
| `fpl_price` | FPL game price (kept for exploration; not a feature) |
| `fpl_id`, `fpl_code` | FPL's ids; the code is stable across seasons |
| `fpl_gameweeks` | finished gameweeks, the same for every row |
| `has_fpl_record` | 1 if the player is in this season's FPL list |

**Past Premier League seasons.** From the FPL archive, over the last four
completed seasons:

| Column | Meaning |
|---|---|
| `hist_minutes`, `hist_starts` | totals |
| `hist_goals`, `hist_assists` | totals |
| `hist_xg`, `hist_xa` | totals |
| `hist_bps` | FPL bonus-point system score, total (kept for exploration; not a feature) |
| `hist_seasons` | seasons on record |
| `has_hist_record` | 1 if there is any PL record |
| `recent_minutes`, `recent_available_minutes` | the newest completed season alone: minutes played and minutes available |
| `recent_bps` | bonus points in that season (exploration only) |

**Other big leagues.** From Understat, or Kaggle where Understat misses the
name. Filled for anyone found there; the model falls back on it only for players
with no Premier League record:

| Column | Meaning |
|---|---|
| `nonpl_minutes`, `nonpl_goals`, `nonpl_assists` | totals in La Liga, the Bundesliga, Serie A, Ligue 1 and the Russian league |
| `nonpl_seasons` | seasons on record |
| `nonpl_available_minutes` | a full season's minutes in that league, for each season on record |
| `has_nonpl_record` | 1 if there is any such record |
| `nonpl_recent_minutes`, `nonpl_recent_available_minutes` | the newest completed season alone |

**Europe and quality.**

| Column | From | Meaning |
|---|---|---|
| `cl_minutes_last` | Kaggle | Champions League minutes in the newest completed season |
| `us_minutes`, `us_xgchain` | Understat | minutes and total xGChain across every covered league, the PL included, for the quality measure |

**The last fee.** From Transfermarkt's transfers pages, else Kaggle:

| Column | Meaning |
|---|---|
| `transfer_fee_eur` | the most recent fee paid for the player |
| `transfer_fee_date` | when (this season's fees are dated 1 July) |
| `transfer_fee_years` | years between that date and the build |
| `has_transfer_fee` | 1 if any fee is on file. A loan or a free move pays nothing new, so the fee before it stands |

Today, 529 players are in the FPL list and 424 have a PL record. 191 have a
record in the other leagues, 412 have enough Understat minutes for the quality
measure, and 150 played in the Champions League last season. 450 have a known
fee.

The model's 25 features are computed from these columns by
[`features.py`](../backend/features.py). They are listed in
[the model notes](model.md#features).

## Trained models

`python -m backend.model` does the following:
- trains the value model and saves it to `models/linear_regression.joblib`,
  which `predict --age …` uses for hypothetical players
- prints the held-out and 5-fold cross-validated accuracy
- redraws `reports/figures/pred_vs_actual.png`
- measures the ranges and writes them to `models/confidence_calibration.json`

`python -m backend.fee_model` trains the fee model and writes
`models/fee_model.joblib` and `models/fee_calibration.json`. It does nothing
without the Kaggle files.

The API does not use the saved value model for the site. When it starts, it
fits the out-of-fold models itself (100 quick fits, well under a second), so the
figures always match the dataset on disk.

## Keeping it current

```bash
python -m backend.refresh            # only when something has changed
python -m backend.refresh --force    # regardless
```

The refresh asks FPL which gameweek has finished. It rebuilds the dataset and
retrains both models only if one of these holds:
- a gameweek has finished since the last build
- Transfermarkt's squad pages are a week old

On a quiet day it does nothing else. The API notices a rebuilt dataset on its
next request, so the server keeps running.

To run the check every morning at 07:00 on macOS (launchd):

```bash
./scripts/install_refresh_schedule.sh     # log in data/refresh.log
./scripts/uninstall_refresh_schedule.sh
```

Keep the project outside the Desktop, Documents and Downloads folders, for
example in `~/projects/pl-value-predictor`. macOS does not let background jobs
read those three, so from there the job fails with "Operation not permitted"
(see `data/refresh.log`). To move an existing checkout:
1. Copy it, `data/` and `models/` included (they are not in git).
2. Create `.venv` afresh in the new place. A virtualenv records absolute paths,
   so a moved one breaks.
3. Run `scripts/uninstall_refresh_schedule.sh`, then
   `scripts/install_refresh_schedule.sh` from the new copy.

`launchctl kickstart -k gui/$(id -u)/com.plvalue.refresh` runs the job at once,
to check it.

## Known gaps

- **Market value is always "current".** Transfermarkt's pages expose only
  today's valuation (its season filters change squad membership, not the value
  shown), so the model predicts today's value from recent performance.
- **Some newcomers have no record anywhere.** Understat and Kaggle fill in
  players from the big five leagues and Russia, but not Portugal, the
  Championship or the Eredivisie. So 56 players (about 10%, €683m of market
  value) have no record the model can use. Kaggle does hold those leagues, but
  counted like the big five they made the model worse. FBref, which covers them,
  blocks automated access.
- **Season length abroad is approximated.** The minutes available in a foreign
  league come from the longest season any player in it played, or from
  Kaggle's club count. The fixture list is not used, because league lengths
  differ (34 and 38 matches).
- **Name matching is guarded, not perfect.** Anything looser than an exact
  name must also agree on position group or come from the player's own club.
  The guard costs a little coverage to avoid filing the wrong player's stats.
- **Early-season numbers are thin.** After five gameweeks `minutes_share` is
  noisy, and the past seasons carry most of the weight. Shares are normalised by
  the gameweeks played, so the feature stays comparable as the season goes on.
- **Valuations can lag by up to a week**, because Transfermarkt's pages are
  cached for seven days.
- **Club names are Transfermarkt's** (`Man City`, not `Manchester City FC`).
  `predict` lists the valid ones if you pass an unknown club.
- **Scraping.** Transfermarkt is read politely (delays, a cache) for personal
  and educational use. Heavier or commercial use is against its terms.
