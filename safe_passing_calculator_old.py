"""
safe_passing_calculator.py
Расчёт параметров безопасного расхождения судов по МППСС.
"""
import numpy as np


class SafePassingCalculator:
    """Калькулятор безопасного расхождения судов"""
    
    def __init__(self):
        # Настройки по умолчанию
        self.desired_dcpa_m = 1852.0  # Желаемое DCPA (1 морская миля)
        self.maneuver_start_tcpa_s = 300.0  # За сколько секунд до TCPA начинать манёвр
        self.min_turn_angle_deg = 15.0  # Минимальный угол поворота
        self.max_turn_angle_deg = 60.0  # Максимальный угол поворота
        self.prefer_starboard = True  # Предпочитать поворот вправо
        self.search_resolution_deg = 1.0  # Точность поиска курса
    
    def calculate_safe_course(self, give_way_ship, stand_on_ship, 
                              desired_dcpa_m=None, prefer_starboard=None):
        """
        Рассчитать безопасный курс для give-way судна.
        Сначала ищем решение справа (starboard). 
        Если не нашли — ищем слева (port).
        """
        if desired_dcpa_m is None:
            desired_dcpa_m = self.desired_dcpa_m
        
        # Автоматически определяем prefer_starboard на основе МППСС
        if prefer_starboard is None:
            prefer_starboard = self.prefer_starboard
        
        current_course = give_way_ship.get_heading_deg()
        
        # Проверяем текущее DCPA
        current_dcpa = self._calculate_dcpa_for_course(
            give_way_ship, stand_on_ship, current_course
        )
        
        if current_dcpa >= desired_dcpa_m:
            return {
                'safe_course_deg': current_course,
                'turn_angle_deg': 0.0,
                'achieved_dcpa_m': current_dcpa,
                'is_valid': True,
                'method': 'no_maneuver_needed',
                'message': 'Current course is already safe'
            }
        
        # === ШАГ 1: Ищем решение СПРАВА (starboard) ===
        starboard_angles = np.arange(self.min_turn_angle_deg, 
                                     self.max_turn_angle_deg + 1, 
                                     self.search_resolution_deg)
        
        for angle in starboard_angles:
            test_course = (current_course + angle) % 360
            test_dcpa = self._calculate_dcpa_for_course(
                give_way_ship, stand_on_ship, test_course
            )
            
            if test_dcpa >= desired_dcpa_m:
                return {
                    'safe_course_deg': test_course,
                    'turn_angle_deg': angle,
                    'achieved_dcpa_m': test_dcpa,
                    'is_valid': True,
                    'method': 'starboard_turn',
                    'message': f'Safe course found: turn {angle:.0f}\u00b0 starboard'
                }
        
        # === ШАГ 2: Справа не нашли — ищем СЛЕВА (port) ===
        port_angles = -np.arange(self.min_turn_angle_deg, 
                                 self.max_turn_angle_deg + 1, 
                                 self.search_resolution_deg)
        
        for angle in port_angles:
            test_course = (current_course + angle) % 360
            test_dcpa = self._calculate_dcpa_for_course(
                give_way_ship, stand_on_ship, test_course
            )
            
            if test_dcpa >= desired_dcpa_m:
                return {
                    'safe_course_deg': test_course,
                    'turn_angle_deg': angle,
                    'achieved_dcpa_m': test_dcpa,
                    'is_valid': True,
                    'method': 'port_turn',
                    'message': f'Safe course found: turn {abs(angle):.0f}\u00b0 port (starboard not sufficient)'
                }
        
        # === ШАГ 3: Не нашли ни справа, ни слева ===
        best_course = current_course
        best_dcpa = current_dcpa
        best_turn = 0
        
        for angle in starboard_angles:
            test_course = (current_course + angle) % 360
            test_dcpa = self._calculate_dcpa_for_course(
                give_way_ship, stand_on_ship, test_course
            )
            if test_dcpa > best_dcpa:
                best_dcpa = test_dcpa
                best_course = test_course
                best_turn = angle
        
        for angle in port_angles:
            test_course = (current_course + angle) % 360
            test_dcpa = self._calculate_dcpa_for_course(
                give_way_ship, stand_on_ship, test_course
            )
            if test_dcpa > best_dcpa:
                best_dcpa = test_dcpa
                best_course = test_course
                best_turn = angle
        
        return {
            'safe_course_deg': best_course,
            'turn_angle_deg': best_turn,
            'achieved_dcpa_m': best_dcpa,
            'is_valid': False,
            'method': 'best_effort',
            'message': f'No safe course within ±{self.max_turn_angle_deg}\u00b0. Best DCPA: {best_dcpa:.0f} m'
        }
    
    def calculate_maneuver_timing(self, give_way_ship, stand_on_ship,
                                  maneuver_start_tcpa_s=None):
        """Рассчитать момент начала манёвра."""
        if maneuver_start_tcpa_s is None:
            maneuver_start_tcpa_s = self.maneuver_start_tcpa_s
        
        current_tcpa = self._calculate_tcpa(give_way_ship, stand_on_ship)
        
        if current_tcpa <= 0:
            urgency = 'passed'
            should_maneuver = False
            time_to_maneuver = float('inf')
        elif current_tcpa <= 60:
            urgency = 'critical'
            should_maneuver = True
            time_to_maneuver = 0
        elif current_tcpa <= maneuver_start_tcpa_s:
            urgency = 'high'
            should_maneuver = True
            time_to_maneuver = 0
        elif current_tcpa <= maneuver_start_tcpa_s * 1.5:
            urgency = 'medium'
            should_maneuver = False
            time_to_maneuver = current_tcpa - maneuver_start_tcpa_s
        else:
            urgency = 'low'
            should_maneuver = False
            time_to_maneuver = current_tcpa - maneuver_start_tcpa_s
        
        return {
            'should_maneuver_now': should_maneuver,
            'current_tcpa_s': current_tcpa,
            'maneuver_start_tcpa_s': maneuver_start_tcpa_s,
            'time_to_maneuver_s': time_to_maneuver,
            'urgency': urgency
        }
    
    def simulate_passing(self, give_way_ship, stand_on_ship, 
                         new_course_deg, dt=1.0, max_time_s=1800):
        """Симулировать расхождение судов после манёвра."""
        orig_x1, orig_y1 = give_way_ship.x, give_way_ship.y
        orig_psi1 = give_way_ship.psi
        orig_u1 = give_way_ship.u
        
        orig_x2, orig_y2 = stand_on_ship.x, stand_on_ship.y
        orig_psi2 = stand_on_ship.psi
        orig_u2 = stand_on_ship.u
        
        give_way_ship.psi = np.deg2rad(new_course_deg)
        
        min_dist = float('inf')
        min_dist_time = 0
        trajectory_1 = [(give_way_ship.x, give_way_ship.y)]
        trajectory_2 = [(stand_on_ship.x, stand_on_ship.y)]
        
        t = 0
        while t < max_time_s:
            x1_dot = give_way_ship.u * np.sin(give_way_ship.psi)
            y1_dot = give_way_ship.u * np.cos(give_way_ship.psi)
            give_way_ship.x += x1_dot * dt
            give_way_ship.y += y1_dot * dt
            
            x2_dot = stand_on_ship.u * np.sin(stand_on_ship.psi)
            y2_dot = stand_on_ship.u * np.cos(stand_on_ship.psi)
            stand_on_ship.x += x2_dot * dt
            stand_on_ship.y += y2_dot * dt
            
            dist = np.sqrt((give_way_ship.x - stand_on_ship.x)**2 + 
                          (give_way_ship.y - stand_on_ship.y)**2)
            
            if dist < min_dist:
                min_dist = dist
                min_dist_time = t
            
            trajectory_1.append((give_way_ship.x, give_way_ship.y))
            trajectory_2.append((stand_on_ship.x, stand_on_ship.y))
            
            if dist > 5000 and t > 60:
                break
            
            t += dt
        
        give_way_ship.x, give_way_ship.y = orig_x1, orig_y1
        give_way_ship.psi = orig_psi1
        give_way_ship.u = orig_u1
        
        stand_on_ship.x, stand_on_ship.y = orig_x2, orig_y2
        stand_on_ship.psi = orig_psi2
        stand_on_ship.u = orig_u2
        
        return {
            'min_distance_m': min_dist,
            'achieved_dcpa_m': min_dist,
            'tcpa_at_min_dist_s': min_dist_time,
            'trajectory_1': trajectory_1,
            'trajectory_2': trajectory_2,
            'is_safe': min_dist >= self.desired_dcpa_m
        }
    
    def predict_trajectory(self, ship, new_course_deg=None, 
                           maneuver_time_s=0, duration_s=600, dt=2.0):
        """Прогнозирует траекторию судна."""
        orig_x, orig_y = ship.x, ship.y
        orig_psi = ship.psi
        orig_u = ship.u
        orig_r = ship.r
        orig_rudder_cmd = ship.rudder_cmd
        orig_rpm_cmd = ship.rpm_cmd
        
        pre_maneuver = [(ship.x, ship.y)]
        post_maneuver = []
        maneuver_point = None
        
        t = 0
        maneuver_applied = False
        
        while t < duration_s:
            if t >= maneuver_time_s and not maneuver_applied and new_course_deg is not None:
                maneuver_point = (ship.x, ship.y)
                
                current_heading = ship.get_heading_deg()
                turn_angle = (new_course_deg - current_heading + 180) % 360 - 180
                ship.rudder_cmd = max(-35, min(35, turn_angle * 2))
                maneuver_applied = True
            
            ship.update(dt)
            
            t += dt
            
            if not maneuver_applied:
                pre_maneuver.append((ship.x, ship.y))
            else:
                post_maneuver.append((ship.x, ship.y))
        
        ship.x, ship.y = orig_x, orig_y
        ship.psi = orig_psi
        ship.u = orig_u
        ship.r = orig_r
        ship.rudder_cmd = orig_rudder_cmd
        ship.rpm_cmd = orig_rpm_cmd
        
        return {
            'pre_maneuver': pre_maneuver,
            'post_maneuver': post_maneuver,
            'maneuver_point': maneuver_point
        }
    
    def calculate_full_maneuver_plan(self, give_way_ship, stand_on_ship):
        """Рассчитать полный план манёвра: курс + момент начала."""
        course_result = self.calculate_safe_course(give_way_ship, stand_on_ship)
        timing_result = self.calculate_maneuver_timing(give_way_ship, stand_on_ship)
        
        simulation_result = None
        if timing_result['should_maneuver_now'] and course_result['is_valid']:
            simulation_result = self.simulate_passing(
                give_way_ship, stand_on_ship, 
                course_result['safe_course_deg']
            )
        
        return {
            'course_plan': course_result,
            'timing_plan': timing_result,
            'simulation': simulation_result,
            'recommendation': self._generate_recommendation(
                course_result, timing_result
            )
        }
    
    def _generate_recommendation(self, course_result, timing_result):
        """Сгенерировать текстовую рекомендацию"""
        if not timing_result['should_maneuver_now']:
            time_to = timing_result['time_to_maneuver_s']
            if time_to == float('inf'):
                return "No maneuver needed - vessels have passed"
            return f"Wait {time_to/60:.1f} min before maneuver"
        
        if not course_result['is_valid']:
            return "WARNING: Cannot find safe course within limits!"
        
        turn = course_result['turn_angle_deg']
        direction = "starboard" if turn > 0 else "port"
        
        urgency = timing_result['urgency']
        urgency_text = {
            'critical': 'IMMEDIATELY',
            'high': 'NOW',
            'medium': 'soon'
        }.get(urgency, '')
        
        return (f"Turn {abs(turn):.0f}\u00b0 to {direction} {urgency_text}. "
                f"Expected DCPA: {course_result['achieved_dcpa_m']:.0f} m")
    
    def _calculate_dcpa_for_course(self, give_way_ship, stand_on_ship, course_deg):
        """Рассчитать DCPA для заданного курса give-way судна."""
        orig_psi = give_way_ship.psi
        give_way_ship.psi = np.deg2rad(course_deg)
        dcpa = self._calculate_dcpa(give_way_ship, stand_on_ship)
        give_way_ship.psi = orig_psi
        return dcpa
    
    def _calculate_dcpa(self, ship1, ship2):
        """Рассчитать DCPA между двумя судами"""
        dx = ship2.x - ship1.x
        dy = ship2.y - ship1.y
        
        v1_x = ship1.u * np.sin(ship1.psi)
        v1_y = ship1.u * np.cos(ship1.psi)
        v2_x = ship2.u * np.sin(ship2.psi)
        v2_y = ship2.u * np.cos(ship2.psi)
        
        v_rel_x = v2_x - v1_x
        v_rel_y = v2_y - v1_y
        v_rel = np.sqrt(v_rel_x**2 + v_rel_y**2)
        
        if v_rel < 0.1:
            return np.sqrt(dx**2 + dy**2)
        
        v_rel_norm_x = v_rel_x / v_rel
        v_rel_norm_y = v_rel_y / v_rel
        
        proj = dx * v_rel_norm_x + dy * v_rel_norm_y
        tcpa = -proj / v_rel
        
        if tcpa < 0:
            return np.sqrt(dx**2 + dy**2)
        
        cpa_x = dx + v_rel_x * tcpa
        cpa_y = dy + v_rel_y * tcpa
        
        return np.sqrt(cpa_x**2 + cpa_y**2)
    
    def _calculate_tcpa(self, ship1, ship2):
        """Рассчитать TCPA между двумя судами"""
        dx = ship2.x - ship1.x
        dy = ship2.y - ship1.y
        
        v1_x = ship1.u * np.sin(ship1.psi)
        v1_y = ship1.u * np.cos(ship1.psi)
        v2_x = ship2.u * np.sin(ship2.psi)
        v2_y = ship2.u * np.cos(ship2.psi)
        
        v_rel_x = v2_x - v1_x
        v_rel_y = v2_y - v1_y
        v_rel = np.sqrt(v_rel_x**2 + v_rel_y**2)
        
        if v_rel < 0.1:
            return float('inf')
        
        v_rel_norm_x = v_rel_x / v_rel
        v_rel_norm_y = v_rel_y / v_rel
        
        proj = dx * v_rel_norm_x + dy * v_rel_norm_y
        tcpa = -proj / v_rel
        
        return max(0, tcpa)