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

/** Backend labels are lowercase fragments; the page sets them as sentences. */
const sentence = (text) => text.charAt(0).toUpperCase() + text.slice(1).replace(" - ", " — ");

const signed = (pct) => `${pct > 0 ? "+" : "−"}${Math.abs(Math.round(pct))}%`;
const plural = (n, word) => `${n.toLocaleString("en-GB")} ${word}${n === 1 ? "" : "s"}`;

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
    button.innerHTML = `
      <span class="suggestion__name"></span>
      <span class="suggestion__meta"></span>
      <span class="suggestion__value"></span>`;
    button.querySelector(".suggestion__name").textContent = player.name;
    button.querySelector(".suggestion__meta").textContent = `${player.club} · ${player.position}`;
    button.querySelector(".suggestion__value").textContent = money(player.marketValueEur);
    button.addEventListener("click", () => open(player.id));
    item.appendChild(button);
    nodes.suggestions.appendChild(item);
  }
  nodes.suggestions.hidden = false;
}

function highlight(step) {
  const options = [...nodes.suggestions.querySelectorAll(".suggestion")];
  if (!options.length) return;
  options[highlighted]?.setAttribute("aria-selected", "false");
  highlighted = (highlighted + step + options.length) % options.length;
  const current = options[highlighted];
  current.setAttribute("aria-selected", "true");
  current.scrollIntoView({ block: "nearest" });
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
    const options = [...nodes.suggestions.querySelectorAll(".suggestion")];
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
  const at = (value) => `${Math.min(100, (value / top) * 100)}%`;

  const rangeLayer = range
    ? `<div class="band__range" style="left:${at(range.lowEur)};right:${100 - (Math.min(100, (range.highEur / top) * 100))}%"></div>`
    : "";

  return `
    <section class="band" aria-label="Valuation range">
      <header class="band__head">
        <span>What the model allows</span>
        <span>${range ? `${Math.round(player.confidence.level * 100)}% range` : "range not calibrated"}</span>
      </header>
      <div class="band__track">
        ${rangeLayer}
        <div class="band__marker band__marker--model" style="left:${at(model)}">
          <div class="band__flag band__flag--top"><span>Model</span><b>${money(model)}</b></div>
        </div>
        <div class="band__marker band__marker--market" style="left:${at(market)}">
          <div class="band__flag band__flag--bottom"><b>${money(market)}</b><span>Market</span></div>
        </div>
      </div>
      <div class="band__scale"><span>€0</span><span>${money(top)}</span></div>
    </section>`;
}

/* --- verdict ----------------------------------------------------------- */

function verdict(player) {
  const gap = player.gapPct;
  const name = player.name.split(" ").slice(-1)[0];

  let line;
  if (Math.abs(gap) < 10) {
    line = `The model and the market agree on ${name}, within ${Math.abs(Math.round(gap))}%.`;
  } else {
    const direction = gap > 0 ? "above" : "below";
    line = `The model puts ${name} ${Math.abs(Math.round(gap))}% ${direction} the market’s ${money(player.marketValueEur)}.`;
  }

  const containment =
    player.marketInRange === null
      ? ""
      : player.marketInRange
        ? `The market’s figure sits inside the range the model allows.`
        : `The market’s figure sits <em>outside</em> the range the model allows — the clearest kind of disagreement here.`;

  return `
    <section class="verdict">
      <p class="verdict__line">${line}</p>
      <p class="verdict__confidence">${containment}</p>
      <p class="verdict__confidence">${sentence(player.confidence.summary ?? player.confidence.label)}.</p>
    </section>`;
}

/* --- evidence ---------------------------------------------------------- */

function evidenceRows(player) {
  const { thisSeason, premierLeague, otherLeagues } = player.evidence;
  const rows = [
    [
      `This season (${thisSeason.gameweeks} gameweeks)`,
      thisSeason.known
        ? `${plural(thisSeason.minutes, "minute")} · ${plural(thisSeason.starts, "start")}`
        : null,
      "Not in this season’s squad data",
    ],
    [
      "Premier League record",
      premierLeague.known
        ? `${plural(premierLeague.seasons, "season")} · ${plural(premierLeague.minutes, "minute")} · ${premierLeague.goals}G ${premierLeague.assists}A`
        : null,
      "No Premier League record in the seasons we cover",
    ],
    [
      "Other leagues",
      otherLeagues.known
        ? `${plural(otherLeagues.seasons, "season")} · ${plural(otherLeagues.minutes, "minute")} · ${otherLeagues.goals}G ${otherLeagues.assists}A`
        : null,
      "No record in the other leagues we cover",
    ],
  ];

  return rows
    .map(
      ([label, value, absent]) => `
      <div class="evidence__row">
        <span class="evidence__label">${label}</span>
        <span class="evidence__value${value ? "" : " evidence__value--absent"}">${value ?? absent}</span>
      </div>`,
    )
    .join("");
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
    <section class="evidence">
      <h2 class="evidence__title">What the model had to go on</h2>
      <div class="evidence__rows">${evidenceRows(player)}</div>
    </section>`;

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
      `Players under ${money(ranks.minValueEur)} are left out: a percentage gap on a cheap squad player is mostly noise.`;
    nodes.colophon.textContent =
      `Cross-validated on ${meta.players} players: R² ${meta.model.r2Log} on log value, average miss ${money(meta.model.maeEur)}. ` +
      `Every estimate is made by a model that never saw that player.`;

    rankList(nodes.underrated, ranks.underrated, "under");
    rankList(nodes.overrated, ranks.overrated, "over");

    route();
    window.addEventListener("hashchange", route);
  } catch (error) {
    document.getElementById("main").innerHTML =
      `<p class="notice">Can’t reach the model server. Start it with <code>uvicorn backend.api:app</code>, then reload.</p>`;
  }
})();
