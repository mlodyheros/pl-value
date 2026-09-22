/* PL Value — chart primitives.

   Built to the dataviz method rather than by eye:
   - thin marks, dots of 14px wearing a 2px ring in the surface colour so they
     stay legible where they cross a range or each other;
   - gridlines and axes are solid hairlines one step off the surface;
   - labels are sparse and always in text colours - a coloured mark beside the
     text carries identity, never the text itself;
   - every chart is interactive, and nothing is only readable on hover: each
     value is also a direct label, a stat tile, or a row in the table view.

   Colour roles (validated with the skill's six-checks script, both modes):
   model = green, market = ink (a neutral reference), and the direction of a
   disagreement = orange (model asks more) / blue (model asks less). Green and
   orange sit too close under protanopia (ΔE 6.2), so they are never placed in
   the same chart - the range plot uses green and ink only. */

const Charts = (() => {
  const euro = (value) => {
    if (value >= 1e9) return `€${(value / 1e9).toFixed(1).replace(/\.0$/, "")}bn`;
    if (value >= 1e6) {
      const m = value / 1e6;
      return `€${m >= 100 ? Math.round(m) : m.toFixed(1).replace(/\.0$/, "")}m`;
    }
    if (value >= 1e3) return `€${Math.round(value / 1e3)}k`;
    return `€${Math.round(value)}`;
  };

  /** Attribute-safe text. Names come from a scrape and are treated as data. */
  const esc = (text) =>
    String(text)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

  /* --- scales ---------------------------------------------------------- */

  function niceStep(span, count) {
    const raw = span / count;
    const magnitude = 10 ** Math.floor(Math.log10(raw));
    const norm = raw / magnitude;
    const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
    return step * magnitude;
  }

  /** Round, zero-based ticks: money on a linear axis starts at nothing. */
  function linearScale(max, count = 5) {
    const step = niceStep(Math.max(max, 1), count);
    const top = Math.ceil(max / step) * step;
    const ticks = [];
    for (let value = 0; value <= top + step / 2; value += step) ticks.push(value);
    return { top, ticks, at: (value) => Math.max(0, Math.min(100, (value / top) * 100)) };
  }

  /** Values across a position span three orders of magnitude; only a log axis
      keeps the cheap ones from collapsing into a single dot at zero. */
  function logScale(min, max) {
    const lo = Math.log10(Math.max(min, 1e4) / 1.25);
    const hi = Math.log10(max * 1.25);
    const ticks = [];
    for (let exponent = Math.ceil(lo); exponent <= Math.floor(hi); exponent++) {
      for (const multiple of [1, 3]) {
        const value = multiple * 10 ** exponent;
        if (Math.log10(value) >= lo && Math.log10(value) <= hi) ticks.push(value);
      }
    }
    return {
      ticks,
      at: (value) => ((Math.log10(Math.max(value, 1)) - lo) / (hi - lo)) * 100,
    };
  }

  const anchor = (percent) => (percent > 86 ? "end" : percent < 14 ? "start" : "mid");

  /* --- range plot -------------------------------------------------------- */

  /**
   * The valuation as a range: the model's 80% interval as a green wash, the
   * model's estimate as a green dot, the market's figure as an ink dot, and a
   * hairline between them. Used on the player page and, with a shared scale,
   * in the compare view.
   */
  function rangePlot({ range, model, market, scale, level = 0.8, labels = true }) {
    const at = scale.at;
    const m = at(model);
    const k = at(market);
    const rangeMark = range
      ? `<span class="rplot__range" style="left:${at(range.lowEur)}%;width:${at(range.highEur) - at(range.lowEur)}%"
           tabindex="0" role="img" aria-label="${Math.round(level * 100)}% range: ${esc(`${euro(range.lowEur)} to ${euro(range.highEur)}`)}"
           data-tip-value="${esc(`${euro(range.lowEur)} – ${euro(range.highEur)}`)}"
           data-tip-label="${Math.round(level * 100)}% range the model allows"></span>`
      : "";
    const directLabels = labels
      ? `<span class="rplot__label rplot__label--above rplot__label--${anchor(m)}" style="left:${m}%"><b>${esc(euro(model))}</b> model</span>
         <span class="rplot__label rplot__label--below rplot__label--${anchor(k)}" style="left:${k}%"><b>${esc(euro(market))}</b> market</span>`
      : "";

    return `
      <div class="rplot${labels ? "" : " rplot--bare"}">
        <div class="rplot__grid" aria-hidden="true">
          ${scale.ticks.map((tick) => `<span style="left:${at(tick)}%"></span>`).join("")}
        </div>
        <div class="rplot__lane">
          ${rangeMark}
          <span class="rplot__link" style="left:${Math.min(m, k)}%;width:${Math.abs(m - k)}%" aria-hidden="true"></span>
          <span class="rplot__dot rplot__dot--market" style="left:${k}%" tabindex="0"
                role="img" aria-label="Market: ${esc(euro(market))}" data-tip-value="${esc(euro(market))}" data-tip-label="Market · Transfermarkt"></span>
          <span class="rplot__dot rplot__dot--model" style="left:${m}%" tabindex="0"
                role="img" aria-label="Model estimate: ${esc(euro(model))}" data-tip-value="${esc(euro(model))}" data-tip-label="Model estimate"></span>
          ${directLabels}
        </div>
        <div class="rplot__axis" aria-hidden="true">
          ${scale.ticks
            .map((tick) => `<span class="rplot__tick rplot__tick--${anchor(at(tick))}" style="left:${at(tick)}%">${esc(euro(tick))}</span>`)
            .join("")}
        </div>
      </div>`;
  }

  /** Legend for the range plot: two series and the wash, so identity is never
      carried by colour alone. */
  function rangeLegend(level = 0.8, withRange = true) {
    const wash = withRange
      ? `<li><span class="key key--wash" aria-hidden="true"></span>${Math.round(level * 100)}% range</li>`
      : "";
    return `
      <ul class="legend">
        <li><span class="key key--dot key--model" aria-hidden="true"></span>Model estimate</li>
        <li><span class="key key--dot key--market" aria-hidden="true"></span>Market (Transfermarkt)</li>
        ${wash}
      </ul>`;
  }

  /* --- peer strip -------------------------------------------------------- */

  /** A stable jitter from an id, so the swarm does not reshuffle on redraw. */
  const jitter = (id) => {
    const x = Math.sin(id * 12.9898) * 43758.5453;
    return x - Math.floor(x);
  };

  /**
   * Every player in the same position as a small dot on a log value axis, this
   * one emphasised - the "one point matters, the rest are context" form. The
   * pointer reads the nearest dot rather than demanding a pixel-perfect hit,
   * and clicking opens that player.
   */
  function renderPeerStrip(root, { peers, focusId, onPick }) {
    const values = peers.map((p) => p.marketValueEur).filter((v) => v > 0);
    const scale = logScale(Math.min(...values), Math.max(...values));
    // The true median - the mean of the middle pair for an even count - so it
    // matches the figure the API reports for the same players.
    const sorted = [...values].sort((a, b) => a - b);
    const middle = Math.floor(sorted.length / 2);
    const median = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;

    const dots = peers.map((p) => ({
      ...p,
      x: scale.at(p.marketValueEur),
      y: p.id === focusId ? 50 : 14 + jitter(p.id) * 72,
    }));
    const focus = dots.find((d) => d.id === focusId);

    root.innerHTML = `
      <div class="strip" role="group" aria-label="Market values of ${peers.length} players in this position">
        <div class="strip__grid" aria-hidden="true">
          ${scale.ticks.map((t) => `<span style="left:${scale.at(t)}%"></span>`).join("")}
          <span class="strip__median" style="left:${scale.at(median)}%"></span>
        </div>
        <div class="strip__field">
          ${dots
            .filter((d) => d.id !== focusId)
            .map((d) => `<span class="strip__dot" style="left:${d.x}%;top:${d.y}%"></span>`)
            .join("")}
          ${focus ? `<span class="strip__dot strip__dot--focus" style="left:${focus.x}%;top:50%"></span>` : ""}
        </div>
        <div class="strip__axis" aria-hidden="true">
          ${scale.ticks.map((t) => `<span class="rplot__tick rplot__tick--${anchor(scale.at(t))}" style="left:${scale.at(t)}%">${esc(euro(t))}</span>`).join("")}
        </div>
      </div>
      <p class="strip__median-label">Median ${esc(euro(median))}</p>`;

    const field = root.querySelector(".strip__field");
    const nearest = (event) => {
      const box = field.getBoundingClientRect();
      const px = event.clientX - box.left;
      const py = event.clientY - box.top;
      let best = null;
      let bestDistance = Infinity;
      for (const d of dots) {
        const dx = (d.x / 100) * box.width - px;
        const dy = (d.y / 100) * box.height - py;
        const distance = dx * dx + dy * dy;
        if (distance < bestDistance) {
          bestDistance = distance;
          best = d;
        }
      }
      // Beyond ~24px the pointer is not near anything worth naming.
      return bestDistance <= 24 * 24 ? best : null;
    };

    field.addEventListener("pointermove", (event) => {
      const d = nearest(event);
      field.style.cursor = d ? "pointer" : "default";
      if (!d) return Tip.hide();
      const box = field.getBoundingClientRect();
      Tip.show(box.left + (d.x / 100) * box.width, box.top + (d.y / 100) * box.height,
               euro(d.marketValueEur), `${d.name} · ${d.club}`);
    });
    field.addEventListener("pointerleave", () => Tip.hide());
    field.addEventListener("click", (event) => {
      const d = nearest(event);
      if (d && d.id !== focusId) onPick(d.id);
    });
  }

  /* --- gap bars ---------------------------------------------------------- */

  /** A one-directional bar for the ranked lists: length is the size of the
      disagreement, colour is its direction, and the number beside it stays ink. */
  function gapBar(gapPct, largest) {
    const width = Math.min(100, (Math.abs(gapPct) / largest) * 100);
    const direction = gapPct > 0 ? "more" : "less";
    return `<span class="gapbar gapbar--${direction}" aria-hidden="true"><span style="width:${width}%"></span></span>`;
  }

  /** The diverging version for the full table: centred on "no disagreement",
      growing right when the model asks more and left when it asks less. */
  function divergingBar(gapPct, cap = 150) {
    const half = Math.min(50, (Math.abs(gapPct) / cap) * 50);
    const direction = gapPct > 0 ? "more" : "less";
    const side = gapPct > 0 ? `left:50%;width:${half}%` : `right:50%;width:${half}%`;
    return `<span class="divbar" aria-hidden="true"><span class="divbar__bar divbar__bar--${direction}" style="${side}"></span></span>`;
  }

  return { euro, esc, linearScale, rangePlot, rangeLegend, renderPeerStrip, gapBar, divergingBar };
})();

/* --- one tooltip for every chart ---------------------------------------- */

const Tip = (() => {
  let el = null;

  function ensure() {
    if (!el) {
      el = document.createElement("div");
      el.className = "tip";
      el.setAttribute("role", "tooltip");
      el.hidden = true;
      document.body.appendChild(el);
    }
    return el;
  }

  /** Value leads, label follows - the reader already knows which series they
      pointed at and wants the number. Built with textContent: labels are data. */
  function show(x, y, value, label) {
    const tip = ensure();
    tip.textContent = "";
    const strong = document.createElement("strong");
    strong.textContent = value;
    const small = document.createElement("span");
    small.textContent = label;
    tip.append(strong, small);
    tip.hidden = false;
    const box = tip.getBoundingClientRect();
    const left = Math.max(8, Math.min(x - box.width / 2, window.innerWidth - box.width - 8));
    const top = y - box.height - 14 < 8 ? y + 18 : y - box.height - 14;
    tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
  }

  const hide = () => {
    if (el) el.hidden = true;
  };

  // Delegated, so charts rendered later need no wiring. Focus shows the same
  // readout as hover.
  const fromTarget = (target) => target.closest?.("[data-tip-value]");
  const showFor = (mark) => {
    const box = mark.getBoundingClientRect();
    show(box.left + box.width / 2, box.top, mark.dataset.tipValue, mark.dataset.tipLabel);
  };
  document.addEventListener("pointerover", (e) => {
    const mark = fromTarget(e.target);
    if (mark) showFor(mark);
  });
  document.addEventListener("pointerout", (e) => {
    if (fromTarget(e.target)) hide();
  });
  document.addEventListener("focusin", (e) => {
    const mark = fromTarget(e.target);
    if (mark) showFor(mark);
  });
  document.addEventListener("focusout", (e) => {
    if (fromTarget(e.target)) hide();
  });
  window.addEventListener("scroll", hide, { passive: true });

  return { show, hide };
})();
