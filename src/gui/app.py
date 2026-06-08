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
from navigation import NavigationResult, run_navigation


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


def _add_network_edges(folium, fmap, graph: nx.DiGraph, max_edges: int) -> None:
    for idx, (u, v) in enumerate(graph.edges()):
        if idx >= max_edges:
            break
        points = edge_geometry_to_latlon(graph, int(u), int(v))
        if len(points) >= 2:
            folium.PolyLine(points, color="#64748b", weight=1, opacity=0.42).add_to(fmap)


def _add_wavefront(folium, fmap, graph: nx.DiGraph, result: NavigationResult, frame_index: int) -> None:
    if not result.wavefront_frames:
        return
    frame = result.wavefront_frames[min(frame_index, len(result.wavefront_frames) - 1)]
    for u, v in frame.active_edges:
        points = edge_geometry_to_latlon(graph, u, v)
        if len(points) >= 2:
            folium.PolyLine(points, color="#06b6d4", weight=2, opacity=0.55).add_to(fmap)
    for node in frame.active_nodes:
        attrs = graph.nodes[node]
        folium.CircleMarker(
            location=(float(attrs["lat"]), float(attrs["lon"])),
            radius=3,
            color="#0e7490",
            fill=True,
            fill_opacity=0.72,
            weight=0,
        ).add_to(fmap)


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
    wave_idx = 0
    if result and result.wavefront_frames:
        if not result.metadata.get("success"):
            st.warning("No final path was found. The wavefront frames below show partial propagation only.")
        if len(result.wavefront_frames) > 1:
            wave_idx = st.slider(
                "Wavefront frame index",
                0,
                len(result.wavefront_frames) - 1,
                len(result.wavefront_frames) - 1,
            )
        else:
            wave_idx = 0
        frame = result.wavefront_frames[wave_idx]
        st.caption(
            f"Wavefront frame {wave_idx}/{len(result.wavefront_frames) - 1}, "
            f"t={frame.t} ms, active_nodes={len(frame.active_nodes)}, active_edges={len(frame.active_edges)}"
        )

    center = _graph_center(graph)
    fmap = folium.Map(location=center, zoom_start=14, tiles=tiles)
    _add_network_edges(folium, fmap, graph, int(max_edges))
    if result:
        _add_wavefront(folium, fmap, graph, result, wave_idx)
    _add_path_and_markers(folium, fmap, graph, result, start_node, goal_node, car_index)
    _fit_map_bounds(fmap, graph, path_points)

    st_folium(fmap, width=None, height=720)

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
