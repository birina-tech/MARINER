"""
canvas.py
Canvas for displaying vessels, routes, and predicted tracks
"""
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QSizePolicy
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, Rectangle
from matplotlib.ticker import FuncFormatter
from matplotlib.lines import Line2D


class ShipCanvas(FigureCanvas):
    def __init__(self, parent=None, use_miles=True, use_knots=True):
        self.fig = Figure(dpi=100)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.view_center_x = 0.0
        self.view_center_y = 0.0
        self.view_scale = 5000.0
        self.min_scale = 200.0
        self.max_scale = 20000.0
        self.zoom_factor = 1.2
        self.is_panning = False
        self.pan_start_pos = None
        self.pan_start_center = None
        self.vector_length_minutes = 12.0
        self.track_length_meters = 5000.0

        # Units of measurement
        self.use_miles = use_miles
        self.use_knots = use_knots

        # Predicted tracks and routes
        self.predicted_tracks = {}
        self.routes = []

        # Route editing mode parameters
        self.editing_route = None
        self.dragging_point_index = None
        self.route_point_click_radius = 80  # Route point selection radius in pixels

        # Remove all layout margins
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        self.ax.set_xlim(-self.view_scale, self.view_scale)
        self.ax.set_ylim(-self.view_scale, self.view_scale)

        # Labels INSIDE the plotting area
        self.ax.tick_params(axis='both', which='both', direction='in',
                            top=True, right=True, left=True, bottom=True)
        self.ax.tick_params(axis='x', which='both', pad=-15)
        self.ax.tick_params(axis='y', which='both', pad=-40)

        self.ax.grid(True, alpha=0.5)

        self.mpl_connect('button_press_event', self.on_click)
        self.mpl_connect('motion_notify_event', self.on_motion)
        self.mpl_connect('button_release_event', self.on_release)
        self.mpl_connect('scroll_event', self.on_scroll)

        self.ships = []
        self.on_click_callback = None
        self.on_ship_click_callback = None
        self.on_mouse_move_callback = None
        self.on_route_point_click_callback = None
        self.on_route_point_moved_callback = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w = event.size().width()
        h = event.size().height()
        if w > 0 and h > 0:
            self.fig.set_size_inches(w / self.fig.dpi, h / self.fig.dpi)
            self.update_plot(
                self.ships, False, 0.0,
                use_miles=self.use_miles,
                use_knots=self.use_knots,
                predicted_tracks=self.predicted_tracks,
                routes=self.routes
            )

    def _get_view_limits(self):
        bbox = self.ax.get_window_extent()
        if bbox.width == 0 or bbox.height == 0:
            return (-self.view_scale, self.view_scale,
                    -self.view_scale, self.view_scale)

        window_aspect = bbox.width / bbox.height
        base_range = self.view_scale

        if window_aspect > 1.0:
            x_range = base_range * window_aspect
            y_range = base_range
        else:
            x_range = base_range
            y_range = base_range / window_aspect

        return (self.view_center_x - x_range, self.view_center_x + x_range,
                self.view_center_y - y_range, self.view_center_y + y_range)

    def get_clicked_route_point(self, x, y):
        """
        Check if the mouse click hit a route waypoint.
        Returns (route, point_index) or (None, None).
        """
        if x is None or y is None:
            return None, None

        # Convert data coordinates to pixels for comparison
        bbox = self.ax.get_window_extent()
        xlim = self.ax.get_xlim()
        ylim = self.ax.get_ylim()

        if (xlim[1] - xlim[0]) == 0 or (ylim[1] - ylim[0]) == 0:
            return None, None

        pixels_per_data_x = bbox.width / (xlim[1] - xlim[0])
        pixels_per_data_y = bbox.height / (ylim[1] - ylim[0])

        for route in self.routes:
            for i, point in enumerate(route.points):
                dx_pix = (point.x - x) * pixels_per_data_x
                dy_pix = (point.y - y) * pixels_per_data_y
                dist_pix = np.sqrt(dx_pix**2 + dy_pix**2)

                if dist_pix <= self.route_point_click_radius:
                    return route, i

        return None, None

    def on_click(self, event):
        if event.inaxes != self.ax:
            return

        if event.button == 1:
            # LMB - if in dragging mode for a route waypoint
            if self.dragging_point_index is not None and self.editing_route:
                route = self.editing_route
                idx = self.dragging_point_index
                if 0 <= idx < len(route.points):
                    route.points[idx].x = event.xdata
                    route.points[idx].y = event.ydata
                    route._recalculate()
                    self.draw()
                    if self.on_route_point_moved_callback:
                        self.on_route_point_moved_callback(route, idx)
                return

            # Otherwise - standard map panning initialization
            self.is_panning = True
            self.pan_start_pos = (event.x, event.y)
            self.pan_start_center = (self.view_center_x, self.view_center_y)
            self.setCursor(Qt.ClosedHandCursor)
            return

        if event.button == 3:
            x, y = event.xdata, event.ydata

            # Check if clicking a route waypoint
            route, point_idx = self.get_clicked_route_point(x, y)

            if route is not None and point_idx is not None:
                if self.on_route_point_click_callback:
                    self.on_route_point_click_callback(route, point_idx, x, y)
                return

            # Standard RMB logic for vessels or empty field
            clicked_ship = None
            click_radius = max(60, self.view_scale * 0.02)
            for ship in self.ships:
                if ship.distance_to(x, y) < click_radius:
                    clicked_ship = ship
                    break
            if clicked_ship:
                if self.on_ship_click_callback:
                    self.on_ship_click_callback(clicked_ship)
            else:
                if self.on_click_callback:
                    self.on_click_callback(x, y)

    def on_motion(self, event):
        if self.is_panning and event.inaxes == self.ax:
            dx_pix = event.x - self.pan_start_pos[0]
            dy_pix = event.y - self.pan_start_pos[1]
            bbox = self.ax.get_window_extent()
            if bbox.width == 0 or bbox.height == 0:
                return

            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            data_width = xlim[1] - xlim[0]
            data_height = ylim[1] - ylim[0]

            pixels_per_data_x = bbox.width / data_width
            pixels_per_data_y = bbox.height / data_height

            dx_data = dx_pix / pixels_per_data_x
            dy_data = -dy_pix / pixels_per_data_y

            self.view_center_x = self.pan_start_center[0] - dx_data
            self.view_center_y = self.pan_start_center[1] + dy_data

            x_min, x_max, y_min, y_max = self._get_view_limits()
            self.ax.set_xlim(x_min, x_max)
            self.ax.set_ylim(y_min, y_max)
            self.draw()

        # If dragging a route waypoint
        if (self.dragging_point_index is not None and 
                self.editing_route and event.inaxes == self.ax):
            route = self.editing_route
            idx = self.dragging_point_index
            if 0 <= idx < len(route.points):
                route.points[idx].x = event.xdata
                route.points[idx].y = event.ydata
                route._recalculate()
                self.draw()
                if self.on_route_point_moved_callback:
                    self.on_route_point_moved_callback(route, idx)

        if event.inaxes == self.ax and event.xdata is not None and event.ydata is not None:
            if self.on_mouse_move_callback:
                self.on_mouse_move_callback(event.xdata, event.ydata)

    def on_release(self, event):
        if event.button == 1:
            if self.dragging_point_index is not None:
                self.dragging_point_index = None
                self.setCursor(Qt.OpenHandCursor)
                return
            if self.is_panning:
                self.is_panning = False
                self.setCursor(Qt.OpenHandCursor)

    def on_scroll(self, event):
        if event.inaxes != self.ax:
            return
        if event.button == 'up':
            self.view_scale /= self.zoom_factor
        elif event.button == 'down':
            self.view_scale *= self.zoom_factor

        self.view_scale = np.clip(self.view_scale, self.min_scale, self.max_scale)

        x_min, x_max, y_min, y_max = self._get_view_limits()
        self.ax.set_xlim(x_min, x_max)
        self.ax.set_ylim(y_min, y_max)
        self.draw()

    def draw_velocity_vector(self, ship):
        if ship.u < 0.1:
            return
        vector_length = ship.u * self.vector_length_minutes * 60
        vector_end_x = ship.x + vector_length * np.sin(ship.psi)
        vector_end_y = ship.y + vector_length * np.cos(ship.psi)
        self.ax.annotate('', xy=(vector_end_x, vector_end_y), xytext=(ship.x, ship.y),
                         arrowprops=dict(arrowstyle='->', color='blue',
                                         lw=0.5, mutation_scale=15), zorder=6)

    def _apply_tick_style(self):
        """Applies style configuration to map grid labels"""
        self.ax.tick_params(axis='both', which='both', direction='in',
                            top=True, right=True, left=True, bottom=True)
        self.ax.tick_params(axis='x', which='both', pad=-15)
        self.ax.tick_params(axis='y', which='both', pad=-40)

        for label in self.ax.get_yticklabels() + self.ax.get_xticklabels():
            label.set_bbox(dict(boxstyle='round,pad=0.2', facecolor='white',
                                alpha=0.85, edgecolor='none'))
            label.set_color('black')
            label.set_fontsize(8)

    def update_plot(self, ships, running, simulation_time,
                    use_miles=None, use_knots=None,
                    predicted_tracks=None, routes=None, chart_data=None,
                    ego_perspective=None):
        """
        Refresh chart plot layout. Added ego_perspective to fix method signature mismatch.
        """
        if predicted_tracks is None:
            predicted_tracks = {}
        if routes is None:
            routes = []

        # Save settings state configurations
        if use_miles is not None:
            self.use_miles = use_miles
        if use_knots is not None:
            self.use_knots = use_knots

        self.predicted_tracks = predicted_tracks
        self.routes = routes
        self.ships = ships

        self.ax.clear()

        x_min, x_max, y_min, y_max = self._get_view_limits()
        self.ax.set_xlim(x_min, x_max)
        self.ax.set_ylim(y_min, y_max)

        self.ax.set_aspect('equal')

        # Apply grid text styles after clear event
        self._apply_tick_style()

        # Format axis labels safely
        if self.use_miles:
            def format_axis_miles(x, pos):
                miles = x / 1852.0
                if abs(miles) >= 1:
                    return f"{miles:.1f}"
                else:
                    return f"{miles:.2f}"

            self.ax.xaxis.set_major_formatter(FuncFormatter(format_axis_miles))
            self.ax.yaxis.set_major_formatter(FuncFormatter(format_axis_miles))
            self.ax.set_xlabel("Distance (nm)", fontsize=9, color='black')
            self.ax.set_ylabel("Distance (nm)", fontsize=9, color='black')
        else:
            def format_axis_meters(x, pos):
                if abs(x) >= 1000:
                    return f"{x / 1000:.1f}"
                return f"{x:.0f}"

            self.ax.xaxis.set_major_formatter(FuncFormatter(format_axis_meters))
            self.ax.yaxis.set_major_formatter(FuncFormatter(format_axis_meters))
            self.ax.set_xlabel("Distance (m/km)", fontsize=9, color='black')
            self.ax.set_ylabel("Distance (m/km)", fontsize=9, color='black')

        self.ax.grid(True, alpha=0.5)

        # === ROUTE RENDERING ENGINE ===
        for route in self.routes:
            if len(route.points) < 2:
                continue

            coordinates = route.get_coordinates_list()
            route_x = [c[0] for c in coordinates]
            route_y = [c[1] for c in coordinates]

            # Route lines
            self.ax.plot(route_x, route_y,
                         color='#595757', linewidth=2, linestyle='-',
                         alpha=0.6, zorder=2)

            # Route waypoints
            self.ax.plot(route_x, route_y,
                         marker='o', markersize=8,
                         color='#595757', markeredgecolor='black',
                         markeredgewidth=1.5, zorder=3)

            # Waypoint labels
            for point in route.points:
                self.ax.text(point.x + 100, point.y + 100,
                             f"P{point.point_number}",
                             fontsize=9, fontweight='bold',
                             color='#595757',
                             bbox=dict(boxstyle='round', facecolor='white',
                                       alpha=0.8, edgecolor='#595757'),
                             zorder=4)

            # Route title identifier
            if route.points:
                mid_x = np.mean(route_x)
                mid_y = np.mean(route_y)
                self.ax.text(mid_x, mid_y - 200,
                             route.name,
                             fontsize=10, fontweight='bold',
                             color='#595757',
                             bbox=dict(boxstyle='round', facecolor='yellow',
                                       alpha=0.7, edgecolor='#595757'),
                             zorder=4)

        # === PREDICTED MANEUVER TRAJECTORIES ===
        for ship_name, track_data in self.predicted_tracks.items():
            role = track_data.get('role', 'unknown')
            pre_maneuver = track_data.get('pre_maneuver', [])
            post_maneuver = track_data.get('post_maneuver', [])
            maneuver_point = track_data.get('maneuver_point', None)

            if role == 'give_way':
                pre_color = '#FFA500'
                post_color = '#00AA00'
                point_color = '#FF0000'
            else:
                pre_color = '#4444FF'
                post_color = None
                point_color = None

            if len(pre_maneuver) > 1:
                pre_x = [p[0] for p in pre_maneuver]
                pre_y = [p[1] for p in pre_maneuver]
                self.ax.plot(pre_x, pre_y,
                             color=pre_color,
                             linewidth=2.0,
                             linestyle='--',
                             alpha=0.7,
                             zorder=3)

            if len(post_maneuver) > 1 and post_color:
                post_x = [p[0] for p in post_maneuver]
                post_y = [p[1] for p in post_maneuver]
                self.ax.plot(post_x, post_y,
                             color=post_color,
                             linewidth=2.5,
                             linestyle='-.',
                             alpha=0.8,
                             zorder=3)

            if maneuver_point and point_color:
                self.ax.plot(maneuver_point[0], maneuver_point[1],
                             marker='o', markersize=10,
                             color=point_color,
                             markeredgecolor='black',
                             markeredgewidth=1.5,
                             zorder=7)

                new_course = track_data.get('new_course')
                if new_course is not None:
                    self.ax.text(maneuver_point[0] + 100, maneuver_point[1] + 100,
                                 f"Turn\nto {new_course:.0f}\u00b0",
                                 fontsize=8,
                                 color=point_color,
                                 fontweight='bold',
                                 bbox=dict(boxstyle='round', facecolor='white',
                                           alpha=0.9, edgecolor=point_color),
                                 zorder=9)

        if self.predicted_tracks:
            legend_elements = [
                Line2D([0], [0], color='#FFA500', linewidth=2, linestyle='--',
                       label='Pre-maneuver (give-way)'),
                Line2D([0], [0], color='#00AA00', linewidth=2.5, linestyle='-.',
                       label='Post-maneuver (give-way)'),
                Line2D([0], [0], color='#4444FF', linewidth=2, linestyle='--',
                       label='Stand-on track'),
                Line2D([0], [0], marker='o', color='w', markerfacecolor='#FF0000',
                       markersize=10, label='Maneuver point')
            ]
            self.ax.legend(handles=legend_elements, loc='upper right', fontsize=8,
                           framealpha=0.9)
        
        # === NAVIGATION METADATA MAP RENDERING ENGINE (S-57 STYLE) ===
        if chart_data and chart_data.get('is_loaded'):
            # 1. Landmass features (Brown fill structures)
            for polygon_rings in chart_data['land_polygons']:
                for ring in polygon_rings:
                    if len(ring) > 2:
                        xs = [p[0] for p in ring]
                        ys = [p[1] for p in ring]
                        self.ax.fill(xs, ys, color='saddlebrown', 
                                    edgecolor='black', linewidth=0.5, 
                                    alpha=0.4, zorder=1)
            
            # 2. Depth Isobars
            for contour in chart_data.get('depth_contours', []):
                points = contour['points']
                depth = contour['depth']
                if len(points) > 1:
                    xs = [p[0] for p in points]
                    ys = [p[1] for p in points]
                    if depth < 10:
                        color = '#FF4444'
                        lw = 1.5
                    elif depth < 20:
                        color = '#FF8800'
                        lw = 1.2
                    else:
                        color = '#4488FF'
                        lw = 0.8
                    self.ax.plot(xs, ys, color=color, linewidth=lw, 
                                alpha=0.7, zorder=1)
                    
                    if len(points) > 5 and self.view_scale < 3000:
                        mid_idx = len(points) // 2
                        self.ax.text(points[mid_idx][0], points[mid_idx][1],
                                    f"{depth:.0f}m", fontsize=7, color=color,
                                    fontweight='bold', ha='center', va='center',
                                    bbox=dict(boxstyle='round,pad=0.2', 
                                            facecolor='white', alpha=0.7),
                                    zorder=2)
            
            # 3. Hazards and Obstacles (Red Cross Markers)
            for obs in chart_data.get('obstacles', []):
                self.ax.plot(obs['x'], obs['y'], marker='x', 
                            color='red', markersize=10, 
                            markeredgewidth=2, zorder=3)
                if obs.get('depth') is not None and self.view_scale < 2000:
                    self.ax.text(obs['x'] + 50, obs['y'] + 50,
                                f"⚠{obs['depth']:.0f}m", 
                                fontsize=7, color='red', fontweight='bold',
                                zorder=3)
                
        # === ACTIVE KINEMATIC VESSELS ===
        for ship in ships:
            track_x = []
            track_y = []
            for hx, hy in zip(ship.history_x, ship.history_y):
                dist = np.sqrt((hx - ship.x) ** 2 + (hy - ship.y) ** 2)
                if dist <= self.track_length_meters:
                    track_x.append(hx)
                    track_y.append(hy)
            if len(track_x) > 1:
                self.ax.plot(track_x, track_y, color=ship.color,
                             alpha=0.4, linewidth=1.5, linestyle='--', zorder=2)

            vertices = ship.get_pentagon_vertices()
            pentagon = Polygon(vertices, closed=True, facecolor='black',
                               edgecolor='black', linewidth=1.5, alpha=0.95, zorder=5)
            self.ax.add_patch(pentagon)

            if ship.llm_controlled:
                rect = Rectangle((ship.x - 60, ship.y - 60), 120, 120,
                                 fill=False, edgecolor='gold', linewidth=3, zorder=4)
                self.ax.add_patch(rect)

            self.draw_velocity_vector(ship)

            font_size = max(7, min(10, 1000 / self.view_scale * 10))
            llm_text = ship.get_llm_status_text()
            self.ax.text(ship.x + 80, ship.y + 80,
                         f"{ship.name}\n{ship.get_heading_deg():.0f}\u00b0\n"
                         f"{ship.u:.1f} m/s\n"
                         f"R:{ship.rudder_cmd:.0f}\u00b0 RPM:{ship.rpm_cmd:.0f}%{llm_text}",
                         fontsize=font_size, ha='left', va='bottom',
                         bbox=dict(boxstyle='round', facecolor='white',
                                   alpha=0.8, edgecolor='gray'))

        self.draw()