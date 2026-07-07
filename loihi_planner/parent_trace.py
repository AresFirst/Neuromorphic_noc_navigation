"""父节点追踪：从脉冲时间推断波前传播路径。

给定 SNN 仿真产生的各神经元首次发放时间和图的拓扑结构，
推断每个发放神经元是被哪个前驱神经元触发的。

推断算法 (infer_parent_trace_from_spikes):
    对每个发放的节点 node (除起点外):
        遍历所有前驱节点 predecessor:
            predicted_time = spike_time[predecessor] + edge_delay
            if |predicted_time - spike_time[node]| <= tolerance_ms:
                此 predecessor 为候选父节点
        在所有候选父节点中，优先选择时间误差最小、累计真实代价更低的父节点
        (最后才按节点 ID 稳定打破平局)

这对应于"波前沿最短路径传播"的假设:
最早触发当前节点的前驱才是真正的父节点。
"""

from __future__ import annotations

import math

import networkx as nx


def _positive_edge_cost(attrs: dict[str, object], preferred_attr: str) -> float:
    for key in (preferred_attr, "cost", "travel_time", "length"):
        value = attrs.get(key)
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed > 0.0:
            return parsed
    return 1.0


def infer_parent_trace_from_spikes(
    G: nx.DiGraph,
    spike_times_by_neuron: dict[int, float],
    start: int,
    delay_attr: str = "delay_ms",
    tolerance_ms: float = 1.0,
    tie_break_attr: str = "cost",
) -> dict[int, int | None]:
    """从 SNN 脉冲时间和图拓扑推断每个节点的父节点。

    父节点定义为"最早成功触发了当前节点的前驱神经元"。
    时间匹配使用容差 tolerance_ms 来容忍 SNN 仿真的数值精度误差。

    Args:
        G: 有向图（边需有 delay 属性和 state 属性）。
        spike_times_by_neuron: {神经元ID: 首次发放时间(ms)}。
        start: 起点节点 ID（其父节点始终为 None）。
        delay_attr: 边延迟属性名。
        tolerance_ms: 时间匹配容差 (ms)。|prediction - actual| <= tolerance 视为匹配。
        tie_break_attr: 多个前驱在同一 spike 时间内匹配时，用于稳定选择更合理父节点的真实代价属性。

    Returns:
        {节点ID: 父节点ID 或 None} 字典。
        未发放的节点和起点节点的父节点为 None。

    Raises:
        nx.NodeNotFound: start 不在图中。
    """
    # 初始化为全部 None（未发放的节点没有父节点）
    parent_trace: dict[int, int | None] = {node: None for node in G.nodes()}
    if start not in G:
        raise nx.NodeNotFound(f"start node {start} not found")

    accumulated_cost: dict[int, float] = {int(start): 0.0}
    fired_nodes = sorted(
        (node for node in G.nodes() if node in spike_times_by_neuron and node != start),
        key=lambda item: (float(spike_times_by_neuron[item]), int(item)),
    )

    for node in fired_nodes:
        # 跳过起点和未发放的节点
        post_spike_time = float(spike_times_by_neuron[node])
        if G.nodes[node].get("snn_neuron_closed", False):
            continue
        candidates: list[tuple[float, float, float, int]] = []

        # 遍历所有前驱节点
        for predecessor in G.predecessors(node):
            # 前驱必须也发放了脉冲
            if predecessor not in spike_times_by_neuron:
                continue
            if predecessor not in accumulated_cost:
                continue
            if G.nodes[predecessor].get("snn_neuron_closed", False):
                continue
            attrs = G[predecessor][node]
            # 跳过阻塞边
            if attrs.get("state") == "blocked" or attrs.get("snn_synapse_closed"):
                continue
            delay = int(attrs.get(delay_attr, 0))
            if delay <= 0:
                continue

            # 预测后节点发放时间 = 前驱发放时间 + 边延迟
            predicted_time = float(spike_times_by_neuron[predecessor]) + float(delay)
            # 时间匹配检查（容差内视为匹配）
            if abs(predicted_time - post_spike_time) <= tolerance_ms:
                edge_cost = _positive_edge_cost(attrs, tie_break_attr)
                path_cost = accumulated_cost[int(predecessor)] + edge_cost
                time_error = abs(predicted_time - post_spike_time)
                candidates.append((time_error, path_cost, edge_cost, int(predecessor)))

        # 在 spike-consistent 前驱中，优先选时间误差最小、累计真实代价更低的候选。
        # 这仍然只使用 SNN spike wavefront 的可行父边，不读取 Dijkstra/A* 的路径结果。
        if candidates:
            _time_error, chosen_cost, _edge_cost, chosen_parent = min(candidates)
            parent_trace[node] = int(chosen_parent)
            accumulated_cost[int(node)] = float(chosen_cost)

    # 起点始终没有父节点
    parent_trace[start] = None
    return parent_trace
