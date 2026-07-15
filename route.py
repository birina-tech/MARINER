"""
route.py
Классы для работы с маршрутами
"""
import numpy as np


class RoutePoint:
    """Точка маршрута"""
    
    def __init__(self, x, y, point_number):
        self.x = x
        self.y = y
        self.point_number = point_number
        self.distance_to_next = 0.0  # расстояние до следующей точки
        self.course_to_next = 0.0    # курс до следующей точки
    
    def calculate_to_next(self, next_point):
        """Рассчитать расстояние и курс до следующей точки"""
        dx = next_point.x - self.x
        dy = next_point.y - self.y
        
        # Расстояние
        self.distance_to_next = np.sqrt(dx**2 + dy**2)
        
        # Курс (от севера, по часовой стрелке)
        course_rad = np.arctan2(dx, dy)
        self.course_to_next = np.degrees(course_rad)
        if self.course_to_next < 0:
            self.course_to_next += 360


class Route:
    """Маршрут движения"""
    
    _counter = 0
    
    def __init__(self):
        Route._counter += 1
        self.name = f"Route_{Route._counter}"
        self.points = []
        self.assigned_ship = None
    
    def add_point(self, x, y):
        """Добавить точку в маршрут"""
        point = RoutePoint(x, y, len(self.points) + 1)
        self.points.append(point)
        self._recalculate()
        return point
    
    def _recalculate(self):
        """Пересчитать расстояния и курсы между точками"""
        for i in range(len(self.points) - 1):
            self.points[i].calculate_to_next(self.points[i + 1])
        
        if self.points:
            self.points[-1].distance_to_next = 0.0
            self.points[-1].course_to_next = 0.0
    
    def remove_point(self, index):
        """Удалить точку по индексу"""
        if 0 <= index < len(self.points):
            self.points.pop(index)
            for i, point in enumerate(self.points):
                point.point_number = i + 1
            self._recalculate()
    
    def remove_last_point(self):
        """Удалить последнюю точку маршрута"""
        if self.points:
            self.remove_point(len(self.points) - 1)
    
    def get_total_distance(self):
        """Получить общее расстояние маршрута"""
        return sum(p.distance_to_next for p in self.points[:-1])
    
    def get_coordinates_list(self):
        """Получить список координат для отрисовки"""
        return [(p.x, p.y) for p in self.points]