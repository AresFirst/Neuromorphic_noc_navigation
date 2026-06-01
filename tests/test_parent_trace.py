"""测试父节点追踪。

验证 infer_parent_trace_from_spikes() 在固定图上的正确性:
- 起点 parent = None
- 直连节点的 parent 正确
- 多候选时选择最早到达的前驱
"""

from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from tests.test_wavefront_reference import _build_small_wavefront_graph


def test_parent_trace_prefers_earliest_parent():
    """验证父节点追踪: 选择最早到达的候选前驱。

    脉冲时间 (由波前传播产生):
        0: 0.0ms (起点)
        1: 1.0ms (来自 0, delay=1)
        2: 3.0ms (来自 0, delay=3)
        3: 2.0ms (来自 1, delay=1: 1.0+1=2.0 < 来自 2: 3.0+1=4.0)
        4: 3.0ms (来自 3, delay=1: 2.0+1=3.0)

    预期 parent 链:
        0 → 1 (最早)
        0 → 2 (仅有一条)
        1 → 3 (1.0+1=2.0 比 3.0+1=4.0 更早)
        3 → 4
    """
    graph = _build_small_wavefront_graph()
    # 模拟波前传播的脉冲时间
    spike_times = {0: 0.0, 1: 1.0, 2: 3.0, 3: 2.0, 4: 3.0}

    parent_trace = infer_parent_trace_from_spikes(graph, spike_times, start=0)
    assert parent_trace[0] is None  # 起点无父节点
    assert parent_trace[1] == 0     # 0 最早触发 1
    assert parent_trace[2] == 0     # 0 触发 2 (delay=3)
    assert parent_trace[3] == 1     # 1 比 2 更早触发 3
    assert parent_trace[4] == 3     # 3 触发 4
