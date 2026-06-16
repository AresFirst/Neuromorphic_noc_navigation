"""Build NavigationResult objects from SNN wavefront output."""

from __future__ import annotations

import time
from typing import Any, Sequence

import networkx as nx

from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compute_path_cost
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from snn import run_wavefront

from .benchmarks import run_algorithm_benchmarks
from .result import NavigationResult, WavefrontFrame


def _path_attr_sum(graph: nx.DiGraph, path_nodes: list[int], attr: str) -> float:
    # 用于 GUI 展示路径总长度/总旅行时间；只读取图边属性，不参与路径选择。
    if len(path_nodes) < 2:
        return 0.0
    total = 0.0
    for u, v in zip(path_nodes, path_nodes[1:]):
        if graph.has_edge(u, v):
            total += float(graph[u][v].get(attr, 0.0) or 0.0)
    return float(total)


def _wavefront_frames(
    graph: nx.DiGraph,
    spike_times: dict[int, float],
    *,
    delay_attr: str,
) -> list[WavefrontFrame]:
    # 后端输出的是每个 neuron 的首次发放时间；GUI 需要按时间组织的 frame。
    if not spike_times:
        return []
    # 只在实际发生 spike 的时间点生成 frame，避免大地图上产生过多空帧。
    times = sorted({int(round(time_ms)) for time_ms in spike_times.values()})
    frames: list[WavefrontFrame] = []
    for t in times:
        active_nodes = sorted(int(node) for node, time_ms in spike_times.items() if float(time_ms) <= float(t))
        active_node_set = set(active_nodes)
        active_edges: list[tuple[int, int]] = []
        # 一条边只有在源节点已发放、目标节点已发放、且传播延迟已走完时才算 active。
        for u, v, attrs in graph.edges(data=True):
            if u not in active_node_set or v not in active_node_set:
                continue
            source_time = float(spike_times.get(u, 0.0))
            delay = float(attrs.get(delay_attr, 1.0))
            if source_time + delay <= float(t) + 1e-9:
                active_edges.append((int(u), int(v)))
        frames.append(WavefrontFrame(t=int(t), active_nodes=active_nodes, active_edges=active_edges))
    return frames


def run_navigation(
    graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    *,
    delay_attr: str = "delay_ms",
    cost_attr: str = "cost",
    use_loihi: bool = True,
    loihi_config: dict[str, Any] | None = None,
    allow_cpu_fallback: bool = True,
    benchmark_algorithms: Sequence[str] | None = ("dijkstra", "astar"),
    include_wavefront_frames: bool = True,
    include_spike_times_metadata: bool = True,
) -> NavigationResult:
    """Run the SNN pipeline and return a standard navigation result."""
    config = loihi_config or {}
    started = time.perf_counter()
    loihi_runtime_sec: float | None = None
    cpu_wavefront_runtime_sec: float | None = None
    wavefront_runtime_sec = 0.0
    parent_trace_runtime_sec = 0.0
    path_reconstruction_runtime_sec = 0.0
    final_wavefront_backend = None
    # 第一阶段：运行 Brian2Loihi 或 CPU 参考 wavefront，得到每个节点的首次 spike 时间。
    wavefront_started = time.perf_counter()
    wavefront = run_wavefront(
        graph,
        int(start_node),
        int(goal_node),
        delay_attr=delay_attr,
        use_loihi=use_loihi,
        threshold=float(config.get("threshold", 1.0)),
        weight=float(config.get("weight", 1.1)),
        refractory_ms=int(config.get("refractory_ms", 1000)),
        seed=int(config.get("seed", 0)),
    )
    first_wavefront_runtime_sec = time.perf_counter() - wavefront_started
    if use_loihi:
        loihi_runtime_sec = first_wavefront_runtime_sec
    else:
        cpu_wavefront_runtime_sec = first_wavefront_runtime_sec
    wavefront_runtime_sec = first_wavefront_runtime_sec
    final_wavefront_backend = wavefront.get("backend")
    loihi_error = None
    if use_loihi and not wavefront.get("success"):
        # 交互调试可以允许 CPU reference fallback；严格 SNN 对比场景会关闭该兜底。
        loihi_error = wavefront.get("error")
        if allow_cpu_fallback:
            wavefront_started = time.perf_counter()
            wavefront = run_wavefront(
                graph,
                int(start_node),
                int(goal_node),
                delay_attr=delay_attr,
                use_loihi=False,
                threshold=float(config.get("threshold", 1.0)),
                weight=float(config.get("weight", 1.1)),
                refractory_ms=int(config.get("refractory_ms", 1000)),
                seed=int(config.get("seed", 0)),
            )
            cpu_wavefront_runtime_sec = time.perf_counter() - wavefront_started
            wavefront_runtime_sec = cpu_wavefront_runtime_sec
            final_wavefront_backend = wavefront.get("backend")
    # 统一把后端返回的 key 转成 int，避免 GraphML 字符串节点和 JSON 显示造成混乱。
    spike_times = {
        int(node): float(time_ms)
        for node, time_ms in (wavefront.get("spike_times_by_neuron") or {}).items()
    }
    path_nodes: list[int] = []
    total_cost: float | None = None
    error = wavefront.get("error")
    if wavefront.get("success"):
        try:
            # 第二阶段：用 spike 时间和图拓扑推断每个节点的父节点。
            parent_trace_started = time.perf_counter()
            parent_trace = infer_parent_trace_from_spikes(
                graph,
                spike_times,
                int(start_node),
                delay_attr=delay_attr,
            )
            parent_trace_runtime_sec = time.perf_counter() - parent_trace_started
            # 第三阶段：从 goal 沿 parent_trace 回溯到 start，得到最终路径。
            path_reconstruction_started = time.perf_counter()
            path_nodes = reconstruct_path_from_parent(parent_trace, int(start_node), int(goal_node))
            total_cost = compute_path_cost(graph, path_nodes, weight=cost_attr)
            path_reconstruction_runtime_sec = time.perf_counter() - path_reconstruction_started
        except Exception as exc:
            error = str(exc)
            path_nodes = []

    elapsed = time.perf_counter() - started
    path_edges = [(int(u), int(v)) for u, v in zip(path_nodes, path_nodes[1:])]
    wavefront_time_max_ms = int(max((round(time_ms) for time_ms in spike_times.values()), default=0))
    algorithm_benchmarks = (
        run_algorithm_benchmarks(
            graph,
            int(start_node),
            int(goal_node),
            cost_attr=cost_attr,
            algorithms=benchmark_algorithms,
        )
        if benchmark_algorithms
        else {}
    )
    # 返回统一结果对象，GUI、测试和后续 API 都只依赖这个结构。
    return NavigationResult(
        start_node=int(start_node),
        goal_node=int(goal_node),
        path_nodes=[int(node) for node in path_nodes],
        path_edges=path_edges,
        wavefront_frames=_wavefront_frames(graph, spike_times, delay_attr=delay_attr)
        if include_wavefront_frames
        else [],
        total_cost=total_cost,
        metadata={
            "success": bool(path_nodes),
            "error": error,
            "backend": wavefront.get("backend"),
            "loihi_error": loihi_error,
            "snn_runtime_sec": float(elapsed),
            "snn_runtime_scope": "SNN wavefront + parent trace，不含地图加载、网页绘制和传统算法对比",
            "wavefront_runtime_sec": float(wavefront_runtime_sec),
            "brian2loihi_simulator_runtime_sec": loihi_runtime_sec,
            "cpu_wavefront_runtime_sec": cpu_wavefront_runtime_sec,
            "final_wavefront_backend": final_wavefront_backend,
            "stdp_parent_trace_runtime_sec": float(parent_trace_runtime_sec),
            "path_reconstruction_runtime_sec": float(path_reconstruction_runtime_sec),
            "stdp_path_backtrace_runtime_sec": float(parent_trace_runtime_sec + path_reconstruction_runtime_sec),
            "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
            "num_spikes": int(wavefront.get("num_spikes", 0) or 0),
            "active_neurons": int(wavefront.get("active_neurons", 0) or 0),
            "sim_time_ms": wavefront.get("sim_time_ms"),
            "spike_times_by_node": spike_times if include_spike_times_metadata else {},
            "wavefront_time_max_ms": wavefront_time_max_ms,
            "path_length_m": _path_attr_sum(graph, path_nodes, "length"),
            "path_travel_time_s": _path_attr_sum(graph, path_nodes, "travel_time"),
            "path_cost_attr": cost_attr,
            "algorithm_benchmarks": algorithm_benchmarks,
            "benchmark_cost_attr": cost_attr,
        },
    )
