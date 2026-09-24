# frontend

A single page, no build step: `index.html` plus `assets/styles.css`,
`assets/charts.js` (chart primitives and the one shared tooltip) and
`assets/app.js` (what to show, and when). It talks to the backend only over `/api`, never by importing
the pipeline, so the two stay separable.

Run both together:

```bash
uvicorn backend.api:app --port 8000 --reload
```

Then open http://localhost:8000. FastAPI serves this directory; there is
nothing else to start.

## What it shows

The page is built around one idea: **a valuation is a range, not a number.**
Most value sites print a single confident figure. This one draws the range the
model actually earns, marks the market's figure on the same scale, and says
plainly whether the market falls inside it.

- **Where it disagrees** — the players the model and the market differ on most.
- **All players** — every one of the 540, filtered by club and position and
  sorted four ways. The filters live in the URL, so a view can be shared.
- **Player** — four stat tiles (model estimate, market value, the gap, rank
  among the same position), then the range, the verdict, minutes season by
  season, every same-position player as a dot, and what evidence the model
  had. Players with no recent playing record get a visibly wider range and a
  low-confidence label rather than a falsely precise number.
- **Compare** — two players' ranges drawn on one shared scale.

Each player page also shows what a club would likely pay, from the second model
(`backend/fee_model.py`): one figure for a Premier League buyer and one for a buyer
abroad, with how widely real fees scatter and a note when a short contract would
pull the price down.

The verdict leads with whether the market falls inside the range, not with the
raw percentage. When a club has just paid several times the market's figure for a
player, the page says so: that valuation has usually not caught up with the fee yet. The model shrinks its estimates toward the middle, so a bare
"18% below" would invite a reader to see a disagreement where there is none.

## Design notes

- **A matchday, not a dashboard.** The page is the terrace - a cool concrete
  grey - and every view opens on a **scoreboard**: a dark housing with
  dot-matrix lamps. A valuation here is a contest between the model and the
  market, so it is announced the way a ground announces a score: the board
  shows the two widest disagreements, a player's model / market / gap / rank,
  and a comparison as a score line ("HAALAND €187m – €69.5m ISAK"). The lamps
  flicker on once when a board appears; nothing else on the page moves except
  the range sweeping in.
- **The scoreboard is the one loud thing.** Everything around it stays quiet:
  chalk panels for the charts, names and headings in Big Shoulders Display (the
  condensed capitals of stadium signage), reading text in Schibsted Grotesk,
  club codes in the three letters of a TV score bug, labels and axes in IBM
  Plex Mono. Doto, the dot-matrix face, appears on the scoreboard and nowhere
  else.
- **Light and dark.** The page follows the system setting; the button in the
  masthead overrides it and remembers the choice. Dark mode has its own colour
  steps, checked against the dark surface, not an inverted light theme.
- **Every colour has one job.** Green is the model, ink is the market, and
  orange / blue say whether the model asks more or less. On the scoreboard the
  same roles light up - model in green lamps, market in white. The pairs were
  checked for colour-blind separation, and green and orange are never put in
  the same chart because they are too close under protanopia. Colour marks the
  bars and dots only; numbers and labels stay in text colours.
- **Scales are honest.** Money axes start at zero; the peer strip uses a log
  axis because one position spans three orders of magnitude; minutes are drawn
  against a full 38-game season, so a bar means the same length on every page.
- **Nothing is hover-only.** Charts have tooltips on hover and keyboard focus,
  but every value is also printed: on the scoreboard, as a direct label, or as
  a row in the table (the peer strip links to that position in the table).
- Keyboard: `↑`/`↓` move through search results, `Enter` opens, `Esc` closes.
  Focus is always visible, and `prefers-reduced-motion` switches the lamps and
  the chart straight on.
- Every colour used for text clears WCAG AA (4.5:1) in both themes, the lamps
  7:1 on the board, and chart marks 3:1. Each chart also has a sentence with the
  same figures for screen readers, and club codes carry the full club name.
