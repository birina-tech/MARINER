"""
autopilot.py
Autonomous surface vessel autopilot based on the work of Burylin Ya.V., Popov A.N.

Formula (1): Maneuver commencement distance depends on the turn angle (table lookup)
Formula (2): Switching to the next leg when d2 < turn_dist(angle) or d2 < d1
Formula (3): Hierarchical PID (heading) + P (cross-track deviation) controller
"""
import numpy as np


class RouteAutopilot:
    """
    Autopilot based on the work of Burylin Ya.V., Popov A.N.
    
    Control law (formula 3):
    δ = a_pr*(K - Kp) + a_in*(K-Kp)dt + a_d*d(K-Kp)/dt + b_pr*χ
    
    where:
    - K, Kp - actual and assigned courses (in degrees)
    - χ - trajectory cross-track error (in meters)
    - b_pr*χ - heading correction relative to cross-track error (in degrees)
    - a_pr, a_in, a_d, b_pr - controller coefficients
    """
    
    MODE_ROUTE = 0
    MODE_HOLD_COURSE = 1
    
    def __init__(self, ship, route):
        self.ship = ship
        self.route = route
        
        self.ship_length = getattr(ship, 'length', 100.0)
        
        # === MANEUVER START DISTANCE TABLE (formula 1) ===
        # Empirical dependence of maneuver start distance on the turn angle
        self.turn_distance_table = {
            30: 500,
            45: 700,
            60: 900,
            90: 1200,
            120: 1600,
            180: 2200,
        }
        
        # === CONTROLLER COEFFICIENTS (formula 3) ===
        # PID heading controller (operates with DEGREES)
        self.a_pr = 3.0
        self.a_in = 0.002
        self.a_d = 0.3
        
        # P controller for cross-track trajectory deviation
        self.b_pr = 0.01
        self.b_in = 0.0
        
        # Integrals for the controller mechanism
        self.integral_heading_error = 0.0
        self.prev_heading_error = 0.0
        self.integral_cross_track = 0.0
        
        # Operational constraints
        self.max_rudder = 35.0  # degrees
        self.max_course_correction = 30.0  # degrees (maximum correction applied for deviation error)
        
        # === PARAMETERS ===
        self.mode = self.MODE_ROUTE
        self.hold_course_rad = None
        self.current_segment_index = 0
        
        # Flag indicating whether the first leg of the route trajectory has been reached
        self.reached_first_leg = False
        
        # === DEBUG DATA CONTAINERS (for UI mapping) ===
        self.debug_d1 = 0.0
        self.debug_d2 = 0.0
        self.debug_cross_track = 0.0
        self.debug_course_correction = 0.0
        self.debug_course_on_leg = 0.0
        self.debug_segment_name = ""
        self.debug_route_name = ""
        self.debug_turn_distance = 0.0  # Maneuver start threshold fetched from interpolation matrix
        self.debug_turn_angle = 0.0     # Angular variation turn angle

    def set_hold_course(self, course_deg):
        """Switch over to hold course configuration (invoked via high level LLM directive)"""
        self.mode = self.MODE_HOLD_COURSE
        self.hold_course_rad = np.deg2rad(course_deg)
        self.reset_integrals()
        print(f"[Autopilot] {self.ship.name}: HOLD COURSE {course_deg:.1f}\u00b0")

    def resume_route(self):
        """Resume tracking along structured route layout points"""
        if self.mode == self.MODE_ROUTE:
            return
        self.mode = self.MODE_ROUTE
        self.hold_course_rad = None
        self.reset_integrals()
        print(f"[Autopilot] {self.ship.name}: RESUME ROUTE")

    def reset_integrals(self):
        """Reset internal accumulator registers to zero"""
        self.integral_heading_error = 0.0
        self.prev_heading_error = 0.0
        self.integral_cross_track = 0.0

    def get_turn_distance(self, turn_angle_deg):
        """
        Fetch dynamic maneuver threshold distance utilizing angular turn boundaries.
        Linearly interpolates across stored configuration data mappings.
        """
        if turn_angle_deg <= 0:
            return 0
        
        angles = sorted(self.turn_distance_table.keys())
        
        if turn_angle_deg <= angles[0]:
            return self.turn_distance_table[angles[0]]
        
        if turn_angle_deg >= angles[-1]:
            return self.turn_distance_table[angles[-1]]
        
        # Linear interpolation
        for i in range(len(angles) - 1):
            if angles[i] <= turn_angle_deg <= angles[i+1]:
                a1, a2 = angles[i], angles[i+1]
                d1, d2 = self.turn_distance_table[a1], self.turn_distance_table[a2]
                return d1 + (d2 - d1) * (turn_angle_deg - a1) / (a2 - a1)
        
        return self.turn_distance_table[angles[-1]]

    def find_nearest_point_and_segment(self, ship_pos, preferred_seg_idx=None):
        """
        Locate closest tracking coordinate target vector line mapping.
        Begins searching from preferred track index baseline boundary maps.
        """
        if not self.route or len(self.route.points) < 2:
            return None, None, None, 0.0, float('inf')
        
        # Begin tracking search using provided structural leg references
        start_idx = preferred_seg_idx if preferred_seg_idx is not None else 0
        # Prevent boundary overflow anomalies
        if start_idx >= len(self.route.points) - 1:
            start_idx = len(self.route.points) - 2
            
        min_dist = float('inf')
        best_seg_idx = start_idx
        best_t = 0.0
        best_closest_point = None
        
        # Scan forward from the indexed target point leg constraint
        for i in range(start_idx, len(self.route.points) - 1):
            p1 = np.array([self.route.points[i].x, self.route.points[i].y])
            p2 = np.array([self.route.points[i+1].x, self.route.points[i+1].y])
            
            v_seg = p2 - p1
            v_ship = ship_pos - p1
            
            seg_len_sq = np.dot(v_seg, v_seg)
            if seg_len_sq == 0:
                continue
            
            t = np.dot(v_ship, v_seg) / seg_len_sq
            t = np.clip(t, 0.0, 1.0)
            
            closest_point = p1 + t * v_seg
            dist = np.linalg.norm(ship_pos - closest_point)
            
            if dist < min_dist:
                min_dist = dist
                best_seg_idx = i
                best_t = t
                best_closest_point = closest_point
        
        # Cross-track error evaluation logic
        cross_track = 0.0
        if best_seg_idx < len(self.route.points) - 1:
            p1 = np.array([self.route.points[best_seg_idx].x, self.route.points[best_seg_idx].y])
            p2 = np.array([self.route.points[best_seg_idx+1].x, self.route.points[best_seg_idx+1].y])
            
            v_seg = p2 - p1
            v_seg_norm = v_seg / np.linalg.norm(v_seg)
            
            v_error = ship_pos - best_closest_point
            # Direction mapping sign representation: positive means right of route axis line
            cross_track = v_seg_norm[0] * v_error[1] - v_seg_norm[1] * v_error[0]
        
        return best_seg_idx, best_t, best_closest_point, cross_track, min_dist

    def distance_to_line(self, point, line_start, line_end):
        """
        Calculate perpendicular projection offset to infinite path line vector.
        """
        line_vec = line_end - line_start
        point_vec = point - line_start
        line_len = np.linalg.norm(line_vec)
        
        if line_len == 0:
            return np.linalg.norm(point_vec)
        
        # Vector cross product mapping logic in 2D coordinate environments
        cross = abs(line_vec[0] * point_vec[1] - line_vec[1] * point_vec[0])
        return cross / line_len

    def calculate_distances(self, ship_pos, seg_idx):
        """
        Calculate d1 and d2 offsets to support waypoint index switching formulas.
        
        d1 - distance to the tracking boundary axis line segment
        d2 - distance to the upcoming forward planning leg vector layout
        """
        if seg_idx is None or seg_idx >= len(self.route.points) - 1:
            return None, None
        
        # Locate path coordinate nodes matching current tracker segments
        p1 = np.array([self.route.points[seg_idx].x, self.route.points[seg_idx].y])
        p2 = np.array([self.route.points[seg_idx+1].x, self.route.points[seg_idx+1].y])
        
        # d1 calculation
        d1 = self.distance_to_line(ship_pos, p1, p2)
        
        # d2 calculation executed only if forward targets remain visible
        d2 = None
        if seg_idx < len(self.route.points) - 2:
            p3 = np.array([self.route.points[seg_idx+2].x, self.route.points[seg_idx+2].y])
            d2 = self.distance_to_line(ship_pos, p2, p3)
        
        return d1, d2

    def calculate_desired_course(self, ship_pos, seg_idx):
        """
        Determine target course while scanning upcoming leg path shifts.
        Applies upcoming leg heading targets early if near turn indices.
        """
        if seg_idx is None or seg_idx < 0 or seg_idx >= len(self.route.points) - 1:
            if len(self.route.points) >= 2:
                seg_idx = len(self.route.points) - 2
            else:
                return None, 0
        
        p1 = np.array([self.route.points[seg_idx].x, self.route.points[seg_idx].y])
        p2 = np.array([self.route.points[seg_idx+1].x, self.route.points[seg_idx+1].y])
        
        v_current = p2 - p1
        current_course = np.arctan2(v_current[0], v_current[1])
        
        # Validate turn constraints mapping to adjacent track vectors
        if seg_idx < len(self.route.points) - 2:
            p3 = np.array([self.route.points[seg_idx+2].x, self.route.points[seg_idx+2].y])
            v_next = p3 - p2
            
            angle_rad = np.arctan2(v_next[1], v_next[0]) - np.arctan2(v_current[1], v_current[0])
            angle_deg = abs(np.degrees(angle_rad))
            angle_deg = min(angle_deg, 360 - angle_deg)
            
            # Linear distance tracking bounds mapping to target node
            d2 = np.linalg.norm(ship_pos - p2)
            turn_dist = self.get_turn_distance(angle_deg)
            
            # If tracking inside lookahead range, switch targeted vectors early
            if d2 < turn_dist:
                next_course = np.arctan2(v_next[0], v_next[1])
                return next_course, angle_deg
        
        return current_course, 0

    def update(self, dt):
        """
        Execute core cyclical autopilot guidance synchronization update step.
        Implements rule equation tracking properties mapped from source documentation.
        """
        if not self.route or len(self.route.points) < 2:
            self.ship.rudder_cmd = 0
            return

        # === CORE GEOMETRIC PATH MATHEMATICS (Executed continuously for background metrics tracking) ===
        ship_pos = np.array([self.ship.x, self.ship.y])
        
        # Calculate nearest track coordinates mapping from modern telemetry positions
        seg_idx, t, closest_point, cross_track, min_dist = \
            self.find_nearest_point_and_segment(ship_pos, self.current_segment_index)
        
        if seg_idx is None or closest_point is None:
            self.ship.rudder_cmd = 0
            return
        
        # Check tracking parameters to verify baseline path arrival thresholds
        if seg_idx == 0 and t > 0.1:
            self.reached_first_leg = True
        
        # Retain live error offsets to pass into global state machines
        self.debug_cross_track = cross_track
        
        # Execute line calculations
        d1, d2 = self.calculate_distances(ship_pos, seg_idx)
        
        # Sync parameters to feed diagnostic frames
        self.debug_d1 = d1 if d1 is not None else 0.0
        self.debug_d2 = d2 if d2 is not None else 0.0
        
        # Assign UI trace values
        if seg_idx < len(self.route.points) - 1:
            name1 = self.route.points[seg_idx].name if hasattr(self.route.points[seg_idx], 'name') else f"P{seg_idx+1}"
            name2 = self.route.points[seg_idx+1].name if hasattr(self.route.points[seg_idx+1], 'name') else f"P{seg_idx+2}"
            self.debug_segment_name = f"{name1}-{name2}"
        else:
            self.debug_segment_name = "END"
        
        self.debug_route_name = self.route.name if self.route else ""

        # === HOLD COURSE OPERATIONAL STATE LOCK CHECK ===
        if self.mode == self.MODE_HOLD_COURSE:
            if self.hold_course_rad is None:
                self.ship.rudder_cmd = 0
                return
            
            current_heading = self.ship.psi
            heading_error = self.hold_course_rad - current_heading
            heading_error = np.arctan2(np.sin(heading_error), np.cos(heading_error))
            
            # Execute standard angular PID tracking loop adjustments only
            error_deg = np.degrees(heading_error)
            rudder_cmd = self.calculate_rudder_from_heading_error(error_deg, dt)
            self.ship.rudder_cmd = np.clip(rudder_cmd, -self.max_rudder, self.max_rudder)
            return

        # === ROUTE PLANNING PATH TRAJECTORY FOLLOW MODE ===
        if d1 is not None and d2 is not None and seg_idx < len(self.route.points) - 2:
            # Map out forward turn metrics
            p_next = np.array([self.route.points[seg_idx+1].x, self.route.points[seg_idx+1].y])
            if seg_idx < len(self.route.points) - 2:
                p_next2 = np.array([self.route.points[seg_idx+2].x, self.route.points[seg_idx+2].y])
                v_curr = p_next - np.array([self.route.points[seg_idx].x, self.route.points[seg_idx].y])
                v_next = p_next2 - p_next
                angle_rad = np.arctan2(v_next[1], v_next[0]) - np.arctan2(v_curr[1], v_curr[0])
                turn_angle = abs(np.degrees(angle_rad))
                turn_angle = min(turn_angle, 360 - turn_angle)
            else:
                turn_angle = 0
            
            turn_dist = self.get_turn_distance(turn_angle)
            self.debug_turn_distance = turn_dist
            self.debug_turn_angle = turn_angle
            
            # Switch structural targets if lookahead boundaries evaluate true
            if d2 < turn_dist or d2 < d1:
                seg_idx = seg_idx + 1
                self.current_segment_index = seg_idx
                self.reset_integrals()
                print(f"[Autopilot] {self.ship.name}: Switched to segment {seg_idx} (d2={d2:.0f}m < turn_dist={turn_dist:.0f}m)")
        
        # Generate optimal heading values
        desired_course, turn_angle = self.calculate_desired_course(ship_pos, seg_idx)
        
        if desired_course is None:
            # Drop back to tracking terminal node coordinates if interpolation fails
            if seg_idx < len(self.route.points) - 1:
                p1 = np.array([self.route.points[seg_idx].x, self.route.points[seg_idx].y])
                p2 = np.array([self.route.points[seg_idx+1].x, self.route.points[seg_idx+1].y])
                desired_course = np.arctan2(p2[0] - p1[0], p2[1] - p1[1])
            else:
                self.ship.rudder_cmd = 0
                return
        
        # === TRACK LAW CALCULATION POLICIES ===
        # Apply cross-track offset adjustment weights if structural alignment checks pass
        if self.reached_first_leg:
            course_correction_deg = self.b_pr * cross_track
            course_correction_deg = np.clip(course_correction_deg, -self.max_course_correction, self.max_course_correction)
        else:
            course_correction_deg = 0.0
        
        # Store corrections to drive context windows
        self.debug_course_correction = course_correction_deg
        self.debug_course_on_leg = np.degrees(desired_course)
        
        # Amalgamate course values
        desired_heading_deg = np.degrees(desired_course) + course_correction_deg
        
        # Calculate divergence
        current_heading_deg = np.degrees(self.ship.psi)
        heading_error_deg = desired_heading_deg - current_heading_deg
        heading_error_deg = (heading_error_deg + 180) % 360 - 180
        
        # Drive output command limits
        rudder_cmd = self.calculate_rudder_from_heading_error(heading_error_deg, dt)
        self.ship.rudder_cmd = np.clip(rudder_cmd, -self.max_rudder, self.max_rudder)
        
        # Check arrival status variables
        if seg_idx >= len(self.route.points) - 2:
            dist_to_end = np.linalg.norm(ship_pos - closest_point)
            if dist_to_end < self.ship_length:
                self.reset_integrals()
                self.ship.rudder_cmd = 0

    def calculate_rudder_from_heading_error(self, error_deg, dt):
        """
        Derive targeted actuator assignments utilizing localized tracking angular drift.
        Operates natively using DEGREES scaling properties.
        δ = a_pr * e + a_in * ∫e dt + a_d * de/dt
        """
        # Proportional factor calculation
        p_term = self.a_pr * error_deg
        
        # Integral tracking limits factoring anti-windup properties
        self.integral_heading_error += error_deg * dt
        max_integral = (self.max_rudder - abs(p_term)) / self.a_in if self.a_in != 0 else 0
        self.integral_heading_error = np.clip(self.integral_heading_error, -max_integral, max_integral)
        i_term = self.a_in * self.integral_heading_error
        
        # Derivative value checks
        derivative = (error_deg - self.prev_heading_error) / dt if dt > 0 else 0
        d_term = self.a_d * derivative
        
        self.prev_heading_error = error_deg
        
        return p_term + i_term + d_term

    def get_debug_info(self):
        """Build contextual property structures to populate interface dialog trackers"""
        info = {
            'route_name': self.debug_route_name,
            'segment': self.debug_segment_name,
            'd1': self.debug_d1,
            'd2': self.debug_d2,
            'cross_track': self.debug_cross_track,
            'course_on_leg': self.debug_course_on_leg,
            'course_correction': self.debug_course_correction,
            'rudder_cmd': self.ship.rudder_cmd,
            'mode': "ROUTE" if self.mode == self.MODE_ROUTE else "HOLD",
            'hold_course': np.degrees(self.hold_course_rad) if self.hold_course_rad else None,
            'turn_distance': self.debug_turn_distance,
            'turn_angle': self.debug_turn_angle,
        }
        return info