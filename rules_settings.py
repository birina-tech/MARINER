"""
rules_settings.py
Хранение и загрузка настроек параметров МППСС
"""
import json
import os

DEFAULT_SETTINGS = {
    "rule_13_overtaking": {
        "bearing_threshold_deg": 112.5,
        "max_distance_m": 5556,
        "speed_ratio_threshold": 1.0,
        "description": "Bearing > 112.5\u00b0 (22.5\u00b0 abaft beam)"
    },
    "rule_14_head_on": {
        "bearing_threshold_deg": 5.0,
        "max_distance_m": 5556,
        "description": "Bearing within ±5\u00b0 of head-on"
    },
    "rule_15_crossing": {
        "max_distance_m": 5556,
        "description": "Bearing between head-on and beam"
    },
    "rule_17_2_emergency": {
        "critical_cpa_m": 926,
        "critical_tcpa_s": 300,
        "critical_distance_m": 1852,
        "description": "CPA < 0.5nm OR TCPA < 5min OR dist < 1nm"
    },
    "general": {
        "min_cpa_for_risk_m": 1852,
        "min_tcpa_for_risk_s": 600,
        "detection_range_m": 9260,
        "description": "General risk thresholds"
    }
}

SETTINGS_FILE = os.path.join(os.getcwd(), "rules_settings.json")


class RulesSettings:
    """Класс для работы с настройками правил МППСС"""
    
    def __init__(self):
        self.settings = self._load_settings()
    
    def _load_settings(self):
        """Загрузить настройки из файла или использовать значения по умолчанию"""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Failed to load settings: {e}")
        return DEFAULT_SETTINGS.copy()
    
    def save(self):
        """Сохранить настройки в файл"""
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Failed to save settings: {e}")
            return False
    
    def get(self, section, key, default=None):
        """Получить значение параметра"""
        try:
            return self.settings[section][key]
        except (KeyError, TypeError):
            return default
    
    def set(self, section, key, value):
        """Установить значение параметра"""
        if section not in self.settings:
            self.settings[section] = {}
        self.settings[section][key] = value
    
    def reset_to_defaults(self):
        """Сбросить настройки к значениям по умолчанию"""
        self.settings = DEFAULT_SETTINGS.copy()
        self.save()
    
    def get_all(self):
        """Получить все настройки"""
        return self.settings.copy()


# Глобальный экземпляр для использования во всём приложении
_rules_settings = None

def get_rules_settings():
    """Получить глобальный экземпляр настроек"""
    global _rules_settings
    if _rules_settings is None:
        _rules_settings = RulesSettings()
    return _rules_settings