"""
colreg_rules.py
Определение правил МППСС на основе относительных пеленгов
С интегрированными настраиваемыми параметрами
"""
import numpy as np
from rules_settings import get_rules_settings


def calculate_relative_bearing(ship1, ship2):
    """
    Рассчитать ОТНОСИТЕЛЬНЫЙ пеленг с ship1 на ship2
    Отсчитывается от курса ship1 (носа судна) по часовой стрелке 0-360°
    """
    # Истинный пеленг на ship2 (от севера)
    dx = ship2.x - ship1.x
    dy = ship2.y - ship1.y
    true_bearing_rad = np.arctan2(dx, dy)
    true_bearing_deg = np.degrees(true_bearing_rad)
    if true_bearing_deg < 0:
        true_bearing_deg += 360
    
    # Курс ship1 в градусах (0-360)
    ship1_course_deg = np.degrees(ship1.psi)
    if ship1_course_deg < 0:
        ship1_course_deg += 360
    
    # Относительный пеленг = истинный пеленг - курс судна
    relative_bearing = true_bearing_deg - ship1_course_deg
    
    # Нормализовать к 0-360
    if relative_bearing < 0:
        relative_bearing += 360
    elif relative_bearing >= 360:
        relative_bearing -= 360
    
    return relative_bearing


def check_rule_14(ship1, ship2, settings=None):
    """
    Правило 14 - Встречная ситуация
    Использует настраиваемый порог пеленга
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Получаем порог из настроек (в градусах)
    bearing_threshold = settings.get("rule_14_head_on", "bearing_threshold_deg", 5.0)
    max_distance = settings.get("rule_14_head_on", "max_distance_m", 5556)
    
    # Проверяем дистанцию
    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist > max_distance:
        return False, None, None
    
    bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
    bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
    
    def is_in_head_on_range(bearing):
        # Проверяем, находится ли пеленг в диапазоне ±threshold от 0° (или 360°)
        return bearing <= bearing_threshold or bearing >= (360 - bearing_threshold)
    
    if is_in_head_on_range(bearing_1_to_2) and is_in_head_on_range(bearing_2_to_1):
        return True, bearing_1_to_2, bearing_2_to_1
    
    return False, bearing_1_to_2, bearing_2_to_1


def check_rule_13(ship1, ship2, settings=None):
    """
    Правило 13 - Обгон
    Сектор обгона: от (180° - threshold) до (180° + threshold)
    По умолчанию: от 112.5° до 247.5° (22.5° позади траверза)
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Получаем параметры из настроек
    # bearing_threshold - это угол ОТ НОСА, за которым начинается сектор
    # По умолчанию 112.5° (т.е. 22.5° позади траверза)
    bearing_threshold = settings.get("rule_13_overtaking", "bearing_threshold_deg", 112.5)
    max_distance = settings.get("rule_13_overtaking", "max_distance_m", 5556)
    speed_ratio = settings.get("rule_13_overtaking", "speed_ratio_threshold", 1.0)
    
    # Проверяем дистанцию
    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist > max_distance:
        return False, None, None
    
    bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
    bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
    
    # Проверяем соотношение скоростей
    if ship1.u > 0.1 and ship2.u > 0.1:
        speed_ratio_actual = max(ship1.u, ship2.u) / min(ship1.u, ship2.u)
        if speed_ratio_actual < speed_ratio:
            return False, None, None
    
    # ПРАВИЛЬНАЯ проверка сектора обгона (симметричного относительно кормы)
    # Сектор: от bearing_threshold до (360° - bearing_threshold)
    # Для threshold=112.5°: сектор 112.5° - 247.5°
    def is_in_overtaking_sector(bearing):
        return bearing_threshold <= bearing <= (360 - bearing_threshold)
    
    # Проверяем, сближаются ли суда
    v1_x = ship1.u * np.sin(ship1.psi)
    v1_y = ship1.u * np.cos(ship1.psi)
    v2_x = ship2.u * np.sin(ship2.psi)
    v2_y = ship2.u * np.cos(ship2.psi)
    
    v_rel_x = v2_x - v1_x
    v_rel_y = v2_y - v1_y
    
    dx = ship2.x - ship1.x
    dy = ship2.y - ship1.y
    
    approaching = (v_rel_x * dx + v_rel_y * dy) < 0
    
    # Для Rule 13: ship2 должен быть в секторе обгона ship1
    # (т.е. ship2 находится позади траверза ship1)
    if is_in_overtaking_sector(bearing_1_to_2) and approaching:
        return True, bearing_1_to_2, bearing_2_to_1
    
    return False, bearing_1_to_2, bearing_2_to_1


def check_rule_15(ship1, ship2, settings=None):
    """
    Правило 15 - Пересечение курсов
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Проверяем, не является ли ситуация Rule 14 или Rule 13
    is_rule_14, _, _ = check_rule_14(ship1, ship2, settings)
    is_rule_13, _, _ = check_rule_13(ship1, ship2, settings)
    
    max_distance = settings.get("rule_15_crossing", "max_distance_m", 5556)
    
    # Проверяем дистанцию
    dist = np.sqrt((ship2.x - ship1.x)**2 + (ship2.y - ship1.y)**2)
    if dist > max_distance:
        return False, None, None
    
    if not is_rule_14 and not is_rule_13:
        bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
        bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
        return True, bearing_1_to_2, bearing_2_to_1
    
    return False, None, None


def check_rule_17_2(dist_m, cpa_m, tcpa_s, settings=None):
    """
    Правило 17.2 - Критическое сближение
    Использует настраиваемые критические значения
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Получаем критические значения из настроек
    critical_cpa = settings.get("rule_17_2_emergency", "critical_cpa_m", 926)
    critical_tcpa = settings.get("rule_17_2_emergency", "critical_tcpa_s", 300)
    critical_distance = settings.get("rule_17_2_emergency", "critical_distance_m", 1852)
    
    # Проверяем, превышены ли критические пороги
    if dist_m < critical_distance or cpa_m < critical_cpa or tcpa_s < critical_tcpa:
        return True
    
    return False


def check_normal_conditions(dist_m, cpa_m, tcpa_s, settings=None):
    """
    Проверка нормальных условий для применения правил 13, 14, 15
    Использует настраиваемые пороги
    """
    if settings is None:
        settings = get_rules_settings()
    
    # Получаем пороги из настроек
    min_cpa = settings.get("general", "min_cpa_for_risk_m", 1852)
    min_tcpa = settings.get("general", "min_tcpa_for_risk_s", 600)
    detection_range = settings.get("general", "detection_range_m", 9260)
    
    # Проверяем, находится ли ситуация в пределах анализа
    if dist_m <= detection_range and cpa_m < min_cpa and tcpa_s < min_tcpa:
        return True
    
    return False


def determine_colreg_situation(ship1, ship2, dist_m, cpa_m, tcpa_s):
    """
    Определить ситуацию МППСС для пары судов
    Использует настраиваемые параметры из rules_settings
    """
    # Получаем настройки
    settings = get_rules_settings()
    
    # Пеленги вычисляются ВСЕГДА
    bearing_1_to_2 = calculate_relative_bearing(ship1, ship2)
    bearing_2_to_1 = calculate_relative_bearing(ship2, ship1)
    
    # Проверка критического сближения (правило 17.2)
    if check_rule_17_2(dist_m, cpa_m, tcpa_s, settings):
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
    
    # Проверка нормальных условий
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
    
    # Проверка правила 14 (встречная)
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
    
    # Проверка правила 13 (обгон)
    is_rule_13, b1, b2 = check_rule_13(ship1, ship2, settings)
    if is_rule_13:
        # Определяем, какое судно обгоняет
        if ship2.u > ship1.u:
            overtaking_ship = ship2.name
            ship1_action = 'Stand on (Rule 17.1)'
            ship2_action = 'Give-way (Rule 16)'
        else:
            overtaking_ship = ship1.name
            ship1_action = 'Give-way (Rule 16)'
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
    
    # Проверка правила 15 (пересечение)
    is_rule_15, b1, b2 = check_rule_15(ship1, ship2, settings)
    if is_rule_15:
        def is_stand_on(bearing):
            # Судно сохраняет курс, если другое судно у него по правому борту (10°-110°)
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