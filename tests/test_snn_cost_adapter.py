"""Tests for graph adaptation before SNN planning."""

from __future__ import annotations

import networkx as nx

from nmn.dynamic.snn_cost_adapter import prepare_graph_for_snn_planning


def _build_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    graph.add_node(0, x=0.0, y=0.0, region=0)
    graph.add_node(1, x=1.0, y=0.0, region=0, threshold_penalty=2.5)
    graph.add_node(2, x=2.0, y=0.0, region=0)
    graph.add_edge(0, 1, delay_ms=4, original_delay_ms=4, state="blocked")
    graph.add_edge(1, 2, delay_ms=12, original_delay_ms=3, state="congested")
    return graph


def test_adapter_preserves_blocked_edges_and_does_not_mutate_input():
    graph = _build_graph()
    prepared = prepare_graph_for_snn_planning(graph)

    assert prepared is not graph
    assert prepared[0][1]["state"] == "blocked"
    assert isinstance(prepared[0][1]["delay_ms"], int)
    assert prepared[0][1]["delay_ms"] > 0
    assert isinstance(prepared[1][2]["delay_ms"], int)
    assert prepared[1][2]["delay_ms"] == 12
    assert prepared.nodes[1]["threshold_penalty"] == 2.5

    assert graph[0][1]["state"] == "blocked"
    assert graph[1][2]["delay_ms"] == 12
    assert graph.nodes[1]["threshold_penalty"] == 2.5
