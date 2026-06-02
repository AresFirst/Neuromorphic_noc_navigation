"""SUMO `.net.xml` 路网解析器。

本模块只做原始 XML 到道路 DiGraph 的转换，不做延迟归一化、
强连通裁剪或节点重编号。这些标准化步骤由 road_graph_normalizer 负责。
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import networkx as nx


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _positive_average(values: list[float]) -> float | None:
    positives = [value for value in values if value > 0.0]
    if not positives:
        return None
    return float(sum(positives) / len(positives))


def _euclidean_distance(G: nx.DiGraph, source: str, target: str) -> float:
    x1 = float(G.nodes[source]["x"])
    y1 = float(G.nodes[source]["y"])
    x2 = float(G.nodes[target]["x"])
    y2 = float(G.nodes[target]["y"])
    return float(math.hypot(x2 - x1, y2 - y1))


def load_sumo_netxml_as_graph(
    netxml_path: str,
    ignore_internal_edges: bool = True,
    use_travel_time_if_speed_available: bool = True,
) -> nx.DiGraph:
    """解析 SUMO `.net.xml` 为原始有向道路图。

    Junction 被转换为节点，edge 被转换为有向边。若同一对 junction 之间
    存在多条 SUMO edge，本实现保留 `base_cost` 最小的那条边，并在
    `merged_edge_ids` 中记录被合并的原始 edge id。

    Args:
        netxml_path: SUMO `.net.xml` 文件路径。
        ignore_internal_edges: 是否忽略 id 以 ":" 开头的 internal edge。
        use_travel_time_if_speed_available: 若 speed 可用，base_cost 使用 length / speed。

    Returns:
        原始 `nx.DiGraph`，节点 id 仍为 SUMO junction id。
    """
    path = Path(netxml_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"SUMO net.xml not found: {path}")

    root = ET.parse(path).getroot()
    graph = nx.DiGraph()
    graph.graph.update({"dataset_type": "sumo_netxml", "netxml_path": str(path)})

    for junction in root.findall("junction"):
        junction_id = junction.attrib.get("id")
        x = _float_or_none(junction.attrib.get("x"))
        y = _float_or_none(junction.attrib.get("y"))
        if junction_id is None or x is None or y is None:
            continue
        graph.add_node(
            junction_id,
            x=float(x),
            y=float(y),
            source="most_raw",
            original_id=str(junction_id),
        )

    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if ignore_internal_edges and edge_id.startswith(":"):
            continue
        source = edge.attrib.get("from")
        target = edge.attrib.get("to")
        if source is None or target is None:
            continue
        if source not in graph or target not in graph:
            continue

        lanes = edge.findall("lane")
        lane_lengths = [
            value for lane in lanes if (value := _float_or_none(lane.attrib.get("length"))) is not None
        ]
        lane_speeds = [
            value for lane in lanes if (value := _float_or_none(lane.attrib.get("speed"))) is not None
        ]

        avg_length = _positive_average(lane_lengths)
        avg_speed = _positive_average(lane_speeds)
        distance = avg_length if avg_length is not None else _euclidean_distance(graph, source, target)
        if distance <= 0.0:
            continue

        if use_travel_time_if_speed_available and avg_speed is not None and avg_speed > 0.0:
            base_cost = distance / avg_speed
        else:
            base_cost = distance
        if base_cost <= 0.0:
            continue

        attrs = {
            "distance": float(distance),
            "base_cost": float(base_cost),
            "speed": float(avg_speed) if avg_speed is not None else None,
            "num_lanes": int(len(lanes)),
            "source": "most_raw",
            "original_edge_id": str(edge_id),
            "merged_edge_ids": [str(edge_id)],
        }

        if graph.has_edge(source, target):
            existing = graph[source][target]
            merged_ids = list(existing.get("merged_edge_ids", [existing.get("original_edge_id")]))
            merged_ids.append(str(edge_id))
            if float(base_cost) < float(existing.get("base_cost", math.inf)):
                attrs["merged_edge_ids"] = merged_ids
                graph[source][target].update(attrs)
            else:
                existing["merged_edge_ids"] = merged_ids
        else:
            graph.add_edge(source, target, **attrs)

    return graph
