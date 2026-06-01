"""测试 STDP 分析和路径对比。

验证:
1. STDP trace 正确标记 parent edge (weight=1.0) 和非 parent edge (weight=0.0)
2. 在 30 节点 community 图上，CPU 参考波前 + parent 追踪 + 路径重建
   的结果与 Dijkstra 最优路径一致 (optimality_ratio ≈ 1.0)
"""

import math

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import dijkstra_delay_path, sample_start_target_pairs
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compare_snn_path_with_dijkstra
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from loihi_planner.stdp_trace import build_stdp_trace_table
from loihi_planner.wavefront_reference import event_driven_wavefront
from tests.test_wavefront_reference import _build_small_wavefront_graph


def test_stdp_trace_weights_mark_parent_edges():
    """验证 STDP 权重: parent edge → 1.0, 非 parent edge → 0.0。

    使用 5 节点固定图:
        parent 链: 0→1→3→4 (这些边 weight=1.0)
        非 parent: 0→2, 2→3 (weight=0.0)
    """
    graph = _build_small_wavefront_graph()
    spike_times = {0: 0.0, 1: 1.0, 2: 3.0, 3: 2.0, 4: 3.0}
    parent_trace = infer_parent_trace_from_spikes(graph, spike_times, start=0)
    stdp_df = build_stdp_trace_table(graph, parent_trace, spike_times)

    # 边 3→4: parent chain → weight=1.0
    parent_row = stdp_df[(stdp_df["pre"] == 3) & (stdp_df["post"] == 4)].iloc[0]
    assert parent_row["stdp_weight"] == 1.0
    # 边 2→3: 非 parent chain (1 更早到达 3) → weight=0.0
    non_parent_row = stdp_df[(stdp_df["pre"] == 2) & (stdp_df["post"] == 3)].iloc[0]
    assert non_parent_row["stdp_weight"] == 0.0


def test_snn_path_matches_dijkstra_on_30_node_complex_graph():
    """验证: 在 30 节点 community 图上，CPU 参考波前 + 父节点追踪
    重建的路径与 Dijkstra 一致 (same_cost=True, optimality_ratio=1.0)。

    这里使用 CPU 参考波前 (event_driven_wavefront) 代替 SNN，
    因为测试可能在没有 Loihi 后端的环境中运行。
    """
    graph = generate_complex_graph("community", 30, seed=9)
    pairs = sample_start_target_pairs(graph, 10, seed=4)

    ratios = []
    for start, target in pairs:
        # 步骤 1: CPU 参考波前 (真值)
        reference = event_driven_wavefront(graph, start, target, delay_attr="delay_ms")
        # 步骤 2: 从到达时间推断父节点
        parent_trace = infer_parent_trace_from_spikes(
            graph, reference["arrival_times"], start, delay_attr="delay_ms"
        )
        # 步骤 3: 沿父链重建路径
        snn_path = reconstruct_path_from_parent(parent_trace, start, target)
        # 步骤 4: Dijkstra 最优路径
        dijkstra_path, _ = dijkstra_delay_path(graph, start, target, delay_attr="delay_ms")
        # 步骤 5: 对比
        compare = compare_snn_path_with_dijkstra(graph, snn_path, dijkstra_path, weight="delay_ms")
        assert compare["same_cost"]
        assert math.isclose(compare["optimality_ratio"], 1.0, rel_tol=1e-9, abs_tol=1e-9)
        ratios.append(compare["optimality_ratio"])

    # 10 对全部测试完成
    assert len(ratios) == 10
