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
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Get threshold from settings (in degrees)
    bearing_threshold = settings.get("rule_14_head_on", "bearing_threshold_deg", 5.0)
    max_distance = settings.get("rule_14_head_on", "max_distance_m", 5556)
    
    # Check distance
    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist > max_distance:
        return False, None, None
    
    bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
    bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
    
    def is_in_head_on_range(bearing):
        # Check if bearing is within ±threshold from 0 (or 360)
        return bearing <= bearing_threshold or bearing >= (360 - bearing_threshold)
    
    if is_in_head_on_range(bearing_1_to_2) and is_in_head_on_range(bearing_2_to_1):
        return True, bearing_1_to_2, bearing_2_to_1
    
    return False, bearing_1_to_2, bearing_2_to_1


def check_rule_13(ship1, ship2, settings=None):
    """
    Rule 13 - Overtaking
    Overtaking sector: from 112.5 to 247.5 degrees abaft the beam of the target vessel
    """
    if settings is None:
        settings = get_rules_settings()
    
    max_distance = settings.get("rule_13_overtaking", "max_distance_m", 5556)
    bearing_threshold = settings.get("rule_13_overtaking", "bearing_threshold_deg", 112.5)
    
    # 1. Verify distance limit
    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist > max_distance:
        return False, None, None
    
    bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
    bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
    
    def is_in_overtaking_sector(bearing):
        return bearing_threshold <= bearing <= (360 - bearing_threshold)
    
    # 2. Geometry Dominance: Check if ship1 is physically coming from behind ship2
    # (Meaning ship1 sees ship2 ahead/traversable, and ship2 sees ship1 abaft its beam)
    if is_in_overtaking_sector(bearing_2_to_1):
        print(f"Rule 13 Triggered: {ship1.name} is overtaking {ship2.name} from astern.")
        return True, bearing_1_to_2, bearing_2_to_1
        
    return False, bearing_1_to_2, bearing_2_to_1
    
    

def check_rule_15(ship1, ship2, settings=None):
    """
    Rule 15 - Crossing situation
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Check if the situation is already defined by Rule 14 or Rule 13
    is_rule_14, _, _ = check_rule_14(ship1, ship2, settings)
    is_rule_13, _, _ = check_rule_13(ship1, ship2, settings)
    
    max_distance = settings.get("rule_15_crossing", "max_distance_m", 5556)
    
    # Check distance
    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist > max_distance:
        return False, None, None
    
    if not is_rule_14 and not is_rule_13:
        bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
        bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
        return True, bearing_1_to_2, bearing_2_to_1
    
    return False, None, None


def check_rule_17_2(ship1, ship2, dist_m, cpa_m, tcpa_s, settings=None):
    """
    Rule 17.2 - Critical convergence (Emergency)
    Uses customizable critical thresholds
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Get critical values from settings
    critical_cpa = settings.get("rule_17_2_emergency", "critical_cpa_m", 926)
    critical_tcpa = settings.get("rule_17_2_emergency", "critical_tcpa_s", 300)
    critical_distance = settings.get("rule_17_2_emergency", "critical_distance_m", 1852)

    # Check if the situation is already defined by Rule 13
    is_rule_13, _, _ = check_rule_13(ship1, ship2, settings)

    # Check if critical thresholds are breached
    if dist_m < critical_distance and cpa_m < critical_cpa and tcpa_s < critical_tcpa:
        if is_rule_13 and dist_m > 800.0:
            # Rule 17.2 easement for safe overtaking operations:
            # If identified as Rule 13, and the distance has not yet breached the physical collision extreme (dist > 800m),
            # prioritize executing the safe pass instead of executing an emergency speed reduction drop via Rule 17.2.
            return False
        else:
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
    min_cpa = settings.get("general", "min_cpa_for_risk_m", 1852)
    min_tcpa = settings.get("general", "min_tcpa_for_risk_s", 600)
    detection_range = settings.get("general", "detection_range_m", 9260)
    
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

    if is_emergency and not (is_rule_13 and dist_m > 800.0):
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