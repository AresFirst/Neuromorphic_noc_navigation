"""Serial full-trip comparison under one fixed congestion schedule."""

from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field
from typing import Callable

import networkx as nx

from navigation import (
    AlgorithmBenchmarkResult,
    NavigationResult,
    run_incremental_snn_navigation,
    run_navigation,
    run_single_algorithm_benchmark,
)

from .edge_state import clamp_delay_ms, initialize_edge_state


@dataclass(frozen=True, slots=True)
class CongestionScheduleItem:
    """One observable congestion event shared by all algorithms."""

    event_id: str
    distance_m: float
    detection_distance_m: float
    affected_edges: list[tuple[int, int]]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class SerialRouteRun:
    """One algorithm's complete trip through the shared congestion schedule."""

    algorithm: str
    label: str
    success: bool
    path_nodes: list[int] = field(default_factory=list)
    path_edges: list[tuple[int, int]] = field(default_factory=list)
    total_planning_runtime_sec: float = 0.0
    initial_planning_runtime_sec: float = 0.0
    reroute_planning_runtime_sec: float = 0.0
    planning_event_count: int = 0
    reroute_count: int = 0
    path_length_m: float = 0.0
    simulated_travel_time_s: float = 0.0
    average_speed_mps: float = 8.3333333333
    backend: str = ""
    error: str | None = None
    loihi_error: str | None = None
    brian2loihi_simulator_runtime_sec: float | None = None
    cpu_wavefront_runtime_sec: float | None = None
    stdp_parent_trace_runtime_sec: float = 0.0
    path_reconstruction_runtime_sec: float = 0.0
    stdp_path_backtrace_runtime_sec: float = 0.0
    final_wavefront_backend: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["path_node_count"] = len(self.path_nodes)
        payload["path_edge_count"] = len(self.path_edges)
        return payload


@dataclass(slots=True)
class SerialNavigationComparison:
    """Results for SNN, Dijkstra, and A* run one after another."""

    start_node: int
    goal_node: int
    congestion_schedule: list[CongestionScheduleItem]
    runs: dict[str, SerialRouteRun]
    runtime_sec: float

    def to_dict(self) -> dict[str, object]:
        return {
            "start_node": int(self.start_node),
            "goal_node": int(self.goal_node),
            "congestion_schedule": [item.to_dict() for item in self.congestion_schedule],
            "runs": {key: run.to_dict() for key, run in self.runs.items()},
            "runtime_sec": float(self.runtime_sec),
        }


ALGORITHM_ORDER: tuple[tuple[str, str], ...] = (
    ("snn", "SNN"),
    ("dijkstra", "Dijkstra"),
    ("astar", "A*"),
)


def _path_edges(path_nodes: list[int]) -> list[tuple[int, int]]:
    return [(int(u), int(v)) for u, v in zip(path_nodes, path_nodes[1:])]


def _edge_length(graph: nx.DiGraph, u: int, v: int) -> float:
    if not graph.has_edge(int(u), int(v)):
        return 1.0
    return max(1.0, float(graph[int(u)][int(v)].get("length", 1.0) or 1.0))


def _path_length(graph: nx.DiGraph, path_nodes: list[int]) -> float:
    return float(sum(_edge_length(graph, u, v) for u, v in _path_edges(path_nodes)))


def _merge_segment(full_path: list[int], segment: list[int]) -> list[int]:
    if not segment:
        return full_path
    if not full_path:
        return [int(node) for node in segment]
    if int(full_path[-1]) == int(segment[0]):
        full_path.extend(int(node) for node in segment[1:])
    else:
        full_path.extend(int(node) for node in segment)
    return full_path


def _route_prefix_at_distance(
    graph: nx.DiGraph,
    route: list[int],
    distance_m: float,
) -> tuple[list[int], float]:
    """Return a route prefix ending at a real graph node before ``distance_m``."""
    if len(route) < 2 or distance_m <= 0.0:
        return [int(route[0])] if route else [], 0.0
    travelled = 0.0
    prefix = [int(route[0])]
    for u, v in _path_edges(route):
        edge_length = _edge_length(graph, u, v)
        if travelled + edge_length > float(distance_m):
            break
        prefix.append(int(v))
        travelled += edge_length
    return prefix, float(travelled)


def _edges_near_route_distance(
    graph: nx.DiGraph,
    route: list[int],
    distance_m: float,
    edge_count: int,
    rng: random.Random,
) -> list[tuple[int, int]]:
    if len(route) < 2:
        return []
    route_edges = _path_edges(route)
    travelled = 0.0
    start_idx = 0
    for idx, (u, v) in enumerate(route_edges):
        travelled += _edge_length(graph, u, v)
        if travelled >= float(distance_m):
            start_idx = idx
            break
    window_start = max(0, start_idx - 2)
    window_end = min(len(route_edges), start_idx + max(2, int(edge_count)) + 3)
    goal = int(route[-1])
    candidates = [edge for edge in route_edges[window_start:window_end] if graph.has_edge(*edge) and int(edge[1]) != goal]
    if not candidates:
        return []
    rng.shuffle(candidates)
    return [(int(u), int(v)) for u, v in candidates[: max(1, int(edge_count))]]


def build_congestion_schedule(
    graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    *,
    cost_attr: str = "cost",
    congestion_count: int = 7,
    edge_count_per_event: int = 1,
    lookahead_m: float = 3_000.0,
    random_seed: int = 7,
) -> list[CongestionScheduleItem]:
    """Generate 5-10 deterministic random congestion events for one trip."""
    reference = run_single_algorithm_benchmark(
        initialize_edge_state(graph.copy()),
        int(start_node),
        int(goal_node),
        cost_attr=cost_attr,
        algorithm="dijkstra",
        copy_graph=False,
    )
    if not reference.success or len(reference.path_nodes) < 2:
        return []

    rng = random.Random(int(random_seed))
    count = min(10, max(5, int(congestion_count)))
    total_length = max(1.0, float(reference.path_length_m or _path_length(graph, reference.path_nodes)))
    interval = total_length / float(count + 1)
    schedule: list[CongestionScheduleItem] = []
    used_edges: set[tuple[int, int]] = set()
    for idx in range(count):
        base_distance = interval * float(idx + 1)
        jitter = rng.uniform(-0.25, 0.25) * interval
        distance = min(total_length * 0.95, max(total_length * 0.05, base_distance + jitter))
        edges = _edges_near_route_distance(
            graph,
            reference.path_nodes,
            distance,
            int(edge_count_per_event),
            rng,
        )
        edges = [edge for edge in edges if edge not in used_edges]
        if not edges:
            edges = _edges_near_route_distance(
                graph,
                reference.path_nodes,
                distance,
                int(edge_count_per_event),
                rng,
            )
        for edge in edges:
            used_edges.add(edge)
        if not edges:
            continue
        schedule.append(
            CongestionScheduleItem(
                event_id=f"congestion-{len(schedule) + 1}",
                distance_m=float(distance),
                detection_distance_m=float(max(0.0, distance - float(lookahead_m))),
                affected_edges=edges,
            )
        )
    schedule.sort(key=lambda item: item.detection_distance_m)
    return schedule


def _apply_congestion(graph: nx.DiGraph, item: CongestionScheduleItem) -> None:
    for u, v in item.affected_edges:
        if not graph.has_edge(int(u), int(v)):
            continue
        attrs = graph[int(u)][int(v)]
        free_flow_time = max(1.0, float(attrs.get("free_flow_time", attrs.get("travel_time", 1.0)) or 1.0))
        attrs["state"] = "blocked"
        attrs["snn_synapse_closed"] = True
        attrs["congestion_level"] = 1.0
        attrs["traffic_congestion"] = 1.0
        attrs["current_speed"] = 0.1
        attrs["travel_time"] = free_flow_time * 100.0
        attrs["cost"] = float(attrs["travel_time"])
        attrs["delay_ms"] = clamp_delay_ms(float(attrs["travel_time"]))
        if int(v) in graph:
            graph.nodes[int(v)]["traffic_node_congestion"] = 1.0


def _navigation_result_from_benchmark(benchmark: AlgorithmBenchmarkResult) -> NavigationResult:
    return NavigationResult(
        start_node=int(benchmark.path_nodes[0]) if benchmark.path_nodes else -1,
        goal_node=int(benchmark.path_nodes[-1]) if benchmark.path_nodes else -1,
        path_nodes=[int(node) for node in benchmark.path_nodes],
        path_edges=[(int(u), int(v)) for u, v in benchmark.path_edges],
        wavefront_frames=[],
        total_cost=benchmark.total_cost,
        metadata={
            "success": bool(benchmark.success),
            "error": benchmark.error,
            "backend": benchmark.algorithm,
            "algorithm": benchmark.algorithm,
            "label": benchmark.label,
            "snn_runtime_sec": 0.0,
            "algorithm_runtime_sec": float(benchmark.runtime_sec),
            "path_length_m": float(benchmark.path_length_m),
            "path_travel_time_s": float(benchmark.path_travel_time_s),
        },
    )


def _plan_classical(
    algorithm: str,
    cost_attr: str,
) -> Callable[[nx.DiGraph, int, int, bool], NavigationResult]:
    def planner(graph: nx.DiGraph, source: int, target: int, _is_initial: bool) -> NavigationResult:
        benchmark = run_single_algorithm_benchmark(
            graph,
            int(source),
            int(target),
            cost_attr=cost_attr,
            algorithm=algorithm,
            copy_graph=False,
        )
        return _navigation_result_from_benchmark(benchmark)

    return planner


def _plan_snn(
    graph: nx.DiGraph,
    source: int,
    target: int,
    is_initial: bool,
    *,
    cost_attr: str,
    loihi_config: dict[str, object] | None,
    allow_cpu_fallback: bool,
) -> NavigationResult:
    if is_initial:
        return run_navigation(
            graph,
            int(source),
            int(target),
            cost_attr=cost_attr,
            use_loihi=True,
            loihi_config=loihi_config,
            allow_cpu_fallback=allow_cpu_fallback,
            benchmark_algorithms=None,
            include_wavefront_frames=False,
            include_spike_times_metadata=False,
        )
    return run_incremental_snn_navigation(
        graph,
        int(source),
        int(target),
        cost_attr=cost_attr,
        use_loihi=True,
        loihi_config=loihi_config,
        allow_cpu_fallback=allow_cpu_fallback,
        benchmark_algorithms=None,
        include_spike_times_metadata=False,
    )


def _planning_runtime(result: NavigationResult, algorithm: str) -> float:
    if algorithm == "snn":
        return float(result.metadata.get("snn_runtime_sec", 0.0) or 0.0)
    return float(result.metadata.get("algorithm_runtime_sec", 0.0) or 0.0)


def _serial_run_from_result(
    graph: nx.DiGraph,
    result: NavigationResult,
    *,
    algorithm: str,
    label: str,
    average_speed_mps: float,
) -> SerialRouteRun:
    path_nodes = [int(node) for node in result.path_nodes]
    metadata = result.metadata
    path_length = float(metadata.get("path_length_m", _path_length(graph, path_nodes)) or 0.0)
    speed = max(0.1, float(average_speed_mps))
    return SerialRouteRun(
        algorithm=algorithm,
        label=label,
        success=bool(path_nodes) and bool(metadata.get("success", True)),
        path_nodes=path_nodes,
        path_edges=_path_edges(path_nodes),
        total_planning_runtime_sec=_planning_runtime(result, algorithm),
        initial_planning_runtime_sec=_planning_runtime(result, algorithm),
        planning_event_count=1,
        path_length_m=float(path_length),
        simulated_travel_time_s=float(path_length / speed),
        average_speed_mps=float(speed),
        backend=str(metadata.get("backend") or algorithm),
        error=str(metadata.get("error")) if metadata.get("error") else None,
        loihi_error=str(metadata.get("loihi_error")) if metadata.get("loihi_error") else None,
        brian2loihi_simulator_runtime_sec=metadata.get("brian2loihi_simulator_runtime_sec"),
        cpu_wavefront_runtime_sec=metadata.get("cpu_wavefront_runtime_sec"),
        stdp_parent_trace_runtime_sec=float(metadata.get("stdp_parent_trace_runtime_sec", 0.0) or 0.0),
        path_reconstruction_runtime_sec=float(metadata.get("path_reconstruction_runtime_sec", 0.0) or 0.0),
        stdp_path_backtrace_runtime_sec=float(metadata.get("stdp_path_backtrace_runtime_sec", 0.0) or 0.0),
        final_wavefront_backend=str(metadata.get("final_wavefront_backend"))
        if metadata.get("final_wavefront_backend")
        else None,
    )


def run_serial_planning_round(
    graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    *,
    cost_attr: str = "cost",
    snn_is_initial: bool = True,
    average_speed_mps: float = 8.3333333333,
    loihi_config: dict[str, object] | None = None,
    allow_snn_cpu_fallback: bool = False,
    on_algorithm_result: Callable[[SerialNavigationComparison], None] | None = None,
) -> SerialNavigationComparison:
    """Run SNN, Dijkstra, and A* once, serially, on the current graph state.

    This does not generate or apply congestion. The caller owns the current road
    state, so the function can be used both for initial no-congestion planning
    and for one reroute after a newly observed closure.
    """
    started = time.perf_counter()
    runs: dict[str, SerialRouteRun] = {}
    for algorithm, label in ALGORITHM_ORDER:
        algorithm_graph = initialize_edge_state(graph.copy())
        if algorithm == "snn":
            result = _plan_snn(
                algorithm_graph,
                int(start_node),
                int(goal_node),
                snn_is_initial,
                cost_attr=cost_attr,
                loihi_config=loihi_config,
                allow_cpu_fallback=allow_snn_cpu_fallback,
            )
        else:
            result = _plan_classical(algorithm, cost_attr)(
                algorithm_graph,
                int(start_node),
                int(goal_node),
                snn_is_initial,
            )
        runs[algorithm] = _serial_run_from_result(
            algorithm_graph,
            result,
            algorithm=algorithm,
            label=label,
            average_speed_mps=average_speed_mps,
        )
        if on_algorithm_result is not None:
            on_algorithm_result(
                SerialNavigationComparison(
                    start_node=int(start_node),
                    goal_node=int(goal_node),
                    congestion_schedule=[],
                    runs=dict(runs),
                    runtime_sec=float(time.perf_counter() - started),
                )
            )
    return SerialNavigationComparison(
        start_node=int(start_node),
        goal_node=int(goal_node),
        congestion_schedule=[],
        runs=runs,
        runtime_sec=float(time.perf_counter() - started),
    )


def _run_one_algorithm(
    base_graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    schedule: list[CongestionScheduleItem],
    *,
    algorithm: str,
    label: str,
    cost_attr: str,
    average_speed_mps: float,
    loihi_config: dict[str, object] | None,
    allow_cpu_fallback: bool,
) -> SerialRouteRun:
    graph = initialize_edge_state(base_graph.copy())
    full_path: list[int] = [int(start_node)]
    current_node = int(start_node)
    total_progress_m = 0.0
    total_runtime = 0.0
    initial_runtime = 0.0
    reroute_runtime = 0.0
    planning_event_count = 0
    reroute_count = 0
    backend = ""
    error: str | None = None
    loihi_error: str | None = None
    brian2loihi_runtime_total = 0.0
    brian2loihi_runtime_seen = False
    cpu_wavefront_runtime_total = 0.0
    cpu_wavefront_runtime_seen = False
    parent_trace_runtime_total = 0.0
    reconstruction_runtime_total = 0.0
    final_wavefront_backend: str | None = None

    def accumulate_snn_breakdown(result: NavigationResult) -> None:
        nonlocal loihi_error
        nonlocal brian2loihi_runtime_total, brian2loihi_runtime_seen
        nonlocal cpu_wavefront_runtime_total, cpu_wavefront_runtime_seen
        nonlocal parent_trace_runtime_total, reconstruction_runtime_total
        nonlocal final_wavefront_backend
        if algorithm != "snn":
            return
        metadata = result.metadata
        value = metadata.get("brian2loihi_simulator_runtime_sec")
        if value is not None:
            brian2loihi_runtime_total += float(value)
            brian2loihi_runtime_seen = True
        value = metadata.get("cpu_wavefront_runtime_sec")
        if value is not None:
            cpu_wavefront_runtime_total += float(value)
            cpu_wavefront_runtime_seen = True
        parent_trace_runtime_total += float(metadata.get("stdp_parent_trace_runtime_sec", 0.0) or 0.0)
        reconstruction_runtime_total += float(metadata.get("path_reconstruction_runtime_sec", 0.0) or 0.0)
        if metadata.get("loihi_error") and loihi_error is None:
            loihi_error = str(metadata.get("loihi_error"))
        if metadata.get("final_wavefront_backend"):
            final_wavefront_backend = str(metadata.get("final_wavefront_backend"))

    def plan(source: int, target: int, *, is_initial: bool) -> NavigationResult:
        if algorithm == "snn":
            return _plan_snn(
                graph,
                int(source),
                int(target),
                is_initial,
                cost_attr=cost_attr,
                loihi_config=loihi_config,
                allow_cpu_fallback=allow_cpu_fallback,
            )
        return _plan_classical(algorithm, cost_attr)(graph, int(source), int(target), is_initial)

    current_result = plan(current_node, int(goal_node), is_initial=True)
    planning_event_count += 1
    initial_runtime = _planning_runtime(current_result, algorithm)
    total_runtime += initial_runtime
    backend = str(current_result.metadata.get("backend") or algorithm)
    accumulate_snn_breakdown(current_result)
    if not current_result.path_nodes:
        return SerialRouteRun(
            algorithm=algorithm,
            label=label,
            success=False,
            path_nodes=full_path,
            path_edges=_path_edges(full_path),
            total_planning_runtime_sec=float(total_runtime),
            initial_planning_runtime_sec=float(initial_runtime),
            planning_event_count=planning_event_count,
            average_speed_mps=float(average_speed_mps),
            backend=backend,
            error=str(current_result.metadata.get("error") or "initial route failed"),
            loihi_error=loihi_error,
            brian2loihi_simulator_runtime_sec=brian2loihi_runtime_total
            if brian2loihi_runtime_seen
            else None,
            cpu_wavefront_runtime_sec=cpu_wavefront_runtime_total if cpu_wavefront_runtime_seen else None,
            stdp_parent_trace_runtime_sec=float(parent_trace_runtime_total),
            path_reconstruction_runtime_sec=float(reconstruction_runtime_total),
            stdp_path_backtrace_runtime_sec=float(parent_trace_runtime_total + reconstruction_runtime_total),
            final_wavefront_backend=final_wavefront_backend,
        )

    active_route = [int(node) for node in current_result.path_nodes]
    for item in schedule:
        detection_distance = max(total_progress_m, float(item.detection_distance_m))
        prefix, progressed = _route_prefix_at_distance(graph, active_route, detection_distance - total_progress_m)
        if prefix:
            _merge_segment(full_path, prefix)
            current_node = int(prefix[-1])
            total_progress_m += float(progressed)
        _apply_congestion(graph, item)
        replanned = plan(current_node, int(goal_node), is_initial=False)
        planning_event_count += 1
        runtime = _planning_runtime(replanned, algorithm)
        total_runtime += runtime
        reroute_runtime += runtime
        accumulate_snn_breakdown(replanned)
        if replanned.path_nodes:
            active_route = [int(node) for node in replanned.path_nodes]
            reroute_count += 1
            backend = str(replanned.metadata.get("backend") or backend or algorithm)
        else:
            error = str(replanned.metadata.get("error") or "reroute failed")
            break

    if error is None and active_route:
        _merge_segment(full_path, active_route)
    full_path = [int(node) for node in full_path]
    path_length = _path_length(graph, full_path)
    speed = max(0.1, float(average_speed_mps))
    return SerialRouteRun(
        algorithm=algorithm,
        label=label,
        success=error is None and len(full_path) >= 2 and int(full_path[-1]) == int(goal_node),
        path_nodes=full_path,
        path_edges=_path_edges(full_path),
        total_planning_runtime_sec=float(total_runtime),
        initial_planning_runtime_sec=float(initial_runtime),
        reroute_planning_runtime_sec=float(reroute_runtime),
        planning_event_count=planning_event_count,
        reroute_count=reroute_count,
        path_length_m=float(path_length),
        simulated_travel_time_s=float(path_length / speed),
        average_speed_mps=float(speed),
        backend=backend,
        error=error,
        loihi_error=loihi_error,
        brian2loihi_simulator_runtime_sec=brian2loihi_runtime_total if brian2loihi_runtime_seen else None,
        cpu_wavefront_runtime_sec=cpu_wavefront_runtime_total if cpu_wavefront_runtime_seen else None,
        stdp_parent_trace_runtime_sec=float(parent_trace_runtime_total),
        path_reconstruction_runtime_sec=float(reconstruction_runtime_total),
        stdp_path_backtrace_runtime_sec=float(parent_trace_runtime_total + reconstruction_runtime_total),
        final_wavefront_backend=final_wavefront_backend,
    )


def run_serial_navigation_comparison(
    graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    *,
    cost_attr: str = "cost",
    congestion_count: int = 7,
    edge_count_per_event: int = 1,
    lookahead_m: float = 3_000.0,
    average_speed_mps: float = 8.3333333333,
    random_seed: int = 7,
    loihi_config: dict[str, object] | None = None,
    allow_snn_cpu_fallback: bool = False,
) -> SerialNavigationComparison:
    """Run SNN, Dijkstra, and A* serially with one unchanged traffic schedule."""
    started = time.perf_counter()
    initialized = initialize_edge_state(graph.copy())
    schedule = build_congestion_schedule(
        initialized,
        int(start_node),
        int(goal_node),
        cost_attr=cost_attr,
        congestion_count=congestion_count,
        edge_count_per_event=edge_count_per_event,
        lookahead_m=lookahead_m,
        random_seed=random_seed,
    )
    runs: dict[str, SerialRouteRun] = {}
    for algorithm, label in ALGORITHM_ORDER:
        runs[algorithm] = _run_one_algorithm(
            initialized,
            int(start_node),
            int(goal_node),
            schedule,
            algorithm=algorithm,
            label=label,
            cost_attr=cost_attr,
            average_speed_mps=average_speed_mps,
            loihi_config=loihi_config,
            allow_cpu_fallback=bool(allow_snn_cpu_fallback),
        )
    return SerialNavigationComparison(
        start_node=int(start_node),
        goal_node=int(goal_node),
        congestion_schedule=schedule,
        runs=runs,
        runtime_sec=float(time.perf_counter() - started),
    )
