"""SUMO net.xml geometry parsing.

This module keeps SUMO edge and lane shapes as the display source of truth.
The NetworkX graph used for planning is derived from this geometry, not the
other way around.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


Point2D = tuple[float, float]


@dataclass(frozen=True)
class SumoNodeGeometry:
    node_id: str
    x: float
    y: float
    node_type: str | None = None


@dataclass(frozen=True)
class SumoLaneGeometry:
    lane_id: str
    index: int
    speed: float | None
    length: float | None
    shape: tuple[Point2D, ...]


@dataclass(frozen=True)
class SumoEdgeGeometry:
    edge_id: str
    from_node: str | None
    to_node: str | None
    function: str | None
    lanes: tuple[SumoLaneGeometry, ...]
    shape: tuple[Point2D, ...]

    @property
    def is_internal(self) -> bool:
        return self.edge_id.startswith(":") or self.function in {"internal", "walkingarea"}

    @property
    def lane_ids(self) -> list[str]:
        return [lane.lane_id for lane in self.lanes]


@dataclass(frozen=True)
class SumoMapGeometry:
    netxml_path: str
    nodes: dict[str, SumoNodeGeometry]
    edges: dict[str, SumoEdgeGeometry]

    def bounds(self) -> tuple[float, float, float, float]:
        points: list[Point2D] = []
        for edge in self.edges.values():
            points.extend(edge.shape)
        if not points:
            points = [(node.x, node.y) for node in self.nodes.values()]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return min(xs), min(ys), max(xs), max(ys)


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_shape_points(shape: str | None) -> tuple[Point2D, ...]:
    """Parse a SUMO lane shape into 2D points.

    SUMO shape tokens may be "x,y" or "x,y,z". The z value is preserved by
    SUMO but is not needed for 2D route overlay.
    """
    if not shape:
        return tuple()

    points: list[Point2D] = []
    for token in shape.split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        x = _float_or_none(parts[0])
        y = _float_or_none(parts[1])
        if x is None or y is None:
            continue
        points.append((float(x), float(y)))
    return tuple(points)


def _fallback_edge_shape(
    edge_attrs: dict[str, str],
    nodes: dict[str, SumoNodeGeometry],
) -> tuple[Point2D, ...]:
    source = edge_attrs.get("from")
    target = edge_attrs.get("to")
    if source in nodes and target in nodes:
        return ((nodes[source].x, nodes[source].y), (nodes[target].x, nodes[target].y))
    return tuple()


def _select_edge_shape(
    lanes: tuple[SumoLaneGeometry, ...],
    fallback_shape: tuple[Point2D, ...],
) -> tuple[Point2D, ...]:
    shaped_lanes = [lane for lane in lanes if lane.shape]
    if shaped_lanes:
        lane = max(shaped_lanes, key=lambda item: item.length or len(item.shape))
        return lane.shape
    return fallback_shape


def load_sumo_network_geometry(
    netxml_path: str | Path,
    ignore_internal_edges: bool = True,
) -> SumoMapGeometry:
    """Load SUMO net.xml while preserving original lane polylines."""
    path = Path(netxml_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"SUMO net.xml not found: {path}")

    root = ET.parse(path).getroot()
    nodes: dict[str, SumoNodeGeometry] = {}
    for junction in root.findall("junction"):
        node_id = junction.attrib.get("id")
        x = _float_or_none(junction.attrib.get("x"))
        y = _float_or_none(junction.attrib.get("y"))
        if node_id is None or x is None or y is None:
            continue
        nodes[str(node_id)] = SumoNodeGeometry(
            node_id=str(node_id),
            x=float(x),
            y=float(y),
            node_type=junction.attrib.get("type"),
        )

    edges: dict[str, SumoEdgeGeometry] = {}
    for edge in root.findall("edge"):
        edge_id = str(edge.attrib.get("id", ""))
        if not edge_id:
            continue
        function = edge.attrib.get("function")
        if ignore_internal_edges and (edge_id.startswith(":") or function in {"internal", "walkingarea"}):
            continue

        lanes: list[SumoLaneGeometry] = []
        for lane in edge.findall("lane"):
            lane_id = lane.attrib.get("id")
            if not lane_id:
                continue
            try:
                lane_index = int(lane.attrib.get("index", len(lanes)))
            except ValueError:
                lane_index = len(lanes)
            lanes.append(
                SumoLaneGeometry(
                    lane_id=str(lane_id),
                    index=lane_index,
                    speed=_float_or_none(lane.attrib.get("speed")),
                    length=_float_or_none(lane.attrib.get("length")),
                    shape=parse_shape_points(lane.attrib.get("shape")),
                )
            )

        fallback_shape = _fallback_edge_shape(edge.attrib, nodes)
        edge_shape = _select_edge_shape(tuple(lanes), fallback_shape)
        edges[edge_id] = SumoEdgeGeometry(
            edge_id=edge_id,
            from_node=edge.attrib.get("from"),
            to_node=edge.attrib.get("to"),
            function=function,
            lanes=tuple(lanes),
            shape=edge_shape,
        )

    return SumoMapGeometry(netxml_path=str(path), nodes=nodes, edges=edges)
