/* Showcase console renderer.
 *
 * The split that makes this work: events arrive from the server as fast as the database
 * can produce them, and are queued. A separate loop drains that queue slowly, typing
 * lines out character by character. So the reveal is paced without the server ever
 * pretending to be slow -- the stage timings printed in the rail are real.
 *
 * It also means the speed control is instant. Switching to 4x or "skip" does not
 * re-request anything; it just drains the queue faster, and "skip" empties it in one go.
 */

const SPEED_KEY = "showcase-speed";
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
  return window.innerHeight + window.scrollY >= document.body.offsetHeight - 140;
}

/* Follow the output, but stop the moment the reader scrolls up to read something --
 * yanking the viewport back down while someone is reading a table is hostile. */
function follow(wasAtBottom) {
  if (wasAtBottom) window.scrollTo({ top: document.body.scrollHeight, behavior: "instant" });
}

// --------------------------------------------------------------------------- //
// renderers
// --------------------------------------------------------------------------- //
async function typeInto(node, text) {
  if (state.speed === 0) {
    node.textContent = text;
    return;
  }
  const cursor = document.createElement("span");
  cursor.className = "cursor";
  node.appendChild(cursor);

  // Typing one character per frame is unreadably slow past a short line, so the chunk
  // size grows with length: a long sentence still lands in about the same time.
  const chunk = Math.max(1, Math.ceil(text.length / 90));
  for (let i = 0; i < text.length; i += chunk) {
    const wasDown = atBottom();
    cursor.insertAdjacentText("beforebegin", text.slice(i, i + chunk));
    follow(wasDown);
    await pace(16);
  }
  cursor.remove();
}

async function renderStage(ev) {
  state.stageIndex += 1;
  const head = document.createElement("div");
  head.className = "stage-head";
  head.innerHTML = `<div class="idx"></div><h2></h2><div class="sub"></div>`;
  el.console.appendChild(head);

  head.querySelector(".idx").textContent =
    `STAGE ${String(state.stageIndex).padStart(2, "0")}`;
  await pace(90);
  await typeInto(head.querySelector("h2"), ev.title);
  await typeInto(head.querySelector(".sub"), ev.subtitle);
  markStage(ev.id, "running");
  await pace(180);
}

async function renderLine(ev) {
  const node = document.createElement("div");
  node.className = `ln ${ev.cls || ""}`.trim();
  el.console.appendChild(node);
  await typeInto(node, ev.text);
  await pace(110);
}

async function renderMetric(ev) {
  const node = document.createElement("div");
  node.className = `metric ${ev.cls || ""}`.trim();
  node.innerHTML = `<span class="k"></span><span class="v"></span>`;
  if (ev.note) node.insertAdjacentHTML("beforeend", `<span class="note"></span>`);
  el.console.appendChild(node);

  node.querySelector(".k").textContent = ev.label;
  await pace(70);
  await typeInto(node.querySelector(".v"), ev.value);
  if (ev.note) {
    node.querySelector(".note").textContent = ev.note;
  }
  await pace(140);
}

async function renderTable(ev) {
  const wasDown = atBottom();
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
  el.console.appendChild(t);
  follow(wasDown);

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
    const down = atBottom();
    tbody.appendChild(tr);
    follow(down);
    await pace(85);
  }
  await pace(180);
}

async function renderStageDone(ev) {
  markStage(ev.id, "done", `${ev.ms} ms`);
  await pace(200);
}

async function renderDone(ev) {
  const node = document.createElement("div");
  node.className = "summary";
  el.console.appendChild(node);
  await typeInto(
    node,
    ev.ok ? "Pipeline walk complete." : "Pipeline walk ended early."
  );
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent =
    `${ev.ms} ms of real query time. Every figure above was read from the warehouse ` +
    `just now — only the pacing of this console is for show.`;
  node.appendChild(meta);
  finish();
}

const RENDERERS = {
  stage: renderStage,
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
