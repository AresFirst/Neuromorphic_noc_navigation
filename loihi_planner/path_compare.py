"""SNN 路径 vs Dijkstra 路径对比。

提供两种对比方式:
1. compute_path_cost(): 计算路径的累积权重代价
2. compare_snn_path_with_dijkstra(): 全面对比 SNN 波前路径和 Dijkstra 最优路径

对比指标包括: 代价比率 (optimality_ratio)、路径相同性、代价相同性、跳数。
"""

from __future__ import annotations

import math


def compute_path_cost(G, path: list[int], weight: str = "base_cost") -> float:
    """计算路径的总累积权重代价。

    对路径中相邻节点间的边，累加指定的权重属性。

    Args:
        G: 有向图。
        path: 路径节点列表 [v0, v1, ..., vk]。
        weight: 边权重属性名（如 "base_cost" 或 "delay_ms"）。

    Returns:
        路径总代价。空路径或单节点路径返回 0.0。

    Raises:
        ValueError: 路径中包含不存在的边。
    """
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
    """全面对比 SNN 波前路径和 Dijkstra 最优路径。

    Args:
        G: 有向图。
        snn_path: SNN 波前路由得到的路径。
        dijkstra_path: Dijkstra 算法得到的最优路径。
        weight: 比较用的边权重属性名。

    Returns:
        对比结果字典:
        - snn_cost: SNN 路径总代价
        - dijkstra_cost: Dijkstra 路径总代价
        - optimality_ratio: cost_ratio = snn/dijkstra (≤1.0 表示 SNN 找到最优)
        - same_path: 两个路径是否完全相同
        - same_cost: 两个代价是否相同 (math.isclose)
        - snn_num_hops / dijkstra_num_hops: 两个路径的跳数
    """
    snn_cost = compute_path_cost(G, snn_path, weight=weight)
    dijkstra_cost = compute_path_cost(G, dijkstra_path, weight=weight)

    # 路径完全相同（节点列表一致）
    same_path = list(snn_path) == list(dijkstra_path)
    # 代价相同（浮点数容差比较）
    same_cost = math.isclose(snn_cost, dijkstra_cost, rel_tol=1e-9, abs_tol=1e-9)

    # 最优性比率: 1.0 = 最优, >1.0 = 次优
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
