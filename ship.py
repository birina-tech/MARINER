import numpy as np

class Ship:
    _counter = 0

    def __init__(self, x, y, psi_deg, speed_ms, name=None):
        Ship._counter += 1
        self.id = Ship._counter
        self.name = name or f"Ship_{self.id}" # Name of the ship for the GUI
        
        self.x = float(x) # Current 2D spatial coordinates of the vessel in meters
        self.y = float(y) # Current 2D spatial coordinates of the vessel in meters
        
        self.psi = np.deg2rad(float(psi_deg)) # Current heading (yaw angle) of the ship, converted from degrees to radians
        self.u = float(speed_ms) # Current forward speed of the ship in meters per second
        self.r = 0.0 # Current rate of turn (yaw rate) in radians per second
        self.T_psi = 30.0
        self.K_psi = 0.01
        self.T_v = 50.0
        self.K_v = 1.0
        self.rudder_cmd = 0.0
        self.rpm_cmd = 50.0
        self.rudder_max = 35.0
        self.rpm_max = 100.0
        self.history_x = [self.x]
        self.history_y = [self.y]
        self.max_history = 2000
        self.length = 100.0 # Vessel length in meters (for pivot calculation)
        self.width = 20.0
        self.bow_length = 10.0
        self.hull_length = 100.0
        self.color = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray'][(self.id - 1) % 8]
        self.llm_controlled = False
        self.llm_decision = None
        self.base_heading_deg = float(psi_deg)

        self.assigned_route = None  # Reference to Route object
        self.autopilot = None  # Instance of RouteAutopilot
        self.autopilot_enabled = False  # Autopilot active status flag
        
        # For tracking LLM maneuvers
        self.in_maneuver = False  # Flag: vessel is executing a collision avoidance maneuver
        self.maneuver_course_deg = None  # Target course assigned for the maneuver
        self.maneuver_target_course = None  # Intended terminal maneuver heading
        self.llm_reasoning = ""  # LLM decision reasoning
        
        # Initialize an empty list to store historical snapshots
        self.trajectory_history = []
        
        ### Track running set of active rules persistent until TCPA <= 0
        self.active_rules = {}  # Format: { "OtherShipName": set(["13", "14"]) }



    def update(self, dt):
        tau_c = np.clip(self.rudder_cmd * np.pi / 180 * (20 / 35), -20, 20)
        u_c = np.clip(self.rpm_cmd, 0, self.rpm_max) / 100.0
        r_dot = -(1 / self.T_psi) * self.r + (self.K_psi / self.T_psi) * tau_c
        u_dot = -(1 / self.T_v) * self.u + (self.K_v / self.T_v) * u_c * 5.0
        self.r = self.r + r_dot * dt
        self.u = max(0.0, self.u + u_dot * dt)
        x_dot = self.u * np.sin(self.psi)
        y_dot = self.u * np.cos(self.psi)
        sin_psi_next = np.sin(self.psi + self.r * dt)
        cos_psi_next = np.cos(self.psi + self.r * dt)
        self.x += x_dot * dt
        self.y += y_dot * dt
        self.psi = np.arctan2(sin_psi_next, cos_psi_next)
        self.history_x.append(self.x)
        self.history_y.append(self.y)
        if len(self.history_x) > self.max_history:
            self.history_x.pop(0)
            self.history_y.pop(0)

    def get_heading_deg(self): # Convert ship's heading from radians into a standard compass heading (in degrees)
        return np.mod(np.rad2deg(self.psi), 360)

    def get_rot(self):
        """
        Calculates and returns the live Rate of Turn (ROT) in degrees per minute.
        Converts internal yaw rate (radians/second) into degrees/minute.
        """
        return np.rad2deg(self.r) * 60.0

    def distance_to(self, px, py): # Calculates the exact straight-line distance between the ship's current position and any other specific point on the map
        return np.sqrt((self.x - px) ** 2 + (self.y - py) ** 2)

    def record_history_waypoint(self, current_time_s):
        """Records a snapshot of the ship's telemetry."""
        self.trajectory_history.append({
            "time": current_time_s,
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "heading": round(self.get_heading_deg(), 1),
            "speed": round(self.u, 1)
        })
        
        # Keep only the last 20 minutes (1200 seconds) of data to save memory
        self.trajectory_history = [wp for wp in self.trajectory_history if current_time_s - wp["time"] <= 1200]

    def get_pentagon_vertices(self): # UI function
        half_width = self.width / 2
        bow_x = self.length / 2
        stern_x = -self.length / 2
        bow_shoulder_x = bow_x - self.bow_length
        local_vertices = np.array([
            [bow_x, 0], [bow_shoulder_x, half_width],
            [stern_x, half_width], [stern_x, -half_width],
            [bow_shoulder_x, -half_width]
        ])
        sin_psi = np.sin(self.psi)
        cos_psi = np.cos(self.psi)
        rotation = np.array([[sin_psi, cos_psi], [cos_psi, -sin_psi]])
        return np.array([rotation @ v + np.array([self.x, self.y]) for v in local_vertices])

    def toggle_llm_control(self, enable=True):
        self.llm_controlled = enable

    def apply_llm_command(self, rudder_deg, rpm_percent): # Converts LLM rudder commands into actionable changes (with physical boundaries)
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
        
        # If the vessel is running under autopilot — display heading target parameters
        autopilot = getattr(self, 'autopilot', None)
        autopilot_enabled = getattr(self, 'autopilot_enabled', False)
        
        if autopilot_enabled and autopilot is not None:
            if autopilot.mode == 1:  # MODE_HOLD_COURSE
                # Display target heading maintained by active track control loop parameters
                hold_course = np.degrees(autopilot.hold_course_rad) if autopilot.hold_course_rad else None
                if hold_course is not None:
                    return f"\nLLM: HOLD {hold_course:.0f}\u00b0"
                else:
                    return "\nLLM: HOLD (no course)"
            else:
                # ROUTE Mode — vessel follows dynamic trajectory segments
                return "\nLLM: ROUTE"
        
        # Standard configuration without active autopilot — display commands parameters
        if self.llm_decision:
            rudder = self.llm_decision.get('rudder_deg', 0)
            rpm = self.llm_decision.get('rpm_percent', 50)
            return f"\nLLM: R={rudder:.0f}\u00b0 RPM={rpm:.0f}%"
        return "\nLLM: waiting..."

    def get_log_row(self, time_s):
        # Added fixed comma separator inside the log array string initialization block
        return [
            f"{time_s:.2f}",
            f"{self.x:.2f}",
            f"{self.y:.2f}",
            f"{self.get_heading_deg():.2f}",
            f"{self.u:.3f}",
            f"{self.rudder_cmd:.2f}",
            f"{self.rpm_cmd:.1f}",
            f"{self.get_rot():.2f}"  # ROT in degrees/minute
        ]

    def set_base_heading(self, heading_deg):
        """Set a new base heading degree and position (e.g., after Load Task)"""
        self.base_heading_deg = float(heading_deg)