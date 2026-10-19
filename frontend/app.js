/*
 * app.js — MARINER_2 frontend
 *
 * Replaces canvas.py (matplotlib) + dialogs.py (AddShipDialog/ControlDialog)
 * + llm_decisions_window.py's table with a plain WebSocket + <canvas> client.
 * See WEBSOCKET_PROTOCOL.md for the full message schema this speaks.
 */

// ---------------------------------------------------------------- WebSocket

let ws = null;
let selectedShip = null;
let routeDrawing = null; // { shipName, points: [[x,y], ...] } while the user is laying out a path
let latestState = null;
const trails = new Map(); // shipName -> [[x,y], ...] (client-side, capped)
const MAX_TRAIL_POINTS = 600;

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
      send({ type: "list_scenarios" });
    } else if (msg.type === "error") {
      console.warn("Server error:", msg.message, msg);
      alert(msg.message || "Command failed");
    } else if (msg.type === "ack") {
      if (msg.of === "list_scenarios") {
        populateScenarioList(msg.scenarios);
      } else if (msg.of === "save_scenario") {
        send({ type: "list_scenarios" }); // refresh so the new save shows up
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
    row.onclick = () => { selectedShip = ship.name; renderVesselList(ships); renderControlPanel(ships); };

    const swatch = document.createElement("div");
    swatch.className = "vessel-swatch";
    swatch.style.background = ship.color;
    row.appendChild(swatch);

    const name = document.createElement("div");
    name.className = "vessel-name";
    name.textContent = `${ship.name}  ${ship.heading_deg.toFixed(0)}°/${(ship.speed_ms).toFixed(1)}m/s`;
    row.appendChild(name);

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

function renderControlPanel(ships) {
  const target = document.getElementById("control-target");
  const ship = ships.find(s => s.name === selectedShip);
  const modeSelect = document.getElementById("control-mode-select");
  const manualHint = document.getElementById("manual-hint");
  const routeButtons = document.getElementById("route-buttons");

  if (!ship) {
    target.textContent = "— none selected —";
    manualHint.classList.add("hidden");
    return;
  }

  target.textContent = ship.name;
  const rudderSlider = document.getElementById("rudder-slider");
  const rpmSlider = document.getElementById("rpm-slider");

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
  // "Follow path" only makes sense to offer prominently once a path exists;
  // the button is still there to create one either way.
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

// -------------------------------------------------------------- canvas view

const canvas = document.getElementById("plot");
const ctx = canvas.getContext("2d");
const view = { cx: 0, cy: 0, scale: 0.15 }; // world meters -> screen pixels

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

function worldToScreen(x, y) {
  const w = canvas.width / (window.devicePixelRatio || 1);
  const h = canvas.height / (window.devicePixelRatio || 1);
  return [
    w / 2 + (x - view.cx) * view.scale,
    h / 2 - (y - view.cy) * view.scale, // screen y grows down; world y (north) should go up
  ];
}

function screenToWorld(sx, sy) {
  const w = canvas.width / (window.devicePixelRatio || 1);
  const h = canvas.height / (window.devicePixelRatio || 1);
  return [
    view.cx + (sx - w / 2) / view.scale,
    view.cy - (sy - h / 2) / view.scale,
  ];
}

function niceRingRadiusM(pixelRadius) {
  return pixelRadius / view.scale;
}

function draw() {
  const w = canvas.width / (window.devicePixelRatio || 1);
  const h = canvas.height / (window.devicePixelRatio || 1);
  ctx.clearRect(0, 0, w, h);

  // range rings, centered on the viewport (like a radar display)
  ctx.strokeStyle = "#123531";
  ctx.fillStyle = "#3f6a63";
  ctx.font = "10px monospace";
  const [cx, cy] = worldToScreen(view.cx, view.cy);
  const ringCount = 4;
  const maxPxRadius = Math.min(w, h) / 2 - 10;
  for (let i = 1; i <= ringCount; i++) {
    const r = (maxPxRadius / ringCount) * i;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    const meters = niceRingRadiusM(r);
    ctx.fillText(meters >= 1000 ? `${(meters / 1000).toFixed(1)}km` : `${meters.toFixed(0)}m`, cx + 4, cy - r + 10);
  }

  if (!latestState) { requestAnimationFrame(draw); return; }

  // routes
  ctx.strokeStyle = "#2a4a44";
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

  // trails
  for (const [name, pts] of trails.entries()) {
    if (pts.length < 2) continue;
    const ship = latestState.ships.find(s => s.name === name);
    ctx.strokeStyle = ship ? ship.color : "#666";
    ctx.globalAlpha = 0.4;
    ctx.beginPath();
    pts.forEach(([x, y], i) => {
      const [sx, sy] = worldToScreen(x, y);
      i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy);
    });
    ctx.stroke();
    ctx.globalAlpha = 1.0;
  }

  // ship hulls
  for (const ship of latestState.ships) {
    const pts = ship.hull.map(([x, y]) => worldToScreen(x, y));
    ctx.beginPath();
    pts.forEach(([sx, sy], i) => i === 0 ? ctx.moveTo(sx, sy) : ctx.lineTo(sx, sy));
    ctx.closePath();
    ctx.fillStyle = ship.color;
    ctx.globalAlpha = ship.name === selectedShip ? 1.0 : 0.85;
    ctx.fill();
    ctx.globalAlpha = 1.0;
    ctx.strokeStyle = ship.name === selectedShip ? "#ffffff" : "#00000055";
    ctx.lineWidth = ship.name === selectedShip ? 2 : 1;
    ctx.stroke();

    const [lx, ly] = worldToScreen(ship.x, ship.y);
    ctx.fillStyle = "#cfe8e2";
    ctx.font = "11px monospace";
    ctx.fillText(ship.name, lx + 12, ly - 8);
    if (ship.in_maneuver) ctx.fillText("⚠", lx + 12, ly + 14);
  }

  // in-progress route being drawn
  if (routeDrawing && routeDrawing.points.length > 0) {
    const ship = latestState ? latestState.ships.find(s => s.name === routeDrawing.shipName) : null;
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
let dragLast = null;

canvas.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return; // left button only for pan/select
  dragging = true;
  dragLast = [e.offsetX, e.offsetY];
});

canvas.addEventListener("mousemove", (e) => {
  if (!dragging) return;
  const dx = e.offsetX - dragLast[0];
  const dy = e.offsetY - dragLast[1];
  view.cx -= dx / view.scale;
  view.cy += dy / view.scale;
  dragLast = [e.offsetX, e.offsetY];
});

window.addEventListener("mouseup", () => { dragging = false; });

canvas.addEventListener("click", (e) => {
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
  // 30px pick radius in world meters
  if (closest && closestDist < 30 / view.scale) {
    selectedShip = closest.name;
    renderVesselList(latestState.ships);
    renderControlPanel(latestState.ships);
  }
});

canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  const [wx, wy] = screenToWorld(e.offsetX, e.offsetY);
  const factor = e.deltaY < 0 ? 1.1 : 0.9;
  view.scale *= factor;
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
  const speedMs = speedKn * 0.514444;
  send({
    type: "add_ship",
    x: pendingAddPos[0], y: pendingAddPos[1],
    course_deg: course, speed_ms: speedMs, name,
  });
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
  send({ type: "assign_route", ship: routeDrawing.shipName, points: routeDrawing.points });
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
  let rudder = manualShip.rudder_cmd, rpm = manualShip.rpm_cmd, changed = true;

  switch (e.key) {
    case "ArrowLeft": rudder = Math.max(-35, rudder - RUDDER_STEP); break;
    case "ArrowRight": rudder = Math.min(35, rudder + RUDDER_STEP); break;
    case "ArrowUp": rpm = Math.min(100, rpm + RPM_STEP); break;
    case "ArrowDown": rpm = Math.max(0, rpm - RPM_STEP); break;
    case "0": rudder = 0; break;
    default: changed = false;
  }

  if (changed) {
    e.preventDefault();
    send({ type: "set_control", ship: manualShip.name, rudder_deg: rudder, rpm_percent: rpm });
  }
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
