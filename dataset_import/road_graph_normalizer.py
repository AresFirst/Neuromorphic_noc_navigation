"""道路图标准化工具。

把 SUMO 原始道路图转换为项目统一使用的 `nx.DiGraph` 属性格式，
供 Dijkstra、Loihi wavefront、STDP 回溯、Grid/Place、Relay 和 Noxim
实验通过 `graph.json` 直接复用。
"""

from __future__ import annotations

import math
import random
from collections import deque
from typing import Hashable

import networkx as nx


def _as_positive_float(value, fallback: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(parsed) or parsed <= 0.0:
        return fallback
    return parsed


def _largest_scc_copy(G: nx.DiGraph) -> nx.DiGraph:
    if G.number_of_nodes() == 0:
        raise ValueError("cannot normalize an empty road graph")
    components = list(nx.strongly_connected_components(G))
    if not components:
        raise ValueError("road graph has no strongly connected component")
    largest = max(components, key=len)
    return G.subgraph(largest).copy()


def _choose_crop_center(G: nx.DiGraph, seed: int) -> Hashable:
    undirected = G.to_undirected(as_view=True)
    rng = random.Random(seed)
    candidates = sorted(
        G.nodes(),
        key=lambda node: (G.in_degree(node) + G.out_degree(node), str(node)),
        reverse=True,
    )[: min(25, G.number_of_nodes())]
    rng.shuffle(candidates)

    best_node = candidates[0]
    best_score: tuple[int, int, float] | None = None
    for node in candidates:
        lengths = nx.single_source_shortest_path_length(undirected, node, cutoff=50)
        reachable = len(lengths)
        total_degree = int(G.in_degree(node) + G.out_degree(node))
        avg_distance = sum(lengths.values()) / reachable if reachable else math.inf
        score = (reachable, total_degree, -avg_distance)
        if best_score is None or score > best_score:
            best_node = node
            best_score = score
    return best_node


def _crop_by_bfs(G: nx.DiGraph, max_nodes: int, seed: int) -> nx.DiGraph:
    if G.number_of_nodes() <= max_nodes:
        return G.copy()

    center = _choose_crop_center(G, seed)
    undirected = G.to_undirected(as_view=True)
    selected: list[Hashable] = []
    seen = {center}
    queue: deque[Hashable] = deque([center])

    while queue and len(selected) < max_nodes:
        node = queue.popleft()
        selected.append(node)
        neighbors = sorted(
            undirected.neighbors(node),
            key=lambda candidate: (G.in_degree(candidate) + G.out_degree(candidate), str(candidate)),
            reverse=True,
        )
        for neighbor in neighbors:
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
            if len(seen) >= max_nodes * 4:
                # 避免在稠密图上无限扩张候选队列；真正入选仍由 selected 控制。
                break

    if len(selected) < 2:
        raise ValueError("max_nodes crop produced fewer than 2 nodes")
    return G.subgraph(selected[:max_nodes]).copy()


def _assign_spatial_grid_regions(
    G: nx.DiGraph,
    region_grid_rows: int,
    region_grid_cols: int,
) -> None:
    xs = [float(attrs["x"]) for _, attrs in G.nodes(data=True)]
    ys = [float(attrs["y"]) for _, attrs in G.nodes(data=True)]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    for node, attrs in G.nodes(data=True):
        x = float(attrs["x"])
        y = float(attrs["y"])
        if math.isclose(max_x, min_x):
            col = 0
        else:
            col = int((x - min_x) / (max_x - min_x) * region_grid_cols)
            col = max(0, min(region_grid_cols - 1, col))
        if math.isclose(max_y, min_y):
            row = 0
        else:
            row = int((y - min_y) / (max_y - min_y) * region_grid_rows)
            row = max(0, min(region_grid_rows - 1, row))
        attrs["region"] = int(row * region_grid_cols + col)


def _normalize_delays(G: nx.DiGraph, min_delay_ms: int, max_delay_ms: int) -> None:
    base_costs = [float(attrs["base_cost"]) for _, _, attrs in G.edges(data=True)]
    min_cost = min(base_costs)
    max_cost = max(base_costs)

    for _, _, attrs in G.edges(data=True):
        base_cost = float(attrs["base_cost"])
        if math.isclose(min_cost, max_cost):
            delay_ms = int(min_delay_ms)
        else:
            normalized = (base_cost - min_cost) / (max_cost - min_cost)
            mapped = min_delay_ms + normalized * (max_delay_ms - min_delay_ms)
            delay_ms = int(round(mapped))
        delay_ms = max(min_delay_ms, min(max_delay_ms, delay_ms))
        attrs["delay_ms"] = int(delay_ms)
        attrs["original_delay_ms"] = int(delay_ms)


def _euclidean_distance(G: nx.DiGraph, u, v) -> float:
    x1 = float(G.nodes[u]["x"])
    y1 = float(G.nodes[u]["y"])
    x2 = float(G.nodes[v]["x"])
    y2 = float(G.nodes[v]["y"])
    distance = math.hypot(x2 - x1, y2 - y1)
    return distance if distance > 0.0 else 1e-9


def normalize_road_graph(
    G: nx.DiGraph,
    min_delay_ms: int = 1,
    max_delay_ms: int = 10,
    largest_strongly_connected_component: bool = True,
    max_nodes: int | None = None,
    region_method: str = "spatial_grid",
    region_grid_rows: int = 4,
    region_grid_cols: int = 4,
    seed: int = 0,
    source: str = "most",
) -> nx.DiGraph:
    """把原始道路图标准化为项目通用 DiGraph。

    输出节点重新编号为 `0..n-1`，原始 junction id 写入 `original_id`；
    edge 的原始 SUMO id 写入 `original_edge_id`；`base_cost` 线性映射到
    `[min_delay_ms, max_delay_ms]`，得到整数 `delay_ms`。
    """
    if min_delay_ms < 1:
        raise ValueError("min_delay_ms must be positive")
    if max_delay_ms < min_delay_ms:
        raise ValueError("max_delay_ms must be >= min_delay_ms")
    if max_nodes is not None and max_nodes < 2:
        raise ValueError("max_nodes must be >= 2 or None")
    if region_grid_rows < 1 or region_grid_cols < 1:
        raise ValueError("region grid dimensions must be positive")
    if region_method != "spatial_grid":
        raise NotImplementedError("only region_method='spatial_grid' is currently implemented")

    original_attrs = dict(G.graph)
    num_nodes_before = int(G.number_of_nodes())
    num_edges_before = int(G.number_of_edges())
    work = nx.DiGraph(G)
    if work.number_of_nodes() == 0 or work.number_of_edges() == 0:
        raise ValueError("cannot normalize an empty road graph")

    if largest_strongly_connected_component:
        work = _largest_scc_copy(work)
    if max_nodes is not None and work.number_of_nodes() > max_nodes:
        work = _crop_by_bfs(work, max_nodes=max_nodes, seed=seed)
        if largest_strongly_connected_component:
            work = _largest_scc_copy(work)

    if work.number_of_nodes() < 2 or work.number_of_edges() == 0:
        raise ValueError("normalized road graph is too small after SCC/crop filtering")

    mapping = {node: idx for idx, node in enumerate(work.nodes())}
    normalized = nx.DiGraph()
    for old_node, new_node in mapping.items():
        attrs = work.nodes[old_node]
        try:
            x = float(attrs["x"])
            y = float(attrs["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"road graph node {old_node!r} missing valid x/y coordinates") from exc
        normalized.add_node(
            new_node,
            x=x,
            y=y,
            source=str(source),
            original_id=str(attrs.get("original_id", old_node)),
        )

    for old_u, old_v, attrs in work.edges(data=True):
        new_u = mapping[old_u]
        new_v = mapping[old_v]
        distance = _as_positive_float(attrs.get("distance"), _euclidean_distance(work, old_u, old_v))
        if distance is None:
            distance = 1e-9
        base_cost = _as_positive_float(attrs.get("base_cost"), distance)
        if base_cost is None:
            base_cost = distance
        normalized.add_edge(
            new_u,
            new_v,
            distance=float(distance),
            base_cost=float(base_cost),
            state="normal",
            source=str(source),
            original_edge_id=str(attrs.get("original_edge_id", f"{old_u}->{old_v}")),
        )

    if normalized.number_of_edges() == 0:
        raise ValueError("normalized road graph has no valid edges")

    _assign_spatial_grid_regions(normalized, region_grid_rows, region_grid_cols)
    _normalize_delays(normalized, min_delay_ms, max_delay_ms)
    normalized.graph.update(original_attrs)
    normalized.graph.update(
        {
            "dataset_name": original_attrs.get("dataset_name", "MoST"),
            "dataset_type": original_attrs.get("dataset_type", "sumo_netxml"),
            "normalized": True,
            "num_nodes_before_normalization": num_nodes_before,
            "num_edges_before_normalization": num_edges_before,
            "num_nodes_after_normalization": normalized.number_of_nodes(),
            "num_edges_after_normalization": normalized.number_of_edges(),
            "max_nodes": max_nodes,
            "cropped": bool(max_nodes is not None and num_nodes_before > max_nodes),
            "min_delay_ms": int(min_delay_ms),
            "max_delay_ms": int(max_delay_ms),
            "region_method": region_method,
            "region_grid_rows": int(region_grid_rows),
            "region_grid_cols": int(region_grid_cols),
        }
    )
    return normalized
