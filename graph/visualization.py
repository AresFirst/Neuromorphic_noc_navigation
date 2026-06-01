from __future__ import annotations

import os
from pathlib import Path

mpl_cache_dir = Path(__file__).resolve().parents[1] / ".matplotlib-cache"
mpl_cache_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache_dir))

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt


def plot_graph_with_path(
    G,
    path: list[int] | None,
    save_path: str,
    title: str | None = None,
) -> None:
    positions = {node: (float(attrs["x"]), float(attrs["y"])) for node, attrs in G.nodes(data=True)}
    fig, ax = plt.subplots(figsize=(8, 6), dpi=180)

    path_edges = set(zip(path[:-1], path[1:])) if path and len(path) >= 2 else set()
    for source, target, _attrs in G.edges(data=True):
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        if (source, target) in path_edges:
            ax.plot([x1, x2], [y1, y2], color="#d62728", linewidth=2.4, alpha=0.95, zorder=2)
        else:
            ax.plot([x1, x2], [y1, y2], color="#9aa0a6", linewidth=0.5, alpha=0.25, zorder=1)

    regions = [int(G.nodes[node].get("region", 0)) for node in G.nodes()]
    xs = [positions[node][0] for node in G.nodes()]
    ys = [positions[node][1] for node in G.nodes()]
    ax.scatter(xs, ys, c=regions, cmap="tab10", s=18, edgecolors="white", linewidths=0.3, zorder=3)

    if path:
        start = path[0]
        target = path[-1]
        sx, sy = positions[start]
        tx, ty = positions[target]
        ax.scatter([sx], [sy], s=110, marker="s", color="#2ca02c", edgecolors="black", linewidths=0.7, zorder=4)
        ax.scatter([tx], [ty], s=135, marker="*", color="#ffbf00", edgecolors="black", linewidths=0.7, zorder=4)

    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=11)
    fig.tight_layout(pad=0.2)

    output = Path(save_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
