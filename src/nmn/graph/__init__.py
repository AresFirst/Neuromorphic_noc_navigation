"""图相关能力的标准入口。"""

from __future__ import annotations

import sys
from importlib import import_module

from graph.complex_graph_generator import assign_edge_attributes, generate_complex_graph
from graph.graph_baseline import dijkstra_delay_path, dijkstra_path, evaluate_dijkstra_pairs, sample_start_target_pairs
from graph.graph_io import load_graph_json, save_graph_json, save_results_json
from graph.graph_metrics import compute_graph_metrics, save_graph_metrics
from graph.visualization import plot_graph_with_path

_ALIASES = {
    "synthetic": "graph.complex_graph_generator",
    "baseline": "graph.graph_baseline",
    "io": "graph.graph_io",
    "metrics": "graph.graph_metrics",
    "visualization": "graph.visualization",
}

for name, module_name in _ALIASES.items():
    sys.modules[f"{__name__}.{name}"] = import_module(module_name)

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
