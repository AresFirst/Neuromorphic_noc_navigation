"""测试图 JSON 序列化/反序列化。

验证 save_graph_json → load_graph_json 的往返一致性：
节点数、边数、节点/边属性在序列化前后应保持一致。
"""

import pytest

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_io import load_graph_json, save_graph_json, save_results_json


def test_graph_json_round_trip_preserves_structure_and_attrs(tmp_path):
    """验证图 JSON 往返: 结构(节点/边数)和属性(坐标/延迟/代价)完全保留。

    tmp_path: pytest 提供的临时目录 fixture。
    """
    graph = generate_complex_graph("random_geometric", 20, seed=5)
    source, target = next(iter(graph.edges()))
    graph[source][target]["source"] = "most"
    path = tmp_path / "graph.json"
    save_graph_json(graph, str(path))

    # 加载还原
    loaded = load_graph_json(str(path))
    assert loaded.number_of_nodes() == graph.number_of_nodes()
    assert loaded.number_of_edges() == graph.number_of_edges()

    # 节点属性一致性
    node = 0
    for key in ["x", "y", "region"]:
        assert loaded.nodes[node][key] == pytest.approx(graph.nodes[node][key])

    # 边属性一致性（抽查第一条边）
    source, target = next(iter(graph.edges()))
    for key in ["distance", "base_cost"]:
        assert loaded[source][target][key] == pytest.approx(graph[source][target][key])
    for key in ["delay_ms", "original_delay_ms", "state"]:
        assert loaded[source][target][key] == graph[source][target][key]
    assert loaded[source][target]["source"] == "most"


def test_save_results_json(tmp_path):
    """验证通用 JSON 结果保存: 文件被创建且内容正确。"""
    path = tmp_path / "result.json"
    save_results_json({"ok": True, "value": 3}, str(path))
    assert path.exists()
    assert '"ok": true' in path.read_text(encoding="utf-8")
