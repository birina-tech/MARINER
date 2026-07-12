"""
collision_analyzer.py
Анализ столкновений и определение правил МППСС
"""
import numpy as np
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QGroupBox, QScrollArea, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor
from colreg_rules import determine_colreg_situation, calculate_relative_bearing
from safe_passing_dialog import SafePassingDialog


class CollisionAnalyzer:
    """Анализатор столкновений"""

    def calculate_cpa_tcpa(self, ship1, ship2):
        # ... без изменений ...
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
        # ... без изменений ...
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


class CollisionAnalysisWindow(QMainWindow):
    """Окно анализа столкновений"""

    def __init__(self, ships, parent=None):
        super().__init__()
        self.ships_ref = ships
        self.main_window = parent
        self.analyzer = CollisionAnalyzer()
        self.setWindowTitle("COLREGs Analysis")
        self.resize(1000, 600)
        self.init_ui()
        self.update_table()
        
        # === ТАЙМЕР АВТООБНОВЛЕНИЯ ===
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_table)
        self.update_timer.start(1000)  # Обновление каждую секунду

    def _get_ships(self):
        """Получить список судов (с учётом callable)"""
        return self.ships_ref() if callable(self.ships_ref) else self.ships_ref

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        title_label = QLabel("Interaction of each pair of vessels in the context of the COLREGs")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        self.btn_calculate_maneuvers = QPushButton("🧮 Calculate Safe Maneuvers for All Vessels")
        self.btn_calculate_maneuvers.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.btn_calculate_maneuvers.clicked.connect(self.calculate_all_maneuvers)
        layout.addWidget(self.btn_calculate_maneuvers)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        
        # === ИСПРАВЛЕНО: используем _get_ships() ===
        ships = self._get_ships()
        self.table.setHorizontalHeaderLabels([
            "Pair",
            "Distance (m)",
            "CPA (m)",
            "TCPA (s)",
            "Risk",
            "Rule №",
            "Situation",
            "Bearing 1→2",
            "Bearing 2→1",
            "Crosses ahead",
            f"Action {ships[0].name if len(ships) > 0 else 'Ship1'}",
            f"Action {ships[1].name if len(ships) > 1 else 'Ship2'}"
        ])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 60)
        self.table.setColumnWidth(5, 70)
        self.table.setColumnWidth(6, 150)
        self.table.setColumnWidth(7, 90)
        self.table.setColumnWidth(8, 90)
        self.table.setColumnWidth(9, 200)
        scroll.setWidget(self.table)
        layout.addWidget(scroll)

        btn_close = QPushButton("Close window")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

    def calculate_all_maneuvers(self):
        try:
            from safe_passing_dialog import SafePassingDialog
            ships = self._get_ships()  # ← ИСПРАВЛЕНО
            if len(ships) < 2:
                QMessageBox.warning(
                    self, "Not enough vessels",
                    "Need at least 2 vessels to calculate safe passing."
                )
                return
            dialog = SafePassingDialog(ships, self.main_window)
            dialog.exec_()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open calculator:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def show_maneuver_results(self, maneuvers, ships):
        msg = QMessageBox(self)
        msg.setWindowTitle("Calculated Maneuvers")
        msg.setIcon(QMessageBox.Information)
        text = "<h3>Maneuver Plan for All Vessels:</h3><ul>"
        for ship in ships:
            maneuver = maneuvers.get(ship.name, {})
            text += f"<li><b>{ship.name}</b>: "
            text += f"Turn {maneuver.get('turn_angle_deg', 0):+.0f}° "
            text += f"to course {maneuver.get('new_course_deg', 0):.0f}°<br>"
            text += f"<i>{maneuver.get('reason', '')}</i></li>"
        text += "</ul>"
        msg.setText(text)
        msg.exec_()

    def apply_maneuvers(self, maneuvers, ships):
        for ship in ships:
            maneuver = maneuvers.get(ship.name)
            if maneuver and maneuver.get('is_valid', False) and maneuver.get('turn_angle_deg', 0) != 0:
                new_course = maneuver['new_course_deg']
                ship.set_base_heading(new_course)
                current_heading = ship.get_heading_deg()
                turn_angle = (new_course - current_heading + 180) % 360 - 180
                ship.rudder_cmd = max(-35, min(35, turn_angle * 2))
        QMessageBox.information(
            self, "Maneuvers Applied",
            f"Calculated maneuvers applied to {len([s for s in ships if maneuvers.get(s.name, {}).get('turn_angle_deg', 0) != 0])} vessels"
        )

    def update_table(self):
        """Обновить таблицу анализа"""
        ships = self._get_ships()  # ← ИСПРАВЛЕНО
        if len(ships) < 2:
            self.table.setRowCount(0)
            return
        self.table.setRowCount(0)
        row = 0
        for i in range(len(ships)):
            for j in range(i + 1, len(ships)):
                ship1 = ships[i]
                ship2 = ships[j]
                cpa_data = self.analyzer.calculate_cpa_tcpa(ship1, ship2)
                risk_index = self.analyzer.calculate_risk_index(
                    cpa_data['DCPA'], cpa_data['TCPA'], cpa_data['dist']
                )
                colreg_data = determine_colreg_situation(
                    ship1, ship2,
                    cpa_data['dist'], cpa_data['DCPA'], cpa_data['TCPA']
                )
                crossing_data = self.analyzer.calculate_course_crossing(ship1, ship2)

                self.table.insertRow(row)
                pair_item = QTableWidgetItem(f"{ship1.name} ↔ {ship2.name}")
                self.table.setItem(row, 0, pair_item)

                from units import format_distance
                dist_item = QTableWidgetItem(format_distance(
                    cpa_data['dist'],
                    self.parent().use_miles if hasattr(self.parent(), 'use_miles') else True
                ))
                self.table.setItem(row, 1, dist_item)

                cpa_item = QTableWidgetItem(format_distance(
                    cpa_data['DCPA'],
                    self.parent().use_miles if hasattr(self.parent(), 'use_miles') else True
                ))
                self.table.setItem(row, 2, cpa_item)

                tcpa_val = cpa_data['TCPA']
                tcpa_str = f"{tcpa_val:.0f}" if tcpa_val != float('inf') else ""
                tcpa_item = QTableWidgetItem(tcpa_str)
                self.table.setItem(row, 3, tcpa_item)

                risk_item = QTableWidgetItem(f"{risk_index:.2f}")
                self.table.setItem(row, 4, risk_item)

                if risk_index > 0.7:
                    color = Qt.red
                elif risk_index > 0.4:
                    color = Qt.yellow
                else:
                    color = Qt.green
                for col in range(5):
                    self.table.item(row, col).setBackground(color)

                rule_item = QTableWidgetItem(f"Rule {colreg_data['rule']}")
                self.table.setItem(row, 5, rule_item)

                situation_item = QTableWidgetItem(colreg_data['situation'])
                self.table.setItem(row, 6, situation_item)

                details = colreg_data.get('details', {})
                bearing_1_to_2 = details.get('bearing_1_to_2', None)
                bearing_2_to_1 = details.get('bearing_2_to_1', None)

                if bearing_1_to_2 is not None:
                    self.table.setItem(row, 7, QTableWidgetItem(f"{bearing_1_to_2:.0f}°"))
                else:
                    self.table.setItem(row, 7, QTableWidgetItem("-"))

                if bearing_2_to_1 is not None:
                    self.table.setItem(row, 8, QTableWidgetItem(f"{bearing_2_to_1:.0f}°"))
                else:
                    self.table.setItem(row, 8, QTableWidgetItem("-"))

                if crossing_data['crossing_type']:
                    cross_text = (f"{crossing_data['crossing_type']}\n"
                                  f"(t={min(crossing_data['time_1_to_cross'], crossing_data['time_2_to_cross']):.0f}s)")
                    cross_item = QTableWidgetItem(cross_text)
                    cross_item.setBackground(QColor(255, 200, 200))
                    self.table.setItem(row, 9, cross_item)
                else:
                    self.table.setItem(row, 9, QTableWidgetItem("No crossing"))

                action1_item = QTableWidgetItem(colreg_data['ship1_action'])
                self.table.setItem(row, 10, action1_item)
                action2_item = QTableWidgetItem(colreg_data['ship2_action'])
                self.table.setItem(row, 11, action2_item)
                row += 1

    # === ИСПРАВЛЕНО: метод ВНУТРИ класса ===
    def closeEvent(self, event):
        """Остановить таймер при закрытии окна"""
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        super().closeEvent(event)


def launch_collision_analysis(ships, parent=None):
    """Запустить окно анализа столкновений"""
    window = CollisionAnalysisWindow(ships, parent)
    window.show()
    return window