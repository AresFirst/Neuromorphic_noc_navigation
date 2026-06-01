import pytest

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_io import load_graph_json, save_graph_json, save_results_json


def test_graph_json_round_trip_preserves_structure_and_attrs(tmp_path):
    graph = generate_complex_graph("random_geometric", 20, seed=5)
    path = tmp_path / "graph.json"
    save_graph_json(graph, str(path))

    loaded = load_graph_json(str(path))
    assert loaded.number_of_nodes() == graph.number_of_nodes()
    assert loaded.number_of_edges() == graph.number_of_edges()

    node = 0
    for key in ["x", "y", "region"]:
        assert loaded.nodes[node][key] == pytest.approx(graph.nodes[node][key])

    source, target = next(iter(graph.edges()))
    for key in ["distance", "base_cost"]:
        assert loaded[source][target][key] == pytest.approx(graph[source][target][key])
    for key in ["delay_ms", "original_delay_ms", "state"]:
        assert loaded[source][target][key] == graph[source][target][key]


def test_save_results_json(tmp_path):
    path = tmp_path / "result.json"
    save_results_json({"ok": True, "value": 3}, str(path))
    assert path.exists()
    assert '"ok": true' in path.read_text(encoding="utf-8")
