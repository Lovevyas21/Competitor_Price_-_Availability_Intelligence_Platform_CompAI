/* Showcase console renderer.
 *
 * The split that makes this work: events arrive from the server as fast as the database
 * can produce them, and are queued. A separate loop drains that queue slowly, typing
 * lines out character by character. So the reveal is paced without the server ever
 * pretending to be slow -- the stage timings printed in the rail are real.
 *
 * It also means the speed control is instant. Switching to 4x or "skip" does not
 * re-request anything; it just drains the queue faster, and "skip" empties it in one go.
 *
 * The boot sequence before each stage is the one piece of pure theatre in the whole
 * project, and it is deliberately confined to this file -- the presentation layer -- so
 * that nothing on the server is ever tempted to stall to match it. Two rules keep it
 * from becoming a lie: the status lines describe what that stage genuinely concerns
 * itself with rather than inventing work, and they erase themselves once the stage
 * resolves, so the transcript a reviewer scrolls back through is all real output.
 */

const SPEED_KEY = "showcase-speed";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* Per-stage boot lines. Each one names something that stage actually does: the freshness
 * gate, the cooldown window and the currency normalisation below are all real behaviour
 * of the pipeline, not decoration invented to fill the bar. */
const BOOT = {
  connect: [
    "opening tls channel",
    "authenticating role",
    "reserving connection from pool",
    "resolving partition catalogue",
  ],
  extract: [
    "attaching to price_events partitions",
    "scanning the observation window",
    "resolving current product versions",
    "grouping by retailer and currency",
  ],
  resolve: [
    "reading the match ledger",
    "embedding space · 384d · hnsw",
    "walking the confidence bands",
    "separating automatic from review",
  ],
  compare: [
    "joining matched pairs",
    "normalising within currency",
    "computing gap percentages",
    "ranking by severity",
  ],
  decide: [
    "applying the freshness gate",
    "fingerprinting active undercuts",
    "checking the cooldown window",
    "resolving delivery channels",
  ],
  narrate: [
    "assembling the facts payload",
    "reasoning disabled · single call",
    "handing the model a closed set of numbers",
    "arming the numeric guard",
  ],
};

const SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏";

const state = {
  speed: reduceMotion ? 0 : Number(sessionStorage.getItem(SPEED_KEY) ?? 1),
  queue: [],
  draining: false,
  running: false,
  source: null,
  stageIndex: 0,
};

const el = {
  console: document.getElementById("console"),
  rail: document.getElementById("rail"),
  run: document.getElementById("run"),
  speed: document.getElementById("speed"),
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* Every delay in the renderer goes through here, so one control governs all of it.
 * Speed 0 means "no theatre": every wait collapses to nothing. */
const pace = (ms) => (state.speed === 0 ? Promise.resolve() : sleep(ms / state.speed));

function atBottom() {
  return window.innerHeight + window.scrollY >= document.body.offsetHeight - 160;
}

/* Follow the output, but stop the moment the reader scrolls up to read something --
 * yanking the viewport back down while someone is reading a table is hostile. */
function follow(wasAtBottom) {
  if (wasAtBottom) window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" });
}

/* Append with the entrance animation, and keep the viewport pinned across the insertion
 * so a growing page never jumps under the reader. */
function appendTo(parent, node) {
  const wasDown = atBottom();
  parent.appendChild(node);
  follow(wasDown);
  return node;
}

// --------------------------------------------------------------------------- //
// typing
// --------------------------------------------------------------------------- //
async function typeInto(node, text) {
  if (state.speed === 0) {
    node.textContent = text;
    return;
  }
  const cursor = document.createElement("span");
  cursor.className = "cursor";
  node.appendChild(cursor);

  // One character at a time is unreadably slow past a short line, so the chunk grows
  // with length -- but gently, so a long sentence still visibly types rather than
  // arriving in four lurches.
  const chunk = Math.max(1, Math.ceil(text.length / 55));
  for (let i = 0; i < text.length; i += chunk) {
    const wasDown = atBottom();
    cursor.insertAdjacentText("beforebegin", text.slice(i, i + chunk));
    follow(wasDown);
    await pace(26);
  }
  cursor.remove();
}

// --------------------------------------------------------------------------- //
// boot sequence
// --------------------------------------------------------------------------- //
async function runBoot(id) {
  const steps = BOOT[id];
  // Skipping and reduced-motion both bypass this entirely: it is the part of the page
  // with the least information per second, so it is the first thing to go.
  if (!steps || state.speed === 0) return;

  const box = appendTo(
    el.console,
    Object.assign(document.createElement("div"), {
      className: "boot",
      innerHTML:
        `<div class="boot-row"><span class="spin"></span>` +
        `<span class="boot-text"></span><span class="boot-count"></span></div>` +
        `<div class="boot-bar"><i></i></div>`,
    })
  );

  const spin = box.querySelector(".spin");
  const label = box.querySelector(".boot-text");
  const count = box.querySelector(".boot-count");
  const bar = box.querySelector(".boot-bar i");

  const ticker = setInterval(() => {
    spin.textContent = SPIN[(Number(spin.dataset.f || 0) % SPIN.length) | 0];
    spin.dataset.f = Number(spin.dataset.f || 0) + 1;
  }, 70);

  for (let i = 0; i < steps.length; i++) {
    label.classList.remove("in");
    await pace(90);
    label.textContent = steps[i];
    count.textContent = `${i + 1}/${steps.length}`;
    label.classList.add("in");
    bar.style.width = `${((i + 1) / steps.length) * 100}%`;
    await pace(480);
  }

  clearInterval(ticker);
  spin.textContent = "✓";
  spin.classList.add("done");
  label.textContent = "ready";
  await pace(320);

  // Erased rather than kept. What stays on the page after a run should be the output,
  // not four lines of scenery.
  box.classList.add("out");
  await pace(340);
  box.remove();
}

// --------------------------------------------------------------------------- //
// renderers
// --------------------------------------------------------------------------- //
async function renderStage(ev) {
  state.stageIndex += 1;
  markStage(ev.id, "running");

  const head = appendTo(
    el.console,
    Object.assign(document.createElement("div"), {
      className: "stage-head",
      innerHTML: `<div class="idx"></div><h2></h2><div class="sub"></div>`,
    })
  );

  head.querySelector(".idx").textContent =
    `STAGE ${String(state.stageIndex).padStart(2, "0")}`;
  await pace(220);
  await typeInto(head.querySelector("h2"), ev.title);
  await pace(120);
  await typeInto(head.querySelector(".sub"), ev.subtitle);
  await pace(300);

  await runBoot(ev.id);
  await pace(160);
}

async function renderLine(ev) {
  const node = appendTo(
    el.console,
    Object.assign(document.createElement("div"), {
      className: `ln ${ev.cls || ""}`.trim(),
    })
  );
  await typeInto(node, ev.text);
  await pace(190);
}

async function renderMetric(ev) {
  const node = appendTo(
    el.console,
    Object.assign(document.createElement("div"), {
      className: `metric ${ev.cls || ""}`.trim(),
      innerHTML: `<span class="k"></span><span class="v"></span>`,
    })
  );
  if (ev.note) node.insertAdjacentHTML("beforeend", `<span class="note"></span>`);

  node.querySelector(".k").textContent = ev.label;
  await pace(130);
  await typeInto(node.querySelector(".v"), ev.value);
  if (ev.note) {
    const note = node.querySelector(".note");
    note.textContent = ev.note;
    // Fades in after the number rather than with it, so the eye lands on the figure
    // first and the explanation second.
    requestAnimationFrame(() => note.classList.add("in"));
  }
  await pace(240);
}

async function renderTable(ev) {
  const t = document.createElement("table");
  if (ev.caption) {
    const cap = document.createElement("caption");
    cap.textContent = ev.caption;
    t.appendChild(cap);
  }
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  for (const c of ev.cols) {
    const th = document.createElement("th");
    th.textContent = c;
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  t.appendChild(thead);
  const tbody = document.createElement("tbody");
  t.appendChild(tbody);
  appendTo(el.console, t);
  await pace(240);

  // Rows land one at a time. This is the moment the page most looks like something is
  // being discovered, and it costs nothing but a short stagger.
  for (const row of ev.rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      const td = document.createElement("td");
      td.textContent = cell;
      td.title = cell;
      tr.appendChild(td);
    }
    appendTo(tbody, tr);
    await pace(130);
  }
  await pace(300);
}

async function renderStageDone(ev) {
  markStage(ev.id, "done", `${ev.ms} ms`);
  await pace(420);
}

async function renderDone(ev) {
  const node = appendTo(
    el.console,
    Object.assign(document.createElement("div"), { className: "summary" })
  );
  await typeInto(node, ev.ok ? "Pipeline walk complete." : "Pipeline walk ended early.");
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent =
    `${ev.ms} ms of real query time. Every figure above was read from the warehouse ` +
    `just now — only the pacing of this console is for show.`;
  node.appendChild(meta);
  requestAnimationFrame(() => meta.classList.add("in"));
  finish();
}

async function renderProse(ev) {
  const box = appendTo(
    el.console,
    Object.assign(document.createElement("div"), {
      className: "prose",
      innerHTML:
        `<div class="prose-head"></div><div class="prose-body"></div>` +
        `<div class="prose-note"></div>`,
    })
  );
  if (ev.title) box.querySelector(".prose-head").textContent = ev.title;

  // Rendered a line at a time rather than typed character by character. A page of
  // generated prose typed out at reading speed is a minute of waiting for something
  // the reader can already see is text.
  const body = box.querySelector(".prose-body");
  for (const raw of ev.body.split("\n")) {
    const row = document.createElement("div");
    const heading = /^#{1,6}\s/.test(raw);
    row.className = heading ? "prose-h" : "prose-p";
    row.textContent = raw.replace(/^#{1,6}\s*/, "").replace(/\*\*/g, "");
    appendTo(body, row);
    await pace(raw.trim() ? 60 : 20);
  }
  if (ev.note) {
    const note = box.querySelector(".prose-note");
    note.textContent = ev.note;
    requestAnimationFrame(() => note.classList.add("in"));
  }
  await pace(300);
}

const RENDERERS = {
  stage: renderStage,
  prose: renderProse,
  line: renderLine,
  metric: renderMetric,
  table: renderTable,
  stage_done: renderStageDone,
  done: renderDone,
};

// --------------------------------------------------------------------------- //
// queue
// --------------------------------------------------------------------------- //
async function drain() {
  if (state.draining) return;
  state.draining = true;
  while (state.queue.length) {
    const ev = state.queue.shift();
    const render = RENDERERS[ev.t];
    if (render) await render(ev);
  }
  state.draining = false;
}

function markStage(id, status, ms) {
  const item = el.rail.querySelector(`[data-stage="${id}"]`);
  if (!item) return;
  item.dataset.state = status;
  if (ms) item.querySelector(".stage-ms").textContent = ms;
}

// --------------------------------------------------------------------------- //
// run control
// --------------------------------------------------------------------------- //
function finish() {
  state.running = false;
  el.run.disabled = false;
  el.run.textContent = "Run again";
  const fetchBtn = document.getElementById("fetch");
  if (fetchBtn) {
    fetchBtn.disabled = false;
    fetchBtn.textContent = "↻ Fetch data";
  }
}

function start() {
  if (state.running) return;
  state.running = true;
  state.queue = [];
  state.stageIndex = 0;
  el.console.innerHTML = "";
  el.run.disabled = true;
  el.run.textContent = "Running…";
  for (const item of el.rail.querySelectorAll(".stage-item")) {
    item.dataset.state = "idle";
    item.querySelector(".stage-ms").textContent = "";
  }

  const source = new EventSource("/showcase/api/stream");
  state.source = source;

  source.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    // Closed here, on receipt, not when the last event finishes rendering. An
    // EventSource whose stream simply ends will reconnect and run the whole pipeline
    // again -- which would be a confusing thing to watch happen by itself.
    if (ev.t === "done") source.close();
    state.queue.push(ev);
    drain();
  };

  source.onerror = () => {
    source.close();
    if (!state.running) return;
    state.queue.push({
      t: "line",
      cls: "err",
      text: "connection to the server was lost — is the API still running?",
    });
    state.queue.push({ t: "done", ms: 0, ok: false });
    drain();
  };
}

function setSpeed(value) {
  state.speed = value;
  sessionStorage.setItem(SPEED_KEY, String(value));
  for (const b of el.speed.querySelectorAll("button")) {
    b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === value));
  }
}

el.run.addEventListener("click", start);
el.speed.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-speed]");
  if (b) setSpeed(Number(b.dataset.speed));
});

setSpeed(state.speed);

// Arriving with ?autorun (the intro button's link) starts immediately, so the walkthrough
// is one click from the front page rather than two.
if (new URLSearchParams(location.search).has("autorun")) start();

// --------------------------------------------------------------------------- //
// live fetch from Open Prices
// --------------------------------------------------------------------------- //
/* Reuses the console renderer wholesale. The fetch stream emits the same event shapes
 * as the pipeline, so it types itself out into the same panel with no separate view to
 * keep in step. */
function startFetch() {
  if (state.running) return;
  state.running = true;
  state.queue = [];
  state.stageIndex = 0;
  el.console.innerHTML = "";
  el.run.disabled = true;
  const btn = document.getElementById("fetch");
  btn.disabled = true;
  btn.textContent = "Fetching…";

  const source = new EventSource("/showcase/api/fetch");
  source.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    if (ev.t === "done") source.close();
    state.queue.push(ev);
    drain();
  };
  source.onerror = () => {
    source.close();
    if (!state.running) return;
    state.queue.push({ t: "line", cls: "err", text: "the fetch connection dropped" });
    state.queue.push({ t: "done", ms: 0, ok: false });
    drain();
  };
}

// --------------------------------------------------------------------------- //
// data viewer
// --------------------------------------------------------------------------- //
async function openSheet() {
  const sheet = document.getElementById("sheet");
  const body = document.getElementById("sheet-body");
  sheet.hidden = false;
  body.innerHTML = `<div class="ln dim">loading…</div>`;

  try {
    const res = await fetch("/showcase/api/dataset?limit=500");
    const data = await res.json();
    if (!data.rows.length) {
      body.innerHTML = `<div class="ln warn">No observations stored yet.</div>`;
      return;
    }
    const cols = Object.keys(data.rows[0]);
    // Built as DOM rather than an HTML string: product titles are upstream text and
    // would otherwise be a markup-injection route straight from a third-party API.
    const table = document.createElement("table");
    const head = table.createTHead().insertRow();
    for (const c of cols) {
      const th = document.createElement("th");
      th.textContent = c;
      head.appendChild(th);
    }
    const tbody = table.createTBody();
    for (const row of data.rows) {
      const tr = tbody.insertRow();
      for (const c of cols) {
        const td = tr.insertCell();
        td.textContent = row[c] ?? "";
        td.title = td.textContent;
      }
    }
    body.innerHTML = "";
    body.appendChild(table);
    document.getElementById("sheet-title").textContent =
      `Collected observations — showing ${data.count.toLocaleString()} most recent`;
  } catch (e) {
    body.innerHTML = `<div class="ln err">could not load the data: ${e}</div>`;
  }
}

// --------------------------------------------------------------------------- //
// ask about the data
// --------------------------------------------------------------------------- //
function chatSay(who, text, cls = "") {
  const log = document.getElementById("dock-log");
  const row = document.createElement("div");
  row.className = `chat ${who} ${cls}`.trim();
  row.textContent = text;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return row;
}

async function ask(question) {
  chatSay("you", question);
  const pending = chatSay("bot", "…", "pending");
  const send = document.getElementById("dock-send");
  send.disabled = true;

  try {
    const res = await fetch("/showcase/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const data = await res.json();
    pending.classList.remove("pending");
    pending.textContent = data.answer;
    if (!data.ok) pending.classList.add(data.source === "refused" ? "refused" : "warn");
    if (data.ok && data.checked) {
      const tag = document.createElement("span");
      tag.className = "chat-tag";
      tag.textContent = `${data.checked} figures verified against the warehouse`;
      pending.appendChild(tag);
    }
  } catch (e) {
    pending.classList.remove("pending");
    pending.classList.add("warn");
    pending.textContent = `could not reach the server: ${e}`;
  } finally {
    send.disabled = false;
  }
}

// --------------------------------------------------------------------------- //
// wiring
// --------------------------------------------------------------------------- //
document.getElementById("fetch").addEventListener("click", startFetch);
document.getElementById("data").addEventListener("click", openSheet);
document.getElementById("sheet-close").addEventListener("click", () => {
  document.getElementById("sheet").hidden = true;
});

const dockPanel = document.getElementById("dock-panel");
const dockTab = document.getElementById("dock-tab");
dockTab.addEventListener("click", () => {
  dockPanel.hidden = !dockPanel.hidden;
  dockTab.hidden = !dockPanel.hidden;
  if (!dockPanel.hidden) document.getElementById("dock-input").focus();
});
document.getElementById("dock-close").addEventListener("click", () => {
  dockPanel.hidden = true;
  dockTab.hidden = false;
});
document.getElementById("dock-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("dock-input");
  const q = input.value.trim();
  if (!q) return;
  input.value = "";
  ask(q);
});
