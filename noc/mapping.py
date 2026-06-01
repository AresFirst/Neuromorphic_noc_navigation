"""Core 映射策略: 将图节点 (SNN 神经元) 分配到物理 NoC Mesh 的 core。

三种映射策略:

1. random: 每个神经元随机分配到一个 core。
   - 基线对照，不利用空间信息
   - 预期性能最差（数据包可能在 mesh 中跳跃很远的距离）

2. topology: 利用节点的 (x, y) 坐标，映射到空间最近的物理 core。
   - 公式: col = round(x * (mesh_cols-1)), row = round(y * (mesh_rows-1))
   - core_id = row * mesh_cols + col (行主序)
   - 保持空间拓扑的连续性

3. community: 按节点的 region 属性分组，同社区节点尽量放在相邻 core 上。
   - 每个社区有一个锚定 core（在 mesh 上均匀分布）
   - 社区内节点按到锚定的曼哈顿距离就近分配
   - 适合具有模块化结构的网络拓扑
"""

from __future__ import annotations

import random
from collections import defaultdict

import networkx as nx


def _num_cores(mesh_rows: int, mesh_cols: int) -> int:
    """验证 mesh 尺寸并返回 core 总数。

    Args:
        mesh_rows: Mesh 行数。
        mesh_cols: Mesh 列数。

    Returns:
        rows * cols。

    Raises:
        ValueError: 任一行/列 ≤ 0。
    """
    if mesh_rows <= 0 or mesh_cols <= 0:
        raise ValueError("mesh_rows and mesh_cols must be positive")
    return int(mesh_rows * mesh_cols)


def _core_from_xy(x: float, y: float, mesh_rows: int, mesh_cols: int) -> int:
    """将归一化坐标 (x, y) 映射到最近的物理 core。

    公式 (行主序):
        col = round(x * (mesh_cols - 1)), 钳制到 [0, mesh_cols-1]
        row = round(y * (mesh_rows - 1)), 钳制到 [0, mesh_rows-1]
        core_id = row * mesh_cols + col

    Args:
        x: 归一化 x 坐标 (通常 ∈ [0, 1])。
        y: 归一化 y 坐标 (通常 ∈ [0, 1])。
        mesh_rows, mesh_cols: Mesh 尺寸。

    Returns:
        core ID (0 .. rows*cols-1)。
    """
    # 四舍五入后钳制到合法范围
    col = min(mesh_cols - 1, max(0, int(round(float(x) * (mesh_cols - 1)))))
    row = min(mesh_rows - 1, max(0, int(round(float(y) * (mesh_rows - 1)))))
    # 行主序: core_id = row * cols + col
    return int(row * mesh_cols + col)


def create_core_mapping(
    G: nx.DiGraph,
    mesh_rows: int,
    mesh_cols: int,
    strategy: str,
    seed: int = 0,
) -> dict[int, int]:
    """将图节点映射到物理 NoC 2D Mesh 的 core。

    这是 SNN→NoC 桥接的关键函数。它决定了每个神经元在物理芯片上的位置，
    直接影响 NoC 通信的跳数和延迟。

    Args:
        G: 有向图（节点可含 x, y, region 属性）。
        mesh_rows: Mesh 行数。
        mesh_cols: Mesh 列数。
        strategy: 映射策略: "random" | "topology" | "community"。
        seed: 随机种子。

    Returns:
        {节点ID: core_id} 字典。core_id 范围 [0, rows*cols-1]。

    Raises:
        ValueError: 策略名称无效。
    """
    num_cores = _num_cores(mesh_rows, mesh_cols)
    strategy = strategy.lower().strip()
    nodes = sorted(int(node) for node in G.nodes())

    # ---- 策略 1: random ----
    # 每个节点均匀随机分配，不利用任何空间信息
    if strategy == "random":
        rng = random.Random(seed)
        return {node: rng.randrange(num_cores) for node in nodes}

    # ---- 策略 2: topology ----
    # 利用节点的 (x, y) 坐标，保持空间拓扑连续性
    if strategy == "topology":
        return {
            node: _core_from_xy(float(G.nodes[node]["x"]), float(G.nodes[node]["y"]), mesh_rows, mesh_cols)
            for node in nodes
        }

    # ---- 策略 3: community ----
    # 按 region 分组，同社区节点尽量靠近
    if strategy == "community":
        # 按 region 属性分组
        regions: dict[int, list[int]] = defaultdict(list)
        for node in nodes:
            regions[int(G.nodes[node].get("region", 0))].append(node)

        sorted_regions = sorted(regions)
        if not sorted_regions:
            return {}

        mapping: dict[int, int] = {}
        for region_index, region in enumerate(sorted_regions):
            # 社区内节点按 y 坐标排序（从上到下），tie-breaker 按 x 坐标
            region_nodes = sorted(
                regions[region],
                key=lambda node: (float(G.nodes[node].get("y", 0.0)), float(G.nodes[node].get("x", 0.0)), node),
            )

            # 计算该社区的锚定 core 位置（在 mesh 上均匀分布各社区）
            anchor_col = int(round((region_index % mesh_cols) * max(1, mesh_cols // max(1, len(sorted_regions)))))
            anchor_row = int(region_index * mesh_rows / max(1, len(sorted_regions)))
            anchor_col = min(mesh_cols - 1, max(0, anchor_col))
            anchor_row = min(mesh_rows - 1, max(0, anchor_row))

            # 按到锚定的曼哈顿距离排序所有 core
            nearby_cores = sorted(
                range(num_cores),
                key=lambda core: (
                    # 曼哈顿距离越小越好
                    abs(core // mesh_cols - anchor_row) + abs(core % mesh_cols - anchor_col),
                    core,  # tie-breaker: core ID
                ),
            )
            # 按序分配 community 节点到最近的 core
            for idx, node in enumerate(region_nodes):
                mapping[node] = nearby_cores[idx % len(nearby_cores)]
        return mapping

    raise ValueError("strategy must be one of: random, community, topology")
