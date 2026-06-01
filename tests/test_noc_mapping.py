from graph.complex_graph_generator import generate_complex_graph
from noc.mapping import create_core_mapping


def test_random_mapping_is_reproducible_for_same_seed():
    graph = generate_complex_graph("community", 30, seed=1)
    first = create_core_mapping(graph, 4, 4, "random", seed=9)
    second = create_core_mapping(graph, 4, 4, "random", seed=9)
    assert first == second


def test_topology_mapping_outputs_valid_core_ids():
    graph = generate_complex_graph("random_geometric", 30, seed=2)
    mapping = create_core_mapping(graph, 4, 4, "topology", seed=0)
    assert set(mapping) == set(graph.nodes())
    assert all(0 <= core < 16 for core in mapping.values())
