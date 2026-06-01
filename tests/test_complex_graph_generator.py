import networkx as nx
import pytest

from graph.complex_graph_generator import generate_complex_graph


@pytest.mark.parametrize(
    "graph_type",
    ["random_geometric", "small_world", "scale_free", "community"],
)
def test_complex_graph_generator_outputs_valid_digraph(graph_type):
    graph = generate_complex_graph(graph_type=graph_type, num_nodes=50, seed=7)

    assert isinstance(graph, nx.DiGraph)
    assert set(graph.nodes()) == set(range(50))
    assert nx.is_strongly_connected(graph)

    for _node, attrs in graph.nodes(data=True):
        assert isinstance(attrs["x"], float)
        assert isinstance(attrs["y"], float)
        assert isinstance(attrs["region"], int)

    for _source, _target, attrs in graph.edges(data=True):
        for key in ["distance", "base_cost", "delay_ms", "original_delay_ms", "state"]:
            assert key in attrs
        assert isinstance(attrs["delay_ms"], int)
        assert attrs["delay_ms"] > 0
        assert attrs["state"] == "normal"
