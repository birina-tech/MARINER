"""
collision_analyzer.py
Collision analysis and COLREGs rules determination
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
    """Collision Analyzer math engine"""

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


class CollisionAnalysisWindow(QMainWindow):
    """COLREGs Analysis GUI Dashboard Window"""

    def __init__(self, ships, parent=None):
        super().__init__()
        self.ships_ref = ships
        self.main_window = parent
        self.analyzer = CollisionAnalyzer()
        self.setWindowTitle("COLREGs Analysis")
        self.resize(1100, 600)
        self.init_ui()
        self.update_table()
        
        # Timer to refresh the table every second to reflect real-time changes in vessel telemetry
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_table)
        self.update_timer.start(1000)

    def _get_ships(self):
        """Returns the current list of ships, whether it's a callable or a direct reference."""
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
        
        ships = self._get_ships()
        self.table.setHorizontalHeaderLabels([
            "Pair",
            "Distance (m)",
            "CPA (m)",
            "TCPA (s)",
            "Risk",
            "Rule #",
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
        self.table.setColumnWidth(5, 110)
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
            ships = self._get_ships()
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

    def update_table(self):
        """Refreshes and dynamically recalculates the encounter evaluation matrix"""
        ships = self._get_ships()
        if len(ships) < 2:
            self.table.setRowCount(0)
            return
            
        # Explicit clear prevents UI row bleeding artifacts during active step loops
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
                
                # Pair Name Identification
                pair_item = QTableWidgetItem(f"{ship1.name} ↔ {ship2.name}")
                self.table.setItem(row, 0, pair_item)

                from units import format_distance
                use_miles = self.main_window.use_miles if self.main_window else True

                # Telemetry formatting parameters
                dist_item = QTableWidgetItem(format_distance(cpa_data['dist'], use_miles))
                self.table.setItem(row, 1, dist_item)

                cpa_item = QTableWidgetItem(format_distance(cpa_data['DCPA'], use_miles))
                self.table.setItem(row, 2, cpa_item)

                tcpa_val = cpa_data['TCPA']
                tcpa_str = f"{tcpa_val:.0f}" if tcpa_val != float('inf') else "—"
                self.table.setItem(row, 3, QTableWidgetItem(tcpa_str))

                risk_item = QTableWidgetItem(f"{risk_index:.2f}")
                self.table.setItem(row, 4, risk_item)

                # Set colored row backgrounds relative to threat severity values
                if risk_index > 0.7:
                    row_color = QColor(255, 200, 200) # Crimson warning
                elif risk_index > 0.4:
                    row_color = QColor(255, 255, 200) # Amber caution
                else:
                    row_color = QColor(200, 255, 200) # Safe green

                for col in range(5):
                    self.table.item(row, col).setBackground(row_color)

                # DYNAMIC RE-FORMATTING FIX FOR RULE # FIELD
                raw_rule = str(colreg_data.get('rule', 'None'))
                if raw_rule in ['None', 'Unknown']:
                    rule_text = "Safe (No Rule)"
                else:
                    rule_text = f"Rule {raw_rule}"
                
                rule_item = QTableWidgetItem(rule_text)
                self.table.setItem(row, 5, rule_item)

                # Situation Type Text
                situation_item = QTableWidgetItem(colreg_data['situation'])
                self.table.setItem(row, 6, situation_item)

                # Relative Bearings
                details = colreg_data.get('details', {})
                b_1_2 = details.get('bearing_1_to_2', None)
                b_2_1 = details.get('bearing_2_to_1', None)

                b1_str = f"{b_1_2:.0f}°" if b_1_2 is not None else "—"
                b2_str = f"{b_2_1:.0f}°" if b_2_1 is not None else "—"
                
                self.table.setItem(row, 7, QTableWidgetItem(b1_str))
                self.table.setItem(row, 8, QTableWidgetItem(b2_str))

                # Course crossing forecast
                if crossing_data['crossing_type']:
                    cross_text = (f"{crossing_data['crossing_type']}\n"
                                  f"(t={min(crossing_data['time_1_to_cross'], crossing_data['time_2_to_cross']):.0f}s)")
                    cross_item = QTableWidgetItem(cross_text)
                    cross_item.setBackground(QColor(255, 220, 220))
                    self.table.setItem(row, 9, cross_item)
                else:
                    self.table.setItem(row, 9, QTableWidgetItem("No crossing"))

                # Context Action items mapping
                self.table.setItem(row, 10, QTableWidgetItem(colreg_data['ship1_action']))
                self.table.setItem(row, 11, QTableWidgetItem(colreg_data['ship2_action']))
                
                row += 1

    def closeEvent(self, event):
        """Stop timer when window is closed to prevent memory leaks"""
        if hasattr(self, 'update_timer'):
            self.update_timer.stop()
        super().closeEvent(event)


def launch_collision_analysis(ships, parent=None):
    """Launches the Collision Analysis Window"""
    window = CollisionAnalysisWindow(ships, parent)
    window.show()
    return window