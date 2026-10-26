import math
import numpy as np

from vessel_spec import make_spec, KN_TO_MS

# ---- model constants -------------------------------------------------------
U_FLOOR = 1.0       # m/s: floor on speed used in the yaw time constant (avoids T -> infinity)
TURN_DRAG = 0.8     # extra resistance at full rudder (speed loss in turns), x(rudder/max)^2
BOW_FRACTION = 0.15 # length of the pointed bow section, fraction of L

_PALETTE = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']


def _wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class Ship:
    _counter = 0

    # Integration sub-step (s). update(dt) with a large dt (simulation speed-up)
    # is split into sub-steps no longer than this, so accuracy does not depend
    # on how fast the user runs the simulation.
    max_substep = 0.25

    def __init__(self, x, y, psi_deg, speed_ms, name=None, spec=None, register=True):
        if register:
            Ship._counter += 1
            self.id = Ship._counter
            self.name = name or f"Ship_{self.id}"
            self.color = _PALETTE[(self.id - 1) % len(_PALETTE)]
        else:
            # Used by maneuvering tests: must not consume a "Ship_N" name.
            self.id = 0
            self.name = name or "_test"
            self.color = 'gray'

        self.spec = spec if spec is not None else make_spec()

        # ---- state ----
        self.x = float(x)
        self.y = float(y)
        self.psi = math.radians(float(psi_deg))
        self.u = float(min(max(speed_ms, 0.0), self.spec.max_speed_ms))
        self.r = 0.0

        # ---- controls ----
        # *_cmd is what the helmsman/autopilot/LLM orders; the actuators
        # (rudder_angle, rpm_actual) follow it at a limited rate.
        self.rudder_cmd = 0.0
        self.rudder_angle = 0.0
        self.rudder_max = self.spec.rudder_max_deg
        self.rpm_max = 100.0
        self.rpm_min = self.spec.rpm_astern_min
        # Start in equilibrium: hold the initial speed instead of drifting to a
        # fixed default.
        self.rpm_cmd = self.spec.rpm_for_speed(self.u)
        self.rpm_actual = self.rpm_cmd
        self.cruise_rpm = self.rpm_cmd     # nominal RPM the LLM is told to return to

        # ---- geometry (hull drawn to scale) ----
        self.length = self.spec.length
        self.hull_length = self.spec.length
        self.width = self.spec.beam
        self.bow_length = BOW_FRACTION * self.spec.length

        # ---- history / bookkeeping ----
        self.history_x = [self.x]
        self.history_y = [self.y]
        self.max_history = 2000

        self.llm_controlled = False
        self.llm_decision = None
        self.control_mode = 'straight'  # 'straight' | 'route' | 'manual' | 'llm'
        self.base_heading_deg = float(psi_deg)
        self.in_maneuver = False
        self.llm_reasoning = ""

        self.assigned_route = None
        self.autopilot = None
        self.autopilot_enabled = False
        self.maneuver_course_deg = None
        self.maneuver_target_course = None

    # ------------------------------------------------------------------ physics

    def _step(self, dt):
        spec = self.spec

        # rudder actuator: rate-limited
        cmd = min(max(self.rudder_cmd, -spec.rudder_max_deg), spec.rudder_max_deg)
        max_move = spec.rudder_rate_deg_s * dt
        self.rudder_angle += min(max(cmd - self.rudder_angle, -max_move), max_move)

        # engine order: rate-limited ramp
        order = min(max(self.rpm_cmd, spec.rpm_astern_min), self.rpm_max)
        max_ramp = spec.engine_ramp_pct_s * dt
        self.rpm_actual += min(max(order - self.rpm_actual, -max_ramp), max_ramp)

        # surge: mass x acceleration = thrust - resistance
        n = self.rpm_actual / 100.0
        thrust = spec.thrust(n, self.u)
        rudder_frac = abs(self.rudder_angle) / spec.rudder_max_deg
        resistance = spec.resistance(self.u) * (1.0 + TURN_DRAG * rudder_frac * rudder_frac)
        u_dot = (thrust - resistance) / spec.m_eff_kg
        self.u = max(0.0, self.u + u_dot * dt)

        # yaw: nondimensional Nomoto with cubic damping
        L = spec.length
        u_eff = max(self.u, U_FLOOR)
        T = spec.t_prime * L / u_eff
        K = spec.k_prime * self.u / L
        delta = math.radians(self.rudder_angle)
        scale = (L / u_eff) ** 2
        r_dot = (K * delta - self.r - spec.alpha * scale * self.r ** 3) / T
        self.r += r_dot * dt

        # kinematics (heading at the middle of the step)
        psi_mid = self.psi + 0.5 * self.r * dt
        self.x += self.u * math.sin(psi_mid) * dt
        self.y += self.u * math.cos(psi_mid) * dt
        self.psi = _wrap(self.psi + self.r * dt)

    def update(self, dt):
        n_sub = max(1, math.ceil(dt / self.max_substep))
        h = dt / n_sub
        for _ in range(n_sub):
            self._step(h)
        self.history_x.append(self.x)
        self.history_y.append(self.y)
        if len(self.history_x) > self.max_history:
            self.history_x.pop(0)
            self.history_y.pop(0)

    # ------------------------------------------------------- state snapshot

    _SNAP_KEYS = ('x', 'y', 'psi', 'u', 'r', 'rudder_cmd', 'rudder_angle',
                  'rpm_cmd', 'rpm_actual')

    def snapshot(self):
        """Dynamic state, for look-ahead predictions that must not disturb the ship."""
        snap = {k: getattr(self, k) for k in self._SNAP_KEYS}
        snap['history_len'] = len(self.history_x)
        return snap

    def restore(self, snap):
        for k in self._SNAP_KEYS:
            setattr(self, k, snap[k])
        n = snap['history_len']
        del self.history_x[n:]
        del self.history_y[n:]

    # -------------------------------------------------------------- helpers

    def get_heading_deg(self):
        return np.mod(np.rad2deg(self.psi), 360)

    def get_rot(self):
        """Rate of turn in degrees per minute."""
        return self.r * (180.0 / math.pi) * 60.0

    def get_speed_kn(self):
        return self.u / KN_TO_MS

    def distance_to(self, px, py):
        return math.hypot(self.x - px, self.y - py)

    def get_pentagon_vertices(self):
        half_width = self.width / 2
        bow_x = self.length / 2
        stern_x = -self.length / 2
        bow_shoulder_x = bow_x - self.bow_length
        local_vertices = np.array([
            [bow_x, 0], [bow_shoulder_x, half_width],
            [stern_x, half_width], [stern_x, -half_width],
            [bow_shoulder_x, -half_width]
        ])
        sin_psi = math.sin(self.psi)
        cos_psi = math.cos(self.psi)
        rotation = np.array([[sin_psi, cos_psi], [cos_psi, -sin_psi]])
        return np.array([rotation @ v + np.array([self.x, self.y]) for v in local_vertices])

    # ------------------------------------------------------------ LLM / modes

    def toggle_llm_control(self, enable=True):
        self.llm_controlled = enable

    def apply_llm_command(self, rudder_deg, rpm_percent):
        rudder_diff = rudder_deg - self.rudder_cmd
        if abs(rudder_diff) > 5:
            self.rudder_cmd += np.sign(rudder_diff) * 5
        else:
            self.rudder_cmd = rudder_deg
        rpm_diff = rpm_percent - self.rpm_cmd
        if abs(rpm_diff) > 10:
            self.rpm_cmd += np.sign(rpm_diff) * 10
        else:
            self.rpm_cmd = rpm_percent

    def get_llm_status_text(self):
        if not self.llm_controlled:
            return ""

        # Under autopilot: show the course it holds, not the rudder
        autopilot = getattr(self, 'autopilot', None)
        autopilot_enabled = getattr(self, 'autopilot_enabled', False)

        if autopilot_enabled and autopilot is not None:
            if autopilot.mode == 1:  # MODE_HOLD_COURSE
                hold_course = np.degrees(autopilot.hold_course_rad) if autopilot.hold_course_rad else None
                if hold_course is not None:
                    return f"\nLLM: HOLD {hold_course:.0f}°"
                else:
                    return "\nLLM: HOLD (no course)"
            else:
                return "\nLLM: ROUTE"

        if self.llm_decision:
            rudder = self.llm_decision.get('rudder_deg', 0)
            rpm = self.llm_decision.get('rpm_percent', 50)
            return f"\nLLM: R={rudder:.0f}° RPM={rpm:.0f}%"
        return "\nLLM: waiting..."

    def get_log_row(self, time_s):
        return [
            f"{time_s:.2f}",
            f"{self.x:.2f}",
            f"{self.y:.2f}",
            f"{self.get_heading_deg():.2f}",
            f"{self.u:.3f}",
            f"{self.rudder_cmd:.2f}",
            f"{self.rpm_cmd:.1f}",
            f"{self.get_rot():.2f}",  # ROT in deg/min
        ]

    def set_base_heading(self, heading_deg):
        """Set a new base heading (e.g. after Load Task)."""
        self.base_heading_deg = float(heading_deg)
