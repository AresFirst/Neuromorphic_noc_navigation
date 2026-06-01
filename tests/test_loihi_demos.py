"""测试三个 Loihi 验证 Demo。

如果 Brian2Loihi 可用，验证三个基础 demo 均成功:
- LIF demo: 单神经元正常发放
- delay demo: 突触延迟准确 (5ms ± 1ms)
- small wavefront demo: 目标在预期时间到达 (3ms ± 1ms)

如果后端不可用，所有测试通过 pytest.skip() 跳过。
"""

import pytest

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_delay_demo import run_loihi_delay_demo
from loihi_planner.loihi_lif_demo import run_loihi_lif_demo
from loihi_planner.loihi_small_wavefront_demo import run_loihi_small_wavefront_demo


def _require_brian2loihi():
    """如果 Brian2Loihi 不可用，跳过当前测试。"""
    status = check_brian2loihi_available()
    if not status["available"]:
        pytest.skip(f"Brian2Loihi unavailable: {status['error']}")


def test_loihi_lif_demo_spikes_when_backend_available():
    """验证 LIF demo: 至少 1 个脉冲、success=True。"""
    _require_brian2loihi()
    result = run_loihi_lif_demo()
    assert result["success"]
    assert result["num_spikes"] >= 1


def test_loihi_delay_demo_observes_integer_delay_when_backend_available():
    """验证 delay demo: 观察延迟 = 5ms ± 1ms。"""
    _require_brian2loihi()
    result = run_loihi_delay_demo(delay_ms=5)
    assert result["success"]
    assert abs(result["observed_delay_ms"] - 5.0) <= 1.0


def test_loihi_small_wavefront_arrival_when_backend_available():
    """验证 small wavefront demo: 目标到达时间 = 3ms ± 1ms。"""
    _require_brian2loihi()
    result = run_loihi_small_wavefront_demo()
    assert result["success"]
    assert abs(result["target_arrival_time_ms"] - 3.0) <= 1.0
