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
    } else if (msg.type === "error") {
      console.warn("Server error:", msg.message, msg);
    }
    // "ack" messages are logged only; UI already reflects optimistic/next-tick state.
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
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

    if (ship.llm_controlled) {
      const b = document.createElement("span");
      b.className = "vessel-badge badge-llm"; b.textContent = "LLM";
      row.appendChild(b);
    }
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
  if (!ship) { target.textContent = "— none selected —"; return; }

  target.textContent = ship.name;
  const rudderSlider = document.getElementById("rudder-slider");
  const rpmSlider = document.getElementById("rpm-slider");
  const llmToggle = document.getElementById("llm-toggle");

  // Don't fight the user while they're actively dragging a slider.
  if (document.activeElement !== rudderSlider) {
    rudderSlider.value = ship.rudder_cmd;
    document.getElementById("rudder-val").textContent = `${ship.rudder_cmd.toFixed(0)}°`;
  }
  if (document.activeElement !== rpmSlider) {
    rpmSlider.value = ship.rpm_cmd;
    document.getElementById("rpm-val").textContent = `${ship.rpm_cmd.toFixed(0)}%`;
  }
  llmToggle.checked = ship.llm_controlled;
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

document.getElementById("llm-toggle").addEventListener("change", (e) => {
  if (!selectedShip) return;
  send({ type: "toggle_llm", ship: selectedShip, enabled: e.target.checked });
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
  const apiKey = document.getElementById("llm-key-input").value.trim();
  const payload = { type: "set_llm_provider", provider };
  if (apiKey) payload.api_key = apiKey;
  send(payload);
});

connect();
