"""测试 CPU 参考波前算法。

验证 event_driven_wavefront() 的路径正确性和阻塞边处理。

测试图 (与 loihi_small_wavefront_demo 相同):
    0 → 1 (delay=1)
    0 → 2 (delay=3)
    1 → 3 (delay=1)
    2 → 3 (delay=1)
    3 → 4 (delay=1)

最短路径: 0→1→3→4, delay = 1+1+1 = 3ms
"""

import networkx as nx

from loihi_planner.wavefront_reference import event_driven_wavefront


def _build_small_wavefront_graph() -> nx.DiGraph:
    """构建 5 节点固定测试图。

    Returns:
        DiGraph，边延迟见 docstring。
    """
    G = nx.DiGraph()
    for node in range(5):
        G.add_node(node, x=float(node), y=float(node), region=0)
    edges = [
        (0, 1, 1),  # delay=1ms
        (0, 2, 3),  # delay=3ms
        (1, 3, 1),
        (2, 3, 1),
        (3, 4, 1),
    ]
    for source, target, delay in edges:
        G.add_edge(source, target,
                   delay_ms=int(delay), base_cost=float(delay),
                   original_delay_ms=int(delay), state="normal", distance=float(delay))
    return G


def test_reference_wavefront_reaches_target_at_3_ms():
    """验证: 最短路径 0→1→3→4, 到达时间 = 1+1+1 = 3ms。

    起点 0 在 t=0 到达自身。
    """
    graph = _build_small_wavefront_graph()
    result = event_driven_wavefront(graph, 0, 4)

    assert result["target_arrival_time"] == 3.0
    assert result["arrival_times"][0] == 0.0  # 起点自身
    assert result["arrival_times"][4] == 3.0  # 目标到达时间
    assert result["visited_order"][0] == 0    # 首先访问起点


def test_reference_wavefront_skips_blocked_edges():
    """验证: state="blocked" 的边被正确跳过。

    测试图: 0→1 被阻塞，波前必须绕行 0→2→1，总延迟 = 2+1 = 3ms。
    """
    graph = nx.DiGraph()
    for node in range(3):
        graph.add_node(node, x=float(node), y=float(node), region=0)
    # 0→1 阻塞
    graph.add_edge(0, 1, delay_ms=1, base_cost=1.0, original_delay_ms=1, state="blocked", distance=1.0)
    # 替代路径: 0→2→1
    graph.add_edge(0, 2, delay_ms=2, base_cost=2.0, original_delay_ms=2, state="normal", distance=2.0)
    graph.add_edge(2, 1, delay_ms=1, base_cost=1.0, original_delay_ms=1, state="normal", distance=1.0)

    result = event_driven_wavefront(graph, 0, 1)
    # 绕过阻塞边: t=0 + 2(delay 0→2) + 1(delay 2→1) = 3ms
    assert result["target_arrival_time"] == 3.0
    assert result["arrival_times"][1] == 3.0
