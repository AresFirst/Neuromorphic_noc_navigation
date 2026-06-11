"""PySide6 desktop map viewer for Hangzhou SNN navigation.

This module is intentionally separate from the Streamlit GUI.  It reuses the
existing OSM cache, DiGraph adapter, SNN navigation result structures and OSM
geometry helpers, then renders them in a local Qt window.
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import networkx as nx

from maps import (
    DEFAULT_FIXED_MAP_REGION,
    HANGZHOU_BBOX,
    edge_geometry_to_latlon,
    load_hangzhou_graph,
    nearest_node_by_latlon,
    osmnx_multidigraph_to_digraph,
    path_nodes_to_latlon,
)
from navigation import NavigationResult, run_navigation

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OSM_TILE_ROOT = PROJECT_ROOT / "data" / "tiles" / "osm"
DEFAULT_TILE_ZOOM = 14
TILE_SIZE = 256
WEB_MERCATOR_MAX_LAT = 85.05112878
SUPPORTED_TILE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")

EdgePoints = list[tuple[int, int, list[tuple[float, float]]]]
ScenePointLookup = dict[int, tuple[float, float]]


@dataclass(frozen=True, slots=True)
class SceneBounds:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return max(1.0, float(self.right) - float(self.left))

    @property
    def height(self) -> float:
        return max(1.0, float(self.bottom) - float(self.top))


def _clamp_latitude(lat: float) -> float:
    return min(WEB_MERCATOR_MAX_LAT, max(-WEB_MERCATOR_MAX_LAT, float(lat)))


def latlon_to_tile_pixel(
    lat: float,
    lon: float,
    *,
    zoom: int = DEFAULT_TILE_ZOOM,
    tile_size: int = TILE_SIZE,
) -> tuple[float, float]:
    """Project lat/lon to slippy-map pixel coordinates at a fixed zoom."""
    lat_rad = math.radians(_clamp_latitude(lat))
    scale = float(tile_size) * (2 ** int(zoom))
    x = (float(lon) + 180.0) / 360.0 * scale
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * scale
    return float(x), float(y)


def tile_pixel_to_latlon(
    x: float,
    y: float,
    *,
    zoom: int = DEFAULT_TILE_ZOOM,
    tile_size: int = TILE_SIZE,
) -> tuple[float, float]:
    """Invert :func:`latlon_to_tile_pixel` for tests and status readouts."""
    scale = float(tile_size) * (2 ** int(zoom))
    lon = float(x) / scale * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * float(y) / scale
    lat = math.degrees(math.atan(math.sinh(n)))
    return float(lat), float(lon)


def tile_range_for_bounds(
    north: float,
    south: float,
    east: float,
    west: float,
    *,
    zoom: int = DEFAULT_TILE_ZOOM,
    tile_size: int = TILE_SIZE,
) -> tuple[range, range]:
    """Return XYZ tile x/y ranges intersecting a north/south/east/west bbox."""
    west_x, north_y = latlon_to_tile_pixel(north, west, zoom=zoom, tile_size=tile_size)
    east_x, south_y = latlon_to_tile_pixel(south, east, zoom=zoom, tile_size=tile_size)
    max_tile = (2 ** int(zoom)) - 1
    min_x = max(0, min(max_tile, int(math.floor(min(west_x, east_x) / tile_size))))
    max_x = max(0, min(max_tile, int(math.floor(max(west_x, east_x) / tile_size))))
    min_y = max(0, min(max_tile, int(math.floor(min(north_y, south_y) / tile_size))))
    max_y = max(0, min(max_tile, int(math.floor(max(north_y, south_y) / tile_size))))
    return range(min_x, max_x + 1), range(min_y, max_y + 1)


def coordinate_in_hangzhou(lat: float, lon: float) -> bool:
    return (
        float(HANGZHOU_BBOX.south) <= float(lat) <= float(HANGZHOU_BBOX.north)
        and float(HANGZHOU_BBOX.west) <= float(lon) <= float(HANGZHOU_BBOX.east)
    )


def graph_bounds(graph: nx.DiGraph) -> tuple[float, float, float, float]:
    """Return graph bounds as north, south, east, west."""
    lats = [float(attrs["lat"]) for _node, attrs in graph.nodes(data=True)]
    lons = [float(attrs["lon"]) for _node, attrs in graph.nodes(data=True)]
    return max(lats), min(lats), max(lons), min(lons)


def graph_scene_bounds(
    graph: nx.DiGraph,
    *,
    zoom: int = DEFAULT_TILE_ZOOM,
    tile_size: int = TILE_SIZE,
) -> SceneBounds:
    north, south, east, west = graph_bounds(graph)
    left, top = latlon_to_tile_pixel(north, west, zoom=zoom, tile_size=tile_size)
    right, bottom = latlon_to_tile_pixel(south, east, zoom=zoom, tile_size=tile_size)
    return SceneBounds(
        left=min(left, right),
        top=min(top, bottom),
        right=max(left, right),
        bottom=max(top, bottom),
    )


def build_edge_points(graph: nx.DiGraph) -> EdgePoints:
    """Precompute OSM edge geometry as lat/lon polylines."""
    edge_points: EdgePoints = []
    for u, v in graph.edges():
        points = edge_geometry_to_latlon(graph, int(u), int(v))
        if len(points) >= 2:
            edge_points.append((int(u), int(v), points))
    return edge_points


def build_scene_node_positions(
    graph: nx.DiGraph,
    *,
    zoom: int = DEFAULT_TILE_ZOOM,
    tile_size: int = TILE_SIZE,
) -> ScenePointLookup:
    return {
        int(node): latlon_to_tile_pixel(
            float(attrs["lat"]),
            float(attrs["lon"]),
            zoom=zoom,
            tile_size=tile_size,
        )
        for node, attrs in graph.nodes(data=True)
    }


def polyline_length_m(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += _distance_m(start, end)
    return float(total)


def point_along_polyline(points: list[tuple[float, float]], distance_m: float) -> tuple[float, float] | None:
    if not points:
        return None
    if len(points) == 1 or distance_m <= 0.0:
        return points[0]
    remaining = float(distance_m)
    for start, end in zip(points, points[1:]):
        segment = max(1.0e-9, _distance_m(start, end))
        if remaining <= segment:
            ratio = remaining / segment
            lat = float(start[0]) + (float(end[0]) - float(start[0])) * ratio
            lon = float(start[1]) + (float(end[1]) - float(start[1])) * ratio
            return float(lat), float(lon)
        remaining -= segment
    return points[-1]


def nearest_scene_node(
    node_positions: ScenePointLookup,
    scene_x: float,
    scene_y: float,
    *,
    max_distance_px: float,
) -> int | None:
    best_node: int | None = None
    best_distance_sq = float(max_distance_px) * float(max_distance_px)
    for node, (x, y) in node_positions.items():
        dx = float(x) - float(scene_x)
        dy = float(y) - float(scene_y)
        distance_sq = dx * dx + dy * dy
        if distance_sq <= best_distance_sq:
            best_node = int(node)
            best_distance_sq = distance_sq
    return best_node


def node_mapping_text(graph: nx.DiGraph, node: int) -> str:
    attrs = graph.nodes[int(node)]
    snn_index = attrs.get("snn_neuron_index", node)
    osm_id = attrs.get("original_osm_node_id", "未知")
    return (
        f"DiGraph 节点：{int(node)}\n"
        f"SNN neuron index：{int(snn_index)}\n"
        f"OSM node id：{osm_id}\n"
        f"纬度：{float(attrs['lat']):.7f}\n"
        f"经度：{float(attrs['lon']):.7f}"
    )


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    dy = (float(a[0]) - float(b[0])) * 111_000.0
    mean_lat = math.radians((float(a[0]) + float(b[0])) / 2.0)
    dx = (float(a[1]) - float(b[1])) * 111_000.0 * max(0.2, math.cos(mean_lat))
    return float((dx * dx + dy * dy) ** 0.5)


def _import_qt():
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except Exception as exc:  # pragma: no cover - depends on local desktop env
        raise RuntimeError(
            "PySide6 is required for the desktop viewer. Install it with "
            "`conda install -c conda-forge pyside6` or `pip install PySide6`."
        ) from exc
    return QtCore, QtGui, QtWidgets


def _tile_path(tile_root: Path, zoom: int, x: int, y: int) -> Path | None:
    base = Path(tile_root) / str(int(zoom)) / str(int(x))
    for suffix in SUPPORTED_TILE_EXTENSIONS:
        candidate = base / f"{int(y)}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _build_desktop_window_class(QtCore, QtGui, QtWidgets):
    class DesktopMapView(QtWidgets.QGraphicsView):
        def __init__(self, scene, parent=None):
            super().__init__(scene, parent)
            self._node_positions: ScenePointLookup = {}
            self._select_callback: Callable[[int], None] | None = None
            self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
            self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
            self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
            self.setBackgroundBrush(QtGui.QColor("#eef2f7"))

        def set_node_positions(
            self,
            node_positions: ScenePointLookup,
            select_callback: Callable[[int], None],
        ) -> None:
            self._node_positions = dict(node_positions)
            self._select_callback = select_callback

        def wheelEvent(self, event):  # noqa: N802
            factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
            self.scale(factor, factor)

        def mouseDoubleClickEvent(self, event):  # noqa: N802
            scene_pos = self.mapToScene(event.position().toPoint())
            scale = max(0.05, float(self.transform().m11()))
            node = nearest_scene_node(
                self._node_positions,
                scene_pos.x(),
                scene_pos.y(),
                max_distance_px=12.0 / scale,
            )
            if node is not None and self._select_callback is not None:
                self._select_callback(node)
                event.accept()
                return
            super().mouseDoubleClickEvent(event)

    class DesktopNavigationWindow(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("杭州 OSM SNN 桌面导航")
            self.resize(1320, 860)

            self.graph: nx.DiGraph | None = None
            self.edge_points: EdgePoints = []
            self.node_positions: ScenePointLookup = {}
            self.result: NavigationResult | None = None
            self.route_points: list[tuple[float, float]] = []
            self.route_length_m = 0.0
            self.vehicle_distance_m = 0.0
            self.last_tick = time.monotonic()
            self.tile_zoom = DEFAULT_TILE_ZOOM
            self.tile_root = DEFAULT_OSM_TILE_ROOT

            self.scene = QtWidgets.QGraphicsScene(self)
            self.view = DesktopMapView(self.scene, self)
            self.timer = QtCore.QTimer(self)
            self.timer.setInterval(100)
            self.timer.timeout.connect(self._advance_vehicle)

            self.road_item = None
            self.node_item = None
            self.route_item = None
            self.car_item = None
            self.start_item = None
            self.goal_item = None
            self.selected_item = None

            self._build_ui()
            self._set_default_coordinates_from_bbox()

        def _build_ui(self) -> None:
            root = QtWidgets.QWidget(self)
            layout = QtWidgets.QHBoxLayout(root)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(8)
            self.setCentralWidget(root)

            panel = QtWidgets.QWidget(root)
            panel.setFixedWidth(340)
            panel_layout = QtWidgets.QVBoxLayout(panel)
            panel_layout.setContentsMargins(0, 0, 0, 0)
            panel_layout.setSpacing(8)
            layout.addWidget(panel)
            layout.addWidget(self.view, stretch=1)

            title = QtWidgets.QLabel("杭州 OSM SNN 桌面导航")
            title_font = title.font()
            title_font.setPointSize(15)
            title_font.setBold(True)
            title.setFont(title_font)
            panel_layout.addWidget(title)
            panel_layout.addWidget(QtWidgets.QLabel(f"地图区域：{DEFAULT_FIXED_MAP_REGION}"))

            self.network_combo = QtWidgets.QComboBox()
            self.network_combo.addItems(["drive", "walk", "bike", "all"])
            self.network_combo.setToolTip("drive 会保留真实机动车道路方向")
            panel_layout.addWidget(QtWidgets.QLabel("道路网络类型"))
            panel_layout.addWidget(self.network_combo)

            self.load_button = QtWidgets.QPushButton("加载杭州地图")
            self.load_button.clicked.connect(self.load_map)
            panel_layout.addWidget(self.load_button)

            panel_layout.addSpacing(6)
            self.start_lat = self._spinbox(HANGZHOU_BBOX.south, HANGZHOU_BBOX.north)
            self.start_lon = self._spinbox(HANGZHOU_BBOX.west, HANGZHOU_BBOX.east)
            self.goal_lat = self._spinbox(HANGZHOU_BBOX.south, HANGZHOU_BBOX.north)
            self.goal_lon = self._spinbox(HANGZHOU_BBOX.west, HANGZHOU_BBOX.east)
            for label, widget in [
                ("起点纬度", self.start_lat),
                ("起点经度", self.start_lon),
                ("终点纬度", self.goal_lat),
                ("终点经度", self.goal_lon),
            ]:
                panel_layout.addWidget(QtWidgets.QLabel(label))
                panel_layout.addWidget(widget)

            self.use_loihi = QtWidgets.QCheckBox("使用 Brian2Loihi 后端（不可用时自动回退）")
            self.use_loihi.setChecked(False)
            panel_layout.addWidget(self.use_loihi)

            self.run_button = QtWidgets.QPushButton("运行 SNN 导航")
            self.run_button.clicked.connect(self.run_snn_navigation)
            panel_layout.addWidget(self.run_button)

            panel_layout.addSpacing(6)
            self.speed_input = QtWidgets.QDoubleSpinBox()
            self.speed_input.setRange(1.0, 80.0)
            self.speed_input.setDecimals(1)
            self.speed_input.setSingleStep(1.0)
            self.speed_input.setValue(13.9)
            panel_layout.addWidget(QtWidgets.QLabel("车辆速度（米/秒）"))
            panel_layout.addWidget(self.speed_input)

            controls = QtWidgets.QHBoxLayout()
            self.start_button = QtWidgets.QPushButton("开始")
            self.pause_button = QtWidgets.QPushButton("暂停")
            self.finish_button = QtWidgets.QPushButton("结束")
            self.start_button.clicked.connect(self.start_vehicle)
            self.pause_button.clicked.connect(self.pause_vehicle)
            self.finish_button.clicked.connect(self.finish_vehicle)
            controls.addWidget(self.start_button)
            controls.addWidget(self.pause_button)
            controls.addWidget(self.finish_button)
            panel_layout.addLayout(controls)

            self.reset_view_button = QtWidgets.QPushButton("重置视图")
            self.reset_view_button.clicked.connect(self.fit_map_view)
            panel_layout.addWidget(self.reset_view_button)

            self.status_label = QtWidgets.QLabel("请先加载杭州地图。")
            self.status_label.setWordWrap(True)
            panel_layout.addWidget(self.status_label)

            self.route_label = QtWidgets.QLabel("路线：未运行")
            self.route_label.setWordWrap(True)
            panel_layout.addWidget(self.route_label)

            panel_layout.addWidget(QtWidgets.QLabel("节点映射（双击地图节点查看）"))
            self.node_text = QtWidgets.QPlainTextEdit()
            self.node_text.setReadOnly(True)
            self.node_text.setMaximumBlockCount(80)
            panel_layout.addWidget(self.node_text, stretch=1)

        def _spinbox(self, minimum: float, maximum: float):
            widget = QtWidgets.QDoubleSpinBox()
            widget.setRange(float(minimum), float(maximum))
            widget.setDecimals(7)
            widget.setSingleStep(0.0005)
            return widget

        def _set_default_coordinates_from_bbox(self) -> None:
            self.start_lat.setValue((HANGZHOU_BBOX.north + HANGZHOU_BBOX.south) / 2.0 + 0.035)
            self.start_lon.setValue((HANGZHOU_BBOX.east + HANGZHOU_BBOX.west) / 2.0 - 0.050)
            self.goal_lat.setValue((HANGZHOU_BBOX.north + HANGZHOU_BBOX.south) / 2.0 - 0.030)
            self.goal_lon.setValue((HANGZHOU_BBOX.east + HANGZHOU_BBOX.west) / 2.0 + 0.055)

        def _set_default_coordinates_from_graph(self) -> None:
            if self.graph is None:
                self._set_default_coordinates_from_bbox()
                return
            north, south, east, west = graph_bounds(self.graph)
            self.start_lat.setValue(south + (north - south) * 0.70)
            self.start_lon.setValue(west + (east - west) * 0.30)
            self.goal_lat.setValue(south + (north - south) * 0.30)
            self.goal_lon.setValue(west + (east - west) * 0.72)

        def load_map(self) -> None:
            self._set_status("正在加载杭州地图缓存...")
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            try:
                network_type = self.network_combo.currentText()
                osm_graph = load_hangzhou_graph(network_type=network_type)
                self.graph = osmnx_multidigraph_to_digraph(osm_graph)
                self.edge_points = build_edge_points(self.graph)
                self.node_positions = build_scene_node_positions(self.graph, zoom=self.tile_zoom)
                self.result = None
                self.route_points = []
                self.route_length_m = 0.0
                self.vehicle_distance_m = 0.0
                self.timer.stop()
                self._set_default_coordinates_from_graph()
                self.draw_map()
                self.fit_map_view()
                self.route_label.setText("路线：未运行")
                self.node_text.clear()
                self._set_status(
                    f"杭州地图加载完成：节点 {self.graph.number_of_nodes()}，边 {self.graph.number_of_edges()}。"
                    "双击节点可查看 DiGraph/SNN/OSM 映射。"
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(
                    self,
                    "杭州地图加载失败",
                    f"{exc}\n\n请检查 data/osm_cache/hangzhou_drive.graphml 等缓存文件，或确认网络可用。",
                )
                self._set_status("杭州地图加载失败。")
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

        def draw_map(self) -> None:
            if self.graph is None:
                return
            self.scene.clear()
            self.road_item = None
            self.node_item = None
            self.route_item = None
            self.car_item = None
            self.start_item = None
            self.goal_item = None
            self.selected_item = None

            bounds = graph_scene_bounds(self.graph, zoom=self.tile_zoom)
            margin = 512.0
            self.scene.setSceneRect(
                bounds.left - margin,
                bounds.top - margin,
                bounds.width + margin * 2,
                bounds.height + margin * 2,
            )
            loaded_tiles = self._add_osm_tiles()
            self._add_road_layer()
            self._add_node_layer()
            self.view.set_node_positions(self.node_positions, self.select_node)
            if loaded_tiles == 0:
                self._set_status(
                    "未检测到本地 OSM 栅格瓦片，当前显示本地道路几何、节点、路线和车辆。"
                    "如需完整 OSM 样式，请放置 data/tiles/osm/{z}/{x}/{y}.png。"
                )
            self._draw_navigation_layers()

        def _add_osm_tiles(self) -> int:
            if self.graph is None:
                return 0
            north, south, east, west = graph_bounds(self.graph)
            x_range, y_range = tile_range_for_bounds(
                north,
                south,
                east,
                west,
                zoom=self.tile_zoom,
            )
            loaded = 0
            for x in x_range:
                for y in y_range:
                    path = _tile_path(self.tile_root, self.tile_zoom, x, y)
                    if path is None:
                        continue
                    pixmap = QtGui.QPixmap(str(path))
                    if pixmap.isNull():
                        continue
                    item = self.scene.addPixmap(pixmap)
                    item.setPos(float(x * TILE_SIZE), float(y * TILE_SIZE))
                    item.setZValue(-100)
                    loaded += 1
            return loaded

        def _add_road_layer(self) -> None:
            path = QtGui.QPainterPath()
            for _u, _v, points in self.edge_points:
                first = True
                for lat, lon in points:
                    x, y = latlon_to_tile_pixel(lat, lon, zoom=self.tile_zoom)
                    if first:
                        path.moveTo(x, y)
                        first = False
                    else:
                        path.lineTo(x, y)
            self.road_item = QtWidgets.QGraphicsPathItem(path)
            pen = QtGui.QPen(QtGui.QColor("#64748b"))
            pen.setWidthF(1.1)
            pen.setCosmetic(True)
            self.road_item.setPen(pen)
            self.road_item.setZValue(-10)
            self.scene.addItem(self.road_item)

        def _add_node_layer(self) -> None:
            path = QtGui.QPainterPath()
            # 节点代表 DiGraph node / SNN neuron。半径略大于道路宽度，确保缩放到
            # 杭州全图时仍能看到节点分布。
            radius = 3.0
            for x, y in self.node_positions.values():
                path.addEllipse(QtCore.QPointF(float(x), float(y)), radius, radius)
            self.node_item = QtWidgets.QGraphicsPathItem(path)
            pen = QtGui.QPen(QtGui.QColor("#1d4ed8"))
            pen.setWidthF(1.0)
            pen.setCosmetic(True)
            self.node_item.setPen(pen)
            color = QtGui.QColor("#2563eb")
            color.setAlpha(120)
            self.node_item.setBrush(QtGui.QBrush(color))
            self.node_item.setZValue(5)
            self.scene.addItem(self.node_item)

        def run_snn_navigation(self) -> None:
            if self.graph is None:
                self.load_map()
                if self.graph is None:
                    return
            start_lat = float(self.start_lat.value())
            start_lon = float(self.start_lon.value())
            goal_lat = float(self.goal_lat.value())
            goal_lon = float(self.goal_lon.value())
            errors = []
            if not coordinate_in_hangzhou(start_lat, start_lon):
                errors.append("起点坐标不在浙江省杭州市范围内。")
            if not coordinate_in_hangzhou(goal_lat, goal_lon):
                errors.append("终点坐标不在浙江省杭州市范围内。")
            if errors:
                QtWidgets.QMessageBox.warning(self, "坐标范围错误", "\n".join(errors))
                return

            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
            self._set_status("正在吸附起终点并运行 SNN 导航...")
            try:
                start_node = nearest_node_by_latlon(self.graph, start_lat, start_lon)
                goal_node = nearest_node_by_latlon(self.graph, goal_lat, goal_lon)
                if start_node != goal_node and not nx.has_path(self.graph, start_node, goal_node):
                    QtWidgets.QMessageBox.warning(
                        self,
                        "路径不可达",
                        "从当前起点到终点不存在有向可达路径。请调整起终点坐标或切换道路网络类型。",
                    )
                    self._set_status("导航失败：起点到终点不可达。")
                    return
                self.result = run_navigation(
                    self.graph,
                    start_node,
                    goal_node,
                    use_loihi=bool(self.use_loihi.isChecked()),
                )
                if not self.result.path_nodes:
                    error = self.result.metadata.get("error") or "目标节点未在 wavefront 中发放。"
                    QtWidgets.QMessageBox.warning(self, "导航失败", str(error))
                    self._set_status(f"导航失败：{error}")
                    return
                self.route_points = path_nodes_to_latlon(self.graph, self.result.path_nodes)
                self.route_length_m = polyline_length_m(self.route_points)
                self.vehicle_distance_m = 0.0
                self.timer.stop()
                self._draw_navigation_layers()
                self.fit_map_view()
                self.route_label.setText(
                    "路线："
                    f"起点节点 {self.result.start_node} -> 终点节点 {self.result.goal_node}\n"
                    f"路径节点 {len(self.result.path_nodes)}，长度 {self.route_length_m:.1f} 米，"
                    f"后端 {self.result.metadata.get('backend')}"
                )
                self._set_status("导航成功。点击“开始”后车辆沿红色路线自动行驶。")
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "SNN 导航异常", str(exc))
                self._set_status("SNN 导航异常。")
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()

        def _draw_navigation_layers(self) -> None:
            for item_name in ["route_item", "car_item", "start_item", "goal_item", "selected_item"]:
                item = getattr(self, item_name)
                if item is not None and item.scene() is self.scene:
                    self.scene.removeItem(item)
                setattr(self, item_name, None)
            if self.graph is None or self.result is None or not self.result.path_nodes:
                return
            self._add_marker(self.result.start_node, "#16a34a", "start_item")
            self._add_marker(self.result.goal_node, "#7e22ce", "goal_item")
            route_path = QtGui.QPainterPath()
            first = True
            for lat, lon in self.route_points:
                x, y = latlon_to_tile_pixel(lat, lon, zoom=self.tile_zoom)
                if first:
                    route_path.moveTo(x, y)
                    first = False
                else:
                    route_path.lineTo(x, y)
            self.route_item = QtWidgets.QGraphicsPathItem(route_path)
            pen = QtGui.QPen(QtGui.QColor("#dc2626"))
            pen.setWidthF(4.5)
            pen.setCosmetic(True)
            self.route_item.setPen(pen)
            self.route_item.setZValue(20)
            self.scene.addItem(self.route_item)
            self._update_vehicle_marker()

        def _add_marker(self, node: int, color: str, attr_name: str) -> None:
            x, y = self.node_positions[int(node)]
            item = QtWidgets.QGraphicsEllipseItem(-7, -7, 14, 14)
            item.setBrush(QtGui.QBrush(QtGui.QColor(color)))
            item.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2))
            item.setPos(float(x), float(y))
            item.setZValue(35)
            item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            self.scene.addItem(item)
            setattr(self, attr_name, item)

        def _update_vehicle_marker(self) -> None:
            if not self.route_points:
                return
            point = point_along_polyline(self.route_points, self.vehicle_distance_m)
            if point is None:
                return
            x, y = latlon_to_tile_pixel(point[0], point[1], zoom=self.tile_zoom)
            if self.car_item is None or self.car_item.scene() is not self.scene:
                self.car_item = QtWidgets.QGraphicsEllipseItem(-8, -8, 16, 16)
                self.car_item.setBrush(QtGui.QBrush(QtGui.QColor("#ef4444")))
                self.car_item.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2))
                self.car_item.setZValue(45)
                self.car_item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                self.scene.addItem(self.car_item)
            self.car_item.setPos(float(x), float(y))

        def start_vehicle(self) -> None:
            if not self.route_points:
                QtWidgets.QMessageBox.information(self, "未生成路线", "请先运行 SNN 导航。")
                return
            if self.vehicle_distance_m >= self.route_length_m:
                self.vehicle_distance_m = 0.0
            self.last_tick = time.monotonic()
            self.timer.start()
            self._set_status("车辆正在自动行驶。")

        def pause_vehicle(self) -> None:
            self.timer.stop()
            self._set_status("导航已暂停，车辆停留在当前位置。")

        def finish_vehicle(self) -> None:
            self.timer.stop()
            self.vehicle_distance_m = 0.0
            self._update_vehicle_marker()
            self._set_status("导航已结束。")

        def _advance_vehicle(self) -> None:
            now = time.monotonic()
            dt = max(0.0, min(1.0, now - self.last_tick))
            self.last_tick = now
            self.vehicle_distance_m += float(self.speed_input.value()) * dt
            if self.vehicle_distance_m >= self.route_length_m:
                self.vehicle_distance_m = self.route_length_m
                self.timer.stop()
                self._update_vehicle_marker()
                self._set_status("车辆已到达终点。")
                return
            self._update_vehicle_marker()
            self._set_status(
                f"车辆正在自动行驶：{self.vehicle_distance_m:.1f}/{self.route_length_m:.1f} 米。"
            )

        def select_node(self, node: int) -> None:
            if self.graph is None:
                return
            if self.selected_item is not None and self.selected_item.scene() is self.scene:
                self.scene.removeItem(self.selected_item)
            x, y = self.node_positions[int(node)]
            self.selected_item = QtWidgets.QGraphicsEllipseItem(-9, -9, 18, 18)
            self.selected_item.setBrush(QtGui.QBrush(QtGui.QColor("#f59e0b")))
            self.selected_item.setPen(QtGui.QPen(QtGui.QColor("#111827"), 2))
            self.selected_item.setPos(float(x), float(y))
            self.selected_item.setZValue(50)
            self.selected_item.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            self.scene.addItem(self.selected_item)
            self.node_text.setPlainText(node_mapping_text(self.graph, int(node)))
            self._set_status(f"已选中 DiGraph/SNN 节点 {int(node)}。")

        def fit_map_view(self) -> None:
            if self.graph is None:
                return
            bounds = graph_scene_bounds(self.graph, zoom=self.tile_zoom)
            rect = QtCore.QRectF(bounds.left, bounds.top, bounds.width, bounds.height)
            self.view.fitInView(rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)

        def _set_status(self, message: str) -> None:
            self.status_label.setText(str(message))

    return DesktopNavigationWindow


def main() -> int:
    QtCore, QtGui, QtWidgets = _import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window_class = _build_desktop_window_class(QtCore, QtGui, QtWidgets)
    window = window_class()
    window.show()
    return int(app.exec())


if __name__ == "__main__":  # pragma: no cover - manual desktop entrypoint
    raise SystemExit(main())
