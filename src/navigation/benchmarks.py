"""Independent shortest-path benchmarks for route-planning comparison."""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Sequence

import networkx as nx


@dataclass(slots=True)
class AlgorithmBenchmarkResult:
    """Runtime and route summary for one non-SNN path algorithm."""

    algorithm: str
    label: str
    success: bool
    runtime_sec: float
    path_nodes: list[int] = field(default_factory=list)
    path_edges: list[tuple[int, int]] = field(default_factory=list)
    total_cost: float | None = None
    path_length_m: float = 0.0
    path_travel_time_s: float = 0.0
    runtime_scope: str = "隔离图快照上的完整路径重算"
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path_node_count"] = len(self.path_nodes)
        payload["path_edge_count"] = len(self.path_edges)
        return payload


RouteFunction = Callable[[nx.DiGraph, int, int, str], list[int]]


def _positive_float(value: object) -> float | None:
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(parsed) and parsed > 0.0:
        return parsed
    return None


def _finite_float(value: object) -> float | None:
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(parsed):
        return parsed
    return None


def _edge_weight(attrs: dict[str, object], cost_attr: str) -> float:
    # Keep classical algorithms on their own weight model. They do not read SNN
    # spike times, parent traces, or reconstructed SNN paths.
    for key in (cost_attr, "travel_time", "length"):
        parsed = _positive_float(attrs.get(key))
        if parsed is not None:
            return parsed
    return 1.0


def _weight_function(cost_attr: str) -> Callable[[int, int, dict[str, object]], float]:
    def weight(_u: int, _v: int, attrs: dict[str, object]) -> float:
        return _edge_weight(attrs, cost_attr)

    return weight


def _routable_view(graph: nx.DiGraph) -> nx.DiGraph:
    # Match the SNN blocked-edge contract without mutating or copying graph data.
    return nx.subgraph_view(
        graph,
        filter_node=lambda node: not bool(graph.nodes[node].get("snn_neuron_closed", False)),
        filter_edge=lambda u, v: graph[u][v].get("state") != "blocked"
        and not bool(graph[u][v].get("snn_synapse_closed", False)),
    )


def _path_edges(path_nodes: list[int]) -> list[tuple[int, int]]:
    return [(int(u), int(v)) for u, v in zip(path_nodes, path_nodes[1:])]


def _path_attr_sum(graph: nx.DiGraph, path_nodes: list[int], attr: str) -> float:
    if len(path_nodes) < 2:
        return 0.0
    total = 0.0
    for u, v in _path_edges(path_nodes):
        if graph.has_edge(u, v):
            total += float(graph[u][v].get(attr, 0.0) or 0.0)
    return float(total)


def _path_cost(graph: nx.DiGraph, path_nodes: list[int], cost_attr: str) -> float:
    total = 0.0
    for u, v in _path_edges(path_nodes):
        if not graph.has_edge(u, v):
            raise ValueError(f"Path contains missing edge ({u}, {v})")
        total += _edge_weight(graph[u][v], cost_attr)
    return float(total)


def _dijkstra_path(graph: nx.DiGraph, start_node: int, goal_node: int, cost_attr: str) -> list[int]:
    view = _routable_view(graph)
    return [int(node) for node in nx.dijkstra_path(view, int(start_node), int(goal_node), weight=_weight_function(cost_attr))]


def _lat_lon(graph: nx.DiGraph, node: int) -> tuple[float, float] | None:
    attrs = graph.nodes.get(node, {})
    lat = _finite_float(attrs.get("lat", attrs.get("y")))
    lon = _finite_float(attrs.get("lon", attrs.get("x")))
    if lat is None or lon is None:
        return None
    return lat, lon


def _great_circle_distance_m(source: tuple[float, float], target: tuple[float, float]) -> float:
    lat1, lon1 = source
    lat2, lon2 = target
    radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    return float(2.0 * radius_m * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a))))


def _minimum_cost_per_meter(graph: nx.DiGraph, cost_attr: str) -> float | None:
    ratios: list[float] = []
    for _u, _v, attrs in graph.edges(data=True):
        if attrs.get("state") == "blocked":
            continue
        length = _positive_float(attrs.get("length"))
        if length is None:
            continue
        ratios.append(_edge_weight(attrs, cost_attr) / length)
    if not ratios:
        return None
    return min(ratios)


def _astar_heuristic(graph: nx.DiGraph, cost_attr: str) -> Callable[[int, int], float]:
    # OSM graphs have meter-scale edge lengths and lat/lon coordinates. For toy
    # graphs with arbitrary coordinates, fall back to zero to preserve optimality.
    if graph.graph.get("source") != "osmnx":
        return lambda _node, _goal: 0.0
    min_cost_per_meter = _minimum_cost_per_meter(graph, cost_attr)
    if min_cost_per_meter is None:
        return lambda _node, _goal: 0.0

    coordinate_cache: dict[int, tuple[float, float] | None] = {}

    def coordinate(node: int) -> tuple[float, float] | None:
        node = int(node)
        if node not in coordinate_cache:
            coordinate_cache[node] = _lat_lon(graph, node)
        return coordinate_cache[node]

    def heuristic(node: int, goal: int) -> float:
        node_coord = coordinate(node)
        goal_coord = coordinate(goal)
        if node_coord is None or goal_coord is None:
            return 0.0
        return _great_circle_distance_m(node_coord, goal_coord) * float(min_cost_per_meter)

    return heuristic


def _astar_path(graph: nx.DiGraph, start_node: int, goal_node: int, cost_attr: str) -> list[int]:
    view = _routable_view(graph)
    return [
        int(node)
        for node in nx.astar_path(
            view,
            int(start_node),
            int(goal_node),
            heuristic=_astar_heuristic(graph, cost_attr),
            weight=_weight_function(cost_attr),
        )
    ]


ALGORITHMS: dict[str, tuple[str, RouteFunction]] = {
    "dijkstra": ("Dijkstra", _dijkstra_path),
    "astar": ("A*", _astar_path),
}


def _run_single_benchmark(
    graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    *,
    cost_attr: str,
    algorithm: str,
    copy_graph: bool,
) -> AlgorithmBenchmarkResult:
    label, route_function = ALGORITHMS[algorithm]
    started = time.perf_counter()
    try:
        planning_graph = graph.copy() if copy_graph else graph
        path_nodes = route_function(planning_graph, int(start_node), int(goal_node), cost_attr)
        runtime_sec = time.perf_counter() - started
        return AlgorithmBenchmarkResult(
            algorithm=algorithm,
            label=label,
            success=True,
            runtime_sec=float(runtime_sec),
            path_nodes=path_nodes,
            path_edges=_path_edges(path_nodes),
            total_cost=_path_cost(planning_graph, path_nodes, cost_attr),
            path_length_m=_path_attr_sum(planning_graph, path_nodes, "length"),
            path_travel_time_s=_path_attr_sum(planning_graph, path_nodes, "travel_time"),
        )
    except Exception as exc:
        runtime_sec = time.perf_counter() - started
        return AlgorithmBenchmarkResult(
            algorithm=algorithm,
            label=label,
            success=False,
            runtime_sec=float(runtime_sec),
            error=str(exc),
        )


def run_algorithm_benchmarks(
    graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    *,
    cost_attr: str = "cost",
    algorithms: Sequence[str] = ("dijkstra", "astar"),
    copy_graph_per_algorithm: bool = True,
) -> dict[str, dict[str, object]]:
    """Run classical path algorithms without sharing route state between them."""
    results: dict[str, dict[str, object]] = {}
    for algorithm in algorithms:
        if algorithm not in ALGORITHMS:
            results[str(algorithm)] = AlgorithmBenchmarkResult(
                algorithm=str(algorithm),
                label=str(algorithm),
                success=False,
                runtime_sec=0.0,
                error=f"Unknown benchmark algorithm: {algorithm}",
            ).to_dict()
            continue
        # Each algorithm computes a fresh route from the same graph snapshot.
        # Shared helpers only summarize that algorithm's returned path.
        result = _run_single_benchmark(
            graph,
            int(start_node),
            int(goal_node),
            cost_attr=cost_attr,
            algorithm=str(algorithm),
            copy_graph=bool(copy_graph_per_algorithm),
        )
        results[str(algorithm)] = result.to_dict()
    return results
