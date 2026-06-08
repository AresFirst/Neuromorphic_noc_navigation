"""Tests for standard navigation results."""

from __future__ import annotations

import networkx as nx

from navigation import NavigationResult, run_navigation


def _toy_graph() -> nx.DiGraph:
    # 三节点 toy graph：0->1->2 虽然边数更多，但 cost/delay 总和优于直达边 0->2。
    graph = nx.DiGraph()
    graph.add_node(0, lat=35.0, lon=139.0, x=139.0, y=35.0, snn_neuron_index=0)
    graph.add_node(1, lat=35.1, lon=139.1, x=139.1, y=35.1, snn_neuron_index=1)
    graph.add_node(2, lat=35.2, lon=139.2, x=139.2, y=35.2, snn_neuron_index=2)
    graph.add_edge(0, 1, cost=1.0, length=10.0, travel_time=1.0, delay_ms=1, state="normal")
    graph.add_edge(1, 2, cost=2.0, length=20.0, travel_time=2.0, delay_ms=2, state="normal")
    graph.add_edge(0, 2, cost=10.0, length=25.0, travel_time=10.0, delay_ms=10, state="normal")
    return graph


def test_toy_graph_runs_navigation_planner_with_cpu_compatible_wavefront():
    # 在无 Loihi 依赖的 CPU reference 上验证完整 NavigationResult 闭环。
    result = run_navigation(_toy_graph(), 0, 2, use_loihi=False)

    assert isinstance(result, NavigationResult)
    assert result.path_nodes == [0, 1, 2]
    assert result.path_edges == [(0, 1), (1, 2)]
    assert result.total_cost == 3.0
    assert result.metadata["path_length_m"] == 30.0
    assert result.metadata["path_travel_time_s"] == 3.0
    assert result.metadata["success"] is True
    assert result.metadata["backend"] == "cpu_reference"
    assert result.wavefront_frames
    assert result.metadata["spike_times_by_node"] == {0: 0.0, 1: 1.0, 2: 3.0}
    assert result.metadata["wavefront_time_max_ms"] == 3


def test_navigation_falls_back_when_loihi_backend_fails(monkeypatch):
    # 模拟 Loihi 后端失败，确认 run_navigation 会自动降级到 CPU reference。
    calls: list[bool] = []

    def fake_run_wavefront(graph, start_node, goal_node, *, use_loihi, **_kwargs):
        # 第一次 use_loihi=True 返回失败；第二次 use_loihi=False 返回可用 spike times。
        calls.append(bool(use_loihi))
        if use_loihi:
            return {
                "backend": "unavailable",
                "success": False,
                "error": "backend missing",
                "spike_times_by_neuron": {},
            }
        return {
            "backend": "cpu_reference",
            "success": True,
            "error": None,
            "spike_times_by_neuron": {0: 0.0, 1: 1.0, 2: 3.0},
            "target_arrival_time_ms": 3.0,
            "num_spikes": 3,
            "active_neurons": 3,
            "sim_time_ms": 3,
        }

    monkeypatch.setattr("navigation.planner.run_wavefront", fake_run_wavefront)

    result = run_navigation(_toy_graph(), 0, 2, use_loihi=True)

    assert calls == [True, False]
    assert result.path_nodes == [0, 1, 2]
    assert result.metadata["backend"] == "cpu_reference"
    assert result.metadata["loihi_error"] == "backend missing"


def test_unreachable_goal_can_still_have_two_wavefront_frames():
    # 不可达并不代表没有 wavefront：起点和可达邻居仍会发放，目标不会发放。
    graph = nx.DiGraph()
    graph.add_node(0, lat=0.0, lon=0.0, x=0.0, y=0.0, snn_neuron_index=0)
    graph.add_node(1, lat=0.0, lon=1.0, x=1.0, y=0.0, snn_neuron_index=1)
    graph.add_node(2, lat=0.0, lon=2.0, x=2.0, y=0.0, snn_neuron_index=2)
    graph.add_edge(1, 0, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="normal")
    graph.add_edge(0, 2, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="normal")

    result = run_navigation(graph, 0, 1, use_loihi=False)

    assert result.path_nodes == []
    assert result.total_cost is None
    assert result.metadata["success"] is False
    assert result.metadata["target_arrival_time_ms"] is None
    assert len(result.wavefront_frames) == 2
    assert [frame.t for frame in result.wavefront_frames] == [0, 1]
