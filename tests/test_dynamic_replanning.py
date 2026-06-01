import pytest

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.dynamic_replanning import replan_from_position
from loihi_planner.relay_controller import RelayController
from tests.test_wavefront_reference import _build_small_wavefront_graph


def _skip_if_no_backend():
    status = check_brian2loihi_available()
    if not status["available"]:
        pytest.skip(f"Brian2Loihi unavailable: {status['error']}")


def test_replan_from_position_estimated_start_is_graph_node():
    _skip_if_no_backend()
    graph = _build_small_wavefront_graph()
    result = replan_from_position(graph, 0.0, 0.0, target=4)

    assert result["estimated_start"] in graph.nodes()
    assert result["success"]


def test_blocked_edge_not_in_replanned_path():
    _skip_if_no_backend()
    graph = _build_small_wavefront_graph()
    controller = RelayController(graph)
    controller.block_edge(0, 1)
    result = replan_from_position(controller.get_graph(), 0.0, 0.0, target=4)

    assert result["success"]
    assert (0, 1) not in set(zip(result["path"], result["path"][1:]))
