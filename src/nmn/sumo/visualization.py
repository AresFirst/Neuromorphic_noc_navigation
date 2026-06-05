"""Geometry-preserving SUMO route overlay visualization."""

from __future__ import annotations

import os
import random
from pathlib import Path

_MPL_CACHE = Path(__file__).resolve().parents[3] / ".matplotlib-cache"
_MPL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPL_CACHE))

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import networkx as nx

from .geometry import SumoMapGeometry


def _plot_shape(ax, shape, *, color: str, linewidth: float, alpha: float, zorder: int) -> None:
    if len(shape) < 2:
        return
    xs = [float(point[0]) for point in shape]
    ys = [float(point[1]) for point in shape]
    ax.plot(xs, ys, color=color, linewidth=linewidth, alpha=alpha, zorder=zorder)


def _edge_shapes(edge, *, draw_lane_shapes: bool) -> list:
    if draw_lane_shapes:
        lane_shapes = [lane.shape for lane in edge.lanes if len(lane.shape) >= 2]
        if lane_shapes:
            return lane_shapes
    return [edge.shape] if len(edge.shape) >= 2 else []


def _collect_route_points(
    geometry: SumoMapGeometry,
    route_edge_ids: set[str],
    route_segments: list[dict] | None,
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if route_segments:
        for segment in route_segments:
            for point in segment.get("shape") or []:
                if len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
        return points

    for edge_id in route_edge_ids:
        edge = geometry.edges.get(edge_id)
        if edge is not None:
            points.extend(edge.shape)
    return points


def _zoom_to_points(ax, points: list[tuple[float, float]], padding: float | None) -> None:
    if not points:
        return
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span = max(max_x - min_x, max_y - min_y)
    pad = float(padding) if padding is not None else max(120.0, span * 0.35)
    ax.set_xlim(min_x - pad, max_x + pad)
    ax.set_ylim(min_y - pad, max_y + pad)


def _node_xy(G: nx.DiGraph, node) -> tuple[float, float] | None:
    if node not in G:
        return None
    attrs = G.nodes[node]
    if "x" not in attrs or "y" not in attrs:
        return None
    return float(attrs["x"]), float(attrs["y"])


def _edge_shape_from_graph(G: nx.DiGraph, source, target) -> list:
    if not G.has_edge(source, target):
        return []
    attrs = G[source][target]
    shape = attrs.get("shape") or []
    if len(shape) >= 2:
        return shape
    source_xy = _node_xy(G, source)
    target_xy = _node_xy(G, target)
    if source_xy is None or target_xy is None:
        return []
    return [source_xy, target_xy]


def _draw_background_roads(
    ax,
    geometry: SumoMapGeometry,
    route_edge_set: set[str],
    max_background_edges: int | None,
    draw_lane_shapes: bool,
    road_color: str,
    road_linewidth: float,
    road_alpha: float,
) -> None:
    background_edges = [edge for edge in geometry.edges.values() if edge.edge_id not in route_edge_set]
    if max_background_edges is not None and len(background_edges) > max_background_edges:
        rng = random.Random(0)
        background_edges = rng.sample(background_edges, int(max_background_edges))
    for edge in background_edges:
        for shape in _edge_shapes(edge, draw_lane_shapes=draw_lane_shapes):
            _plot_shape(
                ax,
                shape,
                color=road_color,
                linewidth=road_linewidth,
                alpha=road_alpha,
                zorder=1,
            )


def _draw_route_segments(
    ax,
    route_segments: list[dict] | None,
    geometry: SumoMapGeometry,
    route_edge_set: set[str],
    route_color: str,
    route_linewidth: float,
    route_outline_color: str,
    route_outline_linewidth: float,
) -> None:
    if route_segments:
        for segment in route_segments:
            shape = segment.get("shape") or []
            _plot_shape(
                ax,
                shape,
                color=route_outline_color,
                linewidth=route_outline_linewidth,
                alpha=0.95,
                zorder=7,
            )
            _plot_shape(
                ax,
                shape,
                color=route_color,
                linewidth=route_linewidth,
                alpha=1.0,
                zorder=8,
            )
        return

    for edge_id in route_edge_set:
        edge = geometry.edges.get(edge_id)
        if edge is not None:
            _plot_shape(
                ax,
                edge.shape,
                color=route_outline_color,
                linewidth=route_outline_linewidth,
                alpha=0.95,
                zorder=7,
            )
            _plot_shape(
                ax,
                edge.shape,
                color=route_color,
                linewidth=route_linewidth,
                alpha=1.0,
                zorder=8,
            )


def draw_sumo_route_overlay(
    geometry: SumoMapGeometry,
    route_edge_ids: list[str] | None = None,
    *,
    route_segments: list[dict] | None = None,
    save_path: str,
    max_background_edges: int | None = None,
    title: str | None = None,
    background_color: str = "#f8fafc",
    road_color: str = "#334155",
    road_linewidth: float = 0.5,
    road_alpha: float = 0.72,
    route_color: str = "#dc2626",
    route_linewidth: float = 3.0,
    route_outline_color: str = "#ffffff",
    route_outline_linewidth: float = 5.4,
    draw_lane_shapes: bool = True,
    zoom_to_route: bool = False,
    route_padding: float | None = None,
) -> None:
    """Draw route over original SUMO lane polylines.

    This is intentionally not a NetworkX node/edge visualization. It uses the
    original SUMO lane shapes as the map layer.
    """
    output = Path(save_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    route_edge_set = {str(edge_id) for edge_id in route_edge_ids or []}

    fig, ax = plt.subplots(figsize=(14, 10), dpi=220, facecolor=background_color)
    ax.set_facecolor(background_color)
    _draw_background_roads(
        ax,
        geometry,
        route_edge_set,
        max_background_edges,
        draw_lane_shapes,
        road_color,
        road_linewidth,
        road_alpha,
    )
    _draw_route_segments(
        ax,
        route_segments,
        geometry,
        route_edge_set,
        route_color,
        route_linewidth,
        route_outline_color,
        route_outline_linewidth,
    )

    if zoom_to_route:
        route_points = _collect_route_points(geometry, route_edge_set, route_segments)
        _zoom_to_points(ax, route_points, route_padding)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=11)
    fig.tight_layout(pad=0.2)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def draw_sumo_dynamic_frame(
    geometry: SumoMapGeometry,
    G: nx.DiGraph,
    *,
    save_path: str,
    route_segments: list[dict] | None = None,
    wavefront_result: dict | None = None,
    wavefront_time_ms: float | None = None,
    vehicle_positions: list[dict] | None = None,
    congested_edges: list[tuple[int, int]] | None = None,
    blocked_edges: list[tuple[int, int]] | None = None,
    current_node: int | None = None,
    target_node: int | None = None,
    title: str | None = None,
    max_background_edges: int | None = None,
    zoom_to_route: bool = False,
    route_padding: float | None = None,
    background_color: str = "#f8fafc",
    road_color: str = "#334155",
    road_linewidth: float = 0.42,
    road_alpha: float = 0.58,
    draw_lane_shapes: bool = True,
) -> None:
    """Draw one dynamic SUMO frame with traffic, congestion, and SNN wavefront."""
    output = Path(save_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    route_edge_ids = {str(segment.get("sumo_edge_id")) for segment in route_segments or []}
    fig, ax = plt.subplots(figsize=(14, 10), dpi=180, facecolor=background_color)
    ax.set_facecolor(background_color)

    _draw_background_roads(
        ax,
        geometry,
        route_edge_ids,
        max_background_edges,
        draw_lane_shapes,
        road_color,
        road_linewidth,
        road_alpha,
    )

    for source, target in congested_edges or []:
        _plot_shape(
            ax,
            _edge_shape_from_graph(G, source, target),
            color="#f59e0b",
            linewidth=2.2,
            alpha=0.88,
            zorder=3,
        )
    for source, target in blocked_edges or []:
        _plot_shape(
            ax,
            _edge_shape_from_graph(G, source, target),
            color="#111827",
            linewidth=2.8,
            alpha=0.95,
            zorder=4,
        )

    if wavefront_result and wavefront_time_ms is not None:
        spike_times = {
            node: float(time_ms)
            for node, time_ms in wavefront_result.get("spike_times_by_neuron", {}).items()
            if float(time_ms) <= float(wavefront_time_ms)
        }
        active_nodes = set(spike_times)
        for source, target, attrs in G.edges(data=True):
            if attrs.get("state") == "blocked":
                continue
            if source in active_nodes and target in active_nodes:
                source_time = float(spike_times[source])
                delay_ms = float(attrs.get("delay_ms", 1))
                if source_time + delay_ms <= float(wavefront_time_ms) + 1e-9:
                    _plot_shape(
                        ax,
                        _edge_shape_from_graph(G, source, target),
                        color="#06b6d4",
                        linewidth=1.4,
                        alpha=0.62,
                        zorder=5,
                    )

        xs: list[float] = []
        ys: list[float] = []
        colors: list[float] = []
        for node, spike_time in spike_times.items():
            xy = _node_xy(G, node)
            if xy is None:
                continue
            xs.append(xy[0])
            ys.append(xy[1])
            colors.append(spike_time)
        if xs:
            ax.scatter(
                xs,
                ys,
                c=colors,
                cmap="viridis",
                s=14,
                linewidths=0,
                alpha=0.9,
                zorder=6,
            )

    _draw_route_segments(
        ax,
        route_segments,
        geometry,
        route_edge_ids,
        route_color="#dc2626",
        route_linewidth=3.0,
        route_outline_color="#ffffff",
        route_outline_linewidth=5.4,
    )

    if vehicle_positions:
        xs = [float(vehicle["x"]) for vehicle in vehicle_positions]
        ys = [float(vehicle["y"]) for vehicle in vehicle_positions]
        ax.scatter(
            xs,
            ys,
            s=16,
            color="#2563eb",
            edgecolors="#eff6ff",
            linewidths=0.6,
            alpha=0.9,
            zorder=9,
        )

    for node, color, marker, size in [
        (current_node, "#16a34a", "o", 54),
        (target_node, "#7c3aed", "*", 92),
    ]:
        if node is None:
            continue
        xy = _node_xy(G, node)
        if xy is None:
            continue
        ax.scatter(
            [xy[0]],
            [xy[1]],
            s=size,
            color=color,
            marker=marker,
            edgecolors="#ffffff",
            linewidths=1.2,
            zorder=10,
        )

    if zoom_to_route:
        route_points = _collect_route_points(geometry, route_edge_ids, route_segments)
        if vehicle_positions:
            route_points.extend((float(v["x"]), float(v["y"])) for v in vehicle_positions)
        _zoom_to_points(ax, route_points, route_padding)

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=11)
    fig.tight_layout(pad=0.2)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
