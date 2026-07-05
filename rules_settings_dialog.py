"""
rules_settings_dialog.py
Диалоговое окно настройки параметров МППСС
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QDoubleSpinBox, QGroupBox, QFormLayout,
                             QTabWidget, QMessageBox, QDialogButtonBox)
from PyQt5.QtCore import Qt
from rules_settings import get_rules_settings, DEFAULT_SETTINGS

# Константы конвертации
METERS_PER_NAUTICAL_MILE = 1852.0


class RulesSettingsDialog(QDialog):
    """Диалог настройки параметров МППСС"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = get_rules_settings()
        
        # Если настройки всё ещё None, создаём дефолтные
        if self.settings is None:
            from rules_settings import RulesSettings
            self.settings = RulesSettings()
        
        self.setWindowTitle("COLREGs Rules Settings")
        self.setFixedSize(600, 500)
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Вкладки для разных правил
        tabs = QTabWidget()
        
        # Вкладка Rule 13
        tab_13 = self._create_rule_13_tab()
        tabs.addTab(tab_13, "Rule 13 (Overtaking)")
        
        # Вкладка Rule 14
        tab_14 = self._create_rule_14_tab()
        tabs.addTab(tab_14, "Rule 14 (Head-on)")
        
        # Вкладка Rule 15
        tab_15 = self._create_rule_15_tab()
        tabs.addTab(tab_15, "Rule 15 (Crossing)")
        
        # Вкладка Rule 17.2
        tab_17 = self._create_rule_17_tab()
        tabs.addTab(tab_17, "Rule 17.2 (Emergency)")
        
        # Вкладка General
        tab_general = self._create_general_tab()
        tabs.addTab(tab_general, "General")
        
        layout.addWidget(tabs)
        
        # Кнопки
        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.reset_to_defaults)
        
        layout.addWidget(button_box)
        self.setLayout(layout)
    
    def _create_spinbox(self, value, min_val, max_val, decimals=1, suffix=""):
        """Создать QDoubleSpinBox"""
        sb = QDoubleSpinBox()
        sb.setRange(min_val, max_val)
        sb.setDecimals(decimals)
        sb.setValue(value if value is not None else min_val)
        if suffix:
            sb.setSuffix(f" {suffix}")
        return sb
    
    def _create_rule_13_tab(self):
        """Вкладка Rule 13 - Overtaking"""
        group = QGroupBox("Overtaking Parameters")
        form = QFormLayout()
        
        # Получаем настройки с проверкой
        rule_13_settings = self.settings.get("rule_13_overtaking", {})
        if rule_13_settings is None:
            rule_13_settings = {}
        
        self.sb_13_bearing = self._create_spinbox(
            rule_13_settings.get("bearing_threshold_deg", 112.5), 90, 179, 1, "deg"
        )
        form.addRow("Bearing threshold (from bow):", self.sb_13_bearing)
        
        self.sb_13_distance = self._create_spinbox(
            rule_13_settings.get("max_distance_m", 5556) / METERS_PER_NAUTICAL_MILE,
            0.5, 10, 2, "nm"
        )
        form.addRow("Max detection distance:", self.sb_13_distance)
        
        self.sb_13_speed = self._create_spinbox(
            rule_13_settings.get("speed_ratio_threshold", 1.0), 0.5, 3.0, 2, "ratio"
        )
        form.addRow("Speed ratio threshold:", self.sb_13_speed)
        
        group.setLayout(form)
        return group
    
    def _create_rule_14_tab(self):
        """Вкладка Rule 14 - Head-on"""
        group = QGroupBox("Head-on Parameters")
        form = QFormLayout()
        
        rule_14_settings = self.settings.get("rule_14_head_on", {})
        if rule_14_settings is None:
            rule_14_settings = {}
        
        self.sb_14_bearing = self._create_spinbox(
            rule_14_settings.get("bearing_threshold_deg", 5.0), 1, 30, 1, "deg"
        )
        form.addRow("Bearing threshold (± from bow):", self.sb_14_bearing)
        
        self.sb_14_distance = self._create_spinbox(
            rule_14_settings.get("max_distance_m", 5556) / METERS_PER_NAUTICAL_MILE,
            0.5, 10, 2, "nm"
        )
        form.addRow("Max detection distance:", self.sb_14_distance)
        
        group.setLayout(form)
        return group
    
    def _create_rule_15_tab(self):
        """Вкладка Rule 15 - Crossing"""
        group = QGroupBox("Crossing Parameters")
        form = QFormLayout()
        
        rule_15_settings = self.settings.get("rule_15_crossing", {})
        if rule_15_settings is None:
            rule_15_settings = {}
        
        self.sb_15_distance = self._create_spinbox(
            rule_15_settings.get("max_distance_m", 5556) / METERS_PER_NAUTICAL_MILE,
            0.5, 10, 2, "nm"
        )
        form.addRow("Max detection distance:", self.sb_15_distance)
        
        group.setLayout(form)
        return group
    
    def _create_rule_17_tab(self):
        """Вкладка Rule 17.2 - Emergency"""
        group = QGroupBox("Emergency / Critical Convergence Parameters")
        form = QFormLayout()
        
        rule_17_settings = self.settings.get("rule_17_2_emergency", {})
        if rule_17_settings is None:
            rule_17_settings = {}
        
        self.sb_17_cpa = self._create_spinbox(
            rule_17_settings.get("critical_cpa_m", 926) / METERS_PER_NAUTICAL_MILE,
            0.1, 5, 2, "nm"
        )
        form.addRow("Critical CPA:", self.sb_17_cpa)
        
        self.sb_17_tcpa = self._create_spinbox(
            rule_17_settings.get("critical_tcpa_s", 300) / 60,
            1, 30, 1, "min"
        )
        form.addRow("Critical TCPA:", self.sb_17_tcpa)
        
        self.sb_17_distance = self._create_spinbox(
            rule_17_settings.get("critical_distance_m", 1852) / METERS_PER_NAUTICAL_MILE,
            0.1, 5, 2, "nm"
        )
        form.addRow("Critical distance:", self.sb_17_distance)
        
        group.setLayout(form)
        return group
    
    def _create_general_tab(self):
        """Вкладка General - общие параметры"""
        group = QGroupBox("General Risk Thresholds")
        form = QFormLayout()
        
        general_settings = self.settings.get("general", {})
        if general_settings is None:
            general_settings = {}
        
        self.sb_gen_cpa = self._create_spinbox(
            general_settings.get("min_cpa_for_risk_m", 1852) / METERS_PER_NAUTICAL_MILE,
            0.1, 10, 2, "nm"
        )
        form.addRow("Min CPA for risk:", self.sb_gen_cpa)
        
        self.sb_gen_tcpa = self._create_spinbox(
            general_settings.get("min_tcpa_for_risk_s", 600) / 60,
            1, 60, 1, "min"
        )
        form.addRow("Min TCPA for risk:", self.sb_gen_tcpa)
        
        self.sb_gen_detection = self._create_spinbox(
            general_settings.get("detection_range_m", 9260) / METERS_PER_NAUTICAL_MILE,
            1, 20, 2, "nm"
        )
        form.addRow("Detection range:", self.sb_gen_detection)
        
        group.setLayout(form)
        return group
    
    def accept(self):
        """Сохранить настройки при нажатии OK"""
        # Rule 13
        self.settings.set("rule_13_overtaking", "bearing_threshold_deg",
                         self.sb_13_bearing.value())
        self.settings.set("rule_13_overtaking", "max_distance_m",
                         self.sb_13_distance.value() * METERS_PER_NAUTICAL_MILE)
        self.settings.set("rule_13_overtaking", "speed_ratio_threshold",
                         self.sb_13_speed.value())
        
        # Rule 14
        self.settings.set("rule_14_head_on", "bearing_threshold_deg",
                         self.sb_14_bearing.value())
        self.settings.set("rule_14_head_on", "max_distance_m",
                         self.sb_14_distance.value() * METERS_PER_NAUTICAL_MILE)
        
        # Rule 15
        self.settings.set("rule_15_crossing", "max_distance_m",
                         self.sb_15_distance.value() * METERS_PER_NAUTICAL_MILE)
        
        # Rule 17.2
        self.settings.set("rule_17_2_emergency", "critical_cpa_m",
                         self.sb_17_cpa.value() * METERS_PER_NAUTICAL_MILE)
        self.settings.set("rule_17_2_emergency", "critical_tcpa_s",
                         self.sb_17_tcpa.value() * 60)
        self.settings.set("rule_17_2_emergency", "critical_distance_m",
                         self.sb_17_distance.value() * METERS_PER_NAUTICAL_MILE)
        
        # General
        self.settings.set("general", "min_cpa_for_risk_m",
                         self.sb_gen_cpa.value() * METERS_PER_NAUTICAL_MILE)
        self.settings.set("general", "min_tcpa_for_risk_s",
                         self.sb_gen_tcpa.value() * 60)
        self.settings.set("general", "detection_range_m",
                         self.sb_gen_detection.value() * METERS_PER_NAUTICAL_MILE)
        
        # Сохранить в файл
        if self.settings.save():
            QMessageBox.information(self, "Settings Saved",
                                   "COLREGs settings saved successfully.")
        else:
            QMessageBox.warning(self, "Save Error",
                               "Failed to save settings to file.")
        
        super().accept()
    
    def reset_to_defaults(self):
        """Сбросить настройки к значениям по умолчанию"""
        reply = QMessageBox.question(
            self, "Reset to Defaults",
            "Are you sure you want to reset all settings to default values?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.settings.reset_to_defaults()
            QMessageBox.information(self, "Reset Complete",
                                   "Settings reset to default values.")
            self.close()


def launch_rules_settings(parent=None):
    """Запустить диалог настроек"""
    dialog = RulesSettingsDialog(parent)
    dialog.exec_()