"""Tests for fixed-condition serial navigation comparison."""

from __future__ import annotations

import networkx as nx

from loihi_planner.wavefront_reference import event_driven_wavefront
from traffic import run_serial_navigation_comparison
from traffic.edge_state import initialize_edge_state


def _ladder_graph() -> nx.DiGraph:
    graph = nx.DiGraph()
    for node in range(11):
        graph.add_node(node, lat=30.0, lon=120.0 + node * 0.001, x=120.0 + node * 0.001, y=30.0)
    for idx in range(10):
        bypass = 100 + idx
        long_bypass = 200 + idx
        graph.add_node(bypass, lat=30.001, lon=120.0 + idx * 0.0015, x=120.0 + idx * 0.0015, y=30.001)
        graph.add_node(long_bypass, lat=30.002, lon=120.0 + idx * 0.0015, x=120.0 + idx * 0.0015, y=30.002)
        graph.add_edge(idx, idx + 1, length=100.0, cost=1.0, travel_time=1.0, delay_ms=1, highway="primary")
        graph.add_edge(idx, bypass, length=60.0, cost=3.0, travel_time=3.0, delay_ms=3, highway="primary")
        bypass_target = min(10, idx + 2)
        graph.add_edge(bypass, bypass_target, length=60.0, cost=3.0, travel_time=3.0, delay_ms=3, highway="primary")
        graph.add_edge(idx, long_bypass, length=120.0, cost=20.0, travel_time=20.0, delay_ms=20, highway="primary")
        graph.add_edge(long_bypass, 10, length=120.0, cost=20.0, travel_time=20.0, delay_ms=20, highway="primary")
        graph.add_edge(bypass, long_bypass, length=120.0, cost=20.0, travel_time=20.0, delay_ms=20, highway="primary")
    return initialize_edge_state(graph)


def test_serial_comparison_uses_one_fixed_congestion_schedule_and_strict_loihi(monkeypatch):
    calls: list[bool] = []

    def fake_run_wavefront(graph, start_node, goal_node, *, use_loihi, delay_attr, **_kwargs):
        calls.append(bool(use_loihi))
        reference = event_driven_wavefront(graph, int(start_node), int(goal_node), delay_attr=delay_attr)
        spike_times = {int(node): float(time) for node, time in reference["arrival_times"].items()}
        return {
            "backend": "brian2loihi",
            "success": reference["target_arrival_time"] is not None,
            "error": None if reference["target_arrival_time"] is not None else "target did not spike",
            "spike_times_by_neuron": spike_times,
            "target_arrival_time_ms": reference["target_arrival_time"],
            "num_spikes": len(spike_times),
            "active_neurons": len(spike_times),
            "sim_time_ms": int(max(spike_times.values(), default=0.0)),
        }

    monkeypatch.setattr("navigation.planner.run_wavefront", fake_run_wavefront)
    monkeypatch.setattr("navigation.incremental.run_wavefront", fake_run_wavefront)

    comparison = run_serial_navigation_comparison(
        _ladder_graph(),
        0,
        10,
        congestion_count=7,
        edge_count_per_event=1,
        lookahead_m=250.0,
        average_speed_mps=8.3333333333,
        allow_snn_cpu_fallback=False,
    )

    assert 5 <= len(comparison.congestion_schedule) <= 10
    assert set(comparison.runs) == {"snn", "dijkstra", "astar"}
    assert all(run.success for run in comparison.runs.values())
    assert all(run.planning_event_count == len(comparison.congestion_schedule) + 1 for run in comparison.runs.values())
    assert comparison.runs["snn"].backend == "incremental_snn_cached_graph"
    assert comparison.runs["dijkstra"].total_planning_runtime_sec >= 0.0
    assert comparison.runs["astar"].total_planning_runtime_sec >= 0.0
    assert calls == [True] * (len(comparison.congestion_schedule) + 1)
