"""
autopilot_debug_dialog.py
Немодальное окно отладки авторулевого.
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGroupBox, QFormLayout, QFrame)
from PyQt5.QtCore import Qt, QTimer


class AutopilotDebugDialog(QDialog):
    """Немодальное окно отладки авторулевого"""

    def __init__(self, ship, parent=None):
        super().__init__(parent)
        self.ship = ship
        self.setWindowTitle(f"Autopilot Debug: {ship.name}")
        self.setFixedSize(450, 380)
        self.setModal(False)

        self.init_ui()
        self.update_info()

        # Таймер обновления каждые 500 мс
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_info)
        self.timer.start(500)

    def init_ui(self):
        layout = QVBoxLayout()

        # Заголовок
        title = QLabel(f"Autopilot: {self.ship.name}")
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Группа: Маршрут и сегмент
        group_route = QGroupBox("Route Information")
        form_route = QFormLayout()

        self.lbl_route_name = QLabel("-")
        self.lbl_route_name.setStyleSheet("font-weight: bold; color: #0066CC;")
        form_route.addRow("Route:", self.lbl_route_name)

        self.lbl_segment = QLabel("-")
        self.lbl_segment.setStyleSheet("font-weight: bold; color: #006600;")
        form_route.addRow("Current leg:", self.lbl_segment)

        self.lbl_mode = QLabel("-")
        self.lbl_mode.setStyleSheet("font-weight: bold;")
        form_route.addRow("Mode:", self.lbl_mode)

        self.lbl_hold_course = QLabel("-")
        form_route.addRow("Hold course:", self.lbl_hold_course)

        group_route.setLayout(form_route)
        layout.addWidget(group_route)

        # Группа: Дистанции
        group_dist = QGroupBox("Distances")
        form_dist = QFormLayout()

        self.lbl_d1 = QLabel("-")
        form_dist.addRow("d1 (to current leg):", self.lbl_d1)

        self.lbl_d2 = QLabel("-")
        form_dist.addRow("d2 (to next leg):", self.lbl_d2)

        self.lbl_threshold = QLabel("-")
        form_dist.addRow("Turn distance:", self.lbl_threshold)

        group_dist.setLayout(form_dist)
        layout.addWidget(group_dist)

        # Группа: Курсы и руль
        group_course = QGroupBox("Course & Rudder")
        form_course = QFormLayout()

        self.lbl_course_on_leg = QLabel("-")
        form_course.addRow("Course on leg:", self.lbl_course_on_leg)

        self.lbl_correction = QLabel("-")
        self.lbl_correction.setStyleSheet("font-weight: bold;")
        form_course.addRow("Correction (ΔK_χ):", self.lbl_correction)

        self.lbl_rudder = QLabel("-")
        self.lbl_rudder.setStyleSheet("font-size: 12px; font-weight: bold; color: #CC0000;")
        form_course.addRow("Rudder cmd:", self.lbl_rudder)

        group_course.setLayout(form_course)
        layout.addWidget(group_course)

        # Кнопка закрытия
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)

        self.setLayout(layout)

    def update_info(self):
        """Обновить информацию из авторулевого"""
        if not hasattr(self.ship, 'autopilot') or self.ship.autopilot is None:
            self.lbl_route_name.setText("No autopilot")
            return

        ap = self.ship.autopilot
        info = ap.get_debug_info()

        # Маршрут
        self.lbl_route_name.setText(info.get('route_name', '-'))

        # Сегмент
        self.lbl_segment.setText(info.get('segment', '-'))

        # Режим
        mode = info.get('mode', '-')
        self.lbl_mode.setText(mode)
        if mode == "HOLD":
            self.lbl_mode.setStyleSheet("font-weight: bold; color: #FF6600;")
            hold_course = info.get('hold_course')
            self.lbl_hold_course.setText(f"{hold_course:.1f}\u00b0" if hold_course else "-")
        else:
            self.lbl_mode.setStyleSheet("font-weight: bold; color: #006600;")
            self.lbl_hold_course.setText("-")

        # Дистанции
        d1 = info.get('d1', 0.0)
        d2 = info.get('d2', 0.0)
        self.lbl_d1.setText(f"{d1:.0f} m")
        self.lbl_d2.setText(f"{d2:.0f} m")
        turn_dist = info.get('turn_distance', 0.0)
        turn_angle = info.get('turn_angle', 0.0)
        if turn_dist > 0:
            self.lbl_threshold.setText(f"{turn_dist:.0f} m (angle {turn_angle:.0f}\u00b0)")
        else:
            self.lbl_threshold.setText("Last leg (no turn)")

        # Подсветка: если d2 < threshold — скоро поворот
        if d2 < info.get('turn_threshold', float('inf')):
            self.lbl_d2.setStyleSheet("font-weight: bold; color: #FF0000;")
        else:
            self.lbl_d2.setStyleSheet("")

        # Курсы
        self.lbl_course_on_leg.setText(f"{info.get('course_on_leg', 0):.1f}\u00b0")

        correction = info.get('course_correction', 0.0)
        self.lbl_correction.setText(f"{correction:+.2f}\u00b0")
        if abs(correction) > 10:
            self.lbl_correction.setStyleSheet("font-weight: bold; color: #FF0000;")
        else:
            self.lbl_correction.setStyleSheet("")

        # Руль
        rudder = info.get('rudder_cmd', 0.0)
        self.lbl_rudder.setText(f"{rudder:+.1f}\u00b0")

    def closeEvent(self, event):
        self.timer.stop()
        super().closeEvent(event)