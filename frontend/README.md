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

- **Board** — the players the model and the market disagree about most.
- **Player** — the range, the verdict, and what evidence the model had. Players
  with no recent playing record get a visibly wider band and a low-confidence
  label rather than a falsely precise number.

## Design notes

- Palette is a floodlit ground at night. Amber and signal blue aren't
  decoration: they encode the only direction that matters, whether the model
  asks more or less than the market.
- Archivo sets names and headlines at expanded widths, the way squad sheets do.
  Every money figure is IBM Plex Mono, so the numbers line up like a ledger.
- Keyboard: `↑`/`↓` move through search results, `Enter` opens, `Esc` closes.
  Focus is always visible, and `prefers-reduced-motion` is respected.
