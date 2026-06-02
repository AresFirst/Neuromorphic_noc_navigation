"""道路图标准化测试。"""

from __future__ import annotations

import networkx as nx
import pytest

from dataset_import.road_graph_normalizer import normalize_road_graph


def _make_raw_graph(num_nodes: int = 6) -> nx.DiGraph:
    graph = nx.DiGraph()
    for idx in range(num_nodes):
        graph.add_node(
            f"J{idx}",
            x=float(idx * 10),
            y=float(idx % 2 * 5),
            source="most_raw",
            original_id=f"J{idx}",
        )
    for idx in range(num_nodes):
        nxt = (idx + 1) % num_nodes
        graph.add_edge(
            f"J{idx}",
            f"J{nxt}",
            distance=float(10 + idx),
            base_cost=float(1 + idx),
            source="most_raw",
            original_edge_id=f"e{idx}",
        )
        graph.add_edge(
            f"J{nxt}",
            f"J{idx}",
            distance=float(10 + idx),
            base_cost=float(1 + idx),
            source="most_raw",
            original_edge_id=f"er{idx}",
        )
    graph.add_node("isolated", x=999.0, y=999.0, source="most_raw", original_id="isolated")
    return graph


def test_normalize_road_graph_outputs_required_attrs_and_regions():
    raw = _make_raw_graph(4)
    normalized = normalize_road_graph(
        raw,
        min_delay_ms=1,
        max_delay_ms=10,
        largest_strongly_connected_component=True,
        max_nodes=None,
        region_method="spatial_grid",
        region_grid_rows=2,
        region_grid_cols=2,
        seed=0,
        source="most",
    )

    assert normalized.graph["dataset_name"] == "MoST"
    assert normalized.graph["normalized"] is True
    assert normalized.graph["num_nodes_before_normalization"] == raw.number_of_nodes()
    assert normalized.graph["num_edges_before_normalization"] == raw.number_of_edges()
    assert normalized.number_of_nodes() >= 2

    for _, attrs in normalized.nodes(data=True):
        assert set(["x", "y", "region", "source", "original_id"]).issubset(attrs.keys())
        assert attrs["source"] == "most"
        assert isinstance(attrs["region"], int)

    for _, _, attrs in normalized.edges(data=True):
        assert set(
            ["distance", "base_cost", "delay_ms", "original_delay_ms", "state", "source", "original_edge_id"]
        ).issubset(attrs.keys())
        assert isinstance(attrs["delay_ms"], int)
        assert attrs["delay_ms"] > 0
        assert attrs["original_delay_ms"] == attrs["delay_ms"]
        assert attrs["state"] == "normal"
        assert attrs["source"] == "most"
        assert attrs["distance"] > 0
        assert attrs["base_cost"] > 0


def test_normalize_road_graph_respects_max_nodes():
    raw = _make_raw_graph(10)
    normalized = normalize_road_graph(
        raw,
        max_nodes=4,
        largest_strongly_connected_component=True,
        region_method="spatial_grid",
        region_grid_rows=2,
        region_grid_cols=2,
        seed=3,
    )
    assert normalized.number_of_nodes() <= 4
    assert normalized.number_of_nodes() >= 2
