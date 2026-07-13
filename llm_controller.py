"""
llm_decisions_window.py
GUI that renders and updates individual LLM decision making processes cleanly.
"""
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QTableWidget, QTableWidgetItem,
                             QHeaderView, QScrollArea)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont  


class LLMDecisionsWindow(QMainWindow):
    """LLM Window displaying decentralized decisions per vessel"""
    
    def __init__(self, ships_ref, llm_coordinator_ref=None):
        super().__init__()
        self.ships_ref = ships_ref
        self.llm_coordinator_ref = llm_coordinator_ref
        
        self.setWindowTitle("LLM Decisions Monitor")
        self.resize(900, 600)
        
        self.init_ui()
        
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_table)
        self.timer.start(1000)  # Update every second
        
        self.update_table()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        title_label = QLabel("LLM Control Decisions & Reasoning (Independent Perspectives)")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px; background-color: #e3f2fd;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Vessel",
            "Status",
            "Rudder (°)",
            "RPM (%)",
            "LLM Reasoning"
        ])
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        
        scroll.setWidget(self.table)
        layout.addWidget(scroll)
        
        btn_close = QPushButton("Close window")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close)
    
    def update_table(self):
        """Обновить таблицу решений LLM"""
        ships = self.ships_ref() if callable(self.ships_ref) else self.ships_ref
        
        if not ships:
            self.table.setRowCount(0)
            return
        
        self.table.setRowCount(0)
        row = 0
        
        for ship in ships:
            if not ship.llm_controlled:
                continue
            
            self.table.insertRow(row)
            
            # 1. Имя судна
            name_item = QTableWidgetItem(ship.name)
            name_item.setFont(QFont("Arial", 10, QFont.Bold))
            self.table.setItem(row, 0, name_item)

            # 2. Извлечение обоснования (Cleaned layout without legacy duplicate)
            reasoning = ""
            if hasattr(ship, 'llm_decision') and ship.llm_decision:
                reasoning = ship.llm_decision.get('reasoning', '')
            
            if not reasoning and hasattr(ship, 'llm_reasoning'):
                reasoning = ship.llm_reasoning
            
            if not reasoning:
                if ship.in_maneuver:
                    if ship.rudder_cmd > 0:
                        reasoning = f"Turning starboard {ship.rudder_cmd:.0f}° to avoid collision"
                    elif ship.rudder_cmd < 0:
                        reasoning = f"Turning port {ship.rudder_cmd:.0f}° to avoid collision"
                    else:
                        reasoning = "Reducing speed for safety"
                else:
                    reasoning = "Maintaining course and speed - no collision risk"

            # 3. Статус обработки удержания/возврата курса
            if ship.in_maneuver:
                if "Deterministic" in reasoning or "RETURN_TO_COURSE" in reasoning:
                    status = "RETURN TO COURSE"
                    status_color = QColor(135, 206, 250)
                else:
                    status = "MANEUVERING"
                    status_color = QColor(255, 200, 0)
            else:
                status = "ON COURSE"
                status_color = QColor(144, 238, 144)
            
            status_item = QTableWidgetItem(status)
            status_item.setBackground(status_color)
            self.table.setItem(row, 1, status_item)
            
            # 4. Вывод значений руля
            rudder_item = QTableWidgetItem(f"{ship.rudder_cmd:+.1f}°")
            if abs(ship.rudder_cmd) > 15:
                rudder_item.setBackground(QColor(255, 150, 150))
            self.table.setItem(row, 2, rudder_item)
            
            # 5. Вывод RPM
            rpm_item = QTableWidgetItem(f"{ship.rpm_cmd:.0f}%")
            if ship.rpm_cmd < 40 or ship.rpm_cmd > 60:
                rpm_item.setBackground(QColor(255, 200, 150))
            self.table.setItem(row, 3, rpm_item)
            
            # 6. Вставка очищенной строки обоснования
            reasoning_item = QTableWidgetItem(reasoning)
            self.table.setItem(row, 4, reasoning_item)
            
            row += 1
        
        if row == 0:
            self.table.setRowCount(1)
            no_data_item = QTableWidgetItem("No vessels under LLM control")
            no_data_item.setForeground(QColor(128, 128, 128))
            self.table.setItem(0, 0, no_data_item)
            self.table.setSpan(0, 0, 1, 5)