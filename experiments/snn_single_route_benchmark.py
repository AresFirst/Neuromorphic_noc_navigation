"""Offline dynamic path-planning benchmark on the Hangzhou road graph.

The experiment is intentionally application-level: it checks whether SNN
wavefront planning has a runtime advantage over Dijkstra/A* when congestion is
discovered one event at a time during a trip.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import networkx as nx

from loihi_planner.backend_check import check_brian2loihi_available
from maps import load_hangzhou_graph, make_bidirectional_roads, osmnx_multidigraph_to_digraph
from navigation import (
    NavigationResult,
    run_incremental_snn_navigation,
    run_navigation,
    run_single_algorithm_benchmark,
)
from traffic import initialize_edge_state


OUTPUT_PATH = Path("docs/snn_single_path_planning_benchmark.md")
RANDOM_SEED = 20260615
OD_PAIR_COUNT = 5
CONGESTION_COUNTS = (1, 2, 4, 8, 16, 20, 50)
MAX_CONGESTION_NODES = max(CONGESTION_COUNTS)
MIN_OD_DISTANCE_M = 6_000.0
MIN_BASE_ROUTE_LENGTH_M = 7_000.0
MIN_BASE_ROUTE_NODES = 90
MAX_OD_SAMPLING_ATTEMPTS = 350


@dataclass(frozen=True)
class ODPair:
    pair_id: str
    start: int
    goal: int
    straight_distance_m: float
    base_path_nodes: list[int]
    base_path_length_m: float
    congestion_nodes: list[int]


@dataclass(frozen=True)
class PlanAttempt:
    algorithm: str
    label: str
    success: bool
    runtime_sec: float
    path_nodes: list[int]
    path_length_m: float | None
    backend: str
    cpu_fallback_sec: float | None
    error: str | None = None


@dataclass(frozen=True)
class AlgorithmRow:
    scenario: str
    pair_id: str
    congestion_nodes: int
    algorithm: str
    success: bool
    runtime_sec: float
    path_length_m: float | None
    path_nodes: int
    backend: str
    cpu_fallback_sec: float | None
    error: str | None = None
    initial_runtime_sec: float = 0.0
    replan_runtime_sec: float = 0.0
    replan_count: int = 0
    closed_node_count: int = 0
    event_nodes: tuple[int, ...] = ()


def _haversine_m(graph: nx.DiGraph, source: int, target: int) -> float:
    s_attrs = graph.nodes[int(source)]
    t_attrs = graph.nodes[int(target)]
    lat1 = math.radians(float(s_attrs["lat"]))
    lat2 = math.radians(float(t_attrs["lat"]))
    d_lat = lat2 - lat1
    d_lon = math.radians(float(t_attrs["lon"]) - float(s_attrs["lon"]))
    a = math.sin(d_lat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2.0) ** 2
    return float(2.0 * 6_371_000.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a))))


def _path_length_m(graph: nx.DiGraph, path_nodes: list[int]) -> float:
    total = 0.0
    for u, v in zip(path_nodes, path_nodes[1:]):
        if graph.has_edge(int(u), int(v)):
            total += float(graph[int(u)][int(v)].get("length", 0.0) or 0.0)
    return float(total)


def _closed_node_view(graph: nx.DiGraph, closed_nodes: set[int]) -> nx.DiGraph:
    closed = {int(node) for node in closed_nodes}
    return nx.subgraph_view(
        graph,
        filter_node=lambda node: int(node) not in closed
        and not bool(graph.nodes[node].get("snn_neuron_closed", False)),
        filter_edge=lambda u, v: graph[u][v].get("state") != "blocked"
        and not bool(graph[u][v].get("snn_synapse_closed", False)),
    )


def _path_exists_with_closed_nodes(
    graph: nx.DiGraph,
    start: int,
    goal: int,
    closed_nodes: set[int],
) -> bool:
    if int(start) in closed_nodes or int(goal) in closed_nodes:
        return False
    try:
        return nx.has_path(_closed_node_view(graph, closed_nodes), int(start), int(goal))
    except (nx.NetworkXError, nx.NodeNotFound):
        return False


def _select_congestion_nodes(
    graph: nx.DiGraph,
    start: int,
    goal: int,
    base_path_nodes: list[int],
    rng: random.Random,
) -> list[int]:
    internal = [int(node) for node in base_path_nodes[1:-1]]
    rng.shuffle(internal)
    selected: list[int] = []
    selected_set: set[int] = set()
    for node in internal:
        candidate_set = selected_set | {int(node)}
        if _path_exists_with_closed_nodes(graph, int(start), int(goal), candidate_set):
            selected.append(int(node))
            selected_set.add(int(node))
            if len(selected) >= MAX_CONGESTION_NODES:
                break
    return selected


def _choose_od_pairs(graph: nx.DiGraph) -> list[ODPair]:
    rng = random.Random(RANDOM_SEED)
    component = max(nx.weakly_connected_components(graph), key=len)
    nodes = [int(node) for node in component]
    pairs: list[ODPair] = []
    used: set[tuple[int, int]] = set()
    attempts = 0
    while len(pairs) < OD_PAIR_COUNT and attempts < MAX_OD_SAMPLING_ATTEMPTS:
        attempts += 1
        start, goal = rng.sample(nodes, 2)
        if (start, goal) in used:
            continue
        used.add((start, goal))
        straight_distance = _haversine_m(graph, start, goal)
        if straight_distance < MIN_OD_DISTANCE_M:
            continue
        base = run_single_algorithm_benchmark(
            graph,
            start,
            goal,
            algorithm="dijkstra",
            copy_graph=False,
        )
        if not base.success or len(base.path_nodes) < MIN_BASE_ROUTE_NODES:
            continue
        base_length = float(base.path_length_m)
        if base_length < MIN_BASE_ROUTE_LENGTH_M:
            continue
        congestion_nodes = _select_congestion_nodes(graph, start, goal, base.path_nodes, rng)
        if len(congestion_nodes) < MAX_CONGESTION_NODES:
            continue
        pair_id = f"OD{len(pairs) + 1}"
        pairs.append(
            ODPair(
                pair_id=pair_id,
                start=int(start),
                goal=int(goal),
                straight_distance_m=float(straight_distance),
                base_path_nodes=[int(node) for node in base.path_nodes],
                base_path_length_m=base_length,
                congestion_nodes=congestion_nodes,
            )
        )
        print(
            f"[od] {pair_id}: start={start}, goal={goal}, "
            f"base_length={base_length:.1f}m, nodes={len(base.path_nodes)}, "
            f"base_congestion_candidates={len(congestion_nodes)}",
            flush=True,
        )
    if len(pairs) < OD_PAIR_COUNT:
        raise RuntimeError(
            f"Only found {len(pairs)} valid OD pairs after {attempts} attempts; "
            "try relaxing MIN_BASE_ROUTE_NODES or MIN_OD_DISTANCE_M."
        )
    return pairs


def _close_congestion_node(graph: nx.DiGraph, node: int) -> None:
    node = int(node)
    if node not in graph:
        return
    graph.nodes[node]["snn_neuron_closed"] = True
    graph.nodes[node]["traffic_node_congestion"] = 1.0
    for predecessor in list(graph.predecessors(node)):
        if graph.has_edge(int(predecessor), node):
            attrs = graph[int(predecessor)][node]
            attrs["state"] = "blocked"
            attrs["snn_synapse_closed"] = True
    for successor in list(graph.successors(node)):
        if graph.has_edge(node, int(successor)):
            attrs = graph[node][int(successor)]
            attrs["state"] = "blocked"
            attrs["snn_synapse_closed"] = True


def _next_congestion_event(
    graph: nx.DiGraph,
    path_nodes: list[int],
    goal: int,
    closed_nodes: set[int],
    rng: random.Random,
) -> tuple[int, int, int] | None:
    """Pick one newly discovered congested node ahead on the current route.

    Returns ``(path_index, current_node, congested_node)``. The vehicle is at
    ``path_nodes[0]`` when the congestion is discovered, so replanning starts
    from the vehicle's current node instead of from the trip origin.
    """
    max_index = len(path_nodes) - 2
    if max_index < 1:
        return None
    near_limit = min(max_index, 3)
    near_indices = list(range(1, near_limit + 1))
    rng.shuffle(near_indices)
    remaining_indices = [index for index in range(1, max_index + 1) if index not in set(near_indices)]
    rng.shuffle(remaining_indices)
    for index in [*near_indices, *remaining_indices]:
        congested_node = int(path_nodes[index])
        current_node = int(path_nodes[0])
        if congested_node == int(goal) or congested_node in closed_nodes or current_node in closed_nodes:
            continue
        if _path_exists_with_closed_nodes(graph, current_node, int(goal), {congested_node}):
            return index, current_node, congested_node
    return None


def _algorithm_label(algorithm: str) -> str:
    if algorithm == "snn":
        return "SNN Brian2Loihi"
    if algorithm == "dijkstra":
        return "Dijkstra"
    if algorithm == "astar":
        return "A*"
    return str(algorithm)


def _snn_attempt_from_result(result: NavigationResult, *, algorithm: str = "snn") -> PlanAttempt:
    metadata = result.metadata
    success = bool(metadata.get("success")) and bool(result.path_nodes)
    cpu_fallback = metadata.get("cpu_wavefront_runtime_sec")
    return PlanAttempt(
        algorithm=algorithm,
        label=_algorithm_label(algorithm),
        success=success,
        runtime_sec=float(metadata.get("snn_runtime_sec", 0.0) or 0.0),
        path_nodes=[int(node) for node in result.path_nodes],
        path_length_m=float(metadata.get("path_length_m", 0.0) or 0.0) if success else None,
        backend=str(metadata.get("final_wavefront_backend") or metadata.get("backend") or ""),
        cpu_fallback_sec=float(cpu_fallback) if cpu_fallback is not None else None,
        error=str(metadata.get("error")) if metadata.get("error") else None,
    )


def _plan_once(
    graph: nx.DiGraph,
    start: int,
    goal: int,
    algorithm: str,
    *,
    initial_snn_plan: bool = False,
) -> PlanAttempt:
    if algorithm == "snn":
        if initial_snn_plan:
            result = run_navigation(
                graph,
                int(start),
                int(goal),
                use_loihi=True,
                allow_cpu_fallback=False,
                benchmark_algorithms=None,
                include_wavefront_frames=False,
                include_spike_times_metadata=False,
            )
        else:
            result = run_incremental_snn_navigation(
                graph,
                int(start),
                int(goal),
                use_loihi=True,
                allow_cpu_fallback=False,
                benchmark_algorithms=None,
                include_spike_times_metadata=False,
            )
        return _snn_attempt_from_result(result, algorithm=algorithm)

    result = run_single_algorithm_benchmark(
        graph,
        int(start),
        int(goal),
        algorithm=algorithm,
        copy_graph=False,
    )
    return PlanAttempt(
        algorithm=algorithm,
        label=result.label,
        success=bool(result.success),
        runtime_sec=float(result.runtime_sec),
        path_nodes=[int(node) for node in result.path_nodes],
        path_length_m=float(result.path_length_m) if result.success else None,
        backend=result.algorithm,
        cpu_fallback_sec=None,
        error=result.error,
    )


def _row_from_attempt(scenario: str, pair: ODPair, attempt: PlanAttempt) -> AlgorithmRow:
    return AlgorithmRow(
        scenario=scenario,
        pair_id=pair.pair_id,
        congestion_nodes=0,
        algorithm=attempt.label,
        success=attempt.success,
        runtime_sec=attempt.runtime_sec,
        path_length_m=attempt.path_length_m,
        path_nodes=len(attempt.path_nodes),
        backend=attempt.backend,
        cpu_fallback_sec=attempt.cpu_fallback_sec,
        error=attempt.error,
        initial_runtime_sec=attempt.runtime_sec,
    )


def _failure_dynamic_rows(
    pair: ODPair,
    algorithm: str,
    completed_events: int,
    target_counts: set[int],
    *,
    initial_runtime_sec: float,
    replan_runtime_sec: float,
    traveled_length_m: float,
    closed_nodes: list[int],
    backend: str,
    cpu_fallback_sec: float | None,
    error: str,
) -> list[AlgorithmRow]:
    rows: list[AlgorithmRow] = []
    for count in sorted(target_counts):
        rows.append(
            AlgorithmRow(
                scenario="动态拥塞累计重规划",
                pair_id=pair.pair_id,
                congestion_nodes=int(count),
                algorithm=_algorithm_label(algorithm),
                success=False,
                runtime_sec=float(initial_runtime_sec + replan_runtime_sec),
                path_length_m=traveled_length_m if traveled_length_m > 0.0 else None,
                path_nodes=0,
                backend=backend,
                cpu_fallback_sec=cpu_fallback_sec,
                error=error,
                initial_runtime_sec=float(initial_runtime_sec),
                replan_runtime_sec=float(replan_runtime_sec),
                replan_count=int(completed_events),
                closed_node_count=len(closed_nodes),
                event_nodes=tuple(closed_nodes),
            )
        )
    return rows


def _run_dynamic_algorithm(graph: nx.DiGraph, pair: ODPair, algorithm: str) -> list[AlgorithmRow]:
    scenario_graph = graph.copy()
    pair_index = int(pair.pair_id.removeprefix("OD") or "0")
    algorithm_index = {"snn": 1, "dijkstra": 2, "astar": 3}[algorithm]
    rng = random.Random(RANDOM_SEED + pair_index * 10_007 + algorithm_index * 1_009)

    print(f"[dynamic] {pair.pair_id} {_algorithm_label(algorithm)} initial", flush=True)
    initial = _plan_once(
        scenario_graph,
        pair.start,
        pair.goal,
        algorithm,
        initial_snn_plan=(algorithm == "snn"),
    )
    if not initial.success:
        return _failure_dynamic_rows(
            pair,
            algorithm,
            0,
            set(CONGESTION_COUNTS),
            initial_runtime_sec=initial.runtime_sec,
            replan_runtime_sec=0.0,
            traveled_length_m=0.0,
            closed_nodes=[],
            backend=initial.backend,
            cpu_fallback_sec=initial.cpu_fallback_sec,
            error=initial.error or "Initial route planning failed.",
        )

    rows: list[AlgorithmRow] = []
    recorded_counts: set[int] = set()
    closed_nodes: list[int] = []
    closed_node_set: set[int] = set()
    current_node = int(pair.start)
    path_nodes = initial.path_nodes
    traveled_length_m = 0.0
    replan_runtime_sec = 0.0
    cpu_fallback_total = initial.cpu_fallback_sec or 0.0
    saw_cpu_fallback = initial.cpu_fallback_sec is not None
    backend = initial.backend

    for event_number in range(1, MAX_CONGESTION_NODES + 1):
        event = _next_congestion_event(
            scenario_graph,
            path_nodes,
            pair.goal,
            closed_node_set,
            rng,
        )
        if event is None:
            remaining = set(CONGESTION_COUNTS) - recorded_counts
            rows.extend(
                _failure_dynamic_rows(
                    pair,
                    algorithm,
                    event_number - 1,
                    remaining,
                    initial_runtime_sec=initial.runtime_sec,
                    replan_runtime_sec=replan_runtime_sec,
                    traveled_length_m=traveled_length_m,
                    closed_nodes=closed_nodes,
                    backend=backend,
                    cpu_fallback_sec=cpu_fallback_total if saw_cpu_fallback else None,
                    error="No reachable congestion event remained on the current route.",
                )
            )
            break

        _path_index, event_current_node, congested_node = event
        _close_congestion_node(scenario_graph, congested_node)
        closed_nodes.append(int(congested_node))
        closed_node_set.add(int(congested_node))
        current_node = int(event_current_node)

        if event_number in CONGESTION_COUNTS or event_number % 10 == 0:
            print(
                f"[dynamic] {pair.pair_id} {_algorithm_label(algorithm)} "
                f"event={event_number}, current={current_node}, blocked={congested_node}",
                flush=True,
            )

        attempt = _plan_once(
            scenario_graph,
            current_node,
            pair.goal,
            algorithm,
            initial_snn_plan=False,
        )
        replan_runtime_sec += attempt.runtime_sec
        backend = attempt.backend or backend
        if attempt.cpu_fallback_sec is not None:
            saw_cpu_fallback = True
            cpu_fallback_total += attempt.cpu_fallback_sec
        if not attempt.success:
            remaining = set(CONGESTION_COUNTS) - recorded_counts
            rows.extend(
                _failure_dynamic_rows(
                    pair,
                    algorithm,
                    event_number,
                    remaining,
                    initial_runtime_sec=initial.runtime_sec,
                    replan_runtime_sec=replan_runtime_sec,
                    traveled_length_m=traveled_length_m,
                    closed_nodes=closed_nodes,
                    backend=backend,
                    cpu_fallback_sec=cpu_fallback_total if saw_cpu_fallback else None,
                    error=attempt.error or "Route replanning failed.",
                )
            )
            break

        if len(attempt.path_nodes) > 1:
            traveled_length_m += _path_length_m(scenario_graph, attempt.path_nodes[:2])
            current_node = int(attempt.path_nodes[1])
            path_nodes = [int(node) for node in attempt.path_nodes[1:]]
        else:
            current_node = int(attempt.path_nodes[0])
            path_nodes = attempt.path_nodes
        if event_number in CONGESTION_COUNTS:
            recorded_counts.add(event_number)
            route_total_length_m = traveled_length_m + _path_length_m(scenario_graph, path_nodes)
            rows.append(
                AlgorithmRow(
                    scenario="动态拥塞累计重规划",
                    pair_id=pair.pair_id,
                    congestion_nodes=int(event_number),
                    algorithm=attempt.label,
                    success=True,
                    runtime_sec=float(initial.runtime_sec + replan_runtime_sec),
                    path_length_m=float(route_total_length_m),
                    path_nodes=len(path_nodes),
                    backend=backend,
                    cpu_fallback_sec=cpu_fallback_total if saw_cpu_fallback else None,
                    error=None,
                    initial_runtime_sec=float(initial.runtime_sec),
                    replan_runtime_sec=float(replan_runtime_sec),
                    replan_count=int(event_number),
                    closed_node_count=len(closed_nodes),
                    event_nodes=tuple(closed_nodes),
                )
            )

    missing = set(CONGESTION_COUNTS) - recorded_counts - {row.congestion_nodes for row in rows}
    if missing:
        rows.extend(
            _failure_dynamic_rows(
                pair,
                algorithm,
                len(closed_nodes),
                missing,
                initial_runtime_sec=initial.runtime_sec,
                replan_runtime_sec=replan_runtime_sec,
                traveled_length_m=traveled_length_m,
                closed_nodes=closed_nodes,
                backend=backend,
                cpu_fallback_sec=cpu_fallback_total if saw_cpu_fallback else None,
                error="Dynamic route simulation stopped before all requested congestion counts.",
            )
        )
    return sorted(rows, key=lambda row: row.congestion_nodes)


def _run_no_congestion(graph: nx.DiGraph, pairs: list[ODPair]) -> list[AlgorithmRow]:
    rows: list[AlgorithmRow] = []
    for pair in pairs:
        for algorithm in ("snn", "dijkstra", "astar"):
            print(f"[no congestion] {pair.pair_id} {_algorithm_label(algorithm)}", flush=True)
            attempt = _plan_once(
                graph,
                pair.start,
                pair.goal,
                algorithm,
                initial_snn_plan=(algorithm == "snn"),
            )
            rows.append(_row_from_attempt("无拥塞", pair, attempt))
    return rows


def _run_dynamic_congestion(graph: nx.DiGraph, pairs: list[ODPair]) -> list[AlgorithmRow]:
    rows: list[AlgorithmRow] = []
    for pair in pairs:
        for algorithm in ("snn", "dijkstra", "astar"):
            rows.extend(_run_dynamic_algorithm(graph, pair, algorithm))
    return rows


def _fmt_float(value: float | None, digits: int = 6) -> str:
    if value is None:
        return "-"
    if not math.isfinite(float(value)):
        return "-"
    return f"{float(value):.{digits}f}"


def _fmt_length(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.1f}"


def _markdown_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _no_congestion_summary_rows(rows: list[AlgorithmRow]) -> list[list[object]]:
    output: list[list[object]] = []
    for algorithm in ("SNN Brian2Loihi", "Dijkstra", "A*"):
        group = [row for row in rows if row.algorithm == algorithm]
        successful = [row for row in group if row.success]
        output.append(
            [
                algorithm,
                f"{len(successful)}/{len(group)}",
                _fmt_float(mean(row.runtime_sec for row in successful) if successful else None),
                _fmt_length(mean(row.path_length_m for row in successful if row.path_length_m is not None) if successful else None),
                f"{mean(row.path_nodes for row in successful):.1f}" if successful else "-",
            ]
        )
    return output


def _dynamic_summary_rows(rows: list[AlgorithmRow]) -> list[list[object]]:
    output: list[list[object]] = []
    for count in CONGESTION_COUNTS:
        for algorithm in ("SNN Brian2Loihi", "Dijkstra", "A*"):
            group = [
                row
                for row in rows
                if row.congestion_nodes == count and row.algorithm == algorithm
            ]
            successful = [row for row in group if row.success]
            output.append(
                [
                    count,
                    algorithm,
                    f"{len(successful)}/{len(group)}",
                    _fmt_float(mean(row.runtime_sec for row in successful) if successful else None),
                    _fmt_float(mean(row.initial_runtime_sec for row in successful) if successful else None),
                    _fmt_float(mean(row.replan_runtime_sec for row in successful) if successful else None),
                    _fmt_length(mean(row.path_length_m for row in successful if row.path_length_m is not None) if successful else None),
                    f"{mean(row.replan_count for row in successful):.1f}" if successful else "-",
                ]
            )
    return output


def _detail_rows(rows: list[AlgorithmRow]) -> list[list[object]]:
    return [
        [
            row.scenario,
            row.pair_id,
            row.congestion_nodes,
            row.algorithm,
            "成功" if row.success else "失败",
            _fmt_float(row.runtime_sec),
            _fmt_float(row.initial_runtime_sec),
            _fmt_float(row.replan_runtime_sec),
            _fmt_length(row.path_length_m),
            row.path_nodes,
            row.replan_count,
            row.closed_node_count,
            row.backend,
            "-" if row.cpu_fallback_sec is None else _fmt_float(row.cpu_fallback_sec),
            ",".join(str(node) for node in row.event_nodes[:8]) if row.event_nodes else "-",
            (row.error or "-").replace("|", "/")[:160],
        ]
        for row in rows
    ]


def _build_report(
    graph: nx.DiGraph,
    load_runtime_sec: float,
    pairs: list[ODPair],
    no_congestion_rows: list[AlgorithmRow],
    dynamic_rows: list[AlgorithmRow],
    backend_info: dict[str, object],
) -> str:
    pair_rows = [
        [
            pair.pair_id,
            pair.start,
            pair.goal,
            _fmt_length(pair.straight_distance_m),
            _fmt_length(pair.base_path_length_m),
            len(pair.base_path_nodes),
            len(pair.congestion_nodes),
        ]
        for pair in pairs
    ]
    snn_no = [row.runtime_sec for row in no_congestion_rows if row.algorithm == "SNN Brian2Loihi" and row.success]
    dijkstra_no = [row.runtime_sec for row in no_congestion_rows if row.algorithm == "Dijkstra" and row.success]
    astar_no = [row.runtime_sec for row in no_congestion_rows if row.algorithm == "A*" and row.success]
    snn_dynamic_50 = [
        row.runtime_sec
        for row in dynamic_rows
        if row.algorithm == "SNN Brian2Loihi" and row.congestion_nodes == 50 and row.success
    ]
    dijkstra_dynamic_50 = [
        row.runtime_sec
        for row in dynamic_rows
        if row.algorithm == "Dijkstra" and row.congestion_nodes == 50 and row.success
    ]
    astar_dynamic_50 = [
        row.runtime_sec
        for row in dynamic_rows
        if row.algorithm == "A*" and row.congestion_nodes == 50 and row.success
    ]
    conclusion = (
        "无拥塞单次路径规划中，SNN Brian2Loihi 平均耗时"
        f" {_fmt_float(mean(snn_no) if snn_no else None)} 秒；"
        f"Dijkstra 为 {_fmt_float(mean(dijkstra_no) if dijkstra_no else None)} 秒，"
        f"A* 为 {_fmt_float(mean(astar_no) if astar_no else None)} 秒。"
        "动态拥塞实验按车辆行驶过程逐次触发拥塞，50 次拥塞事件累计总规划耗时中，"
        f"SNN 为 {_fmt_float(mean(snn_dynamic_50) if snn_dynamic_50 else None)} 秒，"
        f"Dijkstra 为 {_fmt_float(mean(dijkstra_dynamic_50) if dijkstra_dynamic_50 else None)} 秒，"
        f"A* 为 {_fmt_float(mean(astar_dynamic_50) if astar_dynamic_50 else None)} 秒。"
    )

    return "\n\n".join(
        [
            "# 杭州主城动态拥塞路径规划 SNN / Dijkstra / A* 离线实验",
            "## 结论",
            conclusion,
            "## 实验设置",
            "\n".join(
                [
                    f"- 地图：杭州主城固定 bbox，机动车道路，默认双向；节点数 {graph.number_of_nodes()}，边数 {graph.number_of_edges()}。",
                    f"- 地图加载与转换耗时：{load_runtime_sec:.3f} 秒。",
                    f"- OD 组数：{OD_PAIR_COUNT}，随机种子：{RANDOM_SEED}。",
                    f"- 记录的拥塞事件数：{', '.join(str(item) for item in CONGESTION_COUNTS)}。",
                    "- 无拥塞实验：每个算法只从起点到终点规划一次。",
                    "- 动态拥塞实验：先在无拥塞图上生成初始路线；随后车辆沿当前路线行驶，拥塞只在当前路线前方随机 1 到 3 跳附近暴露。系统关闭该前方拥塞节点及其入/出突触，再从车辆当前节点重规划；重规划成功后车辆只沿新路线前进一条边，再等待下一次拥塞事件。",
                    "- 动态拥塞表中的 N 个拥塞事件是同一趟车前 N 次事件的累计结果，不是在起点一次性关闭 N 个节点。",
                    "- SNN 动态重规划：`run_incremental_snn_navigation(... use_loihi=True, allow_cpu_fallback=False)`，复用已有图/SNN 映射状态，只改变拥塞节点和突触状态并从当前节点重新发 spike。",
                    "- Dijkstra/A* 动态重规划：每遇到一个新拥塞节点后，都从当前节点到终点完整重算一次路径；不读取 SNN spike、STDP trace 或 SNN 路线。",
                    "- 总规划耗时 = 初始规划耗时 + 每次拥塞暴露后的重规划耗时累计；路线总长度 = 已行驶路段长度 + 最后一次重规划后的剩余路线长度。",
                    f"- Brian2Loihi 检测：`available={backend_info.get('available')}`，`module={backend_info.get('brian2loihi_module')}`，`error={backend_info.get('error')}`。",
                    "- CPU fallback 校验：结果表中 `CPU fallback(s)` 应全部为 `-`；否则该 SNN 结果不满足本实验约束。",
                ]
            ),
            "## OD 列表",
            _markdown_table(
                ["OD", "start", "goal", "直线距离(m)", "无拥塞基线路线长度(m)", "基线路线节点数", "基线路线可用拥塞候选数"],
                pair_rows,
            ),
            "## 1. 无拥塞单次路径规划平均值",
            _markdown_table(
                ["算法", "成功数", "平均规划耗时(s)", "平均路线长度(m)", "平均路径节点数"],
                _no_congestion_summary_rows(no_congestion_rows),
            ),
            "## 1. 无拥塞单次路径规划明细",
            _markdown_table(
                ["场景", "OD", "拥塞事件数", "算法", "状态", "总规划耗时(s)", "初始规划(s)", "重规划累计(s)", "路线长度(m)", "剩余路径节点数", "重规划次数", "关闭节点数", "后端", "CPU fallback(s)", "拥塞节点样例", "错误"],
                _detail_rows(no_congestion_rows),
            ),
            "## 2. 动态拥塞累计重规划平均值",
            _markdown_table(
                ["拥塞事件数", "算法", "成功数", "平均总规划耗时(s)", "平均初始规划耗时(s)", "平均重规划累计耗时(s)", "平均路线总长度(m)", "平均实际重规划次数"],
                _dynamic_summary_rows(dynamic_rows),
            ),
            "## 2. 动态拥塞累计重规划明细",
            _markdown_table(
                ["场景", "OD", "拥塞事件数", "算法", "状态", "总规划耗时(s)", "初始规划(s)", "重规划累计(s)", "路线长度(m)", "剩余路径节点数", "重规划次数", "关闭节点数", "后端", "CPU fallback(s)", "拥塞节点样例", "错误"],
                _detail_rows(dynamic_rows),
            ),
            "## 解释",
            "\n".join(
                [
                    "- 这次动态实验修正了旧实验的一次性关闭节点逻辑；Dijkstra/A* 的拥塞耗时现在会随事件数量累积，因为每个事件都会触发一次完整重算。",
                    "- 单次或少量事件下，NetworkX 的 Dijkstra/A* 仍然很快；Brian2Loihi 软件仿真需要运行神经网络仿真，单次城市路径规划不是 SNN 的优势场景。",
                    "- 本报告中的 SNN 结果关闭了 CPU fallback；如果 Brian2Loihi 失败，实验会记录失败而不是改用 CPU wavefront。",
                ]
            ),
        ]
    )


def main() -> None:
    backend_info = check_brian2loihi_available()
    if not backend_info.get("available"):
        raise RuntimeError(f"Brian2Loihi unavailable: {backend_info.get('error')}")

    started = time.perf_counter()
    osm_graph = load_hangzhou_graph(network_type="drive")
    graph = initialize_edge_state(make_bidirectional_roads(osmnx_multidigraph_to_digraph(osm_graph)))
    load_runtime_sec = time.perf_counter() - started
    print(
        f"[map] nodes={graph.number_of_nodes()}, edges={graph.number_of_edges()}, "
        f"load_runtime={load_runtime_sec:.3f}s",
        flush=True,
    )

    pairs = _choose_od_pairs(graph)
    no_congestion_rows = _run_no_congestion(graph, pairs)
    dynamic_rows = _run_dynamic_congestion(graph, pairs)

    report = _build_report(
        graph,
        load_runtime_sec,
        pairs,
        no_congestion_rows,
        dynamic_rows,
        backend_info,
    )
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report + "\n", encoding="utf-8")
    print(f"[done] wrote {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
