from __future__ import annotations

import heapq
import math

import networkx as nx


def event_driven_wavefront(
    G: nx.DiGraph,
    start: int,
    target: int,
    delay_attr: str = "delay_ms",
    blocked_state: str = "blocked",
) -> dict:
    if start not in G:
        raise nx.NodeNotFound(f"start node {start} not found")
    if target not in G:
        raise nx.NodeNotFound(f"target node {target} not found")

    arrival_times: dict[int, float] = {start: 0.0}
    visited: set[int] = set()
    visited_order: list[int] = []
    queue: list[tuple[float, int]] = [(0.0, start)]

    while queue:
        current_time, node = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        visited_order.append(node)

        if node == target:
            break

        for neighbor, attrs in G[node].items():
            if attrs.get("state") == blocked_state:
                continue
            delay = int(attrs.get(delay_attr, 0))
            if delay <= 0:
                raise ValueError(f"Edge ({node}, {neighbor}) has invalid delay {delay}.")
            arrival = float(current_time) + float(delay)
            if arrival < arrival_times.get(neighbor, math.inf):
                arrival_times[neighbor] = arrival
                heapq.heappush(queue, (arrival, neighbor))

    return {
        "arrival_times": arrival_times,
        "target_arrival_time": arrival_times.get(target),
        "visited_order": visited_order,
    }
