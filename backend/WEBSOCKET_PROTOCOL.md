# MARINER_2 WebSocket protocol

Single endpoint: `ws(s)://<host>/ws`. JSON text frames both ways.

## Server -> client

### `hello` — sent once, right after the connection is accepted

```json
{
  "type": "hello",
  "llm_providers": ["groq", "openai", "..."],
  "llm_prompts": ["vts_default", "..."],
  "vessel_classes": [
    {
      "id": "coastal_cargo", "name": "Coastal cargo ship", "length": 100.0, "beam": 17.0,
      "loadings": {
        "laden":   {"class_id": "coastal_cargo", "class_name": "...", "loading": "laden",
                    "length": 100.0, "beam": 17.0, "draft": 6.0, "displacement_t": 7841,
                    "max_speed_kn": 12.0, "service_speed_kn": 11.0,
                    "speed_kn": 11.0, "tactical_diameter_m": 340, "advance_m": 283,
                    "stopping_distance_m": 629, "stopping_time_s": 218},
        "ballast": {"...": "same fields, lighter displacement"}
      }
    }
  ]
}
```

`vessel_classes` feeds the add-vessel dialog. The maneuvering figures (`tactical_diameter_m`,
`stopping_distance_m`, ...) are measured by running trials on the real ship model
(`backend/maneuvering.py`) at `speed_kn`, so they always agree with the simulator.

Use this to populate the provider/prompt dropdowns. The client should follow up with a `list_scenarios` command once it receives this (see below).


### `state` — broadcast every tick (every `TICK_SECONDS`, default 50ms)

```json
{
  "type": "state",
  "sim_time": 123.4,
  "running": true,
  "llm_pending": false,
  "llm_configured": true,
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
      "llm_output": {
        "reasoning": "Rule 15 give-way, turning starboard",
        "rudder_deg": 15.0, "rpm_percent": 60.0, "course_deg": null
      },
      "vessel_class": "coastal_cargo",
      "class_name": "Coastal cargo ship",
      "loading": "laden",
      "length": 100.0, "beam": 17.0, "draft": 6.0, "displacement_t": 7841.0,
      "max_speed_ms": 6.17,
      "rudder_angle": 9.2,
      "rpm_actual": 61.0, "rpm_min": -50.0, "cruise_rpm": 83.3,
      "control_mode": "straight",
      "has_route": false,
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
| `add_ship`            | `x`, `y`, `course_deg`, `speed_ms`, `name?`, `vessel_class?`, `loading?`, `overrides?` | name auto-generated if omitted; must be unique. `vessel_class` is a preset id (default `coastal_cargo`), `loading` is `laden` (default) or `ballast`, `overrides` is a dict of spec fields (e.g. `{"length": 120}`). Speed is clipped to the class maximum and the vessel starts holding it. |
| `remove_ship`         | `ship`                                                                | |
| `set_control`         | `ship`, `rudder_deg?`, `rpm_percent?`, `rudder_delta?`, `rpm_delta?`  | absolute or relative (delta) orders; deltas are applied to the server's own value, so fast key repeats are not lost. RPM runs from `rpm_min` (astern, -50) to 100. An operator RPM >= 0 also becomes the vessel's `cruise_rpm` |
| `toggle_llm`          | `ship`, `enabled`                                                     | |
| `assign_route`        | `ship`, `points` (`[[x,y], ...]`, >=2 points; the first point should be the vessel's position) | creates `Route` + `RouteAutopilot`, enables autopilot |
| `clear_route`         | `ship`                                                                | disables autopilot, drops the route |
| `set_sim`             | `running` (bool)                                                      | play/pause |
| `set_dt`              | `dt` (seconds of simulated time per physics step)                    | default 1.0, matches original desktop app |
| `set_llm_provider`    | `provider`, `model?`, `api_key?`, `prompt_name?`                      | `api_key` is session-only, never persisted; omit it on a public deploy and rely on server secrets |
| `set_llm_prompt`      | `prompt` (key into `backend/prompts/PROMPT_REGISTRY`)                 | swap system prompt without recreating the coordinator |
| `apply_safe_passing`  | `give_way`, `stand_on`                                                | runs `SafePassingCalculator.calculate_safe_course` and applies it immediately |
| `set_control_mode`    | `ship`, `mode` (`straight`\|`route`\|`manual`\|`llm`)                 | see below — the single entry point for the 4 control modes |
| `save_scenario`       | `name`                                                                | writes `Tasks/<name>.json` |
| `load_scenario`       | `name`                                                                | halts the sim, clears all ships, rebuilds from the saved file |
| `list_scenarios`      | *(none)*                                                              | reply's `ack.scenarios` is a list of saved scenario names |

## The 4 control modes

Every vessel is in exactly one of these at a time (`ship.control_mode` in the state broadcast):

- **`straight`** — the default. Rudder held at 0, RPM whatever was last set. No autopilot, no LLM.
- **`route`** — follows a previously-assigned path (`assign_route`) at constant speed; only rudder is
  automated (`RouteAutopilot`), RPM stays under manual/last-set control. Switching to this mode via
  `set_control_mode` without an assigned path first returns an error asking you to set one.
- **`manual`** — keyboard-controlled. Only one vessel may hold this mode at a time; setting a second
  vessel to `manual` automatically drops the first one back to `straight` server-side.
- **`llm`** — the swarm coordinator (`LLMCoordinator`) issues rudder/RPM commands for this vessel
  based on the currently selected provider + system prompt.

`assign_route` also switches the vessel into `route` mode as a side effect (and turns off LLM control
if it was on). `clear_route` drops it back to `straight`.

## Extending this

Add a new command by adding a branch in `main.py`'s `handle_command()` and,
if it needs new engine behavior, a method on `SimulationEngine`
(`backend/simulation.py`). Keep `SimulationEngine` Qt-free and HTTP-free —
it should stay usable from a test script with no server running at all.

## Vessel dynamics (what the numbers in `state` mean)

Each vessel has a `VesselSpec` (`backend/vessel_spec.py`): length, beam, draft, block coefficient,
installed power, maximum speed and maneuvering coefficients. Displacement follows from the hull
geometry, so size and weight are always consistent.

- **Steady speed is proportional to RPM%**: at `rpm_actual` = 50 % the vessel settles at half of
  `max_speed_ms`. A new vessel starts at the RPM that holds its initial speed.
- **Orders vs. actuators**: `rudder_cmd` and `rpm_cmd` are what is ordered; `rudder_angle` and
  `rpm_actual` are where the rudder and engine actually are, moving at a limited rate.
- **Heavy ships respond slowly**: speed changes take minutes for large vessels, and a crash stop
  from service speed takes about 3 to 23 minutes depending on class.
- **Astern**: negative RPM gives astern thrust. Speed stops at zero (no sternway is modeled).
- **Simulation speed**: `dt` only sets how much simulated time passes per tick. Physics and the
  autopilot run at a fixed fine step inside it, so changing `dt` does not change vessel behavior.

The preset values are illustrative, not data for specific ships. Run
`python tools/validate_dynamics.py` to print the turning and stopping trials for every class.

## `llm_output` (the reasoning bubble)

For a vessel in LLM mode, `llm_output` holds what the LLM last said about it; for every other vessel it is `null`.
`reasoning` is the LLM's text, and `rudder_deg`, `rpm_percent` and `course_deg` are the values it actually returned.
A value the LLM did not return (or that is not a number) is `null`, and the GUI shows it as `--` rather than inventing
a number. All four are `null` until the first reply, and again whenever a vessel is put back into LLM mode, so a stale
decision is never shown as current. The text is untrusted LLM output: render it as text, never as markup.
