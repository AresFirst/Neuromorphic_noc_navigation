"""STDP 分析表构建。

为图的每条边生成 STDP (Spike-Timing-Dependent Plasticity) 风格的分析记录，
用于分析波前传播过程中哪些连接被"增强"了。

STDP 规则的核心思想:
- 如果前神经元发放 → 后神经元发放，且时间间隔合理: 增强 (LTP)
- 否则: 抑制或不变 (LTD)

在本项目中，STDP 被简化为二值标记:
- is_parent_edge=True: 该边在波前传播的 parent 链上 → stdp_weight = 1.0 (增强)
- is_parent_edge=False: 该边不在 parent 链上 → stdp_weight = 0.0 (不变)

输出 DataFrame 可用于后续的路径可视化和分析。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_stdp_trace_table(
    G,
    parent_trace: dict[int, int | None],
    spike_times_by_neuron: dict[int, float],
    delay_attr: str = "delay_ms",
) -> pd.DataFrame:
    """为图的每条边构建 STDP 分析记录。

    对每条边 (pre → post):
    - 如果两端节点都发放了脉冲，计算 Δt = post_spike_time - pre_spike_time
    - 如果 post 的 parent 等于 pre，则标记为 parent edge (is_parent_edge=True)

    Args:
        G: 有向图。
        parent_trace: {节点ID: 父节点ID} 字典（来自 infer_parent_trace_from_spikes）。
        spike_times_by_neuron: {神经元ID: 发放时间} 字典。
        delay_attr: 边延迟属性名（暂未使用，预留）。

    Returns:
        DataFrame，列:
        - pre: 前神经元 ID
        - post: 后神经元 ID
        - is_parent_edge: 该边是否在 parent 链上
        - pre_spike_time_ms: 前神经元发放时间
        - post_spike_time_ms: 后神经元发放时间
        - delta_t_ms: post_spike_time - pre_spike_time (None 如果任一未发放)
        - stdp_weight: 1.0 (parent edge) 或 0.0 (非 parent edge)
    """
    rows: list[dict[str, object]] = []
    for pre, post, attrs in G.edges(data=True):
        # 跳过两端都未发放的边（它们不参与路径）
        if pre not in spike_times_by_neuron and post not in spike_times_by_neuron:
            continue

        # 判断是否为 parent edge: 后神经元的 parent 是否等于前神经元
        is_parent_edge = parent_trace.get(post) == pre

        # 提取发放时间
        pre_time = spike_times_by_neuron.get(pre)
        post_time = spike_times_by_neuron.get(post)

        # 计算时间差（仅在两端都发放时有效）
        delta_t = None
        if pre_time is not None and post_time is not None:
            delta_t = float(post_time) - float(pre_time)

        rows.append(
            {
                "pre": int(pre),
                "post": int(post),
                "is_parent_edge": bool(is_parent_edge),
                "pre_spike_time_ms": None if pre_time is None else float(pre_time),
                "post_spike_time_ms": None if post_time is None else float(post_time),
                "delta_t_ms": delta_t,
                # 简化 STDP: parent edge → 增强 (1.0), 其他 → 不变 (0.0)
                "stdp_weight": 1.0 if is_parent_edge else 0.0,
            }
        )

    return pd.DataFrame(
        rows,
        columns=[
            "pre",
            "post",
            "is_parent_edge",
            "pre_spike_time_ms",
            "post_spike_time_ms",
            "delta_t_ms",
            "stdp_weight",
        ],
    )
