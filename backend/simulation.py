"""
simulation.py

The headless replacement for ship_simulation.py's MainWindow. It owns the
ship list and simulation clock, steps physics, runs COLREGs analysis, and
dispatches to the LLM coordinator — the exact same responsibilities the
QTimer-driven MainWindow.simulation_step() had, minus every PyQt5 import.

main.py's asyncio loop calls SimulationEngine.step() on a real-time tick and
periodically calls SimulationEngine.maybe_trigger_llm() (fire-and-forget,
non-blocking), then serialize_state() for the WebSocket broadcast.
"""
import asyncio
import math
import os
import json
import numpy as np

from ship import Ship
from autopilot import RouteAutopilot
from route import Route
from collision_analyzer import CollisionAnalyzer
from colreg_rules import determine_colreg_situation
from llm_controller import LLMCoordinator
from prompts import PROMPT_REGISTRY
from vessel_spec import make_spec, spec_from_dict, list_classes, DEFAULT_CLASS, KN_TO_MS
from maneuvering import characteristics

# repo_root/Tasks — same convention as the original desktop app's Save/Load Task
TASKS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Tasks"
)

VALID_CONTROL_MODES = ('straight', 'route', 'manual', 'llm')

# Controllers (autopilot) run at most this far apart in simulated time, however
# large the speed-up (self.dt) is. Ship physics sub-steps further inside Ship.update().
CONTROL_DT = 1.0


class SimulationEngine:
    def __init__(self):
        self.ships = []
        self.routes = {}          # route_name -> Route
        self.running = False
        self.sim_time = 0.0
        self.dt = 1.0             # simulated seconds per physics step (matches original default)

        self.analyzer = CollisionAnalyzer()

        self.llm_coordinator = None      # created lazily via set_llm_provider()
        self.llm_update_interval = 3.0   # seconds of SIM time between LLM calls
        self.last_llm_update = 0.0
        self.llm_pending = False
        self.last_llm_status = None      # 'ok' | 'error' | None, for the frontend status light

    # ---------------------------------------------------------------- ships

    def add_ship(self, x, y, course_deg, speed_ms, name=None,
                 vessel_class=None, loading='laden', overrides=None, spec=None):
        """Create a vessel. `vessel_class`/`loading` pick a preset from
        vessel_spec.PRESETS; `overrides` (dict) adjusts individual spec fields
        (e.g. {'length': 120}); `spec` passes a ready VesselSpec instead."""
        if name and self.get_ship(name):
            raise ValueError(f"A vessel named '{name}' already exists")
        if spec is None:
            spec = make_spec(vessel_class or DEFAULT_CLASS, loading, **(overrides or {}))
        ship = Ship(x, y, course_deg, speed_ms, name=name, spec=spec)
        self.ships.append(ship)
        return ship

    def remove_ship(self, name):
        ship = self.get_ship(name)
        if ship:
            self.ships.remove(ship)

    def get_ship(self, name):
        return next((s for s in self.ships if s.name == name), None)

    def set_control(self, name, rudder_deg=None, rpm_percent=None,
                    rudder_delta=None, rpm_delta=None):
        """Absolute (rudder_deg / rpm_percent) or relative (rudder_delta /
        rpm_delta) orders. Relative orders are applied to the server's own
        current value, so rapid key presses are never lost to network latency
        or to a stale state message on the client."""
        ship = self.get_ship(name)
        if not ship:
            return False
        if rudder_deg is None and rudder_delta is not None:
            rudder_deg = ship.rudder_cmd + rudder_delta
        if rpm_percent is None and rpm_delta is not None:
            rpm_percent = ship.rpm_cmd + rpm_delta
        if rudder_deg is not None:
            ship.rudder_cmd = float(np.clip(rudder_deg, -ship.rudder_max, ship.rudder_max))
        if rpm_percent is not None:
            ship.rpm_cmd = float(np.clip(rpm_percent, ship.rpm_min, ship.rpm_max))
            if ship.rpm_cmd >= 0:
                # An operator-set RPM is the vessel's intended cruise; the LLM is
                # told to return to it after an avoidance maneuver. Astern orders
                # (emergency stops) don't redefine cruise.
                ship.cruise_rpm = ship.rpm_cmd
        return True

    def toggle_llm(self, name, enabled):
        ship = self.get_ship(name)
        if not ship:
            return False
        ship.llm_controlled = bool(enabled)
        return True

    # --------------------------------------------------------------- routes

    def assign_route(self, ship_name, points):
        """points: list of [x, y] pairs. Creates a Route + RouteAutopilot for the ship."""
        ship = self.get_ship(ship_name)
        if not ship:
            return False
        if len(points) < 2:
            raise ValueError('A route needs at least 2 points')
        route = Route()
        for x, y in points:
            route.add_point(x, y)
        route.assigned_ship = ship
        self.routes[route.name] = route

        ship.assigned_route = route
        ship.autopilot = RouteAutopilot(ship, route)
        ship.autopilot_enabled = True
        ship.llm_controlled = False
        ship.control_mode = 'route'
        return route.name

    def clear_route(self, ship_name):
        ship = self.get_ship(ship_name)
        if not ship:
            return False
        if ship.assigned_route and ship.assigned_route.name in self.routes:
            del self.routes[ship.assigned_route.name]
        ship.autopilot_enabled = False
        ship.autopilot = None
        ship.assigned_route = None
        ship.rudder_cmd = 0.0
        ship.control_mode = 'straight'
        return True

    def set_control_mode(self, ship_name, mode):
        """
        The single entry point for the 4 mutually-exclusive control modes:
        'straight' (default, neutral rudder), 'route' (follow an already-
        assigned path at constant speed), 'manual' (keyboard control — only
        one vessel may hold this at a time), 'llm' (swarm-coordinated).
        Returns (ok: bool, error_message: str | None).
        """
        ship = self.get_ship(ship_name)
        if not ship:
            return False, f"Unknown vessel: {ship_name}"
        if mode not in VALID_CONTROL_MODES:
            return False, f"Unknown control mode: {mode}"

        if mode == 'route':
            if not ship.assigned_route or not ship.autopilot:
                return False, "No path set for this vessel yet — use 'Set Path' first"
            ship.autopilot_enabled = True
            ship.llm_controlled = False
            ship.control_mode = 'route'
            return True, None

        if mode == 'manual':
            # Enforce "one vessel at a time": bump any other manual vessel back to straight.
            for other in self.ships:
                if other is not ship and other.control_mode == 'manual':
                    other.control_mode = 'straight'
                    other.autopilot_enabled = False
                    other.llm_controlled = False
                    other.rudder_cmd = 0.0
            ship.autopilot_enabled = False
            ship.llm_controlled = False
            ship.control_mode = 'manual'
            return True, None

        if mode == 'llm':
            ship.autopilot_enabled = False
            ship.llm_controlled = True
            ship.control_mode = 'llm'
            return True, None

        # 'straight'
        ship.autopilot_enabled = False
        ship.llm_controlled = False
        ship.control_mode = 'straight'
        ship.rudder_cmd = 0.0
        return True, None

    # ------------------------------------------------------------- physics

    def step(self):
        """One physics tick. Mirrors MainWindow.simulation_step()'s physics half."""
        if not self.running:
            return

        # Run the controllers and physics at a fixed fine rate no matter how
        # large the speed-up (self.dt) is, so changing the simulation speed
        # never changes how a vessel behaves (a 40 m tug has a ~6 s yaw time
        # constant and would hunt if its autopilot only ran every 5 s).
        n = max(1, math.ceil(self.dt / CONTROL_DT))
        h = self.dt / n
        for _ in range(n):
            for ship in self.ships:
                if getattr(ship, 'autopilot_enabled', False) and ship.autopilot:
                    ship.autopilot.update(h)
                else:
                    heading_diff = abs((ship.base_heading_deg - ship.get_heading_deg() + 180) % 360 - 180)
                    if heading_diff > 2:
                        ship.in_maneuver = True
                ship.update(h)

        self.sim_time += self.dt

    # ------------------------------------------------------------ colregs

    def compute_collision_pairs(self):
        """All-pairs COLREGs analysis, for the frontend table and the LLM prompt."""
        pairs = []
        for i in range(len(self.ships)):
            for j in range(i + 1, len(self.ships)):
                s1, s2 = self.ships[i], self.ships[j]
                cpa = self.analyzer.calculate_cpa_tcpa(s1, s2)
                risk = self.analyzer.calculate_risk_index(cpa['DCPA'], cpa['TCPA'], cpa['dist'])
                colreg = determine_colreg_situation(s1, s2, cpa['dist'], cpa['DCPA'], cpa['TCPA'])
                crossing = self.analyzer.calculate_course_crossing(s1, s2)

                pairs.append({
                    'ship1': s1.name,
                    'ship2': s2.name,
                    'dist_m': float(cpa['dist']),
                    'dcpa_m': float(cpa['DCPA']),
                    'tcpa_s': None if cpa['TCPA'] == float('inf') else float(cpa['TCPA']),
                    'risk': float(risk),
                    'rule': colreg['rule'],
                    'situation': colreg['situation'],
                    'ship1_action': colreg['ship1_action'],
                    'ship2_action': colreg['ship2_action'],
                    'crossing_type': crossing['crossing_type'],
                })
        return pairs

    def collect_collision_data(self, pairs):
        """Reshape compute_collision_pairs() output into the per-ship JSON the
        VTS system prompt expects (backend/prompts/vts_default.py)."""
        ship_data_list = []
        for ship in self.ships:
            pairs_info = []
            must_yield = False
            for p in pairs:
                if p['ship1'] == ship.name:
                    other, tcpa, dcpa, rule, action = p['ship2'], p['tcpa_s'], p['dcpa_m'], p['rule'], p['ship1_action']
                elif p['ship2'] == ship.name:
                    other, tcpa, dcpa, rule, action = p['ship1'], p['tcpa_s'], p['dcpa_m'], p['rule'], p['ship2_action']
                else:
                    continue
                if 'Give-way' in action or 'Alter' in action:
                    must_yield = True
                pairs_info.append({
                    'other_ship': other,
                    'rule': rule,
                    'cpa_m': dcpa,
                    'tcpa_s': 99999.0 if tcpa is None else tcpa,
                })

            ship_data_list.append({
                'name': ship.name,
                'llm_controlled': bool(ship.llm_controlled),
                'current_heading_deg': float(ship.get_heading_deg()),
                'base_heading_deg': float(ship.base_heading_deg),
                'heading_diff_deg': float(abs((ship.base_heading_deg - ship.get_heading_deg() + 180) % 360 - 180)),
                'speed_ms': float(ship.u),
                'current_rudder': float(ship.rudder_cmd),
                'current_rpm': float(ship.rpm_cmd),
                'cruise_rpm': float(ship.cruise_rpm),
                'status': 'MUST_YIELD' if must_yield else 'HOLD_COURSE',
                'no_left_turn': False,
                'in_maneuver': ship.in_maneuver,
                'maneuver_course_deg': ship.maneuver_course_deg,
                'maneuver_target_course': ship.maneuver_target_course,
                'autopilot_enabled': getattr(ship, 'autopilot_enabled', False),
                'autopilot_mode': (
                    ("HOLD" if ship.autopilot.mode == 1 else "ROUTE")
                    if getattr(ship, 'autopilot', None) else None
                ),
                'assigned_route': ship.assigned_route.name if getattr(ship, 'assigned_route', None) else None,
                'pairs': pairs_info,
            })
        return {'ships': ship_data_list}

    # ------------------------------------------------------------ scenarios

    def list_scenarios(self):
        os.makedirs(TASKS_DIR, exist_ok=True)
        return sorted(f[:-5] for f in os.listdir(TASKS_DIR) if f.endswith('.json'))

    def save_scenario(self, name):
        os.makedirs(TASKS_DIR, exist_ok=True)
        data = {'ships': []}
        for ship in self.ships:
            data['ships'].append({
                'name': ship.name,
                'x': ship.x,
                'y': ship.y,
                'course_deg': float(ship.get_heading_deg()),
                'speed_ms': float(ship.u),
                'rudder_cmd': float(ship.rudder_cmd),
                'rpm_cmd': float(ship.rpm_cmd),
                # Full vessel spec + actuator/yaw state: a scenario keeps its
                # exact ships even if the presets change later (reproducibility).
                'spec': ship.spec.to_dict(),
                'cruise_rpm': float(ship.cruise_rpm),
                'rpm_actual': float(ship.rpm_actual),
                'rudder_angle': float(ship.rudder_angle),
                'yaw_rate': float(ship.r),
                'control_mode': ship.control_mode,
                'route_points': (
                    ship.assigned_route.get_coordinates_list()
                    if ship.assigned_route else None
                ),
            })
        safe_name = "".join(c for c in name if c.isalnum() or c in ("_", "-")) or "scenario"
        path = os.path.join(TASKS_DIR, f"{safe_name}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return safe_name

    def load_scenario(self, name):
        safe_name = "".join(c for c in name if c.isalnum() or c in ("_", "-"))
        path = os.path.join(TASKS_DIR, f"{safe_name}.json")
        if not os.path.exists(path):
            return False, f"No such scenario: {name}"

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Halt and clear the running scene before rebuilding it — mirrors the
        # original desktop app's "Load Task safely halts the simulation" step.
        # Atomic: if anything in the file is invalid, the previous scene is
        # restored instead of leaving the user with an empty map.
        backup = (self.ships, self.routes, self.running)
        self.running = False
        self.ships = []
        self.routes = {}

        try:
            for entry in data.get('ships', []):
                has_spec = 'spec' in entry
                ship = self.add_ship(
                    x=entry['x'], y=entry['y'],
                    course_deg=entry['course_deg'], speed_ms=entry['speed_ms'],
                    name=entry['name'],
                    spec=spec_from_dict(entry.get('spec')),   # old files: default class
                )
                ship.rudder_cmd = entry.get('rudder_cmd', 0.0)
                if has_spec:
                    # New-format file: restore the exact dynamic state.
                    ship.rpm_cmd = entry.get('rpm_cmd', ship.rpm_cmd)
                    ship.rpm_actual = entry.get('rpm_actual', ship.rpm_cmd)
                    ship.cruise_rpm = entry.get('cruise_rpm', ship.rpm_cmd)
                    ship.rudder_angle = entry.get('rudder_angle', 0.0)
                    ship.r = entry.get('yaw_rate', 0.0)
                # Old-format files (no 'spec') stored RPM on a different scale;
                # leave the vessel holding its saved speed instead.

                # Recreate the route object first (if any) regardless of which
                # mode was active when saved, so a vessel that had a path but was
                # switched to e.g. manual doesn't lose the path on reload.
                if entry.get('route_points'):
                    self.assign_route(ship.name, entry['route_points'])

                mode = entry.get('control_mode', 'straight')
                if mode != 'route':
                    self.set_control_mode(ship.name, mode)
        except Exception as e:
            self.ships, self.routes, self.running = backup
            return False, f"Could not load scenario '{name}': {e}"

        return True, None

    # ----------------------------------------------------------------- LLM

    @staticmethod
    def available_vessel_classes():
        """Class catalogue for the add-vessel dialog, including maneuvering
        figures (turning diameter, stopping distance) measured on the real
        ship model by maneuvering.characteristics() (cached)."""
        from vessel_spec import make_spec as _mk
        classes = list_classes()
        for c in classes:
            for loading, info in c['loadings'].items():
                info.update(characteristics(_mk(c['id'], loading)))
        return classes

    @staticmethod
    def available_prompts():
        return list(PROMPT_REGISTRY.keys())

    @staticmethod
    def available_providers():
        return list(LLMCoordinator.PROVIDERS.keys())

    def set_llm_provider(self, provider, model=None, api_key=None, prompt_name='vts_default'):
        self.llm_coordinator = LLMCoordinator(
            provider=provider, model=model, api_key=api_key, prompt_name=prompt_name
        )

    async def maybe_trigger_llm(self, pairs):
        """Fire-and-forget LLM call, run off the event loop thread so the
        50ms physics tick never blocks on a network request."""
        llm_ships = [s for s in self.ships if s.llm_controlled]
        if not llm_ships or self.llm_pending or self.llm_coordinator is None:
            return
        if (self.sim_time - self.last_llm_update) < self.llm_update_interval:
            return

        self.last_llm_update = self.sim_time
        self.llm_pending = True
        collision_data = self.collect_collision_data(pairs)

        try:
            commands = await asyncio.to_thread(
                self.llm_coordinator.get_coordinated_commands, self.ships, collision_data
            )
            self.llm_coordinator.apply_commands(self.ships, commands)
            self._update_maneuver_flags()
            self.last_llm_status = self.llm_coordinator.last_status
        except Exception as e:
            self.last_llm_status = 'error'
            print(f"[SimulationEngine] LLM call failed: {e}")
        finally:
            self.llm_pending = False

    def _update_maneuver_flags(self):
        """Mirrors MainWindow.on_llm_result()'s maneuver bookkeeping."""
        for ship in self.ships:
            if not ship.llm_controlled:
                continue
            autopilot = getattr(ship, 'autopilot', None)
            autopilot_enabled = getattr(ship, 'autopilot_enabled', False)

            if autopilot_enabled and autopilot and autopilot.mode == 1:  # MODE_HOLD_COURSE
                current_heading = ship.get_heading_deg()
                target_course = autopilot.hold_course_rad
                if target_course is not None:
                    target_deg = np.degrees(target_course)
                    heading_diff = abs((current_heading - target_deg + 180) % 360 - 180)
                    if heading_diff <= 5.0:
                        if ship.in_maneuver:
                            ship.in_maneuver = False
                            ship.maneuver_course_deg = None
                            ship.maneuver_target_course = None
                    else:
                        if not ship.in_maneuver:
                            ship.in_maneuver = True
                            ship.maneuver_target_course = target_deg
            else:
                if ship.in_maneuver:
                    ship.in_maneuver = False
                    ship.maneuver_course_deg = None
                    ship.maneuver_target_course = None

    # ------------------------------------------------------------- output

    def serialize_state(self, pairs):
        """The payload broadcast to every connected browser each tick."""
        ships_out = []
        for ship in self.ships:
            ships_out.append({
                'name': ship.name,
                'x': ship.x,
                'y': ship.y,
                'heading_deg': float(ship.get_heading_deg()),
                'speed_ms': float(ship.u),
                'rot_deg_min': float(ship.get_rot()),
                'rudder_cmd': float(ship.rudder_cmd),
                'rudder_angle': float(ship.rudder_angle),
                'rpm_cmd': float(ship.rpm_cmd),
                'rpm_actual': float(ship.rpm_actual),
                'rpm_min': float(ship.rpm_min),
                'cruise_rpm': float(ship.cruise_rpm),
                'vessel_class': ship.spec.class_id,
                'class_name': ship.spec.class_name,
                'loading': ship.spec.loading,
                'length': float(ship.spec.length),
                'beam': float(ship.spec.beam),
                'draft': float(ship.spec.draft),
                'displacement_t': float(ship.spec.displacement_t),
                'max_speed_ms': float(ship.spec.max_speed_ms),
                'color': ship.color,
                'llm_controlled': ship.llm_controlled,
                'in_maneuver': ship.in_maneuver,
                'autopilot_enabled': getattr(ship, 'autopilot_enabled', False),
                'control_mode': ship.control_mode,
                'has_route': ship.assigned_route is not None,
                'llm_status_text': ship.get_llm_status_text(),
                # world-space hull polygon — frontend just draws this, no
                # rotation math needed client-side
                'hull': ship.get_pentagon_vertices().tolist(),
            })

        return {
            'type': 'state',
            'sim_time': self.sim_time,
            'running': self.running,
            'llm_pending': self.llm_pending,
            'llm_status': self.last_llm_status,
            'llm_configured': self.llm_coordinator is not None,
            'ships': ships_out,
            'collision_pairs': pairs,
            'routes': {
                name: route.get_coordinates_list() for name, route in self.routes.items()
            },
        }
