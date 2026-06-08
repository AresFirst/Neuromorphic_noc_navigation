"""Tests for GUI-side route status helpers."""

from __future__ import annotations

import networkx as nx

from gui.app import _reachability_status


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
