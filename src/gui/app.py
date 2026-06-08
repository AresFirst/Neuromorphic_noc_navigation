"""Streamlit + Folium GUI for real-map SNN navigation."""

from __future__ import annotations

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

EdgePoints = list[tuple[int, int, list[tuple[float, float]]]]
EdgePointLookup = dict[tuple[int, int], list[tuple[float, float]]]


def _imports():
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
    lats = [float(attrs["lat"]) for _node, attrs in graph.nodes(data=True)]
    lons = [float(attrs["lon"]) for _node, attrs in graph.nodes(data=True)]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _fit_map_bounds(fmap, graph: nx.DiGraph, path_points: list[tuple[float, float]]) -> None:
    if len(path_points) >= 2:
        lats = [point[0] for point in path_points]
        lons = [point[1] for point in path_points]
    else:
        north, south, east, west = _graph_bounds(graph)
        lats = [south, north]
        lons = [west, east]
    fmap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])


def _graph_bounds(graph: nx.DiGraph) -> tuple[float, float, float, float]:
    lats = [float(attrs["lat"]) for _node, attrs in graph.nodes(data=True)]
    lons = [float(attrs["lon"]) for _node, attrs in graph.nodes(data=True)]
    return max(lats), min(lats), max(lons), min(lons)


def _build_edge_points(graph: nx.DiGraph) -> EdgePoints:
    edge_points: EdgePoints = []
    for u, v in graph.edges():
        points = edge_geometry_to_latlon(graph, int(u), int(v))
        if len(points) >= 2:
            edge_points.append((int(u), int(v), points))
    return edge_points


def _edge_point_lookup(edge_points: EdgePoints) -> EdgePointLookup:
    return {(u, v): points for u, v, points in edge_points}


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


def _add_network_edges(folium, fmap, edge_points: EdgePoints, max_edges: int) -> None:
    for idx, (_u, _v, points) in enumerate(edge_points):
        if idx >= max_edges:
            break
        folium.PolyLine(points, color="#64748b", weight=1, opacity=0.34).add_to(fmap)


def _spike_times_by_node(result: NavigationResult) -> dict[int, float]:
    raw = result.metadata.get("spike_times_by_node") or {}
    return {int(node): float(time_ms) for node, time_ms in raw.items()}


def _wavefront_frame_at_time(graph: nx.DiGraph, result: NavigationResult, time_ms: int) -> WavefrontFrame:
    spike_times = _spike_times_by_node(result)
    if not spike_times:
        if not result.wavefront_frames:
            return WavefrontFrame(t=int(time_ms), active_nodes=[], active_edges=[])
        candidates = [frame for frame in result.wavefront_frames if frame.t <= int(time_ms)]
        return candidates[-1] if candidates else result.wavefront_frames[0]

    t = int(time_ms)
    active_nodes = sorted(int(node) for node, spike_time in spike_times.items() if spike_time <= t)
    active_node_set = set(active_nodes)
    active_edges: list[tuple[int, int]] = []
    for u, v, attrs in graph.edges(data=True):
        if int(u) not in spike_times or int(v) not in active_node_set:
            continue
        source_time = float(spike_times[int(u)])
        delay = float(attrs.get("delay_ms", 1.0))
        if source_time + delay <= float(t) + 1e-9:
            active_edges.append((int(u), int(v)))
    return WavefrontFrame(t=t, active_nodes=active_nodes, active_edges=active_edges)


def _wavefront_inflight_edges_at_time(graph: nx.DiGraph, result: NavigationResult, time_ms: int) -> list[tuple[int, int]]:
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
        if source_time <= t < arrival and (target_time is None or target_time > t):
            inflight.append((int(u), int(v)))
    return inflight


def _newly_active_nodes_at_time(result: NavigationResult, time_ms: int) -> set[int]:
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
    if not result.wavefront_frames and not result.metadata.get("spike_times_by_node"):
        return WavefrontFrame(t=int(time_ms), active_nodes=[], active_edges=[])

    frame = _wavefront_frame_at_time(graph, result, int(time_ms))
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

    for u, v in frame.active_edges:
        points = _points_for_edge(edge_lookup, graph, u, v)
        if len(points) >= 2:
            folium.PolyLine(points, color="#06b6d4", weight=2, opacity=0.58).add_to(fmap)

    newly_active = _newly_active_nodes_at_time(result, int(time_ms))
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
    if result is None:
        return 0
    value = result.metadata.get("wavefront_time_max_ms")
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        pass
    return max((int(frame.t) for frame in result.wavefront_frames), default=0)


def _wavefront_time_caption(frame: WavefrontFrame, max_time_ms: int, drawn_node_count: int) -> str:
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
) -> None:
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
        folium.PolyLine(points, color="#dc2626", weight=6, opacity=0.95).add_to(fmap)
        car_point = points[min(car_index, len(points) - 1)]
        folium.Marker(
            car_point,
            tooltip="Car",
            icon=folium.Icon(color="red", icon="car", prefix="fa"),
        ).add_to(fmap)


def _default_points(graph: nx.DiGraph) -> tuple[float, float, float, float]:
    north, south, east, west = _graph_bounds(graph)
    return north, west, south, east


def _metric_float(result: NavigationResult | None, key: str) -> float:
    if result is None:
        return 0.0
    value = result.metadata.get(key, 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _reachability_status(graph: nx.DiGraph, start_node: int, goal_node: int) -> tuple[bool, str]:
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


def _load_graph_cached(st, mode: str, place: str, bbox_values: tuple[float, float, float, float], network_type: str):
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
    st, folium, st_folium = _imports()
    st.set_page_config(page_title="SNN Real-Map Navigation", layout="wide")
    st.title("Real Map + Brian2Loihi SNN Navigation")

    with st.sidebar:
        mode = st.radio("Map input", ["Place name", "Bounding box"], horizontal=True)
        network_type = st.selectbox("Network type", ["drive", "walk", "bike", "all"], index=0)
        tiles = st.selectbox("Map tiles", ["CartoDB dark_matter", "OpenStreetMap", "CartoDB positron"], index=0)
        place = st.text_input("Place name", value="Shinjuku, Tokyo, Japan")
        north = st.number_input("North", value=35.7040, format="%.6f")
        south = st.number_input("South", value=35.6810, format="%.6f")
        east = st.number_input("East", value=139.7160, format="%.6f")
        west = st.number_input("West", value=139.6850, format="%.6f")
        max_edges = st.slider("Road edges to draw", 200, 8000, 2500, 100)
        draw_base_roads = st.checkbox("Draw base roads", value=True)
        max_wavefront_nodes = st.slider("Wavefront nodes to draw", 50, 3000, 700, 50)
        use_loihi = st.checkbox("Use Brian2Loihi backend", value=True)
        load_clicked = st.button("Load OSM Map", type="primary")

    if load_clicked:
        try:
            with st.spinner("Loading OSM road network..."):
                st.session_state.road_graph = _load_graph_cached(
                    st,
                    mode,
                    place,
                    (float(north), float(south), float(east), float(west)),
                    network_type,
                )
                st.session_state.road_edge_points = _build_edge_points(st.session_state.road_graph)
                st.session_state.edge_point_lookup = _edge_point_lookup(st.session_state.road_edge_points)
                st.session_state.navigation_result = None
        except Exception as exc:
            st.error(
                f"{exc}\n\n"
                "Try a smaller bbox, check network access, or place a cached GraphML file under data/osm_cache."
            )
            return
    if "road_graph" not in st.session_state:
        st.info("Load an OSM map to start navigation.")
        return

    graph: nx.DiGraph = st.session_state.road_graph
    if "road_edge_points" not in st.session_state or "edge_point_lookup" not in st.session_state:
        st.session_state.road_edge_points = _build_edge_points(graph)
        st.session_state.edge_point_lookup = _edge_point_lookup(st.session_state.road_edge_points)
    edge_points: EdgePoints = st.session_state.road_edge_points
    edge_lookup: EdgePointLookup = st.session_state.edge_point_lookup
    default_start_lat, default_start_lon, default_goal_lat, default_goal_lon = _default_points(graph)

    col_a, col_b, col_c, col_d = st.columns(4)
    start_lat = col_a.number_input("Start latitude", value=float(default_start_lat), format="%.7f")
    start_lon = col_b.number_input("Start longitude", value=float(default_start_lon), format="%.7f")
    goal_lat = col_c.number_input("Goal latitude", value=float(default_goal_lat), format="%.7f")
    goal_lon = col_d.number_input("Goal longitude", value=float(default_goal_lon), format="%.7f")

    start_node = nearest_node_by_latlon(graph, float(start_lat), float(start_lon))
    goal_node = nearest_node_by_latlon(graph, float(goal_lat), float(goal_lon))
    path_exists, reachability_message = _reachability_status(graph, start_node, goal_node)
    if path_exists:
        st.caption(reachability_message)
    else:
        st.warning(f"{reachability_message} The goal neuron will not spike for this directed route.")

    run_clicked = st.button("Run SNN Navigation", type="primary")
    if run_clicked:
        with st.spinner("Running SNN wavefront navigation..."):
            st.session_state.navigation_result = run_navigation(
                graph,
                start_node,
                goal_node,
                use_loihi=bool(use_loihi),
            )

    result: NavigationResult | None = st.session_state.get("navigation_result")
    path_points = path_nodes_to_latlon(graph, result.path_nodes) if result else []
    car_index = 0
    if len(path_points) > 1:
        car_index = st.slider("Car position", 0, len(path_points) - 1, 0)
    wave_time_ms = 0
    wavefront_frame = WavefrontFrame(t=0, active_nodes=[], active_edges=[])
    max_wave_time_ms = _wavefront_time_limit(result)
    if result and result.wavefront_frames:
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

    center = _graph_center(graph)
    fmap = folium.Map(location=center, zoom_start=14, tiles=tiles, prefer_canvas=True, control_scale=True)
    if draw_base_roads:
        _add_network_edges(folium, fmap, edge_points, int(max_edges))
    if result:
        wavefront_frame = _add_wavefront_timestep(
            folium,
            fmap,
            graph,
            result,
            wave_time_ms,
            edge_lookup,
            int(max_wavefront_nodes),
        )
    _add_path_and_markers(folium, fmap, graph, result, start_node, goal_node, car_index)
    _fit_map_bounds(fmap, graph, path_points)

    if result and result.wavefront_frames:
        st.caption(_wavefront_time_caption(wavefront_frame, max_wave_time_ms, int(max_wavefront_nodes)))

    st_folium(fmap, width=None, height=720, returned_objects=[])

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
        }
    )
    if result and result.metadata.get("error"):
        st.warning(result.metadata["error"])


if __name__ == "__main__":
    main()
