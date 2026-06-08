"""Thin wrapper around the Brian2Loihi wavefront planner."""

from __future__ import annotations

import networkx as nx

from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.wavefront_reference import event_driven_wavefront


def run_wavefront(
    graph: nx.DiGraph,
    start_node: int,
    goal_node: int,
    *,
    delay_attr: str = "delay_ms",
    use_loihi: bool = True,
    threshold: float = 1.0,
    weight: float = 1.1,
    refractory_ms: int = 1000,
    seed: int = 0,
) -> dict:
    """Run Brian2Loihi wavefront propagation or a CPU-compatible fallback."""
    if use_loihi:
        return run_loihi_wavefront(
            graph,
            int(start_node),
            int(goal_node),
            delay_attr=delay_attr,
            threshold=threshold,
            weight=weight,
            refractory_ms=refractory_ms,
            seed=seed,
        )

    reference = event_driven_wavefront(graph, int(start_node), int(goal_node), delay_attr=delay_attr)
    spike_times = {int(node): float(time) for node, time in reference["arrival_times"].items()}
    success = reference["target_arrival_time"] is not None
    return {
        "backend": "cpu_reference",
        "start": int(start_node),
        "target": int(goal_node),
        "spike_times_by_neuron": spike_times,
        "target_arrival_time_ms": reference["target_arrival_time"],
        "num_spikes": len(spike_times),
        "active_neurons": len(spike_times),
        "sim_time_ms": int(max(spike_times.values(), default=0.0)),
        "success": success,
        "error": None if success else f"Target neuron {goal_node} did not spike.",
    }
