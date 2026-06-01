"""复杂拓扑图生成器。

生成模拟 NoC 网络的 NetworkX 有向图，支持 4 种拓扑类型。
每个生成图默认强连通，节点有 (x, y) 坐标和 region 属性，
边有 delay_ms（SNN 突触延迟）、base_cost（Dijkstra 代价）等属性。

生成流程:
1. 根据 graph_type 确定节点坐标和连边规则
2. 可选添加强连通主干环 (backbone cycle)
3. 调用 assign_edge_attributes() 为每条边计算延迟和代价
"""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Iterable

import networkx as nx


def _clip01(value: float) -> float:
    """将值裁剪到 [0.0, 1.0] 范围内，用于保证坐标在单位方形内。"""
    return max(0.0, min(1.0, value))


def _add_bidirectional_edge(G: nx.DiGraph, u: int, v: int) -> None:
    """添加双向边 u↔v。跳过自环 (u == v)。"""
    if u == v:
        return
    G.add_edge(u, v)
    G.add_edge(v, u)


def _add_backbone_cycle(G: nx.DiGraph, num_nodes: int, bidirectional: bool = True) -> None:
    """添加强连通主干环 0→1→2→...→num_nodes-1→0。

    这保证图在任何随机连边之前已经是强连通的。
    对于验证波前传播算法来说，这是关键的安全措施。

    Args:
        bidirectional: 如果 True，每个环边同时添加反方向边。
    """
    if num_nodes < 2:
        return
    for node in range(num_nodes):
        nxt = (node + 1) % num_nodes
        G.add_edge(node, nxt)
        if bidirectional:
            G.add_edge(nxt, node)


def _quadrant_region(x: float, y: float) -> int:
    """根据 (x, y) 坐标返回象限编号 (0~3)。

    划分规则: region = (x >= 0.5) + 2*(y >= 0.5)
    - region 0: x<0.5, y<0.5 (左下)
    - region 1: x>=0.5, y<0.5 (右下)
    - region 2: x<0.5, y>=0.5 (左上)
    - region 3: x>=0.5, y>=0.5 (右上)
    """
    return int(x >= 0.5) + 2 * int(y >= 0.5)


def _balanced_partitions(num_nodes: int, num_groups: int) -> list[list[int]]:
    """将 [0, num_nodes) 均匀分为 num_groups 个连续区间。

    用于 community 拓扑中的节点分区。
    余数优先分配给前几个组，保证各组大小差距不超过 1。

    例: _balanced_partitions(10, 3) → [[0,1,2,3], [4,5,6], [7,8,9]]
    """
    num_groups = max(1, min(num_groups, num_nodes))
    base = num_nodes // num_groups
    remainder = num_nodes % num_groups
    partitions: list[list[int]] = []
    cursor = 0
    for group in range(num_groups):
        # 前 remainder 个组多分配 1 个节点
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
    """加权不放回抽样。

    用于 scale_free 拓扑中的优先连接：度数高的节点有更高的被选概率。

    Args:
        candidates: 候选节点列表。
        weights: 对应权重（如度数+1）。
        k: 抽样数量。

    Returns:
        选中的节点列表（不超过 k 个，不重复）。
    """
    pool = list(zip(candidates, weights))
    selected: list[int] = []
    k = min(k, len(pool))
    for _ in range(k):
        total = sum(weight for _, weight in pool)
        if total <= 0:
            # 所有权重为 0 时均匀随机选
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
    """为图 G 的每条边计算延迟和代价属性。

    计算流程:
    1. 对每条边 (u→v)，计算欧氏距离 distance(u,v)
    2. 乘以随机抖动因子 (0.8~1.2) 得到 base_cost
    3. 将 base_cost 线性映射到 [min_delay_ms, max_delay_ms] 得到 delay_ms
    4. 保存 original_delay_ms = delay_ms（用于 RelayController 恢复）
    5. 边状态 state 初始化为 "normal"

    delay_ms 的含义: 在 SNN 中，它表示突触传导延迟（毫秒）。
    在 NoC 中，它表示链路通信延迟。两者等价。

    Args:
        G: 有向图（原地修改）。
        min_delay_ms: 最小延迟 (ms)，必须 >= 1。
        max_delay_ms: 最大延迟 (ms)，必须 >= min_delay_ms。
        seed: 随机种子（控制抖动因子的随机性）。

    Returns:
        原地修改后的图 G。
    """
    if min_delay_ms < 1:
        raise ValueError("min_delay_ms must be positive")
    if max_delay_ms < min_delay_ms:
        raise ValueError("max_delay_ms must be >= min_delay_ms")

    rng = random.Random(seed)
    # 第一步：预计算所有边的距离和基础代价
    edge_rows: list[tuple[int, int, float, float]] = []
    for u, v in G.edges():
        x1 = float(G.nodes[u]["x"])
        y1 = float(G.nodes[u]["y"])
        x2 = float(G.nodes[v]["x"])
        y2 = float(G.nodes[v]["y"])
        # 欧氏距离 = sqrt((x2-x1)^2 + (y2-y1)^2)
        distance = math.hypot(x2 - x1, y2 - y1)
        # 随机抖动 0.8~1.2 模拟链路质量的随机差异
        random_factor = rng.uniform(0.8, 1.2)
        base_cost = distance * random_factor
        edge_rows.append((u, v, distance, base_cost))

    if not edge_rows:
        return G

    # 第二步：将 base_cost 线性映射到 [min_delay_ms, max_delay_ms]
    base_costs = [row[3] for row in edge_rows]
    min_base = min(base_costs)
    max_base = max(base_costs)

    for u, v, distance, base_cost in edge_rows:
        if math.isclose(min_base, max_base):
            # 所有边的代价相同，取中间值避免除零
            delay_ms = int(round((min_delay_ms + max_delay_ms) / 2))
        else:
            # 线性归一化映射: [min_base, max_base] → [min_delay_ms, max_delay_ms]
            normalized = (base_cost - min_base) / (max_base - min_base)
            mapped = min_delay_ms + normalized * (max_delay_ms - min_delay_ms)
            delay_ms = int(round(mapped))
        # 确保在合法范围内
        delay_ms = max(min_delay_ms, min(max_delay_ms, delay_ms))
        # 第三步：原地更新边属性
        G[u][v].update(
            {
                "distance": float(distance),
                "base_cost": float(base_cost),
                "delay_ms": int(delay_ms),
                "original_delay_ms": int(delay_ms),  # 用于 RelayController 恢复
                "state": "normal",  # normal / blocked / penalized
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
    """生成指定拓扑类型的有向图。

    支持的拓扑类型:
    - random_geometric: 节点随机分布，半径内按概率连边。
        参数: radius (默认 0.25), edge_prob (默认 0.55)
    - small_world: 环状排列 + 近邻连接 + 随机重连。
        参数: k (默认 2, 近邻数), rewire_prob (默认 0.12, 重连概率)
    - scale_free: BA 无标度网络，优先连接。
        参数: m0 (默认 4, 种子节点数), m (默认 2, 每步连接数)
    - community: 节点分簇，簇内密集、簇间稀疏。
        参数: num_communities (默认 4), p_intra (默认 0.45), p_inter (默认 0.05)

    所有拓扑默认添加 backbone cycle 保证强连通性。

    Args:
        graph_type: 拓扑类型（大小写不敏感）。
        num_nodes: 节点总数。
        seed: 随机种子。
        directed: 保留参数，当前始终返回 DiGraph。
        ensure_strongly_connected: 是否添加强连通主干环。
        **kwargs: 拓扑特定的参数（见上文）。

    Returns:
        带有节点属性 (x, y, region) 和边属性 (delay_ms, base_cost 等) 的 DiGraph。
    """
    if num_nodes < 0:
        raise ValueError("num_nodes must be non-negative")

    graph_type = graph_type.lower().strip()
    rng = random.Random(seed)
    G = nx.DiGraph()

    # 空图：仅保留元数据
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

    # ---- random_geometric: 随机几何图 ----
    if graph_type == "random_geometric":
        # 节点在单位正方形 [0,1]×[0,1] 内均匀分布
        for node in range(num_nodes):
            x = rng.random()
            y = rng.random()
            coordinates[node] = (x, y)
            regions[node] = _quadrant_region(x, y)
        radius = float(kwargs.get("radius", 0.25))
        edge_prob = float(kwargs.get("edge_prob", 0.55))
        if ensure_strongly_connected:
            _add_backbone_cycle(G, num_nodes, bidirectional=True)
        # 距离 < radius 的节点对按 edge_prob 概率连边
        for i in range(num_nodes):
            for j in range(i + 1, num_nodes):
                x1, y1 = coordinates[i]
                x2, y2 = coordinates[j]
                distance = math.hypot(x2 - x1, y2 - y1)
                if distance <= radius and rng.random() <= edge_prob:
                    _add_bidirectional_edge(G, i, j)

    # ---- small_world: 小世界网络 ----
    elif graph_type == "small_world":
        # 节点均匀排列在圆上（半径 0.35），加小幅度随机抖动
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
        # 每个节点连接 k 个顺时针最近邻，每条边以 rewire_prob 重连到随机节点
        for node in range(num_nodes):
            for step in range(2, k + 1):
                target = (node + step) % num_nodes
                if rng.random() < rewire_prob:
                    target = rng.randrange(num_nodes)
                if target != node:
                    _add_bidirectional_edge(G, node, target)

    # ---- scale_free: BA 无标度网络 ----
    elif graph_type == "scale_free":
        # 节点在 [0.05, 0.95] 范围内随机分布
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
            # 种子节点间随机互连
            initial_nodes = list(range(min(m0, num_nodes)))
            for i in initial_nodes:
                for j in initial_nodes:
                    if i != j and rng.random() < 0.5:
                        _add_bidirectional_edge(G, i, j)
            # 后续节点按度优先 (preferential attachment) 连接
            for node in range(min(m0, num_nodes), num_nodes):
                existing = list(range(node))
                # 权重 = 度数 + 1，保证度高的节点更容易被选中
                weights = [G.degree(candidate) + 1 for candidate in existing]
                targets = _weighted_sample_without_replacement(rng, existing, weights, m)
                for target in targets:
                    if target != node:
                        G.add_edge(node, target)
                        if rng.random() < 0.35:
                            G.add_edge(target, node)

    # ---- community: 社区结构图 ----
    elif graph_type == "community":
        # 节点分为 num_communities 个组，每组围绕一个中心呈高斯分布
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
        p_intra = float(kwargs.get("p_intra", 0.45))  # 簇内连接概率
        p_inter = float(kwargs.get("p_inter", 0.05))  # 簇间连接概率
        if ensure_strongly_connected:
            _add_backbone_cycle(G, num_nodes, bidirectional=True)
        # 簇内连接：同组节点按 p_intra 随机互连
        for community, nodes in enumerate(partitions):
            for i, source in enumerate(nodes):
                for target in nodes[i + 1 :]:
                    if rng.random() < p_intra:
                        _add_bidirectional_edge(G, source, target)
        # 保证相邻社区间至少有一条连接边
        for idx, nodes in enumerate(partitions):
            next_nodes = partitions[(idx + 1) % len(partitions)] if partitions else []
            if nodes and next_nodes:
                source = rng.choice(nodes)
                target = rng.choice(next_nodes)
                _add_bidirectional_edge(G, source, target)
            # 簇间连接：不同组节点按 p_inter 随机互连
            for source in nodes:
                for target in next_nodes:
                    if source != target and rng.random() < p_inter:
                        _add_bidirectional_edge(G, source, target)

    else:
        supported = ["random_geometric", "small_world", "scale_free", "community"]
        raise ValueError(f"Unsupported graph_type '{graph_type}'. Expected one of {supported}.")

    # 将坐标和区域写入节点属性
    for node in range(num_nodes):
        x, y = coordinates[node]
        G.add_node(node, x=float(x), y=float(y), region=int(regions[node]))

    if not directed:
        # The project uses DiGraph throughout, but the argument is retained for API compatibility.
        pass

    # 为所有边计算延迟和代价属性
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
