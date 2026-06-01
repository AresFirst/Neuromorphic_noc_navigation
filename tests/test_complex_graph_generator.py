"""测试复杂图生成器。

对 4 种拓扑类型分别验证:
- 返回的是合法的 NetworkX DiGraph
- 节点数和节点 ID 正确
- 强连通性保证
- 节点和边的属性结构完整
"""

import networkx as nx
import pytest

from graph.complex_graph_generator import generate_complex_graph


@pytest.mark.parametrize(
    "graph_type",
    ["random_geometric", "small_world", "scale_free", "community"],
)
def test_complex_graph_generator_outputs_valid_digraph(graph_type):
    """对每种拓扑类型验证生成的图满足结构契约。

    验证点:
    1. 返回类型是 DiGraph
    2. 节点集合 = {0, 1, ..., 49}
    3. 图是强连通的 (ensure_strongly_connected=True)
    4. 所有节点有 x(float), y(float), region(int) 属性
    5. 所有边有 distance, base_cost, delay_ms, original_delay_ms, state 属性
    6. delay_ms > 0, state = "normal"
    """
    graph = generate_complex_graph(graph_type=graph_type, num_nodes=50, seed=7)

    assert isinstance(graph, nx.DiGraph)
    assert set(graph.nodes()) == set(range(50))
    assert nx.is_strongly_connected(graph)

    # 节点属性检查
    for _node, attrs in graph.nodes(data=True):
        assert isinstance(attrs["x"], float)
        assert isinstance(attrs["y"], float)
        assert isinstance(attrs["region"], int)

    # 边属性检查
    for _source, _target, attrs in graph.edges(data=True):
        for key in ["distance", "base_cost", "delay_ms", "original_delay_ms", "state"]:
            assert key in attrs
        assert isinstance(attrs["delay_ms"], int)
        assert attrs["delay_ms"] > 0
        assert attrs["state"] == "normal"
