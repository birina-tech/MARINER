# MARINER_2 WebSocket protocol

Single endpoint: `ws(s)://<host>/ws`. JSON text frames both ways.

## Server -> client

### `state` — broadcast every tick (every `TICK_SECONDS`, default 50ms)

```json
{
  "type": "state",
  "sim_time": 123.4,
  "running": true,
  "llm_pending": false,
  "llm_status": "ok",
  "ships": [
    {
      "name": "Ship_1",
      "x": 1000.0, "y": 2000.0,
      "heading_deg": 45.0,
      "speed_ms": 5.2,
      "rot_deg_min": 1.3,
      "rudder_cmd": 10.0,
      "rpm_cmd": 50.0,
      "color": "blue",
      "llm_controlled": true,
      "in_maneuver": false,
      "autopilot_enabled": false,
      "llm_status_text": "\nLLM: R=10° RPM=50%",
      "hull": [[x1, y1], [x2, y2], [x3, y3], [x4, y4], [x5, y5]]
    }
  ],
  "collision_pairs": [
    {
      "ship1": "Ship_1", "ship2": "Ship_2",
      "dist_m": 5000.0, "dcpa_m": 800.0, "tcpa_s": 200.0,
      "risk": 0.62, "rule": "15", "situation": "Crossing situation",
      "ship1_action": "Give-way (Rule 16)", "ship2_action": "Stand on (Rule 17.1)",
      "crossing_type": "Ship_1 crosses Ship_2 ahead"
    }
  ],
  "routes": {
    "Route_1": [[0, 0], [1000, 2000], [3000, 2500]]
  }
}
```

`hull` is already in world meters, pre-rotated server-side (`Ship.get_pentagon_vertices()`)
— the frontend just draws the polygon, no trig needed client-side.
`tcpa_s` is `null` when TCPA is infinite (vessels diverging).

### `ack` — reply to a client command that succeeded

```json
{"type": "ack", "of": "add_ship", "ok": true, "ship": "Ship_3"}
```

### `error` — reply to a failed/invalid command

```json
{"type": "error", "of": "set_control", "message": "Missing field: 'ship'"}
```

## Client -> server

| `type`               | fields                                                              | notes |
|----------------------|----------------------------------------------------------------------|-------|
| `add_ship`            | `x`, `y`, `course_deg`, `speed_ms`, `name?`                          | name auto-generated if omitted |
| `remove_ship`         | `ship`                                                                | |
| `set_control`         | `ship`, `rudder_deg?`, `rpm_percent?`                                 | either field may be omitted |
| `toggle_llm`          | `ship`, `enabled`                                                     | |
| `assign_route`        | `ship`, `points` (`[[x,y], ...]`, >=2 points)                         | creates `Route` + `RouteAutopilot`, enables autopilot |
| `clear_route`         | `ship`                                                                | disables autopilot, drops the route |
| `set_sim`             | `running` (bool)                                                      | play/pause |
| `set_dt`              | `dt` (seconds of simulated time per physics step)                    | default 1.0, matches original desktop app |
| `set_llm_provider`    | `provider`, `model?`, `api_key?`, `prompt_name?`                      | `api_key` is session-only, never persisted; omit it on a public deploy and rely on server secrets |
| `set_llm_prompt`      | `prompt` (key into `backend/prompts/PROMPT_REGISTRY`)                 | swap system prompt without recreating the coordinator |
| `apply_safe_passing`  | `give_way`, `stand_on`                                                | runs `SafePassingCalculator.calculate_safe_course` and applies it immediately |

## Extending this

Add a new command by adding a branch in `main.py`'s `handle_command()` and,
if it needs new engine behavior, a method on `SimulationEngine`
(`backend/simulation.py`). Keep `SimulationEngine` Qt-free and HTTP-free —
it should stay usable from a test script with no server running at all.
