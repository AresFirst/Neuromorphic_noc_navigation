"""Tests for the replanning policy."""

from __future__ import annotations

import networkx as nx

from nmn.dynamic.replanning_policy import ReplanningPolicy


def _build_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    for node in range(6):
        graph.add_node(node, x=float(node), y=0.0, region=0)
    graph.add_edge(0, 1, delay_ms=1, state="normal")
    graph.add_edge(1, 2, delay_ms=1, state="normal")
    graph.add_edge(2, 5, delay_ms=1, state="normal")
    return graph


def test_policy_triggers_on_initial_step_and_interval():
    policy = ReplanningPolicy(replan_interval=5)
    graph = _build_graph()
    route = [0, 1, 2, 5]
    vehicle_state = {"current_node": 0, "route_index": 0, "arrived": False}

    should_replan, reason = policy.should_replan(0, vehicle_state, route, [], graph)
    assert should_replan is True
    assert reason == "initial_plan"

    should_replan, reason = policy.should_replan(5, vehicle_state, route, [], graph)
    assert should_replan is True
    assert reason == "replan_interval"


def test_policy_triggers_on_route_hazards_and_arrival():
    policy = ReplanningPolicy(replan_interval=5)
    graph = _build_graph()
    route = [0, 1, 2, 5]
    vehicle_state = {"current_node": 1, "route_index": 1, "arrived": False}

    graph[1][2]["state"] = "congested"
    should_replan, reason = policy.should_replan(1, vehicle_state, route, [(1, 2)], graph)
    assert should_replan is True
    assert reason == "blocked_edge_on_route" or reason == "congested_edge_on_route"

    graph[1][2]["state"] = "blocked"
    should_replan, reason = policy.should_replan(2, vehicle_state, route, [], graph)
    assert should_replan is True
    assert reason == "blocked_edge_on_route"

    arrived_state = {"current_node": 5, "route_index": 3, "arrived": True}
    should_replan, reason = policy.should_replan(3, arrived_state, route, [], graph)
    assert should_replan is False
    assert reason == "arrived"
