"""
collision_analyzer.py (backend / headless version)

Same CPA/TCPA/risk/crossing math as the original MARINER desktop app's
CollisionAnalyzer class. The PyQt5 CollisionAnalysisWindow has been removed —
that responsibility now belongs to the browser frontend (it renders the
COLREGs table from the WebSocket 'state' message instead).
"""
import numpy as np


class CollisionAnalyzer:
    """CPA/TCPA, risk index and course-crossing calculations (no UI)."""

    def calculate_cpa_tcpa(self, ship1, ship2):
        dx = ship2.x - ship1.x
        dy = ship2.y - ship1.y
        dist = np.sqrt(dx**2 + dy**2)
        v1_x = ship1.u * np.sin(ship1.psi)
        v1_y = ship1.u * np.cos(ship1.psi)
        v2_x = ship2.u * np.sin(ship2.psi)
        v2_y = ship2.u * np.cos(ship2.psi)
        v_rel_x = v2_x - v1_x
        v_rel_y = v2_y - v1_y
        v_rel = np.sqrt(v_rel_x**2 + v_rel_y**2)
        if v_rel < 0.1:
            return {'dist': dist, 'DCPA': dist, 'TCPA': float('inf'), 'v_rel': v_rel}
        v_rel_norm_x = v_rel_x / v_rel
        v_rel_norm_y = v_rel_y / v_rel
        proj = dx * v_rel_norm_x + dy * v_rel_norm_y
        tcpa = -proj / v_rel
        if tcpa < 0:
            tcpa = 0
        cpa_x = dx + v_rel_x * tcpa
        cpa_y = dy + v_rel_y * tcpa
        dcpa = np.sqrt(cpa_x**2 + cpa_y**2)
        return {'dist': dist, 'DCPA': dcpa, 'TCPA': tcpa, 'v_rel': v_rel}

    def calculate_risk_index(self, dcpa, tcpa, dist):
        dcpa_risk = max(0, min(1, (1000 - dcpa) / 1000))
        tcpa_risk = max(0, min(1, (600 - tcpa) / 600))
        dist_risk = max(0, min(1, (5000 - dist) / 5000))
        return (dcpa_risk + tcpa_risk + dist_risk) / 3

    def calculate_course_crossing(self, ship1, ship2):
        result = {
            'crossing_point': None,
            'crosses_1_by_2': False,
            'crosses_2_by_1': False,
            'time_1_to_cross': None,
            'time_2_to_cross': None,
            'time_gap': None,
            'crossing_type': None,
        }
        sin1, cos1 = np.sin(ship1.psi), np.cos(ship1.psi)
        sin2, cos2 = np.sin(ship2.psi), np.cos(ship2.psi)
        dx = ship2.x - ship1.x
        dy = ship2.y - ship1.y
        D = sin2 * cos1 - cos2 * sin1
        if abs(D) < 1e-6:
            return result
        s = (dy * sin2 - dx * cos2) / D
        t = (dy * sin1 - dx * cos1) / D
        cross_x = ship1.x + s * sin1
        cross_y = ship1.y + s * cos1
        result['crossing_point'] = (cross_x, cross_y)
        if not (s > 0 and t > 0):
            return result
        if ship1.u < 0.1 or ship2.u < 0.1:
            return result
        time_1 = s / ship1.u
        time_2 = t / ship2.u
        result['time_1_to_cross'] = time_1
        result['time_2_to_cross'] = time_2
        result['time_gap'] = abs(time_1 - time_2)
        if time_1 < time_2:
            result['crosses_2_by_1'] = True
            result['crossing_type'] = f'{ship1.name} crosses {ship2.name} ahead'
        else:
            result['crosses_1_by_2'] = True
            result['crossing_type'] = f'{ship2.name} crosses {ship1.name} ahead'
        return result
