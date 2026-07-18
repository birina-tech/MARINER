"""
colreg_rules.py
Determination of COLREGs rules based on relative bearings
With integrated customizable parameters
"""
import numpy as np
from rules_settings import get_rules_settings


def calculate_relative_bearing(ship1, ship2):
    """
    Calculate the RELATIVE bearing from ship1 to ship2
    Measured from ship1's heading (vessel's bow) clockwise from 0 to 360 degrees
    """
    # True bearing to ship2 (from North)
    dx = ship2.x - ship1.x
    dy = ship2.y - ship1.y
    true_bearing_rad = np.arctan2(dx, dy)
    true_bearing_deg = np.degrees(true_bearing_rad)
    if true_bearing_deg < 0:
        true_bearing_deg += 360
    
    # ship1 course in degrees (0-360)
    ship1_course_deg = np.degrees(ship1.psi)
    if ship1_course_deg < 0:
        ship1_course_deg += 360
    
    # Relative bearing = true bearing - vessel course
    relative_bearing = true_bearing_deg - ship1_course_deg
    
    # Normalize to 0-360
    if relative_bearing < 0:
        relative_bearing += 360
    elif relative_bearing >= 360:
        relative_bearing -= 360
    
    return relative_bearing


def check_rule_14(ship1, ship2, settings=None):
    """
    Rule 14 - Head-on situation
    Uses a customizable bearing threshold
    The relative bearing from Vessel 1 to Vessel 2 is within the range of 350 to 10 degrees (passing through 0).
    AND
    The relative bearing from Vessel 2 to Vessel 1 is within the range of 350 to 10 degrees (passing through 0/360).
    AND
    The distance between the vessels is less than 12 miles.
    AND     
    CPA < 2 nm.
    AND
    TCPA < 30 min.
    """
    if settings is None:
        settings = get_rules_settings()
    

    ### Fetch  parameter keys matching rules_settings
    bound_low = settings.get("rule_14_head_on", "bearing_bound_low_deg", 350.0)
    bound_high = settings.get("rule_14_head_on", "bearing_bound_high_deg", 10.0)
    max_dist = settings.get("rule_14_head_on", "max_distance_m", 22224.0)
    max_cpa = settings.get("rule_14_head_on", "max_cpa_m", 3704.0)
    max_tcpa = settings.get("rule_14_head_on", "max_tcpa_s", 1800.0)

    ### Calculate standard physical distance
    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist >= max_dist:
        return False, None, None
    

    ### Analyzer and calculate cpa_data to prevent NameError crash
    from collision_analyzer import CollisionAnalyzer
    analyzer = CollisionAnalyzer()
    cpa_data = analyzer.calculate_cpa_tcpa(ship1, ship2)


    ### Enforce mathematical CPA and TCPA limit blocks
    if cpa_data['DCPA'] >= max_cpa or cpa_data['TCPA'] >= max_tcpa:
        return False, None, None

    bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
    bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)

    def is_heading_within_bounds(bearing):
        ### Verify if relative angle passes through 0/360 sector bounds
        return bearing >= bound_low or bearing <= bound_high
    
    if is_heading_within_bounds(bearing_1_to_2) and is_heading_within_bounds(bearing_2_to_1):
        return True, bearing_1_to_2, bearing_2_to_1
    
    return False, bearing_1_to_2, bearing_2_to_1
   


def check_rule_13(ship1, ship2, settings=None):
    """
    Rule 13 - Overtaking
    ######
    Case 1: 
    1.1. The relative bearing from one vessel to the other was within the range of 110 to 250 degrees.
    AND
    1.2. The relative bearing from the second vessel to the first is from 270 to 90 degrees (passing through 0/360).
    AND
    1.3. The vessels are closing in (think about how to verify this).
    AND
    1.4. TCPA < 120 min.
    AND
    1.5. CPA < 2 nm.
    AND
    1.6. The distance between the vessels is less than 6 miles.
    ######
    OR
    ######
    Case 2:
    2.1. The relative bearing from the second vessel to the first was within the range of 110 to 250 degrees.
    AND
    2.2. The relative bearing from the first vessel to the second is from 270 to 90 degrees (passing through 0/360).
    AND
    2.3. The vessels are closing in (think about how to verify this).
    AND
    2.4. TCPA < 120 min.
    AND
    2.5. CPA < 2 nm.
    AND
    2.6. The distance between the vessels is less than 6 miles.
    """
    if settings is None:
        settings = get_rules_settings()
    

    ### Extract updated exact parameter keys matching definitions
    min_overtaken = settings.get("rule_13_overtaking", "min_overtaken_bearing_deg", 110.0)
    max_overtaken = settings.get("rule_13_overtaking", "max_overtaken_bearing_deg", 250.0)
    min_overtaker = settings.get("rule_13_overtaking", "min_overtaker_bearing_deg", 270.0)
    max_overtaker = settings.get("rule_13_overtaking", "max_overtaker_bearing_deg", 90.0)
    max_dist = settings.get("rule_13_overtaking", "max_distance_m", 11112.0)
    max_cpa = settings.get("rule_13_overtaking", "max_cpa_m", 3704.0)
    max_tcpa = settings.get("rule_13_overtaking", "max_tcpa_s", 7200.0)


    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist >= max_dist:
        return False, None, None
        
    from collision_analyzer import CollisionAnalyzer
    analyzer = CollisionAnalyzer()
    cpa_data = analyzer.calculate_cpa_tcpa(ship1, ship2)
    
    if cpa_data['DCPA'] >= max_cpa or cpa_data['TCPA'] >= max_tcpa:
        return False, None, None
        
    bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
    bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)


    ### Check if vessels are actively closing in on each other using kinematic dot products
    v1_x = ship1.u * np.sin(ship1.psi)
    v1_y = ship1.u * np.cos(ship1.psi)
    v2_x = ship2.u * np.sin(ship2.psi)
    v2_y = ship2.u * np.cos(ship2.psi)
    v_rel_x = v2_x - v1_x
    v_rel_y = v2_y - v1_y
    dx = ship2.x - ship1.x
    dy = ship2.y - ship1.y
    closing_in = (v_rel_x * dx + v_rel_y * dy) < 0

    if not closing_in:
        return False, bearing_1_to_2, bearing_2_to_1

    def is_within_overtaken_cone(bearing):
        return min_overtaken <= bearing <= max_overtaken

    def is_within_overtaker_cone(bearing):
        return bearing >= min_overtaker or bearing <= max_overtaker

    ### Case 1 execution: ship1 is overtaking ship2 from behind
    if is_within_overtaken_cone(bearing_2_to_1) and is_within_overtaker_cone(bearing_1_to_2):
        return True, bearing_1_to_2, bearing_2_to_1

    ### Case 2 execution: ship2 is overtaking ship1 from behind
    if is_within_overtaken_cone(bearing_1_to_2) and is_within_overtaker_cone(bearing_2_to_1):
        return True, bearing_1_to_2, bearing_2_to_1
        
    return False, bearing_1_to_2, bearing_2_to_1  
    
  
   

def check_rule_15(ship1, ship2, settings=None):
    """
    Rule 15 - Crossing situation
    CPA < 2 nm.
    AND
    TCPA < 30 min.
    AND
    Rule 14 does not apply.
    AND
    Rule 13 does not apply.
    AND
    The distance between the vessels is less than 12 miles.
    """
    if settings is None:
        settings = get_rules_settings()
    

    max_dist = settings.get("rule_15_crossing", "max_distance_m", 22224.0)
    max_cpa = settings.get("rule_15_crossing", "max_cpa_m", 3704.0)
    max_tcpa = settings.get("rule_15_crossing", "max_tcpa_s", 1800.0)
    
    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist >= max_dist:
        return False, None, None
        
    from collision_analyzer import CollisionAnalyzer
    analyzer = CollisionAnalyzer()
    cpa_data = analyzer.calculate_cpa_tcpa(ship1, ship2)


    if cpa_data['DCPA'] >= max_cpa or cpa_data['TCPA'] >= max_tcpa:
        return False, None, None
    
    is_rule_14, _, _ = check_rule_14(ship1, ship2, settings)
    is_rule_13, _, _ = check_rule_13(ship1, ship2, settings)
    
    if not is_rule_14 and not is_rule_13:
        bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
        bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
        return True, bearing_1_to_2, bearing_2_to_1
    
    return False, None, None


def check_rule_17_2(ship1, ship2, dist_m, cpa_m, tcpa_s, settings=None):
    """
    Rule 17.2 - Critical convergence (Emergency)
    ####
    Case 1:
    .1. Rule 13 exists.
    AND
    1.2. The distance between the vessels is less than 0.5 miles.
    AND
    1.3. CPA < 0.1 nm.
    AND
    1.4. TCPA < 15 min.
    #####
    OR
    #####
    Case 2:
    2.1. The distance between the vessels is less than 1 mile.
    AND
    2.2. CPA < 0.2 nm.
    AND
    2.3. TCPA < 10 min.
    AND
    2.4. Rule 13 does not apply.
    """
    if settings is None:
        settings = get_rules_settings()
    
    ### Load  new multi-case tracking configurations from parameters handle
    c1_dist = settings.get("rule_17_2_emergency", "case_1_max_distance_m", 926.0)
    c1_cpa = settings.get("rule_17_2_emergency", "case_1_max_cpa_m", 185.2)
    c1_tcpa = settings.get("rule_17_2_emergency", "case_1_max_tcpa_s", 900.0)
    
    c2_dist = settings.get("rule_17_2_emergency", "case_2_max_distance_m", 1852.0)
    c2_cpa = settings.get("rule_17_2_emergency", "case_2_max_cpa_m", 370.4)
    c2_tcpa = settings.get("rule_17_2_emergency", "case_2_max_tcpa_s", 600.0)

    is_rule_13, _, _ = check_rule_13(ship1, ship2, settings)
    
    
    ### Evaluates Case 1 tracking conditions: Rule 13 is currently active
    if is_rule_13:
        if dist_m < c1_dist and cpa_m < c1_cpa and tcpa_s < c1_tcpa:
            return True

    ### Evaluates Case 2 tracking conditions: Rule 13 is not active
    else:
        if dist_m < c2_dist and cpa_m < c2_cpa and tcpa_s < c2_tcpa:
            return True
    
    return False


def check_normal_conditions(dist_m, cpa_m, tcpa_s, settings=None):
    """
    Check normal conditions for applying Rules 13, 14, 15
    Uses customizable thresholds
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Get thresholds from settings
    min_cpa = settings.get("general", "min_cpa_for_risk_m", 3704.0) # 2 nm * 1852m
    min_tcpa = settings.get("general", "min_tcpa_for_risk_s", 7200.0) # 120 minutes * 60s
    detection_range = settings.get("general", "detection_range_m", 22224.0)  # 12 nm * 1852m
    
    # Check if the encounter falls within the analytical thresholds
    if dist_m <= detection_range and cpa_m < min_cpa and tcpa_s < min_tcpa:
        print("Normal conditions applies")
        return True
    
    return False


def determine_colreg_situation(ship1, ship2, dist_m, cpa_m, tcpa_s):
    """
    Determine the COLREGs situation for a pair of vessels
    Uses customizable parameters from rules_settings 
    """
    # Load settings
    settings = get_rules_settings()
    
    # Bearings are ALWAYS calculated
    bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
    bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
    
    # First check if the encounter is an overtaking situation (Rule 13)
    is_rule_13, b1, b2 = check_rule_13(ship1, ship2, settings)
    
    # Check critical convergence state (Rule 17.2)
    is_emergency = check_rule_17_2(ship1, ship2, dist_m, cpa_m, tcpa_s, settings)
    
    # Rule 17.2 easement for safe overtaking operations:
    # If identified as Rule 13, and the distance has not yet breached the physical collision extreme (dist > 800m),
    # prioritize executing the safe pass instead of executing an emergency speed reduction drop via Rule 17.2.

    if is_emergency:
        return {
            'rule': '17.2',
            'situation': 'Critical convergence (Emergency)',
            'ship1_action': 'Change course/speed immediately',
            'ship2_action': 'Change course/speed immediately',
            'details': {
                'bearing_1_to_2': bearing_1_to_2,
                'bearing_2_to_1': bearing_2_to_1,
                'dist_nm': dist_m / 1852.0,
                'cpa_nm': cpa_m / 1852.0,
                'tcpa_min': tcpa_s / 60.0
            }
        }
    
    # Check Rule 13 (Overtaking)
    if is_rule_13:
        # Determine which vessel is performing the overtake
        if ship2.u > ship1.u:
            overtaking_ship = ship2.name
            ship1_action = 'Stand on (Rule 17.1)'
            ship2_action = 'Give-way (Rule 16) - Overtake Starboard'
        else:
            overtaking_ship = ship1.name
            ship1_action = 'Give-way (Rule 16) - Overtake Starboard'
            ship2_action = 'Stand on (Rule 17.1)'
        
        return {
            'rule': '13',
            'situation': 'Overtaking',
            'ship1_action': ship1_action,
            'ship2_action': ship2_action,
            'details': {
                'bearing_1_to_2': b1,
                'bearing_2_to_1': b2,
                'dist_nm': dist_m / 1852.0,
                'cpa_nm': cpa_m / 1852.0,
                'tcpa_min': tcpa_s / 60.0,
                'overtaking_ship': overtaking_ship
            }
        }

    # Check Rule 14 (Head-on)
    is_rule_14, b1, b2 = check_rule_14(ship1, ship2, settings)
    if is_rule_14:
        return {
            'rule': '14',
            'situation': 'Head-on situation',
            'ship1_action': 'Alter course to starboard',
            'ship2_action': 'Alter course to starboard',
            'details': {
                'bearing_1_to_2': b1,
                'bearing_2_to_1': b2,
                'dist_nm': dist_m / 1852.0,
                'cpa_nm': cpa_m / 1852.0,
                'tcpa_min': tcpa_s / 60.0
            }
        }

    # Check Rule 15 (Crossing)
    is_rule_15, b1, b2 = check_rule_15(ship1, ship2, settings)
    if is_rule_15:
        def is_stand_on(bearing):
            # Vessel stands on if the other vessel is on its starboard side (10 to 110 degrees)
            return 10 <= bearing <= 110
        
        ship1_stand_on = is_stand_on(bearing_2_to_1)
        
        if ship1_stand_on:
            ship1_action = 'Stand on (Rule 17.1)'
            ship2_action = 'Give-way (Rule 16)'
        else:
            ship1_action = 'Give-way (Rule 16)'
            ship2_action = 'Stand on (Rule 17.1)'
        
        return {
            'rule': '15',
            'situation': 'Crossing situation',
            'ship1_action': ship1_action,
            'ship2_action': ship2_action,
            'details': {
                'bearing_1_to_2': b1,
                'bearing_2_to_1': b2,
                'dist_nm': dist_m / 1852.0,
                'cpa_nm': cpa_m / 1852.0,
                'tcpa_min': tcpa_s / 60.0
            }
        }

    # Check normal risk evaluation thresholds conditions
    if not check_normal_conditions(dist_m, cpa_m, tcpa_s, settings):
        return {
            'rule': 'None',
            'situation': 'Safe situation',
            'ship1_action': 'Stand on',
            'ship2_action': 'Stand on',
            'details': {
                'bearing_1_to_2': bearing_1_to_2,
                'bearing_2_to_1': bearing_2_to_1,
            }
        }

    return {
        'rule': 'Unknown',
        'situation': 'Uncertain situation',
        'ship1_action': 'Stand on',
        'ship2_action': 'Stand on',
        'details': {
            'bearing_1_to_2': bearing_1_to_2,
            'bearing_2_to_1': bearing_2_to_1
        }
    }