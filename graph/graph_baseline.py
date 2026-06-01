from __future__ import annotations

import heapq
import math
import random
from typing import Iterable

import networkx as nx
import pandas as pd


def _dijkstra(
    G: nx.DiGraph,
    start: int,
    target: int,
    weight: str,
) -> tuple[list[int], float]:
    if start not in G:
        raise nx.NodeNotFound(f"start node {start} not found")
    if target not in G:
        raise nx.NodeNotFound(f"target node {target} not found")

    queue: list[tuple[float, int]] = [(0.0, start)]
    distances: dict[int, float] = {start: 0.0}
    previous: dict[int, int] = {}
    visited: set[int] = set()

    while queue:
        current_cost, node = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        if node == target:
            break
        for neighbor, attrs in G[node].items():
            edge_cost = float(attrs.get(weight, 1.0))
            new_cost = current_cost + edge_cost
            if new_cost < distances.get(neighbor, math.inf):
                distances[neighbor] = new_cost
                previous[neighbor] = node
                heapq.heappush(queue, (new_cost, neighbor))

    if target not in distances:
        raise nx.NetworkXNoPath(f"No path from {start} to {target}")

    path = [target]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return path, float(distances[target])


def dijkstra_path(
    G,
    start: int,
    target: int,
    weight: str = "base_cost",
) -> tuple[list[int], float]:
    return _dijkstra(G, start, target, weight)


def dijkstra_delay_path(
    G,
    start: int,
    target: int,
    delay_attr: str = "delay_ms",
) -> tuple[list[int], float]:
    return _dijkstra(G, start, target, delay_attr)


def sample_start_target_pairs(
    G,
    num_pairs: int,
    seed: int = 0,
) -> list[tuple[int, int]]:
    nodes = list(G.nodes())
    if num_pairs <= 0 or len(nodes) < 2:
        return []

    rng = random.Random(seed)
    pairs: list[tuple[int, int]] = []
    while len(pairs) < num_pairs:
        start, target = rng.sample(nodes, 2)
        pairs.append((start, target))
    return pairs


def evaluate_dijkstra_pairs(
    G,
    pairs,
    weight: str = "base_cost",
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for start, target in pairs:
        try:
            path, path_cost = dijkstra_path(G, start, target, weight=weight)
            records.append(
                {
                    "start": start,
                    "target": target,
                    "path": path,
                    "path_cost": float(path_cost),
                    "num_hops": max(0, len(path) - 1),
                    "success": True,
                    "error": None,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            records.append(
                {
                    "start": start,
                    "target": target,
                    "path": None,
                    "path_cost": None,
                    "num_hops": None,
                    "success": False,
                    "error": str(exc),
                }
            )
    return pd.DataFrame.from_records(
        records,
        columns=["start", "target", "path", "path_cost", "num_hops", "success", "error"],
    )
