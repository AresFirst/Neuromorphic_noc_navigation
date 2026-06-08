"""Tests for GUI-side route status helpers."""

from __future__ import annotations

import networkx as nx

from gui.app import (
    _wavefront_frame_at_time,
    _wavefront_inflight_edges_at_time,
    _wavefront_time_limit,
    _reachability_status,
)
from navigation import NavigationResult, WavefrontFrame


def test_reachability_status_detects_reverse_only_route():
    graph = nx.DiGraph()
    graph.add_edge(1, 0)
    graph.add_edge(0, 2)

    reachable, message = _reachability_status(graph, 0, 1)

    assert reachable is False
    assert "reverse direction is reachable" in message


def test_reachability_status_accepts_directed_route():
    graph = nx.DiGraph()
    graph.add_edge(0, 1)

    reachable, message = _reachability_status(graph, 0, 1)

    assert reachable is True
    assert "directed route exists" in message


def test_wavefront_frame_at_arbitrary_timestep():
    graph = nx.DiGraph()
    graph.add_edge(0, 1, delay_ms=2)
    graph.add_edge(1, 2, delay_ms=2)
    result = NavigationResult(
        start_node=0,
        goal_node=2,
        path_nodes=[0, 1, 2],
        path_edges=[(0, 1), (1, 2)],
        wavefront_frames=[
            WavefrontFrame(t=0, active_nodes=[0], active_edges=[]),
            WavefrontFrame(t=2, active_nodes=[0, 1], active_edges=[(0, 1)]),
            WavefrontFrame(t=4, active_nodes=[0, 1, 2], active_edges=[(0, 1), (1, 2)]),
        ],
        metadata={"spike_times_by_node": {0: 0.0, 1: 2.0, 2: 4.0}, "wavefront_time_max_ms": 4},
    )

    frame = _wavefront_frame_at_time(graph, result, 3)

    assert frame.t == 3
    assert frame.active_nodes == [0, 1]
    assert frame.active_edges == [(0, 1)]
    assert _wavefront_inflight_edges_at_time(graph, result, 3) == [(1, 2)]
    assert _wavefront_time_limit(result) == 4
