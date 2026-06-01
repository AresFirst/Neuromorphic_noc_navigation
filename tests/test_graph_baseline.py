"""测试 Dijkstra 基线算法。

验证 Dijkstra 最短路径、延迟路径、起止点采样和批量评估的功能。
"""

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import (
    dijkstra_delay_path,
    dijkstra_path,
    evaluate_dijkstra_pairs,
    sample_start_target_pairs,
)


def test_dijkstra_path_start_target_and_pairs():
    """验证 Dijkstra 路径、延迟路径、采样和评估。

    测试场景: 50 节点的 small_world 图。

    验证:
    - dijkstra_path: 从 0→25 有路径，头尾正确
    - dijkstra_delay_path: 延迟路径代价 ≥ 1.0 (边延迟最小 1ms)
    - sample_start_target_pairs: 采样 6 对，起止点不重复
    - evaluate_dijkstra_pairs: 返回正确列的 DataFrame, 全部成功
    """
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
