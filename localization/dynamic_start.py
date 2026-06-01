from __future__ import annotations

import networkx as nx

from .place_cells import PlaceCellLayer


def estimate_start_node_from_position(
    G: nx.DiGraph,
    x: float,
    y: float,
    sigma: float = 0.1,
) -> int:
    node_positions = {
        int(node): (float(attrs["x"]), float(attrs["y"]))
        for node, attrs in G.nodes(data=True)
    }
    layer = PlaceCellLayer(node_positions, sigma=sigma)
    start = layer.winner_take_all(x, y)
    if start not in G:
        raise ValueError("estimated start node is not in graph")
    return start
