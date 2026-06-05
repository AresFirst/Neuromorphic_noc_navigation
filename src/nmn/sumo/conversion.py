"""Conversion between SUMO geometry, temporary DiGraph, and SNN paths."""

from __future__ import annotations

import math
import random
from collections import deque
from pathlib import Path
from typing import Any

import networkx as nx

from nmn.loihi import infer_parent_trace_from_spikes, reconstruct_path_from_parent

from .geometry import SumoEdgeGeometry, SumoMapGeometry, load_sumo_network_geometry


def _polyline_length(shape: tuple[tuple[float, float], ...]) -> float:
    if len(shape) < 2:
        return 0.0
    return float(
        sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(shape, shape[1:]))
    )


def _edge_base_cost(
    edge: SumoEdgeGeometry,
    use_travel_time_if_speed_available: bool,
) -> tuple[float, float, float | None]:
    lane_lengths = [lane.length for lane in edge.lanes if lane.length is not None and lane.length > 0]
    lane_speeds = [lane.speed for lane in edge.lanes if lane.speed is not None and lane.speed > 0]
    distance = float(sum(lane_lengths) / len(lane_lengths)) if lane_lengths else _polyline_length(edge.shape)
    distance = distance if distance > 0.0 else 1e-9
    speed = float(sum(lane_speeds) / len(lane_speeds)) if lane_speeds else None
    if use_travel_time_if_speed_available and speed is not None and speed > 0.0:
        base_cost = distance / speed
    else:
        base_cost = distance
    return float(distance), float(base_cost), speed


def _largest_scc_copy(G: nx.DiGraph) -> nx.DiGraph:
    if G.number_of_nodes() == 0:
        raise ValueError("cannot select SCC from an empty graph")
    components = list(nx.strongly_connected_components(G))
    if not components:
        raise ValueError("graph has no strongly connected component")
    return G.subgraph(max(components, key=len)).copy()


def _crop_by_bfs(G: nx.DiGraph, max_nodes: int, seed: int) -> nx.DiGraph:
    if G.number_of_nodes() <= max_nodes:
        return G.copy()
    rng = random.Random(seed)
    candidates = sorted(
        G.nodes(),
        key=lambda node: (G.in_degree(node) + G.out_degree(node), str(node)),
        reverse=True,
    )[: min(25, G.number_of_nodes())]
    rng.shuffle(candidates)
    center = candidates[0]

    undirected = G.to_undirected(as_view=True)
    selected: list[Any] = []
    seen = {center}
    queue: deque[Any] = deque([center])
    while queue and len(selected) < max_nodes:
        node = queue.popleft()
        selected.append(node)
        neighbors = sorted(
            undirected.neighbors(node),
            key=lambda item: (G.in_degree(item) + G.out_degree(item), str(item)),
            reverse=True,
        )
        for neighbor in neighbors:
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    return G.subgraph(selected[:max_nodes]).copy()


def _assign_delay_ms(G: nx.DiGraph, min_delay_ms: int, max_delay_ms: int) -> None:
    costs = [float(attrs.get("base_cost", 1.0)) for _, _, attrs in G.edges(data=True)]
    if not costs:
        return
    min_cost = min(costs)
    max_cost = max(costs)
    for _u, _v, attrs in G.edges(data=True):
        base_cost = float(attrs.get("base_cost", 1.0))
        if math.isclose(min_cost, max_cost):
            delay_ms = int(min_delay_ms)
        else:
            normalized = (base_cost - min_cost) / (max_cost - min_cost)
            delay_ms = int(round(min_delay_ms + normalized * (max_delay_ms - min_delay_ms)))
        delay_ms = max(min_delay_ms, min(max_delay_ms, delay_ms))
        attrs["delay_ms"] = int(delay_ms)
        attrs["original_delay_ms"] = int(delay_ms)
        attrs["state"] = str(attrs.get("state", "normal"))


def _relabel_to_int_nodes(G: nx.DiGraph) -> nx.DiGraph:
    mapping = {node: idx for idx, node in enumerate(G.nodes())}
    relabeled = nx.relabel_nodes(G, mapping, copy=True)
    int_to_sumo = {int_node: str(sumo_node) for sumo_node, int_node in mapping.items()}
    sumo_to_int = {str(sumo_node): int(int_node) for sumo_node, int_node in mapping.items()}
    for int_node, sumo_node in int_to_sumo.items():
        relabeled.nodes[int_node]["sumo_node_id"] = sumo_node
    relabeled.graph["node_id_to_sumo_id"] = int_to_sumo
    relabeled.graph["sumo_node_id_to_node_id"] = sumo_to_int
    return relabeled


def _positive_int(value: object, fallback: int) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return int(fallback)
    return max(1, parsed)


def prepare_graph_for_snn_planning(
    G: nx.DiGraph,
    *,
    min_delay_ms: int = 1,
    max_delay_ms: int | None = None,
) -> nx.DiGraph:
    """Return a copy with valid SNN delays and blocked edge states preserved."""
    if min_delay_ms < 1:
        raise ValueError("min_delay_ms must be positive")
    if max_delay_ms is not None and max_delay_ms < min_delay_ms:
        raise ValueError("max_delay_ms must be >= min_delay_ms")

    prepared = G.copy()
    for _source, _target, attrs in prepared.edges(data=True):
        state = str(attrs.get("state", "normal"))
        delay_ms = _positive_int(attrs.get("delay_ms", attrs.get("original_delay_ms", min_delay_ms)), min_delay_ms)
        delay_ms = max(min_delay_ms, delay_ms)
        if max_delay_ms is not None:
            delay_ms = min(delay_ms, int(max_delay_ms))
        attrs["delay_ms"] = int(delay_ms)
        attrs["state"] = "blocked" if state == "blocked" else ("congested" if state == "congested" else "normal")
    return prepared


def most_to_digraph(
    netxml_path: str | Path,
    *,
    ignore_internal_edges: bool = True,
    use_travel_time_if_speed_available: bool = True,
    min_delay_ms: int = 1,
    max_delay_ms: int = 10,
    largest_strongly_connected_component: bool = True,
    max_nodes: int | None = None,
    seed: int = 0,
    relabel_nodes_to_int: bool = True,
) -> tuple[nx.DiGraph, SumoMapGeometry]:
    """Create a temporary planning graph from SUMO geometry.

    The returned DiGraph carries SUMO ids and edge shapes in attributes so a
    computed path can be mapped back to original SUMO roads for visualization.
    """
    if min_delay_ms < 1:
        raise ValueError("min_delay_ms must be positive")
    if max_delay_ms < min_delay_ms:
        raise ValueError("max_delay_ms must be >= min_delay_ms")
    if max_nodes is not None and max_nodes < 2:
        raise ValueError("max_nodes must be >= 2 or None")

    geometry = load_sumo_network_geometry(netxml_path, ignore_internal_edges=ignore_internal_edges)
    graph = nx.DiGraph()
    for node_id, node in geometry.nodes.items():
        graph.add_node(node_id, x=float(node.x), y=float(node.y), sumo_node_id=node_id)

    for edge_id, edge in geometry.edges.items():
        if edge.from_node not in graph or edge.to_node not in graph or edge.from_node == edge.to_node:
            continue
        distance, base_cost, speed = _edge_base_cost(edge, use_travel_time_if_speed_available)
        attrs = {
            "sumo_edge_id": edge_id,
            "original_edge_id": edge_id,
            "merged_sumo_edge_ids": [edge_id],
            "lane_ids": edge.lane_ids,
            "from_sumo_node_id": edge.from_node,
            "to_sumo_node_id": edge.to_node,
            "shape": [list(point) for point in edge.shape],
            "distance": float(distance),
            "base_cost": float(base_cost),
            "speed": speed,
            "source": "sumo",
            "state": "normal",
        }
        if graph.has_edge(edge.from_node, edge.to_node):
            existing = graph[edge.from_node][edge.to_node]
            existing_ids = list(existing.get("merged_sumo_edge_ids", [existing.get("sumo_edge_id")]))
            existing_ids.append(edge_id)
            if float(base_cost) < float(existing.get("base_cost", math.inf)):
                attrs["merged_sumo_edge_ids"] = existing_ids
                graph[edge.from_node][edge.to_node].update(attrs)
            else:
                existing["merged_sumo_edge_ids"] = existing_ids
        else:
            graph.add_edge(edge.from_node, edge.to_node, **attrs)

    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise ValueError("SUMO network produced an empty planning graph")

    if largest_strongly_connected_component:
        graph = _largest_scc_copy(graph)
    if max_nodes is not None and graph.number_of_nodes() > max_nodes:
        graph = _crop_by_bfs(graph, max_nodes=max_nodes, seed=seed)
        if largest_strongly_connected_component:
            graph = _largest_scc_copy(graph)

    _assign_delay_ms(graph, min_delay_ms=min_delay_ms, max_delay_ms=max_delay_ms)
    graph.graph.update(
        {
            "source": "sumo",
            "sumo_netxml_path": geometry.netxml_path,
            "geometry_preserved": True,
            "visualization_source": "sumo_netxml",
            "num_nodes_before_crop": len(geometry.nodes),
            "num_edges_before_crop": len(geometry.edges),
        }
    )
    if relabel_nodes_to_int:
        graph = _relabel_to_int_nodes(graph)
        graph.graph.update(
            {
                "source": "sumo",
                "sumo_netxml_path": geometry.netxml_path,
                "geometry_preserved": True,
                "visualization_source": "sumo_netxml",
                "num_nodes_before_crop": len(geometry.nodes),
                "num_edges_before_crop": len(geometry.edges),
            }
        )
    return graph, geometry


def digraph_to_snn(G: nx.DiGraph) -> nx.DiGraph:
    """Prepare the temporary graph for Brian2Loihi wavefront planning."""
    return prepare_graph_for_snn_planning(G)


def snn_output_to_path(
    G: nx.DiGraph,
    wavefront_result: dict,
    start: int,
    target: int,
    delay_attr: str = "delay_ms",
) -> list[int]:
    """Convert Brian2Loihi spike output back into a graph node path."""
    if not wavefront_result.get("success"):
        raise ValueError(f"SNN planning failed: {wavefront_result.get('error')}")
    parent_trace = infer_parent_trace_from_spikes(
        G,
        wavefront_result["spike_times_by_neuron"],
        start,
        delay_attr=delay_attr,
    )
    return reconstruct_path_from_parent(parent_trace, start, target)


def path_to_sumo_route(G: nx.DiGraph, path: list[int]) -> dict:
    """Map a planning graph path back to SUMO edge ids and geometry."""
    route_edges: list[str] = []
    segments: list[dict] = []
    for source, target in zip(path, path[1:]):
        if not G.has_edge(source, target):
            raise ValueError(f"path contains missing graph edge ({source}, {target})")
        attrs = G[source][target]
        edge_id = str(attrs.get("sumo_edge_id") or attrs.get("original_edge_id") or f"{source}->{target}")
        shape = attrs.get("shape") or []
        route_edges.append(edge_id)
        segments.append(
            {
                "graph_source": int(source) if isinstance(source, int) else source,
                "graph_target": int(target) if isinstance(target, int) else target,
                "sumo_edge_id": edge_id,
                "from_sumo_node_id": attrs.get("from_sumo_node_id"),
                "to_sumo_node_id": attrs.get("to_sumo_node_id"),
                "lane_ids": list(attrs.get("lane_ids", [])),
                "shape": shape,
                "delay_ms": int(attrs.get("delay_ms", 1)),
                "base_cost": float(attrs.get("base_cost", 0.0)),
            }
        )

    node_sumo_ids = [G.nodes[node].get("sumo_node_id", str(node)) for node in path]
    return {
        "graph_path": list(path),
        "sumo_node_ids": node_sumo_ids,
        "sumo_edge_ids": route_edges,
        "segments": segments,
    }
