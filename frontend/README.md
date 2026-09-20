# frontend

A single page, no build step: `index.html` plus `assets/styles.css` and
`assets/app.js`. It talks to the backend only over `/api`, never by importing
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
- **Player** — the range, the verdict, minutes season by season, where the
  player sits among others in the same position, and what evidence the model
  had. Players with no recent playing record get a visibly wider band and a
  low-confidence label rather than a falsely precise number.
- **Compare** — two players' ranges drawn on one scale.

The verdict leads with whether the market falls inside the range, not with the
raw percentage. The model shrinks its estimates toward the middle, so a bare
"18% below" would invite a reader to see a disagreement where there is none.

## Design notes

- Palette is a floodlit ground at night. Amber and signal blue aren't
  decoration: they encode the only direction that matters, whether the model
  asks more or less than the market.
- Archivo sets names and headlines at expanded widths, the way squad sheets do.
  Every money figure is IBM Plex Mono, so the numbers line up like a ledger.
- Keyboard: `↑`/`↓` move through search results, `Enter` opens, `Esc` closes.
  Focus is always visible, and `prefers-reduced-motion` is respected.
- Every colour used for text clears WCAG AA (4.5:1) on the paper background.
  The band is drawn for the eye but carries a spoken sentence with the same
  figures for anyone using a screen reader.
