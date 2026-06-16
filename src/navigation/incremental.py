"""Incremental SNN-style rerouting on an already built road/SNN graph."""

from __future__ import annotations

import time
from typing import Sequence

import networkx as nx

from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compute_path_cost
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from loihi_planner.wavefront_reference import event_driven_wavefront
from snn import run_wavefront

from .benchmarks import run_algorithm_benchmarks
from .result import NavigationResult


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


def run_incremental_snn_navigation(
    graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    *,
    delay_attr: str = "delay_ms",
    cost_attr: str = "cost",
    use_loihi: bool = False,
    loihi_config: dict[str, object] | None = None,
    allow_cpu_fallback: bool = True,
    benchmark_algorithms: Sequence[str] | None = ("dijkstra", "astar"),
    include_spike_times_metadata: bool = True,
) -> NavigationResult:
    """Send a new pulse from ``start_node`` without rebuilding the SNN graph.

    This is used after dynamic congestion closes already mapped neurons/synapses.
    The graph is treated as the existing SNN circuit: closed neurons are skipped
    through node attributes, and closed/blocked synapses are skipped through edge
    attributes.
    """
    started = time.perf_counter()
    error: str | None = None
    path_nodes: list[int] = []
    total_cost: float | None = None
    spike_times: dict[int, float] = {}
    target_arrival_time_ms: float | None = None
    wavefront_runtime_sec = 0.0
    parent_trace_runtime_sec = 0.0
    path_reconstruction_runtime_sec = 0.0
    loihi_runtime_sec: float | None = None
    cpu_wavefront_runtime_sec: float | None = None
    final_wavefront_backend = "cpu_reference_incremental"
    loihi_error: str | None = None
    config = loihi_config or {}
    try:
        wavefront_started = time.perf_counter()
        if use_loihi:
            wavefront = run_wavefront(
                graph,
                int(start_node),
                int(goal_node),
                delay_attr=delay_attr,
                use_loihi=True,
                threshold=float(config.get("threshold", 1.0)),
                weight=float(config.get("weight", 1.1)),
                refractory_ms=int(config.get("refractory_ms", 1000)),
                seed=int(config.get("seed", 0)),
            )
            loihi_runtime_sec = time.perf_counter() - wavefront_started
            wavefront_runtime_sec = loihi_runtime_sec
            final_wavefront_backend = str(wavefront.get("backend") or "brian2loihi")
            if not wavefront.get("success"):
                error = str(wavefront.get("error") or "Brian2Loihi wavefront failed.")
                loihi_error = error
                if not allow_cpu_fallback:
                    raise RuntimeError(error)
                wavefront_started = time.perf_counter()
                reference = event_driven_wavefront(
                    graph,
                    int(start_node),
                    int(goal_node),
                    delay_attr=delay_attr,
                )
                cpu_wavefront_runtime_sec = time.perf_counter() - wavefront_started
                wavefront_runtime_sec = cpu_wavefront_runtime_sec
                final_wavefront_backend = "cpu_reference_incremental"
                spike_times = {
                    int(node): float(time_ms) for node, time_ms in reference["arrival_times"].items()
                }
                target_arrival_time_ms = reference["target_arrival_time"]
            else:
                spike_times = {
                    int(node): float(time_ms)
                    for node, time_ms in (wavefront.get("spike_times_by_neuron") or {}).items()
                }
                target_arrival_time_ms = wavefront.get("target_arrival_time_ms")
        else:
            reference = event_driven_wavefront(
                graph,
                int(start_node),
                int(goal_node),
                delay_attr=delay_attr,
            )
            cpu_wavefront_runtime_sec = time.perf_counter() - wavefront_started
            wavefront_runtime_sec = cpu_wavefront_runtime_sec
            spike_times = {int(node): float(time_ms) for node, time_ms in reference["arrival_times"].items()}
            target_arrival_time_ms = reference["target_arrival_time"]
        if target_arrival_time_ms is None:
            error = f"Target neuron {goal_node} did not spike."
        else:
            parent_trace_started = time.perf_counter()
            parent_trace = infer_parent_trace_from_spikes(
                graph,
                spike_times,
                int(start_node),
                delay_attr=delay_attr,
            )
            parent_trace_runtime_sec = time.perf_counter() - parent_trace_started
            path_reconstruction_started = time.perf_counter()
            path_nodes = reconstruct_path_from_parent(parent_trace, int(start_node), int(goal_node))
            total_cost = compute_path_cost(graph, path_nodes, weight=cost_attr)
            path_reconstruction_runtime_sec = time.perf_counter() - path_reconstruction_started
    except Exception as exc:
        error = str(exc)
    elapsed = time.perf_counter() - started

    algorithm_benchmarks = (
        run_algorithm_benchmarks(
            graph,
            int(start_node),
            int(goal_node),
            cost_attr=cost_attr,
            algorithms=benchmark_algorithms,
            copy_graph_per_algorithm=False,
        )
        if benchmark_algorithms
        else {}
    )
    closed_nodes = [int(node) for node, attrs in graph.nodes(data=True) if attrs.get("snn_neuron_closed")]
    closed_edges = [
        (int(u), int(v))
        for u, v, attrs in graph.edges(data=True)
        if attrs.get("snn_synapse_closed") or attrs.get("state") == "blocked"
    ]
    return NavigationResult(
        start_node=int(start_node),
        goal_node=int(goal_node),
        path_nodes=[int(node) for node in path_nodes],
        path_edges=_path_edges(path_nodes),
        wavefront_frames=[],
        total_cost=total_cost,
        metadata={
            "success": bool(path_nodes),
            "error": error,
            "backend": "incremental_snn_cached_graph",
            "loihi_error": loihi_error,
            "incremental_snn": True,
            "snn_setup_reused": True,
            "pulse_start_node": int(start_node),
            "snn_runtime_sec": float(elapsed),
            "snn_runtime_scope": "已构建 SNN 图上的增量 pulse + parent trace，不含地图加载、网页绘制和传统算法完整重算",
            "wavefront_runtime_sec": float(wavefront_runtime_sec),
            "brian2loihi_simulator_runtime_sec": loihi_runtime_sec,
            "cpu_wavefront_runtime_sec": cpu_wavefront_runtime_sec,
            "final_wavefront_backend": final_wavefront_backend,
            "stdp_parent_trace_runtime_sec": float(parent_trace_runtime_sec),
            "path_reconstruction_runtime_sec": float(path_reconstruction_runtime_sec),
            "stdp_path_backtrace_runtime_sec": float(parent_trace_runtime_sec + path_reconstruction_runtime_sec),
            "target_arrival_time_ms": target_arrival_time_ms,
            "num_spikes": int(len(spike_times)),
            "active_neurons": int(len(spike_times)),
            "spike_times_by_node": spike_times if include_spike_times_metadata else {},
            "wavefront_time_max_ms": int(max((round(time_ms) for time_ms in spike_times.values()), default=0)),
            "path_length_m": _path_attr_sum(graph, path_nodes, "length"),
            "path_travel_time_s": _path_attr_sum(graph, path_nodes, "travel_time"),
            "path_cost_attr": cost_attr,
            "algorithm_benchmarks": algorithm_benchmarks,
            "benchmark_cost_attr": cost_attr,
            "closed_neuron_count": len(closed_nodes),
            "closed_synapse_count": len(closed_edges),
            "closed_neurons": closed_nodes[:30],
            "closed_synapses": [f"{u}->{v}" for u, v in closed_edges[:30]],
        },
    )
