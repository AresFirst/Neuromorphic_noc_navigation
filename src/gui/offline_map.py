"""Map renderer for the Streamlit GUI.

The default browser view preserves the familiar OpenStreetMap raster style.
Local vector/raster assets are still supported so the GUI can run fully offline
when the corresponding files are prepared under ``data/offline_map`` and
``data/tiles``.
"""

from __future__ import annotations

import json
import mimetypes
import sqlite3
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import networkx as nx

from maps import edge_geometry_to_latlon, path_nodes_to_latlon
from navigation import NavigationResult, WavefrontFrame
from traffic import TrafficSnapshot

EdgePoints = list[tuple[int, int, list[tuple[float, float]]]]
EdgePointLookup = dict[tuple[int, int], list[tuple[float, float]]]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OFFLINE_MAP_DIR = PROJECT_ROOT / "data" / "offline_map"
OFFLINE_ASSET_DIR = OFFLINE_MAP_DIR / "assets"
OFFLINE_TILE_DIR = PROJECT_ROOT / "data" / "tiles"
DEFAULT_MBTILES_PATH = OFFLINE_TILE_DIR / "hangzhou.mbtiles"
DEFAULT_PMTILES_PATH = OFFLINE_TILE_DIR / "hangzhou.pmtiles"
LOCAL_OSM_RASTER_TILE_DIR = OFFLINE_TILE_DIR / "osm"
MAPLIBRE_JS_PATH = OFFLINE_ASSET_DIR / "maplibre-gl.js"
MAPLIBRE_CSS_PATH = OFFLINE_ASSET_DIR / "maplibre-gl.css"
PMTILES_JS_PATH = OFFLINE_ASSET_DIR / "pmtiles.js"
LEAFLET_JS_PATH = OFFLINE_ASSET_DIR / "leaflet.js"
LEAFLET_CSS_PATH = OFFLINE_ASSET_DIR / "leaflet.css"
LEAFLET_JS_CDN = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
LEAFLET_CSS_CDN = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
OSM_ONLINE_RASTER_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = "&copy; OpenStreetMap contributors"
OSM_RASTER_RENDERER_NAME = "OpenStreetMap 标准样式"
LOCAL_OSM_RASTER_RENDERER_NAME = "OpenStreetMap 本地瓦片样式"
MAP_RENDERER_NAME = "MapLibre 本地矢量瓦片"
CANVAS_FALLBACK_RENDERER_NAME = "Canvas 离线降级渲染"
RASTER_TILE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


@dataclass(frozen=True)
class OfflineMapRuntime:
    renderer: str
    server_url: str | None
    leaflet_js_url: str | None
    leaflet_css_url: str | None
    raster_tile_url: str | None
    raster_attribution: str | None
    maplibre_js_url: str | None
    maplibre_css_url: str | None
    pmtiles_js_url: str | None
    tilejson_url: str | None
    pmtiles_url: str | None
    vector_layers: list[dict[str, Any]]
    messages: tuple[str, ...]

    @property
    def uses_maplibre(self) -> bool:
        return self.maplibre_js_url is not None and self.maplibre_css_url is not None

    @property
    def uses_leaflet_raster(self) -> bool:
        return (
            self.leaflet_js_url is not None
            and self.leaflet_css_url is not None
            and self.raster_tile_url is not None
        )


_SERVER_LOCK = threading.Lock()
_SERVER: ThreadingHTTPServer | None = None
_SERVER_THREAD: threading.Thread | None = None
_SERVER_URL: str | None = None


def _latlon_to_lonlat(points: list[tuple[float, float]]) -> list[list[float]]:
    return [[float(lon), float(lat)] for lat, lon in points]


def _line_feature(points: list[tuple[float, float]], properties: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if len(points) < 2:
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": _latlon_to_lonlat(points)},
        "properties": properties or {},
    }


def _point_feature(point: tuple[float, float], properties: dict[str, Any]) -> dict[str, Any]:
    lat, lon = point
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
        "properties": properties,
    }


def _feature_collection(features: list[dict[str, Any] | None]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [feature for feature in features if feature is not None]}


def _points_for_edge(
    edge_lookup: EdgePointLookup,
    graph: nx.DiGraph,
    u: int,
    v: int,
) -> list[tuple[float, float]]:
    points = edge_lookup.get((int(u), int(v)))
    if points is not None:
        return points
    return edge_geometry_to_latlon(graph, int(u), int(v))


def _graph_bounds(graph: nx.DiGraph, path_points: list[tuple[float, float]]) -> list[list[float]]:
    if len(path_points) >= 2:
        lats = [point[0] for point in path_points]
        lons = [point[1] for point in path_points]
    else:
        lats = [float(attrs["lat"]) for _node, attrs in graph.nodes(data=True)]
        lons = [float(attrs["lon"]) for _node, attrs in graph.nodes(data=True)]
    return [[min(lons), min(lats)], [max(lons), max(lats)]]


def _graph_center(graph: nx.DiGraph) -> list[float]:
    lats = [float(attrs["lat"]) for _node, attrs in graph.nodes(data=True)]
    lons = [float(attrs["lon"]) for _node, attrs in graph.nodes(data=True)]
    return [sum(lons) / len(lons), sum(lats) / len(lats)]


def _traffic_color(congestion: float, blocked: bool) -> str:
    if blocked or congestion >= 0.90:
        return "#7f1d1d"
    if congestion >= 0.70:
        return "#dc2626"
    if congestion >= 0.40:
        return "#facc15"
    return "#16a34a"


def _edge_collection(
    graph: nx.DiGraph,
    edge_lookup: EdgePointLookup,
    edges: list[tuple[int, int]],
    *,
    color: str,
    width: float,
    opacity: float,
    dash: bool = False,
) -> dict[str, Any]:
    features: list[dict[str, Any] | None] = []
    for u, v in edges:
        features.append(
            _line_feature(
                _points_for_edge(edge_lookup, graph, int(u), int(v)),
                {"color": color, "width": width, "opacity": opacity, "dash": dash},
            )
        )
    return _feature_collection(features)


def build_offline_map_payload(
    graph: nx.DiGraph,
    edge_points: EdgePoints,
    edge_lookup: EdgePointLookup,
    *,
    result: NavigationResult | None,
    start_node: int,
    goal_node: int,
    car_point: tuple[float, float] | None,
    traffic_snapshot: TrafficSnapshot | None,
    previous_route: list[int],
    wavefront_frame: WavefrontFrame,
    inflight_edges: list[tuple[int, int]],
    draw_base_roads: bool,
    max_base_edges: int,
    max_traffic_edges: int,
    max_wavefront_nodes: int,
) -> dict[str, Any]:
    """Build a compact GeoJSON payload consumed by the offline map component."""
    path_points = path_nodes_to_latlon(graph, result.path_nodes) if result else []
    if car_point is None and path_points:
        car_point = path_points[0]

    base_features: list[dict[str, Any] | None] = []
    if draw_base_roads:
        for _u, _v, points in edge_points[: int(max_base_edges)]:
            base_features.append(_line_feature(points, {"color": "#64748b", "width": 1.0, "opacity": 0.34}))

    traffic_features: list[dict[str, Any] | None] = []
    if traffic_snapshot is not None:
        ranked_states = sorted(
            traffic_snapshot.edge_states.values(),
            key=lambda state: (state.blocked, state.congestion, state.vehicle_count),
            reverse=True,
        )
        for state in ranked_states[: int(max_traffic_edges)]:
            u, v = state.edge
            traffic_features.append(
                _line_feature(
                    _points_for_edge(edge_lookup, graph, u, v),
                    {
                        "color": _traffic_color(float(state.congestion), bool(state.blocked)),
                        "width": 6.0 if state.blocked else 4.0,
                        "opacity": 0.82,
                        "dash": bool(state.blocked),
                        "tooltip": f"交通路段 {u}->{v}，拥堵={state.congestion:.2f}，车辆={state.vehicle_count}",
                    },
                )
            )

    path_feature = _line_feature(path_points, {"color": "#dc2626", "width": 6.0, "opacity": 0.95})
    previous_route_feature = _line_feature(
        path_nodes_to_latlon(graph, previous_route),
        {"color": "#f97316", "width": 4.0, "opacity": 0.72, "dash": True},
    )
    active_wave_edges = _edge_collection(
        graph,
        edge_lookup,
        [(int(u), int(v)) for u, v in wavefront_frame.active_edges[: max(0, int(max_wavefront_nodes) * 3)]],
        color="#06b6d4",
        width=2.0,
        opacity=0.58,
    )
    inflight_wave_edges = _edge_collection(
        graph,
        edge_lookup,
        [(int(u), int(v)) for u, v in inflight_edges[: max(0, int(max_wavefront_nodes) * 3)]],
        color="#f59e0b",
        width=3.0,
        opacity=0.62,
        dash=True,
    )

    wave_node_features: list[dict[str, Any]] = []
    for node in wavefront_frame.active_nodes[: int(max_wavefront_nodes)]:
        if node not in graph:
            continue
        attrs = graph.nodes[int(node)]
        wave_node_features.append(
            _point_feature(
                (float(attrs["lat"]), float(attrs["lon"])),
                {"color": "#0e7490", "radius": 4.0, "opacity": 0.62, "kind": "wavefront"},
            )
        )

    marker_features = [
        _point_feature(
            (float(graph.nodes[start_node]["lat"]), float(graph.nodes[start_node]["lon"])),
            {"kind": "start", "label": "起点", "color": "#16a34a", "radius": 8.0},
        ),
        _point_feature(
            (float(graph.nodes[goal_node]["lat"]), float(graph.nodes[goal_node]["lon"])),
            {"kind": "goal", "label": "终点", "color": "#7e22ce", "radius": 8.0},
        ),
    ]
    if car_point is not None:
        marker_features.append(
            _point_feature(car_point, {"kind": "car", "label": "车辆", "color": "#dc2626", "radius": 9.0})
        )

    return {
        "center": _graph_center(graph),
        "bounds": _graph_bounds(graph, path_points),
        "baseRoads": _feature_collection(base_features),
        "traffic": _feature_collection(traffic_features),
        "path": _feature_collection([path_feature]),
        "previousRoute": _feature_collection([previous_route_feature]),
        "wavefrontEdges": active_wave_edges,
        "wavefrontInflight": inflight_wave_edges,
        "wavefrontNodes": _feature_collection(wave_node_features),
        "markers": _feature_collection(marker_features),
    }


def _read_mbtiles_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    metadata: dict[str, Any] = {}
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        rows = conn.execute("select name, value from metadata").fetchall()
    for name, value in rows:
        metadata[str(name)] = str(value)
    raw_json = metadata.get("json")
    if raw_json:
        try:
            metadata["parsed_json"] = json.loads(raw_json)
        except json.JSONDecodeError:
            metadata["parsed_json"] = {}
    else:
        metadata["parsed_json"] = {}
    return metadata


def _vector_layers_from_metadata(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    parsed = metadata.get("parsed_json") if isinstance(metadata.get("parsed_json"), dict) else {}
    layers = parsed.get("vector_layers") if isinstance(parsed, dict) else []
    if isinstance(layers, list):
        return [layer for layer in layers if isinstance(layer, dict) and layer.get("id")]
    return []


def _tilejson(metadata: dict[str, Any], server_url: str) -> dict[str, Any]:
    bounds = [119.95, 30.08, 120.36, 30.42]
    if metadata.get("bounds"):
        try:
            bounds = [float(item) for item in str(metadata["bounds"]).split(",")]
        except ValueError:
            pass
    return {
        "tilejson": "3.0.0",
        "name": metadata.get("name", "hangzhou"),
        "scheme": metadata.get("scheme", "tms"),
        "tiles": [f"{server_url}/tiles/{{z}}/{{x}}/{{y}}.pbf"],
        "minzoom": int(float(metadata.get("minzoom", 0) or 0)),
        "maxzoom": int(float(metadata.get("maxzoom", 14) or 14)),
        "bounds": bounds,
        "vector_layers": _vector_layers_from_metadata(metadata),
    }


def _serve_bytes(
    handler: BaseHTTPRequestHandler,
    payload: bytes,
    *,
    content_type: str,
    status: HTTPStatus = HTTPStatus.OK,
    extra_headers: dict[str, str] | None = None,
) -> None:
    handler.send_response(int(status))
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Cache-Control", "public, max-age=3600")
    for key, value in (extra_headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(payload)


def _make_handler(
    *,
    asset_dir: Path,
    mbtiles_path: Path,
    pmtiles_path: Path,
    raster_tile_dir: Path,
    metadata: dict[str, Any],
    server_url_getter,
):
    class OfflineMapRequestHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *args: Any) -> None:
            return

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
            self.end_headers()

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path == "/tilejson.json":
                payload = json.dumps(_tilejson(metadata, server_url_getter()), ensure_ascii=False).encode("utf-8")
                _serve_bytes(self, payload, content_type="application/json; charset=utf-8")
                return
            if path.startswith("/assets/"):
                self._serve_static(asset_dir, path.removeprefix("/assets/"))
                return
            if path.startswith("/pmtiles/"):
                self._serve_file_with_range(pmtiles_path)
                return
            if path.startswith("/osm/"):
                self._serve_static(raster_tile_dir, path.removeprefix("/osm/"))
                return
            if path.startswith("/tiles/"):
                self._serve_mbtiles(path)
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def _serve_static(self, root: Path, relative: str) -> None:
            candidate = (root / relative).resolve()
            if root.resolve() not in candidate.parents and candidate != root.resolve():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not candidate.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            self._serve_file_with_range(candidate, content_type=content_type)

        def _serve_file_with_range(self, path: Path, content_type: str = "application/octet-stream") -> None:
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            data = path.read_bytes()
            range_header = self.headers.get("Range")
            if not range_header:
                _serve_bytes(self, data, content_type=content_type, extra_headers={"Accept-Ranges": "bytes"})
                return
            try:
                unit, values = range_header.split("=", 1)
                if unit.strip() != "bytes":
                    raise ValueError
                start_text, end_text = values.split("-", 1)
                start = int(start_text) if start_text else 0
                end = int(end_text) if end_text else len(data) - 1
                start = max(0, start)
                end = min(len(data) - 1, end)
                if start > end:
                    raise ValueError
            except ValueError:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            chunk = data[start : end + 1]
            _serve_bytes(
                self,
                chunk,
                content_type=content_type,
                status=HTTPStatus.PARTIAL_CONTENT,
                extra_headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {start}-{end}/{len(data)}",
                },
            )

        def _serve_mbtiles(self, path: str) -> None:
            if not mbtiles_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            parts = path.strip("/").split("/")
            if len(parts) != 4:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                z = int(parts[1])
                x = int(parts[2])
                y = int(parts[3].split(".", 1)[0])
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            scheme = str(metadata.get("scheme", "tms")).lower()
            tile_row = y if scheme == "xyz" else (1 << z) - 1 - y
            with sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True) as conn:
                row = conn.execute(
                    "select tile_data from tiles where zoom_level=? and tile_column=? and tile_row=?",
                    (z, x, tile_row),
                ).fetchone()
            if row is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            tile_data = bytes(row[0])
            headers = {}
            if tile_data[:2] == b"\x1f\x8b":
                headers["Content-Encoding"] = "gzip"
            _serve_bytes(self, tile_data, content_type="application/x-protobuf", extra_headers=headers)

    return OfflineMapRequestHandler


def _ensure_server(
    asset_dir: Path,
    mbtiles_path: Path,
    pmtiles_path: Path,
    raster_tile_dir: Path,
    metadata: dict[str, Any],
) -> str:
    global _SERVER, _SERVER_THREAD, _SERVER_URL
    with _SERVER_LOCK:
        if _SERVER is not None and _SERVER_URL is not None:
            return _SERVER_URL

        def current_url() -> str:
            if _SERVER_URL is None:
                return ""
            return _SERVER_URL

        handler = _make_handler(
            asset_dir=asset_dir,
            mbtiles_path=mbtiles_path,
            pmtiles_path=pmtiles_path,
            raster_tile_dir=raster_tile_dir,
            metadata=metadata,
            server_url_getter=current_url,
        )
        _SERVER = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        host, port = _SERVER.server_address
        _SERVER_URL = f"http://{host}:{port}"
        _SERVER_THREAD = threading.Thread(target=_SERVER.serve_forever, name="offline-map-server", daemon=True)
        _SERVER_THREAD.start()
        return _SERVER_URL


def _detect_local_raster_tile_extension(tile_dir: Path) -> str | None:
    """Return the first supported local raster tile extension under z/x/y files."""
    if not tile_dir.is_dir():
        return None
    for z_dir in tile_dir.iterdir():
        if not z_dir.is_dir():
            continue
        for x_dir in z_dir.iterdir():
            if not x_dir.is_dir():
                continue
            for tile_file in x_dir.iterdir():
                suffix = tile_file.suffix.lower()
                if tile_file.is_file() and suffix in RASTER_TILE_EXTENSIONS:
                    return suffix.lstrip(".")
    return None


def get_offline_map_runtime(
    *,
    asset_dir: Path = OFFLINE_ASSET_DIR,
    mbtiles_path: Path = DEFAULT_MBTILES_PATH,
    pmtiles_path: Path = DEFAULT_PMTILES_PATH,
    raster_tile_dir: Path = LOCAL_OSM_RASTER_TILE_DIR,
    allow_online_osm: bool = True,
) -> OfflineMapRuntime:
    """Return available map rendering resources.

    The common online case keeps the original OpenStreetMap raster style. For a
    fully offline OSM-looking map, prepare local Leaflet assets and raster tiles.
    """
    has_maplibre = (asset_dir / MAPLIBRE_JS_PATH.name).is_file() and (asset_dir / MAPLIBRE_CSS_PATH.name).is_file()
    has_leaflet = (asset_dir / LEAFLET_JS_PATH.name).is_file() and (asset_dir / LEAFLET_CSS_PATH.name).is_file()
    has_mbtiles = mbtiles_path.is_file()
    has_pmtiles = pmtiles_path.is_file()
    has_pmtiles_js = (asset_dir / PMTILES_JS_PATH.name).is_file()
    raster_extension = _detect_local_raster_tile_extension(raster_tile_dir)
    metadata = _read_mbtiles_metadata(mbtiles_path) if has_mbtiles else {}
    vector_layers = _vector_layers_from_metadata(metadata)
    messages: list[str] = []

    if has_maplibre and (has_mbtiles or (has_pmtiles and has_pmtiles_js)):
        server_url = _ensure_server(asset_dir, mbtiles_path, pmtiles_path, raster_tile_dir, metadata)
        if has_mbtiles:
            messages.append("已检测到本地 MBTiles，MapLibre 将使用离线矢量瓦片。")
        else:
            messages.append("已检测到本地 PMTiles，MapLibre 将使用离线矢量瓦片。")
        return OfflineMapRuntime(
            renderer=MAP_RENDERER_NAME,
            server_url=server_url,
            leaflet_js_url=None,
            leaflet_css_url=None,
            raster_tile_url=None,
            raster_attribution=None,
            maplibre_js_url=f"{server_url}/assets/{MAPLIBRE_JS_PATH.name}",
            maplibre_css_url=f"{server_url}/assets/{MAPLIBRE_CSS_PATH.name}",
            pmtiles_js_url=f"{server_url}/assets/{PMTILES_JS_PATH.name}" if has_pmtiles_js else None,
            tilejson_url=f"{server_url}/tilejson.json" if has_mbtiles else None,
            pmtiles_url=f"pmtiles://{server_url}/pmtiles/{pmtiles_path.name}"
            if has_pmtiles and has_pmtiles_js
            else None,
            vector_layers=vector_layers,
            messages=tuple(messages),
        )

    if raster_extension is not None:
        server_url = _ensure_server(asset_dir, mbtiles_path, pmtiles_path, raster_tile_dir, metadata)
        leaflet_js_url = f"{server_url}/assets/{LEAFLET_JS_PATH.name}" if has_leaflet else LEAFLET_JS_CDN
        leaflet_css_url = f"{server_url}/assets/{LEAFLET_CSS_PATH.name}" if has_leaflet else LEAFLET_CSS_CDN
        messages.append("已检测到本地 OpenStreetMap 栅格瓦片，底图将优先从 data/tiles/osm 离线加载。")
        if not has_leaflet:
            messages.append(
                "未检测到本地 Leaflet 资源，当前 Leaflet 前端资源会从 CDN 加载；"
                "完全断网使用请放置 data/offline_map/assets/leaflet.js 和 leaflet.css。"
            )
        return OfflineMapRuntime(
            renderer=LOCAL_OSM_RASTER_RENDERER_NAME,
            server_url=server_url,
            leaflet_js_url=leaflet_js_url,
            leaflet_css_url=leaflet_css_url,
            raster_tile_url=f"{server_url}/osm/{{z}}/{{x}}/{{y}}.{raster_extension}",
            raster_attribution=OSM_ATTRIBUTION,
            maplibre_js_url=None,
            maplibre_css_url=None,
            pmtiles_js_url=None,
            tilejson_url=None,
            pmtiles_url=None,
            vector_layers=[],
            messages=tuple(messages),
        )

    if allow_online_osm:
        messages.append(
            "未检测到本地 OSM 栅格瓦片，当前使用在线 OpenStreetMap 标准底图以保留原地图样式。"
            "完全断网使用请准备 data/tiles/osm/{z}/{x}/{y}.png 和本地 Leaflet 资源。"
        )
        return OfflineMapRuntime(
            renderer=OSM_RASTER_RENDERER_NAME,
            server_url=None,
            leaflet_js_url=LEAFLET_JS_CDN,
            leaflet_css_url=LEAFLET_CSS_CDN,
            raster_tile_url=OSM_ONLINE_RASTER_TEMPLATE,
            raster_attribution=OSM_ATTRIBUTION,
            maplibre_js_url=None,
            maplibre_css_url=None,
            pmtiles_js_url=None,
            tilejson_url=None,
            pmtiles_url=None,
            vector_layers=[],
            messages=tuple(messages),
        )

    if has_maplibre:
        messages.append(
            "未检测到本地矢量瓦片和 OSM 栅格瓦片，MapLibre 将使用本地 GraphML 道路 GeoJSON 作为底图叠加。"
            "推荐放置 data/tiles/hangzhou.mbtiles，或放置 data/tiles/osm/{z}/{x}/{y}.png。"
        )
        server_url = _ensure_server(asset_dir, mbtiles_path, pmtiles_path, raster_tile_dir, metadata)
        return OfflineMapRuntime(
            renderer="MapLibre 本地 GeoJSON 渲染",
            server_url=server_url,
            leaflet_js_url=None,
            leaflet_css_url=None,
            raster_tile_url=None,
            raster_attribution=None,
            maplibre_js_url=f"{server_url}/assets/{MAPLIBRE_JS_PATH.name}",
            maplibre_css_url=f"{server_url}/assets/{MAPLIBRE_CSS_PATH.name}",
            pmtiles_js_url=f"{server_url}/assets/{PMTILES_JS_PATH.name}" if has_pmtiles_js else None,
            tilejson_url=None,
            pmtiles_url=None,
            vector_layers=vector_layers,
            messages=tuple(messages),
        )

    if has_mbtiles or has_pmtiles:
        messages.append("已检测到本地矢量瓦片，但缺少本地 MapLibre 资源，无法启用矢量瓦片底图。")
    if has_pmtiles and not has_pmtiles_js:
        messages.append("已检测到本地 PMTiles，但缺少 pmtiles.js，无法启用 PMTiles 渲染。")
    messages.append(
        "未检测到可用本地前端地图资源，当前使用 Canvas 离线降级渲染。"
        "如需保留 OpenStreetMap 样式，请允许在线 OSM，或准备本地 Leaflet 资源和 OSM 栅格瓦片。"
    )
    return OfflineMapRuntime(
        renderer=CANVAS_FALLBACK_RENDERER_NAME,
        server_url=None,
        leaflet_js_url=None,
        leaflet_css_url=None,
        raster_tile_url=None,
        raster_attribution=None,
        maplibre_js_url=None,
        maplibre_css_url=None,
        pmtiles_js_url=None,
        tilejson_url=None,
        pmtiles_url=None,
        vector_layers=[],
        messages=tuple(messages),
    )


def _json_script(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _maplibre_html(payload: dict[str, Any], runtime: OfflineMapRuntime) -> str:
    runtime_payload = {
        "tilejsonUrl": runtime.tilejson_url,
        "pmtilesUrl": runtime.pmtiles_url,
        "vectorLayers": runtime.vector_layers,
        "hasPmtiles": runtime.pmtiles_url is not None and runtime.pmtiles_js_url is not None,
    }
    pmtiles_script = f'<script src="{runtime.pmtiles_js_url}"></script>' if runtime.pmtiles_js_url else ""
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="{runtime.maplibre_css_url}" />
  <style>
    html, body, #map {{ width: 100%; height: 100%; margin: 0; background: #f8fafc; }}
    .maplibregl-popup-content {{ font: 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="{runtime.maplibre_js_url}"></script>
  {pmtiles_script}
  <script id="payload" type="application/json">{_json_script(payload)}</script>
  <script id="runtime" type="application/json">{_json_script(runtime_payload)}</script>
  <script>
    const payload = JSON.parse(document.getElementById("payload").textContent);
    const runtime = JSON.parse(document.getElementById("runtime").textContent);
    if (runtime.hasPmtiles && window.pmtiles) {{
      const protocol = new pmtiles.Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
    }}
    const style = {{
      version: 8,
      sources: {{}},
      layers: [{{ id: "background", type: "background", paint: {{ "background-color": "#f8fafc" }} }}]
    }};
    if (runtime.tilejsonUrl) {{
      style.sources.hangzhou_tiles = {{ type: "vector", url: runtime.tilejsonUrl }};
    }} else if (runtime.pmtilesUrl) {{
      style.sources.hangzhou_tiles = {{ type: "vector", url: runtime.pmtilesUrl }};
    }}
    function addVectorStyleLayers() {{
      const sourceId = "hangzhou_tiles";
      if (!style.sources[sourceId]) return;
      for (const layer of runtime.vectorLayers || []) {{
        const id = String(layer.id || "");
        const low = id.toLowerCase();
        const isRoad = low.includes("road") || low.includes("transport") || low.includes("street");
        const isWater = low.includes("water");
        const isBuilding = low.includes("building");
        const isLand = low.includes("land") || low.includes("park") || low.includes("earth");
        if (isWater || isBuilding || isLand) {{
          style.layers.push({{
            id: "fill-" + id,
            type: "fill",
            source: sourceId,
            "source-layer": id,
            paint: {{
              "fill-color": isWater ? "#bfdbfe" : (isBuilding ? "#d1d5db" : "#dcfce7"),
              "fill-opacity": isWater ? 0.75 : 0.45
            }}
          }});
        }}
        style.layers.push({{
          id: "line-" + id,
          type: "line",
          source: sourceId,
          "source-layer": id,
          paint: {{
            "line-color": isRoad ? "#94a3b8" : "#cbd5e1",
            "line-width": isRoad ? ["interpolate", ["linear"], ["zoom"], 8, 0.5, 14, 2.2, 17, 5] : 0.8,
            "line-opacity": isRoad ? 0.8 : 0.35
          }}
        }});
      }}
    }}
    addVectorStyleLayers();
    const map = new maplibregl.Map({{
      container: "map",
      style,
      center: payload.center,
      zoom: 12,
      attributionControl: false,
      preserveDrawingBuffer: false
    }});
    map.addControl(new maplibregl.NavigationControl({{ visualizePitch: false }}), "top-right");
    function addLineLayer(id, data, fallbackColor, fallbackWidth, dashed) {{
      map.addSource(id, {{ type: "geojson", data }});
      map.addLayer({{
        id,
        type: "line",
        source: id,
        layout: {{ "line-cap": "round", "line-join": "round" }},
        paint: {{
          "line-color": ["case", ["has", "color"], ["get", "color"], fallbackColor],
          "line-width": ["case", ["has", "width"], ["get", "width"], fallbackWidth],
          "line-opacity": ["case", ["has", "opacity"], ["get", "opacity"], 0.8],
          "line-dasharray": dashed ? [1.5, 1.5] : ["case", ["to-boolean", ["get", "dash"]], ["literal", [1.5, 1.5]], ["literal", [1, 0]]]
        }}
      }});
    }}
    function addPointLayer(id, data) {{
      map.addSource(id, {{ type: "geojson", data }});
      map.addLayer({{
        id,
        type: "circle",
        source: id,
        paint: {{
          "circle-color": ["case", ["has", "color"], ["get", "color"], "#0f172a"],
          "circle-radius": ["case", ["has", "radius"], ["get", "radius"], 5],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
          "circle-opacity": ["case", ["has", "opacity"], ["get", "opacity"], 0.92]
        }}
      }});
    }}
    map.on("load", () => {{
      addLineLayer("base-roads", payload.baseRoads, "#64748b", 1, false);
      addLineLayer("traffic", payload.traffic, "#16a34a", 4, false);
      addLineLayer("wavefront-inflight", payload.wavefrontInflight, "#f59e0b", 3, true);
      addLineLayer("wavefront-edges", payload.wavefrontEdges, "#06b6d4", 2, false);
      addLineLayer("previous-route", payload.previousRoute, "#f97316", 4, true);
      addLineLayer("path", payload.path, "#dc2626", 6, false);
      addPointLayer("wavefront-nodes", payload.wavefrontNodes);
      addPointLayer("markers", payload.markers);
      if (payload.bounds && payload.bounds[0] && payload.bounds[1]) {{
        map.fitBounds(payload.bounds, {{ padding: 44, duration: 0, maxZoom: 15 }});
      }}
    }});
  </script>
</body>
</html>
"""


def _leaflet_raster_html(payload: dict[str, Any], runtime: OfflineMapRuntime) -> str:
    runtime_payload = {
        "tileUrl": runtime.raster_tile_url,
        "attribution": runtime.raster_attribution or OSM_ATTRIBUTION,
        "renderer": runtime.renderer,
    }
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="{runtime.leaflet_css_url}" />
  <style>
    html, body, #map {{ width: 100%; height: 100%; margin: 0; background: #f8fafc; }}
    .leaflet-tooltip {{ font: 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .renderer-badge {{
      position: absolute;
      left: 12px;
      top: 12px;
      z-index: 500;
      padding: 5px 8px;
      background: rgba(255, 255, 255, .9);
      border: 1px solid #dbe3eb;
      border-radius: 4px;
      color: #334155;
      font: 12px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      pointer-events: none;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="renderer-badge">{runtime.renderer}</div>
  <script src="{runtime.leaflet_js_url}"></script>
  <script id="payload" type="application/json">{_json_script(payload)}</script>
  <script id="runtime" type="application/json">{_json_script(runtime_payload)}</script>
  <script>
    const payload = JSON.parse(document.getElementById("payload").textContent);
    const runtime = JSON.parse(document.getElementById("runtime").textContent);
    const center = payload.center || [120.16, 30.25];
    const map = L.map("map", {{
      preferCanvas: true,
      zoomControl: true,
      attributionControl: true
    }}).setView([center[1], center[0]], 12);

    L.tileLayer(runtime.tileUrl, {{
      maxZoom: 19,
      attribution: runtime.attribution
    }}).addTo(map);

    function lineStyle(feature, fallback) {{
      const p = feature.properties || {{}};
      return {{
        color: p.color || fallback.color,
        weight: p.width || fallback.width,
        opacity: p.opacity ?? fallback.opacity ?? 0.8,
        dashArray: p.dash ? "7 8" : null,
        lineCap: "round",
        lineJoin: "round"
      }};
    }}

    function bindLabel(feature, layer) {{
      const p = feature.properties || {{}};
      const label = p.tooltip || p.label;
      if (label) layer.bindTooltip(String(label));
    }}

    function addLineLayer(collection, fallback) {{
      if (!collection || !collection.features || collection.features.length === 0) return;
      L.geoJSON(collection, {{
        style: (feature) => lineStyle(feature, fallback),
        onEachFeature: bindLabel
      }}).addTo(map);
    }}

    function addPointLayer(collection) {{
      if (!collection || !collection.features || collection.features.length === 0) return;
      L.geoJSON(collection, {{
        pointToLayer: (feature, latlng) => {{
          const p = feature.properties || {{}};
          return L.circleMarker(latlng, {{
            radius: p.radius || 5,
            color: "#ffffff",
            weight: 1.5,
            opacity: 1,
            fillColor: p.color || "#0f172a",
            fillOpacity: p.opacity ?? 0.92
          }});
        }},
        onEachFeature: bindLabel
      }}).addTo(map);
    }}

    addLineLayer(payload.baseRoads, {{ color: "#64748b", width: 1, opacity: .34 }});
    addLineLayer(payload.traffic, {{ color: "#16a34a", width: 4, opacity: .82 }});
    addLineLayer(payload.wavefrontInflight, {{ color: "#f59e0b", width: 3, opacity: .62 }});
    addLineLayer(payload.wavefrontEdges, {{ color: "#06b6d4", width: 2, opacity: .58 }});
    addLineLayer(payload.previousRoute, {{ color: "#f97316", width: 4, opacity: .72 }});
    addLineLayer(payload.path, {{ color: "#dc2626", width: 6, opacity: .95 }});
    addPointLayer(payload.wavefrontNodes);
    addPointLayer(payload.markers);

    if (payload.bounds && payload.bounds[0] && payload.bounds[1]) {{
      const [[minLon, minLat], [maxLon, maxLat]] = payload.bounds;
      map.fitBounds([[minLat, minLon], [maxLat, maxLon]], {{
        padding: [44, 44],
        maxZoom: 15,
        animate: false
      }});
    }}
  </script>
</body>
</html>
"""


def _canvas_html(payload: dict[str, Any]) -> str:
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    html, body {{ width: 100%; height: 100%; margin: 0; overflow: hidden; background: #f8fafc; }}
    #wrap {{ position: relative; width: 100%; height: 100%; font: 12px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    #map {{ width: 100%; height: 100%; display: block; cursor: grab; }}
    #badge {{ position: absolute; left: 12px; top: 12px; padding: 6px 8px; background: rgba(255,255,255,.92); border: 1px solid #e2e8f0; border-radius: 6px; color: #334155; }}
  </style>
</head>
<body>
  <div id="wrap">
    <canvas id="map"></canvas>
    <div id="badge">Canvas 离线地图 · 滚轮缩放 · 拖拽平移</div>
  </div>
  <script id="payload" type="application/json">{_json_script(payload)}</script>
  <script>
    const payload = JSON.parse(document.getElementById("payload").textContent);
    const canvas = document.getElementById("map");
    const ctx = canvas.getContext("2d");
    let zoom = 1, offsetX = 0, offsetY = 0, dragging = false, lastX = 0, lastY = 0;
    function resize() {{
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * devicePixelRatio));
      canvas.height = Math.max(1, Math.floor(rect.height * devicePixelRatio));
      draw();
    }}
    function project(coord) {{
      const [[minLon, minLat], [maxLon, maxLat]] = payload.bounds;
      const w = canvas.width, h = canvas.height;
      const pad = 36 * devicePixelRatio;
      const sx = (w - pad * 2) / Math.max(1e-9, maxLon - minLon);
      const sy = (h - pad * 2) / Math.max(1e-9, maxLat - minLat);
      const s = Math.min(sx, sy) * zoom;
      const x = pad + (coord[0] - minLon) * s + offsetX;
      const y = h - pad - (coord[1] - minLat) * s + offsetY;
      return [x, y];
    }}
    function drawLines(collection, fallback) {{
      for (const feature of collection.features || []) {{
        const coords = feature.geometry.coordinates;
        if (!coords || coords.length < 2) continue;
        const p = feature.properties || {{}};
        ctx.beginPath();
        coords.forEach((coord, idx) => {{
          const [x, y] = project(coord);
          if (idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }});
        ctx.strokeStyle = p.color || fallback.color;
        ctx.globalAlpha = p.opacity || fallback.opacity || 1;
        ctx.lineWidth = (p.width || fallback.width || 1) * devicePixelRatio;
        ctx.setLineDash(p.dash ? [8 * devicePixelRatio, 8 * devicePixelRatio] : []);
        ctx.stroke();
      }}
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    }}
    function drawPoints(collection) {{
      for (const feature of collection.features || []) {{
        const [x, y] = project(feature.geometry.coordinates);
        const p = feature.properties || {{}};
        const r = (p.radius || 5) * devicePixelRatio;
        ctx.beginPath();
        ctx.fillStyle = p.color || "#0f172a";
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.lineWidth = 1.5 * devicePixelRatio;
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();
      }}
    }}
    function draw() {{
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#f8fafc";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      drawLines(payload.baseRoads, {{ color: "#64748b", width: 1, opacity: .34 }});
      drawLines(payload.traffic, {{ color: "#16a34a", width: 4, opacity: .82 }});
      drawLines(payload.wavefrontInflight, {{ color: "#f59e0b", width: 3, opacity: .62 }});
      drawLines(payload.wavefrontEdges, {{ color: "#06b6d4", width: 2, opacity: .58 }});
      drawLines(payload.previousRoute, {{ color: "#f97316", width: 4, opacity: .72 }});
      drawLines(payload.path, {{ color: "#dc2626", width: 6, opacity: .95 }});
      drawPoints(payload.wavefrontNodes);
      drawPoints(payload.markers);
    }}
    canvas.addEventListener("wheel", (event) => {{
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.15 : 0.87;
      zoom = Math.min(12, Math.max(0.5, zoom * factor));
      draw();
    }}, {{ passive: false }});
    canvas.addEventListener("mousedown", (event) => {{ dragging = true; lastX = event.clientX; lastY = event.clientY; canvas.style.cursor = "grabbing"; }});
    window.addEventListener("mouseup", () => {{ dragging = false; canvas.style.cursor = "grab"; }});
    window.addEventListener("mousemove", (event) => {{
      if (!dragging) return;
      offsetX += (event.clientX - lastX) * devicePixelRatio;
      offsetY += (event.clientY - lastY) * devicePixelRatio;
      lastX = event.clientX; lastY = event.clientY;
      draw();
    }});
    window.addEventListener("resize", resize);
    resize();
  </script>
</body>
</html>
"""


def render_offline_map(components, payload: dict[str, Any], runtime: OfflineMapRuntime, *, height: int = 720) -> None:
    if runtime.uses_leaflet_raster:
        html = _leaflet_raster_html(payload, runtime)
    elif runtime.uses_maplibre:
        html = _maplibre_html(payload, runtime)
    else:
        html = _canvas_html(payload)
    components.html(html, height=height, scrolling=False)
