from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from graph.graph_io import load_graph_json


def _parse_path(value) -> list[int] | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, list):
        return [int(node) for node in value]
    parsed = ast.literal_eval(str(value))
    if parsed is None:
        return None
    return [int(node) for node in parsed]


def _draw_path(ax, positions, path: list[int], color: str, linestyle: str, linewidth: float, label: str) -> None:
    first = True
    for source, target in zip(path, path[1:]):
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        ax.plot(
            [x1, x2],
            [y1, y2],
            color=color,
            linestyle=linestyle,
            linewidth=linewidth,
            alpha=0.95,
            zorder=4,
            label=label if first else None,
        )
        first = False


def visualize_path_comparison(
    graph_path: str,
    results_csv: str,
    pair_id: int,
    output_path: str,
) -> None:
    graph = load_graph_json(graph_path)
    results = pd.read_csv(results_csv)
    row = results.loc[results["pair_id"] == int(pair_id)]
    if row.empty:
        raise ValueError(f"pair_id {pair_id} not found in {results_csv}")
    record = row.iloc[0].to_dict()

    snn_path = _parse_path(record.get("snn_path"))
    dijkstra_path = _parse_path(record.get("dijkstra_path"))
    if not snn_path and not dijkstra_path:
        raise ValueError(f"pair_id {pair_id} has no SNN or Dijkstra path")

    import os

    os.environ.setdefault("MPLCONFIGDIR", str(REPO_ROOT / ".matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    positions = {int(node): (float(attrs["x"]), float(attrs["y"])) for node, attrs in graph.nodes(data=True)}
    fig, ax = plt.subplots(figsize=(8, 6), dpi=180)

    snn_edges = set(zip(snn_path[:-1], snn_path[1:])) if snn_path else set()
    dijkstra_edges = set(zip(dijkstra_path[:-1], dijkstra_path[1:])) if dijkstra_path else set()
    highlighted_edges = snn_edges | dijkstra_edges

    for source, target, _attrs in graph.edges(data=True):
        source = int(source)
        target = int(target)
        if (source, target) in highlighted_edges:
            continue
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        ax.plot([x1, x2], [y1, y2], color="#9aa0a6", linewidth=0.45, alpha=0.20, zorder=1)

    overlap_edges = snn_edges & dijkstra_edges
    snn_only_path = snn_path or []
    dijkstra_only_path = dijkstra_path or []

    if dijkstra_path:
        _draw_path(ax, positions, dijkstra_only_path, "#1f77b4", "--", 2.2, "Dijkstra path")
    if snn_path:
        _draw_path(ax, positions, snn_only_path, "#d62728", "-", 2.0, "SNN wavefront path")
    for index, (source, target) in enumerate(sorted(overlap_edges)):
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        ax.plot(
            [x1, x2],
            [y1, y2],
            color="#7b3294",
            linewidth=3.2,
            alpha=0.95,
            zorder=5,
            label="overlap" if index == 0 else None,
        )

    regions = [int(graph.nodes[node].get("region", 0)) for node in graph.nodes()]
    xs = [positions[int(node)][0] for node in graph.nodes()]
    ys = [positions[int(node)][1] for node in graph.nodes()]
    ax.scatter(xs, ys, c=regions, cmap="tab10", s=16, edgecolors="white", linewidths=0.25, zorder=3)

    start = int(record["start"])
    target = int(record["target"])
    sx, sy = positions[start]
    tx, ty = positions[target]
    ax.scatter([sx], [sy], s=115, marker="s", color="#2ca02c", edgecolors="black", linewidths=0.7, zorder=6, label="start")
    ax.scatter([tx], [ty], s=145, marker="*", color="#ffbf00", edgecolors="black", linewidths=0.7, zorder=6, label="target")

    title = (
        f"Pair {pair_id}: SNN vs Dijkstra | "
        f"same_cost={record.get('same_cost')} | ratio={record.get('optimality_ratio')}"
    )
    ax.set_title(title, fontsize=10)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    ax.legend(loc="upper right", fontsize=7, frameon=True)
    fig.tight_layout(pad=0.2)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize SNN wavefront path against Dijkstra path.")
    parser.add_argument("--graph", required=True)
    parser.add_argument("--results", required=True)
    parser.add_argument("--pair-id", type=int, default=0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    visualize_path_comparison(
        graph_path=args.graph,
        results_csv=args.results,
        pair_id=args.pair_id,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
