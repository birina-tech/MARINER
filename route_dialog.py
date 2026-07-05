"""
route_dialog.py
Немодальное диалоговое окно для создания и редактирования маршрута.
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QTableWidget, QTableWidgetItem,
                             QComboBox, QMessageBox, QHeaderView, QGroupBox,
                             QFormLayout, QAbstractItemView)
from PyQt5.QtCore import Qt, pyqtSignal


class RouteDialog(QDialog):
    """Немодальный диалог управления маршрутом"""

    route_updated = pyqtSignal()

    def __init__(self, route, ships, parent=None, is_editing=False):
        super().__init__(parent)
        self.route = route
        self.ships = ships
        self.is_editing = is_editing

        mode_text = "Edit" if is_editing else "Create"
        self.setWindowTitle(f"Route: {route.name} [{mode_text} Mode]")
        self.setFixedSize(850, 550)

        # Немодальное окно
        self.setModal(False)

        self.init_ui()
        self.update_table()

    def init_ui(self):
        layout = QVBoxLayout()

        # Заголовок
        title_label = QLabel(f"Route: {self.route.name}")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        # Подсказка
        if self.is_editing:
            hint_text = " LMB drag to move points | RMB on point for menu"
        else:
            hint_text = "💡 Click RMB on the canvas to add waypoints"
        hint_label = QLabel(hint_text)
        hint_label.setStyleSheet("font-size: 11px; color: #555; padding: 5px;")
        hint_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint_label)

        # Таблица точек маршрута
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Point #", "Distance (m)", "Course (°)",
            "X (m)", "Y (m)", "Assigned Vessel"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        # Выбор судна
        ship_group = QGroupBox("Assign Vessel to Route")
        ship_layout = QFormLayout()

        self.ship_combo = QComboBox()
        self.ship_combo.addItem("-- No vessel --", None)
        for ship in self.ships:
            self.ship_combo.addItem(ship.name, ship)

        if self.route.assigned_ship:
            for i in range(self.ship_combo.count()):
                if self.ship_combo.itemData(i) == self.route.assigned_ship:
                    self.ship_combo.setCurrentIndex(i)
                    break

        ship_layout.addRow("Select vessel:", self.ship_combo)
        ship_group.setLayout(ship_layout)
        layout.addWidget(ship_group)

        # Кнопки
        buttons_layout = QHBoxLayout()

        btn_assign = QPushButton("Assign Vessel")
        btn_assign.setStyleSheet("QPushButton { background-color: #90EE90; font-weight: bold; }")
        btn_assign.clicked.connect(self.assign_ship)
        buttons_layout.addWidget(btn_assign)

        btn_remove_selected = QPushButton("Remove Selected Point")
        btn_remove_selected.clicked.connect(self.remove_selected_point)
        buttons_layout.addWidget(btn_remove_selected)

        btn_remove_last = QPushButton("Remove Last Point")
        btn_remove_last.clicked.connect(self.remove_last_point)
        buttons_layout.addWidget(btn_remove_last)

        if self.is_editing:
            btn_save = QPushButton("💾 Save Changes")
            btn_save.setStyleSheet("QPushButton { background-color: #87CEEB; font-weight: bold; }")
            btn_save.clicked.connect(self.save_changes)
            buttons_layout.addWidget(btn_save)
        else:
            btn_finish = QPushButton("Finish Route")
            btn_finish.setStyleSheet("QPushButton { background-color: #87CEEB; font-weight: bold; }")
            btn_finish.clicked.connect(self.finish_route)
            buttons_layout.addWidget(btn_finish)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        buttons_layout.addWidget(btn_close)

        layout.addLayout(buttons_layout)
        self.setLayout(layout)

    def update_table(self):
        """Обновить таблицу точек маршрута"""
        self.table.setRowCount(0)

        for point in self.route.points:
            row = self.table.rowCount()
            self.table.insertRow(row)

            self.table.setItem(row, 0, QTableWidgetItem(str(point.point_number)))
            self.table.setItem(row, 1, QTableWidgetItem(f"{point.distance_to_next:.0f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{point.course_to_next:.1f}°"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{point.x:.0f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{point.y:.0f}"))

            ship_name = self.route.assigned_ship.name if self.route.assigned_ship else "None"
            self.table.setItem(row, 5, QTableWidgetItem(ship_name))

        if self.table.rowCount() > 0:
            self.table.scrollToBottom()

    def assign_ship(self):
        """Назначить судно на маршрут"""
        ship = self.ship_combo.currentData()
        self.route.assigned_ship = ship
        
        if ship:
            from autopilot import RouteAutopilot
            ship.assigned_route = self.route
            ship.autopilot = RouteAutopilot(ship, self.route)
            ship.autopilot_enabled = True
            # Включаем LLM для координации с авторулевым
            ship.llm_controlled = True
            print(f"Autopilot + LLM enabled for {ship.name}")
        else:
            if self.route.assigned_ship:
                self.route.assigned_ship.autopilot_enabled = False
                self.route.assigned_ship.autopilot = None
                self.route.assigned_ship.assigned_route = None
                # LLM остаётся включённым, если был включён вручную
        
        self.update_table()
        
        if ship:
            QMessageBox.information(
                self, "Vessel Assigned",
                f"Vessel {ship.name} assigned to route {self.route.name}\n"
                f"Autopilot ENABLED\n"
                f"LLM coordination ENABLED"
            )
        else:
            QMessageBox.information(
                self, "Vessel Removed",
                f"Vessel removed from route {self.route.name}"
            )

    def remove_selected_point(self):
        """Удалить выбранную в таблице точку"""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(
                self, "No Selection",
                "Please select a point in the table first."
            )
            return

        # Собираем индексы (в обратном порядке чтобы не сбить нумерацию)
        indices = sorted([row.row() for row in selected_rows], reverse=True)

        for idx in indices:
            if 0 <= idx < len(self.route.points):
                self.route.remove_point(idx)

        self.update_table()
        self._update_canvas()

    def remove_last_point(self):
        """Удалить последнюю точку маршрута"""
        if self.route.points:
            self.route.remove_last_point()
            self.update_table()
            self._update_canvas()

    def finish_route(self):
        """Завершить создание маршрута"""
        if len(self.route.points) < 2:
            QMessageBox.warning(
                self, "Not enough points",
                "Route must have at least 2 points!"
            )
            return

        QMessageBox.information(
            self, "Route Created",
            f"Route {self.route.name} created with {len(self.route.points)} points\n"
            f"Total distance: {self.route.get_total_distance():.0f} m"
        )
        self.close()

    def save_changes(self):
        """Сохранить изменения в режиме редактирования"""
        if len(self.route.points) < 2:
            QMessageBox.warning(
                self, "Not enough points",
                "Route must have at least 2 points!"
            )
            return

        QMessageBox.information(
            self, "Changes Saved",
            f"Route {self.route.name} updated\n"
            f"Points: {len(self.route.points)}\n"
            f"Total distance: {self.route.get_total_distance():.0f} m"
        )
        self._update_canvas()

    def refresh_from_route(self):
        """Обновить таблицу из данных маршрута"""
        self.update_table()
        self._update_canvas()

    def _update_canvas(self):
        """Обновить canvas через родительское окно"""
        parent = self.parent()
        if parent and hasattr(parent, 'canvas'):
            parent.canvas.update_plot(
                parent.ships, parent.running, parent.simulation_time,
                use_miles=parent.use_miles,
                use_knots=parent.use_knots,
                predicted_tracks=parent.predicted_tracks,
                routes=parent.routes
            )

    def closeEvent(self, event):
        """Обработка закрытия окна"""
        self.route_updated.emit()
        super().closeEvent(event)