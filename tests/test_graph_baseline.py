from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import (
    dijkstra_delay_path,
    dijkstra_path,
    evaluate_dijkstra_pairs,
    sample_start_target_pairs,
)


def test_dijkstra_path_start_target_and_pairs():
    graph = generate_complex_graph("small_world", 50, seed=11)
    path, cost = dijkstra_path(graph, 0, 25)

    assert path[0] == 0
    assert path[-1] == 25
    assert cost >= 0.0

    delay_path, delay_cost = dijkstra_delay_path(graph, 0, 25)
    assert delay_path[0] == 0
    assert delay_path[-1] == 25
    assert delay_cost >= 1.0

    pairs = sample_start_target_pairs(graph, 6, seed=3)
    assert len(pairs) == 6
    assert all(start != target for start, target in pairs)

    results = evaluate_dijkstra_pairs(graph, pairs)
    assert list(results.columns) == ["start", "target", "path", "path_cost", "num_hops", "success", "error"]
    assert results["success"].all()
