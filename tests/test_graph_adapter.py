"""Tests for OSMnx graph adaptation."""

from __future__ import annotations

import networkx as nx

from maps import osmnx_multidigraph_to_digraph, path_nodes_to_latlon


def _parallel_osm_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(1001, x=139.7000, y=35.6900)
    graph.add_node(1002, x=139.7010, y=35.6910)
    graph.add_node(1003, x=139.7020, y=35.6920)
    graph.add_edge(1001, 1002, key=0, length=50.0, travel_time=8.0)
    graph.add_edge(1001, 1002, key=1, length=30.0, travel_time=4.0, snn_synapse_index=42)
    graph.add_edge(1002, 1003, key=0, length=20.0)
    return graph


def test_multidigraph_to_digraph_merges_parallel_edges_by_min_cost():
    graph = osmnx_multidigraph_to_digraph(_parallel_osm_graph())

    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 2
    assert graph.has_edge(0, 1)
    assert graph[0][1]["cost"] == 4.0
    assert graph[0][1]["length"] == 30.0
    assert graph[0][1]["snn_synapse_index"] == 42


def test_node_id_and_neuron_index_mapping_is_reversible():
    graph = osmnx_multidigraph_to_digraph(_parallel_osm_graph())

    assert graph.nodes[0]["original_osm_node_id"] == 1001
    assert graph.nodes[0]["snn_neuron_index"] == 0
    assert graph.graph["osm_node_id_to_node_id"][1002] == 1
    assert graph.graph["node_id_to_osm_id"][2] == 1003
    assert graph.graph["neuron_index_to_node_id"][1] == 1


def test_path_nodes_map_back_to_latlon_points():
    graph = osmnx_multidigraph_to_digraph(_parallel_osm_graph())
    points = path_nodes_to_latlon(graph, [0, 1, 2])

    assert points[0] == (35.6900, 139.7000)
    assert points[-1] == (35.6920, 139.7020)
    assert len(points) == 3


def test_cost_falls_back_to_length_then_default():
    graph = nx.MultiDiGraph()
    graph.add_node("a", x=0.0, y=0.0)
    graph.add_node("b", x=1.0, y=1.0)
    graph.add_node("c", x=2.0, y=2.0)
    graph.add_edge("a", "b", length="12.5")
    graph.add_edge("b", "c")

    adapted = osmnx_multidigraph_to_digraph(graph)

    assert adapted[0][1]["cost"] == 12.5
    assert adapted[0][1]["travel_time"] == 12.5
    assert adapted[1][2]["cost"] == 1.0
    assert adapted[1][2]["length"] == 1.0


def test_delay_ms_is_capped_for_loihi_but_cost_is_preserved():
    graph = nx.MultiDiGraph()
    graph.add_node("a", x=0.0, y=0.0)
    graph.add_node("b", x=1.0, y=1.0)
    graph.add_edge("a", "b", travel_time=120.0, length=500.0)

    adapted = osmnx_multidigraph_to_digraph(graph)

    assert adapted[0][1]["cost"] == 120.0
    assert adapted[0][1]["raw_delay_ms"] == 120
    assert adapted[0][1]["delay_ms"] == 62
    assert adapted.graph["delay_encoding"]["max_ms"] == 62
