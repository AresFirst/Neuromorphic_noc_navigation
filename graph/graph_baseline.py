"""Dijkstra 基线算法。

实现经典 Dijkstra 最短路径算法，作为传统（非神经形态）路径规划的基线。
用于与 SNN 波前路由的结果进行最优性对比。

关键函数:
- dijkstra_path(): 按 base_cost 求最短路径
- dijkstra_delay_path(): 按 delay_ms 求最短路径（等价于波前的最小延迟路径）
- sample_start_target_pairs(): 随机采样测试用的起止点对
- evaluate_dijkstra_pairs(): 批量评估，返回 DataFrame
"""

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
    """Dijkstra 最短路径算法的内部实现。

    使用最小堆优先队列，时间复杂度 O((V+E)log V)。

    Args:
        G: 有向图。
        start: 起点节点 ID。
        target: 终点节点 ID。
        weight: 边权重属性名 (如 "base_cost" 或 "delay_ms")。

    Returns:
        (path, cost) 元组: path 是从 start 到 target 的节点列表,
        cost 是路径总代价。

    Raises:
        nx.NodeNotFound: start 或 target 不在图中。
        nx.NetworkXNoPath: 不存在从 start 到 target 的路径。
    """
    if start not in G:
        raise nx.NodeNotFound(f"start node {start} not found")
    if target not in G:
        raise nx.NodeNotFound(f"target node {target} not found")

    # 优先队列: [(累计代价, 节点ID)]
    queue: list[tuple[float, int]] = [(0.0, start)]
    distances: dict[int, float] = {start: 0.0}
    previous: dict[int, int] = {}  # 用于路径反向追踪
    visited: set[int] = set()

    while queue:
        current_cost, node = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        # 到达目标，可以提前终止
        if node == target:
            break
        for neighbor, attrs in G[node].items():
            edge_cost = float(attrs.get(weight, 1.0))
            new_cost = current_cost + edge_cost
            # 松弛操作：发现更短路径时更新
            if new_cost < distances.get(neighbor, math.inf):
                distances[neighbor] = new_cost
                previous[neighbor] = node
                heapq.heappush(queue, (new_cost, neighbor))

    if target not in distances:
        raise nx.NetworkXNoPath(f"No path from {start} to {target}")

    # 从 target 沿 previous 链反向追踪回 start
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
    """按 base_cost 权重计算最短路径。

    base_cost 基于欧氏距离 + 随机抖动，反映链路基础代价。
    """
    return _dijkstra(G, start, target, weight)


def dijkstra_delay_path(
    G,
    start: int,
    target: int,
    delay_attr: str = "delay_ms",
) -> tuple[list[int], float]:
    """按 delay_ms 权重计算最短路径。

    delay_ms 是边延迟，在 SNN 中对应突触延迟。
    这个路径与波前传播找到的最短延迟路径应一致。
    """
    return _dijkstra(G, start, target, delay_attr)


def sample_start_target_pairs(
    G,
    num_pairs: int,
    seed: int = 0,
) -> list[tuple[int, int]]:
    """从图中随机采样不重复的 (起点, 终点) 对。

    Args:
        G: 图。
        num_pairs: 采样对数。
        seed: 随机种子。

    Returns:
        [(start, target), ...] 列表。start != target。
    """
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
    """对一批起止点对运行 Dijkstra，返回结构化结果。

    Args:
        G: 图。
        pairs: [(start, target), ...] 列表。
        weight: 边权重属性名。

    Returns:
        DataFrame，包含列: start, target, path, path_cost, num_hops, success, error。
        失败时 success=False，error 包含异常信息。
    """
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
