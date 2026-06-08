"""Convert OSMnx MultiDiGraph road networks into the project DiGraph format."""

from __future__ import annotations

import math
from typing import Any, Iterable

import networkx as nx

LOIHI_MIN_DELAY_MS = 1
LOIHI_MAX_DELAY_MS = 62


def _positive_float(value: Any) -> float | None:
    # OSMnx 从 GraphML 读回时，部分属性可能变成字符串或单元素列表，这里统一清洗成正数。
    if isinstance(value, list) and value:
        value = value[0]
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(parsed) and parsed > 0.0:
        return parsed
    return None


def _edge_cost(attrs: dict[str, Any]) -> float:
    # 规划代价优先使用 travel_time；没有速度信息时退化到 length；再没有才用 1.0。
    for key in ("travel_time", "length"):
        parsed = _positive_float(attrs.get(key))
        if parsed is not None:
            return parsed
    return 1.0


def _delay_ms(cost: float) -> int:
    # Brian2Loihi delay 有硬限制；真实代价保存在 raw_delay_ms/cost，SNN delay 只做受限编码。
    raw_delay = int(round(float(cost)))
    return min(LOIHI_MAX_DELAY_MS, max(LOIHI_MIN_DELAY_MS, raw_delay))


def _geometry_from_attrs(attrs: dict[str, Any]) -> Any:
    # geometry 是地图可视化的关键，不能在 MultiDiGraph -> DiGraph 时丢弃。
    return attrs.get("geometry")


def _node_float(attrs: dict[str, Any], key: str) -> float:
    value = attrs.get(key)
    if value is None:
        raise ValueError(f"OSM node missing coordinate attribute: {key}")
    return float(value)


def osmnx_multidigraph_to_digraph(graph: nx.MultiDiGraph) -> nx.DiGraph:
    """Return a DiGraph suitable for the SNN pipeline.

    Project node IDs are contiguous integers and equal to `snn_neuron_index`.
    Original OSM node IDs are preserved in node attributes and graph-level maps.
    Parallel edges are merged by minimum cost.
    """
    if graph.number_of_nodes() == 0:
        raise ValueError("OSM graph has no nodes")

    # 项目内部要求连续整数节点；这些整数也直接作为 snn_neuron_index 使用。
    osm_nodes = list(graph.nodes())
    osm_to_project = {osm_node: idx for idx, osm_node in enumerate(osm_nodes)}
    project_to_osm = {idx: osm_node for osm_node, idx in osm_to_project.items()}

    output = nx.DiGraph()
    # 每个 OSM node 变成一个项目 node / SNN neuron，并保留原始 OSM id 和经纬度。
    for osm_node, attrs in graph.nodes(data=True):
        node_id = osm_to_project[osm_node]
        lon = _node_float(attrs, "x")
        lat = _node_float(attrs, "y")
        output.add_node(
            node_id,
            original_osm_node_id=osm_node,
            x=lon,
            lon=lon,
            y=lat,
            lat=lat,
            snn_neuron_index=node_id,
        )

    selected_edges: dict[tuple[int, int], dict[str, Any]] = {}
    # OSMnx 使用 MultiDiGraph 表示平行道路；SNN pipeline 需要普通 DiGraph。
    # 因此同一个 (u, v) 方向只保留 cost 最小的一条边。
    for osm_u, osm_v, key, attrs in graph.edges(keys=True, data=True):
        if osm_u not in osm_to_project or osm_v not in osm_to_project:
            continue
        u = osm_to_project[osm_u]
        v = osm_to_project[osm_v]
        cost = _edge_cost(attrs)
        length = _positive_float(attrs.get("length")) or cost
        travel_time = _positive_float(attrs.get("travel_time")) or cost
        edge_payload = {
            "u": u,
            "v": v,
            "original_osm_u": osm_u,
            "original_osm_v": osm_v,
            "original_osm_key": key,
            "length": float(length),
            "travel_time": float(travel_time),
            "cost": float(cost),
            "raw_delay_ms": max(LOIHI_MIN_DELAY_MS, int(round(float(cost)))),
            "delay_ms": _delay_ms(cost),
            "geometry": _geometry_from_attrs(attrs),
            "state": str(attrs.get("state", "normal")),
        }
        if "snn_synapse_index" in attrs:
            edge_payload["snn_synapse_index"] = attrs["snn_synapse_index"]

        pair = (u, v)
        if pair not in selected_edges or cost < float(selected_edges[pair]["cost"]):
            selected_edges[pair] = edge_payload

    # 给保留下来的每条有向边分配 snn_synapse_index，便于后续从突触回溯到道路边。
    for synapse_index, ((u, v), attrs) in enumerate(selected_edges.items()):
        attrs.setdefault("snn_synapse_index", synapse_index)
        output.add_edge(u, v, **attrs)

    # 图级 mapping 是反向映射的核心：SNN 输出 neuron id 后，可以找回项目节点和 OSM 节点。
    output.graph.update(
        {
            "source": "osmnx",
            "node_id_to_osm_id": project_to_osm,
            "osm_node_id_to_node_id": osm_to_project,
            "node_id_to_neuron_index": {node: node for node in output.nodes()},
            "neuron_index_to_node_id": {node: node for node in output.nodes()},
            "delay_encoding": {
                "attr": "delay_ms",
                "raw_attr": "raw_delay_ms",
                "min_ms": LOIHI_MIN_DELAY_MS,
                "max_ms": LOIHI_MAX_DELAY_MS,
            },
        }
    )
    return output


def path_edges(path_nodes: Iterable[int]) -> list[tuple[int, int]]:
    # 将 [n0, n1, n2] 形式的路径节点转换为 [(n0,n1), (n1,n2)] 边序列。
    nodes = [int(node) for node in path_nodes]
    return [(source, target) for source, target in zip(nodes, nodes[1:])]


def _geometry_coords(geometry: Any) -> list[tuple[float, float]]:
    # geometry 可能是 shapely LineString，也可能是 GraphML 读回来的 WKT 字符串。
    if geometry is None:
        return []
    if hasattr(geometry, "coords"):
        return [(float(x), float(y)) for x, y, *_rest in geometry.coords]
    if isinstance(geometry, str):
        try:
            from shapely import wkt

            parsed = wkt.loads(geometry)
            if hasattr(parsed, "coords"):
                return [(float(x), float(y)) for x, y, *_rest in parsed.coords]
        except Exception:
            return []
    return []


def edge_geometry_to_latlon(graph: nx.DiGraph, u: int, v: int) -> list[tuple[float, float]]:
    """Return edge geometry as Folium-ready `(lat, lon)` points."""
    if not graph.has_edge(u, v):
        return []
    coords = _geometry_coords(graph[u][v].get("geometry"))
    if coords:
        # shapely/OSM 几何通常是 (lon, lat)，Folium 需要 (lat, lon)。
        return [(lat, lon) for lon, lat in coords]
    # 没有道路几何时，用边两端节点坐标退化为直线段。
    return [
        (float(graph.nodes[u]["lat"]), float(graph.nodes[u]["lon"])),
        (float(graph.nodes[v]["lat"]), float(graph.nodes[v]["lon"])),
    ]


def path_nodes_to_latlon(graph: nx.DiGraph, path_nodes: Iterable[int]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for u, v in path_edges(path_nodes):
        edge_points = edge_geometry_to_latlon(graph, u, v)
        if not edge_points:
            continue
        # 相邻边共享端点时去重，避免路径折线上出现重复点。
        if points and edge_points[0] == points[-1]:
            points.extend(edge_points[1:])
        else:
            points.extend(edge_points)
    if not points:
        # 单节点路径或缺失边几何时，至少返回节点坐标，保证 GUI 可以放 marker。
        for node in path_nodes:
            attrs = graph.nodes[int(node)]
            points.append((float(attrs["lat"]), float(attrs["lon"])))
    return points


def nearest_node_by_latlon(graph: nx.DiGraph, lat: float, lon: float) -> int:
    """Snap a latitude/longitude to the nearest project graph node."""
    best_node: int | None = None
    best_distance = math.inf
    # 这里用经纬度平方距离做近似 snap；小 bbox 内足够稳定，且避免额外空间索引依赖。
    for node, attrs in graph.nodes(data=True):
        dx = float(attrs["lon"]) - float(lon)
        dy = float(attrs["lat"]) - float(lat)
        distance = dx * dx + dy * dy
        if distance < best_distance:
            best_node = int(node)
            best_distance = distance
    if best_node is None:
        raise ValueError("cannot snap to an empty graph")
    return best_node
