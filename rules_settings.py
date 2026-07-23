"""
rules_settings.py
Storage and management of COLREGs parameter configurations mapped to operational rules.
"""
import json
import os

### Convert exact nautical thresholds to metric parameters (1 nm = 1852m)
DEFAULT_SETTINGS = {
    "rule_13_overtaking": {
        "min_overtaken_bearing_deg": 110.0,
        "max_overtaken_bearing_deg": 250.0,
        "min_overtaker_bearing_deg": 270.0,
        "max_overtaker_bearing_deg": 90.0,
        "bearing_threshold_deg": 120.0,
        "speed_ratio_threshold": 1.0,
        "max_distance_m": 11112.0,            # 6 nm * 1852m
        "max_cpa_m": 3704.0,                  # 2 nm * 1852m
        "max_tcpa_s": 2700.0,                 # 60 minutes * 60s
        "description": "Rule 13: Cone between 110-250 and 270-90, dist < 6nm, CPA < 2nm, TCPA < 120min"
    },
    "rule_14_head_on": {
        "bearing_bound_low_deg": 350.0,
        "bearing_bound_high_deg": 10.0,
        "max_distance_m": 22224.0,            # 12 nm * 1852m
        "max_cpa_m": 3704.0,                  # 2 nm * 1852m
        "max_tcpa_s": 2700.0,                 # 60 minutes * 60s
        "speed_ratio_threshold": 1.0,
        "description": "Rule 14: Bow approach aspect +/-10 deg, dist < 12nm, CPA < 2nm, TCPA < 30min"
    },
    "rule_15_crossing": {
        "max_distance_m": 22224.0,            # 12 nm * 1852m
        "max_cpa_m": 3704.0,                  # 2 nm * 1852m
        "max_tcpa_s": 2700.0,                 # 60 minutes * 60s
        "description": "Rule 15: Trajectory risk crossing when Rule 13 and 14 do not apply, dist < 12nm"
    },
    "rule_17_2_emergency": {
        "case_1_max_distance_m": 926.0,       # 0.5 nm * 1852m
        "case_1_max_cpa_m": 185.2,            # 0.1 nm * 1852m
        "case_1_max_tcpa_s": 900.0,           # 15 minutes * 60s
        "case_2_max_distance_m": 1852.0,      # 1.0 nm * 1852m
        "case_2_max_cpa_m": 370.4,            # 0.2 nm * 1852m
        "case_2_max_tcpa_s": 600.0,           # 10 minutes * 60s
        "description": "Rule 17.2: Case 1 (Overtaking subset) or Case 2 (Critical convergence), dist < 0.5nm or CPA < 0.1nm or TCPA < 15min, OR dist < 1nm or CPA < 0.2nm or TCPA < 10min"
    }
}



SETTINGS_FILE = os.path.join(os.getcwd(), "rules_settings.json")


class RulesSettings:
    """Class to load, save, and fetch strict mathematical limits for COLREGs filters."""
    
    def __init__(self):
        self.settings = self._load_settings()
    
    def _load_settings(self):
        """Load configured settings data from disk json file structure or fallback to custom criteria defaults."""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Warning] Failed to read rules configuration parameters: {e}")
        return DEFAULT_SETTINGS.copy()
    
    def save(self):
        """Serialize current parameter definitions into standard configuration file structure."""
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[Error] Failed to execute disk write operation for settings data: {e}")
            return False
    
    def get(self, section, key, default=None):
        """Safely fetch numeric limit variables from mapped sections."""
        try:
            return self.settings[section][key]
        except (KeyError, TypeError):
            return default
    
    def set(self, section, key, value):
        """Update runtime data configuration keys."""
        if section not in self.settings:
            self.settings[section] = {}
        self.settings[section][key] = value
    
    def reset_to_defaults(self):
        """Overwrite current structural files back to default programmatic settings definitions."""
        self.settings = DEFAULT_SETTINGS.copy()
        self.save()
    
    def get_all(self):
        """Return shallow copy of target parameters memory dictionary."""
        return self.settings.copy()


### Shared global memory tracking handle reference
_rules_settings = None

def get_rules_settings():
    """Retrieve runtime static handle memory tracking reference."""
    global _rules_settings
    if _rules_settings is None:
        _rules_settings = RulesSettings()
    return _rules_settings