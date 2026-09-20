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
};

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
    else if (name.includes(q) || p.club.toLowerCase().includes(q)) contains.push(p);
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

  return `
    <section class="band" aria-label="Valuation range">
      <header class="band__head">
        <span>What the model allows</span>
        <span>${range ? `${Math.round(player.confidence.level * 100)}% range` : "range not calibrated"}</span>
      </header>
      <div class="band__track">
        ${rangeLayer}
        <div class="band__marker band__marker--model" style="left:${pct(model)}%">
          <div class="band__flag band__flag--top"><span>Model</span>${money(model)}</div>
        </div>
        <div class="band__marker band__marker--market" style="left:${pct(market)}%">
          <div class="band__flag band__flag--bottom">${money(market)}<span>Market</span></div>
        </div>
      </div>
      <div class="band__scale"><span>€0</span><span>${money(top)}</span></div>
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
      <p class="verdict__confidence">${sentence(player.confidence.summary ?? player.confidence.label)}.</p>
    </section>`;
}

/* --- panels ------------------------------------------------------------ */

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
      <p class="peer__body">${league === "Premier League" ? "Premier League." : `Outside the Premier League — ${league}.`}</p>
    </section>`;
}

function peersPanel(player) {
  const peers = player.peers;
  const percent = Math.round(peers.valuePercentile * 100);
  const role = peers.position.toLowerCase();
  return `
    <section>
      <h2 class="panel__title">Against other ${role}s</h2>
      <div class="peer__scale">
        <div class="peer__pin" style="left:${percent}%">
          <span class="peer__pin-label">${money(player.marketValueEur)}</span>
        </div>
      </div>
      <div class="peer__ends"><span>Cheapest</span><span>Most valuable</span></div>
      <p class="peer__body">
        Worth more than ${percent}% of the ${peers.count} ${role}s in the league.
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
  nodes.board.hidden = false;
  nodes.player.innerHTML = "";
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

  nodes.player.innerHTML = `
    <button class="back" type="button">← All players</button>
    <h1 class="player__name">${player.name}</h1>
    <p class="player__meta">${player.position} · ${player.age} · ${player.nationality} · ${player.club}</p>
    ${band(player)}
    ${verdict(player)}
    <div class="panels">
      ${seasonsPanel(player)}
      ${peersPanel(player)}
      ${evidencePanel(player)}
    </div>`;

  nodes.player.querySelector(".back").addEventListener("click", () => {
    location.hash = "";
  });

  nodes.board.hidden = true;
  nodes.player.hidden = false;
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
    nodes.gridRows.innerHTML = `<p class="panel__empty">No player matches both filters. Widen one of them.</p>`;
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const player of rows) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "grid__row";
    button.setAttribute("role", "row");
    button.innerHTML = `
      <span><span class="grid__name"></span><span class="grid__meta"></span></span>
      <span class="grid__figure"></span>
      <span class="grid__figure"></span>
      <span class="grid__gap grid__gap--${player.gapPct > 0 ? "under" : "over"}"></span>`;
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

function switchView(view) {
  for (const button of document.querySelectorAll(".view")) {
    button.setAttribute("aria-pressed", String(button.dataset.view === view));
  }
  nodes.viewGaps.hidden = view !== "gaps";
  nodes.viewAll.hidden = view !== "all";
  if (view === "all") renderGrid();
}

function route() {
  const match = location.hash.match(/^#p(\d+)$/);
  if (match) open(Number(match[1]));
  else showBoard();
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
      control.addEventListener("change", renderGrid);
    }

    route();
    window.addEventListener("hashchange", route);
  } catch {
    el("main").innerHTML =
      `<p class="notice">Can’t reach the model server. Start it with <code>uvicorn backend.api:app</code>, then reload.</p>`;
  }
})();
