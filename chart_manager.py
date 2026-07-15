"""
chart_manager.py
Менеджер для загрузки и обработки навигационных карт S-57 с помощью GDAL/OGR.
ВЕРСИЯ 3: Изобаты как основной источник глубин, убраны warnings GDAL.
"""
from osgeo import ogr, osr
import numpy as np


class ChartManager:
    def __init__(self):
        self.is_loaded = False
        self.land_polygons = []
        self.depth_areas = []        # Точки с глубиной (из SOUNDG + вершины изобат)
        self.depth_contours = []     # Изобаты (линии равных глубин)
        self.obstacles = []          # Препятствия
        self.chart_center_x = 0.0
        self.chart_center_y = 0.0
        self.available_layers = []
        self.depth_layers_info = {}  # Информация о полях слоёв глубин

    def _safe_get_field(self, feature, field_name):
        """
        Безопасно получить значение поля.
        Использует GetFieldIndex() — НЕ генерирует warning в GDAL.
        """
        try:
            field_idx = feature.GetFieldIndex(field_name)
            if field_idx == -1:
                return None
            return feature.GetField(field_idx)
        except Exception:
            return None

    def _get_all_field_names(self, layer):
        """Получить список всех полей слоя"""
        field_names = []
        layer_defn = layer.GetLayerDefn()
        for i in range(layer_defn.GetFieldCount()):
            field_defn = layer_defn.GetFieldDefn(i)
            field_names.append(field_defn.GetName())
        return field_names

    def load_s57(self, file_path):
        """Загружает S-57 карту и извлекает основные слои"""
        try:
            ds = ogr.Open(file_path)
            if ds is None:
                raise Exception(f"Не удалось открыть файл: {file_path}")

            source_srs = osr.SpatialReference()
            source_srs.ImportFromEPSG(4326)

            # Собираем координаты для нахождения центра
            temp_coords = []
            for i in range(ds.GetLayerCount()):
                layer = ds.GetLayerByIndex(i)
                layer.ResetReading()
                for feature in layer:
                    geom = feature.GetGeometryRef()
                    if geom:
                        if geom.GetGeometryName() == 'POINT':
                            temp_coords.append((geom.GetX(), geom.GetY()))
                        elif geom.GetGeometryName() in ['POLYGON', 'MULTIPOLYGON']:
                            ring = geom.GetGeometryRef(0)
                            if ring.GetPointCount() > 0:
                                temp_coords.append((ring.GetX(0), ring.GetY(0)))

            if not temp_coords:
                raise Exception("Карта не содержит геометрических данных")

            avg_lon = np.mean([c[0] for c in temp_coords])
            avg_lat = np.mean([c[1] for c in temp_coords])
            self.chart_center_x = avg_lon
            self.chart_center_y = avg_lat

            # Коэффициенты для перевода в метры
            meters_per_deg_lat = 111320.0
            meters_per_deg_lon = 111320.0 * np.cos(np.radians(avg_lat))

            def to_local_coords(lon, lat):
                x = (lon - avg_lon) * meters_per_deg_lon
                y = (lat - avg_lat) * meters_per_deg_lat
                return x, y

            self.land_polygons = []
            self.depth_areas = []
            self.obstacles = []
            self.depth_contours = []
            self.available_layers = []
            self.depth_layers_info = {}

            # Слои, содержащие информацию о глубинах
            depth_related_layers = {'DEPARE', 'DEPCNT', 'SOUNDG', 'OBSTRN', 'UWTROC', 'WRECKS'}

            for i in range(ds.GetLayerCount()):
                layer = ds.GetLayerByIndex(i)
                layer_name = layer.GetName()
                self.available_layers.append(layer_name)

                field_names = self._get_all_field_names(layer)

                # Для слоёв глубин — выводим ВСЕ поля
                if layer_name in depth_related_layers:
                    print(f"  Слой '{layer_name}': ВСЕ поля = {field_names}")
                    self.depth_layers_info[layer_name] = field_names
                else:
                    print(f"  Слой '{layer_name}': поля = {field_names[:10]}...")

                layer.ResetReading()

                # === СУША ===
                if layer_name == 'LNDARE':
                    for feature in layer:
                        geom = feature.GetGeometryRef()
                        if geom and geom.GetGeometryName() in ['POLYGON', 'MULTIPOLYGON']:
                            polygon_rings = []
                            for j in range(geom.GetGeometryCount()):
                                ring = geom.GetGeometryRef(j)
                                points = []
                                for k in range(ring.GetPointCount()):
                                    lon, lat, _ = ring.GetPoint(k)
                                    x, y = to_local_coords(lon, lat)
                                    points.append((x, y))
                                polygon_rings.append(points)
                            self.land_polygons.append(polygon_rings)

                # === УЧАСТКИ ГЛУБИН (DEPARE) ===
                elif layer_name == 'DEPARE':
                    for feature in layer:
                        geom = feature.GetGeometryRef()
                        if geom:
                            centroid = geom.Centroid()
                            if centroid:
                                lon, lat, _ = centroid.GetPoint(0)
                                x, y = to_local_coords(lon, lat)
                                
                                depth = self._safe_get_field(feature, 'VALDCO')
                                if depth is None:
                                    depth = self._safe_get_field(feature, 'VALSOU')
                                if depth is None:
                                    drval1 = self._safe_get_field(feature, 'DRVAL1')
                                    drval2 = self._safe_get_field(feature, 'DRVAL2')
                                    if drval1 is not None and drval2 is not None:
                                        depth = min(float(drval1), float(drval2))
                                
                                if depth is not None:
                                    self.depth_areas.append({
                                        'x': x, 'y': y, 'depth': float(depth),
                                        'source': 'DEPARE'
                                    })

                # === ИЗОбАТЫ (DEPCNT) — ОСНОВНОЙ ИСТОЧНИК! ===
                elif layer_name == 'DEPCNT':
                    for feature in layer:
                        geom = feature.GetGeometryRef()
                        if geom and geom.GetGeometryName() in ['LINESTRING', 'MULTILINESTRING']:
                            # Пробуем разные поля для глубины изобаты
                            depth = self._safe_get_field(feature, 'VALDCO')
                            if depth is None:
                                depth = self._safe_get_field(feature, 'VALSOU')
                            if depth is None:
                                depth = self._safe_get_field(feature, 'DRVAL1')
                            
                            if depth is None:
                                continue  # Пропускаем изобату без глубины
                            
                            depth_value = float(depth)
                            contour_points = []
                            
                            # Извлекаем все точки линии
                            if geom.GetGeometryName() == 'LINESTRING':
                                for k in range(geom.GetPointCount()):
                                    lon, lat, _ = geom.GetPoint(k)
                                    x, y = to_local_coords(lon, lat)
                                    contour_points.append((x, y))
                                    # Каждая вершина изобаты — это точка с известной глубиной
                                    self.depth_areas.append({
                                        'x': x, 'y': y, 'depth': depth_value,
                                        'source': 'DEPCNT'
                                    })
                            elif geom.GetGeometryName() == 'MULTILINESTRING':
                                for j in range(geom.GetGeometryCount()):
                                    line = geom.GetGeometryRef(j)
                                    for k in range(line.GetPointCount()):
                                        lon, lat, _ = line.GetPoint(k)
                                        x, y = to_local_coords(lon, lat)
                                        contour_points.append((x, y))
                                        self.depth_areas.append({
                                            'x': x, 'y': y, 'depth': depth_value,
                                            'source': 'DEPCNT'
                                        })
                            
                            if contour_points:
                                self.depth_contours.append({
                                    'points': contour_points,
                                    'depth': depth_value
                                })

                # === ПРОМЕРЫ ГЛУБИН (SOUNDG) ===
                elif layer_name == 'SOUNDG':
                    for feature in layer:
                        geom = feature.GetGeometryRef()
                        if geom and geom.GetGeometryName() == 'POINT':
                            lon, lat, _ = geom.GetPoint(0)
                            x, y = to_local_coords(lon, lat)
                            
                            depth = self._safe_get_field(feature, 'VALSOU')
                            if depth is None:
                                depth = self._safe_get_field(feature, 'VALDCO')
                            if depth is None:
                                depth = self._safe_get_field(feature, 'EXPSOU')
                            
                            if depth is not None:
                                self.depth_areas.append({
                                    'x': x, 'y': y, 'depth': float(depth),
                                    'source': 'SOUNDG'
                                })

                # === ПРЕПЯТСТВИЯ ===
                elif layer_name in ('OBSTRN', 'UWTROC', 'WRECKS'):
                    for feature in layer:
                        geom = feature.GetGeometryRef()
                        if geom:
                            if geom.GetGeometryName() == 'POINT':
                                lon, lat, _ = geom.GetPoint(0)
                                x, y = to_local_coords(lon, lat)
                                depth = self._safe_get_field(feature, 'VALDCO')
                                if depth is None:
                                    depth = self._safe_get_field(feature, 'DRVAL1')
                                self.obstacles.append({
                                    'x': x, 'y': y,
                                    'depth': float(depth) if depth is not None else None,
                                    'type': layer_name
                                })

            self.is_loaded = True
            print(f"\n✅ Карта загружена!")
            print(f"   Слои: {len(self.available_layers)}")
            print(f"   Суша: {len(self.land_polygons)} полигонов")
            print(f"   Глубины (всего точек): {len(self.depth_areas)}")
            
            # Статистика по источникам
            sources = {}
            for area in self.depth_areas:
                src = area.get('source', 'unknown')
                sources[src] = sources.get(src, 0) + 1
            for src, count in sources.items():
                print(f"      - {src}: {count} точек")
            
            print(f"   Изобаты (линии): {len(self.depth_contours)}")
            print(f"   Препятствия: {len(self.obstacles)} объектов")
            return True

        except Exception as e:
            print(f"❌ Ошибка загрузки карты: {e}")
            import traceback
            traceback.print_exc()
            return False

    def get_depth_at_position(self, ship_x, ship_y, search_radius=500.0):
        """
        Определить глубину в точке судна по ближайшей изобате/промеру.
        Returns: (depth_meters, distance_to_nearest)
        """
        if not self.is_loaded or not self.depth_areas:
            return None, float('inf')

        min_dist = float('inf')
        nearest_depth = None

        for area in self.depth_areas:
            dist = np.sqrt((ship_x - area['x'])**2 + (ship_y - area['y'])**2)
            if dist < min_dist:
                min_dist = dist
                nearest_depth = area['depth']

        if min_dist > search_radius:
            return None, min_dist

        return nearest_depth, min_dist

    def check_grounding(self, ship_x, ship_y, safety_depth=10.0):
        """Проверяет, не находится ли судно на мелководье"""
        if not self.is_loaded:
            return False, "Карта не загружена"

        depth, dist = self.get_depth_at_position(ship_x, ship_y)

        if depth is not None:
            if depth < safety_depth:
                return True, f"Опасное мелководье! Глубина: {depth:.1f} м (на расстоянии {dist:.0f} м)"
            else:
                return False, f"Глубина {depth:.1f} м — безопасно"

        return False, f"Нет данных о глубине (ближайшая точка на {dist:.0f} м)"

    def get_draw_data(self):
        """Возвращает данные для отрисовки на canvas"""
        return {
            'is_loaded': self.is_loaded,
            'land_polygons': self.land_polygons,
            'depth_areas': self.depth_areas,
            'obstacles': self.obstacles,
            'depth_contours': self.depth_contours,
            'available_layers': self.available_layers,
            'depth_layers_info': self.depth_layers_info
        }