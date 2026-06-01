"""数据包跟踪转换: SNN 脉冲时间 → NoC 包跟踪。

将 SNN 仿真产生的脉冲发放时间表转换为 NoC 可理解的数据包跟踪 DataFrame。

转换规则 (spike_trace_to_packet_trace):
    对图的每条边 (src→dst):
    1. 跳过 state="blocked" 的边
    2. 要求两端神经元都发放了脉冲
    3. 验证时间关系: spike_time[src] + delay ≈ spike_time[dst]
       (在 tolerance_ms 容差内)
    4. 通过 core_mapping 将 (src_neuron, dst_neuron) 转为 (src_core, dst_core)
    5. 生成一条 packet 记录: type="spike", size=1

输出 DataFrame 结构 (PACKET_COLUMNS):
    cycle, src_neuron, dst_neuron, src_core, dst_core, packet_type, packet_size
"""

from __future__ import annotations

import pandas as pd

# 数据包跟踪 DataFrame 的标准列名
PACKET_COLUMNS = [
    "cycle",          # 注入周期 (对应源神经元的发放时间)
    "src_neuron",     # 源神经元 ID
    "dst_neuron",     # 目标神经元 ID
    "src_core",       # 源物理 core ID (由 core_mapping 查询)
    "dst_core",       # 目标物理 core ID
    "packet_type",    # "spike" (波前传播) 或 "relay" (中继事件)
    "packet_size",    # 数据包大小 (flits)
]


def spike_trace_to_packet_trace(
    G,
    spike_times_by_neuron: dict[int, float],
    core_mapping: dict[int, int],
    delay_attr: str = "delay_ms",
    tolerance_ms: float = 1.0,
) -> pd.DataFrame:
    """将 SNN 脉冲时间表转换为 NoC 数据包跟踪。

    遍历图的所有边，检查每条边上是否发生了波前传播事件。
    如果 spike_time[src] + delay ≈ spike_time[dst] (容差内)，
    说明波前沿该边传播，生成对应的数据包记录。

    Args:
        G: 有向图（边需有 delay_attr 和 state 属性）。
        spike_times_by_neuron: {神经元ID: 首次发放时间(ms)}。
        core_mapping: {神经元ID: 物理 core ID}。
        delay_attr: 边延迟属性名。
        tolerance_ms: 时间匹配容差 (ms)。

    Returns:
        DataFrame，列 = PACKET_COLUMNS，按 (cycle, src_neuron, dst_neuron) 排序。
    """
    rows: list[dict[str, object]] = []
    spike_times = {int(node): float(time) for node, time in spike_times_by_neuron.items()}

    for src, dst, attrs in G.edges(data=True):
        src = int(src)
        dst = int(dst)

        # 跳过阻塞边
        if attrs.get("state") == "blocked":
            continue
        # 两端都必须发放了脉冲
        if src not in spike_times or dst not in spike_times:
            continue

        delay = int(attrs.get(delay_attr, 0))
        if delay <= 0:
            continue

        # 验证时间关系: spike_time[src] + delay ≈ spike_time[dst]
        predicted = spike_times[src] + float(delay)
        if abs(predicted - spike_times[dst]) <= float(tolerance_ms):
            # 时间匹配 → 波前确实沿此边传播
            rows.append(
                {
                    "cycle": int(round(spike_times[src])),  # 包注入周期 = 源发放时间
                    "src_neuron": src,
                    "dst_neuron": dst,
                    "src_core": int(core_mapping[src]),     # 通过映射查物理 core
                    "dst_core": int(core_mapping[dst]),
                    "packet_type": "spike",                 # 波前传播包
                    "packet_size": 1,                       # 每个脉冲 = 1 flit
                }
            )

    # 按时间→源→目标排序，保证确定性输出
    return pd.DataFrame(rows, columns=PACKET_COLUMNS).sort_values(
        ["cycle", "src_neuron", "dst_neuron"], ignore_index=True
    )


def relay_events_to_packet_trace(
    relay_events: list[dict],
    core_mapping: dict[int, int],
    relay_core: int = 0,
) -> pd.DataFrame:
    """将中继事件列表转换为数据包跟踪。

    中继事件是第二阶段的通信：一个中继 core 向受影响的边两端节点发送通知包。

    Args:
        relay_events: [{"cycle": int, "edge_u": int, "edge_v": int}, ...]。
        core_mapping: {神经元ID: 物理 core ID}。
        relay_core: 中继所在的 core ID。

    Returns:
        DataFrame，列 = PACKET_COLUMNS，按 (cycle, dst_neuron) 排序。
    """
    rows: list[dict[str, object]] = []
    for event in relay_events:
        cycle = int(event.get("cycle", 0))
        edge_u = int(event["edge_u"])
        edge_v = int(event["edge_v"])
        # 每个 relay 事件发送两个包: 分别到边的两端节点
        for node in (edge_u, edge_v):
            rows.append(
                {
                    "cycle": cycle,
                    "src_neuron": -1,                       # relay 包没有源神经元
                    "dst_neuron": node,
                    "src_core": int(relay_core),
                    "dst_core": int(core_mapping[node]),
                    "packet_type": "relay",
                    "packet_size": 1,
                }
            )
    return pd.DataFrame(rows, columns=PACKET_COLUMNS).sort_values(
        ["cycle", "dst_neuron"], ignore_index=True
    )
