from __future__ import annotations

import networkx as nx

from localization.dynamic_start import estimate_start_node_from_position

from .loihi_wavefront import run_loihi_wavefront
from .parent_trace import infer_parent_trace_from_spikes
from .path_compare import compute_path_cost
from .path_reconstruction import reconstruct_path_from_parent


def replan_from_position(
    G: nx.DiGraph,
    x: float,
    y: float,
    target: int,
    sigma: float = 0.1,
    loihi_config: dict | None = None,
) -> dict:
    config = loihi_config or {}
    try:
        estimated_start = estimate_start_node_from_position(G, x, y, sigma=sigma)
        wavefront = run_loihi_wavefront(
            G,
            estimated_start,
            target,
            delay_attr="delay_ms",
            threshold=float(config.get("threshold", 1.0)),
            weight=float(config.get("weight", 1.1)),
            refractory_ms=int(config.get("refractory_ms", 1000)),
            seed=int(config.get("seed", 0)),
        )
        if not wavefront.get("success"):
            return {
                "estimated_start": estimated_start,
                "target": target,
                "path": None,
                "path_cost": None,
                "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
                "num_spikes": int(wavefront.get("num_spikes", 0)),
                "success": False,
                "error": wavefront.get("error"),
            }

        parent_trace = infer_parent_trace_from_spikes(
            G,
            wavefront["spike_times_by_neuron"],
            estimated_start,
            delay_attr="delay_ms",
        )
        path = reconstruct_path_from_parent(parent_trace, estimated_start, target)
        path_cost = compute_path_cost(G, path, weight="delay_ms")
        return {
            "estimated_start": estimated_start,
            "target": target,
            "path": path,
            "path_cost": path_cost,
            "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
            "num_spikes": int(wavefront.get("num_spikes", 0)),
            "success": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "estimated_start": None,
            "target": target,
            "path": None,
            "path_cost": None,
            "target_arrival_time_ms": None,
            "num_spikes": 0,
            "success": False,
            "error": str(exc),
        }
