/* PL Value — talks to the backend over /api, never to the model directly. */

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
};

// Rows rendered before the "show all" button appears. 540 at once is a wall,
// especially on a phone.
const FIRST_PAGE = 60;
let gridLimit = FIRST_PAGE;

let everyone = [];
let highlighted = -1;

/* --- formatting -------------------------------------------------------- */

/** Transfer fees are spoken in millions, so write them that way. */
function money(eur) {
  if (eur >= 1e6) {
    const m = eur / 1e6;
    return `€${m >= 100 ? Math.round(m) : m.toFixed(1).replace(/\.0$/, "")}m`;
  }
  if (eur >= 1e3) return `€${Math.round(eur / 1e3)}k`;
  return `€${Math.round(eur)}`;
}

const signed = (pct) => `${pct > 0 ? "+" : "−"}${Math.abs(Math.round(pct))}%`;
const count = (n, word) => `${n.toLocaleString("en-GB")} ${word}${n === 1 ? "" : "s"}`;
const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1).replace(" - ", " — ");
const seasonLabel = (year) => `${year}/${String(year + 1).slice(-2)}`;

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

/* --- the band ---------------------------------------------------------- */

function band(player) {
  const { range, marketValueEur: market, predictedEur: model } = player;
  const top = Math.max(range?.highEur ?? 0, market, model) * 1.08;
  const pct = (value) => Math.min(100, (value / top) * 100);

  const rangeLayer = range
    ? `<div class="band__range" style="left:${pct(range.lowEur)}%;right:${100 - pct(range.highEur)}%"></div>`
    : "";

  const spoken = range
    ? `Model estimate ${money(model)}. The ${Math.round(player.confidence.level * 100)}% range runs from ${money(range.lowEur)} to ${money(range.highEur)}. The market values this player at ${money(market)}, ${player.marketInRange ? "inside" : "outside"} that range.`
    : `Model estimate ${money(model)}. The market values this player at ${money(market)}. No calibrated range available.`;

  return `
    <section class="band" role="img" aria-label="${spoken}">
      <p class="visually-hidden">${spoken}</p>
      <header class="band__head" aria-hidden="true">
        <span>What the model allows</span>
        <span>${range ? `${Math.round(player.confidence.level * 100)}% range` : "range not calibrated"}</span>
      </header>
      <div class="band__track" aria-hidden="true">
        ${rangeLayer}
        <div class="band__marker band__marker--model" style="left:${pct(model)}%">
          <div class="band__flag band__flag--top"><span>Model</span>${money(model)}</div>
        </div>
        <div class="band__marker band__marker--market" style="left:${pct(market)}%">
          <div class="band__flag band__flag--bottom">${money(market)}<span>Market</span></div>
        </div>
      </div>
      <div class="band__scale" aria-hidden="true"><span>€0</span><span>${money(top)}</span></div>
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
  const surname = player.name.split(" ").slice(-1)[0];
  const direction = player.gapPct > 0 ? "more" : "less";

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

function contractLine(player) {
  if (!player.contractExpiry) return "";
  const expiry = new Date(player.contractExpiry);
  const years = (expiry - new Date()) / (365.25 * 24 * 3600 * 1000);
  const when = expiry.toLocaleDateString("en-GB", { month: "short", year: "numeric" });
  return ` · contract to ${when}${years < 1 ? " (under a year)" : ""}`;
}

function seasonsPanel(player) {
  const seasons = player.seasons ?? [];
  if (!seasons.length) {
    return `<section><h2 class="panel__title">Minutes by season</h2>
      <p class="panel__empty">No season on record in the competitions we cover.</p></section>`;
  }

  const peak = Math.max(...seasons.map((s) => s.minutes), 1);
  const rows = seasons
    .map((season) => {
      const isPL = season.competition === "Premier League";
      return `
        <div class="season">
          <span class="season__label">${seasonLabel(season.season)}</span>
          <div class="season__bar">
            <div class="season__fill${isPL ? "" : " season__fill--other"}" style="width:${(season.minutes / peak) * 100}%"></div>
          </div>
          <span class="season__figure">${season.minutes.toLocaleString("en-GB")}′</span>
        </div>`;
    })
    .join("");

  const league = seasons[0].competition;
  return `
    <section>
      <h2 class="panel__title">Minutes by season</h2>
      <div class="seasons">${rows}</div>
      <p class="panel__body">${league === "Premier League" ? "Premier League." : `Outside the Premier League — ${league}.`}</p>
    </section>`;
}

const PEERS_NEEDED = 5;

function peersPanel(player) {
  const peers = player.peers;
  const plural = positionPlural(peers.position);
  const title = `<h2 class="panel__title">Against other ${plural}</h2>`;

  // A percentile drawn from one or two players is theatre, not information.
  if (peers.count < PEERS_NEEDED) {
    const others = peers.count - 1;
    return `<section>${title}
      <p class="panel__empty">
        ${others === 0
          ? `The only ${positionSingular(peers.position)} in the league, so there is nobody to compare against.`
          : `Only ${count(others, "other " + positionSingular(peers.position))} in the league — too few to place this value among.`}
      </p></section>`;
  }

  const percent = Math.round(peers.valuePercentile * 100);
  // Keep the label inside the track when the pin sits at either end.
  const shift = percent > 88 ? "-100%" : percent < 12 ? "0%" : "-50%";
  return `
    <section>${title}
      <div class="peer__scale">
        <div class="peer__pin" style="left:${percent}%">
          <span class="peer__pin-label" style="transform:translateX(${shift})">${money(player.marketValueEur)}</span>
        </div>
      </div>
      <div class="peer__ends"><span>Cheapest</span><span>Most valuable</span></div>
      <p class="panel__body">
        Worth more than ${percent}% of the ${peers.count} ${plural} in the league.
        The median one is valued at ${money(peers.medianValueEur)}.
      </p>
    </section>`;
}

function evidencePanel(player) {
  const { thisSeason, premierLeague, otherLeagues } = player.evidence;
  const rows = [
    [
      `This season (${thisSeason.gameweeks} gameweeks)`,
      thisSeason.known ? `${count(thisSeason.minutes, "minute")} · ${count(thisSeason.starts, "start")}` : null,
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
    <section>
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
  nodes.player.hidden = true;
  nodes.compare.hidden = true;
  nodes.board.hidden = false;
  nodes.player.innerHTML = "";
  nodes.compare.innerHTML = "";
}

async function open(id) {
  closeSuggestions();
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

  const cameFrom = nodes.viewAll.hidden ? "Where it disagrees" : "All players";
  nodes.player.innerHTML = `
    <button class="back" type="button">← ${cameFrom}</button>
    <h1 class="player__name">${player.name}</h1>
    <p class="player__meta">${player.position} · ${player.age} · ${player.nationality} · ${player.club}${contractLine(player)}</p>
    <p class="player__source">“Market” is ${player.marketValueSource ?? "Transfermarkt"}’s published valuation — a community estimate moderated by its editors, not a fee anyone paid.</p>
    ${band(player)}
    ${verdict(player)}
    <div class="panels">
      ${seasonsPanel(player)}
      ${peersPanel(player)}
      ${evidencePanel(player)}
    </div>
    <div class="picker">
      <label class="picker__label" for="compare-with">Put this next to</label>
      <input id="compare-with" list="compare-options" placeholder="another player">
      <datalist id="compare-options"></datalist>
    </div>`;

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

function compareRow(player, top) {
  const pct = (value) => Math.min(100, (value / top) * 100);
  const range = player.range;
  const rangeLayer = range
    ? `<div class="band__range" style="left:${pct(range.lowEur)}%;right:${100 - pct(range.highEur)}%"></div>`
    : "";

  return `
    <div class="compare__row">
      <div class="compare__who">
        <span class="compare__name">${player.name}</span>
        <span class="compare__meta">${player.club} · ${player.position} · ${player.age}</span>
        <span class="compare__figures">market ${money(player.marketValueEur)} · model ${money(player.predictedEur)}</span>
      </div>
      <div class="band__track">
        ${rangeLayer}
        <div class="band__marker band__marker--model" style="left:${pct(player.predictedEur)}%"></div>
        <div class="band__marker band__marker--market" style="left:${pct(player.marketValueEur)}%"></div>
      </div>
    </div>`;
}

async function compare(leftId, rightId) {
  closeSuggestions();
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

  // One scale for both, or the bands would not be comparable.
  const top = Math.max(...pair.map((p) => Math.max(p.range?.highEur ?? 0, p.marketValueEur, p.predictedEur))) * 1.08;

  nodes.compare.innerHTML = `
    <button class="back" type="button">← ${pair[0].name}</button>
    <h1 class="compare__title">${pair[0].name} and ${pair[1].name}</h1>
    <p class="compare__lead">
      Both ranges on one scale. The darker line is the model’s estimate, the
      orange one is the market.
    </p>
    <div class="compare__rows">
      ${pair.map((p) => compareRow(p, top)).join("")}
      <div class="compare__scale"><span>€0</span><span>${money(top)}</span></div>
    </div>`;

  nodes.compare.querySelector(".back").addEventListener("click", () => {
    location.hash = `p${leftId}`;
  });

  nodes.board.hidden = true;
  nodes.player.hidden = true;
  nodes.compare.hidden = false;
  window.scrollTo({ top: 0, behavior: "instant" });
}

function rankList(target, players, kind) {
  target.innerHTML = "";
  players.forEach((player, index) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "rank";
    button.innerHTML = `
      <span class="rank__pos">${String(index + 1).padStart(2, "0")}</span>
      <span><span class="rank__name"></span><span class="rank__club"></span></span>
      <span class="rank__gap rank__gap--${kind}"></span>`;
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
      <span class="grid__gap grid__gap--${player.gapPct > 0 ? "under" : "over"}" role="cell"></span>`;
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

    rankList(nodes.underrated, ranks.underrated, "under");
    rankList(nodes.overrated, ranks.overrated, "over");

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
