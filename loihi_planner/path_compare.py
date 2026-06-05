"""Path cost helper for the Brian2Loihi route result."""

from __future__ import annotations

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
