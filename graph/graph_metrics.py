"""图结构指标计算。

计算生成图的描述性统计指标，用于分析图的结构特性，
确保实验使用的图具有合理的拓扑属性。

统计内容:
- 基本统计: 节点数、边数、密度、强连通性
- 度统计: 出度/入度的均值和标准差
- 边统计: 平均距离、平均 base_cost、延迟均值和极值
- 区域统计: 各 region 的节点数量分布
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mean, pstdev

import networkx as nx

from .graph_io import save_results_json


def _safe_mean(values):
    """安全求均值: 空列表返回 None, 否则返回 float。"""
    return float(mean(values)) if values else None


def _safe_pstdev(values):
    """安全求总体标准差: 单元素返回 0.0, 空列表返回 None。"""
    return float(pstdev(values)) if len(values) > 1 else 0.0 if values else None


def compute_graph_metrics(G) -> dict:
    """计算图的结构指标。

    Args:
        G: NetworkX 有向图 (节点需有 region 属性, 边需有 distance/base_cost/delay_ms 属性)。

    Returns:
        指标字典，包含:
        - graph_type, seed: 图元数据
        - num_nodes, num_edges: 规模
        - density: 图密度 = E / (V*(V-1))
        - is_strongly_connected: 是否强连通
        - average_out_degree / average_in_degree: 平均出入度
        - out_degree_std / in_degree_std: 出入度标准差
        - average_distance / average_base_cost / average_delay_ms: 平均边属性
        - min_delay_ms / max_delay_ms: 延迟极值
        - region_histogram: 各区域节点分布
    """
    num_nodes = G.number_of_nodes()
    num_edges = G.number_of_edges()

    # 度分布统计
    out_degrees = [degree for _, degree in G.out_degree()]
    in_degrees = [degree for _, degree in G.in_degree()]

    # 边属性统计
    distances = [float(attrs.get("distance", 0.0)) for _, _, attrs in G.edges(data=True)]
    base_costs = [float(attrs.get("base_cost", 0.0)) for _, _, attrs in G.edges(data=True)]
    delays = [int(attrs.get("delay_ms", 0)) for _, _, attrs in G.edges(data=True)]

    # 区域分布: Counter 统计每个 region 的节点数
    regions = Counter(int(attrs.get("region", 0)) for _, attrs in G.nodes(data=True))

    metrics = {
        "graph_type": G.graph.get("graph_type"),
        "seed": G.graph.get("seed"),
        "num_nodes": num_nodes,
        "num_edges": num_edges,
        # density = 实际边数 / 最大可能边数 = E / (V*(V-1))
        "density": float(nx.density(G)) if num_nodes > 1 else 0.0,
        "is_strongly_connected": bool(nx.is_strongly_connected(G)) if num_nodes > 0 else True,
        "average_out_degree": _safe_mean(out_degrees),
        "average_in_degree": _safe_mean(in_degrees),
        "out_degree_std": _safe_pstdev(out_degrees),
        "in_degree_std": _safe_pstdev(in_degrees),
        "average_distance": _safe_mean(distances),
        "average_base_cost": _safe_mean(base_costs),
        "average_delay_ms": _safe_mean(delays),
        "min_delay_ms": min(delays) if delays else None,
        "max_delay_ms": max(delays) if delays else None,
        "region_histogram": dict(regions),
    }
    return metrics


def save_graph_metrics(G, path: str) -> dict:
    """计算图指标并保存为 JSON 文件。

    Args:
        G: 图。
        path: 输出 JSON 路径。

    Returns:
        指标字典（与 compute_graph_metrics 返回值相同）。
    """
    metrics = compute_graph_metrics(G)
    save_results_json(metrics, path)
    return metrics
