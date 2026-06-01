import pytest

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_delay_demo import run_loihi_delay_demo
from loihi_planner.loihi_lif_demo import run_loihi_lif_demo
from loihi_planner.loihi_small_wavefront_demo import run_loihi_small_wavefront_demo


def _require_brian2loihi():
    status = check_brian2loihi_available()
    if not status["available"]:
        pytest.skip(f"Brian2Loihi unavailable: {status['error']}")


def test_loihi_lif_demo_spikes_when_backend_available():
    _require_brian2loihi()
    result = run_loihi_lif_demo()
    assert result["success"]
    assert result["num_spikes"] >= 1


def test_loihi_delay_demo_observes_integer_delay_when_backend_available():
    _require_brian2loihi()
    result = run_loihi_delay_demo(delay_ms=5)
    assert result["success"]
    assert abs(result["observed_delay_ms"] - 5.0) <= 1.0


def test_loihi_small_wavefront_arrival_when_backend_available():
    _require_brian2loihi()
    result = run_loihi_small_wavefront_demo()
    assert result["success"]
    assert abs(result["target_arrival_time_ms"] - 3.0) <= 1.0
