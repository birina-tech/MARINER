# MARINER: Multi-Agent Risk-aware Interactive Navigation & Encounter Resolution

The **MARINER Project** is an advanced interactive simulation framework that leverages Large Language Models (LLMs) to coordinate multi-agent autonomous surface vessels. Operating effectively as an AI-driven Vessel Traffic Service (VTS), the system analyzes entire pairwise encounter vectors and generates simultaneous, COLREGs-compliant steering commands (Rudder and RPM) for a swarm of ships.


## Features

- Interactive GUI Simulation Platform, built via a PyQt5 application loop with integrated Matplotlib canvas plotting layout tracking.  
- Decentralized Parallel AI Pilots - spawns asynchronous non-blocking network worker threads (LLMWorker) via LiteLLM.
- Persistent Rule Memory Pipeline to track active COLREG rules continuously until the Time to Closest Point of Approach (TCPA) resolves <= 0 and target ranges are cleared.  
- Dual-Mode Guidance Systems seamlessly bridges LLM maritime maneuvering with localized geometric cross-track error ($\chi$) tracking and Burylin/Popov PID route recovery algorithms.  
- Trajectory Projection allows to draw multi-segment maneuver paths directly on the map interface to simulate routing scenarios.  
- Customizable Parametric Filters inplemented ia threshold customization interfaces allowing user adjustments to safe Closest Point of Approach (DCPA), TCPA limits, and angular boundary sectors.  
- Full Session Telemetry Logging that exports time-synchronized vessel kinematics (X, Y, Heading, Speed, Rudder, RPM, and Rate of Turn) into discrete multi-file CSV records. 









# MARINER: Multi-Agent Risk-aware Interactive Navigation & Encounter Resolution

The **MARINER Project** is an advanced interactive simulation framework that leverages *Large Language Models* (LLMs) to coordinate multi-agent autonomous surface vessels. Operating effectively as an AI-driven Vessel Traffic Service (VTS), the system analyzes entire pairwise encounter vectors and generates simultaneous, COLREGs-compliant steering commands (Rudder and RPM) for a swarm of ships.

---

## Features

*   **Interactive GUI Simulation Platform**: Built via a robust PyQt5 application loop with integrated Matplotlib canvas plotting layout tracking.
*   **Decentralized Parallel AI Pilots**: Spawns asynchronous non-blocking network worker threads (`LLMWorker`) via LiteLLM to eliminate visual layout stutters during remote API completion lookups.
*   **Persistent Rule Memory Pipeline**: Tracks active COLREG rules continuously until the Time to Closest Point of Approach (TCPA) resolves <= 0 and target ranges are cleared.
*   **Dual-Mode Guidance Systems**: Seamlessly bridges LLM maritime maneuvering with localized geometric cross-track error ($\chi$) tracking and Burylin/Popov PID route recovery algorithms.
*   **Predictive Trajectory Projection**: Calculates and draws lookahead multi-segment maneuver paths directly on the map interface to forecast safe routing scenarios.
*   **Customizable Parametric Filters**: Tabbed threshold customization interfaces allowing user adjustments to safe Closest Point of Approach (DCPA), TCPA limits, and angular boundary sectors.
*   **Geospatial S-57 ENC Support**: Live ingestion and styling of S-57 nautical charts via GDAL/OGR including bathymetric isobars, obstacles, and landmass features.
*   **Full Session Telemetry Logging**: Automatically exports time-synchronized vessel kinematics (X, Y, Heading, Speed, Rudder, RPM, and Rate of Turn) into discrete multi-file CSV records.

---

## Methodology

### Vessel Dynamics Simulation (Nomoto Model)
Kinematic motion profiles utilize the first-order **Nomoto** steering model to accurately represent the yaw and forward velocity profiles of marine vessels under actuator lag:

$$T_{\psi} \dot{r} + r = K_{\psi} \delta_{\tau}$$

$$T_{v} \dot{u} + u = K_{v} u_{c}$$

Actuator adjustments are capped at realistic steering rates of $5^\circ$ per time-step for the rudder and $10\%$ per step for the engine RPM to enforce physical conservation boundaries.


### Collision Risk Assessment & Dominant Status Matrix

Pairwise interaction matrices continuously evaluate fuzzy Z-shaped tracking indexes driven by DCPA and TCPA.

The state synchronization loop maps conflicts into three distinct behavioral regimes:

1.  **`MUST_YIELD`**: The vessel is designated as give-way under COLREGs Rules 13, 14, or 15 and must execute immediate evasive actions.

2.  **`MANEUVER`**: Active threats have successfully cleared, but the vessel remains off-track or misaligned from its core base course, initiating geometric trajectory alignment recovery.

3.  **`HOLD_COURSE`**: Navigational sectors are free of hazardous objects, enabling the ship to maintain its uniform speed and baseline course.


### Analytical Safe Passing Strategy
Using the full-featured trajectory tool, users can choose specific encounter combinations to calculate mathematically optimized evasive maneuvers. The search algorithm iterates through angular arcs ($\Delta \theta = 1^\circ$) to secure desired DCPA tolerances, defaulting to safe starboard turns unless restricted by spatial boundaries.

---

## Project Structure



```
MARINER/
├── Tasks/                  # Directory for saved JSON scenario configurations
├── Logs/                   # Session directories with logged vessel CSV files
├── ship_simulation.py      # Main application entry point: PyQt5 GUI & step loops
├── ship.py                 # Nomoto dynamics simulation modeling & telemetry logging
├── autopilot.py            # Route tracking controller & Burylin/Popov PID logic
├── route.py                # Waypoint nodes, track segments, & kinematic distances
├── collision_analyzer.py   # Mathematical CPA/TCPA matrix & crossing point forecasts
├── colreg_rules.py         # Sector calculations for Rules 13, 14, 15, and 17.2
├── rules_settings.py       # JSON parameter serialization handle for rules thresholds
├── llm_controller.py       # Universal LiteLLM coordinator platform connector
├── llm_worker.py           # Threaded background worker for non-blocking requests
├── agent_prompts.py        # Structural JSON blueprint system prompts for pilots
├── canvas.py               # Optimized Matplotlib rendering engine pipeline
├── units.py                # Kinematic conversion utilities (knots, meters, nm)
├── safe_passing_calculator.py # Search algorithm for safe courses & track predictions
├── safe_passing_dialog.py  # Diagnostic dashboard tool for safe passing calculations
├── dialogs.py              # User adjustment sliders & security key settings
├── route_dialog.py         # Tabular waypoint coordinator interface
├── rules_settings_dialog.py# Threshold validation interface configuration tabs
├── llm_decisions_window.py # Real-time AI reasoning cell monitor panel
├── autopilot_debug_dialog.py# Non-modal path tracking telemetry window
└── test_litellm_isolated.py # Diagnostic script to verify remote model completions  

```




## Installation & Dependencies

### Prerequisites
*   Python 3.8 or higher
*   Cross-platform operational compatibility across Windows, macOS, or Linux

### Dependency Ingestion
Install all necessary computation libraries, core interface structures, and multi-provider remote completion frameworks using `pip`:

```
bash
pip install PyQt5 numpy matplotlib litellm requests
```

### Running the Application

To run the simulation platform interface, execute the main runtime file:

```
Bash
python ship_simulation.py
```


## Operations Guide


### Simulation Execution Controls

*   **Simulation Step Multiplier (`dt`)**: Accessible via **View $\rightarrow$ Simulation speed...** to alter the mathematical time-step integration deltas ($dt$).
*   **Actuator Perspective Shift**: Right-clicking an active vessel switches the visualization canvas perspective to treat that specific vessel as the target *Ego Vessel*, showing its localized pairwise threat ranges.
*   **Real-time Configuration Tables**: The **ColReg Analysis** and **LLM Decisions** dashboards provide deep, transparent insights into active fuzzy risk indexes, active ruleset arrays, and ongoing text descriptions generated by the AI.

### Multi-File Session Ingestion

1.  Click **🔴 Start Rec** on the toolbar to initiate a fresh session folder inside the `Logs/` directory, timestamped down to the second.
2.  The application opens data append streams for every ship on the canvas.
3.  Each cycle flushes live strings containing timestamped variables directly into file targets formatted as follows:
    `[time_s, x_m, y_m, course_deg, speed_ms, rudder_deg, rpm_percent, rot_deg_min]`
4.  Click **⏹ Stop Rec** to safely close all file streams and finalize text inputs without risk of memory leaks.

### Dynamic Path Routing
1.  Press **🛤 Create Route** to activate the path routing session.
2.  Use the **Right Mouse Button (RMB)** on the canvas to project sequentially ordered waypoints (`RoutePoint`).
3.  Open the non-modal `RouteDialog` to assign the completed route to a chosen vessel[cite: 11]. This activates the internal line-of-sight pathing system to track along the route waypoints automatically.
4.  Waypoints can be rearranged in real-time by holding down the **Left Mouse Button (LMB)** and dragging them across the chart area.


### LLM Connectivity Setup
1.  Navigate to **LLM $\rightarrow$ ⚙️ LLM Settings...** to adjust the active API parameters.
2.  Choose between local engines (**Ollama**) or specialized paid cloud endpoints (**OpenAI, DeepSeek, Anthropic, Google Gemini, Alibaba Qwen, Groq**).
3.  Input the required authentication key parameters; these keys are held securely in volatile memory and are never written to disk.
4.  Click **🔍 Test Connection** to send a small, isolated handshake request via LiteLLM to verify configuration parameters before starting the main simulation loop.

---

## Task Management (Scenarios)

The application includes a *Task Management* system located in the Tasks menu for reproducible scenario testing:

*   **Save Task**: Validates that vessels exist on the map (warns if empty). Prompts the user for a filename via `QInputDialog.getText()`. Automatically creates a `Tasks/` directory if it does not exist. Serializes all current vessel parameters into a structured JSON file. Displays a success confirmation message.

*   **Load Task**: Verifies the existence of the `Tasks/` directory and `.json` files. Presents a dropdown list of available tasks via `QInputDialog.getItem()`. Safely halts any running simulation and clears the canvas. Reconstructs the vessels with their exact saved states and parameters. Displays a summary of the loaded vessels.

---

## License
This software framework is distributed under the conditions of the MIT License. Review the explicit LICENSE file for strict details regarding copyright boundaries and permission authorizations.

## Developers

PI **Yaroslav Burylin** 

Navigation Department

Admiral Ushakov Maritime State University (AUMSU)

Novorossiysk, Russian Federation

Co-I **Irina Benedyk** 

Civil, Structural, and Environmental Department

State University of New York (SUNY) at Buffalo

Buffalo, USA
