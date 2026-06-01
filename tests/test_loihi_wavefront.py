"""测试 Loihi SNN 波前路由与参考算法的一致性。

在 5 节点小图上验证 run_loihi_wavefront() 的输出
与 event_driven_wavefront() (CPU 真值) 的到达时间一致 (误差 ≤ 1ms)。

如果 Brian2Loihi 不可用，测试通过 pytest.skip() 跳过。
"""

import pytest

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.wavefront_reference import event_driven_wavefront
from tests.test_wavefront_reference import _build_small_wavefront_graph


def test_loihi_wavefront_matches_reference_when_backend_available():
    """验证 Loihi SNN 波前与 CPU 参考算法的到达时间一致性。

    使用 5 节点固定图 (与 small_wavefront_demo 相同):
        0→1→3→4, 到达时间 = 3ms

    误差容差: ≤ 1.0 ms。
    """
    status = check_brian2loihi_available()
    if not status["available"]:
        pytest.skip(f"Brian2Loihi unavailable: {status['error']}")

    graph = _build_small_wavefront_graph()
    reference = event_driven_wavefront(graph, 0, 4)
    result = run_loihi_wavefront(
        graph, 0, 4, threshold=1.0, weight=1.1, refractory_ms=1000, seed=0
    )

    assert result["success"]
    assert result["target_arrival_time_ms"] is not None
    # Loihi 波前到达时间应在参考值 ±1ms 内
    assert abs(result["target_arrival_time_ms"] - reference["target_arrival_time"]) <= 1.0
