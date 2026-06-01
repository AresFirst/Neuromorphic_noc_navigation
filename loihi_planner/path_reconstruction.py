"""路径重建：从父节点追踪关系反向追溯完整路径。

给定 parent_trace (每个节点的父节点关系) 和目标节点 target，
通过沿父链反向走到起点 start，重建完整路径。

算法:
    current = target
    while current != start:
        current = parent_trace[current]  # 沿父节点回溯
    path.reverse()  # 转为正向顺序

检测机制:
- 缺失节点: parent_trace 中找不到当前节点 → ValueError
- 空父节点: 某节点的 parent 为 None → ValueError（父链断裂）
- 环路检测: visited 集合跟踪已访问节点 → ValueError（循环引用）
"""

from __future__ import annotations


def reconstruct_path_from_parent(
    parent_trace: dict[int, int | None],
    start: int,
    target: int,
) -> list[int]:
    """从父节点追踪字典重建从 start 到 target 的完整路径。

    Args:
        parent_trace: {节点ID: 父节点ID 或 None} 字典。
                      起点 start 的父节点应为 None。
        start: 起点节点 ID。
        target: 目标节点 ID。

    Returns:
        [start, ..., target] 正向路径列表。

    Raises:
        ValueError: 目标不在 parent_trace 中、父链断裂（遇到 None）、
                    检测到环路或节点缺失。
    """
    # 起点 = 终点：直接返回单节点路径
    if start == target:
        return [start]
    if target not in parent_trace and target != start:
        raise ValueError(f"target {target} is not present in the parent trace")

    # 从 target 出发，沿父链反向走回 start
    path = [target]
    visited = {target}  # 已访问集合，用于环路检测
    current = target

    while current != start:
        if current not in parent_trace:
            raise ValueError(f"node {current} is not present in the parent trace")
        current = parent_trace[current]
        if current is None:
            # 父链断裂：某节点的 parent 是 None 但尚未到达 start
            raise ValueError(f"Unable to reconstruct a path from {target} back to start {start}")
        if current in visited:
            # 检测到环路：当前节点已经访问过
            raise ValueError("Cycle detected while reconstructing path from parent trace")
        visited.add(current)
        path.append(current)

    # 此时 path = [target, ..., start]，需要翻转
    path.reverse()
    return path  # 现在 path = [start, ..., target]
