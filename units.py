"""
units.py
Функции конвертации единиц измерения
"""

# Константы
METERS_PER_NAUTICAL_MILE = 1852.0
KNOTS_TO_MS = 0.514444  # 1 узел = 0.514444 м/с

def meters_to_miles(meters):
    """Метры в морские мили"""
    return meters / METERS_PER_NAUTICAL_MILE

def miles_to_meters(miles):
    """Морские мили в метры"""
    return miles * METERS_PER_NAUTICAL_MILE

def ms_to_knots(ms):
    """м/с в узлы"""
    return ms / KNOTS_TO_MS

def knots_to_ms(knots):
    """Узлы в м/с"""
    return knots * KNOTS_TO_MS

def format_distance(value_meters, use_miles=True):
    """Форматирование расстояния"""
    if use_miles:
        return f"{meters_to_miles(value_meters):.2f} nm"
    else:
        return f"{value_meters:.0f} m"

def format_speed(value_ms, use_knots=True):
    """Форматирование скорости"""
    if use_knots:
        return f"{ms_to_knots(value_ms):.1f} kn"
    else:
        return f"{value_ms:.1f} m/s"

def format_scale(value_meters, use_miles=True):
    """Форматирование шкалы"""
    if use_miles:
        miles = meters_to_miles(value_meters)
        if miles >= 1:
            return f"{miles:.1f} nm"
        else:
            return f"{meters_to_miles(value_meters) * 1000:.0f} m"
    else:
        if value_meters >= 1000:
            return f"{value_meters / 1000:.1f} km"
        else:
            return f"{value_meters:.0f} m"