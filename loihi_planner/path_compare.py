from __future__ import annotations

import math


def compute_path_cost(G, path: list[int], weight: str = "base_cost") -> float:
    if not path:
        return 0.0
    if len(path) == 1:
        return 0.0

    total = 0.0
    for source, target in zip(path, path[1:]):
        if not G.has_edge(source, target):
            raise ValueError(f"Path contains missing edge ({source}, {target})")
        total += float(G[source][target].get(weight, 0.0))
    return float(total)


def compare_snn_path_with_dijkstra(
    G,
    snn_path: list[int],
    dijkstra_path: list[int],
    weight: str = "base_cost",
) -> dict:
    snn_cost = compute_path_cost(G, snn_path, weight=weight)
    dijkstra_cost = compute_path_cost(G, dijkstra_path, weight=weight)
    same_path = list(snn_path) == list(dijkstra_path)
    same_cost = math.isclose(snn_cost, dijkstra_cost, rel_tol=1e-9, abs_tol=1e-9)
    optimality_ratio = None
    if dijkstra_cost == 0.0:
        optimality_ratio = 1.0 if same_cost else None
    else:
        optimality_ratio = float(snn_cost / dijkstra_cost)

    return {
        "snn_cost": float(snn_cost),
        "dijkstra_cost": float(dijkstra_cost),
        "optimality_ratio": optimality_ratio,
        "same_path": same_path,
        "same_cost": same_cost,
        "snn_num_hops": max(0, len(snn_path) - 1),
        "dijkstra_num_hops": max(0, len(dijkstra_path) - 1),
    }
