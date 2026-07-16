import sys
import os
import json
import csv
from datetime import datetime
import numpy as np
import warnings
from autopilot import RouteAutopilot
from autopilot_debug_dialog import AutopilotDebugDialog
warnings.filterwarnings("ignore")
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QStatusBar,
                             QMessageBox, QInputDialog, QMenu, QAction, QDialog)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QSizePolicy
from ship import Ship
from canvas import ShipCanvas
from dialogs import AddShipDialog, ControlDialog, LLMSettingsDialog
from llm_worker import LLMWorker
from collision_analyzer import launch_collision_analysis, CollisionAnalyzer
from llm_controller import LLMCoordinator
from llm_decisions_window import launch_llm_decisions_window
from safe_passing_dialog import launch_safe_passing_calculator
from units import format_speed, format_distance
from route import Route, RoutePoint
from route_dialog import RouteDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('MASS Sim')
        self.resize(1400, 900)
        self.ships = []
        self.running = False
        self.dt = 1.0
        self.simulation_time = 0.0
        self.analysis_window = None
        self.llm_decisions_window = None
        self.llm_coordinator = None
        self.current_provider = 'ollama'
        self.api_keys = {}
        self.llm_status_text = "Not tested"
        self.llm_update_interval = 3.0
        self.last_llm_update = 0.0
        self.recording = False
        self.rec_session_path = None
        self.log_files = {}
        self.tasks_dir = os.path.join(os.getcwd(), "Tasks")
        self.llm_workers = {}
        self.llm_pending = False
        self.move_mode = False
        self.move_ship = None
        self.predicted_tracks = {}
        self.routes = []
        self.current_route = None
        self.route_mode = False
        self.editing_route = None
        self.route_dialog = None
        self.autopilot_debug_dialog = None
        # Units
        self.use_miles = True
        self.use_knots = True

        self.selected_ego_ship = None  # Tracks whose perspective we are viewing

        self.init_menu()
        self.init_ui()
        self.timer = QTimer()
        self.timer.timeout.connect(self.simulation_step)
        self.last_history_record = 0.0  # Tracks when we last saved waypoints

    def closeEvent(self, event):
        """Intercepts the window close event to clean up threads gracefully."""
        self.statusBar().showMessage("Shutting down workers, please wait...")
        self.stop_simulation()
        event.accept()

    def set_predicted_tracks(self, tracks_dict):
        """Set up routes for GUI"""
        self.predicted_tracks = tracks_dict
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )
        self.statusBar().showMessage(
            f"Predicted tracks displayed for {len(tracks_dict)} vessels"
        )

    def clear_predicted_tracks(self):
        """Remove routes from GUI"""
        self.predicted_tracks = {}
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )
        self.statusBar().showMessage("Predicted tracks cleared")

    def init_menu(self):
        menu_bar = self.menuBar()

        view_menu = menu_bar.addMenu("View")
        self.action_vector_len = view_menu.addAction("Vector length (minutes)")
        self.action_vector_len.triggered.connect(self.set_vector_length)
        self.action_track_len = view_menu.addAction("Track length (meters)")
        self.action_track_len.triggered.connect(self.set_track_length)
        view_menu.addSeparator()
        self.action_sim_speed = view_menu.addAction("Simulation speed...")
        self.action_sim_speed.triggered.connect(self.set_simulation_speed)
        view_menu.addSeparator()
        self.action_reset_view = view_menu.addAction("Reset view settings")
        self.action_reset_view.triggered.connect(self.reset_view_settings)

        # Units Menu
        units_menu = menu_bar.addMenu("Units")
        self.action_toggle_distance = units_menu.addAction("📏 Distance: Nautical Miles")
        self.action_toggle_distance.triggered.connect(self.toggle_distance_units)
        self.action_toggle_speed = units_menu.addAction(" Speed: Knots")
        self.action_toggle_speed.triggered.connect(self.toggle_speed_units)

        llm_menu = menu_bar.addMenu("LLM")
        self.action_llm_settings = llm_menu.addAction("⚙️ LLM Settings...")
        self.action_llm_settings.triggered.connect(self.open_llm_settings)
        self.action_llm_test = llm_menu.addAction("🔍 Test connection")
        self.action_llm_test.triggered.connect(self.test_llm_connection)
        llm_menu.addSeparator()
        self.action_llm_interval = llm_menu.addAction(
            f"⏱ Query interval: {self.llm_update_interval:.1f}s")
        self.action_llm_interval.triggered.connect(self.set_llm_interval)
        llm_menu.addSeparator()
        self.action_llm_status = llm_menu.addAction(f"📊 Status: {self.llm_status_text}")
        self.action_llm_status.setEnabled(False) 
        llm_menu.addSeparator()
        self.action_llm_toggle = llm_menu.addAction("🤖 Enable LLM for all vessels")
        self.action_llm_toggle.triggered.connect(self.toggle_llm_for_all)

        tasks_menu = menu_bar.addMenu("Tasks")
        self.action_save_task = tasks_menu.addAction("💾 Save Task")
        self.action_save_task.triggered.connect(self.save_task)
        self.action_load_task = tasks_menu.addAction(" Load Task")
        self.action_load_task.triggered.connect(self.load_task)

        help_menu = menu_bar.addMenu("Help")
        self.action_help = help_menu.addAction("📖 User guide")
        self.action_help.triggered.connect(self.show_help)
        self.action_api_help = help_menu.addAction(" Where to get API keys?")
        self.action_api_help.triggered.connect(self.show_api_help)
        help_menu.addSeparator()
        self.action_about = help_menu.addAction("ℹ️ About")
        self.action_about.triggered.connect(self.show_about)

    def open_rules_settings(self):
        """Open settings windows for COLREG thresholds"""
        from rules_settings_dialog import launch_rules_settings
        launch_rules_settings(self)

    def toggle_distance_units(self):
        self.use_miles = not self.use_miles
        unit_name = "Nautical Miles" if self.use_miles else "Meters"
        self.action_toggle_distance.setText(f"📏 Distance: {unit_name}")
        self.statusBar().showMessage(f"Distance units: {unit_name}")
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    def toggle_speed_units(self):
        self.use_knots = not self.use_knots
        unit_name = "Knots" if self.use_knots else "m/s"
        self.action_toggle_speed.setText(f"⚡ Speed: {unit_name}")
        self.statusBar().showMessage(f"Speed units: {unit_name}")
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    def set_llm_interval(self):
        val, ok = QInputDialog.getDouble(
            self, "LLM Query Interval",
            "Interval between LLM queries (seconds):",
            self.llm_update_interval, 1.0, 60.0, 1)
        if ok:
            self.llm_update_interval = val
            self.action_llm_interval.setText(f" Query interval: {val:.1f}s")
            self.statusBar().showMessage(f"LLM query interval set to {val:.1f}s")

    def set_simulation_speed(self):
        current = self.dt
        val, ok = QInputDialog.getDouble(
            self, "Simulation Speed",
            "Simulation speed multiplier (dt per step, seconds):",
            current, 0.1, 10.0, 1)
        if ok:
            self.dt = val
            self.statusBar().showMessage(f"Simulation speed set: dt={val:.2f}s")

    def open_llm_settings(self):
        dialog = LLMSettingsDialog(self.current_provider, self.api_keys, self)
        if dialog.exec_() == QDialog.Accepted:
            new_provider, new_keys = dialog.get_results()
            self.current_provider = new_provider
            self.api_keys = new_keys
            self.llm_coordinator = None
            self.llm_status_text = "Settings changed"
            self.update_llm_status_display()
            config = LLMCoordinator.PROVIDERS[self.current_provider]
            self.statusBar().showMessage(f"LLM settings updated: {config['name']}")

    def test_llm_connection(self):
        coordinator = self.get_or_create_coordinator()
        self.statusBar().showMessage(
            f"Testing connection to {coordinator.PROVIDERS[self.current_provider]['name']}...")
        QApplication.processEvents()
        success, message = coordinator.test_connection()
        if success:
            self.llm_status_text = f"OK: {coordinator.PROVIDERS[self.current_provider]['name']}"
            QMessageBox.information(
                self, "Connection successful",
                f"OK: {message}\n"
                f"Provider: {coordinator.PROVIDERS[self.current_provider]['name']}\n"
                f"Model: {coordinator.model}")
        else:
            self.llm_status_text = f"Error: {message[:50]}"
            QMessageBox.warning(
                self, "Connection error",
                f"Error: {message}\n"
                f"Provider: {coordinator.PROVIDERS[self.current_provider]['name']}")
        self.update_llm_status_display()
        self.statusBar().showMessage(message)

    def update_llm_status_display(self):
        self.action_llm_status.setText(f"📊 Status: {self.llm_status_text}")

    def get_or_create_coordinator(self):
        """Fetches or instantiates a fresh coordinator with current environment keys."""
        api_key = self.api_keys.get(self.current_provider)
        self.llm_coordinator = LLMCoordinator(
            provider=self.current_provider, 
            api_key=api_key
        )
        return self.llm_coordinator

    def set_vector_length(self):
        current_val = self.canvas.vector_length_minutes
        val, ok = QInputDialog.getDouble(
            self, "Vector length",
            "Enter vector length (minutes):",
            current_val, 0.1, 120.0, 1)
        if ok:
            self.canvas.vector_length_minutes = val
            self.statusBar().showMessage(f"Vector length set: {val} min")

    def set_track_length(self):
        current_val = self.canvas.track_length_meters
        val, ok = QInputDialog.getInt(
            self, "Track length",
            "Enter track length (meters):",
            int(current_val), 100, 50000, 100)
        if ok:
            self.canvas.track_length_meters = float(val)
            self.statusBar().showMessage(f"Track length set: {val} m")

    def reset_view_settings(self):
        self.canvas.vector_length_minutes = 12.0
        self.canvas.track_length_meters = 5000.0
        self.canvas.view_center_x = 0.0
        self.canvas.view_center_y = 0.0
        self.canvas.view_scale = 5000.0
        self.canvas.ax.set_xlim(-5000, 5000)
        self.canvas.ax.set_ylim(-5000, 5000)
        self.canvas.draw()
        self.statusBar().showMessage("View settings reset")

    def show_api_help(self):
        from PyQt5.QtWidgets import QDialog, QTextBrowser, QPushButton
        dialog = QDialog(self)
        dialog.setWindowTitle("Where to get API keys?")
        dialog.setFixedSize(650, 520)
        layout = QVBoxLayout()
        text_browser = QTextBrowser()
        text_browser.setOpenExternalLinks(True)
        text_browser.setHtml("""
            <h3>Getting API keys for LLM</h3>
            <p><b>1. Ollama (Local, Free):</b><br>
            No key needed! Download from <a href="https://ollama.com">ollama.com</a> and run it.</p>
            <p><b>2. Groq (Free, Very fast):</b><br>
            Go to <a href="https://console.groq.com">console.groq.com</a>, sign in via GitHub/Google,
            create an API Key in the "API Keys" section. Key starts with <code>gsk_</code>.</p>
            <p><b>3. OpenAI (Paid, ~$0.01/request):</b><br>
            Keys at <a href="https://platform.openai.com/api-keys">platform.openai.com</a>.</p>
            <p><b>4. DeepSeek (Very cheap):</b><br>
            Keys at <a href="https://platform.deepseek.com">platform.deepseek.com</a>.</p>
            <p><b>5. Anthropic Claude (Paid):</b><br>
            Keys at <a href="https://console.anthropic.com">console.anthropic.com</a>.</p>
            <p><i>Copy the key and paste it via menu LLM → LLM Settings.</i></p>
        """)
        text_browser.setStyleSheet("font-size: 12px;")
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.close)
        layout.addWidget(text_browser)
        layout.addWidget(btn_close)
        dialog.setLayout(layout)
        dialog.exec_()

    def show_help(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("User guide")
        msg.setIcon(QMessageBox.Information)
        msg.setTextFormat(Qt.RichText)
        text = """
        <h2>MASS Sim - Autonomous Vessel Collision Avoidance Simulator</h2>
        <h3>Scene control:</h3>
        <ul>
        <li><b>Pan:</b> Hold <b>Left Mouse Button (LMB)</b> and drag.</li>
        <li><b>Zoom:</b> Use the <b>Mouse Wheel</b>.</li>
        </ul>
        <h3>Vessel operations:</h3>
        <ul>
        <li><b>Add vessel:</b> <b>Right-click (RMB)</b> on empty space. Set course and speed.</li>
        <li><b>Control vessel:</b> <b>RMB on vessel icon</b>. Opens context menu with Delete/Move/Options.</li>
        <li><b>Move vessel:</b> RMB on vessel → Move → Click LMB on new position → Set course and speed.</li>
        </ul>
        <h3>Routes:</h3>
        <ul>
        <li>Press <b>🛤 Create Route</b> button on the toolbar.</li>
        <li>Click <b>RMB</b> on the canvas to add waypoints.</li>
        <li><b>RMB on route point</b> → Edit or Delete route.</li>
        <li>In edit mode: <b>LMB drag</b> to move route points.</li>
        <li>Assign a vessel to follow the route.</li>
        </ul>
        <h3>Tasks:</h3>
        <ul>
        <li>Menu <b>Tasks → Save Task</b> — save current vessel configuration to a file.</li>
        <li>Menu <b>Tasks → Load Task</b> — load vessel configuration from a file.</li>
        <li>Task files are stored in the <code>Tasks</code> folder.</li>
        </ul>
        <h3>LLM (AI Coordinator) setup:</h3>
        <ul>
        <li>Menu <b>LLM → LLM Settings...</b> — choose provider and API key.</li>
        <li>Menu <b>LLM → Test connection</b> — test link to provider.</li>
        <li>Menu <b>LLM → Query interval</b> — set frequency of LLM requests.</li>
        <li>Menu <b>LLM → Enable LLM for all vessels</b> — quick AI control toggle.</li>
        </ul>
        <h3>Running simulation:</h3>
        <ul>
        <li>Add at least 2 vessels or load a task.</li>
        <li>Enable LLM (via menu or RMB on vessel → Options).</li>
        <li>Press <b>▶ Start</b>. AI will analyze COLREGs and issue commands.</li>
        <li>Menu <b>View → Simulation speed...</b> — change simulation speed.</li>
        </ul>
        <h3>Data recording:</h3>
        <ul>
        <li>Press <b>Start Rec</b> to begin recording. A session folder is created under <code>Logs/yy_mm_dd_hh_mm_ss/</code>.</li>
        <li>Each vessel's state is logged to a CSV file named after the vessel.</li>
        <li>Press <b>Stop Rec</b> to stop recording and close files.</li>
        </ul>
        <h3>COLREG Analysis:</h3>
        <ul>
        <li>Button <b>ColReg analysis</b> opens a table with CPA, TCPA, risk index and rules for all pairs.</li>
        </ul>
        <p><i>Gold frame around a vessel = under AI control.</i></p>
        """
        msg.setText(text)
        msg.exec_()

    def show_about(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("About")
        msg.setIcon(QMessageBox.Information)
        msg.setTextFormat(Qt.RichText)
        text = """
        <h2>MASS Sim</h2>
        <p>Version 1.0</p>
        <p>Autonomous vessel collision avoidance simulator with AI coordinator
        compliant with COLREGs (International Regulations for Preventing Collisions at Sea).</p>
        <p><b>Features:</b></p>
        <ul>
        <li>Nomoto vessel dynamics model</li>
        <li>CPA/TCPA and risk index calculation</li>
        <li>Automatic COLREGs rule detection (13, 14, 15, 17)</li>
        <li>LLM coordinator for maneuver coordination</li>
        <li>Support for local (Ollama) and cloud (OpenAI, Groq, Anthropic, DeepSeek) models</li>
        <li>Simulation data logging to CSV</li>
        <li>Task save/load functionality</li>
        <li>Route creation and vessel assignment</li>
        </ul>
        <p><i>Based on architecture from the paper
        "Large Language Model-based Decision-making for COLREGs-compliant autonomous surface vehicles"</i></p>
        """
        msg.setText(text)
        msg.exec_()

    def save_task(self):
        if len(self.ships) == 0 and len(self.routes) == 0:
            QMessageBox.warning(self, "Nothing to save", "No vessels or routes to save.")
            return
        filename, ok = QInputDialog.getText(
            self, "Save Task", "Enter task filename (without extension):")
        if not ok or not filename.strip():
            return
        filename = filename.strip()
        if not filename.endswith('.json'):
            filename += '.json'
        os.makedirs(self.tasks_dir, exist_ok=True)
        filepath = os.path.join(self.tasks_dir, filename)
        
        task_data = {'vessels': [], 'routes': []}
        
        # === SAVING ROUTES ===
        for route in self.routes:
            route_data = {
                'name': route.name,
                'points': [],
                'assigned_ship': route.assigned_ship.name if route.assigned_ship else None,
            }
            for point in route.points:
                point_data = {
                    'x': point.x,
                    'y': point.y,
                    'point_number': point.point_number,
                }
                route_data['points'].append(point_data)
            task_data['routes'].append(route_data)
        
        # === SAVING VESSELS ===
        for ship in self.ships:
            vessel_data = {
                'name': ship.name,
                'x': ship.x,
                'y': ship.y,
                'course_deg': ship.get_heading_deg(),
                'speed_ms': ship.u,
                'rudder_deg': ship.rudder_cmd,
                'rpm_percent': ship.rpm_cmd,
                'llm_controlled': ship.llm_controlled,
                'assigned_route': ship.assigned_route.name if ship.assigned_route else None,
            }
            task_data['vessels'].append(vessel_data)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, indent=2, ensure_ascii=False)
            self.statusBar().showMessage(f"Task saved: {filepath}")
            QMessageBox.information(
                self, "Task Saved", 
                f"Task saved successfully:\n{filepath}\n\n"
                f"Vessels: {len(self.ships)}\nRoutes: {len(self.routes)}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save task:\n{e}")

    def load_task(self):
        if not os.path.exists(self.tasks_dir):
            QMessageBox.warning(self, "No Tasks", "No Tasks folder found.")
            return
        task_files = [f for f in os.listdir(self.tasks_dir) if f.endswith('.json')]
        if not task_files:
            QMessageBox.warning(self, "No Tasks", "No task files found in Tasks folder.")
            return
        filename, ok = QInputDialog.getItem(
            self, "Load Task", "Select task file to load:",
            task_files, 0, False)
        if not ok or not filename:
            return
        filepath = os.path.join(self.tasks_dir, filename)
        if self.running:
            self.stop_simulation()
        self.clear_ships()
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                task_data = json.load(f)
            
            # === LOADING ROUTES ===
            route_objects = {}
            for route_data in task_data.get('routes', []):
                route = Route()
                route.name = route_data['name']
                for point_data in route_data['points']:
                    point = RoutePoint(
                        point_data['x'], 
                        point_data['y'], 
                        point_data['point_number']
                    )
                    route.points.append(point)
                route._recalculate()
                self.routes.append(route)
                route_objects[route.name] = route
            
            # === LOADING VESSELS ===
            for vessel_data in task_data.get('vessels', []):
                ship = Ship(
                    x=vessel_data['x'],
                    y=vessel_data['y'],
                    psi_deg=vessel_data['course_deg'],
                    speed_ms=vessel_data['speed_ms'],
                    name=vessel_data.get('name')
                )
                ship.rudder_cmd = vessel_data.get('rudder_deg', 0.0)
                ship.rpm_cmd = vessel_data.get('rpm_percent', 50.0)
                ship.set_base_heading(vessel_data['course_deg'])
                ship.llm_controlled = vessel_data.get('llm_controlled', False)
                
                # === RESTORING SHIP-ROUTE ASSOCIATIONS ===
                assigned_route_name = vessel_data.get('assigned_route')
                if assigned_route_name and assigned_route_name in route_objects:
                    route = route_objects[assigned_route_name]
                    ship.assigned_route = route
                    ship.autopilot_enabled = True
                    ship.autopilot = RouteAutopilot(ship, route)
                    route.assigned_ship = ship
                
                self.ships.append(ship)
            
            self.statusBar().showMessage(f"Task loaded: {filepath}")
            QMessageBox.information(
                self, "Task Loaded",
                f"Task loaded successfully:\n{filepath}\n\n"
                f"Vessels: {len(self.ships)}\nRoutes: {len(self.routes)}")
            self.canvas.update_plot(
                self.ships, self.running, self.simulation_time,
                use_miles=self.use_miles, use_knots=self.use_knots,
                predicted_tracks=self.predicted_tracks,
                routes=self.routes,
                ego_perspective=self.selected_ego_ship
            )
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to load task:\n{e}")
            import traceback
            traceback.print_exc()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setStyleSheet("background-color: #f0f0f0; border-bottom: 1px solid #cccccc;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 5, 10, 5)
        toolbar_layout.setSpacing(10)

        default_style = """
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #b0b0b0;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
            QPushButton:pressed {
                background-color: #c0c0c0;
            }
        """

        self.btn_start = QPushButton("▶ Start")
        self.btn_start.setStyleSheet(default_style)
        self.btn_start.setFixedHeight(40)
        self.btn_start.clicked.connect(self.start_simulation)

        self.btn_stop = QPushButton("⏸ Stop")
        self.btn_stop.setStyleSheet(default_style)
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.clicked.connect(self.stop_simulation)

        self.btn_clear = QPushButton("🗑 Clear All")
        self.btn_clear.setStyleSheet(default_style)
        self.btn_clear.setFixedHeight(40)
        self.btn_clear.clicked.connect(self.clear_ships)

        self.btn_rec = QPushButton("🔴 Start Rec")
        self.btn_rec.setStyleSheet(default_style)
        self.btn_rec.setFixedHeight(40)
        self.btn_rec.setEnabled(False)
        self.btn_rec.clicked.connect(self.toggle_recording)

        self.btn_analysis = QPushButton("📊 ColReg analysis")
        self.btn_analysis.setStyleSheet(default_style)
        self.btn_analysis.setFixedHeight(40)
        self.btn_analysis.clicked.connect(self.open_collision_analysis)

        self.btn_llm_decisions = QPushButton(" LLM Decisions")
        self.btn_llm_decisions.setStyleSheet(default_style)
        self.btn_llm_decisions.setFixedHeight(40)
        self.btn_llm_decisions.clicked.connect(self.open_llm_decisions)

        self.btn_create_route = QPushButton("🛤 Create Route")
        self.btn_create_route.setStyleSheet("""
            QPushButton {
                background-color: #FFD700;
                color: black;
                font-size: 12px;
                font-weight: bold;
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #FFC700;
            }
        """)
        self.btn_create_route.clicked.connect(self.toggle_route_mode)

        toolbar_layout.addWidget(self.btn_start)
        toolbar_layout.addWidget(self.btn_stop)
        toolbar_layout.addWidget(self.btn_clear)
        toolbar_layout.addWidget(self.btn_rec)
        toolbar_layout.addWidget(self.btn_analysis)
        toolbar_layout.addWidget(self.btn_llm_decisions)
        toolbar_layout.addWidget(self.btn_create_route)
        toolbar_layout.addStretch()

        main_layout.addWidget(toolbar)

        # Canvas Setup
        self.canvas = ShipCanvas(use_miles=self.use_miles, use_knots=self.use_knots)
        self.canvas.on_click_callback = self.on_empty_field_click
        self.canvas.on_ship_click_callback = self.on_ship_click
        self.canvas.on_mouse_move_callback = self.on_mouse_move
        self.canvas.on_route_point_click_callback = self.on_route_point_right_click
        self.canvas.on_route_point_moved_callback = self.on_route_point_moved
        
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_layout.addWidget(self.canvas, stretch=1)

        self.statusBar().showMessage("Ready. Use the menus at the top.")

    # ========== ROUTES ==========

    def toggle_route_mode(self):
        """Enable/Disable route creation session mode."""
        if self.editing_route is not None:
            self.editing_route = None
            self.canvas.editing_route = None
            if hasattr(self, 'route_dialog') and self.route_dialog:
                self.route_dialog.close()
                self.route_dialog = None

        self.route_mode = not self.route_mode

        if self.route_mode:
            self.current_route = Route()
            self.routes.append(self.current_route)

            self.route_dialog = RouteDialog(self.current_route, self.ships, self, is_editing=False)
            self.route_dialog.show()
            self.route_dialog.route_updated.connect(self.on_route_dialog_closed)

            self.canvas.update_plot(
                self.ships, self.running, self.simulation_time,
                use_miles=self.use_miles, use_knots=self.use_knots,
                predicted_tracks=self.predicted_tracks,
                routes=self.routes,
                ego_perspective=self.selected_ego_ship
            )
            self.statusBar().showMessage(
                "Route creation mode: RMB on canvas to add waypoints"
            )
        else:
            self.route_mode = False
            if hasattr(self, 'route_dialog') and self.route_dialog:
                self.route_dialog.close()
                self.route_dialog = None

    def on_route_dialog_closed(self):
        """Triggered upon route dialog interface dismissal."""
        self.route_mode = False

        if self.current_route and len(self.current_route.points) < 2:
            if self.current_route in self.routes:
                self.routes.remove(self.current_route)

        self.current_route = None

        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    def add_route_point(self, x, y):
        """Append target coordinate waypoint into current configuration path container."""
        if self.route_mode and self.current_route:
            self.current_route.add_point(x, y)

            if hasattr(self, 'route_dialog') and self.route_dialog:
                self.route_dialog.refresh_from_route()

            self.canvas.update_plot(
                self.ships, self.running, self.simulation_time,
                use_miles=self.use_miles, use_knots=self.use_knots,
                predicted_tracks=self.predicted_tracks,
                routes=self.routes,
                ego_perspective=self.selected_ego_ship
            )

    def on_route_point_right_click(self, route, point_index, x, y):
        """Handle RMB context selections on route points."""
        menu = QMenu(self)

        action_edit = QAction("✏️ Edit Route", self)
        action_edit.triggered.connect(lambda: self.edit_route(route))
        menu.addAction(action_edit)

        action_delete = QAction("🗑 Delete Route", self)
        action_delete.triggered.connect(lambda: self.delete_route(route))
        menu.addAction(action_delete)

        menu.exec_(QCursor.pos())

    def delete_route(self, route):
        """Remove explicit route instance entirely."""
        if route in self.routes:
            self.routes.remove(route)

        if self.editing_route is route:
            self.editing_route = None
            self.canvas.editing_route = None
            if hasattr(self, 'route_dialog') and self.route_dialog:
                self.route_dialog.close()
                self.route_dialog = None

        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )
        self.statusBar().showMessage(f"Route {route.name} deleted")

    def edit_route(self, route):
        """Open specialized modification window for an active route path layout."""
        self.route_mode = False
        self.current_route = None

        self.editing_route = route
        self.canvas.editing_route = route

        self.route_dialog = RouteDialog(route, self.ships, self, is_editing=True)
        self.route_dialog.show()
        self.route_dialog.route_updated.connect(self.on_route_dialog_closed)

        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )
        self.statusBar().showMessage(
            f"Editing route {route.name} — LMB drag points, RMB for menu"
        )

    def on_route_point_moved(self, route, point_index):
        """Dispatched continuously when route points change coordinates via UI layout."""
        if hasattr(self, 'route_dialog') and self.route_dialog:
            self.route_dialog.refresh_from_route()

        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    # ========== MISCELLANEOUS ENGINE ROUTINES ==========

    def on_mouse_move(self, x, y):
        if self.move_mode:
            self.statusBar().showMessage(
                f"📍 MOVE MODE: Click to place {self.move_ship.name} at X={x:.0f} m, Y={y:.0f} m (or press Esc to cancel)")
        else:
            self.statusBar().showMessage(f"Cursor: X={x:.0f} m, Y={y:.0f} m")

    def update_rec_button_state(self):
        can_record = len(self.ships) > 0 or self.running
        self.btn_rec.setEnabled(can_record)

    def toggle_recording(self):
        if not self.recording:
            if len(self.ships) == 0 and not self.running:
                QMessageBox.warning(
                    self, "Recording unavailable",
                    "Cannot start recording: no vessels present and simulation is not running.")
                return
            now = datetime.now()
            session_name = now.strftime("%y_%m_%d_%H_%M_%S")
            logs_dir = os.path.join(os.getcwd(), "Logs")
            os.makedirs(logs_dir, exist_ok=True)
            self.rec_session_path = os.path.join(logs_dir, session_name)
            os.makedirs(self.rec_session_path, exist_ok=True)
            for ship in self.ships:
                self.open_log_file(ship)
            self.recording = True
            self.btn_rec.setText("⏹ Stop Rec")
            self.btn_rec.setStyleSheet("""
                QPushButton {
                    background-color: #ff9999;
                    border: 1px solid #cc6666;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: bold;
                    min-width: 100px;
                }
                QPushButton:hover {
                    background-color: #ff8080;
                }
                QPushButton:pressed {
                    background-color: #ff6666;
                }
            """)
            self.statusBar().showMessage(f"Recording started: {self.rec_session_path}")
        else:
            self.close_all_logs()
            self.recording = False
            self.rec_session_path = None
            self.btn_rec.setText("🔴 Start Rec")
            self.btn_rec.setStyleSheet("""
                QPushButton {
                    background-color: #e0e0e0;
                    border: 1px solid #b0b0b0;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: bold;
                    min-width: 100px;
                }
                QPushButton:hover {
                    background-color: #d0d0d0;
                }
                QPushButton:pressed {
                    background-color: #c0c0c0;
                }
            """)
            self.statusBar().showMessage("Recording stopped")

    def open_log_file(self, ship):
        if ship.name in self.log_files:
            return
        if self.rec_session_path is None:
            return
        filename = os.path.join(self.rec_session_path, f"{ship.name}.csv")
        try:
            f = open(filename, 'w', newline='')
            writer = csv.writer(f)
            writer.writerow(['time_s', 'x_m', 'y_m',
                             'course_deg', 'speed_ms', 'rudder_deg', 'rpm_percent', 'rot_deg_min'])
            self.log_files[ship.name] = (f, writer)
        except Exception as e:
            print(f"Failed to open log file for {ship.name}: {e}")

    def close_log_file(self, ship_name):
        if ship_name in self.log_files:
            f, _ = self.log_files[ship_name]
            try:
                f.close()
            except Exception:
                pass
            del self.log_files[ship_name]

    def log_ship_state(self, ship):
        if not self.recording:
            return
        if ship.name not in self.log_files:
            self.open_log_file(ship)
        if ship.name in self.log_files:
            f, writer = self.log_files[ship.name]
            try:
                writer.writerow(ship.get_log_row(self.simulation_time))
                f.flush()
            except Exception as e:
                print(f"Log write error for {ship.name}: {e}")

    def close_all_logs(self):
        for name, (f, _) in self.log_files.items():
            try:
                f.close()
            except Exception:
                pass
        self.log_files.clear()

    def on_empty_field_click(self, x, y):
        """Handles canvas empty field context initialization mouse triggers."""
        if self.route_mode:
            self.add_route_point(x, y)
            return

        if self.move_mode and self.move_ship:
            self.complete_move_ship(x, y)
            return

        dialog = AddShipDialog(x, y, self, use_knots=self.use_knots)
        if dialog.exec_() == QDialog.Accepted:
            name, course, speed = dialog.get_values()
            if course is not None and speed is not None:
                ship = Ship(x, y, course, speed, name)
                ship.set_base_heading(course)
                self.ships.append(ship)
                if self.recording:
                    self.open_log_file(ship)
                speed_text = format_speed(speed, self.use_knots)
                self.statusBar().showMessage(
                    f"Added: {ship.name} | ({x:.0f}, {y:.0f}) | "
                    f"Course: {course}\u00b0 | Speed: {speed_text}")
                self.update_rec_button_state()
                self.canvas.update_plot(
                    self.ships, self.running, self.simulation_time,
                    use_miles=self.use_miles, use_knots=self.use_knots,
                    predicted_tracks=self.predicted_tracks,
                    routes=self.routes,
                    ego_perspective=self.selected_ego_ship
                )
            else:
                QMessageBox.warning(self, "Error", "Invalid course or speed values")

    def on_ship_click(self, ship):
        if self.move_mode:
            self.cancel_move_ship()

        self.selected_ego_ship = ship
        self.statusBar().showMessage(f"Active perspective switched to: {ship.name}")

        menu = QMenu(self)
        action_delete = QAction("🗑 Delete", self)
        action_delete.triggered.connect(lambda: self.delete_ship(ship))
        menu.addAction(action_delete)
        action_move = QAction("📍 Move", self)
        action_move.triggered.connect(lambda: self.start_move_ship(ship))
        menu.addAction(action_move)
        action_options = QAction("⚙️ Options", self)
        action_options.triggered.connect(lambda: self.open_ship_options(ship))
        menu.addAction(action_options)

        action_autopilot = QAction("🤖 Autopilot", self)
        action_autopilot.triggered.connect(lambda: self.open_autopilot_debug(ship))
        menu.addAction(action_autopilot)

        menu.exec_(QCursor.pos())

        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    def open_autopilot_debug(self, ship):
        """Open specialized tuning analysis fields for a single autopilot framework."""
        if (self.autopilot_debug_dialog is not None and 
                self.autopilot_debug_dialog.ship == ship and
                self.autopilot_debug_dialog.isVisible()):
            self.autopilot_debug_dialog.show()
            self.autopilot_debug_dialog.raise_()
            self.autopilot_debug_dialog.activateWindow()
            return
        
        self.autopilot_debug_dialog = AutopilotDebugDialog(ship, self)
        self.autopilot_debug_dialog.show()

    def start_move_ship(self, ship):
        self.move_mode = True
        self.move_ship = ship
        self.statusBar().showMessage(
            f"📍 MOVE MODE: Click LMB on the scene to place {ship.name} (or press Esc to cancel)")
        self.canvas.setCursor(Qt.CrossCursor)

    def complete_move_ship(self, x, y):
        if not self.move_mode or not self.move_ship:
            return
        ship = self.move_ship
        current_course = ship.get_heading_deg()
        current_speed = ship.u
        current_name = ship.name
        self.close_log_file(ship.name)
        if ship in self.ships:
            self.ships.remove(ship)
        self.move_mode = False
        self.move_ship = None
        self.canvas.setCursor(Qt.OpenHandCursor)
        dialog = AddShipDialog(
            x, y, self,
            default_course=current_course,
            default_speed=current_speed,
            default_name=current_name,
            use_knots=self.use_knots
        )
        if dialog.exec_() == QDialog.Accepted:
            name, course, speed = dialog.get_values()
            if course is not None and speed is not None:
                new_ship = Ship(x, y, course, speed, name)
                new_ship.set_base_heading(course)
                self.ships.append(new_ship)
                if self.recording:
                    self.open_log_file(new_ship)
                speed_text = format_speed(speed, self.use_knots)
                self.statusBar().showMessage(
                    f"Moved: {new_ship.name} | ({x:.0f}, {y:.0f}) | "
                    f"Course: {course}\u00b0 | Speed: {speed_text}")
        else:
            self.ships.append(ship)
            self.statusBar().showMessage(f"Move cancelled: {ship.name} remains at original position")
        self.update_rec_button_state()
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes, 
            ego_perspective=self.selected_ego_ship
        )

    def cancel_move_ship(self):
        if self.move_mode:
            self.move_mode = False
            self.move_ship = None
            self.canvas.setCursor(Qt.OpenHandCursor)
            self.statusBar().showMessage("Move cancelled")

    def delete_ship(self, ship):
        if self.move_mode:
            self.cancel_move_ship()
        self.close_log_file(ship.name)
        if ship in self.ships:
            self.ships.remove(ship)
        self.statusBar().showMessage(f"Deleted: {ship.name}")
        self.update_rec_button_state()
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    def open_ship_options(self, ship):
        if self.move_mode:
            self.cancel_move_ship()
        dialog = ControlDialog(ship, self, use_knots=self.use_knots)
        dialog.exec_()
        llm_status = "LLM enabled" if ship.llm_controlled else "Manual control"
        self.statusBar().showMessage(
            f"{ship.name}: {llm_status} | Rudder={ship.rudder_cmd}\u00b0, RPM={ship.rpm_cmd}%")
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    def toggle_llm_for_all(self):
        llm_enabled = not any(s.llm_controlled for s in self.ships)
        if llm_enabled:
            coordinator = self.get_or_create_coordinator()
            success, message = coordinator.test_connection()
            if not success:
                QMessageBox.warning(
                    self, "LLM connection error",
                    f"Failed to connect to {coordinator.PROVIDERS[self.current_provider]['name']}:\n"
                    f"{message}\n\nCheck settings in menu LLM → LLM Settings.")
                return
            self.llm_status_text = f"OK: {coordinator.PROVIDERS[self.current_provider]['name']}"
        else:
            self.llm_status_text = "LLM disabled"
        for ship in self.ships:
            ship.toggle_llm_control(llm_enabled)
        if llm_enabled:
            self.statusBar().showMessage(
                f"LLM ({coordinator.PROVIDERS[self.current_provider]['name']}) "
                f"enabled for all vessels")
            self.action_llm_toggle.setText(" Disable LLM for all vessels")
        else:
            self.statusBar().showMessage("LLM control disabled")
            self.action_llm_toggle.setText(" Enable LLM for all vessels")
        self.update_llm_status_display()
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    def open_collision_analysis(self):
        """Open COLREG evaluation matrix metrics context interfaces."""
        if self.analysis_window is None:
            self.analysis_window = launch_collision_analysis(lambda: self.ships, self)
        else:
            self.analysis_window.show()
            self.analysis_window.raise_()
            self.analysis_window.activateWindow()

    def open_llm_decisions(self):
        if self.llm_decisions_window is None:
            self.llm_decisions_window = launch_llm_decisions_window(
                self.ships,
                self.llm_coordinator
            )
        else:
            self.llm_decisions_window.show()
            self.llm_decisions_window.raise_()
            self.llm_decisions_window.activateWindow()

    def open_safe_passing_calculator(self):
        """Open trajectory vector forecast calculator models interface."""
        if len(self.ships) < 2:
            QMessageBox.warning(
                self, "Not enough vessels",
                "Need at least 2 vessels to calculate safe passing."
            )
            return
        launch_safe_passing_calculator(self.ships, self)

    def start_simulation(self):
        if not self.running:
            self.running = True
            self.timer.start(50)
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #90EE90;
                    border: 1px solid #66CC66;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: bold;
                    min-width: 100px;
                }
                QPushButton:hover {
                    background-color: #7FDB7F;
                }
                QPushButton:pressed {
                    background-color: #66CC66;
                }
            """)
            self.statusBar().showMessage("Simulation started")
            self.update_rec_button_state()

    def stop_simulation(self):
        self.running = False
        self.timer.stop()
        
        # Stop all decentralized parallel workers safely
        if hasattr(self, 'llm_workers') and self.llm_workers:
            for ship_name, worker in list(self.llm_workers.items()):
                try:
                    if worker.isRunning():
                        worker.stop()
                        worker.wait(2000)
                except (RuntimeError, ReferenceError):
                    pass
            self.llm_workers.clear()
            
        self.llm_pending = False
        if self.recording:
            self.toggle_recording()
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #e0e0e0;
                border: 1px solid #b0b0b0;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #d0d0d0;
            }
            QPushButton:pressed {
                background-color: #c0c0c0;
            }
        """)
        self.statusBar().showMessage("Simulation stopped")
        self.update_rec_button_state()

    def clear_ships(self):
        if self.recording:
            self.toggle_recording()
        if self.move_mode:
            self.cancel_move_ship()
        
        # Disengage and reset active autopilot references
        for ship in self.ships:
            ship.autopilot_enabled = False
            ship.autopilot = None
            ship.assigned_route = None
        
        self.ships.clear()
        self.routes.clear()
        self.current_route = None
        self.editing_route = None
        self.route_mode = False
        
        if hasattr(self, 'route_dialog') and self.route_dialog:
            self.route_dialog.close()
            self.route_dialog = None
        
        Ship._counter = 0
        self.simulation_time = 0.0
        self.last_llm_update = 0.0
        self.statusBar().showMessage("All vessels and routes cleared")
        self.update_rec_button_state()
        
        self.canvas.update_plot(
            self.ships, self.running, self.simulation_time,
            use_miles=self.use_miles, use_knots=self.use_knots,
            predicted_tracks=self.predicted_tracks,
            routes=self.routes,
            ego_perspective=self.selected_ego_ship
        )

    def collect_ego_data(self, ego_ship):
        from colreg_rules import determine_colreg_situation
        from collision_analyzer import CollisionAnalyzer
        import numpy as np
        
        def get_historical_state(target_time, history):
            if not history: return None
            closest = min(history, key=lambda wp: abs(wp["time"] - target_time))
            if abs(closest["time"] - target_time) > 120:
                return None
            return {"heading_deg": closest["heading"], "speed_ms": closest["speed"]}

        analyzer = CollisionAnalyzer()
        pairs_info = []
        
        # Priority mapping for rule weights (higher values indicate greater navigational urgency)
        RULE_PRIORITY = {
            '17.2': 5,     # Critical Convergence / Emergency
            '14': 4,       # Head-on
            '15': 3,       # Crossing
            '13': 2,       # Overtaking
            'None': 0,     # Safe Status
            'Unknown': 0
        }
        
        highest_rule_severity = 0
        dominant_status = 'HOLD_COURSE'
        no_left_turn = False
        all_passed = True
        
        t_15m = max(0, self.simulation_time - 900)
        t_10m = max(0, self.simulation_time - 600)
        t_5m  = max(0, self.simulation_time - 300)
        
        for other in self.ships:
            if other is ego_ship:
                continue
          
            cpa_data = analyzer.calculate_cpa_tcpa(ego_ship, other)
            colreg = determine_colreg_situation(
                ego_ship, other,
                cpa_data['dist'], cpa_data['DCPA'], cpa_data['TCPA']
            )
            
            rule_id = colreg.get('rule', 'None')
            current_severity = RULE_PRIORITY.get(rule_id, 0)
            
            action = colreg['ship1_action']
            
            # Map out tactical role for this distinct pair
            if 'Give-way' in action or 'Alter' in action or 'Change' in action:
                pair_role = 'GIVE_WAY'
                pair_status = 'MUST_YIELD'
            elif 'Stand on' in action:
                pair_role = 'STAND_ON'
                pair_status = 'HOLD_COURSE'
            else:
                pair_role = 'BOTH_ALTER'
                pair_status = 'MUST_YIELD'
                
            # If this vessel is in an emergency under 17.2, override pair status explicitly
            if rule_id == '17.2':
                pair_status = 'CRITICAL_CONVERGENCE'

            # Evaluates if the current interaction dict overrides the previous dominant rule threat
            if current_severity > highest_rule_severity:
                highest_rule_severity = current_severity
                dominant_status = pair_status

            crossing = analyzer.calculate_course_crossing(ego_ship, other)
            crosses_ahead = None
            if crossing['crossing_type']:
                if crossing['crosses_1_by_2']:
                    crosses_ahead = f"{other.name} crosses {ego_ship.name} ahead"
                elif crossing['crosses_2_by_1']:
                    crosses_ahead = f"{ego_ship.name} crosses {other.name} ahead"
            
            # Starboard turn constraint safeguard rule
            if pair_role == 'GIVE_WAY' and crosses_ahead and f"{other.name} crosses" in crosses_ahead:
                no_left_turn = True
            
            tcpa_val = cpa_data['TCPA']
            if np.isinf(tcpa_val) or tcpa_val > 0.1:
                all_passed = False

            historical_data = {
                "T-15m": get_historical_state(t_15m, other.trajectory_history),
                "T-10m": get_historical_state(t_10m, other.trajectory_history),
                "T-5m":  get_historical_state(t_5m, other.trajectory_history)
            }

            pairs_info.append({
                'other_ship': other.name,
                'rule': rule_id,
                'role': pair_role,
                'cpa_m': float(cpa_data['DCPA']),
                'tcpa_s': float(cpa_data['TCPA']) if not np.isinf(cpa_data['TCPA']) else 99999.0,
                'crosses_ahead': crosses_ahead,
                'recent_history': historical_data
            })

        current_heading = ego_ship.get_heading_deg()
        heading_diff = abs((ego_ship.base_heading_deg - current_heading + 180) % 360 - 180)
        
        # Final status assignment based strictly on hierarchical logic dominance
        if dominant_status == 'CRITICAL_CONVERGENCE':
            status = 'MUST_YIELD'  # Kept as MUST_YIELD for LLM vocabulary parsing match, but prioritized
        elif max(highest_rule_severity, 0) > 0:
            status = 'MUST_YIELD'
        elif all_passed and heading_diff > 1 and ego_ship.in_maneuver:
            status = 'RETURN_TO_COURSE'
        elif ego_ship.in_maneuver:
            status = 'MANEUVERING'    
        else:
            status = 'HOLD_COURSE'
        
        return {
            'name': ego_ship.name,
            'current_x': float(ego_ship.x),
            'current_y': float(ego_ship.y),
            'base_x': float(ego_ship.base_x),
            'base_y': float(ego_ship.base_y),
            'current_heading_deg': float(current_heading),
            'base_heading_deg': float(ego_ship.base_heading_deg),
            'heading_diff_deg': float(heading_diff),
            'speed_ms': float(ego_ship.u),
            'current_rudder': float(ego_ship.rudder_cmd),
            'current_rpm': float(ego_ship.rpm_cmd),
            'status': status,
            'no_left_turn': no_left_turn,
            'in_maneuver': ego_ship.in_maneuver,
            'pairs': pairs_info
        }

    def on_llm_result(self, ship_name, commands):
        """Processes telemetry response commands returned from decentralized agents."""
        self.llm_pending = False
        
        ship = next((s for s in self.ships if s.name == ship_name), None)
        if not ship:
            return

        if isinstance(commands, dict):
            rudder = commands.get("rudder_deg", 0)
            rpm = commands.get("rpm_percent", 50)
            reasoning = commands.get("reasoning", "No reasoning provided")

            ship.apply_llm_command(rudder, rpm)
            ship.llm_decision = commands
            ship.llm_reasoning = reasoning
        elif isinstance(commands, str):
            ship.llm_reasoning = commands
            ship.llm_decision = {"rudder_deg": 0, "rpm_percent": 50, "reasoning": commands}
        
        for s in self.ships:
            if not s.llm_controlled:
                continue
            
            autopilot = getattr(s, 'autopilot', None)
            autopilot_enabled = getattr(s, 'autopilot_enabled', False)
            
            if autopilot_enabled and autopilot and autopilot.mode == 1:  # MODE_HOLD_COURSE
                current_heading = s.get_heading_deg()
                target_course = autopilot.hold_course_rad
                
                if target_course is not None:
                    target_deg = np.degrees(target_course)
                    heading_diff = abs((current_heading - target_deg + 180) % 360 - 180)
                    
                    if heading_diff <= 5.0:
                        if s.in_maneuver:
                            s.in_maneuver = False
                            s.maneuver_course_deg = None
                            s.maneuver_target_course = None
                            print(f"[Maneuver] {s.name}: COMPLETED - reached target course {target_deg:.1f}\u00b0")
                    else:
                        if not s.in_maneuver:
                            s.in_maneuver = True
                            s.maneuver_target_course = target_deg
                            print(f"[Maneuver] {s.name}: STARTED - target {target_deg:.1f}\u00b0, current {current_heading:.1f}\u00b0")
            else:
                heading_diff = abs((s.base_heading_deg - s.get_heading_deg() + 180) % 360 - 180)
                if heading_diff < 1 and getattr(s, 'rudder_cmd', 0) == 0:
                    s.in_maneuver = False

        if hasattr(self, 'statusBar') and self.statusBar():
            self.statusBar().showMessage(f"LLM applied for {ship_name} at t={self.simulation_time:.1f}s")

    def on_llm_error(self, error_msg):
        self.llm_pending = False
        print(f"LLM Worker Error: {error_msg}")
        self.statusBar().showMessage(f"LLM Error: {error_msg[:50]}")

    def simulation_step(self):
        if self.running:
            llm_ships = [s for s in self.ships if s.llm_controlled]
                
            if llm_ships and (self.simulation_time - self.last_llm_update >= self.llm_update_interval):
                coordinator = self.get_or_create_coordinator()
                    
                if not hasattr(self, 'llm_workers') or self.llm_workers is None:
                    self.llm_workers = {}
                        
                for ship in llm_ships:
                    worker_active = False
                    if ship.name in self.llm_workers:
                        try:
                            if self.llm_workers[ship.name].isRunning():
                                worker_active = True
                        except RuntimeError:
                            del self.llm_workers[ship.name]

                    if not worker_active:
                        ego_data = self.collect_ego_data(ship)
                            
                        if ego_data['status'] == 'RETURN_TO_COURSE':
                            heading_error = (ship.base_heading_deg - ship.get_heading_deg() + 180) % 360 - 180
                            rudder = np.clip(1.5 * heading_error, -35.0, 35.0) 
                            rpm = 50.0
                            
                            ship.apply_llm_command(rudder, rpm)
                            
                            # 1. Attempt extraction from the dictionary structure first
                            agent_reason = ""
                            if hasattr(ship, 'llm_decision') and isinstance(ship.llm_decision, dict):
                                agent_reason = ship.llm_decision.get('reasoning', '')

                            # 2. Fall back to the raw attribute string if the dictionary is empty
                            if not agent_reason and hasattr(ship, 'llm_reasoning'):
                                agent_reason = ship.llm_reasoning

                            # 3. Clean up any existing autopilot tags to prevent stacking
                            if isinstance(agent_reason, str):
                                agent_reason = agent_reason.replace("(Autopilot) ", "")

                            # 4. Fall back to default string if no core reasoning is left
                            if not agent_reason or not agent_reason.strip():
                                agent_reason = "Collision avoided."

                            # 5. Append the uniform format cleanly
                            ship.llm_reasoning = f"(Autopilot) {agent_reason.strip()}"
                            ship.llm_decision = {"rudder_deg": float(rudder), "rpm_percent": float(rpm), "reasoning": ship.llm_reasoning}

                            ship.status_state = "RESUME_COURSE"

                            if abs(heading_error) <= 1.0:
                                ship.apply_llm_command(0.0, rpm)
                                ship.in_maneuver = False
                                ship.status_state = "ON_COURSE"

                        else:
                            # If we are entering this block, it means the ship is NOT in 'RETURN_TO_COURSE'
                            # and must consult the LLM because a threat exists or course is held.
                            # Clear the old autopilot return state if a new threat takes over.
                            if getattr(ship, 'status_state', None) == "RESUME_COURSE":
                                ship.status_state = "MANEUVERING"

                            worker = LLMWorker(coordinator, ship.name, ego_data)
                            worker.result_ready.connect(self.on_llm_result)
                            worker.error_occurred.connect(self.on_llm_error)
                            self.llm_workers[ship.name] = worker
                            worker.start()
                    
                self.last_llm_update = self.simulation_time
                    
                active_count = 0
                for w in self.llm_workers.values():
                    try:
                        if w.isRunning():
                            active_count += 1
                    except RuntimeError:
                        pass
                        
                if active_count > 0:
                    self.statusBar().showMessage(f"Sent {active_count} parallel LLM requests at t={self.simulation_time:.1f}s")
                
            for ship in self.ships:
                heading_diff = abs((ship.base_heading_deg - ship.get_heading_deg() + 180) % 360 - 180)
                if heading_diff > 1:
                    # If the ship is not explicitly under the autopilot return loop, it is maneuvering
                    if getattr(ship, 'status_state', None) != "RESUME_COURSE":
                        ship.in_maneuver = True
                else:
                    
                    # Clear the maneuvering and return states once course is stable
                    ship.in_maneuver = False
                    ship.status_state = "ON_COURSE"
                    
                ship.update(self.dt)
                self.log_ship_state(ship)
                
            self.simulation_time += self.dt
            
            self.canvas.update_plot(
                self.ships, self.running, self.simulation_time,
                use_miles=self.use_miles, use_knots=self.use_knots,
                predicted_tracks=self.predicted_tracks, routes=self.routes,
                ego_perspective=self.selected_ego_ship
            )
            
            if self.simulation_time - self.last_history_record >= 60.0:
                for ship in self.ships:
                    ship.record_history_waypoint(self.simulation_time)
                self.last_history_record = self.simulation_time


if __name__ == "__main__":
    import os
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())