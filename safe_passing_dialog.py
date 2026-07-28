"""
safe_passing_dialog.py
Полноценное диалоговое окно калькулятора безопасного расхождения
"""
import numpy as np
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QDoubleSpinBox, QGroupBox, QFormLayout,
                             QComboBox, QTextEdit, QMessageBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from safe_passing_calculator import SafePassingCalculator

METERS_PER_NAUTICAL_MILE = 1852.0

def normalize_heading_error(target_heading, current_heading):
    ### normalizes the angular difference to fit strictly between -180 and +180 degrees
    return (target_heading - current_heading + 180) % 360 - 180


class SafePassingDialog(QDialog):
    """Полноценный диалог расчёта безопасного расхождения"""
    


    def __init__(self, ships, parent=None):
        super().__init__(parent)
        self.ships = ships
        self.parent_window = parent
        self.calculator = SafePassingCalculator()
        
        self.setWindowTitle("Safe Passing Calculator (Full)")
        self.setFixedSize(900, 700)
        
        self.init_ui()
        self.update_calculation()



    def init_ui(self):
        layout = QVBoxLayout()
        
        # === 1. Настройки параметров ===
        settings_group = QGroupBox("Passing Parameters")
        settings_layout = QHBoxLayout()
        
        # Желаемое DCPA
        dcpa_form = QFormLayout()
        self.dcpa_spin = QDoubleSpinBox()
        self.dcpa_spin.setRange(0.1, 5.0)
        self.dcpa_spin.setValue(1.0)
        self.dcpa_spin.setDecimals(2)
        self.dcpa_spin.setSuffix(" nm")
        self.dcpa_spin.valueChanged.connect(self.on_settings_changed)
        dcpa_form.addRow("Desired DCPA:", self.dcpa_spin)
        settings_layout.addLayout(dcpa_form)
        
        # TCPA начала манёвра
        tcpa_form = QFormLayout()
        self.tcpa_spin = QDoubleSpinBox()
        self.tcpa_spin.setRange(1.0, 30.0)
        self.tcpa_spin.setValue(5.0)
        self.tcpa_spin.setDecimals(1)
        self.tcpa_spin.setSuffix(" min")
        self.tcpa_spin.valueChanged.connect(self.on_settings_changed)
        tcpa_form.addRow("Start maneuver before TCPA:", self.tcpa_spin)
        settings_layout.addLayout(tcpa_form)
        
        # Предпочтение поворота
        turn_form = QFormLayout()
        self.turn_combo = QComboBox()
        self.turn_combo.addItem("Starboard (right)", True)
        self.turn_combo.addItem("Port (left)", False)
        self.turn_combo.currentIndexChanged.connect(self.on_settings_changed)
        turn_form.addRow("Prefer turn:", self.turn_combo)
        settings_layout.addLayout(turn_form)
        
        # Максимальный угол поворота
        angle_form = QFormLayout()
        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setRange(15, 90)
        self.angle_spin.setValue(60)
        self.angle_spin.setDecimals(0)
        self.angle_spin.setSuffix("\u00b0")
        self.angle_spin.valueChanged.connect(self.on_settings_changed)
        angle_form.addRow("Max turn angle:", self.angle_spin)
        settings_layout.addLayout(angle_form)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        # === 2. Выбор судов ===
        ships_group = QGroupBox("Vessels")
        ships_layout = QHBoxLayout()
        
        gw_form = QFormLayout()
        self.give_way_combo = QComboBox()
        for ship in self.ships:
            self.give_way_combo.addItem(ship.name, ship)
        self.give_way_combo.currentIndexChanged.connect(self.update_calculation)
        gw_form.addRow("Give-way vessel:", self.give_way_combo)
        ships_layout.addLayout(gw_form)
        
        so_form = QFormLayout()
        self.stand_on_combo = QComboBox()
        for ship in self.ships:
            self.stand_on_combo.addItem(ship.name, ship)
        if len(self.ships) > 1:
            self.stand_on_combo.setCurrentIndex(1)
        self.stand_on_combo.currentIndexChanged.connect(self.update_calculation)
        so_form.addRow("Stand-on vessel:", self.stand_on_combo)
        ships_layout.addLayout(so_form)
        
        ships_group.setLayout(ships_layout)
        layout.addWidget(ships_group)
        
        # === 3. Результаты расчёта ===
        results_group = QGroupBox("Calculation Results")
        results_layout = QVBoxLayout()
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(2)
        self.results_table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.results_table.setMaximumHeight(250)
        results_layout.addWidget(self.results_table)
        
        self.recommendation_label = QLabel()
        self.recommendation_label.setStyleSheet(
            "QLabel { font-size: 14px; font-weight: bold; padding: 10px; "
            "background-color: #e3f2fd; border-radius: 5px; }"
        )
        self.recommendation_label.setWordWrap(True)
        results_layout.addWidget(self.recommendation_label)
        
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(120)
        results_layout.addWidget(self.details_text)
        
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        # === 4. Кнопки ===
        buttons_layout = QHBoxLayout()
        
        btn_calculate = QPushButton(" Recalculate")
        btn_calculate.clicked.connect(self.update_calculation)
        buttons_layout.addWidget(btn_calculate)
        
        btn_show_tracks = QPushButton(" Show Predicted Tracks")
        btn_show_tracks.setStyleSheet("QPushButton { background-color: #87CEEB; font-weight: bold; }")
        btn_show_tracks.clicked.connect(self.show_predicted_tracks)
        buttons_layout.addWidget(btn_show_tracks)
        
        btn_apply = QPushButton("✅ Apply Course to Vessel")
        btn_apply.setStyleSheet("QPushButton { background-color: #90EE90; font-weight: bold; }")
        btn_apply.clicked.connect(self.apply_course)
        buttons_layout.addWidget(btn_apply)
        
        btn_clear_tracks = QPushButton(" Clear Tracks")
        btn_clear_tracks.clicked.connect(self.clear_predicted_tracks)
        buttons_layout.addWidget(btn_clear_tracks)
        
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        buttons_layout.addWidget(btn_close)
        
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
    
    def on_settings_changed(self):
        self.calculator.desired_dcpa_m = self.dcpa_spin.value() * METERS_PER_NAUTICAL_MILE
        self.calculator.maneuver_start_tcpa_s = self.tcpa_spin.value() * 60
        self.calculator.prefer_starboard = self.turn_combo.currentData()
        self.calculator.max_turn_angle_deg = self.angle_spin.value()
        self.update_calculation()
    
    def update_calculation(self):
        if len(self.ships) < 2:
            return
        
        give_way_ship = self.give_way_combo.currentData()
        stand_on_ship = self.stand_on_combo.currentData()
        
        if give_way_ship is None or stand_on_ship is None or give_way_ship is stand_on_ship:
            self.recommendation_label.setText("Select two different vessels")
            return
        
        try:
            result = self.calculator.calculate_full_maneuver_plan(give_way_ship, stand_on_ship)
            self._update_results_table(result, give_way_ship, stand_on_ship)
            self._update_recommendation(result)
            self._update_details(result, give_way_ship, stand_on_ship)
        except Exception as e:
            self.recommendation_label.setText(f"Calculation Error: {str(e)}")
            print(f"Error in calculation: {e}")
    
    def _update_results_table(self, result, give_way_ship, stand_on_ship):
        self.results_table.setRowCount(0)
        course_plan = result['course_plan']
        timing_plan = result['timing_plan']
        
        rows = [
            ("Current DCPA", f"{self.calculator._calculate_dcpa(give_way_ship, stand_on_ship):.0f} m"),
            ("Desired DCPA", f"{self.calculator.desired_dcpa_m:.0f} m"),
            ("Achieved DCPA", f"{course_plan['achieved_dcpa_m']:.0f} m"),
            ("", ""),
            ("Current TCPA", f"{timing_plan['current_tcpa_s']:.0f} s"),
            ("Maneuver threshold", f"{timing_plan['maneuver_start_tcpa_s']:.0f} s"),
            ("Urgency", timing_plan['urgency'].upper()),
            ("", ""),
            ("New course", f"{course_plan['safe_course_deg']:.1f}\u00b0"),
            ("Turn angle", f"{course_plan['turn_angle_deg']:+.1f}\u00b0"),
            ("Turn direction", "STARBOARD" if course_plan['turn_angle_deg'] > 0 else "PORT"),
            ("", ""),
            ("Valid solution", "YES" if course_plan['is_valid'] else "NO"),
        ]
        
        for param, value in rows:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            param_item = QTableWidgetItem(param)
            if param == "":
                param_item.setBackground(QColor(240, 240, 240))
            self.results_table.setItem(row, 0, param_item)
            
            value_item = QTableWidgetItem(str(value))
            if "CRITICAL" in str(value).upper():
                value_item.setBackground(QColor(255, 150, 150))
            self.results_table.setItem(row, 1, value_item)
    
    def _update_recommendation(self, result):
        recommendation = result['recommendation']
        urgency = result['timing_plan']['urgency']
        colors = {
            'critical': '#ff6666', 'high': '#ffaa66', 
            'medium': '#ffdd66', 'low': '#99ff99', 'passed': '#cccccc'
        }
        color = colors.get(urgency, '#e3f2fd')
        self.recommendation_label.setStyleSheet(
            f"QLabel {{ font-size: 14px; font-weight: bold; padding: 10px; "
            f"background-color: {color}; border-radius: 5px; }}"
        )
        self.recommendation_label.setText(recommendation)
    
    def _update_details(self, result, give_way_ship, stand_on_ship):
        course_plan = result['course_plan']
        timing_plan = result['timing_plan']
        
        details = f"""
<b>Vessel Details:</b>
• {give_way_ship.name}: Course {give_way_ship.get_heading_deg():.1f}\u00b0, Speed {give_way_ship.u:.1f} m/s
• {stand_on_ship.name}: Course {stand_on_ship.get_heading_deg():.1f}\u00b0, Speed {stand_on_ship.u:.1f} m/s

<b>Maneuver Plan:</b>
• Current course: {give_way_ship.get_heading_deg():.1f}\u00b0
• New course: {course_plan['safe_course_deg']:.1f}\u00b0
• Turn: {course_plan['turn_angle_deg']:+.1f}\u00b0
• Time to maneuver: {timing_plan['time_to_maneuver_s']:.0f} s
"""
        self.details_text.setHtml(details)
    


    def show_predicted_tracks(self):
        if len(self.ships) < 2:
            return
        
        give_way_ship = self.give_way_combo.currentData()
        stand_on_ship = self.stand_on_combo.currentData()
        
        if not give_way_ship or not stand_on_ship:
            return
        
        result = self.calculator.calculate_full_maneuver_plan(give_way_ship, stand_on_ship)
        course_plan = result['course_plan']
        timing_plan = result['timing_plan']
        
        maneuver_time_s = max(0, timing_plan['time_to_maneuver_s'])
        if maneuver_time_s == float('inf'):
            maneuver_time_s = 0
        duration_s = max(300, timing_plan['current_tcpa_s'] + 300)
        
        predicted_tracks = {}
        
        if course_plan['is_valid']:
            gw_track = self.calculator.predict_trajectory(
                give_way_ship, new_course_deg=course_plan['safe_course_deg'],
                maneuver_time_s=maneuver_time_s, duration_s=duration_s
            )
            predicted_tracks[give_way_ship.name] = {
                'pre_maneuver': gw_track['pre_maneuver'],
                'post_maneuver': gw_track['post_maneuver'],
                'maneuver_point': gw_track['maneuver_point'],
                'role': 'give_way',
                'new_course': course_plan['safe_course_deg']
            }
        
        so_track = self.calculator.predict_trajectory(
            stand_on_ship, new_course_deg=None, maneuver_time_s=99999, duration_s=duration_s
        )
        predicted_tracks[stand_on_ship.name] = {
            'pre_maneuver': so_track['pre_maneuver'] + so_track['post_maneuver'],
            'post_maneuver': [],
            'maneuver_point': None,
            'role': 'stand_on',
            'new_course': None
        }
        
        if self.parent_window and hasattr(self.parent_window, 'set_predicted_tracks'):
            self.parent_window.set_predicted_tracks(predicted_tracks)
            QMessageBox.information(
                self, "Tracks Shown",
                f"Predicted tracks displayed for:\n"
                f"• {give_way_ship.name}\n• {stand_on_ship.name}"
            )
        else:
            QMessageBox.warning(self, "Error", "Cannot send tracks to main window!")

    def clear_predicted_tracks(self):
        if self.parent_window and hasattr(self.parent_window, 'clear_predicted_tracks'):
            self.parent_window.clear_predicted_tracks()

    def apply_course(self):
        give_way_ship = self.give_way_combo.currentData()
        if not give_way_ship:
            return
        
        result = self.calculator.calculate_safe_course(
            give_way_ship, self.stand_on_combo.currentData()
        )
        
        if not result['is_valid']:
            QMessageBox.warning(self, "Cannot Apply", "No safe course found within limits!")
            return
        
        new_course = result['safe_course_deg']
        give_way_ship.set_base_heading(new_course)
        
        current_heading = give_way_ship.get_heading_deg()
        
        ### we substitute the hardcoded formula with our new utility function
        turn_angle = normalize_heading_error(new_course, current_heading)
        give_way_ship.rudder_cmd = max(-35, min(35, turn_angle * 2))
        
        QMessageBox.information(self, "Course Applied", f"New course {new_course:.1f}\u00b0 applied to {give_way_ship.name}")
        self.update_calculation()


def launch_safe_passing_calculator(ships, parent=None):
    dialog = SafePassingDialog(ships, parent)
    dialog.exec_()