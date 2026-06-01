"""动态重规划：从连续坐标位置重新规划路径。

提供一站式函数 replan_from_position()，
将从连续坐标定位到最近的图节点、运行 SNN 波前路由、
以及路径重建和代价计算的所有步骤串联在一起。

适用于 Agent 在真实环境中移动时，
需要根据新的连续坐标重新规划到目标的路径的场景。

工作流程:
    (x, y) → estimate_start_node_from_position() → start_node
           → run_loihi_wavefront() → spike_times
           → infer_parent_trace_from_spikes() → parent_trace
           → reconstruct_path_from_parent() → path
           → compute_path_cost() → path_cost
"""

from __future__ import annotations

import networkx as nx

# 从 localization 包导入连续坐标→图节点的定位函数
from localization.dynamic_start import estimate_start_node_from_position

from .loihi_wavefront import run_loihi_wavefront
from .parent_trace import infer_parent_trace_from_spikes
from .path_compare import compute_path_cost
from .path_reconstruction import reconstruct_path_from_parent


def replan_from_position(
    G: nx.DiGraph,
    x: float,
    y: float,
    target: int,
    sigma: float = 0.1,
    loihi_config: dict | None = None,
) -> dict:
    """从连续坐标 (x, y) 重新规划到目标节点的路径。

    完整流程:
    1. 将 (x, y) 定位到图上最近的节点 (estimate_start_node_from_position)
    2. 运行 SNN 波前路由 (run_loihi_wavefront)
    3. 从脉冲时间推断父节点关系 (infer_parent_trace_from_spikes)
    4. 反向追踪重建路径 (reconstruct_path_from_parent)
    5. 计算路径总代价 (compute_path_cost)

    Args:
        G: 有向图（节点需有 x, y 属性）。
        x: Agent 当前连续 x 坐标。
        y: Agent 当前连续 y 坐标。
        target: 目标节点 ID。
        sigma: 定位高斯 sigma（默认 0.1）。越小越精确。
        loihi_config: SNN 参数配置字典（threshold, weight, refractory_ms, seed）。

    Returns:
        {
            "estimated_start": 定位到的起始节点 ID (或 None),
            "target": 目标节点 ID,
            "path": [start, ..., target] 路径列表 (或 None),
            "path_cost": 路径总延迟代价 (或 None),
            "target_arrival_time_ms": 波前到达目标的时间,
            "num_spikes": SNN 仿真中发放的脉冲总数,
            "success": True/False,
            "error": 错误消息 (或 None)
        }
    """
    config = loihi_config or {}
    try:
        # 步骤 1: 连续坐标 → 图节点
        estimated_start = estimate_start_node_from_position(G, x, y, sigma=sigma)

        # 步骤 2: SNN 波前路由
        wavefront = run_loihi_wavefront(
            G,
            estimated_start,
            target,
            delay_attr="delay_ms",
            threshold=float(config.get("threshold", 1.0)),
            weight=float(config.get("weight", 1.1)),
            refractory_ms=int(config.get("refractory_ms", 1000)),
            seed=int(config.get("seed", 0)),
        )

        # 波前失败：目标不可达
        if not wavefront.get("success"):
            return {
                "estimated_start": estimated_start,
                "target": target,
                "path": None,
                "path_cost": None,
                "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
                "num_spikes": int(wavefront.get("num_spikes", 0)),
                "success": False,
                "error": wavefront.get("error"),
            }

        # 步骤 3: 父节点追踪
        parent_trace = infer_parent_trace_from_spikes(
            G,
            wavefront["spike_times_by_neuron"],
            estimated_start,
            delay_attr="delay_ms",
        )

        # 步骤 4: 路径重建
        path = reconstruct_path_from_parent(parent_trace, estimated_start, target)

        # 步骤 5: 路径代价计算
        path_cost = compute_path_cost(G, path, weight="delay_ms")

        return {
            "estimated_start": estimated_start,
            "target": target,
            "path": path,
            "path_cost": path_cost,
            "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
            "num_spikes": int(wavefront.get("num_spikes", 0)),
            "success": True,
            "error": None,
        }
    except Exception as exc:
        # 任何步骤失败时返回统一的失败结果
        return {
            "estimated_start": None,
            "target": target,
            "path": None,
            "path_cost": None,
            "target_arrival_time_ms": None,
            "num_spikes": 0,
            "success": False,
            "error": str(exc),
        }
