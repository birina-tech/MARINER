"""
dialogs.py
Диалоговые окна для симулятора
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QComboBox, QDoubleSpinBox,
                             QSpinBox, QCheckBox, QGroupBox, QFormLayout,
                             QSlider)
from PyQt5.QtCore import Qt, QTimer

# Константы конвертации
KNOTS_TO_MS = 0.514444


class AddShipDialog(QDialog):
    """Диалог добавления судна"""
    
    def __init__(self, x, y, parent=None, default_course=0, default_speed=5.0, 
                 default_name=None, use_knots=True):
        super().__init__(parent)
        self.use_knots = use_knots
        
        self.setWindowTitle("Add Vessel")
        self.setFixedSize(350, 250)
        
        layout = QVBoxLayout()
        
        coord_layout = QHBoxLayout()
        coord_layout.addWidget(QLabel(f"Position: X={x:.0f} m, Y={y:.0f} m"))
        layout.addLayout(coord_layout)
        
        form_layout = QFormLayout()
        
        self.name_input = QLineEdit()
        if default_name:
            self.name_input.setText(default_name)
        else:
            self.name_input.setPlaceholderText("Auto-generated if empty")
        form_layout.addRow("Vessel name:", self.name_input)
        
        self.course_input = QDoubleSpinBox()
        self.course_input.setRange(0, 359)
        self.course_input.setValue(default_course)
        self.course_input.setDecimals(0)
        self.course_input.setSuffix("°")
        form_layout.addRow("Course:", self.course_input)
        
        self.speed_input = QDoubleSpinBox()
        self.speed_input.setDecimals(1)
        
        if self.use_knots:
            speed_in_knots = default_speed / KNOTS_TO_MS
            self.speed_input.setValue(speed_in_knots)
            self.speed_input.setRange(0, 50)
            self.speed_input.setSuffix(" kn")
        else:
            self.speed_input.setValue(default_speed)
            self.speed_input.setRange(0, 25)
            self.speed_input.setSuffix(" m/s")
        
        form_layout.addRow("Speed:", self.speed_input)
        
        layout.addLayout(form_layout)
        
        button_layout = QHBoxLayout()
        
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        button_layout.addWidget(btn_ok)
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancel)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def get_values(self):
        name = self.name_input.text().strip()
        if not name:
            name = None
        
        course = self.course_input.value()
        speed_value = self.speed_input.value()
        
        if self.use_knots:
            speed_ms = speed_value * KNOTS_TO_MS
        else:
            speed_ms = speed_value
        
        return name, course, speed_ms


class ControlDialog(QDialog):
    """Диалог управления судном с автообновлением информации"""
    
    def __init__(self, ship, parent=None, use_knots=True):
        super().__init__(parent)
        self.ship = ship
        self.use_knots = use_knots
        
        self.setWindowTitle(f"Control: {ship.name}")
        self.setFixedSize(450, 450)
        
        layout = QVBoxLayout()
        
        # === Блок информации о судне (обновляется в реальном времени) ===
        self.info_group = QGroupBox("Vessel Information (live)")
        self.info_layout = QFormLayout()
        
        self.name_label = QLabel(ship.name)
        self.position_label = QLabel(f"X={ship.x:.0f} m, Y={ship.y:.0f} m")
        
        if self.use_knots:
            speed_kn = ship.u / KNOTS_TO_MS
            self.speed_label = QLabel(f"{speed_kn:.1f} kn ({ship.u:.2f} m/s)")
        else:
            self.speed_label = QLabel(f"{ship.u:.2f} m/s")
        
        self.course_label = QLabel(f"{ship.get_heading_deg():.1f}°")
        self.rot_label = QLabel(f"{ship.get_rot():+.1f}°/min" if hasattr(ship, 'get_rot') else "N/A")
        self.info_layout.addRow("ROT:", self.rot_label)
        
        self.info_layout.addRow("Name:", self.name_label)
        self.info_layout.addRow("Position:", self.position_label)
        self.info_layout.addRow("Speed:", self.speed_label)
        self.info_layout.addRow("Course:", self.course_label)
        
        self.info_group.setLayout(self.info_layout)
        layout.addWidget(self.info_group)
        
        # === Управление с ползунками ===
        control_group = QGroupBox("Manual Control (set desired values)")
        control_layout = QVBoxLayout()
        
        # --- РУЛЬ ---
        rudder_layout = QVBoxLayout()
        
        # Метка "текущее значение"
        self.rudder_current_label = QLabel(f"Current: {ship.rudder_cmd:.0f}°")
        self.rudder_current_label.setStyleSheet("color: gray; font-style: italic;")
        rudder_layout.addWidget(self.rudder_current_label)
        
        # Ползунок + значение
        rudder_row = QHBoxLayout()
        rudder_label = QLabel("Desired rudder:")
        rudder_label.setFixedWidth(120)
        
        self.rudder_slider = QSlider(Qt.Horizontal)
        self.rudder_slider.setRange(-35, 35)
        self.rudder_slider.setValue(int(ship.rudder_cmd))
        self.rudder_slider.setTickPosition(QSlider.TicksBelow)
        self.rudder_slider.setTickInterval(5)
        
        self.rudder_value_label = QLabel(f"{ship.rudder_cmd:.0f}°")
        self.rudder_value_label.setFixedWidth(50)
        self.rudder_value_label.setAlignment(Qt.AlignCenter)
        self.rudder_value_label.setStyleSheet("font-weight: bold;")
        
        self.rudder_slider.valueChanged.connect(self.update_rudder_label)
        
        rudder_row.addWidget(rudder_label)
        rudder_row.addWidget(self.rudder_slider)
        rudder_row.addWidget(self.rudder_value_label)
        rudder_layout.addLayout(rudder_row)
        
        control_layout.addLayout(rudder_layout)
        
        # --- RPM ---
        rpm_layout = QVBoxLayout()
        
        # Метка "текущее значение"
        self.rpm_current_label = QLabel(f"Current: {ship.rpm_cmd:.0f}%")
        self.rpm_current_label.setStyleSheet("color: gray; font-style: italic;")
        rpm_layout.addWidget(self.rpm_current_label)
        
        # Ползунок + значение
        rpm_row = QHBoxLayout()
        rpm_label = QLabel("Desired RPM:")
        rpm_label.setFixedWidth(120)
        
        self.rpm_slider = QSlider(Qt.Horizontal)
        self.rpm_slider.setRange(0, 100)
        self.rpm_slider.setValue(int(ship.rpm_cmd))
        self.rpm_slider.setTickPosition(QSlider.TicksBelow)
        self.rpm_slider.setTickInterval(10)
        
        self.rpm_value_label = QLabel(f"{ship.rpm_cmd:.0f}%")
        self.rpm_value_label.setFixedWidth(50)
        self.rpm_value_label.setAlignment(Qt.AlignCenter)
        self.rpm_value_label.setStyleSheet("font-weight: bold;")
        
        self.rpm_slider.valueChanged.connect(self.update_rpm_label)
        
        rpm_row.addWidget(rpm_label)
        rpm_row.addWidget(self.rpm_slider)
        rpm_row.addWidget(self.rpm_value_label)
        rpm_layout.addLayout(rpm_row)
        
        control_layout.addLayout(rpm_layout)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
        # === LLM управление ===
        llm_group = QGroupBox("AI Control")
        llm_layout = QVBoxLayout()
        
        self.llm_checkbox = QCheckBox("Enable LLM control")
        self.llm_checkbox.setChecked(ship.llm_controlled)
        llm_layout.addWidget(self.llm_checkbox)
        
        llm_group.setLayout(llm_layout)
        layout.addWidget(llm_group)
        
        # Кнопки
        button_layout = QHBoxLayout()
        
        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self.apply_changes)
        button_layout.addWidget(btn_apply)
        
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        button_layout.addWidget(btn_close)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
        
        # === ТАЙМЕР ОБНОВЛЕНИЯ ИНФОРМАЦИИ ===
        # Обновляет только метки "Current:" и блок информации, НЕ ползунки
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_ship_info)
        self.update_timer.start(500)
    
    def refresh_ship_info(self):
        """Обновить только информационные метки, НЕ ползунки"""
        # Позиция
        self.position_label.setText(f"X={self.ship.x:.0f} m, Y={self.ship.y:.0f} m")
        
        # Скорость
        if self.use_knots:
            speed_kn = self.ship.u / KNOTS_TO_MS
            self.speed_label.setText(f"{speed_kn:.1f} kn ({self.ship.u:.2f} m/s)")
        else:
            self.speed_label.setText(f"{self.ship.u:.2f} m/s")
        
        # Курс
        self.course_label.setText(f"{self.ship.get_heading_deg():.1f}°")
        self.rot_label.setText(f"{self.ship.get_rot():+.1f}°/min")
        
        # Обновляем только метки "Current:" рядом с ползунками
        self.rudder_current_label.setText(f"Current: {self.ship.rudder_cmd:.0f}°")
        self.rpm_current_label.setText(f"Current: {self.ship.rpm_cmd:.0f}%")
        
        # ПОЛЗУНКИ НЕ ОБНОВЛЯЮТСЯ — они представляют намерение пользователя
    
    def update_rudder_label(self, value):
        self.rudder_value_label.setText(f"{value}°")
    
    def update_rpm_label(self, value):
        self.rpm_value_label.setText(f"{value}%")
    
    def apply_changes(self):
        """Применить значения ползунков к судну"""
        self.ship.rudder_cmd = float(self.rudder_slider.value())
        self.ship.rpm_cmd = float(self.rpm_slider.value())
        self.ship.llm_controlled = self.llm_checkbox.isChecked()
        
        # После применения синхронизируем метки "Current:" с ползунками
        self.rudder_current_label.setText(f"Current: {self.rudder_slider.value():.0f}°")
        self.rpm_current_label.setText(f"Current: {self.rpm_slider.value():.0f}%")
    
    def closeEvent(self, event):
        self.update_timer.stop()
        super().closeEvent(event)
        """Остановить таймер при закрытии окна"""
        self.update_timer.stop()
        super().closeEvent(event)


class LLMSettingsDialog(QDialog):
    """Диалог настроек LLM"""
    
    def __init__(self, current_provider, api_keys, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LLM Settings")
        self.setFixedSize(500, 300)
        
        from llm_controller import LLMCoordinator
        
        layout = QVBoxLayout()
        
        provider_group = QGroupBox("Provider")
        provider_layout = QFormLayout()
        
        self.provider_combo = QComboBox()
        for key, config in LLMCoordinator.PROVIDERS.items():
            self.provider_combo.addItem(config['name'], key)
        
        for i in range(self.provider_combo.count()):
            if self.provider_combo.itemData(i) == current_provider:
                self.provider_combo.setCurrentIndex(i)
                break
        
        provider_layout.addRow("Select provider:", self.provider_combo)
        provider_group.setLayout(provider_layout)
        layout.addWidget(provider_group)
        
        key_group = QGroupBox("API Key")
        key_layout = QFormLayout()
        
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        
        current_key = api_keys.get(current_provider, '')
        self.key_input.setText(current_key)
        self.key_input.setPlaceholderText("Enter API key (if required)")
        
        key_layout.addRow("API Key:", self.key_input)
        key_group.setLayout(key_layout)
        layout.addWidget(key_group)
        
        button_layout = QHBoxLayout()
        
        btn_ok = QPushButton("OK")
        btn_ok.clicked.connect(self.accept)
        button_layout.addWidget(btn_ok)
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        button_layout.addWidget(btn_cancel)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def get_results(self):
        provider = self.provider_combo.currentData()
        key = self.key_input.text().strip()
        
        api_keys = {provider: key} if key else {}
        
        return provider, api_keys
