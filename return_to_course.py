import numpy as np

class TrajectoryAutopilot:
    """
    Hierarchical PD Autopilot based on Burylin & Popov (2019).
    Tuned for high-inertia Nomoto models.
    """
    def __init__(self):
        # Outer Loop (PD): Cross-Track Error -> Heading Correction
        self.b_pr = 0.005  # Reduced Proportional gain for XTE to prevent aggressive diving
        self.b_in = 0.0    # DISABLED Integral gain to prevent windup/figure-8s
        self.integral_chi = 0.0
        self.max_approach_angle_deg = 30.0 # Smoother intercept angle

        # Inner Loop (PD): Heading Error -> Rudder Command
        self.a_pr = 1.5   # Heading proportional gain
        self.a_in = 0.0   # DISABLED heading integral to prevent rudder oscillation
        self.a_d = 20.0   # INCREASED Derivative (damping) to brake the turn perfectly
        self.integral_heading = 0.0
        self.max_rudder_deg = 35.0

    def calculate_return_maneuver(self, x, y, base_x, base_y, current_heading_deg, base_heading_deg, angular_velocity_r, dt):
        """Calculates optimal Rudder and RPM to return to the original trajectory."""
        
        # Calculate Cross-Track Error (chi)
        base_heading_rad = np.radians(base_heading_deg)
        dx = x - base_x
        dy = y - base_y
        
        # chi > 0 means the ship is to the right of the path; chi < 0 means left.
        chi = dx * np.cos(base_heading_rad) - dy * np.sin(base_heading_rad)
        
        # Outer Loop: Calculate Heading Correction (No integral windup)
        self.integral_chi += chi * dt
        heading_correction_rad = -(self.b_pr * chi + self.b_in * self.integral_chi)
        
        # Clamp the approach angle
        max_corr_rad = np.radians(self.max_approach_angle_deg)
        heading_correction_rad = np.clip(heading_correction_rad, -max_corr_rad, max_corr_rad)
        
        # Inner Loop: Calculate Rudder Command
        target_heading_rad = base_heading_rad + heading_correction_rad
        current_heading_rad = np.radians(current_heading_deg)
        
        # Find shortest angular distance between current and target heading
        heading_error_rad = (target_heading_rad - current_heading_rad + np.pi) % (2 * np.pi) - np.pi
        
        self.integral_heading += heading_error_rad * dt
        
        # The PD equation for rudder execution
        rudder_cmd_rad = (self.a_pr * heading_error_rad + 
                          self.a_in * self.integral_heading - 
                          self.a_d * angular_velocity_r)
        
        rudder_deg = np.degrees(rudder_cmd_rad)
        rudder_deg = np.clip(rudder_deg, -self.max_rudder_deg, self.max_rudder_deg)
        
        # RPM Calculation
        if abs(rudder_deg) > 15.0:
            rpm_percent = 40.0
        else:
            rpm_percent = 50.0
            
        return float(rudder_deg), float(rpm_percent)