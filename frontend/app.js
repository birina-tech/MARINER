/*
 * app.js — MARINER_2 frontend
 *
 * Replaces canvas.py (matplotlib) + dialogs.py (AddShipDialog/ControlDialog)
 * + llm_decisions_window.py's table with a plain WebSocket + <canvas> client.
 * See WEBSOCKET_PROTOCOL.md for the full message schema this speaks.
 *
 * Drawing is to scale: hulls are polygons in world metres (length and beam of
 * each vessel class), the scale bar and range rings are in real distance, and
 * when a hull would be too small to see, a fixed-size heading symbol is drawn
 * instead (as on an ECDIS / radar display).
 */

// ---------------------------------------------------------------- constants

const KN_PER_MS = 1 / 0.514444;
const M_PER_NM = 1852;
const MAX_TRAIL_POINTS = 600;
const MIN_HULL_PX = 14;          // below this on-screen length, draw a symbol instead
const MIN_ZOOM = 0.003;          // px per metre (about 333 m per pixel)
const MAX_ZOOM = 6;              // px per metre

// Hull colours picked for contrast on the dark plot background.
const COLORS = {
  blue: "#4aa3ff", red: "#ff5a4e", green: "#35d68a", orange: "#ff9f43",
  purple: "#b07cff", brown: "#c8885a", pink: "#ff8ad0", gray: "#a0a8a8",
};
const shipColor = (ship) => COLORS[ship.color] || ship.color;

// ------------------------------------------------------------------- state

let ws = null;
let selectedShip = null;
let routeDrawing = null;   // { shipName, points: [[x,y], ...] } while the user is laying out a path
let latestState = null;
let vesselClasses = [];    // class catalogue from the server's hello message
let vectorMinutes = 6;     // speed-vector length, minutes (0 = off)
let fitPending = false;    // zoom to fit on the next state (after loading a scenario)
let showReasoning = false; // draw the LLM reasoning bubbles
const trails = new Map();  // shipName -> [[x,y], ...] (client-side, capped)

// ---------------------------------------------------------------- WebSocket

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => setConn(true);
  ws.onclose = () => { setConn(false); setTimeout(connect, 1500); };
  ws.onerror = () => ws.close();

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === "state") {
      onState(msg);
    } else if (msg.type === "hello") {
      populateProviderAndPromptSelects(msg.llm_providers, msg.llm_prompts);
      vesselClasses = msg.vessel_classes || [];
      populateClassSelect();
      send({ type: "list_scenarios" });
    } else if (msg.type === "error") {
      console.warn("Server error:", msg.message, msg);
      alert(msg.message || "Command failed");
    } else if (msg.type === "ack") {
      if (msg.of === "list_scenarios") {
        populateScenarioList(msg.scenarios);
      } else if (msg.of === "save_scenario") {
        send({ type: "list_scenarios" }); // refresh so the new save shows up
      } else if (msg.of === "load_scenario" && msg.ok) {
        fitPending = true;
      } else if (!msg.ok) {
        alert(msg.message || `${msg.of} failed`);
      }
    }
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function populateProviderAndPromptSelects(providers, prompts) {
  const providerSelect = document.getElementById("llm-provider");
  if (providers && providers.length) {
    providerSelect.innerHTML = "";
    for (const p of providers) {
      const opt = document.createElement("option");
      opt.value = p; opt.textContent = p;
      if (p === "groq") opt.selected = true;
      providerSelect.appendChild(opt);
    }
  }

  const promptSelect = document.getElementById("llm-prompt");
  promptSelect.innerHTML = "";
  for (const name of prompts) {
    const opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    if (name === "vts_default") opt.selected = true;
    promptSelect.appendChild(opt);
  }
}

function populateScenarioList(names) {
  const select = document.getElementById("scenario-list");
  const previous = select.value;
  select.innerHTML = "";
  for (const name of names) {
    const opt = document.createElement("option");
    opt.value = name; opt.textContent = name;
    select.appendChild(opt);
  }
  if (names.includes(previous)) select.value = previous;
}

function setConn(ok) {
  document.getElementById("conn-dot").className = "dot " + (ok ? "dot-on" : "dot-off");
  document.getElementById("conn-label").textContent = ok ? "connected" : "reconnecting…";
}

// ------------------------------------------------------------- state intake

function onState(msg) {
  latestState = msg;

  document.getElementById("sim-time").textContent = `t = ${msg.sim_time.toFixed(1)} s`;
  document.getElementById("btn-play-pause").textContent = msg.running ? "⏸ Pause" : "▶ Run";

  const llmDot = document.getElementById("llm-dot");
  const llmLabel = document.getElementById("llm-label");
  if (msg.llm_pending) {
    llmDot.className = "dot dot-busy"; llmLabel.textContent = "LLM thinking…";
  } else if (msg.llm_status === "error") {
    llmDot.className = "dot dot-err"; llmLabel.textContent = "LLM error";
  } else if (msg.llm_status === "ok") {
    llmDot.className = "dot dot-on"; llmLabel.textContent = "LLM ok";
  } else if (!msg.llm_configured && msg.ships.some(s => s.control_mode === "llm")) {
    // A vessel is in LLM mode but no provider has been applied: it would never be commanded.
    llmDot.className = "dot dot-busy"; llmLabel.textContent = "LLM not configured: choose a provider and click Apply";
  } else {
    llmDot.className = "dot dot-off"; llmLabel.textContent = "LLM idle";
  }

  for (const ship of msg.ships) {
    if (!trails.has(ship.name)) trails.set(ship.name, []);
    const t = trails.get(ship.name);
    t.push([ship.x, ship.y]);
    if (t.length > MAX_TRAIL_POINTS) t.shift();
  }
  // drop trails for ships that no longer exist
  const liveNames = new Set(msg.ships.map(s => s.name));
  for (const name of Array.from(trails.keys())) {
    if (!liveNames.has(name)) trails.delete(name);
  }

  if (selectedShip && !liveNames.has(selectedShip)) selectedShip = null;

  if (fitPending && msg.ships.length > 0) { fitView(); fitPending = false; }

  renderVesselList(msg.ships);
  renderControlPanel(msg.ships);
  renderColregsTable(msg.collision_pairs);
}

// -------------------------------------------------------------- side panels

function renderVesselList(ships) {
  const list = document.getElementById("vessel-list");
  list.innerHTML = "";
  for (const ship of ships) {
    const row = document.createElement("div");
    row.className = "vessel-row" + (ship.name === selectedShip ? " selected" : "");
    row.dataset.name = ship.name;   // selection is handled by delegation, see below

    const swatch = document.createElement("div");
    swatch.className = "vessel-swatch";
    swatch.style.background = shipColor(ship);
    row.appendChild(swatch);

    const text = document.createElement("div");
    text.className = "vessel-text";
    const name = document.createElement("div");
    name.className = "vessel-name";
    name.textContent = ship.name;
    const sub = document.createElement("div");
    sub.className = "vessel-sub";
    sub.textContent =
      `${ship.class_name} · ${(ship.speed_ms * KN_PER_MS).toFixed(1)} kn · ${ship.heading_deg.toFixed(0).padStart(3, "0")}°`;
    text.appendChild(name);
    text.appendChild(sub);
    row.appendChild(text);

    const modeBadge = document.createElement("span");
    const modeClass = { straight: "", route: "badge-route", manual: "badge-manual", llm: "badge-llm" }[ship.control_mode] || "";
    modeBadge.className = "vessel-badge " + modeClass;
    modeBadge.textContent = ship.control_mode.toUpperCase();
    row.appendChild(modeBadge);

    if (ship.in_maneuver) {
      const b = document.createElement("span");
      b.className = "vessel-badge badge-maneuver"; b.textContent = "MNVR";
      row.appendChild(b);
    }
    list.appendChild(row);
  }
}

// The list is rebuilt on every state message (20x per second). A click needs
// mouse-down and mouse-up on the *same* element, so per-row click handlers
// lose many clicks. Handle mouse-down once on the persistent container instead.
document.getElementById("vessel-list").addEventListener("mousedown", (e) => {
  const row = e.target.closest(".vessel-row");
  if (!row || !latestState) return;
  selectedShip = row.dataset.name;
  renderVesselList(latestState.ships);
  renderControlPanel(latestState.ships);
});

function renderControlPanel(ships) {
  const target = document.getElementById("control-target");
  const ship = ships.find(s => s.name === selectedShip);
  const modeSelect = document.getElementById("control-mode-select");
  const manualHint = document.getElementById("manual-hint");
  const routeButtons = document.getElementById("route-buttons");
  const info = document.getElementById("vessel-info");

  if (!ship) {
    target.textContent = "— none selected —";
    info.textContent = "Select a vessel on the map or in the list.";
    manualHint.classList.add("hidden");
    return;
  }

  target.textContent = ship.name;
  info.textContent = [
    `${ship.class_name} (${ship.loading})`,
    `${ship.length.toFixed(0)} × ${ship.beam.toFixed(0)} m · draft ${ship.draft.toFixed(1)} m · ${Math.round(ship.displacement_t).toLocaleString()} t`,
    `HDG ${ship.heading_deg.toFixed(0).padStart(3, "0")}°  SOG ${(ship.speed_ms * KN_PER_MS).toFixed(1)} kn (max ${(ship.max_speed_ms * KN_PER_MS).toFixed(1)})`,
    `ROT ${ship.rot_deg_min >= 0 ? "+" : ""}${ship.rot_deg_min.toFixed(1)}°/min`,
    `Rudder ${ship.rudder_angle.toFixed(1)}° (ordered ${ship.rudder_cmd.toFixed(0)}°)`,
    `Engine ${ship.rpm_actual.toFixed(0)}% (ordered ${ship.rpm_cmd.toFixed(0)}%)`,
  ].join("\n");

  const rudderSlider = document.getElementById("rudder-slider");
  const rpmSlider = document.getElementById("rpm-slider");
  rpmSlider.min = ship.rpm_min;

  // Don't fight the user while they're actively dragging a slider or picking a mode.
  if (document.activeElement !== rudderSlider) {
    rudderSlider.value = ship.rudder_cmd;
    document.getElementById("rudder-val").textContent = `${ship.rudder_cmd.toFixed(0)}°`;
  }
  if (document.activeElement !== rpmSlider) {
    rpmSlider.value = ship.rpm_cmd;
    document.getElementById("rpm-val").textContent = `${ship.rpm_cmd.toFixed(0)}%`;
  }
  if (document.activeElement !== modeSelect && !routeDrawing) {
    modeSelect.value = ship.control_mode;
  }

  manualHint.classList.toggle("hidden", ship.control_mode !== "manual");
  routeButtons.querySelector("#btn-clear-path").disabled = !ship.has_route;
}

function renderColregsTable(pairs) {
  const tbody = document.querySelector("#colregs-table tbody");
  tbody.innerHTML = "";
  for (const p of pairs) {
    const tr = document.createElement("tr");
    tr.className = p.risk > 0.7 ? "risk-high" : (p.risk > 0.4 ? "risk-med" : "");
    const tcpaStr = p.tcpa_s === null ? "—" : p.tcpa_s.toFixed(0) + "s";
    tr.innerHTML = `
      <td>${p.ship1}↔${p.ship2}</td>
      <td>${p.dist_m.toFixed(0)}m</td>
      <td>${p.dcpa_m.toFixed(0)}m</td>
      <td>${tcpaStr}</td>
      <td>${p.risk.toFixed(2)}</td>
      <td>${p.rule}</td>`;
    tbody.appendChild(tr);
  }
}

// ----------------------------------------------------- add-vessel dialog

function populateClassSelect() {
  const select = document.getElementById("modal-class");
  const previous = select.value;
  select.innerHTML = "";
  for (const c of vesselClasses) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = `${c.name} (${c.length.toFixed(0)} m)`;
    select.appendChild(opt);
  }
  const preferred = vesselClasses.some(c => c.id === previous) ? previous : "coastal_cargo";
  if (vesselClasses.some(c => c.id === preferred)) select.value = preferred;
  refreshModalInfo(true);
}

function modalClassInfo() {
  const cls = vesselClasses.find(c => c.id === document.getElementById("modal-class").value);
  if (!cls) return null;
  const loading = document.getElementById("modal-loading").value;
  return { cls, loading, info: cls.loadings[loading] };
}

// Show the selected class's size/weight and measured maneuvering figures, and
// keep the speed field within the class's limits.
function refreshModalInfo(resetSpeed) {
  const sel = modalClassInfo();
  const out = document.getElementById("modal-class-info");
  const speed = document.getElementById("modal-speed");
  if (!sel) { out.textContent = ""; return; }
  const { info } = sel;
  const L = info.length;
  out.textContent = [
    `${info.length.toFixed(0)} × ${info.beam.toFixed(0)} m · draft ${info.draft.toFixed(1)} m · ${info.displacement_t.toLocaleString()} t`,
    `Max speed ${info.max_speed_kn.toFixed(1)} kn`,
    `Turning diameter ≈ ${info.tactical_diameter_m.toLocaleString()} m (${(info.tactical_diameter_m / L).toFixed(1)} L)`,
    `Crash stop from ${info.speed_kn} kn ≈ ${info.stopping_distance_m.toLocaleString()} m (${(info.stopping_distance_m / L).toFixed(1)} L), ${(info.stopping_time_s / 60).toFixed(1)} min`,
  ].join("\n");
  speed.max = info.max_speed_kn;
  if (resetSpeed || parseFloat(speed.value) > info.max_speed_kn) speed.value = info.service_speed_kn;
}

document.getElementById("modal-class").addEventListener("change", () => refreshModalInfo(true));
document.getElementById("modal-loading").addEventListener("change", () => refreshModalInfo(false));

// -------------------------------------------------------------- canvas view

const canvas = document.getElementById("plot");
const ctx = canvas.getContext("2d");
const view = { cx: 0, cy: 0, scale: 0.15 }; // world meters -> screen pixels

function cssSize() {
  const dpr = window.devicePixelRatio || 1;
  return [canvas.width / dpr, canvas.height / dpr];
}

function resizeCanvas() {
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  canvas.style.width = rect.width + "px";
  canvas.style.height = rect.height + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resizeCanvas);
resizeCanvas();

function clampScale() {
  view.scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.scale));
}

function worldToScreen(x, y) {
  const [w, h] = cssSize();
  return [
    w / 2 + (x - view.cx) * view.scale,
    h / 2 - (y - view.cy) * view.scale, // screen y grows down; world y (north) should go up
  ];
}

function screenToWorld(sx, sy) {
  const [w, h] = cssSize();
  return [
    view.cx + (sx - w / 2) / view.scale,
    view.cy - (sy - h / 2) / view.scale,
  ];
}

// Largest "nice" number (1, 2 or 5 x 10^k) not exceeding x.
function niceNumber(x) {
  if (!(x > 0)) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(x)));
  for (const m of [5, 2, 1]) if (m * mag <= x) return m * mag;
  return mag;
}

function fmtLen(m) {
  if (m >= 1000) return `${+(m / 1000).toFixed(1)} km`;
  return `${m} m`;
}

// Zoom and centre so every vessel (and route point) is visible.
function fitView() {
  if (!latestState || latestState.ships.length === 0) return;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  const include = (x, y, pad = 0) => {
    minX = Math.min(minX, x - pad); maxX = Math.max(maxX, x + pad);
    minY = Math.min(minY, y - pad); maxY = Math.max(maxY, y + pad);
  };
  for (const s of latestState.ships) include(s.x, s.y, s.length / 2);
  for (const pts of Object.values(latestState.routes)) for (const [x, y] of pts) include(x, y);
  const [w, h] = cssSize();
  const spanX = Math.max(maxX - minX, 300);
  const spanY = Math.max(maxY - minY, 300);
  view.cx = (minX + maxX) / 2;
  view.cy = (minY + maxY) / 2;
  view.scale = Math.min((w - 160) / spanX, (h - 160) / spanY);
  clampScale();
}
document.getElementById("btn-fit").addEventListener("click", fitView);

// A vessel too small to see at this zoom: a heading triangle of fixed pixel size.
function drawShipSymbol(ship, selected) {
  const [sx, sy] = worldToScreen(ship.x, ship.y);
  const psi = ship.heading_deg * Math.PI / 180;
  const fx = Math.sin(psi), fy = -Math.cos(psi);   // forward, in screen space
  const px = Math.cos(psi), py = Math.sin(psi);    // starboard, in screen space
  ctx.beginPath();
  ctx.moveTo(sx + fx * 9, sy + fy * 9);
  ctx.lineTo(sx - fx * 6 + px * 5, sy - fy * 6 + py * 5);
  ctx.lineTo(sx - fx * 6 - px * 5, sy - fy * 6 - py * 5);
  ctx.closePath();
  ctx.fillStyle = shipColor(ship);
  ctx.fill();
  ctx.strokeStyle = selected ? "#ffffff" : "#00000088";
  ctx.lineWidth = selected ? 2 : 1;
  ctx.stroke();
}

function drawShipHull(ship, selected) {
  const pts = ship.hull.map(([x, y]) => worldToScreen(x, y));
  ctx.beginPath();
  pts.forEach(([sx, sy], i) => i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy));
  ctx.closePath();
  ctx.fillStyle = shipColor(ship);
  ctx.globalAlpha = selected ? 1.0 : 0.85;
  ctx.fill();
  ctx.globalAlpha = 1.0;
  ctx.strokeStyle = selected ? "#ffffff" : "#00000088";
  ctx.lineWidth = selected ? 2 : 1;
  ctx.stroke();
}

// Speed vector: where the vessel will be in N minutes at its current heading
// and speed, with a tick every minute.
function drawSpeedVector(ship) {
  if (vectorMinutes <= 0 || ship.speed_ms < 0.2) return;
  const psi = ship.heading_deg * Math.PI / 180;
  const dx = Math.sin(psi), dy = Math.cos(psi);
  const [x0, y0] = worldToScreen(ship.x, ship.y);
  const [x1, y1] = worldToScreen(
    ship.x + dx * ship.speed_ms * 60 * vectorMinutes,
    ship.y + dy * ship.speed_ms * 60 * vectorMinutes);
  ctx.strokeStyle = shipColor(ship);
  ctx.globalAlpha = 0.7;
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  for (let m = 1; m <= vectorMinutes; m++) {
    const [tx, ty] = worldToScreen(
      ship.x + dx * ship.speed_ms * 60 * m, ship.y + dy * ship.speed_ms * 60 * m);
    // tick perpendicular to the vector (screen space)
    ctx.beginPath();
    ctx.moveTo(tx - Math.cos(psi) * 3, ty - Math.sin(psi) * 3);
    ctx.lineTo(tx + Math.cos(psi) * 3, ty + Math.sin(psi) * 3);
    ctx.stroke();
  }
  ctx.globalAlpha = 1.0;
}

// -------------------------------------------------- LLM reasoning bubbles
//
// One bubble per vessel in LLM mode, shown when "LLM reasoning" is ticked.
// It carries the LLM's reasoning text and the values it returned (rudder, RPM,
// and course when given). Anything the LLM did not return shows as "--", never
// as an invented number. Bubbles are HTML so the text wraps; the text comes
// from the LLM, so it is only ever set with textContent, never as markup.

const bubbles = new Map();   // ship name -> { el, parts, key, w, h }
const bubbleLayer = document.getElementById("bubble-layer");

const fmtDeg = (v) => (v === null || v === undefined) ? "--" : `${v > 0 ? "+" : ""}${v.toFixed(0)}°`;
const fmtPct = (v) => (v === null || v === undefined) ? "--" : `${v.toFixed(0)}%`;
const fmtCourse = (v) => `${String(Math.round(((v % 360) + 360) % 360)).padStart(3, "0")}°`;

function makeBubble(ship) {
  const el = document.createElement("div");
  el.className = "bubble";
  el.style.setProperty("--bubble-color", shipColor(ship));
  const head = document.createElement("div"); head.className = "bubble-head";
  const name = document.createElement("span"); name.className = "bubble-name"; name.textContent = ship.name;
  const status = document.createElement("span"); status.className = "bubble-status";
  head.append(name, status);
  const text = document.createElement("div"); text.className = "bubble-text";
  const out = document.createElement("div"); out.className = "bubble-out";
  const rudder = document.createElement("span");
  const rpm = document.createElement("span");
  const course = document.createElement("span");
  out.append(rudder, rpm, course);
  el.append(head, text, out);
  bubbleLayer.appendChild(el);
  return { el, parts: { status, text, rudder, rpm, course }, key: null, w: 0, h: 0 };
}

function setOutput(span, label, value) {
  span.textContent = `${label} `;
  const b = document.createElement("b");
  b.textContent = value;
  if (value === "--") b.className = "none";
  span.appendChild(b);
}

// Only touches the DOM (and re-measures) when the content actually changed.
function updateBubbleContent(b, ship) {
  const o = ship.llm_output || {};
  let status = "";
  if (!latestState.llm_configured) status = "not configured";
  else if (latestState.llm_pending) status = "thinking…";
  const key = JSON.stringify([status, o.reasoning, o.rudder_deg, o.rpm_percent, o.course_deg]);
  if (key === b.key) return;
  b.key = key;
  b.parts.status.textContent = status;
  b.parts.text.textContent = o.reasoning || "--";
  b.parts.text.classList.toggle("none", !o.reasoning);
  setOutput(b.parts.rudder, "Rudder", fmtDeg(o.rudder_deg));
  setOutput(b.parts.rpm, "RPM", fmtPct(o.rpm_percent));
  const hasCourse = o.course_deg !== null && o.course_deg !== undefined;
  b.parts.course.style.display = hasCourse ? "" : "none";
  if (hasCourse) setOutput(b.parts.course, "Course", fmtCourse(o.course_deg));
  b.w = b.el.offsetWidth;
  b.h = b.el.offsetHeight;
}

function clearBubbles() {
  for (const b of bubbles.values()) b.el.remove();
  bubbles.clear();
}

// Place the bubbles next to their vessels and return where they ended up, so the
// canvas can draw a connector line from each vessel to its bubble.
function layoutBubbles(w, h) {
  const placements = [];
  if (!showReasoning || !latestState) { clearBubbles(); return placements; }

  const live = new Set();
  const items = [];
  for (const ship of latestState.ships) {
    if (ship.control_mode !== "llm") continue;
    live.add(ship.name);
    let b = bubbles.get(ship.name);
    if (!b) { b = makeBubble(ship); bubbles.set(ship.name, b); }
    updateBubbleContent(b, ship);
    const [sx, sy] = worldToScreen(ship.x, ship.y);
    if (sx < -20 || sx > w + 20 || sy < -20 || sy > h + 20) { b.el.style.display = "none"; continue; }  // off screen
    items.push({ ship, b, sx, sy });
  }
  for (const [name, b] of Array.from(bubbles.entries())) {
    if (!live.has(name)) { b.el.remove(); bubbles.delete(name); }
  }

  const placed = [];
  for (const { ship, b, sx, sy } of items) {
    const gap = Math.max(14, ship.length * view.scale / 2 + 8);
    let dir = -1;                                   // -1: above the vessel, +1: below it
    let x = sx + gap;
    let y = sy - 30 - b.h;
    if (x + b.w > w - 4) x = sx - gap - b.w;        // near the right edge: put it on the left
    if (y < 4) { y = sy + 30; dir = 1; }            // near the top edge: put it below
    x = Math.max(4, Math.min(x, w - b.w - 4));
    // Nudge away from bubbles already placed, so nearby vessels don't hide each other.
    for (let tries = 0; tries < 12; tries++) {
      const hit = placed.find(p => x < p.x + p.w + 4 && x + b.w + 4 > p.x && y < p.y + p.h + 4 && y + b.h + 4 > p.y);
      if (!hit) break;
      y = dir < 0 ? hit.y - b.h - 6 : hit.y + hit.h + 6;
    }
    y = Math.max(4, Math.min(y, h - b.h - 4));
    placed.push({ x, y, w: b.w, h: b.h });
    b.el.style.display = "";
    b.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    // connector ends at the point of the bubble closest to the vessel
    placements.push({
      ship, sx, sy,
      ax: Math.max(x, Math.min(sx, x + b.w)),
      ay: Math.max(y, Math.min(sy, y + b.h)),
    });
  }
  return placements;
}

function drawRangeRingsAndScale(w, h) {
  const [cx, cy] = worldToScreen(view.cx, view.cy);
  const maxPx = Math.min(w, h) / 2 - 10;

  // Range rings at "nice" real distances from the view centre.
  ctx.strokeStyle = "#123531";
  ctx.fillStyle = "#3f6a63";
  ctx.lineWidth = 1;
  ctx.font = "10px monospace";
  const stepM = niceNumber(maxPx / view.scale / 4);
  for (let k = 1; k * stepM * view.scale <= maxPx; k++) {
    const r = k * stepM * view.scale;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillText(fmtLen(k * stepM), cx + 4, cy - r + 11);
  }

  // Scale bar, bottom right: metres and nautical miles.
  const barM = niceNumber(140 / view.scale);
  const barPx = barM * view.scale;
  const x1 = w - 16, x0 = x1 - barPx, y = h - 28;
  ctx.strokeStyle = "#8fb8b0";
  ctx.fillStyle = "#8fb8b0";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x0, y - 5); ctx.lineTo(x0, y + 5);
  ctx.moveTo(x0, y); ctx.lineTo(x1, y);
  ctx.moveTo(x1, y - 5); ctx.lineTo(x1, y + 5);
  ctx.stroke();
  ctx.font = "11px monospace";
  ctx.textAlign = "right";
  ctx.fillText(`${fmtLen(barM)}  (${(barM / M_PER_NM).toFixed(2)} nm)`, x1, y - 9);
  ctx.textAlign = "left";
}

function draw() {
  const [w, h] = cssSize();
  ctx.clearRect(0, 0, w, h);

  drawRangeRingsAndScale(w, h);

  if (!latestState) { requestAnimationFrame(draw); return; }

  // routes
  ctx.strokeStyle = "#2a4a44";
  ctx.fillStyle = "#2a4a44";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  for (const pts of Object.values(latestState.routes)) {
    if (pts.length < 2) continue;
    ctx.beginPath();
    pts.forEach(([x, y], i) => {
      const [sx, sy] = worldToScreen(x, y);
      i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy);
    });
    ctx.stroke();
  }
  ctx.setLineDash([]);
  for (const pts of Object.values(latestState.routes)) {
    for (const [x, y] of pts) {
      const [sx, sy] = worldToScreen(x, y);
      ctx.beginPath(); ctx.arc(sx, sy, 3, 0, Math.PI * 2); ctx.fill();
    }
  }

  // trails
  for (const [name, pts] of trails.entries()) {
    if (pts.length < 2) continue;
    const ship = latestState.ships.find(s => s.name === name);
    ctx.strokeStyle = ship ? shipColor(ship) : "#666";
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.4;
    ctx.beginPath();
    pts.forEach(([x, y], i) => {
      const [sx, sy] = worldToScreen(x, y);
      i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy);
    });
    ctx.stroke();
    ctx.globalAlpha = 1.0;
  }

  // LLM reasoning bubbles: connector lines here (under the hulls), the bubbles themselves are HTML
  for (const p of layoutBubbles(w, h)) {
    ctx.strokeStyle = shipColor(p.ship);
    ctx.globalAlpha = 0.55;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(p.sx, p.sy); ctx.lineTo(p.ax, p.ay); ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1.0;
  }

  // vessels, to scale
  for (const ship of latestState.ships) {
    const selected = ship.name === selectedShip;
    drawSpeedVector(ship);

    const lenPx = ship.length * view.scale;
    if (lenPx >= MIN_HULL_PX) drawShipHull(ship, selected);
    else drawShipSymbol(ship, selected);

    const [lx, ly] = worldToScreen(ship.x, ship.y);
    const off = Math.max(12, lenPx / 2 + 6);
    ctx.fillStyle = "#cfe8e2";
    ctx.font = "11px monospace";
    ctx.fillText(ship.name, lx + off, ly - 6);
    ctx.fillStyle = "#7fa39b";
    ctx.font = "10px monospace";
    ctx.fillText(`${(ship.speed_ms * KN_PER_MS).toFixed(1)} kn  ${ship.heading_deg.toFixed(0).padStart(3, "0")}°`, lx + off, ly + 6);
    if (ship.in_maneuver) { ctx.fillStyle = "#e0a530"; ctx.fillText("⚠", lx + off, ly + 18); }
  }

  // in-progress route being drawn (starts at the vessel, as it will when sent)
  if (routeDrawing && routeDrawing.points.length > 0) {
    const ship = latestState.ships.find(s => s.name === routeDrawing.shipName);
    ctx.strokeStyle = "#e0a530";
    ctx.fillStyle = "#e0a530";
    ctx.lineWidth = 2;
    ctx.beginPath();
    const start = ship ? [ship.x, ship.y] : routeDrawing.points[0];
    let [sx, sy] = worldToScreen(start[0], start[1]);
    ctx.moveTo(sx, sy);
    for (const [x, y] of routeDrawing.points) {
      [sx, sy] = worldToScreen(x, y);
      ctx.lineTo(sx, sy);
    }
    ctx.stroke();
    for (const [x, y] of routeDrawing.points) {
      const [px, py] = worldToScreen(x, y);
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);

// ------------------------------------------------------------- mouse input

let dragging = false;
let dragMoved = false;     // true once the pointer has travelled far enough to count as a pan
let dragLast = null;
const DRAG_THRESHOLD_PX = 4;

canvas.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return; // left button only for pan/select
  dragging = true;
  dragMoved = false;
  dragLast = [e.offsetX, e.offsetY];
});

canvas.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  const dx = e.offsetX - dragLast[0];
  const dy = e.offsetY - dragLast[1];
  if (!dragMoved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) return;
  dragMoved = true;
  view.cx -= dx / view.scale;
  view.cy += dy / view.scale;
  dragLast = [e.offsetX, e.offsetY];
});

window.addEventListener("mouseup", () => { dragging = false; });

canvas.addEventListener("click", (e) => {
  // A drag ends with a click event too; it was a pan, not a selection or waypoint.
  if (dragMoved) { dragMoved = false; return; }
  if (!latestState) return;
  const [wx, wy] = screenToWorld(e.offsetX, e.offsetY);

  if (routeDrawing) {
    routeDrawing.points.push([wx, wy]);
    document.getElementById("route-drawing-status").textContent =
      `${routeDrawing.points.length} waypoint(s) — click to add more`;
    return;
  }

  let closest = null, closestDist = Infinity;
  for (const ship of latestState.ships) {
    const d = Math.hypot(ship.x - wx, ship.y - wy);
    if (d < closestDist) { closestDist = d; closest = ship; }
  }
  // pick radius: 30 px or the hull's half-length, whichever is larger
  if (closest && closestDist < Math.max(30 / view.scale, closest.length / 2)) {
    selectedShip = closest.name;
    renderVesselList(latestState.ships);
    renderControlPanel(latestState.ships);
  }
});

canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const [wx, wy] = screenToWorld(e.offsetX, e.offsetY);
  view.scale *= e.deltaY < 0 ? 1.1 : 0.9;
  clampScale();
  // keep the point under the cursor fixed
  const [sx2, sy2] = worldToScreen(wx, wy);
  view.cx += (sx2 - e.offsetX) / view.scale;
  view.cy -= (sy2 - e.offsetY) / view.scale;
}, { passive: false });

// right-click: open "add vessel" modal at that world position
let pendingAddPos = null;
canvas.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  pendingAddPos = screenToWorld(e.offsetX, e.offsetY);
  document.getElementById("add-ship-modal").classList.remove("hidden");
});

document.getElementById("modal-cancel").onclick = () => {
  document.getElementById("add-ship-modal").classList.add("hidden");
};
document.getElementById("modal-confirm").onclick = () => {
  const name = document.getElementById("modal-name").value.trim() || undefined;
  const course = parseFloat(document.getElementById("modal-course").value) || 0;
  const speedKn = parseFloat(document.getElementById("modal-speed").value) || 0;
  const payload = {
    type: "add_ship",
    x: pendingAddPos[0], y: pendingAddPos[1],
    course_deg: course, speed_ms: speedKn / KN_PER_MS, name,
  };
  const sel = modalClassInfo();
  if (sel) { payload.vessel_class = sel.cls.id; payload.loading = sel.loading; }
  send(payload);
  document.getElementById("modal-name").value = "";
  document.getElementById("add-ship-modal").classList.add("hidden");
};

// -------------------------------------------------------------- side panel wiring

document.getElementById("rudder-slider").addEventListener("input", (e) => {
  if (!selectedShip) return;
  document.getElementById("rudder-val").textContent = `${e.target.value}°`;
  send({ type: "set_control", ship: selectedShip, rudder_deg: parseFloat(e.target.value) });
});

document.getElementById("rpm-slider").addEventListener("input", (e) => {
  if (!selectedShip) return;
  document.getElementById("rpm-val").textContent = `${e.target.value}%`;
  send({ type: "set_control", ship: selectedShip, rpm_percent: parseFloat(e.target.value) });
});

document.getElementById("control-mode-select").addEventListener("change", (e) => {
  if (!selectedShip) return;
  send({ type: "set_control_mode", ship: selectedShip, mode: e.target.value });
});

document.getElementById("vector-select").addEventListener("change", (e) => {
  vectorMinutes = parseFloat(e.target.value);
});

document.getElementById("show-reasoning").addEventListener("change", (e) => {
  showReasoning = e.target.checked;
  if (!showReasoning) clearBubbles();
});

// After choosing from a dropdown or ticking a box, hand the keyboard back to the page.
// Otherwise the arrow keys keep acting on that control (they would cycle the Mode
// dropdown instead of steering a vessel that was just put in Manual mode).
document.querySelectorAll("select, input[type=checkbox]").forEach((el) => {
  el.addEventListener("change", () => el.blur());
});

// ---------------------------------------------------------- route drawing

document.getElementById("btn-set-path").addEventListener("click", () => {
  if (!selectedShip) { alert("Select a vessel first"); return; }
  routeDrawing = { shipName: selectedShip, points: [] };
  document.getElementById("route-drawing-status").textContent = "Click canvas to add waypoints";
  document.getElementById("route-drawing-buttons").classList.remove("hidden");
  document.getElementById("route-buttons").classList.add("hidden");
});

document.getElementById("btn-cancel-path").addEventListener("click", () => {
  routeDrawing = null;
  document.getElementById("route-drawing-buttons").classList.add("hidden");
  document.getElementById("route-buttons").classList.remove("hidden");
});

document.getElementById("btn-finish-path").addEventListener("click", () => {
  if (!routeDrawing || routeDrawing.points.length < 1) {
    alert("Click at least one waypoint on the canvas first");
    return;
  }
  const ship = latestState && latestState.ships.find(s => s.name === routeDrawing.shipName);
  if (!ship) { alert("That vessel no longer exists"); routeDrawing = null; return; }
  // The path starts where the vessel is now; the clicked points follow.
  const points = [[ship.x, ship.y], ...routeDrawing.points];
  send({ type: "assign_route", ship: routeDrawing.shipName, points });
  routeDrawing = null;
  document.getElementById("route-drawing-buttons").classList.add("hidden");
  document.getElementById("route-buttons").classList.remove("hidden");
});

document.getElementById("btn-clear-path").addEventListener("click", () => {
  if (!selectedShip) return;
  send({ type: "clear_route", ship: selectedShip });
});

// ----------------------------------------------------------------- scenario

document.getElementById("btn-save-scenario").addEventListener("click", () => {
  const name = document.getElementById("scenario-name").value.trim();
  if (!name) { alert("Enter a scenario name"); return; }
  send({ type: "save_scenario", name });
});

document.getElementById("btn-load-scenario").addEventListener("click", () => {
  const select = document.getElementById("scenario-list");
  if (!select.value) { alert("No saved scenarios yet"); return; }
  selectedShip = null;
  routeDrawing = null;
  document.getElementById("route-drawing-buttons").classList.add("hidden");
  document.getElementById("route-buttons").classList.remove("hidden");
  send({ type: "load_scenario", name: select.value });
});

// ----------------------------------------------------------------- keyboard

document.addEventListener("keydown", (e) => {
  const tag = document.activeElement && document.activeElement.tagName;
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return; // don't hijack typing
  if (!latestState) return;

  const manualShip = latestState.ships.find(s => s.control_mode === "manual");
  if (!manualShip) return;

  const RUDDER_STEP = 5, RPM_STEP = 5;
  const msg = { type: "set_control", ship: manualShip.name };

  // Relative orders: the server adds the step to its own current value and
  // clips to the vessel's limits, so fast key repeats are never lost to a
  // stale state message or network latency.
  switch (e.key) {
    case "ArrowLeft":  msg.rudder_delta = -RUDDER_STEP; break;
    case "ArrowRight": msg.rudder_delta = RUDDER_STEP; break;
    case "ArrowUp":    msg.rpm_delta = RPM_STEP; break;
    case "ArrowDown":  msg.rpm_delta = -RPM_STEP; break;
    case "0":          msg.rudder_deg = 0; break;
    default: return;
  }

  e.preventDefault();
  send(msg);   // only the field that changed, so RPM keys never touch the rudder and vice versa
});

document.getElementById("btn-remove-ship").addEventListener("click", () => {
  if (!selectedShip) return;
  send({ type: "remove_ship", ship: selectedShip });
  selectedShip = null;
});

document.getElementById("btn-play-pause").addEventListener("click", () => {
  const running = !(latestState && latestState.running);
  send({ type: "set_sim", running });
});

document.getElementById("dt-input").addEventListener("change", (e) => {
  send({ type: "set_dt", dt: parseFloat(e.target.value) });
});

document.getElementById("btn-set-provider").addEventListener("click", () => {
  const provider = document.getElementById("llm-provider").value;
  const promptName = document.getElementById("llm-prompt").value;
  const apiKey = document.getElementById("llm-key-input").value.trim();
  const payload = { type: "set_llm_provider", provider, prompt_name: promptName };
  if (apiKey) payload.api_key = apiKey;
  send(payload);
});

connect();
