"""
main.py
MARINER_2 backend entry point.

Replaces the original stub main.py. The simulation_loop() placeholder is now
filled in with the real Ship / CollisionAnalyzer / colreg_rules / autopilot /
LLMCoordinator pipeline, via backend/simulation.py's SimulationEngine — the
headless equivalent of the old PyQt5 MainWindow.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 7860
Then open http://localhost:7860 in a browser.

On HuggingFace Spaces (Docker SDK) this is the module uvicorn is pointed at
in the Dockerfile's CMD.
"""
import asyncio
import os
import sys
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

# backend/ keeps the original MARINER flat-import style (from ship import Ship,
# etc.) so those files could be copied over unchanged. We just add the
# directory to sys.path instead of turning it into a nested package.
BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
sys.path.insert(0, BACKEND_DIR)

from simulation import SimulationEngine  # noqa: E402

app = FastAPI(title="MARINER_2")

engine = SimulationEngine()
TICK_SECONDS = 0.05  # real-time interval between ticks (was QTimer.start(50))


# --------------------------------------------------------------------------
# WebSocket connection management
# --------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, payload: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_to(self, ws: WebSocket, payload: dict):
        try:
            await ws.send_json(payload)
        except Exception:
            pass


manager = ConnectionManager()


# --------------------------------------------------------------------------
# Command handling — see WEBSOCKET_PROTOCOL.md for the full message schema
# --------------------------------------------------------------------------

def handle_command(msg: dict) -> dict:
    """Dispatch one client->server WebSocket message. Returns an ack/error dict."""
    msg_type = msg.get("type")

    try:
        if msg_type == "add_ship":
            ship = engine.add_ship(
                x=msg["x"], y=msg["y"],
                course_deg=msg.get("course_deg", 0),
                speed_ms=msg.get("speed_ms", 5.0),
                name=msg.get("name"),
                vessel_class=msg.get("vessel_class"),
                loading=msg.get("loading", "laden"),
                overrides=msg.get("overrides"),
            )
            return {"type": "ack", "of": "add_ship", "ok": True, "ship": ship.name,
                    "vessel_class": ship.spec.class_id, "loading": ship.spec.loading}

        elif msg_type == "remove_ship":
            engine.remove_ship(msg["ship"])
            return {"type": "ack", "of": "remove_ship", "ok": True, "ship": msg["ship"]}

        elif msg_type == "set_control":
            ok = engine.set_control(
                msg["ship"],
                rudder_deg=msg.get("rudder_deg"),
                rpm_percent=msg.get("rpm_percent"),
                rudder_delta=msg.get("rudder_delta"),
                rpm_delta=msg.get("rpm_delta"),
            )
            return {"type": "ack", "of": "set_control", "ok": ok, "ship": msg["ship"]}

        elif msg_type == "toggle_llm":
            ok = engine.toggle_llm(msg["ship"], msg.get("enabled", True))
            return {"type": "ack", "of": "toggle_llm", "ok": ok, "ship": msg["ship"]}

        elif msg_type == "assign_route":
            route_name = engine.assign_route(msg["ship"], msg["points"])
            return {"type": "ack", "of": "assign_route", "ok": bool(route_name), "route": route_name}

        elif msg_type == "clear_route":
            ok = engine.clear_route(msg["ship"])
            return {"type": "ack", "of": "clear_route", "ok": ok, "ship": msg["ship"]}

        elif msg_type == "set_control_mode":
            ok, error = engine.set_control_mode(msg["ship"], msg["mode"])
            resp = {"type": "ack", "of": "set_control_mode", "ok": ok, "ship": msg["ship"], "mode": msg["mode"]}
            if not ok:
                resp["message"] = error
            return resp

        elif msg_type == "save_scenario":
            saved_name = engine.save_scenario(msg["name"])
            return {"type": "ack", "of": "save_scenario", "ok": True, "name": saved_name}

        elif msg_type == "load_scenario":
            ok, error = engine.load_scenario(msg["name"])
            resp = {"type": "ack", "of": "load_scenario", "ok": ok, "name": msg["name"]}
            if not ok:
                resp["message"] = error
            return resp

        elif msg_type == "list_scenarios":
            return {"type": "ack", "of": "list_scenarios", "ok": True, "scenarios": engine.list_scenarios()}

        elif msg_type == "set_sim":
            engine.running = bool(msg.get("running", True))
            return {"type": "ack", "of": "set_sim", "ok": True, "running": engine.running}

        elif msg_type == "set_dt":
            engine.dt = float(msg["dt"])
            return {"type": "ack", "of": "set_dt", "ok": True, "dt": engine.dt}

        elif msg_type == "set_llm_provider":
            # NOTE: an api_key sent from the browser is used for this
            # session only and is never written to disk or logged. Prefer
            # setting provider keys as HF Space secrets (env vars) and
            # omitting api_key from this message on a public deployment.
            engine.set_llm_provider(
                provider=msg["provider"],
                model=msg.get("model"),
                api_key=msg.get("api_key"),
                prompt_name=msg.get("prompt_name", "vts_default"),
            )
            return {"type": "ack", "of": "set_llm_provider", "ok": True, "provider": msg["provider"]}

        elif msg_type == "set_llm_prompt":
            if engine.llm_coordinator is None:
                return {"type": "error", "of": "set_llm_prompt", "message": "No LLM provider configured yet"}
            engine.llm_coordinator.set_prompt(msg["prompt"])
            return {"type": "ack", "of": "set_llm_prompt", "ok": True, "prompt": msg["prompt"]}

        elif msg_type == "apply_safe_passing":
            from safe_passing_calculator import SafePassingCalculator  # noqa: E402
            give_way = engine.get_ship(msg["give_way"])
            stand_on = engine.get_ship(msg["stand_on"])
            if not give_way or not stand_on:
                return {"type": "error", "of": "apply_safe_passing", "message": "Unknown vessel name"}
            calc = SafePassingCalculator()
            result = calc.calculate_safe_course(give_way, stand_on)
            if result["is_valid"]:
                give_way.set_base_heading(result["safe_course_deg"])
                current_heading = give_way.get_heading_deg()
                turn_angle = (result["safe_course_deg"] - current_heading + 180) % 360 - 180
                give_way.rudder_cmd = max(-35, min(35, turn_angle * 2))
            return {"type": "ack", "of": "apply_safe_passing", "ok": result["is_valid"], "result": result}

        else:
            return {"type": "error", "message": f"Unknown command type: {msg_type}"}

    except KeyError as e:
        return {"type": "error", "of": msg_type, "message": f"Missing field: {e}"}
    except Exception as e:
        return {"type": "error", "of": msg_type, "message": str(e)}


# --------------------------------------------------------------------------
# Simulation loop (replaces QTimer(50ms) -> MainWindow.simulation_step)
# --------------------------------------------------------------------------

async def simulation_loop():
    while True:
        engine.step()
        pairs = engine.compute_collision_pairs()
        await engine.maybe_trigger_llm(pairs)   # no-ops instantly unless due
        state = engine.serialize_state(pairs)
        await manager.broadcast(state)
        await asyncio.sleep(TICK_SECONDS)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(simulation_loop())


# --------------------------------------------------------------------------
# WebSocket endpoint
# --------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await manager.send_to(websocket, {
        "type": "hello",
        "llm_prompts": SimulationEngine.available_prompts(),
        "llm_providers": SimulationEngine.available_providers(),
        "vessel_classes": SimulationEngine.available_vessel_classes(),
    })
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_to(websocket, {"type": "error", "message": "Invalid JSON"})
                continue
            response = handle_command(msg)
            await manager.send_to(websocket, response)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# --------------------------------------------------------------------------
# Static frontend (index.html / app.js / style.css)
# --------------------------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
