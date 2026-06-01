import pytest

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.wavefront_reference import event_driven_wavefront
from tests.test_wavefront_reference import _build_small_wavefront_graph


def test_loihi_wavefront_matches_reference_when_backend_available():
    status = check_brian2loihi_available()
    if not status["available"]:
        pytest.skip(f"Brian2Loihi unavailable: {status['error']}")

    graph = _build_small_wavefront_graph()
    reference = event_driven_wavefront(graph, 0, 4)
    result = run_loihi_wavefront(graph, 0, 4, threshold=1.0, weight=1.1, refractory_ms=1000, seed=0)

    assert result["success"]
    assert result["target_arrival_time_ms"] is not None
    assert abs(result["target_arrival_time_ms"] - reference["target_arrival_time"]) <= 1.0
