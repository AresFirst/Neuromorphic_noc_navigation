"""事件驱动波前参考算法（CPU 真值）。

实现一个基于最小堆优先队列的 Dijkstra-like 波前传播算法。
这是纯 Python 实现，运行在 CPU 上，作为 SNN 波前路由的"真值" (ground truth) 参考。

SNN 波前路由的准确性通过与 event_driven_wavefront() 的输出对比来验证:
- 各节点的最早到达时间是否一致
- 目标节点的到达时间是否与 SNN 一致

算法:
    与 Dijkstra 类似，但边权重语义是"传播延迟"而非"路径代价"。
    使用 heapq 维护当前波前边缘，每次弹出最早到达的节点，
    然后将其邻居的预计到达时间 (当前时间 + 边延迟) 推入堆中。

    仅记录每个节点的最早到达时间（标准最短路径松弛）。
"""

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
    """CPU 上的事件驱动波前传播算法。

    模拟一个从 start 出发、以边延迟为传播速度的波前。
    返回每个节点的最早到达时间和访问顺序。

    这是 Loihi SNN 波前路由的参考实现，两者在理想情况下应产生一致的结果。

    Args:
        G: 有向图（边需有 delay 属性和可选的 state 属性）。
        start: 起点节点 ID。
        target: 终点节点 ID。
        delay_attr: 边延迟属性名（默认 "delay_ms"）。
        blocked_state: 阻塞边的 state 值（默认 "blocked"）。

    Returns:
        {
            "arrival_times": {节点ID: 最早到达时间},
            "target_arrival_time": 目标到达时间 (None 表示不可达),
            "visited_order": [按首次访问顺序排列的节点列表]
        }

    Raises:
        nx.NodeNotFound: start 或 target 不在图中。
        ValueError: 边的 delay <= 0（无效延迟）。
    """
    if start not in G:
        raise nx.NodeNotFound(f"start node {start} not found")
    if target not in G:
        raise nx.NodeNotFound(f"target node {target} not found")

    # arrival_times: 记录每个节点的最早到达时间
    arrival_times: dict[int, float] = {start: 0.0}
    visited: set[int] = set()
    visited_order: list[int] = []
    # 优先队列: [(到达时间, 节点ID)]
    queue: list[tuple[float, int]] = [(0.0, start)]

    while queue:
        # 弹出最早到达的节点
        current_time, node = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        visited_order.append(node)

        # 到达目标，可以提前终止
        if node == target:
            break

        # 将波前传播到所有未阻塞的邻居
        for neighbor, attrs in G[node].items():
            # 跳过阻塞边
            if attrs.get("state") == blocked_state:
                continue
            delay = int(attrs.get(delay_attr, 0))
            if delay <= 0:
                raise ValueError(f"Edge ({node}, {neighbor}) has invalid delay {delay}.")
            # 预计到达时间 = 当前时间 + 边延迟
            arrival = float(current_time) + float(delay)
            # 松弛：只保留最早到达时间
            if arrival < arrival_times.get(neighbor, math.inf):
                arrival_times[neighbor] = arrival
                heapq.heappush(queue, (arrival, neighbor))

    return {
        "arrival_times": arrival_times,
        "target_arrival_time": arrival_times.get(target),
        "visited_order": visited_order,
    }
