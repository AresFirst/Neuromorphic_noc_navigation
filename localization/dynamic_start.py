"""动态起点定位入口。

提供一站式函数 estimate_start_node_from_position()，
将 Agent 的连续 (x, y) 坐标捕捉到图中最近的节点。

这是 localization 包的主要对外接口，
下游导航模块通过此函数获取 Agent 在图上的起始节点，
然后进行波前路由规划。
"""

from __future__ import annotations

import networkx as nx

from .place_cells import PlaceCellLayer


def estimate_start_node_from_position(
    G: nx.DiGraph,
    x: float,
    y: float,
    sigma: float = 0.1,
) -> int:
    """将连续坐标 (x, y) 定位到图中最近的节点。

    工作流程:
    1. 从图 G 中提取所有节点的 (x, y) 坐标
    2. 构建 PlaceCellLayer，以节点位置为高斯野中心
    3. 用 winner_take_all 找到激活最大的节点

    Args:
        G: NetworkX 有向图。每个节点必须有 "x" 和 "y" 属性
           (归一化坐标，通常在 [0, 1] 范围内)。
        x: Agent 当前连续 x 坐标。
        y: Agent 当前连续 y 坐标。
        sigma: 位置野的标准差。默认 0.1。
               sigma 越小越精确但要求 Agent 必须接近某节点。

    Returns:
        最近图节点的整数 ID。

    Raises:
        ValueError: 如果 sigma <= 0（由 PlaceCellLayer 抛出）。
        ValueError: 如果定位结果不在图中（安全检查）。
    """
    # 步骤 1: 从图节点属性中提取坐标
    node_positions = {
        int(node): (float(attrs["x"]), float(attrs["y"]))
        for node, attrs in G.nodes(data=True)
    }
    # 步骤 2: 构建位置细胞层
    layer = PlaceCellLayer(node_positions, sigma=sigma)
    # 步骤 3: 硬分配，找出最近的节点
    start = layer.winner_take_all(x, y)
    # 安全检查：确保 WTA 结果确实在图节点集合中
    if start not in G:
        raise ValueError("estimated start node is not in graph")
    return start
