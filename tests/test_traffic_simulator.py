"""Tests for simulated traffic congestion and dynamic replanning."""

from __future__ import annotations

import networkx as nx

from navigation import run_navigation
from traffic import TrafficConfig, TrafficEdgeState, TrafficSnapshot, apply_traffic_to_graph, generate_traffic_snapshot


def _reroute_graph() -> nx.DiGraph:
    # 两条候选路线：0->1->3 原本更快，0->2->3 是拥堵后的备选路线。
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node), x=float(node), y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="normal")
    graph.add_edge(1, 3, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="normal")
    graph.add_edge(0, 2, cost=5.0, length=5.0, travel_time=5.0, delay_ms=5, state="normal")
    graph.add_edge(2, 3, cost=5.0, length=5.0, travel_time=5.0, delay_ms=5, state="normal")
    return graph


def test_apply_traffic_blocks_edges_without_mutating_base_graph():
    # 交通层必须返回 copy；base_graph 代表原始地图，不能被动态拥堵污染。
    base_graph = _reroute_graph()
    snapshot = TrafficSnapshot(
        step=1,
        edge_states={
            (0, 1): TrafficEdgeState(
                edge=(0, 1),
                vehicle_count=25,
                congestion=1.0,
                delay_factor=4.0,
                blocked=True,
            )
        },
        inhibited_nodes={1: 1.0},
    )

    dynamic_graph = apply_traffic_to_graph(base_graph, snapshot, config=TrafficConfig(node_penalty_ms=8))

    assert base_graph[0][1]["state"] == "normal"
    assert base_graph[0][1]["delay_ms"] == 1
    assert dynamic_graph[0][1]["state"] == "blocked"
    assert dynamic_graph[0][1]["traffic_congestion"] == 1.0
    assert dynamic_graph[0][1]["vehicle_count"] == 25
    assert dynamic_graph.graph["traffic_snapshot_step"] == 1


def test_simulated_route_congestion_can_force_wavefront_reroute():
    # 把拥堵放到当前最优路径上，验证重新运行 wavefront 后能切换到替代路径。
    base_graph = _reroute_graph()
    baseline = run_navigation(base_graph, 0, 3, use_loihi=False)
    assert baseline.path_nodes == [0, 1, 3]

    config = TrafficConfig(
        vehicle_count=120,
        hotspot_count=1,
        congestion_strength=4.0,
        block_threshold=0.5,
        node_penalty_ms=0,
        seed=3,
    )
    snapshot = generate_traffic_snapshot(
        base_graph,
        step=1,
        config=config,
        route_edges=baseline.path_edges,
        prefer_route=True,
    )
    dynamic_graph = apply_traffic_to_graph(base_graph, snapshot, config=config)
    replanned = run_navigation(dynamic_graph, 0, 3, use_loihi=False)

    assert snapshot.blocked_edges
    assert replanned.path_nodes == [0, 2, 3]
    assert replanned.total_cost == 10.0
