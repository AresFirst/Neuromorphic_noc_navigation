"""NoC 代理指标: 无需 Noxim 的快速 NoC 性能估算。

通过曼哈顿距离和包大小计算近似 NoC 性能指标:
- average_hop: 平均每包的曼哈顿跳数
- energy_proxy: 粗略能量估算 = Σ(packet_size × manhattan_hop)
- hotspot_core: 最忙碌的 core (收发包总数最多)

这些指标不需要运行耗时的 Noxim 仿真，可以快速迭代评估映射策略的好坏。

注意: 代理指标不考虑拥塞、缓冲区竞争、路由算法等因素，
只能作为相对比较的粗略参考，不是严格的物理建模。
"""

from __future__ import annotations

from collections import Counter

import pandas as pd


def core_id_to_xy(core_id: int, mesh_cols: int) -> tuple[int, int]:
    """将线性 core ID 转换为 2D Mesh 坐标。

    行主序: x = core_id % mesh_cols, y = core_id // mesh_cols。

    Args:
        core_id: 线性 core ID。
        mesh_cols: Mesh 列数。

    Returns:
        (x, y) 坐标元组。

    Raises:
        ValueError: mesh_cols <= 0。
    """
    if mesh_cols <= 0:
        raise ValueError("mesh_cols must be positive")
    return int(core_id % mesh_cols), int(core_id // mesh_cols)


def manhattan_hop(src_core: int, dst_core: int, mesh_cols: int) -> int:
    """计算两个 core 在 2D Mesh 上的曼哈顿距离（跳数）。

    曼哈顿距离 = |x1 - x2| + |y1 - y2|。
    对于使用 XY 路由的 2D Mesh NoC，这是精确的单包跳数。

    Args:
        src_core: 源 core ID。
        dst_core: 目标 core ID。
        mesh_cols: Mesh 列数。

    Returns:
        跳数 (非负整数)。
    """
    src_x, src_y = core_id_to_xy(src_core, mesh_cols)
    dst_x, dst_y = core_id_to_xy(dst_core, mesh_cols)
    return int(abs(src_x - dst_x) + abs(src_y - dst_y))


def compute_noc_proxy_metrics(
    packet_trace: pd.DataFrame,
    mesh_rows: int,
    mesh_cols: int,
) -> dict:
    """从数据包跟踪计算 NoC 代理指标。

    不运行 Noxim，直接用曼哈顿距离估算通信性能。
    适用于快速迭代和策略对比。

    Args:
        packet_trace: 数据包跟踪 DataFrame (PACKET_COLUMNS 格式)。
        mesh_rows: Mesh 行数。
        mesh_cols: Mesh 列数。

    Returns:
        字典:
        - num_packets: 总包数
        - num_spike_packets: spike 包数
        - num_relay_packets: relay 包数
        - average_hop: 平均曼哈顿跳数
        - max_hop: 最大曼哈顿跳数
        - total_hop: 总跳数
        - energy_proxy: 代理能耗 (= Σ(packet_size × hop))
        - hotspot_core: 最繁忙 core ID (平局时选最小 ID)
        - hotspot_packet_count: 最繁忙 core 的包计数
    """
    # 空 table → 返回全零/None
    if packet_trace.empty:
        return {
            "num_packets": 0,
            "num_spike_packets": 0,
            "num_relay_packets": 0,
            "average_hop": 0.0,
            "max_hop": 0,
            "total_hop": 0,
            "energy_proxy": 0.0,
            "hotspot_core": None,
            "hotspot_packet_count": 0,
        }

    hops: list[int] = []
    energy = 0.0
    hotspot_counts: Counter[int] = Counter()

    for row in packet_trace.to_dict(orient="records"):
        src_core = int(row["src_core"])
        dst_core = int(row["dst_core"])
        packet_size = float(row.get("packet_size", 1))

        # 计算此包的曼哈顿跳数
        hop = manhattan_hop(src_core, dst_core, mesh_cols)
        hops.append(hop)

        # 代理能耗模型: energy ∝ packet_size × hop_count
        # 这粗略反映了数据在 mesh 中传输消耗的能量
        energy += packet_size * hop

        # 每个 core 的收发包计数（找最忙 core）
        hotspot_counts[src_core] += 1
        hotspot_counts[dst_core] += 1

    # 找最忙 core: 先按 -count 排序(越大越前)，再按 core_id (越小越前)
    hotspot_core, hotspot_count = min(
        hotspot_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )

    packet_types = packet_trace["packet_type"] if "packet_type" in packet_trace else []
    return {
        "num_packets": int(len(packet_trace)),
        "num_spike_packets": int(sum(1 for value in packet_types if value == "spike")),
        "num_relay_packets": int(sum(1 for value in packet_types if value == "relay")),
        "average_hop": float(sum(hops) / len(hops)),
        "max_hop": int(max(hops)),
        "total_hop": int(sum(hops)),
        "energy_proxy": float(energy),
        "hotspot_core": int(hotspot_core),
        "hotspot_packet_count": int(hotspot_count),
    }
