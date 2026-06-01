import pytest

from loihi_planner.relay_controller import RelayController
from tests.test_wavefront_reference import _build_small_wavefront_graph


def test_relay_controller_block_penalize_restore():
    graph = _build_small_wavefront_graph()
    controller = RelayController(graph)

    controller.block_edge(0, 1)
    assert controller.get_graph()[0][1]["state"] == "blocked"

    controller.penalize_edge(0, 1, factor=5.0)
    assert controller.get_graph()[0][1]["state"] == "penalized"
    assert controller.get_graph()[0][1]["delay_ms"] == 5

    controller.restore_edge(0, 1)
    assert controller.get_graph()[0][1]["state"] == "normal"
    assert controller.get_graph()[0][1]["delay_ms"] == 1


def test_relay_controller_missing_edge_raises():
    graph = _build_small_wavefront_graph()
    controller = RelayController(graph)
    with pytest.raises(ValueError):
        controller.block_edge(4, 0)
