"""Matplotlib visualization for the closed-loop demo."""

from __future__ import annotations

import random
from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
import networkx as nx


def _edge_path(route: list[int] | None) -> set[tuple[int, int]]:
    if not route or len(route) < 2:
        return set()
    return {(int(u), int(v)) for u, v in zip(route, route[1:])}


def draw_dynamic_state(
    G: nx.DiGraph,
    vehicle_node: int,
    target_node: int,
    current_route: list[int] | None,
    active_congested_edges: list[tuple[int, int]],
    step: int,
    save_path: str | None = None,
) -> None:
    positions = {node: (float(attrs["x"]), float(attrs["y"])) for node, attrs in G.nodes(data=True)}
    route_edges = _edge_path(current_route)
    congested_edges = {tuple(edge) for edge in active_congested_edges}

    all_edges = list(G.edges())
    normal_edges = [edge for edge in all_edges if edge not in route_edges and edge not in congested_edges]
    max_normal_edges = int(G.graph.get("max_draw_edges", 3000))
    if len(normal_edges) > max_normal_edges:
        rng = random.Random(int(step))
        normal_edges = rng.sample(normal_edges, max_normal_edges)

    fig, ax = plt.subplots(figsize=(12, 10), dpi=180)

    if normal_edges:
        nx.draw_networkx_edges(
            G,
            positions,
            edgelist=normal_edges,
            ax=ax,
            edge_color="#d1d5db",
            width=0.35,
            alpha=0.28,
            arrows=False,
        )

    if congested_edges:
        nx.draw_networkx_edges(
            G,
            positions,
            edgelist=list(congested_edges),
            ax=ax,
            edge_color="#dc2626",
            width=2.8,
            style="dashed",
            alpha=0.95,
            arrows=False,
        )

    if route_edges:
        nx.draw_networkx_edges(
            G,
            positions,
            edgelist=list(route_edges),
            ax=ax,
            edge_color="#2563eb",
            width=2.6,
            alpha=0.9,
            arrows=False,
        )

    xs = [positions[node][0] for node in G.nodes()]
    ys = [positions[node][1] for node in G.nodes()]
    ax.scatter(xs, ys, s=6, c="#6b7280", alpha=0.7, linewidths=0, zorder=3)

    if target_node in positions:
        ax.scatter(
            [positions[target_node][0]],
            [positions[target_node][1]],
            s=80,
            marker="^",
            c="#16a34a",
            edgecolors="white",
            linewidths=0.6,
            zorder=5,
        )

    if vehicle_node in positions:
        ax.scatter(
            [positions[vehicle_node][0]],
            [positions[vehicle_node][1]],
            s=90,
            marker="o",
            c="#111827",
            edgecolors="white",
            linewidths=0.7,
            zorder=6,
        )

    ax.set_title(f"Dynamic city navigation - step {int(step)}", fontsize=11)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    fig.tight_layout(pad=0.2)

    if save_path:
        output = Path(save_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, bbox_inches="tight")

    plt.close(fig)
