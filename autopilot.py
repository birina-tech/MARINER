"""
autopilot.py
Каскадный ПИД-регулятор для следования по маршруту.

Структура управления (сверху вниз):
  1. Дистанция до траектории (cross-track error) → поправка к курсу
  2. Ошибка курса → желаемая угловая скорость (yaw rate)
  3. Ошибка угловой скорости → перекладка руля

Режимы работы:
  - MODE_ROUTE: следование по маршруту (выход на траекторию + проход по точкам)
  - MODE_HOLD_COURSE: удержание заданного курса (команда от LLM)
"""
import numpy as np


class PIDController:
    """
    ПИД-регулятор с ограничением выхода и anti-windup.
    """

    def __init__(self, kp, ki, kd, output_min, output_max):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_min = output_min
        self.output_max = output_max
        self.integral = 0.0
        self.prev_error = 0.0
        self.first_run = True

    def reset(self):
        """Сброс интегратора и предыдущей ошибки."""
        self.integral = 0.0
        self.prev_error = 0.0
        self.first_run = True

    def update(self, error, dt):
        """
        Рассчитать выход ПИД-регулятора.

        Args:
            error: текущая ошибка
            dt: шаг времени (секунды)

        Returns:
            ограниченное значение управления
        """
        if dt <= 0:
            return 0.0

        if self.first_run:
            self.prev_error = error
            self.first_run = False

        # Пропорциональная составляющая
        p_term = self.kp * error

        # Интегральная составляющая с anti-windup
        self.integral += error * dt
        if self.ki != 0:
            max_integral = (self.output_max - p_term) / self.ki
            min_integral = (self.output_min - p_term) / self.ki
            self.integral = np.clip(self.integral, min_integral, max_integral)
        i_term = self.ki * self.integral

        # Дифференциальная составляющая
        derivative = (error - self.prev_error) / dt
        d_term = self.kd * derivative

        self.prev_error = error

        output = p_term + i_term + d_term
        return np.clip(output, self.output_min, self.output_max)


class RouteAutopilot:
    """
    Авторулевой для следования по маршруту.

    Поддерживает два режима:
    - MODE_ROUTE: судно следует по точкам маршрута, плавно выходит на траекторию
    - MODE_HOLD_COURSE: судно удерживает курс, заданный LLM

    Переключение между режимами:
    - set_hold_course(course_deg) — перейти в режим удержания курса
    - resume_route() — вернуться к следованию по маршруту
    """

    # Режимы работы
    MODE_ROUTE = 0        # Следование по маршруту
    MODE_HOLD_COURSE = 1  # Удержание курса от LLM

    def __init__(self, ship, route):
        """
        Инициализация авторулевого.

        Args:
            ship: объект Ship
            route: объект Route
        """
        self.ship = ship
        self.route = route

        # Длина судна (для расчёта точки начала поворота)
        self.ship_length = getattr(ship, 'length', 100.0)
        self.turn_radius_distance = 2.0 * self.ship_length

        # Текущий режим
        self.mode = self.MODE_ROUTE
        self.hold_course_rad = None

        # Индекс текущего сегмента маршрута
        self.current_segment_index = 0

        # === НАСТРОЙКИ КАСКАДНЫХ ПИД-РЕГУЛЯТОРОВ ===

        # Уровень 1: Дистанция до траектории → поправка к курсу (рад)
        # kp=0.02: при ошибке 100 м поправка ~2 рад (ограничено ±60°)
        self.pid_distance = PIDController(
            kp=0.02, ki=0.0005, kd=0.01,
            output_min=-np.pi / 3, output_max=np.pi / 3
        )

        # Уровень 2: Ошибка курса → желаемая угловая скорость (рад/с)
        # kp=0.8: при ошибке 1 рад (~57°) желаемая скорость поворота ~0.8 рад/с
        self.pid_course = PIDController(
            kp=0.8, ki=0.05, kd=0.4,
            output_min=-0.3, output_max=0.3
        )

        # Уровень 3: Ошибка угловой скорости → перекладка руля (градусы)
        # kp=15: для создания скорости 0.1 рад/с нужен руль ~1.5°
        self.pid_rate = PIDController(
            kp=15.0, ki=1.0, kd=3.0,
            output_min=-35.0, output_max=35.0
        )

    # ========== УПРАВЛЕНИЕ РЕЖИМАМИ ==========

    def set_hold_course(self, course_deg):
        """
        Переключиться в режим удержания курса (команда от LLM).
        Авторулевой будет удерживать заданный курс через каскад ПИД.

        Args:
            course_deg: желаемый курс в градусах (0-360)
        """
        self.mode = self.MODE_HOLD_COURSE
        self.hold_course_rad = np.deg2rad(course_deg)
        # Сброс интеграторов для плавного перехода
        self.pid_course.reset()
        self.pid_rate.reset()
        print(f"[Autopilot] {self.ship.name}: HOLD COURSE {course_deg:.1f}°")

    def resume_route(self):
        """
        Вернуться к следованию по маршруту (команда от LLM).
        Сбрасывает режим удержания курса и возобновляет навигацию по точкам.
        """
        if self.mode == self.MODE_ROUTE:
            return
        self.mode = self.MODE_ROUTE
        self.hold_course_rad = None
        # Сброс интеграторов для плавного перехода
        self.pid_distance.reset()
        self.pid_course.reset()
        self.pid_rate.reset()
        print(f"[Autopilot] {self.ship.name}: RESUME ROUTE")

    # ========== ГЕОМЕТРИЯ МАРШРУТА ==========

    def find_closest_segment(self, ship_pos):
        """
        Найти ближайший сегмент маршрута к судну.

        Используется для выхода на траекторию, если судно находится
        в стороне от маршрута.

        Args:
            ship_pos: numpy array [x, y] — позиция судна

        Returns:
            (segment_index, min_distance, closest_point)
        """
        min_dist = float('inf')
        best_seg_idx = 0
        best_closest_point = None

        for i in range(len(self.route.points) - 1):
            p1 = np.array([self.route.points[i].x, self.route.points[i].y])
            p2 = np.array([self.route.points[i + 1].x, self.route.points[i + 1].y])

            v_seg = p2 - p1
            v_ship = ship_pos - p1

            seg_len_sq = np.dot(v_seg, v_seg)
            if seg_len_sq == 0:
                continue

            # Проекция судна на линию сегмента
            t = np.dot(v_ship, v_seg) / seg_len_sq
            t = np.clip(t, 0.0, 1.0)

            closest_point = p1 + t * v_seg
            dist = np.linalg.norm(ship_pos - closest_point)

            if dist < min_dist:
                min_dist = dist
                best_seg_idx = i
                best_closest_point = closest_point

        return best_seg_idx, min_dist, best_closest_point

    def _check_waypoint_switch(self, ship_pos, seg_idx, p1, p2):
        """
        Проверить условие перехода к следующей точке маршрута.

        Поворот начинается на дистанции, равной удвоенной длине судна.

        Returns:
            (new_seg_idx, new_p1, new_p2, switched)
        """
        dist_to_next_wp = np.linalg.norm(ship_pos - p2)

        if dist_to_next_wp < self.turn_radius_distance:
            if seg_idx < len(self.route.points) - 2:
                new_idx = seg_idx + 1
                new_p1 = np.array([
                    self.route.points[new_idx].x,
                    self.route.points[new_idx].y
                ])
                new_p2 = np.array([
                    self.route.points[new_idx + 1].x,
                    self.route.points[new_idx + 1].y
                ])
                # Сброс интегратора дистанции при смене сегмента
                self.pid_distance.reset()
                return new_idx, new_p1, new_p2, True
            else:
                # Конец маршрута
                return seg_idx, p1, p2, False
        return seg_idx, p1, p2, False

    # ========== ШАГ АВТОРУЛЕВОГО ==========

    def update(self, dt):
        """
        Шаг работы авторулевого.

        Args:
            dt: шаг времени (секунды)
        """
        if not self.route or len(self.route.points) < 2:
            self.ship.rudder_cmd = 0
            return

        # === РЕЖИМ УДЕРЖАНИЯ КУРСА (команда от LLM) ===
        if self.mode == self.MODE_HOLD_COURSE:
            if self.hold_course_rad is None:
                self.ship.rudder_cmd = 0
                return

            # Уровень 2: ошибка курса → желаемая угловая скорость
            current_heading = self.ship.psi
            heading_error = self.hold_course_rad - current_heading
            heading_error = np.arctan2(
                np.sin(heading_error), np.cos(heading_error)
            )

            desired_yaw_rate = self.pid_course.update(heading_error, dt)

            # Уровень 3: ошибка угловой скорости → руль
            current_yaw_rate = getattr(self.ship, 'r', 0.0)
            rate_error = desired_yaw_rate - current_yaw_rate
            rudder_cmd = self.pid_rate.update(rate_error, dt)

            self.ship.rudder_cmd = rudder_cmd
            return

        # === РЕЖИМ СЛЕДОВАНИЯ ПО МАРШРУТУ ===
        ship_pos = np.array([self.ship.x, self.ship.y])

        # Найти ближайший сегмент (для выхода на траекторию)
        seg_idx, dist_to_route, closest_point = self.find_closest_segment(ship_pos)
        self.current_segment_index = seg_idx

        p1 = np.array([self.route.points[seg_idx].x, self.route.points[seg_idx].y])
        p2 = np.array([self.route.points[seg_idx + 1].x, self.route.points[seg_idx + 1].y])

        # Проверить переход к следующей точке
        seg_idx, p1, p2, switched = self._check_waypoint_switch(
            ship_pos, seg_idx, p1, p2
        )

        if switched:
            # Если только что переключились — пересчитать ближайшую точку
            # для нового сегмента
            v_seg = p2 - p1
            v_ship = ship_pos - p1
            seg_len_sq = np.dot(v_seg, v_seg)
            if seg_len_sq > 0:
                t = np.dot(v_ship, v_seg) / seg_len_sq
                t = np.clip(t, 0.0, 1.0)
                closest_point = p1 + t * v_seg

        # Проверить конец маршрута
        if seg_idx >= len(self.route.points) - 2:
            dist_to_last = np.linalg.norm(ship_pos - p2)
            if dist_to_last < self.turn_radius_distance:
                # Достигли конца маршрута — удержание последнего курса
                self.pid_distance.reset()
                self.pid_course.reset()
                self.pid_rate.reset()
                self.ship.rudder_cmd = 0
                return

        # Вектор сегмента и его длина
        v_seg = p2 - p1
        seg_length = np.linalg.norm(v_seg)
        if seg_length < 0.1:
            return

        # Единичный вектор направления сегмента
        v_seg_norm = v_seg / seg_length

        # Базовый курс сегмента (угол от севера по часовой стрелке)
        course_segment = np.arctan2(v_seg_norm[0], v_seg_norm[1])

        # === УРОВЕНЬ 1: Дистанция → Курс ===
        # Вектор от ближайшей точки на сегменте к судну
        v_error = ship_pos - closest_point
        cross_track_dist = np.linalg.norm(v_error)

        # Знак ошибки (слева или справа от траектории)
        # 2D векторное произведение: cross = v_seg_x * v_error_y - v_seg_y * v_error_x
        cross = v_seg_norm[0] * v_error[1] - v_seg_norm[1] * v_error[0]

        # error_dist со знаком: положительный — судно справа от курса
        # (в системе, где psi растёт по часовой от севера)
        error_dist = cross * cross_track_dist

        course_correction = self.pid_distance.update(error_dist, dt)
        desired_course = course_segment + course_correction
        desired_course = np.arctan2(
            np.sin(desired_course), np.cos(desired_course)
        )

        # === УРОВЕНЬ 2: Курс → Угловая скорость ===
        current_heading = self.ship.psi
        heading_error = desired_course - current_heading
        heading_error = np.arctan2(
            np.sin(heading_error), np.cos(heading_error)
        )

        desired_yaw_rate = self.pid_course.update(heading_error, dt)

        # === УРОВЕНЬ 3: Угловая скорость → Руль ===
        current_yaw_rate = getattr(self.ship, 'r', 0.0)
        rate_error = desired_yaw_rate - current_yaw_rate

        rudder_cmd = self.pid_rate.update(rate_error, dt)

        self.ship.rudder_cmd = rudder_cmd

    # ========== ОТЛАДКА ==========

    def get_debug_info(self):
        """
        Получить отладочную информацию о состоянии авторулевого.

        Returns:
            dict с текущими параметрами
        """
        mode_str = "ROUTE" if self.mode == self.MODE_ROUTE else "HOLD"
        info = {
            'mode': mode_str,
            'segment': self.current_segment_index,
            'rudder_cmd': self.ship.rudder_cmd,
        }

        if self.mode == self.MODE_HOLD_COURSE and self.hold_course_rad is not None:
            info['hold_course_deg'] = np.rad2deg(self.hold_course_rad)

        return info