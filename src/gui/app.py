"""Streamlit + Folium GUI for real-map SNN navigation."""

from __future__ import annotations

import math
import time

import networkx as nx

from maps import (
    BoundingBox,
    DEFAULT_FIXED_MAP_REGION,
    HANGZHOU_BBOX,
    HANGZHOU_CACHE_FILENAME_TEMPLATE,
    edge_geometry_to_latlon,
    load_hangzhou_graph,
    nearest_node_by_latlon,
    osmnx_multidigraph_to_digraph,
    path_nodes_to_latlon,
)
from navigation import NavigationResult, WavefrontFrame, run_navigation
from traffic import (
    DynamicRouterConfig,
    FlowGeneratorConfig,
    IncidentGeneratorConfig,
    SimulationEngine,
    SimulationEngineConfig,
    TrafficSnapshot,
    Vehicle,
)

# EdgePoints 是 GUI 层的道路几何缓存格式：
# (起点 node id, 终点 node id, Folium 可直接绘制的 [(lat, lon), ...] 折线点)。
# 预先缓存这份数据可以避免每次拖动 slider 时重复解析 edge geometry，减少页面卡顿。
EdgePoints = list[tuple[int, int, list[tuple[float, float]]]]

# EdgePointLookup 用于 O(1) 根据有向边 (u, v) 找到道路几何。
# wavefront、交通拥堵和最终路径都需要频繁按边取坐标，所以单独建索引。
EdgePointLookup = dict[tuple[int, int], list[tuple[float, float]]]

FOLIUM_TILE_NAME = "OpenStreetMap"
NETWORK_TYPE_LABELS = {
    "drive": "机动车道路",
    "walk": "步行道路",
    "bike": "骑行道路",
    "all": "全部道路",
}
TRAFFIC_MODE_LABELS = {
    "normal": "普通",
    "peak": "高峰",
    "incident": "事故/施工",
}
REROUTE_REASON_LABELS = {
    "lookahead_congestion": "前方拥堵",
    "eta_improvement": "新路线 ETA 更优",
    "severe_congestion_without_eta_improvement": "前方拥堵但新路线不更优",
    "eta_improvement_too_small": "ETA 改善不足",
    "no_current_route_available": "当前无可用替代路线",
}
PLAYBACK_DEFAULTS = {
    "vehicle_running": False,
    "vehicle_paused": False,
    "vehicle_finished": False,
    "simulation_started": False,
    "last_tick_time": None,
    "auto_sim_time": 0.0,
    "navigation_status_message": None,
}


def _imports():
    # Streamlit/Folium 是交互式 GUI 依赖。放在函数里导入，便于测试非 GUI 逻辑时
    # 不强制提前初始化 Streamlit runtime。
    try:
        import folium
        import streamlit as st
        from streamlit_folium import st_folium
    except Exception as exc:  # pragma: no cover - interactive dependency
        raise RuntimeError(
            "GUI dependencies are missing. Install them with `pip install -r requirements.txt`."
        ) from exc
    return st, folium, st_folium


def _coordinate_in_bbox(lat: float, lon: float, bbox: BoundingBox = HANGZHOU_BBOX) -> bool:
    return (
        float(bbox.south) <= float(lat) <= float(bbox.north)
        and float(bbox.west) <= float(lon) <= float(bbox.east)
    )


def _validate_hangzhou_coordinates(
    start_lat: float,
    start_lon: float,
    goal_lat: float,
    goal_lon: float,
    bbox: BoundingBox = HANGZHOU_BBOX,
) -> list[str]:
    errors: list[str] = []
    if not _coordinate_in_bbox(start_lat, start_lon, bbox):
        errors.append("起点坐标不在浙江省杭州市范围内，请输入杭州经纬度范围内的坐标。")
    if not _coordinate_in_bbox(goal_lat, goal_lon, bbox):
        errors.append("终点坐标不在浙江省杭州市范围内，请输入杭州经纬度范围内的坐标。")
    return errors


def _ensure_playback_state(state) -> None:
    for key, value in PLAYBACK_DEFAULTS.items():
        state.setdefault(key, value)


def _reset_playback_state(state, *, message: str | None = None) -> None:
    state["vehicle_running"] = False
    state["vehicle_paused"] = False
    state["vehicle_finished"] = False
    state["simulation_started"] = False
    state["last_tick_time"] = None
    state["auto_sim_time"] = 0.0
    state["navigation_status_message"] = message


def _start_playback_state(state, *, now: float | None = None) -> None:
    state["vehicle_running"] = True
    state["vehicle_paused"] = False
    state["vehicle_finished"] = False
    state["simulation_started"] = True
    state["last_tick_time"] = float(now if now is not None else time.monotonic())
    state["navigation_status_message"] = "车辆正在自动行驶"


def _pause_playback_state(state) -> None:
    state["vehicle_running"] = False
    state["vehicle_paused"] = True
    state["vehicle_finished"] = False
    state["navigation_status_message"] = "导航已暂停"


def _finish_playback_state(state, message: str) -> None:
    state["vehicle_running"] = False
    state["vehicle_paused"] = False
    state["vehicle_finished"] = True
    state["last_tick_time"] = None
    state["navigation_status_message"] = message


def _navigation_status_label(result: NavigationResult | None) -> str:
    if result is None:
        return "未运行"
    return "导航成功" if bool(result.metadata.get("success")) else "导航失败"


def _reroute_decision_payload(decision) -> dict[str, object] | None:
    if decision is None:
        return None
    return {
        "是否重规划": bool(decision.rerouted),
        "重规划时间（秒）": float(decision.reroute_time),
        "旧 ETA（秒）": float(decision.old_route_eta_before_reroute),
        "新 ETA（秒）": float(decision.new_route_eta_after_reroute),
        "受影响路段": [f"{u}->{v}" for u, v in decision.affected_edge_ids],
        "旧路线": [int(node) for node in decision.old_route],
        "新路线": [int(node) for node in decision.new_route],
        "原因": REROUTE_REASON_LABELS.get(str(decision.reason), str(decision.reason)),
    }


def _graph_center(graph: nx.DiGraph) -> tuple[float, float]:
    # Folium 地图中心使用 (lat, lon)。项目图里 lat/lon 来自 OSMnx 节点属性。
    lats = [float(attrs["lat"]) for _node, attrs in graph.nodes(data=True)]
    lons = [float(attrs["lon"]) for _node, attrs in graph.nodes(data=True)]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _fit_map_bounds(fmap, graph: nx.DiGraph, path_points: list[tuple[float, float]]) -> None:
    # 如果已有最终路径，优先按路径范围缩放，用户能直接看到路线。
    # 如果还没有路径，就按整个加载的道路网络范围缩放。
    if len(path_points) >= 2:
        lats = [point[0] for point in path_points]
        lons = [point[1] for point in path_points]
    else:
        north, south, east, west = _graph_bounds(graph)
        lats = [south, north]
        lons = [west, east]
    fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])


def _graph_bounds(graph: nx.DiGraph) -> tuple[float, float, float, float]:
    # 返回顺序是 north, south, east, west，和 GUI 中 bbox 的命名保持一致。
    lats = [float(attrs["lat"]) for _node, attrs in graph.nodes(data=True)]
    lons = [float(attrs["lon"]) for _node, attrs in graph.nodes(data=True)]
    return max(lats), min(lats), max(lons), min(lons)


def _build_edge_points(graph: nx.DiGraph) -> EdgePoints:
    # 将图中的每条有向边转换成 Folium PolyLine 坐标。
    # edge_geometry_to_latlon 会优先使用 OSM 原始 geometry；没有 geometry 时回退到端点直线。
    edge_points: EdgePoints = []
    for u, v in graph.edges():
        points = edge_geometry_to_latlon(graph, int(u), int(v))
        if len(points) >= 2:
            edge_points.append((int(u), int(v), points))
    return edge_points


def _edge_point_lookup(edge_points: EdgePoints) -> EdgePointLookup:
    # 同一对 (u, v) 只保留一条已经适配后的 DiGraph 边，因此可以直接作为 dict key。
    return {(u, v): points for u, v, points in edge_points}


def _points_for_edge(
    edge_lookup: EdgePointLookup,
    graph: nx.DiGraph,
    u: int,
    v: int,
) -> list[tuple[float, float]]:
    # 绝大多数边都能从缓存命中。miss 时再即时解析，避免异常边导致可视化中断。
    points = edge_lookup.get((int(u), int(v)))
    if points is not None:
        return points
    return edge_geometry_to_latlon(graph, int(u), int(v))


def _add_network_edges(folium, fmap, edge_points: EdgePoints, max_edges: int) -> None:
    # 普通道路底图只画前 max_edges 条，避免大地图一次绘制几万条边导致卡顿。
    # 这里绘制的是灰色道路背景，不参与路径计算。
    for idx, (_u, _v, points) in enumerate(edge_points):
        if idx >= max_edges:
            break
        folium.PolyLine(points, color="#64748b", weight=1, opacity=0.34).add_to(fmap)


def _traffic_color(congestion: float, blocked: bool) -> str:
    # 交通拥堵颜色只用于 GUI 表达：
    # 绿色=畅通，黄色=开始拥堵，红色=重度拥堵，深红=接近饱和/阻塞。
    if blocked:
        return "#7f1d1d"
    if congestion >= 0.90:
        return "#7f1d1d"
    if congestion >= 0.70:
        return "#dc2626"
    if congestion >= 0.40:
        return "#facc15"
    return "#16a34a"


def _add_traffic_overlay(
    folium,
    fmap,
    graph: nx.DiGraph,
    snapshot: TrafficSnapshot | None,
    edge_lookup: EdgePointLookup,
    *,
    max_edges: int,
) -> None:
    # 将 TrafficSnapshot 叠加到地图上。
    # 注意这里不修改 graph，只读取 snapshot 和 graph 中的几何信息进行绘制。
    if snapshot is None:
        return

    # 优先绘制最严重的拥堵/阻塞边。max_edges 用于限制 Folium 图层数量。
    ranked_states = sorted(
        snapshot.edge_states.values(),
        key=lambda state: (state.blocked, state.congestion, state.vehicle_count),
        reverse=True,
    )
    for state in ranked_states[:max_edges]:
        u, v = state.edge
        points = _points_for_edge(edge_lookup, graph, u, v)
        if len(points) < 2:
            continue
        folium.PolyLine(
            points,
            color=_traffic_color(state.congestion, state.blocked),
            weight=6 if state.blocked else 4,
            opacity=0.82,
            dash_array="3,5" if state.blocked else None,
            tooltip=(
                f"交通路段 {u}->{v}，拥堵={state.congestion:.2f}，"
                f"车辆={state.vehicle_count}，阻塞={state.blocked}"
            ),
        ).add_to(fmap)

    # inhibited_nodes 表示拥堵路口对神经元发放的抑制强度。
    # GUI 用紫红色圆点显示，语义是“进入该路口的边被额外增加 delay”。
    for node, congestion in snapshot.inhibited_nodes.items():
        if node not in graph:
            continue
        attrs = graph.nodes[node]
        folium.CircleMarker(
            location=(float(attrs["lat"]), float(attrs["lon"])),
            radius=7,
            color="#be123c",
            fill=True,
            fill_opacity=min(0.85, 0.25 + float(congestion) * 0.65),
            weight=2,
            tooltip=f"受抑制路口/神经元 {node}，拥堵={float(congestion):.2f}",
        ).add_to(fmap)


def _spike_times_by_node(result: NavigationResult) -> dict[int, float]:
    # run_navigation 会把每个 node/neuron 的首次发放时间放进 metadata。
    # 这里统一转成 int->float，避免 JSON/session 序列化后 key/value 类型漂移。
    raw = result.metadata.get("spike_times_by_node") or {}
    return {int(node): float(time_ms) for node, time_ms in raw.items()}


def _wavefront_frame_at_time(graph: nx.DiGraph, result: NavigationResult, time_ms: int) -> WavefrontFrame:
    # 根据任意毫秒 time_ms 重建 wavefront 状态。
    # 这不是重新运行 SNN，而是根据 spike_times_by_node 回放“哪些 neuron 已经发放”。
    spike_times = _spike_times_by_node(result)
    if not spike_times:
        # 兼容旧结果：如果没有完整 spike time，就退回到已有稀疏 frame。
        if not result.wavefront_frames:
            return WavefrontFrame(t=int(time_ms), active_nodes=[], active_edges=[])
        candidates = [frame for frame in result.wavefront_frames if frame.t <= int(time_ms)]
        return candidates[-1] if candidates else result.wavefront_frames[0]

    t = int(time_ms)
    # active_nodes：在当前时间 t 之前已经发放过 spike 的所有 node/neuron。
    active_nodes = sorted(int(node) for node, spike_time in spike_times.items() if spike_time <= t)
    active_node_set = set(active_nodes)
    active_edges: list[tuple[int, int]] = []
    for u, v, attrs in graph.edges(data=True):
        # 一条边被认为“传播完成”的条件：
        # 1. 前驱 u 已经发放；
        # 2. 后继 v 已经发放；
        # 3. u 的发放时间 + edge.delay_ms <= 当前时间。
        if int(u) not in spike_times or int(v) not in active_node_set:
            continue
        source_time = float(spike_times[int(u)])
        delay = float(attrs.get("delay_ms", 1.0))
        if source_time + delay <= float(t) + 1e-9:
            active_edges.append((int(u), int(v)))
    return WavefrontFrame(t=t, active_nodes=active_nodes, active_edges=active_edges)


def _wavefront_inflight_edges_at_time(graph: nx.DiGraph, result: NavigationResult, time_ms: int) -> list[tuple[int, int]]:
    # inflight edge 表示脉冲已经从前驱 neuron 发出，但还没到达后继 neuron。
    # GUI 中用橙色虚线显示，能更直观地表达 SNN 波前正在扩散。
    spike_times = _spike_times_by_node(result)
    if not spike_times:
        return []
    t = float(time_ms)
    inflight: list[tuple[int, int]] = []
    for u, v, attrs in graph.edges(data=True):
        source_time = spike_times.get(int(u))
        if source_time is None or source_time > t:
            continue
        delay = float(attrs.get("delay_ms", 1.0))
        arrival = source_time + delay
        target_time = spike_times.get(int(v))
        # t 位于 [source_time, arrival) 时，边处于传播中。
        # 如果目标 neuron 已经在 t 前发放，则这条边不再算 inflight。
        if source_time <= t < arrival and (target_time is None or target_time > t):
            inflight.append((int(u), int(v)))
    return inflight


def _newly_active_nodes_at_time(result: NavigationResult, time_ms: int) -> set[int]:
    # 当前毫秒新激活的 neuron 用橙色高亮，其余已激活 neuron 用青色显示。
    return {
        int(node)
        for node, spike_time in _spike_times_by_node(result).items()
        if int(round(float(spike_time))) == int(time_ms)
    }


def _add_wavefront_timestep(
    folium,
    fmap,
    graph: nx.DiGraph,
    result: NavigationResult,
    time_ms: int,
    edge_lookup: EdgePointLookup,
    max_nodes: int,
) -> WavefrontFrame:
    # 在 Folium 地图上绘制指定 timestep 的 SNN 扩散状态：
    # - 橙色虚线：传播中的 synapse/edge；
    # - 青色线：传播完成的 synapse/edge；
    # - 橙色点：本 timestep 新发放的 neuron；
    # - 青色点：此前已经发放过的 neuron。
    if not result.wavefront_frames and not result.metadata.get("spike_times_by_node"):
        return WavefrontFrame(t=int(time_ms), active_nodes=[], active_edges=[])

    frame = _wavefront_frame_at_time(graph, result, int(time_ms))

    # 先画传播中的边，作为“正在扩散”的动态视觉层。
    for u, v in _wavefront_inflight_edges_at_time(graph, result, int(time_ms)):
        points = _points_for_edge(edge_lookup, graph, u, v)
        if len(points) >= 2:
            folium.PolyLine(
                points,
                color="#f59e0b",
                weight=3,
                opacity=0.62,
                dash_array="5,7",
            ).add_to(fmap)

    # 再画已经传播完成的边，表示 wavefront 已经确认到达的部分。
    for u, v in frame.active_edges:
        points = _points_for_edge(edge_lookup, graph, u, v)
        if len(points) >= 2:
            folium.PolyLine(points, color="#06b6d4", weight=2, opacity=0.58).add_to(fmap)

    newly_active = _newly_active_nodes_at_time(result, int(time_ms))
    # 新激活节点排在前面，确保 max_nodes 裁剪时优先保留最有信息量的点。
    ordered_nodes = sorted(newly_active) + [node for node in frame.active_nodes if node not in newly_active]
    for node in ordered_nodes[:max_nodes]:
        attrs = graph.nodes[node]
        is_new = node in newly_active
        folium.CircleMarker(
            location=(float(attrs["lat"]), float(attrs["lon"])),
            radius=5 if is_new else 3,
            color="#f97316" if is_new else "#0e7490",
            fill=True,
            fill_opacity=0.85 if is_new else 0.58,
            weight=1 if is_new else 0,
        ).add_to(fmap)
    return frame


def _wavefront_time_limit(result: NavigationResult | None) -> int:
    # GUI slider 的最大值。优先使用完整 spike time 的最大时间；
    # 没有 metadata 时回退到 wavefront_frames 的最大 t。
    if result is None:
        return 0
    value = result.metadata.get("wavefront_time_max_ms")
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        pass
    return max((int(frame.t) for frame in result.wavefront_frames), default=0)


def _wavefront_time_caption(frame: WavefrontFrame, max_time_ms: int, drawn_node_count: int) -> str:
    # 显示当前 wavefront timestep 的摘要。drawn_nodes 用于提醒用户视觉上只画了前 N 个点。
    clipped = "" if drawn_node_count >= len(frame.active_nodes) else f"，已绘制节点={drawn_node_count}"
    return (
        f"波前时间步 t={frame.t}/{max_time_ms} 毫秒，"
        f"已激活节点={len(frame.active_nodes)}{clipped}，已激活边={len(frame.active_edges)}"
    )


def _add_path_and_markers(
    folium,
    fmap,
    graph: nx.DiGraph,
    result: NavigationResult | None,
    start_node: int,
    goal_node: int,
    car_index: int,
    car_point: tuple[float, float] | None = None,
) -> None:
    # 绘制起点、终点、最终路径和小车位置。
    # car_index 是路径折线点索引，不是 graph node id。
    start_attrs = graph.nodes[start_node]
    goal_attrs = graph.nodes[goal_node]
    folium.Marker(
        (float(start_attrs["lat"]), float(start_attrs["lon"])),
        tooltip=f"起点节点 {start_node}",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(fmap)
    folium.Marker(
        (float(goal_attrs["lat"]), float(goal_attrs["lon"])),
        tooltip=f"终点节点 {goal_node}",
        icon=folium.Icon(color="purple", icon="flag"),
    ).add_to(fmap)
    if result is None or not result.path_nodes:
        return
    points = path_nodes_to_latlon(graph, result.path_nodes)
    if len(points) >= 2:
        # 红色粗线表示当前规划结果。交通重规划后，这条线可能改变。
        folium.PolyLine(points, color="#dc2626", weight=6, opacity=0.95).add_to(fmap)
        car_point = car_point or points[min(car_index, len(points) - 1)]
        folium.Marker(
            car_point,
            tooltip="车辆",
            icon=folium.Icon(color="red", icon="car", prefix="fa"),
        ).add_to(fmap)


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    # 小范围地图中用经纬度近似米制距离，足够支持小车沿 edge geometry 插值。
    dy = (float(a[0]) - float(b[0])) * 111_000.0
    dx = (float(a[1]) - float(b[1])) * 111_000.0
    return (dx * dx + dy * dy) ** 0.5


def _interpolate_polyline(points: list[tuple[float, float]], distance_m: float) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if len(points) == 1 or distance_m <= 0.0:
        return points[0]
    remaining = float(distance_m)
    for start, end in zip(points, points[1:]):
        segment = max(1.0e-9, _distance_m(start, end))
        if remaining <= segment:
            ratio = remaining / segment
            lat = float(start[0]) + (float(end[0]) - float(start[0])) * ratio
            lon = float(start[1]) + (float(end[1]) - float(start[1])) * ratio
            return lat, lon
        remaining -= segment
    return points[-1]


def _vehicle_position_latlon(
    graph: nx.DiGraph,
    edge_lookup: EdgePointLookup,
    vehicle: Vehicle | None,
) -> tuple[float, float] | None:
    # 动态仿真中车辆位置来自 route 上当前 edge 的 position_on_edge。
    if vehicle is None:
        return None
    edge = vehicle.current_edge
    if edge is None:
        if vehicle.destination in graph:
            attrs = graph.nodes[vehicle.destination]
            return float(attrs["lat"]), float(attrs["lon"])
        return None
    points = _points_for_edge(edge_lookup, graph, edge[0], edge[1])
    if len(points) < 2:
        return None
    return _interpolate_polyline(points, float(vehicle.position_on_edge))


def _add_previous_route_overlay(
    folium,
    fmap,
    graph: nx.DiGraph,
    previous_route: list[int],
) -> None:
    # 发生 reroute 后，用橙色虚线保留上一条剩余路线，便于对比新旧路径。
    if len(previous_route) < 2:
        return
    points = path_nodes_to_latlon(graph, previous_route)
    if len(points) >= 2:
        folium.PolyLine(points, color="#f97316", weight=4, opacity=0.72, dash_array="8,8").add_to(fmap)


def _default_points(graph: nx.DiGraph) -> tuple[float, float, float, float]:
    # 默认起点/终点输入框使用图的西北角和东南角，确保初始值落在地图范围内。
    north, south, east, west = _graph_bounds(graph)
    return north, west, south, east


def _metric_float(result: NavigationResult | None, key: str) -> float:
    # Streamlit metric 需要稳定的数字字符串。这里把缺失或非数字值统一转成 0.0。
    if result is None:
        return 0.0
    value = result.metadata.get(key, 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _algorithm_comparison_rows(result: NavigationResult | None) -> list[dict[str, object]]:
    if result is None:
        return []
    rows: list[dict[str, object]] = [
        {
            "算法": "SNN",
            "运行耗时（秒）": round(_metric_float(result, "snn_runtime_sec"), 6),
            "状态": _navigation_status_label(result),
            "路径节点数": len(result.path_nodes),
            "总成本": _optional_float(result.total_cost),
            "预计通行时间（秒）": _optional_float(result.metadata.get("path_travel_time_s")),
        }
    ]
    benchmarks = result.metadata.get("algorithm_benchmarks") or {}
    if not isinstance(benchmarks, dict):
        return rows
    for benchmark in benchmarks.values():
        if not isinstance(benchmark, dict):
            continue
        rows.append(
            {
                "算法": str(benchmark.get("label") or benchmark.get("algorithm") or ""),
                "运行耗时（秒）": round(float(benchmark.get("runtime_sec", 0.0) or 0.0), 6),
                "状态": "成功" if bool(benchmark.get("success")) else "失败",
                "路径节点数": int(benchmark.get("path_node_count", len(benchmark.get("path_nodes", []))) or 0),
                "总成本": _optional_float(benchmark.get("total_cost")),
                "预计通行时间（秒）": _optional_float(benchmark.get("path_travel_time_s")),
            }
        )
    return rows


def _reachability_status(graph: nx.DiGraph, start_node: int, goal_node: int) -> tuple[bool, str]:
    # 可达性检查使用当前 planning graph。
    # traffic 开启后，blocked 边已经从 wavefront 角度不可通行，因此这里也会反映交通影响。
    if start_node == goal_node:
        return True, "起点和终点吸附到了同一个道路节点。"
    if nx.has_path(graph, start_node, goal_node):
        return True, "从起点到终点存在有向可达路径。"
    if nx.has_path(graph, goal_node, start_node):
        return False, (
            "从当前起点到终点不存在有向可达路径，但反方向可能可达。"
            "请调整起终点位置或扩大地图区域。"
        )
    weak_component = nx.node_connected_component(graph.to_undirected(as_view=True), start_node)
    if goal_node not in weak_component:
        return False, (
            "起点和终点位于不同道路连通分量中。"
            "请将坐标调整到杭州道路网络的连通区域内。"
        )
    return False, (
        "起点和终点在同一无向连通分量内，但不存在有向可达路径。"
        "请尝试附近坐标，或切换道路网络类型。"
    )


def _simulation_config(
    traffic_mode: str,
    background_rate: float,
    dt_seconds: float,
    incident_probability: float,
    reroute_check_interval: float,
    min_reroute_interval: float,
    congestion_threshold: float,
    random_seed: int,
) -> SimulationEngineConfig:
    # 动态交通配置只控制“当前 timestep 如何推进”，不会生成未来拥堵计划。
    return SimulationEngineConfig(
        dt=float(dt_seconds),
        random_seed=int(random_seed),
        flow=FlowGeneratorConfig(
            traffic_mode=str(traffic_mode),
            base_rate_veh_per_minute=float(background_rate),
            random_seed=int(random_seed),
        ),
        incidents=IncidentGeneratorConfig(
            incident_probability_per_minute=float(incident_probability),
            random_seed=int(random_seed) + 1,
        ),
        router=DynamicRouterConfig(
            reroute_check_interval=float(reroute_check_interval),
            min_reroute_interval=float(min_reroute_interval),
            congestion_threshold=float(congestion_threshold),
        ),
    )


def _planning_graph(
    base_graph: nx.DiGraph,
    traffic_enabled: bool,
    engine: SimulationEngine | None,
) -> nx.DiGraph:
    # 动态交通开启时，planning graph 是 SimulationEngine 当前时刻的 graph。
    if not traffic_enabled or engine is None:
        return base_graph
    return engine.graph


def _load_hangzhou_graph_cached(st, network_type: str):
    # Streamlit cache_resource 缓存杭州地图下载/转换结果。
    # 只要 network_type 不变，重复 rerun 页面不会重新读取 GraphML 或访问网络。
    @st.cache_resource(show_spinner=False)
    def _load(network_type_key: str):
        osm_graph = load_hangzhou_graph(network_type=network_type_key)
        return osmnx_multidigraph_to_digraph(osm_graph)

    return _load(network_type)


def main() -> None:
    # main 是整个 Web 页面入口。Streamlit 的特点是每次控件变化都会从头执行 main，
    # 所以需要通过 st.session_state 保存地图、交通快照和上一次导航结果。
    st, folium, st_folium = _imports()
    st.set_page_config(page_title="杭州 OSM SNN 导航", layout="wide")
    st.title("杭州 OSM SNN 导航")
    _ensure_playback_state(st.session_state)

    with st.sidebar:
        st.header("地图与规划")
        st.caption(f"当前地图区域：{DEFAULT_FIXED_MAP_REGION}")
        st.caption(
            "地图数据优先从本地缓存加载；缓存不存在时将自动从 OpenStreetMap 下载并缓存。"
        )
        st.caption(
            f"杭州经纬度范围：北 {HANGZHOU_BBOX.north:.3f}，南 {HANGZHOU_BBOX.south:.3f}，"
            f"东 {HANGZHOU_BBOX.east:.3f}，西 {HANGZHOU_BBOX.west:.3f}"
        )
        st.caption(f"地图底图：{FOLIUM_TILE_NAME}")

        # network_type="drive" 会保留真实机动车道路方向，可能出现单行道不可达。
        network_type = st.selectbox(
            "道路网络类型",
            ["drive", "walk", "bike", "all"],
            index=0,
            format_func=lambda value: NETWORK_TYPE_LABELS.get(value, value),
        )
        st.caption(
            f"缓存文件：data/osm_cache/{HANGZHOU_CACHE_FILENAME_TEMPLATE.format(network_type=network_type)}"
        )

        # 性能控制区：Folium 线段/点越多，交互越卡。
        max_edges = st.slider("道路绘制数量上限", 200, 8000, 2500, 100)
        draw_base_roads = st.checkbox("显示基础道路网络", value=True)
        max_wavefront_nodes = st.slider("波前节点绘制数量上限", 50, 3000, 700, 50)
        use_loihi = st.checkbox("使用 Brian2Loihi 后端", value=True)
        load_clicked = st.button("加载杭州地图", type="primary")
        st.divider()

        # 动态交通区：自动行驶时每次刷新都会推进真实 timestep，拥堵由车辆流和当前事件实时产生。
        st.header("模拟交通")
        traffic_enabled = st.checkbox("启用模拟交通", value=False)
        traffic_mode = st.selectbox(
            "交通模式",
            ["normal", "peak", "incident"],
            index=1,
            format_func=lambda value: TRAFFIC_MODE_LABELS.get(value, value),
        )
        traffic_background_rate = st.slider("背景车辆生成率（辆/分钟）", 0.0, 120.0, 18.0, 1.0)
        traffic_dt_seconds = st.slider("交通时间步（秒）", 1.0, 30.0, 5.0, 1.0)
        traffic_steps_per_refresh = st.slider("每次刷新推进步数", 1, 20, 1, 1)
        incident_probability = st.slider("事故/施工概率（每分钟）", 0.0, 0.50, 0.05, 0.01)
        reroute_check_interval = st.slider("重规划检查间隔（秒）", 5.0, 60.0, 10.0, 5.0)
        min_reroute_interval = st.slider("最小重规划间隔（秒）", 10.0, 120.0, 30.0, 5.0)
        congestion_threshold = st.slider("重规划拥堵阈值", 0.40, 1.00, 0.80, 0.05)
        traffic_seed = st.number_input("交通随机种子", value=7, step=1)
        max_traffic_edges = st.slider("交通路段绘制数量上限", 10, 1000, 180, 10)
        apply_traffic_clicked = st.button(
            "应用当前交通设置",
            disabled=st.session_state.get("traffic_engine") is None,
        )

    if load_clicked:
        try:
            with st.spinner("正在加载杭州道路网络..."):
                # road_graph 是 base_graph：只包含 OSM 基础道路和基础 SNN delay。
                # 后续交通拥堵不会直接改这个图，而是生成临时 planning_graph。
                st.session_state.road_graph = _load_hangzhou_graph_cached(st, network_type)
                # 加载地图后立即预计算所有道路几何。后续 rerun 时直接复用，减少卡顿。
                st.session_state.road_edge_points = _build_edge_points(st.session_state.road_graph)
                st.session_state.edge_point_lookup = _edge_point_lookup(st.session_state.road_edge_points)

                # 新地图意味着旧路线和旧交通状态都不再适用，必须清空。
                st.session_state.navigation_result = None
                st.session_state.traffic_engine = None
                st.session_state.traffic_snapshot = None
                st.session_state.traffic_step_result = None
                st.session_state.traffic_step = 0
                st.session_state.last_start_node = None
                st.session_state.last_goal_node = None
                _reset_playback_state(st.session_state)
        except Exception as exc:
            st.error(
                "杭州地图加载失败："
                f"{exc}\n\n"
                "请检查网络连接，或确认本地缓存文件位于 data/osm_cache/ 目录。"
            )
            return
    if "road_graph" not in st.session_state:
        # 页面首次打开时不自动下载地图，避免直接触发耗时请求。
        st.info("请先点击“加载杭州地图”开始导航。")
        return

    base_graph: nx.DiGraph = st.session_state.road_graph
    if "road_edge_points" not in st.session_state or "edge_point_lookup" not in st.session_state:
        # 兼容旧 session：如果代码更新前已有 road_graph，但没有几何缓存，就补建。
        st.session_state.road_edge_points = _build_edge_points(base_graph)
        st.session_state.edge_point_lookup = _edge_point_lookup(st.session_state.road_edge_points)
    edge_points: EdgePoints = st.session_state.road_edge_points
    edge_lookup: EdgePointLookup = st.session_state.edge_point_lookup

    # 动态仿真配置只在创建新 SimulationEngine 时使用；已运行的 engine 会持续保存当前车辆和事件状态。
    sim_config = _simulation_config(
        traffic_mode,
        traffic_background_rate,
        traffic_dt_seconds,
        incident_probability if traffic_mode == "incident" else 0.0,
        reroute_check_interval,
        min_reroute_interval,
        congestion_threshold,
        int(traffic_seed),
    )
    traffic_engine: SimulationEngine | None = st.session_state.get("traffic_engine")
    if apply_traffic_clicked and traffic_engine is not None:
        traffic_engine.update_config(sim_config)
        st.success("当前交通设置已应用，将在下一次自动推进或恢复行驶时生效。")

    traffic_snapshot: TrafficSnapshot | None = (
        traffic_engine.current_snapshot() if bool(traffic_enabled) and traffic_engine is not None else None
    )

    # graph 是当前 planning_graph。自动行驶启动后即使不显示交通图层，也使用 SimulationEngine 当前图。
    graph = _planning_graph(
        base_graph,
        bool(traffic_enabled) or bool(st.session_state.get("simulation_started")),
        traffic_engine,
    )
    default_start_lat, default_start_lon, default_goal_lat, default_goal_lon = _default_points(base_graph)

    # 起终点输入仍使用经纬度。真正用于 SNN 的是 snap 后的 node id。
    col_a, col_b, col_c, col_d = st.columns(4)
    start_lat = col_a.number_input("起点纬度", value=float(default_start_lat), format="%.7f")
    start_lon = col_b.number_input("起点经度", value=float(default_start_lon), format="%.7f")
    goal_lat = col_c.number_input("终点纬度", value=float(default_goal_lat), format="%.7f")
    goal_lon = col_d.number_input("终点经度", value=float(default_goal_lon), format="%.7f")

    coordinate_errors = _validate_hangzhou_coordinates(
        float(start_lat),
        float(start_lon),
        float(goal_lat),
        float(goal_lon),
    )
    for error in coordinate_errors:
        st.error(error)

    # snap 用 base_graph 做，避免交通导致的 blocked 状态影响“最近道路节点”的选择。
    # 规划和可达性检查则用当前 graph，让交通阻塞影响路径结果。
    start_node = nearest_node_by_latlon(base_graph, float(start_lat), float(start_lon))
    goal_node = nearest_node_by_latlon(base_graph, float(goal_lat), float(goal_lon))
    path_exists, reachability_message = _reachability_status(graph, start_node, goal_node)

    def _project_route_planner(route_graph: nx.DiGraph, source: int, target: int) -> NavigationResult:
        # DynamicRouter 调用该函数时，只传入当前 graph；不会接触未来事件或未来车辆状态。
        return run_navigation(route_graph, source, target, use_loihi=bool(use_loihi))

    # 主要动作：
    # 1. 运行 SNN 导航：生成当前路线和 wavefront；
    # 2. 开始/暂停/结束：控制车辆自动沿当前路线推进；
    # 3. 恢复开始时强制检查一次当前拥堵状态下是否需要重规划。
    run_col, start_col, pause_col, end_col = st.columns(4)
    run_clicked = run_col.button("运行 SNN 导航", type="primary", disabled=bool(coordinate_errors))
    start_clicked = start_col.button("开始", disabled=bool(coordinate_errors))
    pause_clicked = pause_col.button("暂停", disabled=not bool(st.session_state.get("simulation_started")))
    end_clicked = end_col.button("结束", disabled=not bool(st.session_state.get("simulation_started")))

    if run_clicked:
        try:
            with st.spinner("正在运行 SNN 波前导航..."):
                _reset_playback_state(st.session_state)
                st.session_state.last_start_node = int(start_node)
                st.session_state.last_goal_node = int(goal_node)
                if traffic_enabled:
                    traffic_engine = SimulationEngine(base_graph, config=sim_config)
                    st.session_state.traffic_engine = traffic_engine
                    st.session_state.navigation_result = traffic_engine.start_navigation(
                        start_node,
                        goal_node,
                        route_planner=_project_route_planner,
                    )
                    traffic_snapshot = traffic_engine.current_snapshot()
                    st.session_state.traffic_snapshot = traffic_snapshot
                    graph = traffic_engine.graph
                else:
                    st.session_state.traffic_engine = None
                    traffic_engine = None
                    traffic_snapshot = None
                    st.session_state.traffic_snapshot = None
                    st.session_state.traffic_step_result = None
                    st.session_state.traffic_step = 0
                    # run_navigation 内部会执行 DiGraph -> SNN wavefront -> parent trace -> NavigationResult。
                    st.session_state.navigation_result = run_navigation(
                        graph,
                        start_node,
                        goal_node,
                        use_loihi=bool(use_loihi),
                    )
        except Exception as exc:
            st.error(f"运行 SNN 导航失败：{exc}")

    result_for_start: NavigationResult | None = st.session_state.get("navigation_result")
    if start_clicked:
        if result_for_start is None:
            st.warning("请先加载杭州地图并运行 SNN 导航。")
        elif not result_for_start.path_nodes:
            st.warning("当前没有可行路径，无法开始自动行驶。")
        else:
            try:
                if traffic_engine is None:
                    traffic_engine = SimulationEngine(base_graph, config=sim_config)
                    st.session_state.traffic_engine = traffic_engine
                    st.session_state.navigation_result = traffic_engine.start_navigation(
                        start_node,
                        goal_node,
                        route_planner=_project_route_planner,
                    )
                else:
                    traffic_engine.update_config(sim_config)
                    if traffic_engine.navigation_vehicle is None or traffic_engine.navigation_vehicle.arrived:
                        st.session_state.navigation_result = traffic_engine.start_navigation(
                            start_node,
                            goal_node,
                            route_planner=_project_route_planner,
                        )
                # 恢复行驶时立即基于当前 graph edge 状态检查是否重规划。
                traffic_engine.check_navigation_reroute(route_planner=_project_route_planner, force=True)
                st.session_state.navigation_result = traffic_engine.navigation_result or st.session_state.navigation_result
                traffic_snapshot = traffic_engine.current_snapshot()
                st.session_state.traffic_snapshot = traffic_snapshot
                _start_playback_state(st.session_state)
                st.success("车辆开始自动行驶。")
            except Exception as exc:
                st.error(f"开始自动行驶失败：{exc}")

    if pause_clicked:
        _pause_playback_state(st.session_state)
        st.warning("导航已暂停。")

    if end_clicked:
        _finish_playback_state(st.session_state, "导航已结束")
        st.info("导航已结束。")

    if st.session_state.get("vehicle_running") and traffic_engine is not None:
        traffic_engine.update_config(sim_config)
        step_result = None
        for _ in range(int(traffic_steps_per_refresh)):
            step_result = traffic_engine.step(route_planner=_project_route_planner)
        st.session_state.traffic_step_result = step_result
        st.session_state.traffic_step = int(st.session_state.get("traffic_step", 0)) + int(traffic_steps_per_refresh)
        st.session_state.navigation_result = traffic_engine.navigation_result
        st.session_state.auto_sim_time = float(traffic_engine.current_time)
        traffic_snapshot = traffic_engine.current_snapshot()
        st.session_state.traffic_snapshot = traffic_snapshot
        if traffic_engine.navigation_vehicle is not None and traffic_engine.navigation_vehicle.arrived:
            _finish_playback_state(st.session_state, "车辆已到达终点")
            st.success("车辆已到达终点。")

    # 按最新 graph 再做一次可达性检查。自动推进后 graph 可能已经变化。
    traffic_engine = st.session_state.get("traffic_engine")
    traffic_snapshot = (
        traffic_engine.current_snapshot() if bool(traffic_enabled) and traffic_engine is not None else None
    )
    graph = _planning_graph(
        base_graph,
        bool(traffic_enabled) or bool(st.session_state.get("simulation_started")),
        traffic_engine,
    )
    path_exists, reachability_message = _reachability_status(graph, start_node, goal_node)
    if coordinate_errors:
        pass
    elif path_exists:
        st.caption(reachability_message)
    else:
        st.warning(f"{reachability_message} 目标神经元不会在该有向路线中发放。")

    result: NavigationResult | None = st.session_state.get("navigation_result")
    if result is not None:
        if result.metadata.get("success"):
            st.success("导航成功。")
        else:
            st.warning("导航失败：未找到可行路径。")
    status_message = st.session_state.get("navigation_status_message")
    if status_message:
        if status_message == "车辆已到达终点":
            st.success(status_message)
        elif status_message == "导航已暂停":
            st.warning(status_message)
        else:
            st.info(status_message)

    # path_points 是最终路径的折线坐标，用于地图缩放。
    path_points = path_nodes_to_latlon(graph, result.path_nodes) if result else []
    simulation_vehicle = traffic_engine.navigation_vehicle if traffic_engine is not None else None
    actual_car_point = _vehicle_position_latlon(graph, edge_lookup, simulation_vehicle)
    car_index = 0
    wave_time_ms = 0
    wavefront_frame = WavefrontFrame(t=0, active_nodes=[], active_edges=[])
    max_wave_time_ms = _wavefront_time_limit(result)
    if result and result.wavefront_frames:
        # 即使没有找到最终路径，wavefront 也可能传播到部分可达节点。
        # 这时仍允许用户查看局部扩散过程。
        if not result.metadata.get("success"):
            st.warning("未找到最终路径，下方波前帧仅显示局部传播结果。")
        if max_wave_time_ms > 0:
            wave_time_ms = st.slider(
                "波前时间步（毫秒）",
                0,
                max_wave_time_ms,
                max_wave_time_ms,
            )
        else:
            wave_time_ms = 0

    # Folium 地图每次 rerun 都重新生成。prefer_canvas=True 可以缓解大量线段绘制的卡顿。
    center = _graph_center(graph)
    fmap = folium.Map(location=center, zoom_start=14, tiles=FOLIUM_TILE_NAME, prefer_canvas=True, control_scale=True)
    if draw_base_roads:
        # 普通道路底图；关闭后拖动小车或 wavefront 会更流畅。
        _add_network_edges(folium, fmap, edge_points, int(max_edges))

    # 交通图层画在普通道路之上、wavefront 和最终路径之下。
    _add_traffic_overlay(
        folium,
        fmap,
        graph,
        traffic_snapshot if bool(traffic_enabled) else None,
        edge_lookup,
        max_edges=int(max_traffic_edges),
    )
    if result:
        # wavefront 图层按当前毫秒重建，不需要重新运行 SNN。
        wavefront_frame = _add_wavefront_timestep(
            folium,
            fmap,
            graph,
            result,
            wave_time_ms,
            edge_lookup,
            int(max_wavefront_nodes),
        )
    if traffic_engine is not None:
        _add_previous_route_overlay(folium, fmap, graph, traffic_engine.previous_navigation_route)
    # 最终路径和起终点 marker 放到最上层，保证用户容易识别当前路线。
    _add_path_and_markers(folium, fmap, graph, result, start_node, goal_node, car_index, actual_car_point)
    _fit_map_bounds(fmap, graph, path_points)

    if result and result.wavefront_frames:
        st.caption(_wavefront_time_caption(wavefront_frame, max_wave_time_ms, int(max_wavefront_nodes)))

    # returned_objects=[] 避免 Streamlit-Folium 把地图点击/缩放状态大量回传，
    # 这对 slider 交互性能有明显帮助。
    st_folium(fmap, width=None, height=720, returned_objects=[])

    # 指标区：展示 snap 后节点、路径长度、通行时间和 SNN 运行耗时。
    metric_cols = st.columns(6)
    metric_cols[0].metric("起点节点", str(start_node))
    metric_cols[1].metric("终点节点", str(goal_node))
    metric_cols[2].metric("路径节点数", str(len(result.path_nodes) if result else 0))
    metric_cols[3].metric(
        "路径长度",
        f"{_metric_float(result, 'path_length_m'):.1f} m",
    )
    metric_cols[4].metric(
        "预计通行时间",
        f"{_metric_float(result, 'path_travel_time_s'):.1f} s",
    )
    metric_cols[5].metric(
        "SNN 运行耗时",
        f"{_metric_float(result, 'snn_runtime_sec'):.3f} s",
    )
    comparison_rows = _algorithm_comparison_rows(result)
    if comparison_rows:
        st.subheader("算法运行耗时对比")
        st.table(comparison_rows)

    if traffic_engine is not None:
        # 动态交通指标区：全部来自当前 SimulationEngine 状态，不含未来信息。
        metrics = traffic_engine.metrics.metrics
        traffic_cols = st.columns(5)
        traffic_cols[0].metric("仿真时间", f"{traffic_engine.current_time:.1f} s")
        traffic_cols[1].metric("车辆数", str(len(traffic_engine.vehicles)))
        traffic_cols[2].metric(
            "平均速度",
            f"{metrics.average_network_speed:.1f} m/s",
        )
        traffic_cols[3].metric(
            "拥堵路段",
            str(metrics.number_of_congested_edges),
        )
        traffic_cols[4].metric("重规划次数", str(metrics.number_of_reroutes))

    # 调试区：保留关键状态，方便定位“目标 neuron 是否发放”“是否因为交通 blocked 不可达”等问题。
    with st.expander("调试信息 / 元数据 / 日志", expanded=False):
        st.json(
            {
                "总成本": result.total_cost if result else None,
                "后端": result.metadata.get("backend") if result else None,
                "导航状态": _navigation_status_label(result),
                "波前帧数": len(result.wavefront_frames) if result else 0,
                "目标发放时间（毫秒）": result.metadata.get("target_arrival_time_ms") if result else None,
                "错误": result.metadata.get("error") if result else None,
                "Loihi 错误": result.metadata.get("loihi_error") if result else None,
                "算法基准": result.metadata.get("algorithm_benchmarks") if result else {},
                "存在有向路径": path_exists,
                "启用模拟交通": bool(traffic_enabled),
                "交通步数": int(st.session_state.get("traffic_step", 0)),
                "仿真时间": traffic_engine.current_time if traffic_engine else 0.0,
                "交通车辆数": len(traffic_engine.vehicles) if traffic_engine else 0,
                "拥堵路段数": len(traffic_snapshot.congested_edges) if traffic_snapshot else 0,
                "活跃事故/施工数": len(traffic_engine.incident_generator.active_incidents(traffic_engine.current_time))
                if traffic_engine
                else 0,
                "指标": traffic_engine.metrics.metrics.to_dict() if traffic_engine else {},
                "最近一次重规划": _reroute_decision_payload(traffic_engine.last_reroute_decision)
                if traffic_engine
                else None,
            }
        )
    if result and result.metadata.get("error"):
        # path reconstruction 或后端返回的错误会在这里显示。
        st.warning(f"导航错误：{result.metadata['error']}")

    if st.session_state.get("vehicle_running") and st.session_state.get("traffic_engine") is not None:
        time.sleep(0.35)
        st.rerun()


if __name__ == "__main__":
    main()
