"""MoST / Monaco SUMO Traffic Scenario 导入实验。"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dataset_import.dataset_config import load_dataset_config
from dataset_import.dataset_loader import load_public_road_dataset_as_graph
from graph.graph_io import save_graph_json, save_results_json
from graph.graph_metrics import compute_graph_metrics


def _plot_preview(G, save_path: str, max_edges: int = 8000) -> None:
    """绘制 road graph 预览图。

    大图时仅采样部分边，但节点全部保留，便于快速确认导入是否正确。
    """
    os.environ.setdefault("MPLCONFIGDIR", str(REPO_ROOT / ".matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    positions = {node: (float(attrs["x"]), float(attrs["y"])) for node, attrs in G.nodes(data=True)}
    edges = list(G.edges())
    if len(edges) > max_edges:
        rng = random.Random(0)
        edges = rng.sample(edges, max_edges)

    fig, ax = plt.subplots(figsize=(10, 8), dpi=180)
    for source, target in edges:
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        ax.plot([x1, x2], [y1, y2], color="#9aa0a6", linewidth=0.35, alpha=0.22, zorder=1)

    regions = [int(G.nodes[node].get("region", 0)) for node in G.nodes()]
    xs = [positions[node][0] for node in G.nodes()]
    ys = [positions[node][1] for node in G.nodes()]
    ax.scatter(xs, ys, c=regions, cmap="tab20", s=3.5, linewidths=0, zorder=2)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    fig.tight_layout(pad=0.2)
    output = Path(save_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import MoST SUMO network into normalized graph JSON.")
    parser.add_argument("--config", required=True, help="Path to configs/most.yaml")
    args = parser.parse_args()

    config = load_dataset_config(args.config)
    output_dir = Path(config["output"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    graph = load_public_road_dataset_as_graph(args.config)
    metrics = compute_graph_metrics(graph)
    save_graph_json(graph, config["output"]["graph_json"])
    save_results_json(metrics, config["output"]["graph_metrics_json"])
    _plot_preview(graph, config["output"]["preview_png"])

    summary = {
        "dataset_name": graph.graph.get("dataset_name"),
        "dataset_type": graph.graph.get("dataset_type"),
        "netxml_path": graph.graph.get("netxml_path"),
        "num_nodes": graph.number_of_nodes(),
        "num_edges": graph.number_of_edges(),
        "num_regions": len({int(attrs.get("region", 0)) for _, attrs in graph.nodes(data=True)}),
        "min_delay_ms": metrics.get("min_delay_ms"),
        "max_delay_ms": metrics.get("max_delay_ms"),
        "is_strongly_connected": metrics.get("is_strongly_connected"),
        "output_graph_json": config["output"]["graph_json"],
        "output_graph_metrics_json": config["output"]["graph_metrics_json"],
        "output_preview_png": config["output"]["preview_png"],
        "normalized": graph.graph.get("normalized"),
        "max_nodes": graph.graph.get("max_nodes"),
        "cropped": graph.graph.get("cropped"),
        "num_nodes_before_normalization": graph.graph.get("num_nodes_before_normalization"),
        "num_edges_before_normalization": graph.graph.get("num_edges_before_normalization"),
        "num_nodes_after_normalization": graph.graph.get("num_nodes_after_normalization"),
        "num_edges_after_normalization": graph.graph.get("num_edges_after_normalization"),
    }
    save_results_json(summary, config["output"]["import_summary_json"])
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
