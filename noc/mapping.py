from __future__ import annotations

import random
from collections import defaultdict

import networkx as nx


def _num_cores(mesh_rows: int, mesh_cols: int) -> int:
    if mesh_rows <= 0 or mesh_cols <= 0:
        raise ValueError("mesh_rows and mesh_cols must be positive")
    return int(mesh_rows * mesh_cols)


def _core_from_xy(x: float, y: float, mesh_rows: int, mesh_cols: int) -> int:
    col = min(mesh_cols - 1, max(0, int(round(float(x) * (mesh_cols - 1)))))
    row = min(mesh_rows - 1, max(0, int(round(float(y) * (mesh_rows - 1)))))
    return int(row * mesh_cols + col)


def create_core_mapping(
    G: nx.DiGraph,
    mesh_rows: int,
    mesh_cols: int,
    strategy: str,
    seed: int = 0,
) -> dict[int, int]:
    num_cores = _num_cores(mesh_rows, mesh_cols)
    strategy = strategy.lower().strip()
    nodes = sorted(int(node) for node in G.nodes())

    if strategy == "random":
        rng = random.Random(seed)
        return {node: rng.randrange(num_cores) for node in nodes}

    if strategy == "topology":
        return {
            node: _core_from_xy(float(G.nodes[node]["x"]), float(G.nodes[node]["y"]), mesh_rows, mesh_cols)
            for node in nodes
        }

    if strategy == "community":
        regions: dict[int, list[int]] = defaultdict(list)
        for node in nodes:
            regions[int(G.nodes[node].get("region", 0))].append(node)

        sorted_regions = sorted(regions)
        if not sorted_regions:
            return {}

        mapping: dict[int, int] = {}
        for region_index, region in enumerate(sorted_regions):
            region_nodes = sorted(
                regions[region],
                key=lambda node: (float(G.nodes[node].get("y", 0.0)), float(G.nodes[node].get("x", 0.0)), node),
            )
            anchor_col = int(round((region_index % mesh_cols) * max(1, mesh_cols // max(1, len(sorted_regions)))))
            anchor_row = int(region_index * mesh_rows / max(1, len(sorted_regions)))
            anchor_col = min(mesh_cols - 1, max(0, anchor_col))
            anchor_row = min(mesh_rows - 1, max(0, anchor_row))

            nearby_cores = sorted(
                range(num_cores),
                key=lambda core: (
                    abs(core // mesh_cols - anchor_row) + abs(core % mesh_cols - anchor_col),
                    core,
                ),
            )
            for idx, node in enumerate(region_nodes):
                mapping[node] = nearby_cores[idx % len(nearby_cores)]
        return mapping

    raise ValueError("strategy must be one of: random, community, topology")
