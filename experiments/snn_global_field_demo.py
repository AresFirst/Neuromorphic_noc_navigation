"""Offline global-field demos for SNN route reuse on the Hangzhou graph.

The demos intentionally avoid Streamlit/Folium. They compare application-level
reuse patterns where a single SNN wavefront can serve many queries:

1. one source searching many candidate targets at the same time;
2. many users sharing one destination field.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable

import networkx as nx

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from maps import HANGZHOU_BBOX, load_hangzhou_graph, load_osm_graph, make_bidirectional_roads, osmnx_multidigraph_to_digraph
from navigation.benchmarks import run_algorithm_benchmarks
from snn import run_wavefront
from traffic import initialize_edge_state


OUTPUT_PATH = Path("docs/snn_global_field_demo_results.md")
RANDOM_SEED = 20260617
SAMPLE_COUNT = 1
SCALES = (1, 2, 5, 10, 20, 50, 100, 200)
MAX_QUERY_COUNT = max(SCALES)
MIN_DISTANCE_M = 3_000.0
MAX_SAMPLE_ATTEMPTS = 120
LEGACY_HANGZHOU_CACHE = "hangzhou_core_bidirectional_drive.graphml"


@dataclass(frozen=True)
class FieldRun:
    success: bool
    spike_times: dict[int, float]
    parent_trace: dict[int, int | None]
    wavefront_runtime_sec: float
    parent_trace_runtime_sec: float
    backend: str
    simulator_target: int
    active_neurons: int
    error: str | None = None


@dataclass(frozen=True)
class DemoRow:
    demo: str
    sample_id: str
    scale: int
    algorithm: str
    success_count: int
    query_count: int
    wavefront_count: int
    planning_calls: int
    total_runtime_sec: float
    wavefront_runtime_sec: float | None
    field_build_runtime_sec: float | None
    route_backtrace_runtime_sec: float | None
    avg_path_length_m: float | None
    avg_path_nodes: float | None
    selected_target: int | None
    backend: str
    error: str | None = None


def _finite_float(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _edge_weight(attrs: dict[str, object], attr: str) -> float:
    for key in (attr, "cost", "travel_time", "length"):
        parsed = _finite_float(attrs.get(key))
        if parsed is not None and parsed > 0.0:
            return parsed
    return 1.0


def _weight_function(attr: str):
    def weight(_u: int, _v: int, attrs: dict[str, object]) -> float:
        return _edge_weight(attrs, attr)

    return weight


def _path_length_m(graph: nx.DiGraph, path_nodes: list[int]) -> float:
    total = 0.0
    for u, v in zip(path_nodes, path_nodes[1:]):
        if graph.has_edge(int(u), int(v)):
            total += float(graph[int(u)][int(v)].get("length", 0.0) or 0.0)
    return float(total)


def _haversine_m(graph: nx.DiGraph, source: int, target: int) -> float:
    s_attrs = graph.nodes[int(source)]
    t_attrs = graph.nodes[int(target)]
    lat1 = math.radians(float(s_attrs["lat"]))
    lat2 = math.radians(float(t_attrs["lat"]))
    d_lat = lat2 - lat1
    d_lon = math.radians(float(t_attrs["lon"]) - float(s_attrs["lon"]))
    a = math.sin(d_lat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2.0) ** 2
    return float(2.0 * 6_371_000.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a))))


def _largest_component_nodes(graph: nx.DiGraph) -> list[int]:
    component = max(nx.weakly_connected_components(graph), key=len)
    return [int(node) for node in component]


def _load_hangzhou_experiment_graph() -> tuple[nx.MultiDiGraph, str]:
    try:
        return load_hangzhou_graph(network_type="drive"), "load_hangzhou_graph(network_type='drive')"
    except RuntimeError as exc:
        cached = load_osm_graph(
            bbox=HANGZHOU_BBOX,
            network_type="drive",
            cache_filename=LEGACY_HANGZHOU_CACHE,
            simplify=False,
        )
        return cached, f"legacy local cache {LEGACY_HANGZHOU_CACHE} after load_hangzhou_graph failed: {exc}"


def _reachable_candidates(
    graph: nx.DiGraph,
    source: int,
    candidates: Iterable[int],
    *,
    weight_attr: str = "delay_ms",
) -> list[tuple[int, float]]:
    lengths = nx.single_source_dijkstra_path_length(
        graph,
        int(source),
        weight=_weight_function(weight_attr),
    )
    rows: list[tuple[int, float]] = []
    for node in candidates:
        node = int(node)
        if node == int(source) or node not in lengths:
            continue
        if _haversine_m(graph, int(source), node) < MIN_DISTANCE_M:
            continue
        rows.append((node, float(lengths[node])))
    return rows


def _choose_ordered_nodes(
    graph: nx.DiGraph,
    anchor: int,
    nodes: list[int],
    rng: random.Random,
    *,
    reverse: bool = False,
) -> tuple[list[int], int]:
    """Return ``MAX_QUERY_COUNT`` reachable nodes and a farthest simulator target.

    The farthest node is used only to give the Brian2Loihi simulation enough
    time to cover the whole sampled query set. It is not used to choose SNN
    routes or targets.
    """
    shuffled = list(nodes)
    rng.shuffle(shuffled)
    planning_graph = graph.reverse(copy=False) if reverse else graph
    reachable = _reachable_candidates(planning_graph, int(anchor), shuffled)
    if len(reachable) < MAX_QUERY_COUNT:
        raise RuntimeError(f"Only found {len(reachable)} reachable nodes from anchor {anchor}")
    selected = reachable[:MAX_QUERY_COUNT]
    simulator_target, _delay = max(selected, key=lambda item: item[1])
    return [int(node) for node, _delay in selected], int(simulator_target)


def _run_loihi_field(
    graph: nx.DiGraph,
    source: int,
    simulator_target: int,
    *,
    delay_attr: str = "delay_ms",
) -> FieldRun:
    started = time.perf_counter()
    wavefront = run_wavefront(
        graph,
        int(source),
        int(simulator_target),
        delay_attr=delay_attr,
        use_loihi=True,
    )
    wavefront_runtime_sec = time.perf_counter() - started
    backend = str(wavefront.get("backend") or "")
    if not wavefront.get("success"):
        return FieldRun(
            success=False,
            spike_times={},
            parent_trace={},
            wavefront_runtime_sec=float(wavefront_runtime_sec),
            parent_trace_runtime_sec=0.0,
            backend=backend,
            simulator_target=int(simulator_target),
            active_neurons=0,
            error=str(wavefront.get("error") or "Brian2Loihi wavefront failed."),
        )
    if backend == "cpu_reference":
        return FieldRun(
            success=False,
            spike_times={},
            parent_trace={},
            wavefront_runtime_sec=float(wavefront_runtime_sec),
            parent_trace_runtime_sec=0.0,
            backend=backend,
            simulator_target=int(simulator_target),
            active_neurons=0,
            error="SNN field used CPU reference backend.",
        )
    spike_times = {
        int(node): float(time_ms)
        for node, time_ms in (wavefront.get("spike_times_by_neuron") or {}).items()
    }
    trace_started = time.perf_counter()
    parent_trace = infer_parent_trace_from_spikes(
        graph,
        spike_times,
        int(source),
        delay_attr=delay_attr,
    )
    parent_trace_runtime_sec = time.perf_counter() - trace_started
    return FieldRun(
        success=True,
        spike_times=spike_times,
        parent_trace=parent_trace,
        wavefront_runtime_sec=float(wavefront_runtime_sec),
        parent_trace_runtime_sec=float(parent_trace_runtime_sec),
        backend=backend,
        simulator_target=int(simulator_target),
        active_neurons=int(len(spike_times)),
        error=None,
    )


def _benchmark_prefix_routes(
    graph: nx.DiGraph,
    pairs: list[tuple[int, int]],
    algorithm: str,
    *,
    scales: tuple[int, ...] = SCALES,
) -> dict[int, tuple[int, float, list[float], list[int], str | None]]:
    cumulative_runtime = 0.0
    lengths: list[float] = []
    node_counts: list[int] = []
    success_count = 0
    error: str | None = None
    outputs: dict[int, tuple[int, float, list[float], list[int], str | None]] = {}
    scale_set = set(scales)
    for idx, (source, target) in enumerate(pairs, start=1):
        result = run_algorithm_benchmarks(
            graph,
            int(source),
            int(target),
            algorithms=(algorithm,),
            copy_graph_per_algorithm=False,
        )[algorithm]
        cumulative_runtime += float(result.get("runtime_sec") or 0.0)
        if result.get("success"):
            success_count += 1
            lengths.append(float(result.get("path_length_m") or 0.0))
            node_counts.append(len(result.get("path_nodes") or []))
        elif error is None:
            error = str(result.get("error") or "path planning failed")
        if idx in scale_set:
            outputs[idx] = (
                success_count,
                float(cumulative_runtime),
                list(lengths),
                list(node_counts),
                error,
            )
    return outputs


def _fmt_float(value: float | None, digits: int = 6) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    return f"{float(value):.{digits}f}"


def _fmt_length(value: float | None) -> str:
    if value is None or not math.isfinite(float(value)):
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


def _average(values: Iterable[float]) -> float | None:
    values = [float(value) for value in values if math.isfinite(float(value))]
    return mean(values) if values else None


def _row_average_path_length(lengths: list[float]) -> float | None:
    return mean(lengths) if lengths else None


def _row_average_path_nodes(node_counts: list[int]) -> float | None:
    return mean(node_counts) if node_counts else None


def _demo_multi_target(
    graph: nx.DiGraph,
    nodes: list[int],
    sample_id: str,
    rng: random.Random,
) -> list[DemoRow]:
    for attempt in range(MAX_SAMPLE_ATTEMPTS):
        source = int(rng.choice(nodes))
        try:
            targets, simulator_target = _choose_ordered_nodes(graph, source, nodes, rng)
            break
        except RuntimeError:
            if attempt == MAX_SAMPLE_ATTEMPTS - 1:
                raise
    print(f"[multi-target] {sample_id}: source={source}, max_targets={len(targets)}", flush=True)
    field = _run_loihi_field(graph, source, simulator_target)
    rows: list[DemoRow] = []
    if field.success:
        for scale in SCALES:
            prefix = targets[:scale]
            backtrace_started = time.perf_counter()
            selected_target: int | None = None
            success_count = 0
            lengths: list[float] = []
            node_counts: list[int] = []
            error: str | None = None
            reachable_targets = [target for target in prefix if target in field.spike_times]
            if reachable_targets:
                # Also record the earliest target to show the simultaneous-search
                # decision; route metrics below cover every target in the prefix.
                selected_target = min(reachable_targets, key=lambda node: field.spike_times[int(node)])
            for target in prefix:
                if target not in field.spike_times:
                    if error is None:
                        error = f"Target {target} did not spike in the SNN field."
                    continue
                try:
                    path_nodes = reconstruct_path_from_parent(field.parent_trace, source, int(target))
                    success_count += 1
                    lengths.append(_path_length_m(graph, path_nodes))
                    node_counts.append(len(path_nodes))
                except Exception as exc:
                    if error is None:
                        error = str(exc)
            backtrace_runtime = time.perf_counter() - backtrace_started
            rows.append(
                DemoRow(
                    demo="多目标同时搜索",
                    sample_id=sample_id,
                    scale=int(scale),
                    algorithm="SNN Brian2Loihi",
                    success_count=int(success_count),
                    query_count=int(scale),
                    wavefront_count=1,
                    planning_calls=1,
                    total_runtime_sec=float(field.wavefront_runtime_sec + field.parent_trace_runtime_sec + backtrace_runtime),
                    wavefront_runtime_sec=field.wavefront_runtime_sec,
                    field_build_runtime_sec=field.parent_trace_runtime_sec,
                    route_backtrace_runtime_sec=float(backtrace_runtime),
                    avg_path_length_m=_row_average_path_length(lengths),
                    avg_path_nodes=_row_average_path_nodes(node_counts),
                    selected_target=selected_target,
                    backend=field.backend,
                    error=error,
                )
            )
    else:
        for scale in SCALES:
            rows.append(
                DemoRow(
                    demo="多目标同时搜索",
                    sample_id=sample_id,
                    scale=int(scale),
                    algorithm="SNN Brian2Loihi",
                    success_count=0,
                    query_count=int(scale),
                    wavefront_count=1,
                    planning_calls=1,
                    total_runtime_sec=field.wavefront_runtime_sec,
                    wavefront_runtime_sec=field.wavefront_runtime_sec,
                    field_build_runtime_sec=0.0,
                    route_backtrace_runtime_sec=0.0,
                    avg_path_length_m=None,
                    avg_path_nodes=None,
                    selected_target=None,
                    backend=field.backend,
                    error=field.error,
                )
            )

    pairs = [(source, target) for target in targets]
    for algorithm, label in (("dijkstra", "Dijkstra"), ("astar", "A*")):
        benchmark_rows = _benchmark_prefix_routes(graph, pairs, algorithm)
        for scale in SCALES:
            success_count, runtime, lengths, node_counts, error = benchmark_rows[int(scale)]
            rows.append(
                DemoRow(
                    demo="多目标同时搜索",
                    sample_id=sample_id,
                    scale=int(scale),
                    algorithm=label,
                    success_count=int(success_count),
                    query_count=int(scale),
                    wavefront_count=0,
                    planning_calls=int(scale),
                    total_runtime_sec=float(runtime),
                    wavefront_runtime_sec=None,
                    field_build_runtime_sec=None,
                    route_backtrace_runtime_sec=None,
                    avg_path_length_m=_row_average_path_length(lengths),
                    avg_path_nodes=_row_average_path_nodes(node_counts),
                    selected_target=None,
                    backend=algorithm,
                    error=error,
                )
            )
    return rows


def _follow_next_hop_field(
    next_hop: dict[int, int | None],
    start: int,
    goal: int,
) -> list[int]:
    if start == goal:
        return [int(goal)]
    route = [int(start)]
    visited = {int(start)}
    current = int(start)
    while current != int(goal):
        successor = next_hop.get(current)
        if successor is None:
            raise ValueError(f"next-hop field has no successor for node {current}")
        successor = int(successor)
        if successor in visited:
            raise ValueError("cycle detected while following next-hop field")
        route.append(successor)
        visited.add(successor)
        current = successor
    return route


def _demo_shared_target(
    graph: nx.DiGraph,
    reverse_graph: nx.DiGraph,
    nodes: list[int],
    sample_id: str,
    rng: random.Random,
) -> list[DemoRow]:
    for attempt in range(MAX_SAMPLE_ATTEMPTS):
        destination = int(rng.choice(nodes))
        try:
            users, simulator_target = _choose_ordered_nodes(graph, destination, nodes, rng, reverse=True)
            break
        except RuntimeError:
            if attempt == MAX_SAMPLE_ATTEMPTS - 1:
                raise
    print(f"[shared-target] {sample_id}: destination={destination}, max_users={len(users)}", flush=True)
    field = _run_loihi_field(reverse_graph, destination, simulator_target)
    rows: list[DemoRow] = []
    if field.success:
        next_hop = {int(node): (None if parent is None else int(parent)) for node, parent in field.parent_trace.items()}
        for scale in SCALES:
            prefix = users[:scale]
            backtrace_started = time.perf_counter()
            success_count = 0
            lengths: list[float] = []
            node_counts: list[int] = []
            error: str | None = None
            for user in prefix:
                try:
                    route = _follow_next_hop_field(next_hop, int(user), destination)
                    success_count += 1
                    lengths.append(_path_length_m(graph, route))
                    node_counts.append(len(route))
                except Exception as exc:
                    if error is None:
                        error = str(exc)
            backtrace_runtime = time.perf_counter() - backtrace_started
            rows.append(
                DemoRow(
                    demo="多用户共享目标场",
                    sample_id=sample_id,
                    scale=int(scale),
                    algorithm="SNN Brian2Loihi",
                    success_count=int(success_count),
                    query_count=int(scale),
                    wavefront_count=1,
                    planning_calls=1,
                    total_runtime_sec=float(field.wavefront_runtime_sec + field.parent_trace_runtime_sec + backtrace_runtime),
                    wavefront_runtime_sec=field.wavefront_runtime_sec,
                    field_build_runtime_sec=field.parent_trace_runtime_sec,
                    route_backtrace_runtime_sec=float(backtrace_runtime),
                    avg_path_length_m=_row_average_path_length(lengths),
                    avg_path_nodes=_row_average_path_nodes(node_counts),
                    selected_target=destination,
                    backend=field.backend,
                    error=error,
                )
            )
    else:
        for scale in SCALES:
            rows.append(
                DemoRow(
                    demo="多用户共享目标场",
                    sample_id=sample_id,
                    scale=int(scale),
                    algorithm="SNN Brian2Loihi",
                    success_count=0,
                    query_count=int(scale),
                    wavefront_count=1,
                    planning_calls=1,
                    total_runtime_sec=field.wavefront_runtime_sec,
                    wavefront_runtime_sec=field.wavefront_runtime_sec,
                    field_build_runtime_sec=0.0,
                    route_backtrace_runtime_sec=0.0,
                    avg_path_length_m=None,
                    avg_path_nodes=None,
                    selected_target=destination,
                    backend=field.backend,
                    error=field.error,
                )
            )

    pairs = [(user, destination) for user in users]
    for algorithm, label in (("dijkstra", "Dijkstra"), ("astar", "A*")):
        benchmark_rows = _benchmark_prefix_routes(graph, pairs, algorithm)
        for scale in SCALES:
            success_count, runtime, lengths, node_counts, error = benchmark_rows[int(scale)]
            rows.append(
                DemoRow(
                    demo="多用户共享目标场",
                    sample_id=sample_id,
                    scale=int(scale),
                    algorithm=label,
                    success_count=int(success_count),
                    query_count=int(scale),
                    wavefront_count=0,
                    planning_calls=int(scale),
                    total_runtime_sec=float(runtime),
                    wavefront_runtime_sec=None,
                    field_build_runtime_sec=None,
                    route_backtrace_runtime_sec=None,
                    avg_path_length_m=_row_average_path_length(lengths),
                    avg_path_nodes=_row_average_path_nodes(node_counts),
                    selected_target=destination,
                    backend=algorithm,
                    error=error,
                )
            )
    return rows


def _summary_rows(rows: list[DemoRow], demo: str) -> list[list[object]]:
    output: list[list[object]] = []
    for scale in SCALES:
        for algorithm in ("SNN Brian2Loihi", "Dijkstra", "A*"):
            group = [row for row in rows if row.demo == demo and row.scale == scale and row.algorithm == algorithm]
            runtimes = [row.total_runtime_sec for row in group if row.success_count == row.query_count]
            output.append(
                [
                    scale,
                    algorithm,
                    f"{sum(1 for row in group if row.success_count == row.query_count)}/{len(group)}",
                    _fmt_float(_average(runtimes)),
                    _fmt_float(_average(row.wavefront_runtime_sec for row in group if row.wavefront_runtime_sec is not None)),
                    _fmt_float(_average(row.field_build_runtime_sec for row in group if row.field_build_runtime_sec is not None)),
                    _fmt_float(_average(row.route_backtrace_runtime_sec for row in group if row.route_backtrace_runtime_sec is not None)),
                    _fmt_length(_average(row.avg_path_length_m for row in group if row.avg_path_length_m is not None)),
                    _fmt_float(_average(row.avg_path_nodes for row in group if row.avg_path_nodes is not None), digits=1),
                    _fmt_float(_average(row.planning_calls for row in group), digits=1),
                    _fmt_float(_average(row.wavefront_count for row in group), digits=1),
                ]
            )
    return output


def _detail_rows(rows: list[DemoRow]) -> list[list[object]]:
    return [
        [
            row.demo,
            row.sample_id,
            row.scale,
            row.algorithm,
            f"{row.success_count}/{row.query_count}",
            row.wavefront_count,
            row.planning_calls,
            _fmt_float(row.total_runtime_sec),
            _fmt_float(row.wavefront_runtime_sec),
            _fmt_float(row.field_build_runtime_sec),
            _fmt_float(row.route_backtrace_runtime_sec),
            _fmt_length(row.avg_path_length_m),
            _fmt_float(row.avg_path_nodes, digits=1),
            "-" if row.selected_target is None else row.selected_target,
            row.backend,
            (row.error or "-").replace("|", "/")[:160],
        ]
        for row in rows
    ]


def _build_report(
    graph: nx.DiGraph,
    load_runtime_sec: float,
    rows: list[DemoRow],
    backend_info: dict[str, object],
    map_source: str,
) -> str:
    mt_200 = {row.algorithm: row.total_runtime_sec for row in rows if row.demo == "多目标同时搜索" and row.scale == 200}
    st_200 = {row.algorithm: row.total_runtime_sec for row in rows if row.demo == "多用户共享目标场" and row.scale == 200}
    conclusion = (
        "在无拥塞杭州主城图上，SNN 的优势不来自单次点到点规划，而来自一次 wavefront 的全局复用。"
        f"多目标同时搜索在 200 个候选目标下：SNN {_fmt_float(mt_200.get('SNN Brian2Loihi'))} 秒，"
        f"Dijkstra {_fmt_float(mt_200.get('Dijkstra'))} 秒，A* {_fmt_float(mt_200.get('A*'))} 秒。"
        f"多用户共享目标场在 200 个用户下：SNN {_fmt_float(st_200.get('SNN Brian2Loihi'))} 秒，"
        f"Dijkstra {_fmt_float(st_200.get('Dijkstra'))} 秒，A* {_fmt_float(st_200.get('A*'))} 秒。"
    )
    return "\n\n".join(
        [
            "# SNN 全局路径场复用 Demo 实验",
            "## 结论",
            conclusion,
            "## 实验设置",
            "\n".join(
                [
                    f"- 地图：杭州主城机动车双向道路图；节点数 {graph.number_of_nodes()}，边数 {graph.number_of_edges()}。",
                    f"- 地图来源：{map_source}。",
                    f"- 地图加载与转换耗时：{load_runtime_sec:.3f} 秒。",
                    f"- 随机种子：{RANDOM_SEED}；样本数：{SAMPLE_COUNT}；规模：{', '.join(str(item) for item in SCALES)}。",
                    "- 场景无拥塞：不关闭节点、不关闭突触、不修改交通状态。",
                    "- SNN：每个样本只运行一次 Brian2Loihi wavefront，然后用 spike time / parent trace / next-hop field 服务多个查询。",
                    "- Dijkstra/A*：每个目标或用户都独立运行一次完整路径规划；规模为 N 时，规划调用次数为 N。",
                    "- 为保证 Brian2Loihi 仿真时间覆盖所有 sampled queries，实验只在采样阶段选择一个最远 simulator target；路线选择和 next-hop field 不读取 Dijkstra/A* 的路径结果。",
                    f"- Brian2Loihi 检测：`available={backend_info.get('available')}`，`module={backend_info.get('brian2loihi_module')}`，`error={backend_info.get('error')}`。",
                    "- CPU fallback：脚本直接调用 `run_wavefront(... use_loihi=True)` 并拒绝 `cpu_reference` 后端。",
                ]
            ),
            "## Demo 1：多目标同时搜索平均值",
            _markdown_table(
                ["目标数", "算法", "成功样本", "平均总耗时(s)", "wavefront(s)", "field构建(s)", "路线回溯(s)", "平均路径长度(m)", "平均路径节点数", "平均规划调用", "平均wavefront调用"],
                _summary_rows(rows, "多目标同时搜索"),
            ),
            "## Demo 2：多用户共享目标场平均值",
            _markdown_table(
                ["用户数", "算法", "成功样本", "平均总耗时(s)", "wavefront(s)", "field构建(s)", "路线回溯(s)", "平均路径长度(m)", "平均路径节点数", "平均规划调用", "平均wavefront调用"],
                _summary_rows(rows, "多用户共享目标场"),
            ),
            "## 明细",
            _markdown_table(
                ["Demo", "样本", "规模", "算法", "成功数", "wavefront调用", "规划调用", "总耗时(s)", "wavefront(s)", "field构建(s)", "路线回溯(s)", "平均路径长度(m)", "平均路径节点数", "目标/终点", "后端", "错误"],
                _detail_rows(rows),
            ),
            "## 解释",
            "\n".join(
                [
                    "- 多目标同时搜索中，SNN 从一个起点发放一次 wavefront，并用同一份 parent trace 回溯所有候选目标的完整路线；如只需要最近目标，也可直接选择最早发放的候选目标。",
                    "- 多用户共享目标场中，SNN 在反向图上从共享终点发放一次 wavefront，parent trace 可直接解释为所有节点指向终点的 next-hop field；每个用户只需沿 next-hop field 回溯完整路线。",
                    "- 这两个 demo 展示的是应用级复用优势：查询数量增加时，经典算法调用次数线性增加，而 SNN 的核心 wavefront 调用次数保持为 1。",
                    "- Brian2Loihi 仍是软件仿真，绝对耗时不一定总是低于高度优化的经典图算法；因此应重点观察随目标数/用户数增长的趋势和调用次数差异。",
                ]
            ),
        ]
    )


def main() -> None:
    backend_info = check_brian2loihi_available()
    if not backend_info.get("available"):
        raise RuntimeError(f"Brian2Loihi unavailable: {backend_info.get('error')}")

    started = time.perf_counter()
    osm_graph, map_source = _load_hangzhou_experiment_graph()
    graph = initialize_edge_state(make_bidirectional_roads(osmnx_multidigraph_to_digraph(osm_graph)))
    load_runtime_sec = time.perf_counter() - started
    print(
        f"[map] nodes={graph.number_of_nodes()}, edges={graph.number_of_edges()}, "
        f"load_runtime={load_runtime_sec:.3f}s",
        flush=True,
    )
    nodes = _largest_component_nodes(graph)
    reverse_graph = graph.reverse(copy=True)
    rows: list[DemoRow] = []
    rng = random.Random(RANDOM_SEED)
    for sample_idx in range(1, SAMPLE_COUNT + 1):
        sample_id = f"S{sample_idx}"
        rows.extend(_demo_multi_target(graph, nodes, sample_id, rng))
        rows.extend(_demo_shared_target(graph, reverse_graph, nodes, sample_id, rng))
    report = _build_report(graph, load_runtime_sec, rows, backend_info, map_source)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(report + "\n", encoding="utf-8")
    print(f"[done] wrote {OUTPUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
