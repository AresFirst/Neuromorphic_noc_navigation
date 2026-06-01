from __future__ import annotations

import math

import networkx as nx


def infer_parent_trace_from_spikes(
    G: nx.DiGraph,
    spike_times_by_neuron: dict[int, float],
    start: int,
    delay_attr: str = "delay_ms",
    tolerance_ms: float = 1.0,
) -> dict[int, int | None]:
    parent_trace: dict[int, int | None] = {node: None for node in G.nodes()}
    if start not in G:
        raise nx.NodeNotFound(f"start node {start} not found")

    for node in G.nodes():
        if node == start or node not in spike_times_by_neuron:
            continue

        post_spike_time = float(spike_times_by_neuron[node])
        candidates: list[tuple[float, int]] = []
        for predecessor in G.predecessors(node):
            if predecessor not in spike_times_by_neuron:
                continue
            attrs = G[predecessor][node]
            if attrs.get("state") == "blocked":
                continue
            delay = int(attrs.get(delay_attr, 0))
            if delay <= 0:
                continue
            predicted_time = float(spike_times_by_neuron[predecessor]) + float(delay)
            if abs(predicted_time - post_spike_time) <= tolerance_ms:
                candidates.append((predicted_time, predecessor))

        if candidates:
            predicted_time, chosen_parent = min(candidates, key=lambda item: (item[0], item[1]))
            parent_trace[node] = int(chosen_parent)

    parent_trace[start] = None
    return parent_trace
