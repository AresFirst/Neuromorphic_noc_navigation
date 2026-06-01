"""图模块 (graph) —— 图生成、传统算法、持久化、指标与可视化。

本包提供：
- 4 种复杂拓扑图生成器（random_geometric, small_world, scale_free, community）
- Dijkstra 最短路径基线算法
- 图的 JSON 序列化/反序列化
- 图结构统计指标计算
- 基于 Matplotlib 的图路径可视化
"""

from .complex_graph_generator import assign_edge_attributes, generate_complex_graph
from .graph_baseline import (
    dijkstra_delay_path,
    dijkstra_path,
    evaluate_dijkstra_pairs,
    sample_start_target_pairs,
)
from .graph_io import load_graph_json, save_graph_json, save_results_json
from .graph_metrics import compute_graph_metrics, save_graph_metrics
from .visualization import plot_graph_with_path

__all__ = [
    "assign_edge_attributes",
    "generate_complex_graph",
    "dijkstra_delay_path",
    "dijkstra_path",
    "evaluate_dijkstra_pairs",
    "sample_start_target_pairs",
    "load_graph_json",
    "save_graph_json",
    "save_results_json",
    "compute_graph_metrics",
    "save_graph_metrics",
    "plot_graph_with_path",
]
