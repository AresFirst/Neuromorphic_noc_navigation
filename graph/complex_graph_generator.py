from __future__ import annotations

import math
import random
from collections import Counter
from typing import Iterable

import networkx as nx


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _add_bidirectional_edge(G: nx.DiGraph, u: int, v: int) -> None:
    if u == v:
        return
    G.add_edge(u, v)
    G.add_edge(v, u)


def _add_backbone_cycle(G: nx.DiGraph, num_nodes: int, bidirectional: bool = True) -> None:
    if num_nodes < 2:
        return
    for node in range(num_nodes):
        nxt = (node + 1) % num_nodes
        G.add_edge(node, nxt)
        if bidirectional:
            G.add_edge(nxt, node)


def _quadrant_region(x: float, y: float) -> int:
    return int(x >= 0.5) + 2 * int(y >= 0.5)


def _balanced_partitions(num_nodes: int, num_groups: int) -> list[list[int]]:
    num_groups = max(1, min(num_groups, num_nodes))
    base = num_nodes // num_groups
    remainder = num_nodes % num_groups
    partitions: list[list[int]] = []
    cursor = 0
    for group in range(num_groups):
        size = base + (1 if group < remainder else 0)
        partitions.append(list(range(cursor, cursor + size)))
        cursor += size
    return partitions


def _weighted_sample_without_replacement(
    rng: random.Random,
    candidates: list[int],
    weights: list[float],
    k: int,
) -> list[int]:
    pool = list(zip(candidates, weights))
    selected: list[int] = []
    k = min(k, len(pool))
    for _ in range(k):
        total = sum(weight for _, weight in pool)
        if total <= 0:
            choice = rng.choice(pool)[0]
        else:
            target = rng.random() * total
            cumulative = 0.0
            choice = pool[-1][0]
            for idx, (candidate, weight) in enumerate(pool):
                cumulative += weight
                if target <= cumulative:
                    choice = candidate
                    pool.pop(idx)
                    break
            else:
                pool.pop()
        if choice not in selected:
            selected.append(choice)
    return selected


def assign_edge_attributes(
    G: nx.DiGraph,
    min_delay_ms: int = 1,
    max_delay_ms: int = 10,
    seed: int = 0,
) -> nx.DiGraph:
    if min_delay_ms < 1:
        raise ValueError("min_delay_ms must be positive")
    if max_delay_ms < min_delay_ms:
        raise ValueError("max_delay_ms must be >= min_delay_ms")

    rng = random.Random(seed)
    edge_rows: list[tuple[int, int, float, float]] = []
    for u, v in G.edges():
        x1 = float(G.nodes[u]["x"])
        y1 = float(G.nodes[u]["y"])
        x2 = float(G.nodes[v]["x"])
        y2 = float(G.nodes[v]["y"])
        distance = math.hypot(x2 - x1, y2 - y1)
        random_factor = rng.uniform(0.8, 1.2)
        base_cost = distance * random_factor
        edge_rows.append((u, v, distance, base_cost))

    if not edge_rows:
        return G

    base_costs = [row[3] for row in edge_rows]
    min_base = min(base_costs)
    max_base = max(base_costs)

    for u, v, distance, base_cost in edge_rows:
        if math.isclose(min_base, max_base):
            delay_ms = int(round((min_delay_ms + max_delay_ms) / 2))
        else:
            normalized = (base_cost - min_base) / (max_base - min_base)
            mapped = min_delay_ms + normalized * (max_delay_ms - min_delay_ms)
            delay_ms = int(round(mapped))
        delay_ms = max(min_delay_ms, min(max_delay_ms, delay_ms))
        G[u][v].update(
            {
                "distance": float(distance),
                "base_cost": float(base_cost),
                "delay_ms": int(delay_ms),
                "original_delay_ms": int(delay_ms),
                "state": "normal",
            }
        )
    return G


def generate_complex_graph(
    graph_type: str,
    num_nodes: int,
    seed: int = 0,
    directed: bool = True,
    ensure_strongly_connected: bool = True,
    **kwargs,
) -> nx.DiGraph:
    if num_nodes < 0:
        raise ValueError("num_nodes must be non-negative")

    graph_type = graph_type.lower().strip()
    rng = random.Random(seed)
    G = nx.DiGraph()

    if num_nodes == 0:
        G.graph.update(
            {
                "graph_type": graph_type,
                "seed": seed,
                "directed": True,
                "ensure_strongly_connected": ensure_strongly_connected,
            }
        )
        return G

    coordinates: dict[int, tuple[float, float]] = {}
    regions: dict[int, int] = {}

    if graph_type == "random_geometric":
        for node in range(num_nodes):
            x = rng.random()
            y = rng.random()
            coordinates[node] = (x, y)
            regions[node] = _quadrant_region(x, y)
        radius = float(kwargs.get("radius", 0.25))
        edge_prob = float(kwargs.get("edge_prob", 0.55))
        if ensure_strongly_connected:
            _add_backbone_cycle(G, num_nodes, bidirectional=True)
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                x1, y1 = coordinates[i]
                x2, y2 = coordinates[j]
                distance = math.hypot(x2 - x1, y2 - y1)
                if distance <= radius and rng.random() <= edge_prob:
                    _add_bidirectional_edge(G, i, j)

    elif graph_type == "small_world":
        for node in range(num_nodes):
            angle = 2.0 * math.pi * node / max(1, num_nodes)
            jitter_x = rng.uniform(-0.03, 0.03)
            jitter_y = rng.uniform(-0.03, 0.03)
            x = _clip01(0.5 + 0.35 * math.cos(angle) + jitter_x)
            y = _clip01(0.5 + 0.35 * math.sin(angle) + jitter_y)
            coordinates[node] = (x, y)
            regions[node] = int((node * max(1, int(kwargs.get("region_bins", 4)))) / num_nodes)
        k = max(1, int(kwargs.get("k", 2)))
        rewire_prob = float(kwargs.get("rewire_prob", 0.12))
        if ensure_strongly_connected:
            _add_backbone_cycle(G, num_nodes, bidirectional=True)
        for node in range(num_nodes):
            for step in range(2, k + 1):
                target = (node + step) % num_nodes
                if rng.random() < rewire_prob:
                    target = rng.randrange(num_nodes)
                if target != node:
                    _add_bidirectional_edge(G, node, target)

    elif graph_type == "scale_free":
        for node in range(num_nodes):
            x = _clip01(rng.random() * 0.9 + 0.05)
            y = _clip01(rng.random() * 0.9 + 0.05)
            coordinates[node] = (x, y)
            regions[node] = int((node * max(1, int(kwargs.get("region_bins", 4)))) / num_nodes)
        m0 = max(2, int(kwargs.get("m0", min(4, num_nodes))))
        m = max(1, int(kwargs.get("m", 2)))
        if ensure_strongly_connected:
            _add_backbone_cycle(G, num_nodes, bidirectional=True)
        if num_nodes <= 1:
            pass
        else:
            initial_nodes = list(range(min(m0, num_nodes)))
            for i in initial_nodes:
                for j in initial_nodes:
                    if i != j and rng.random() < 0.5:
                        _add_bidirectional_edge(G, i, j)
            for node in range(min(m0, num_nodes), num_nodes):
                existing = list(range(node))
                weights = [G.degree(candidate) + 1 for candidate in existing]
                targets = _weighted_sample_without_replacement(rng, existing, weights, m)
                for target in targets:
                    if target != node:
                        G.add_edge(node, target)
                        if rng.random() < 0.35:
                            G.add_edge(target, node)

    elif graph_type == "community":
        num_communities = max(1, int(kwargs.get("num_communities", min(4, num_nodes))))
        partitions = _balanced_partitions(num_nodes, num_communities)
        centers: list[tuple[float, float]] = []
        for community in range(len(partitions)):
            angle = 2.0 * math.pi * community / max(1, len(partitions))
            centers.append((0.5 + 0.32 * math.cos(angle), 0.5 + 0.32 * math.sin(angle)))
        for community, nodes in enumerate(partitions):
            cx, cy = centers[community]
            for node in nodes:
                x = _clip01(cx + rng.gauss(0.0, 0.06))
                y = _clip01(cy + rng.gauss(0.0, 0.06))
                coordinates[node] = (x, y)
                regions[node] = community
        p_intra = float(kwargs.get("p_intra", 0.45))
        p_inter = float(kwargs.get("p_inter", 0.05))
        if ensure_strongly_connected:
            _add_backbone_cycle(G, num_nodes, bidirectional=True)
        for community, nodes in enumerate(partitions):
            for i, source in enumerate(nodes):
                for target in nodes[i + 1 :]:
                    if rng.random() < p_intra:
                        _add_bidirectional_edge(G, source, target)
        for idx, nodes in enumerate(partitions):
            next_nodes = partitions[(idx + 1) % len(partitions)] if partitions else []
            if nodes and next_nodes:
                source = rng.choice(nodes)
                target = rng.choice(next_nodes)
                _add_bidirectional_edge(G, source, target)
            for source in nodes:
                for target in next_nodes:
                    if source != target and rng.random() < p_inter:
                        _add_bidirectional_edge(G, source, target)

    else:
        supported = ["random_geometric", "small_world", "scale_free", "community"]
        raise ValueError(f"Unsupported graph_type '{graph_type}'. Expected one of {supported}.")

    for node in range(num_nodes):
        x, y = coordinates[node]
        G.add_node(node, x=float(x), y=float(y), region=int(regions[node]))

    if not directed:
        # The project uses DiGraph throughout, but the argument is retained for API compatibility.
        pass

    assign_edge_attributes(
        G,
        min_delay_ms=int(kwargs.get("min_delay_ms", 1)),
        max_delay_ms=int(kwargs.get("max_delay_ms", 10)),
        seed=seed,
    )

    G.graph.update(
        {
            "graph_type": graph_type,
            "seed": seed,
            "directed": True,
            "ensure_strongly_connected": ensure_strongly_connected,
        }
    )
    return G
