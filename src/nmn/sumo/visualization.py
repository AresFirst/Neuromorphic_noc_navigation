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
    background_edges = [edge for edge in geometry.edges.values() if edge.edge_id not in route_edge_set]
    if max_background_edges is not None and len(background_edges) > max_background_edges:
        rng = random.Random(0)
        background_edges = rng.sample(background_edges, int(max_background_edges))

    fig, ax = plt.subplots(figsize=(14, 10), dpi=220, facecolor=background_color)
    ax.set_facecolor(background_color)
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

    if route_segments:
        for segment in route_segments:
            _plot_shape(
                ax,
                segment.get("shape") or [],
                color=route_outline_color,
                linewidth=route_outline_linewidth,
                alpha=0.95,
                zorder=3,
            )
            _plot_shape(
                ax,
                segment.get("shape") or [],
                color=route_color,
                linewidth=route_linewidth,
                alpha=1.0,
                zorder=4,
            )
    else:
        for edge_id in route_edge_set:
            edge = geometry.edges.get(edge_id)
            if edge is not None:
                _plot_shape(
                    ax,
                    edge.shape,
                    color=route_outline_color,
                    linewidth=route_outline_linewidth,
                    alpha=0.95,
                    zorder=3,
                )
                _plot_shape(
                    ax,
                    edge.shape,
                    color=route_color,
                    linewidth=route_linewidth,
                    alpha=1.0,
                    zorder=4,
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
