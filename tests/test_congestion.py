"""Tests for congestion events and controller."""

from __future__ import annotations

import networkx as nx

from nmn.dynamic.congestion import CongestionController, CongestionEvent


def _build_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    for node in range(3):
        graph.add_node(node, x=float(node), y=0.0, region=0)
    graph.add_edge(0, 1, delay_ms=2, original_delay_ms=2, state="normal")
    graph.add_edge(1, 2, delay_ms=3, original_delay_ms=3, state="normal")
    return graph


def test_delay_mode_updates_and_restores_delay():
    controller = CongestionController(_build_graph())
    controller.add_event(CongestionEvent(0, 1, start_step=1, end_step=3, delay_factor=5.0, mode="delay"))

    result0 = controller.update(0)
    assert result0["active_edges"] == []
    assert controller.get_graph()[0][1]["delay_ms"] == 2

    result1 = controller.update(1)
    assert result1["activated_edges"] == [(0, 1)]
    assert controller.get_graph()[0][1]["delay_ms"] == 10
    assert controller.get_graph()[0][1]["state"] == "congested"

    result2 = controller.update(2)
    assert controller.get_graph()[0][1]["delay_ms"] == 10
    assert result2["active_edges"] == [(0, 1)]

    result3 = controller.update(3)
    assert result3["deactivated_edges"] == [(0, 1)]
    assert controller.get_graph()[0][1]["delay_ms"] == 2
    assert controller.get_graph()[0][1]["state"] == "normal"


def test_blocked_mode_sets_and_clears_state():
    controller = CongestionController(_build_graph())
    controller.add_event(CongestionEvent(0, 1, start_step=1, end_step=2, mode="blocked"))

    controller.update(1)
    assert controller.get_graph()[0][1]["state"] == "blocked"

    controller.update(2)
    assert controller.get_graph()[0][1]["state"] == "normal"


def test_multiple_updates_do_not_cascade_delay():
    controller = CongestionController(_build_graph())
    controller.add_event(CongestionEvent(0, 1, start_step=1, end_step=4, delay_factor=4.0, mode="delay"))

    controller.update(1)
    assert controller.get_graph()[0][1]["delay_ms"] == 8

    controller.update(2)
    assert controller.get_graph()[0][1]["delay_ms"] == 8
