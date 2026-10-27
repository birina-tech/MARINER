---
title: MARINER 2
emoji: 🚢
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# MARINER_2: Multi-Agent Risk-aware Interactive Navigation & Encounter Resolution

The **MARINER Project** is an interactive simulation framework that leverages *Large Language Models* (LLMs) to coordinate multi-agent autonomous surface vessels. The system acts as an AI-driven Vessel Traffic Service (VTS): it analyzes the entire collision matrix and generates simultaneous, COLREGs-compliant maneuver commands (rudder and RPM) for a swarm of ships.

**MARINER_2** is the web version of the original desktop application. The simulation engine runs on a Python backend (FastAPI + WebSocket) and the interface runs in any modern browser, so it can be deployed as a Docker container, for example on Hugging Face Spaces, and shared by link without installing anything.

## Features

- Browser-based interactive simulation: HTML5 canvas with pan, zoom, vessel trails and live COLREGs table
- Five vessel classes (harbor tug to VLCC), laden or in ballast, with size- and weight-dependent dynamics
- Four vessel control modes: straight, path following, keyboard (manual), and LLM
- Global swarm coordination modeled as LLM-guided coordination, with a selectable system prompt
- Universal LLM integration: DeepSeek, OpenAI, Anthropic, Groq, OpenRouter, Hugging Face Inference, and local models via Ollama (local use only)
- Real-time COLREGs analysis: DCPA, TCPA, risk index, and automatic classification of Rules 13, 14, 15 and 17.2
- Path editor: draw a route for any vessel by clicking waypoints on the map
- Scenario management: save and load multi-vessel scenarios (including routes and control modes) as JSON files

## Methodology

### Vessel Dynamics Simulation (Nomoto Model)

Vessel motion is modeled with the first-order **Nomoto** model, a widely accepted representation of the yaw dynamics of marine vessels. Control inputs are human-readable:

- **Rudder angle**: commanded in degrees (±35°), moving at a limited rate. LLM commands change the order by at most 5° per step.
- **Engine RPM**: commanded as a percentage of maximum thrust.

### Risk Assessment & COLREGs

Collision risk combines three parameters: *DCPA* (distance at the closest point of approach), *TCPA* (time to the closest point of approach), and the current distance between vessels. Based on relative bearings and risk, the `colreg_rules.py` module classifies each pair of vessels into a specific COLREGs situation (head-on, overtaking, crossing, or emergency) and assigns give-way / stand-on roles. These results are passed to the LLM to guide its decisions. Thresholds are defined in `rules_settings.py`.

### Vessel Classes, Size and Weight

Each vessel is created from a class and a loading condition (laden or ballast). Class presets give length, beam, draft, block coefficient, installed power, maximum speed and maneuvering coefficients; displacement is derived from the hull geometry, so size and weight stay consistent.

| Class | Length | Laden displacement | Max speed |
|-------|--------|--------------------|-----------|
| Harbor tug | 40 m | ~1,000 t | 12 kn |
| Coastal cargo ship | 100 m | ~7,800 t | 12 kn |
| Panamax bulk carrier | 230 m | ~72,000 t | 14 kn |
| Large container ship | 366 m | ~180,000 t | 22 kn |
| VLCC tanker | 330 m | ~354,000 t | 15 kn |

What this changes in the simulation:

- **Turning** scales with ship length and speed (nonlinear Nomoto yaw model, turning diameters of about 2.4 to 4.6 ship lengths at full rudder).
- **Speed** follows from mass, engine thrust and resistance: heavy ships accelerate and stop slowly. Steady speed is proportional to RPM%, so a vessel added at 10 kn keeps 10 kn. A crash stop from service speed takes from about 0.6 min (tug) to 23 min (laden VLCC).
- **Rudder and engine** orders move the actual rudder and engine at a limited rate. Negative RPM gives astern thrust.
- **Hulls are drawn to scale** on the map, with a scale bar and range rings in real distances. A vessel too small to see at the current zoom is shown as a heading symbol.
- The **autopilot's gains and wheel-over distances are derived from each vessel's dynamics** (`RouteAutopilot.auto_tune`; set it to `False` to restore the original fixed coefficients).

The preset values are illustrative, chosen to be plausible and to meet the IMO maneuvering criteria as recalled in `backend/maneuvering.py`; they are not data for specific ships. Run `python tools/validate_dynamics.py` to print the turning circle, crash-stop and zig-zag trials for every class, and pass overrides (for example a different length or maximum speed) when creating a vessel to model a specific ship. Ballast changes displacement and maximum speed but not the turning characteristics.

## Vessel Control Modes

Every vessel is in exactly one of four modes at a time. Select the vessel (click it on the map or in the Vessels list), then choose the mode in the Control panel.

| Mode | Behavior |
|------|----------|
| **Straight** (default) | Neutral rudder; the vessel keeps its heading and speed. |
| **Follow path** | The vessel follows a drawn or loaded path at constant speed. Only the rudder is automated. Requires a path to be set first. |
| **Manual (keyboard)** | One vessel at a time. `←` / `→` change the rudder, `↑` / `↓` change RPM, `0` centers the rudder. |
| **LLM** | The LLM coordinator issues rudder and RPM commands for the vessel. |

**Setting a path:** select a vessel, click **Set Path…**, click waypoints on the map (the path starts from the vessel's current position), then click **Finish**. The vessel switches to *Follow path* automatically. **Clear Path** removes it.

## Project Structure

```
MARINER/
├── main.py                  # FastAPI app: WebSocket endpoint, simulation loop, static hosting
├── Dockerfile               # Container image (also used by Hugging Face Spaces)
├── requirements.txt         # Python dependencies
├── WEBSOCKET_PROTOCOL.md    # Message schema between frontend and backend
├── Tasks/                   # Saved JSON scenarios (created automatically)
├── tools/
│   └── validate_dynamics.py # Prints the maneuvering trials for every vessel class
├── backend/
│   ├── simulation.py        # SimulationEngine: ships, physics tick, COLREGs, LLM dispatch, scenarios
│   ├── ship.py              # Vessel model (Nomoto dynamics)
│   ├── autopilot.py         # Route-following autopilot (gains derived from vessel dynamics)
│   ├── vessel_spec.py       # Vessel classes: size, weight, power, maneuvering coefficients
│   ├── maneuvering.py       # Turning circle, crash stop, zig-zag trials; IMO check
│   ├── route.py             # Route and waypoint classes
│   ├── collision_analyzer.py# CPA / TCPA / risk / course-crossing math
│   ├── colreg_rules.py      # COLREGs situation classification
│   ├── rules_settings.py    # COLREGs thresholds
│   ├── safe_passing_calculator.py  # Safe-passing course search
│   ├── llm_controller.py    # LLM provider integrations
│   ├── units.py             # Unit conversion helpers
│   └── prompts/
│       └── vts_default.py   # Default system prompt (more can be registered)
└── frontend/
    ├── index.html           # Page layout
    ├── style.css            # Styling
    └── app.js               # Canvas rendering, controls, WebSocket client
```

## Installation & Running

### Option 1: Docker (recommended)

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), then from the repository root:

```
docker build -t mariner2 .
docker run -p 7860:7860 mariner2
```

Open http://localhost:7860 in a browser.

To pass an API key and keep saved scenarios between runs (PowerShell):

```
docker run -p 7860:7860 -e GROQ_API_KEY=your_key -v "${PWD}/Tasks:/app/Tasks" mariner2
```

### Option 2: Python directly

Requires Python 3.9 or higher.

```
pip install -r requirements.txt
uvicorn main:app --port 7860
```

Open http://localhost:7860 in a browser.

## Usability & Functionality

### Scene Control

- **Pan**: hold the left mouse button on the map and drag.
- **Zoom**: mouse wheel.
- **Add vessel**: right-click an empty spot on the map and enter name, course and speed.
- **Select vessel**: left-click it on the map, or click its name in the Vessels list.
- **Run / Pause**: button in the top bar. The `dt` field sets how many simulated seconds pass per 50 ms tick (default 1.0, so the simulation runs 20 times faster than real time; 0.05 is real time).
- **Vector**: draws, for each vessel, a line showing where it will be in 3, 6 or 12 minutes at its current heading and speed, with a tick every minute. It is a display option only and does not affect the simulation.
- **LLM reasoning**: tick this box to show a bubble next to each vessel in LLM mode with the LLM's reasoning and the values it returned (rudder, RPM, and course if given). A value the LLM did not return shows as `--`.

### Scenarios

Use the Scenario panel to save the current vessels (positions, headings, speeds, rudder/RPM, control modes and paths) under a name, and to load a saved scenario from the list. Loading halts the simulation and replaces all current vessels. Files are stored in the `Tasks/` folder.

## LLM Setup & Safety

API keys are read from **environment variables** on the server and are never written to disk or sent to the browser:

| Provider | Variable |
|----------|----------|
| Groq | `GROQ_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| Hugging Face Inference | `HF_TOKEN` |

On Hugging Face Spaces, add these under **Settings → Variables and secrets**. Locally, pass them with `docker run -e NAME=value`, or set them in your shell before `uvicorn`.

To use the LLM:

1. In the **LLM Coordinator** panel, choose a provider and a system prompt (`vts_default` is selected by default).
2. Click **Apply**. The coordinator is not created until you do this.
3. Set one or more vessels to **LLM** mode and press **Run**.

The LLM indicator in the top bar shows idle, thinking, ok, or error. Ollama works only when it runs on the same machine as the server, so it is for local development, not for a hosted Space.

### Adding a system prompt

Create `backend/prompts/vts_<name>.py` containing a `SYSTEM_PROMPT` string, then register it in `backend/prompts/__init__.py`. It will appear in the prompt list automatically.

## Deployment (Hugging Face Spaces)

The YAML block at the very top of this file tells Hugging Face to build the `Dockerfile` (`sdk: docker`) and to route traffic to port 7860 (`app_port: 7860`). To deploy, create a Docker Space, add your keys as secrets, and push this repository to the Space. Saved scenarios in `Tasks/` do not persist across Space restarts unless persistent storage is enabled.

## Status of Features Ported from the Desktop Version

| Feature | Status |
|---------|--------|
| Ship dynamics, COLREGs analysis, LLM coordination | Ported |
| Route following, scenario save/load | Ported |
| Safe-passing calculator | Backend command available (`apply_safe_passing`); no interface yet |
| Predicted-track overlay | Not yet ported |
| Telemetry logging to CSV | Not yet ported |
| COLREGs settings editor and autopilot debug window | Not yet ported (thresholds are set in `rules_settings.py`) |

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Developers

PI **Yaroslav Burylin**

Navigation Department

Admiral Ushakov Maritime State University (AUMSU)

Novorossiysk, Russian Federation

Co-I **Irina Benedyk**

Civil, Structural, and Environmental Department

State University of New York (SUNY) at Buffalo

Buffalo, USA
