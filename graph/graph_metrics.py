from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mean, pstdev

import networkx as nx

from .graph_io import save_results_json


def _safe_mean(values):
    return float(mean(values)) if values else None


def _safe_pstdev(values):
    return float(pstdev(values)) if len(values) > 1 else 0.0 if values else None


def compute_graph_metrics(G) -> dict:
    num_nodes = G.number_of_nodes()
    num_edges = G.number_of_edges()
    out_degrees = [degree for _, degree in G.out_degree()]
    in_degrees = [degree for _, degree in G.in_degree()]
    distances = [float(attrs.get("distance", 0.0)) for _, _, attrs in G.edges(data=True)]
    base_costs = [float(attrs.get("base_cost", 0.0)) for _, _, attrs in G.edges(data=True)]
    delays = [int(attrs.get("delay_ms", 0)) for _, _, attrs in G.edges(data=True)]
    regions = Counter(int(attrs.get("region", 0)) for _, attrs in G.nodes(data=True))

    metrics = {
        "graph_type": G.graph.get("graph_type"),
        "seed": G.graph.get("seed"),
        "num_nodes": num_nodes,
        "num_edges": num_edges,
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
    metrics = compute_graph_metrics(G)
    save_results_json(metrics, path)
    return metrics
