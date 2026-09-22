/* PL Value — talks to the backend over /api, never to the model directly.
   Drawing lives in charts.js; this file decides what to show and when. */

const el = (id) => document.getElementById(id);
const nodes = {
  query: el("q"),
  suggestions: el("suggestions"),
  board: el("board"),
  player: el("player"),
  underrated: el("underrated"),
  overrated: el("overrated"),
  stat: el("masthead-stat"),
  tablesNote: el("tables-note"),
  gridNote: el("grid-note"),
  gridRows: el("grid-rows"),
  filterClub: el("filter-club"),
  filterPosition: el("filter-position"),
  sort: el("sort"),
  filterCount: el("filter-count"),
  viewGaps: el("view-gaps"),
  viewAll: el("view-all"),
  colophon: el("colophon-model"),
  compare: el("compare"),
  loading: el("loading"),
  showAll: el("show-all"),
  themeToggle: el("theme-toggle"),
};

// Rows rendered before the "show all" button appears. 540 at once is a wall,
// especially on a phone.
const FIRST_PAGE = 60;
let gridLimit = FIRST_PAGE;

let everyone = [];
let highlighted = -1;
// Starting year of the season being played now; set from /api/meta.
let thisSeason = null;

/* --- formatting -------------------------------------------------------- */

/** Transfer fees are spoken in millions, so write them that way. */
const money = Charts.euro;
const esc = Charts.esc;

const signed = (pct) => `${pct > 0 ? "+" : "−"}${Math.abs(Math.round(pct))}%`;
const count = (n, word) => `${n.toLocaleString("en-GB")} ${word}${n === 1 ? "" : "s"}`;
const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1).replace(" - ", " — ");
const seasonLabel = (year) => `${year}/${String(year + 1).slice(-2)}`;
const minutesLabel = (n) => `${n.toLocaleString("en-GB")}′`;
const surnameOf = (name) => name.split(" ").slice(-1)[0];
const directionOf = (gapPct) => (gapPct > 0 ? "more" : "less");

function ordinal(n) {
  const teen = n % 100 >= 11 && n % 100 <= 13;
  const suffix = teen ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] ?? "th");
  return `${n}${suffix}`;
}

/** "Central Midfield" -> "central midfielder", "Centre-Back" -> "centre-back". */
function positionSingular(position) {
  const lower = position.toLowerCase();
  return lower.endsWith("midfield") ? `${lower}er` : lower;
}

const positionPlural = (position) => `${positionSingular(position)}s`;

async function api(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

/* --- theme ------------------------------------------------------------- */

// The saved choice is applied by an inline script in <head>, before the first
// paint; this only keeps the button honest and records changes.
const THEME_KEY = "pl-value-theme";
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");

const MOON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.5 14.1A8.5 8.5 0 1 1 9.9 3.5a6.8 6.8 0 0 0 10.6 10.6z"/></svg>`;
const SUN = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/></svg>`;

const currentTheme = () =>
  document.documentElement.dataset.theme ?? (prefersDark.matches ? "dark" : "light");

function paintToggle() {
  const dark = currentTheme() === "dark";
  nodes.themeToggle.innerHTML = dark ? SUN : MOON;
  nodes.themeToggle.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
}

nodes.themeToggle.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    // Storage blocked (private window): the choice lasts until reload.
  }
  paintToggle();
});
prefersDark.addEventListener("change", paintToggle);
paintToggle();

/* --- search ------------------------------------------------------------ */

function matches(term) {
  const q = term.trim().toLowerCase();
  if (q.length < 2) return [];
  const starts = [];
  const contains = [];
  for (const p of everyone) {
    const name = p.name.toLowerCase();
    if (name.startsWith(q)) starts.push(p);
    else if (
      name.includes(q) ||
      p.club.toLowerCase().includes(q) ||
      p.position.toLowerCase().includes(q) ||
      (p.nationality ?? "").toLowerCase().includes(q)
    ) {
      contains.push(p);
    }
  }
  return [...starts, ...contains].slice(0, 8);
}

function renderSuggestions(list, term) {
  highlighted = -1;
  nodes.suggestions.innerHTML = "";
  nodes.query.setAttribute("aria-expanded", String(list.length > 0));

  // Silence reads as a broken box. Say why there is nothing to show.
  if (!list.length) {
    if (term.trim().length < 2) {
      nodes.suggestions.hidden = true;
      return;
    }
    const empty = document.createElement("li");
    empty.className = "suggestion suggestion--empty";
    empty.textContent = "No player in this season’s squads matches that.";
    nodes.suggestions.appendChild(empty);
    nodes.suggestions.hidden = false;
    return;
  }

  for (const player of list) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", "false");
    button.innerHTML = `<span class="suggestion__name"></span><span class="suggestion__meta"></span><span class="suggestion__value"></span>`;
    button.querySelector(".suggestion__name").textContent = player.name;
    button.querySelector(".suggestion__meta").textContent = `${player.club} · ${player.position}`;
    button.querySelector(".suggestion__value").textContent = money(player.marketValueEur);
    button.addEventListener("click", () => open(player.id));
    item.appendChild(button);
    nodes.suggestions.appendChild(item);
  }
  nodes.suggestions.hidden = false;
}

const suggestionButtons = () => [
  ...nodes.suggestions.querySelectorAll(".suggestion:not(.suggestion--empty)"),
];

function highlight(step) {
  const options = suggestionButtons();
  if (!options.length) return;
  options[highlighted]?.setAttribute("aria-selected", "false");
  highlighted = (highlighted + step + options.length) % options.length;
  options[highlighted].setAttribute("aria-selected", "true");
  options[highlighted].scrollIntoView({ block: "nearest" });
}

function closeSuggestions() {
  nodes.suggestions.hidden = true;
  nodes.query.setAttribute("aria-expanded", "false");
  highlighted = -1;
}

nodes.query.addEventListener("input", () =>
  renderSuggestions(matches(nodes.query.value), nodes.query.value),
);

nodes.query.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    highlight(event.key === "ArrowDown" ? 1 : -1);
  } else if (event.key === "Enter") {
    event.preventDefault();
    const options = suggestionButtons();
    (options[highlighted] ?? options[0])?.click();
  } else if (event.key === "Escape") {
    closeSuggestions();
  }
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".finder")) closeSuggestions();
});

/* --- the valuation ----------------------------------------------------- */

/** The chart, said in words, for anyone not looking at it. */
function spokenSummary(player) {
  const { range, marketValueEur: market, predictedEur: model } = player;
  const level = Math.round(player.confidence.level * 100);
  return range
    ? `Model estimate ${money(model)}. The ${level}% range runs from ${money(range.lowEur)} to ${money(range.highEur)}. ` +
        `The market values this player at ${money(market)}, ${player.marketInRange ? "inside" : "outside"} that range.`
    : `Model estimate ${money(model)}. The market values this player at ${money(market)}. No calibrated range available.`;
}

/** The four numbers a reader came for, before any chart asks to be read. */
function statTiles(player, rank) {
  const { range, marketValueEur: market, predictedEur: model, peers } = player;
  const level = Math.round(player.confidence.level * 100);
  const direction = directionOf(player.gapPct);
  return `
    <div class="kpis">
      <section class="card kpi">
        <p class="kpi__label">Model estimate</p>
        <p class="kpi__value kpi__value--keyed"><span class="key key--dot key--model" aria-hidden="true"></span>${money(model)}</p>
        <p class="kpi__sub">${range ? `${level}% range ${money(range.lowEur)} – ${money(range.highEur)}` : "Range not calibrated"}</p>
      </section>
      <section class="card kpi">
        <p class="kpi__label">Market value</p>
        <p class="kpi__value kpi__value--keyed"><span class="key key--dot key--market" aria-hidden="true"></span>${money(market)}</p>
        <p class="kpi__sub">${esc(player.marketValueSource ?? "Transfermarkt")} valuation</p>
      </section>
      <section class="card kpi">
        <p class="kpi__label">Model vs market</p>
        <p class="kpi__value">${signed(player.gapPct)}</p>
        <p class="kpi__sub kpi__dir"><span class="key key--${direction}" aria-hidden="true"></span>Model asks ${direction}</p>
      </section>
      <section class="card kpi">
        <p class="kpi__label">Among ${esc(positionPlural(peers.position))}</p>
        <p class="kpi__value">${ordinal(rank)} <span class="kpi__of">of ${peers.count}</span></p>
        <p class="kpi__sub">by market value</p>
      </section>
    </div>`;
}

function valuationChart(player) {
  const { range, marketValueEur: market, predictedEur: model } = player;
  const level = player.confidence.level;
  const scale = Charts.linearScale(Math.max(range?.highEur ?? 0, market, model));
  return `
    <section class="card chart" aria-labelledby="chart-title">
      <header class="chart__head">
        <h2 class="chart__title" id="chart-title">What the model allows</h2>
        ${Charts.rangeLegend(level, Boolean(range))}
      </header>
      <p class="visually-hidden">${spokenSummary(player)}</p>
      ${Charts.rangePlot({ range, model, market, scale, level })}
      <p class="chart__note">“Market” is ${esc(player.marketValueSource ?? "Transfermarkt")}’s published valuation —
        a community estimate moderated by its editors, not a fee anyone paid.</p>
    </section>`;
}

/* --- verdict ----------------------------------------------------------- */

/**
 * Leads with whether the market falls inside the range, not the raw percentage.
 * The model shrinks its estimates toward the middle — it runs about 15% low on
 * the most expensive players and high on the cheapest — so a bare "18% below"
 * invites a reader to see a disagreement where the range says there is none.
 */
function verdict(player) {
  const gap = Math.abs(Math.round(player.gapPct));
  const surname = esc(surnameOf(player.name));
  const direction = directionOf(player.gapPct);

  let headline;
  if (player.marketInRange === false) {
    headline = `The model and the market disagree about ${surname}.`;
  } else if (player.marketInRange === true) {
    headline = `The model and the market agree about ${surname}.`;
  } else {
    headline = `The model puts ${surname} ${gap}% ${player.gapPct > 0 ? "above" : "below"} the market.`;
  }

  const inside = player.marketInRange
    ? "but the market’s figure still falls inside the range the model allows"
    : "and the market’s figure falls outside the range the model allows";
  const detail =
    player.marketInRange === null
      ? ""
      : `Its estimate of <em>${money(player.predictedEur)}</em> asks ${gap}% ${direction} than the market’s ${money(player.marketValueEur)}, ${inside}.`;

  return `
    <section class="verdict">
      <p class="verdict__line">${headline}</p>
      <p class="verdict__detail">${detail}</p>
      ${caveat(player)}
      <p class="verdict__confidence">${sentence(player.confidence.summary ?? player.confidence.label)}.</p>
    </section>`;
}

// The model almost never values anyone under about €2m, so below that its
// estimate describes its own floor rather than the player.
const MODEL_FLOOR_EUR = 2_000_000;

function caveat(player) {
  const minutes =
    player.evidence.thisSeason.minutes +
    player.evidence.premierLeague.minutes +
    player.evidence.otherLeagues.minutes;

  if (minutes === 0) {
    return `<p class="verdict__caveat">This player has no minutes on record anywhere we look, so the
      estimate rests on age, position and club alone. Treat it as a starting point, not a reading.</p>`;
  }
  if (player.marketValueEur < MODEL_FLOOR_EUR) {
    return `<p class="verdict__caveat">The model rarely values anyone below about ${money(MODEL_FLOOR_EUR)},
      so for the cheapest players the gap says more about that floor than about this one.</p>`;
  }
  return "";
}

/* --- panels ------------------------------------------------------------ */

function contractText(player) {
  if (!player.contractExpiry) return "";
  const expiry = new Date(player.contractExpiry);
  const years = (expiry - new Date()) / (365.25 * 24 * 3600 * 1000);
  const when = expiry.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
  return `Contract to ${when}${years < 1 ? " · under a year left" : ""}`;
}

function metaChips(player) {
  return [player.position, `Age ${player.age}`, player.nationality, player.club, contractText(player)]
    .filter(Boolean)
    .map((text) => `<li class="chip">${esc(text)}</li>`)
    .join("");
}

// Every minute of a 38-game season: the fixed end of the minutes scale, so a
// season's bar means the same length on every player's page.
const FULL_SEASON_MINUTES = 38 * 90;

function seasonRow({ label, note, minutes, possible, detail, tip }) {
  const share = Math.min(1, minutes / FULL_SEASON_MINUTES);
  const bar = minutes
    ? `<span class="season__bar" style="--share:${share}" tabindex="0" role="img"
         aria-label="${esc(`${label}: ${minutesLabel(minutes)}`)}"
         data-tip-value="${esc(minutesLabel(minutes))}" data-tip-label="${esc(tip)}"></span>`
    : "";
  return `
    <div class="season">
      <span class="season__label">${label}${note ? `<small>${note}</small>` : ""}</span>
      <span class="season__track" style="--possible:${Math.min(1, possible / FULL_SEASON_MINUTES)}">${bar}</span>
      <span class="season__figure">${minutesLabel(minutes)}<small>${detail}</small></span>
    </div>`;
}

function seasonsPanel(player) {
  const past = player.seasons ?? [];
  const now = player.evidence.thisSeason;
  const title = `<h2 class="panel__title">Minutes by season</h2>`;

  const rows = past.map((s) =>
    seasonRow({
      label: seasonLabel(s.season),
      minutes: s.minutes,
      possible: FULL_SEASON_MINUTES,
      detail: `${s.goals}G ${s.assists}A`,
      tip: `${seasonLabel(s.season)} · ${s.competition} · ${count(s.goals, "goal")}, ${count(s.assists, "assist")}`,
    }),
  );
  // The season in progress gets a track only as long as the games played so
  // far, or four gameweeks would read as a player who barely features.
  if (now.known && thisSeason !== null) {
    rows.push(
      seasonRow({
        label: seasonLabel(thisSeason),
        note: "so far",
        minutes: now.minutes,
        possible: now.gameweeks * 90,
        detail: `of ${minutesLabel(now.gameweeks * 90)}`,
        tip: `${seasonLabel(thisSeason)} so far · Premier League · ${count(now.starts, "start")} in ${count(now.gameweeks, "gameweek")}`,
      }),
    );
  }

  if (!rows.length) {
    return `<section class="card panel">${title}
      <p class="panel__empty">No season on record in the competitions we cover.</p></section>`;
  }

  const leagues = [...new Set(past.map((s) => s.competition))];
  const where =
    !leagues.length || (leagues.length === 1 && leagues[0] === "Premier League")
      ? "Premier League minutes."
      : `Earlier seasons in ${leagues.join(" and ")}${now.known ? "; this one in the Premier League" : ""}.`;

  return `
    <section class="card panel">${title}
      <div class="seasons">${rows.join("")}</div>
      <div class="season__scale" aria-hidden="true"><span>0′</span><span>${minutesLabel(FULL_SEASON_MINUTES)}</span></div>
      <p class="panel__body">${where} The track behind each bar is every minute of a 38-game season.</p>
    </section>`;
}

const PEERS_NEEDED = 5;

function peersPanel(player) {
  const peers = player.peers;
  const plural = positionPlural(peers.position);
  const title = `<h2 class="panel__title">Against other ${esc(plural)}</h2>`;

  // A distribution drawn from one or two players is theatre, not information.
  if (peers.count < PEERS_NEEDED) {
    const others = peers.count - 1;
    return `<section class="card panel">${title}
      <p class="panel__empty">
        ${others === 0
          ? `The only ${esc(positionSingular(peers.position))} in the league, so there is nobody to compare against.`
          : `Only ${count(others, "other " + positionSingular(peers.position))} in the league — too few to place this value among.`}
      </p></section>`;
  }

  const percent = Math.round(peers.valuePercentile * 100);
  const table = new URLSearchParams({ position: peers.position }).toString();
  return `
    <section class="card panel">${title}
      <div id="peer-strip"></div>
      <p class="panel__body">
        Worth more than ${percent}% of the ${peers.count} ${esc(plural)} in the league. Each dot is
        one of them, on a log scale; ${esc(surnameOf(player.name))} is the large ringed one.
      </p>
      <a class="panel__link" href="#all?${table}">All ${peers.count} ${esc(plural)} as a table →</a>
    </section>`;
}

function evidencePanel(player) {
  const { thisSeason: now, premierLeague, otherLeagues } = player.evidence;
  const rows = [
    [
      `This season (${now.gameweeks} gameweeks)`,
      now.known ? `${count(now.minutes, "minute")} · ${count(now.starts, "start")}` : null,
      "Not in this season’s squad data",
    ],
    [
      "Premier League record",
      premierLeague.known
        ? `${count(premierLeague.seasons, "season")} · ${count(premierLeague.minutes, "minute")} · ${premierLeague.goals}G ${premierLeague.assists}A`
        : null,
      "No Premier League record in the seasons we cover",
    ],
    [
      "Other leagues",
      otherLeagues.known
        ? `${count(otherLeagues.seasons, "season")} · ${count(otherLeagues.minutes, "minute")} · ${otherLeagues.goals}G ${otherLeagues.assists}A`
        : null,
      "No record in the other leagues we cover",
    ],
    [
      "Last transfer fee",
      player.lastFee
        ? `${money(player.lastFee.eur)}${player.lastFee.date ? ` · ${new Date(player.lastFee.date).getFullYear()}` : ""}`
        : null,
      "No fee on record — a free transfer, or one we don’t have",
    ],
  ];

  return `
    <section class="card panel panel--wide">
      <h2 class="panel__title">What the model had to go on</h2>
      ${rows
        .map(
          ([label, value, absent]) => `
        <div class="evidence__row">
          <span class="evidence__label">${label}</span>
          <span class="evidence__value${value ? "" : " evidence__value--absent"}">${value ?? absent}</span>
        </div>`,
        )
        .join("")}
    </section>`;
}

/* --- views ------------------------------------------------------------- */

function showBoard() {
  Tip.hide();
  nodes.player.hidden = true;
  nodes.compare.hidden = true;
  nodes.board.hidden = false;
  nodes.player.innerHTML = "";
  nodes.compare.innerHTML = "";
}

async function open(id) {
  closeSuggestions();
  Tip.hide();
  nodes.query.value = "";
  if (location.hash !== `#p${id}`) location.hash = `p${id}`;

  let player;
  try {
    player = await api(`/api/players/${id}`);
  } catch {
    nodes.player.innerHTML = `<p class="notice">Couldn’t load that player. The model server may have stopped.</p>`;
    nodes.board.hidden = true;
    nodes.player.hidden = false;
    return;
  }

  const peers = everyone.filter((p) => p.position === player.position);
  const rank = peers.filter((p) => p.marketValueEur > player.marketValueEur).length + 1;
  const cameFrom = nodes.viewAll.hidden ? "Where it disagrees" : "All players";

  nodes.player.innerHTML = `
    <button class="back" type="button">← ${cameFrom}</button>
    <header class="player__head">
      <h1 class="player__name">${esc(player.name)}</h1>
      <ul class="player__meta" aria-label="Profile">${metaChips(player)}</ul>
    </header>
    ${statTiles(player, rank)}
    ${valuationChart(player)}
    ${verdict(player)}
    <div class="panels">
      ${seasonsPanel(player)}
      ${peersPanel(player)}
      ${evidencePanel(player)}
    </div>
    <div class="card picker">
      <label class="picker__label" for="compare-with">Put ${esc(surnameOf(player.name))} next to</label>
      <input id="compare-with" list="compare-options" placeholder="another player’s name">
      <datalist id="compare-options"></datalist>
      <span class="picker__hint">Both ranges on one scale.</span>
    </div>`;

  const strip = nodes.player.querySelector("#peer-strip");
  if (strip) {
    Charts.renderPeerStrip(strip, {
      peers,
      focusId: player.id,
      onPick: (pick) => {
        location.hash = `p${pick}`;
      },
    });
  }

  nodes.player.querySelector(".back").addEventListener("click", () => {
    location.hash = nodes.viewAll.hidden ? "" : gridHash();
  });
  wirePicker(nodes.player, player.id);

  nodes.board.hidden = true;
  nodes.compare.hidden = true;
  nodes.player.hidden = false;
  window.scrollTo({ top: 0, behavior: "instant" });
}

/* --- compare ----------------------------------------------------------- */

/** A second player, chosen by name, opens the two-up view. */
function wirePicker(root, currentId) {
  const input = root.querySelector(".picker input");
  const list = root.querySelector(".picker datalist");
  if (!input) return;

  for (const player of everyone) {
    if (player.id === currentId) continue;
    const option = document.createElement("option");
    option.value = `${player.name} — ${player.club}`;
    option.dataset.id = String(player.id);
    list.appendChild(option);
  }

  input.addEventListener("change", () => {
    const chosen = [...list.options].find((option) => option.value === input.value);
    if (chosen) location.hash = `c${currentId},${chosen.dataset.id}`;
  });
}

function compareRow(player, scale) {
  const direction = directionOf(player.gapPct);
  return `
    <div class="compare__row">
      <div class="compare__who">
        <a class="compare__name" href="#p${player.id}">${esc(player.name)}</a>
        <span class="compare__meta">${esc(player.club)} · ${esc(player.position)} · ${player.age}</span>
        <span class="compare__figures kpi__dir">
          <span class="key key--${direction}" aria-hidden="true"></span>Model asks ${Math.abs(Math.round(player.gapPct))}% ${direction}
        </span>
      </div>
      <p class="visually-hidden">${esc(player.name)}: ${spokenSummary(player)}</p>
      ${Charts.rangePlot({
        range: player.range,
        model: player.predictedEur,
        market: player.marketValueEur,
        scale,
        level: player.confidence.level,
      })}
    </div>`;
}

async function compare(leftId, rightId) {
  closeSuggestions();
  Tip.hide();
  let pair;
  try {
    pair = await Promise.all([api(`/api/players/${leftId}`), api(`/api/players/${rightId}`)]);
  } catch {
    nodes.compare.innerHTML = `<p class="notice">Couldn’t load both players.</p>`;
    nodes.board.hidden = true;
    nodes.player.hidden = true;
    nodes.compare.hidden = false;
    return;
  }

  // One scale for both, or the ranges could not be read against each other.
  const scale = Charts.linearScale(
    Math.max(...pair.map((p) => Math.max(p.range?.highEur ?? 0, p.marketValueEur, p.predictedEur))),
  );

  nodes.compare.innerHTML = `
    <button class="back" type="button">← ${esc(pair[0].name)}</button>
    <h1 class="compare__title">${esc(pair[0].name)} and ${esc(pair[1].name)}</h1>
    <p class="compare__lead">Both on one scale, so each range can be read against the other.</p>
    <section class="card compare__card">
      <header class="chart__head">
        <h2 class="chart__title">What the model allows</h2>
        ${Charts.rangeLegend(pair[0].confidence.level, pair.some((p) => p.range))}
      </header>
      ${pair.map((p) => compareRow(p, scale)).join("")}
    </section>`;

  nodes.compare.querySelector(".back").addEventListener("click", () => {
    location.hash = `p${leftId}`;
  });

  nodes.board.hidden = true;
  nodes.player.hidden = true;
  nodes.compare.hidden = false;
  window.scrollTo({ top: 0, behavior: "instant" });
}

/* --- board ------------------------------------------------------------- */

/** Both lists share one bar scale, so a long bar means the same on either side. */
function rankList(target, players, largest) {
  target.innerHTML = "";
  players.forEach((player, index) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "rank";
    button.innerHTML = `
      <span class="rank__pos">${String(index + 1).padStart(2, "0")}</span>
      <span><span class="rank__name"></span><span class="rank__club"></span></span>
      ${Charts.gapBar(player.gapPct, largest)}
      <span class="rank__gap"></span>`;
    button.querySelector(".rank__name").textContent = player.name;
    button.querySelector(".rank__club").textContent =
      `${player.club} · ${money(player.marketValueEur)} → ${money(player.predictedEur)}`;
    button.querySelector(".rank__gap").textContent = signed(player.gapPct);
    button.addEventListener("click", () => open(player.id));
    item.appendChild(button);
    target.appendChild(item);
  });
}

const sorters = {
  value: (a, b) => b.marketValueEur - a.marketValueEur,
  predicted: (a, b) => b.predictedEur - a.predictedEur,
  gap: (a, b) => Math.abs(b.gapPct) - Math.abs(a.gapPct),
  name: (a, b) => a.name.localeCompare(b.name),
};

// Where the table's diverging bars saturate. The asking-less side cannot pass
// -100%, so this keeps both halves on the same footing.
const GAP_BAR_CAP = 100;

function renderGrid() {
  const club = nodes.filterClub.value;
  const position = nodes.filterPosition.value;
  const rows = everyone
    .filter((p) => (!club || p.club === club) && (!position || p.position === position))
    .sort(sorters[nodes.sort.value]);

  nodes.filterCount.textContent = `${rows.length} of ${everyone.length}`;
  nodes.gridRows.innerHTML = "";

  if (!rows.length) {
    nodes.showAll.hidden = true;
    nodes.gridRows.innerHTML = `<p class="panel__empty">No player matches both filters. Widen one of them.</p>`;
    return;
  }

  const shown = rows.slice(0, gridLimit);
  const remaining = rows.length - shown.length;
  nodes.showAll.hidden = remaining === 0;
  if (remaining) nodes.showAll.textContent = `Show the other ${remaining}`;

  const fragment = document.createDocumentFragment();
  for (const player of shown) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "grid__row";
    button.setAttribute("role", "row");
    button.innerHTML = `
      <span role="cell"><span class="grid__name"></span><span class="grid__meta"></span></span>
      <span class="grid__figure" role="cell"></span>
      <span class="grid__figure" role="cell"></span>
      <span aria-hidden="true">${Charts.divergingBar(player.gapPct, GAP_BAR_CAP)}</span>
      <span class="grid__gap" role="cell"></span>`;
    const figures = button.querySelectorAll(".grid__figure");
    button.querySelector(".grid__name").textContent = player.name;
    button.querySelector(".grid__meta").textContent = `${player.club} · ${player.position}`;
    figures[0].textContent = money(player.marketValueEur);
    figures[1].textContent = money(player.predictedEur);
    button.querySelector(".grid__gap").textContent = signed(player.gapPct);
    button.addEventListener("click", () => open(player.id));
    fragment.appendChild(button);
  }
  nodes.gridRows.appendChild(fragment);
}

function gridHash() {
  const params = new URLSearchParams();
  if (nodes.filterClub.value) params.set("club", nodes.filterClub.value);
  if (nodes.filterPosition.value) params.set("position", nodes.filterPosition.value);
  if (nodes.sort.value !== "value") params.set("sort", nodes.sort.value);
  const query = params.toString();
  return query ? `all?${query}` : "all";
}

function applyGridHash(query) {
  const params = new URLSearchParams(query);
  nodes.filterClub.value = params.get("club") ?? "";
  nodes.filterPosition.value = params.get("position") ?? "";
  nodes.sort.value = params.get("sort") ?? "value";
}

function switchView(view, { push = true } = {}) {
  for (const button of document.querySelectorAll(".view")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  }
  nodes.viewGaps.hidden = view !== "gaps";
  nodes.viewAll.hidden = view !== "all";
  if (view === "all") {
    gridLimit = FIRST_PAGE;
    renderGrid();
  }
  if (push) location.hash = view === "all" ? gridHash() : "";
}

function route() {
  const hash = location.hash.slice(1);

  const player = hash.match(/^p(\d+)$/);
  if (player) return open(Number(player[1]));

  const pair = hash.match(/^c(\d+),(\d+)$/);
  if (pair) return compare(Number(pair[1]), Number(pair[2]));

  showBoard();
  const grid = hash.match(/^all(?:\?(.*))?$/);
  if (grid) {
    applyGridHash(grid[1] ?? "");
    switchView("all", { push: false });
  } else {
    switchView("gaps", { push: false });
  }
}

/* --- start ------------------------------------------------------------- */

(async function start() {
  try {
    const [players, meta, ranks] = await Promise.all([
      api("/api/players"),
      api("/api/meta"),
      api("/api/rankings?limit=8"),
    ]);
    everyone = players;
    thisSeason = Math.max(...meta.seasons) + 1;

    nodes.stat.textContent = `${meta.players} players · ${meta.clubs} clubs`;
    nodes.tablesNote.textContent =
      `Players under ${money(ranks.minValueEur)} are left out here: a percentage gap on a cheap squad player is mostly noise.`;
    nodes.gridNote.textContent =
      "The model shrinks its estimates toward the middle, so it tends to ask less than the market for the most expensive players and more for the cheapest. Read a gap against that, and open a player to see the range.";
    nodes.colophon.textContent =
      `Cross-validated on ${meta.players} players: R² ${meta.model.r2Log} on log value, average miss ${money(meta.model.maeEur)}. ` +
      `Every estimate is made by a model that never saw that player.`;

    for (const club of meta.clubList) nodes.filterClub.append(new Option(club, club));
    for (const position of meta.positionList) nodes.filterPosition.append(new Option(position, position));

    const largest = Math.max(1, ...[...ranks.underrated, ...ranks.overrated].map((p) => Math.abs(p.gapPct)));
    rankList(nodes.underrated, ranks.underrated, largest);
    rankList(nodes.overrated, ranks.overrated, largest);

    for (const button of document.querySelectorAll(".view")) {
      button.addEventListener("click", () => switchView(button.dataset.view));
    }
    for (const control of [nodes.filterClub, nodes.filterPosition, nodes.sort]) {
      control.addEventListener("change", () => {
        gridLimit = FIRST_PAGE;
        location.hash = gridHash();
        renderGrid();
      });
    }
    nodes.showAll.addEventListener("click", () => {
      gridLimit = Infinity;
      renderGrid();
    });

    nodes.loading.hidden = true;
    route();
    window.addEventListener("hashchange", route);
  } catch {
    el("main").innerHTML =
      `<p class="notice">Can’t reach the model server. Start it with <code>uvicorn backend.api:app</code>, then reload.</p>`;
  }
})();
