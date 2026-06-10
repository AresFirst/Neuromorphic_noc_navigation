"""Streamlit + Folium GUI for real-map SNN navigation."""

from __future__ import annotations

from dataclasses import asdict

import networkx as nx

from maps import (
    BoundingBox,
    edge_geometry_to_latlon,
    load_osm_graph,
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
                f"traffic edge {u}->{v}, congestion={state.congestion:.2f}, "
                f"vehicles={state.vehicle_count}, blocked={state.blocked}"
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
            tooltip=f"inhibited neuron/node {node}, congestion={float(congestion):.2f}",
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
    clipped = "" if drawn_node_count >= len(frame.active_nodes) else f", drawn_nodes={drawn_node_count}"
    return (
        f"Wavefront timestep t={frame.t}/{max_time_ms} ms, "
        f"active_nodes={len(frame.active_nodes)}{clipped}, active_edges={len(frame.active_edges)}"
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
        tooltip=f"Start node {start_node}",
        icon=folium.Icon(color="green", icon="play"),
    ).add_to(fmap)
    folium.Marker(
        (float(goal_attrs["lat"]), float(goal_attrs["lon"])),
        tooltip=f"Goal node {goal_node}",
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
            tooltip="Car",
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


def _reachability_status(graph: nx.DiGraph, start_node: int, goal_node: int) -> tuple[bool, str]:
    # 可达性检查使用当前 planning graph。
    # traffic 开启后，blocked 边已经从 wavefront 角度不可通行，因此这里也会反映交通影响。
    if start_node == goal_node:
        return True, "Start and goal snap to the same node."
    if nx.has_path(graph, start_node, goal_node):
        return True, "A directed route exists from start to goal."
    if nx.has_path(graph, goal_node, start_node):
        return False, (
            "No directed route exists from start to goal, but the reverse direction is reachable. "
            "This usually means one-way streets or snapped points are facing the wrong direction."
        )
    weak_component = nx.node_connected_component(graph.to_undirected(as_view=True), start_node)
    if goal_node not in weak_component:
        return False, (
            "Start and goal are in different road-network components. "
            "Move one point closer to the connected road network or load a larger map area."
        )
    return False, (
        "Start and goal are in the same undirected component, but no directed route exists. "
        "Try nearby coordinates, `network_type=all`, or a different start/goal direction."
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


def _load_graph_cached(st, mode: str, place: str, bbox_values: tuple[float, float, float, float], network_type: str):
    # Streamlit cache_resource 缓存地图下载/转换结果。
    # 只要 mode/place/bbox/network_type 不变，重复 rerun 页面不会重新下载 OSM。
    @st.cache_resource(show_spinner=False)
    def _load(mode_key: str, place_key: str, bbox_key: tuple[float, float, float, float], network_type_key: str):
        if mode_key == "Place name":
            osm_graph = load_osm_graph(place_name=place_key, network_type=network_type_key)
        else:
            north, south, east, west = bbox_key
            osm_graph = load_osm_graph(
                bbox=BoundingBox(north=north, south=south, east=east, west=west),
                network_type=network_type_key,
            )
        return osmnx_multidigraph_to_digraph(osm_graph)

    return _load(mode, place, bbox_values, network_type)


def main() -> None:
    # main 是整个 Web 页面入口。Streamlit 的特点是每次控件变化都会从头执行 main，
    # 所以需要通过 st.session_state 保存地图、交通快照和上一次导航结果。
    st, folium, st_folium = _imports()
    st.set_page_config(page_title="SNN Real-Map Navigation", layout="wide")
    st.title("Real Map + Brian2Loihi SNN Navigation")

    with st.sidebar:
        # 地图输入区：支持按地名下载，也支持按 bbox 精确裁剪。
        # network_type="drive" 会保留真实机动车道路方向，可能出现单行道不可达。
        mode = st.radio("Map input", ["Place name", "Bounding box"], horizontal=True)
        network_type = st.selectbox("Network type", ["drive", "walk", "bike", "all"], index=0)
        tiles = st.selectbox("Map tiles", ["CartoDB dark_matter", "OpenStreetMap", "CartoDB positron"], index=0)
        place = st.text_input("Place name", value="Shinjuku, Tokyo, Japan")
        north = st.number_input("North", value=35.7040, format="%.6f")
        south = st.number_input("South", value=35.6810, format="%.6f")
        east = st.number_input("East", value=139.7160, format="%.6f")
        west = st.number_input("West", value=139.6850, format="%.6f")

        # 性能控制区：Folium 线段/点越多，slider 交互越卡。
        # 这里允许用户限制底图道路数和 wavefront 节点数。
        max_edges = st.slider("Road edges to draw", 200, 8000, 2500, 100)
        draw_base_roads = st.checkbox("Draw base roads", value=True)
        max_wavefront_nodes = st.slider("Wavefront nodes to draw", 50, 3000, 700, 50)
        use_loihi = st.checkbox("Use Brian2Loihi backend", value=True)
        st.divider()

        # 动态交通区：每次点击都会推进真实 timestep，拥堵由车辆流和当前事件实时产生。
        traffic_enabled = st.checkbox("Simulated traffic", value=False)
        traffic_mode = st.selectbox("Traffic mode", ["normal", "peak", "incident"], index=1)
        traffic_background_rate = st.slider("Background vehicles/min", 0.0, 120.0, 18.0, 1.0)
        traffic_dt_seconds = st.slider("Traffic timestep seconds", 1.0, 30.0, 5.0, 1.0)
        traffic_steps_per_click = st.slider("Traffic steps per click", 1, 20, 1, 1)
        incident_probability = st.slider("Incident probability/min", 0.0, 0.50, 0.05, 0.01)
        reroute_check_interval = st.slider("Reroute check interval s", 5.0, 60.0, 10.0, 5.0)
        min_reroute_interval = st.slider("Min reroute interval s", 10.0, 120.0, 30.0, 5.0)
        congestion_threshold = st.slider("Reroute congestion threshold", 0.40, 1.00, 0.80, 0.05)
        traffic_seed = st.number_input("Traffic seed", value=7, step=1)
        max_traffic_edges = st.slider("Traffic edges to draw", 10, 1000, 180, 10)
        load_clicked = st.button("Load OSM Map", type="primary")

    if load_clicked:
        try:
            with st.spinner("Loading OSM road network..."):
                # road_graph 是 base_graph：只包含 OSM 基础道路和基础 SNN delay。
                # 后续交通拥堵不会直接改这个图，而是生成临时 planning_graph。
                st.session_state.road_graph = _load_graph_cached(
                    st,
                    mode,
                    place,
                    (float(north), float(south), float(east), float(west)),
                    network_type,
                )
                # 加载地图后立即预计算所有道路几何。后续 rerun 时直接复用，减少卡顿。
                st.session_state.road_edge_points = _build_edge_points(st.session_state.road_graph)
                st.session_state.edge_point_lookup = _edge_point_lookup(st.session_state.road_edge_points)

                # 新地图意味着旧路线和旧交通状态都不再适用，必须清空。
                st.session_state.navigation_result = None
                st.session_state.traffic_engine = None
                st.session_state.traffic_snapshot = None
                st.session_state.traffic_step_result = None
                st.session_state.traffic_step = 0
        except Exception as exc:
            st.error(
                f"{exc}\n\n"
                "Try a smaller bbox, check network access, or place a cached GraphML file under data/osm_cache."
            )
            return
    if "road_graph" not in st.session_state:
        # 页面首次打开时不自动下载地图，避免用户还没选择区域就开始耗时请求。
        st.info("Load an OSM map to start navigation.")
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
    traffic_snapshot: TrafficSnapshot | None = (
        traffic_engine.current_snapshot() if bool(traffic_enabled) and traffic_engine is not None else None
    )

    # graph 是当前 planning_graph。交通关闭时等于 base_graph；交通开启时来自 SimulationEngine 当前状态。
    graph = _planning_graph(base_graph, bool(traffic_enabled), traffic_engine)
    default_start_lat, default_start_lon, default_goal_lat, default_goal_lon = _default_points(base_graph)

    # 起终点输入仍使用经纬度。真正用于 SNN 的是 snap 后的 node id。
    col_a, col_b, col_c, col_d = st.columns(4)
    start_lat = col_a.number_input("Start latitude", value=float(default_start_lat), format="%.7f")
    start_lon = col_b.number_input("Start longitude", value=float(default_start_lon), format="%.7f")
    goal_lat = col_c.number_input("Goal latitude", value=float(default_goal_lat), format="%.7f")
    goal_lon = col_d.number_input("Goal longitude", value=float(default_goal_lon), format="%.7f")

    # snap 用 base_graph 做，避免交通导致的 blocked 状态影响“最近道路节点”的选择。
    # 规划和可达性检查则用当前 graph，让交通阻塞影响路径结果。
    start_node = nearest_node_by_latlon(base_graph, float(start_lat), float(start_lon))
    goal_node = nearest_node_by_latlon(base_graph, float(goal_lat), float(goal_lon))
    path_exists, reachability_message = _reachability_status(graph, start_node, goal_node)

    # 三个主要动作：
    # 1. Run SNN Navigation：无交通时直接规划；有交通时启动 SimulationEngine 和导航车辆；
    # 2. Step Dynamic Traffic：推进在线仿真，路由器只看当前 graph edge state；
    # 3. Clear Traffic：清空车辆、事件和动态边状态。
    run_col, traffic_col, clear_col = st.columns(3)
    run_clicked = run_col.button("Run SNN Navigation", type="primary")
    traffic_clicked = traffic_col.button("Step Dynamic Traffic", disabled=not bool(traffic_enabled))
    clear_traffic_clicked = clear_col.button("Clear Traffic", disabled=traffic_engine is None)
    if clear_traffic_clicked:
        # 清空交通时不删除 base_graph，只删除动态仿真状态和旧结果。
        st.session_state.traffic_engine = None
        st.session_state.traffic_snapshot = None
        st.session_state.traffic_step_result = None
        st.session_state.traffic_step = 0
        traffic_engine = None
        traffic_snapshot = None
        graph = _planning_graph(base_graph, bool(traffic_enabled), traffic_engine)
        st.session_state.navigation_result = None

    def _project_route_planner(route_graph: nx.DiGraph, source: int, target: int) -> NavigationResult:
        # DynamicRouter 调用该函数时，只传入当前 graph；不会接触未来事件或未来车辆状态。
        return run_navigation(route_graph, source, target, use_loihi=bool(use_loihi))

    if run_clicked:
        with st.spinner("Running SNN wavefront navigation..."):
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
                # run_navigation 内部会执行 DiGraph -> SNN wavefront -> parent trace -> NavigationResult。
                st.session_state.navigation_result = run_navigation(
                    graph,
                    start_node,
                    goal_node,
                    use_loihi=bool(use_loihi),
                )
    if traffic_clicked:
        if traffic_engine is None:
            traffic_engine = SimulationEngine(base_graph, config=sim_config)
            st.session_state.traffic_engine = traffic_engine
            traffic_engine.start_navigation(start_node, goal_node, route_planner=_project_route_planner)
        with st.spinner("Advancing dynamic traffic and checking reroute..."):
            step_result = None
            for _ in range(int(traffic_steps_per_click)):
                step_result = traffic_engine.step(route_planner=_project_route_planner)
            st.session_state.traffic_step_result = step_result
            st.session_state.traffic_step = int(st.session_state.get("traffic_step", 0)) + int(traffic_steps_per_click)
            st.session_state.navigation_result = traffic_engine.navigation_result
            traffic_snapshot = traffic_engine.current_snapshot()
            st.session_state.traffic_snapshot = traffic_snapshot
            graph = traffic_engine.graph

    # 按最新 graph 再做一次可达性检查。traffic_clicked 后 graph 可能已经变化。
    path_exists, reachability_message = _reachability_status(graph, start_node, goal_node)
    if path_exists:
        st.caption(reachability_message)
    else:
        st.warning(f"{reachability_message} The goal neuron will not spike for this directed route.")

    result: NavigationResult | None = st.session_state.get("navigation_result")
    # path_points 是最终路径的折线坐标，用于小车 slider 和地图缩放。
    path_points = path_nodes_to_latlon(graph, result.path_nodes) if result else []
    simulation_vehicle = traffic_engine.navigation_vehicle if bool(traffic_enabled) and traffic_engine is not None else None
    actual_car_point = _vehicle_position_latlon(graph, edge_lookup, simulation_vehicle)
    car_index = 0
    if len(path_points) > 1 and simulation_vehicle is None:
        car_index = st.slider("Car position", 0, len(path_points) - 1, 0)
    wave_time_ms = 0
    wavefront_frame = WavefrontFrame(t=0, active_nodes=[], active_edges=[])
    max_wave_time_ms = _wavefront_time_limit(result)
    if result and result.wavefront_frames:
        # 即使没有找到最终路径，wavefront 也可能传播到部分可达节点。
        # 这时仍允许用户查看局部扩散过程。
        if not result.metadata.get("success"):
            st.warning("No final path was found. The wavefront frames below show partial propagation only.")
        if max_wave_time_ms > 0:
            wave_time_ms = st.slider(
                "Wavefront timestep (ms)",
                0,
                max_wave_time_ms,
                max_wave_time_ms,
            )
        else:
            wave_time_ms = 0

    # Folium 地图每次 rerun 都重新生成。prefer_canvas=True 可以缓解大量线段绘制的卡顿。
    center = _graph_center(graph)
    fmap = folium.Map(location=center, zoom_start=14, tiles=tiles, prefer_canvas=True, control_scale=True)
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
    metric_cols[0].metric("Start node", str(start_node))
    metric_cols[1].metric("Goal node", str(goal_node))
    metric_cols[2].metric("Path nodes", str(len(result.path_nodes) if result else 0))
    metric_cols[3].metric(
        "Path length",
        f"{_metric_float(result, 'path_length_m'):.1f} m",
    )
    metric_cols[4].metric(
        "Travel time",
        f"{_metric_float(result, 'path_travel_time_s'):.1f} s",
    )
    metric_cols[5].metric(
        "SNN runtime",
        f"{_metric_float(result, 'snn_runtime_sec'):.3f} s",
    )
    if traffic_enabled:
        # 动态交通指标区：全部来自当前 SimulationEngine 状态，不含未来信息。
        metrics = traffic_engine.metrics.metrics if traffic_engine is not None else None
        traffic_cols = st.columns(5)
        traffic_cols[0].metric("Sim time", f"{traffic_engine.current_time:.1f} s" if traffic_engine else "0.0 s")
        traffic_cols[1].metric("Vehicles", str(len(traffic_engine.vehicles) if traffic_engine else 0))
        traffic_cols[2].metric(
            "Avg speed",
            f"{metrics.average_network_speed:.1f} m/s" if metrics else "0.0 m/s",
        )
        traffic_cols[3].metric(
            "Congested edges",
            str(metrics.number_of_congested_edges if metrics else 0),
        )
        traffic_cols[4].metric("Reroutes", str(metrics.number_of_reroutes if metrics else 0))

    # JSON 调试区：保留关键状态，方便定位“目标 neuron 是否发放”“是否因为交通 blocked 不可达”等问题。
    st.json(
        {
            "total_cost": result.total_cost if result else None,
            "backend": result.metadata.get("backend") if result else None,
            "success": result.metadata.get("success") if result else None,
            "wavefront_steps": len(result.wavefront_frames) if result else 0,
            "target_arrival_time_ms": result.metadata.get("target_arrival_time_ms") if result else None,
            "error": result.metadata.get("error") if result else None,
            "loihi_error": result.metadata.get("loihi_error") if result else None,
            "directed_path_exists": path_exists,
            "traffic_enabled": bool(traffic_enabled),
            "traffic_step": int(st.session_state.get("traffic_step", 0)),
            "simulation_time": traffic_engine.current_time if traffic_engine else 0.0,
            "traffic_vehicle_count": len(traffic_engine.vehicles) if traffic_engine else 0,
            "traffic_congested_edges": len(traffic_snapshot.congested_edges) if traffic_snapshot else 0,
            "active_incidents": len(traffic_engine.incident_generator.active_incidents(traffic_engine.current_time))
            if traffic_engine
            else 0,
            "metrics": traffic_engine.metrics.metrics.to_dict() if traffic_engine else {},
            "last_reroute": asdict(traffic_engine.last_reroute_decision)
            if traffic_engine and traffic_engine.last_reroute_decision
            else None,
        }
    )
    if result and result.metadata.get("error"):
        # path reconstruction 或后端返回的错误会在这里显示。
        st.warning(result.metadata["error"])


if __name__ == "__main__":
    main()
