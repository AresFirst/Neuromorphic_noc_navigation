"""Build NavigationResult objects from SNN wavefront output."""

from __future__ import annotations

import time
from typing import Any

import networkx as nx

from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compute_path_cost
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from snn import run_wavefront

from .result import NavigationResult, WavefrontFrame


def _path_attr_sum(graph: nx.DiGraph, path_nodes: list[int], attr: str) -> float:
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
    if not spike_times:
        return []
    times = sorted({int(round(time_ms)) for time_ms in spike_times.values()})
    frames: list[WavefrontFrame] = []
    for t in times:
        active_nodes = sorted(int(node) for node, time_ms in spike_times.items() if float(time_ms) <= float(t))
        active_node_set = set(active_nodes)
        active_edges: list[tuple[int, int]] = []
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
) -> NavigationResult:
    """Run the SNN pipeline and return a standard navigation result."""
    config = loihi_config or {}
    started = time.perf_counter()
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
    loihi_error = None
    if use_loihi and not wavefront.get("success"):
        loihi_error = wavefront.get("error")
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
    elapsed = time.perf_counter() - started

    spike_times = {
        int(node): float(time_ms)
        for node, time_ms in (wavefront.get("spike_times_by_neuron") or {}).items()
    }
    path_nodes: list[int] = []
    total_cost: float | None = None
    error = wavefront.get("error")
    if wavefront.get("success"):
        try:
            parent_trace = infer_parent_trace_from_spikes(
                graph,
                spike_times,
                int(start_node),
                delay_attr=delay_attr,
            )
            path_nodes = reconstruct_path_from_parent(parent_trace, int(start_node), int(goal_node))
            total_cost = compute_path_cost(graph, path_nodes, weight=cost_attr)
        except Exception as exc:
            error = str(exc)
            path_nodes = []

    path_edges = [(int(u), int(v)) for u, v in zip(path_nodes, path_nodes[1:])]
    return NavigationResult(
        start_node=int(start_node),
        goal_node=int(goal_node),
        path_nodes=[int(node) for node in path_nodes],
        path_edges=path_edges,
        wavefront_frames=_wavefront_frames(graph, spike_times, delay_attr=delay_attr),
        total_cost=total_cost,
        metadata={
            "success": bool(path_nodes),
            "error": error,
            "backend": wavefront.get("backend"),
            "loihi_error": loihi_error,
            "snn_runtime_sec": float(elapsed),
            "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
            "num_spikes": int(wavefront.get("num_spikes", 0) or 0),
            "active_neurons": int(wavefront.get("active_neurons", 0) or 0),
            "sim_time_ms": wavefront.get("sim_time_ms"),
            "path_length_m": _path_attr_sum(graph, path_nodes, "length"),
            "path_travel_time_s": _path_attr_sum(graph, path_nodes, "travel_time"),
            "path_cost_attr": cost_attr,
        },
    )
