"""Tests for standard navigation results."""

from __future__ import annotations

import networkx as nx

from navigation import NavigationResult, run_algorithm_benchmarks, run_incremental_snn_navigation, run_navigation


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
    assert result.metadata["wavefront_runtime_sec"] >= 0.0
    assert result.metadata["brian2loihi_simulator_runtime_sec"] is None
    assert result.metadata["cpu_wavefront_runtime_sec"] >= 0.0
    assert result.metadata["final_wavefront_backend"] == "cpu_reference"
    assert result.metadata["stdp_parent_trace_runtime_sec"] >= 0.0
    assert result.metadata["path_reconstruction_runtime_sec"] >= 0.0
    assert result.metadata["stdp_path_backtrace_runtime_sec"] >= 0.0
    assert result.wavefront_frames
    assert result.metadata["spike_times_by_node"] == {0: 0.0, 1: 1.0, 2: 3.0}
    assert result.metadata["wavefront_time_max_ms"] == 3
    benchmarks = result.metadata["algorithm_benchmarks"]
    assert benchmarks["dijkstra"]["success"] is True
    assert benchmarks["dijkstra"]["path_nodes"] == [0, 1, 2]
    assert benchmarks["dijkstra"]["total_cost"] == 3.0
    assert benchmarks["astar"]["success"] is True
    assert benchmarks["astar"]["path_nodes"] == [0, 1, 2]
    assert benchmarks["astar"]["total_cost"] == 3.0


def test_snn_parent_trace_tie_breaks_by_real_route_cost():
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node), x=float(node), y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="normal")
    graph.add_edge(1, 3, cost=10.0, length=10.0, travel_time=10.0, delay_ms=1, state="normal")
    graph.add_edge(0, 2, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="normal")
    graph.add_edge(2, 3, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="normal")

    result = run_navigation(graph, 0, 3, use_loihi=False)

    assert result.path_nodes == [0, 2, 3]
    assert result.total_cost == 2.0


def test_navigation_can_skip_heavy_wavefront_visualization_payload():
    result = run_navigation(
        _toy_graph(),
        0,
        2,
        use_loihi=False,
        include_wavefront_frames=False,
        include_spike_times_metadata=False,
    )

    assert result.path_nodes == [0, 1, 2]
    assert result.wavefront_frames == []
    assert result.metadata["spike_times_by_node"] == {}
    assert result.metadata["num_spikes"] == 3
    assert result.metadata["wavefront_time_max_ms"] == 3


def test_classical_benchmarks_skip_blocked_edges_without_snn_state():
    # Dijkstra/A* 只读取当前图和权重属性；不会复用 SNN spike 或 parent trace。
    graph = _toy_graph()
    graph[0][1]["state"] = "blocked"

    benchmarks = run_algorithm_benchmarks(graph, 0, 2, cost_attr="cost")

    assert benchmarks["dijkstra"]["path_nodes"] == [0, 2]
    assert benchmarks["dijkstra"]["total_cost"] == 10.0
    assert benchmarks["astar"]["path_nodes"] == [0, 2]
    assert benchmarks["astar"]["total_cost"] == 10.0


def test_astar_benchmark_uses_osm_heuristic_without_losing_optimal_route():
    graph = nx.DiGraph()
    graph.graph["source"] = "osmnx"
    graph.add_node(0, lat=30.0, lon=120.0)
    graph.add_node(1, lat=30.001, lon=120.001)
    graph.add_node(2, lat=30.002, lon=120.002)
    graph.add_edge(0, 1, cost=1.0, travel_time=1.0, length=160.0, state="normal")
    graph.add_edge(1, 2, cost=1.0, travel_time=1.0, length=160.0, state="normal")
    graph.add_edge(0, 2, cost=5.0, travel_time=5.0, length=320.0, state="normal")

    benchmarks = run_algorithm_benchmarks(graph, 0, 2, cost_attr="cost")

    assert benchmarks["astar"]["success"] is True
    assert benchmarks["astar"]["path_nodes"] == [0, 1, 2]
    assert benchmarks["astar"]["total_cost"] == 2.0


def test_incremental_snn_avoids_closed_neurons_and_still_benchmarks_full_recompute():
    graph = nx.DiGraph()
    for node in range(4):
        graph.add_node(node, lat=0.0, lon=float(node), x=float(node), y=0.0, snn_neuron_index=node)
    graph.add_edge(0, 1, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="blocked", snn_synapse_closed=True)
    graph.add_edge(1, 3, cost=1.0, length=1.0, travel_time=1.0, delay_ms=1, state="normal")
    graph.add_edge(0, 2, cost=3.0, length=3.0, travel_time=3.0, delay_ms=3, state="normal")
    graph.add_edge(2, 3, cost=3.0, length=3.0, travel_time=3.0, delay_ms=3, state="normal")
    graph.nodes[1]["snn_neuron_closed"] = True

    result = run_incremental_snn_navigation(graph, 0, 3)

    assert result.path_nodes == [0, 2, 3]
    assert result.metadata["backend"] == "incremental_snn_cached_graph"
    assert result.metadata["snn_setup_reused"] is True
    assert result.metadata["wavefront_runtime_sec"] >= 0.0
    assert result.metadata["brian2loihi_simulator_runtime_sec"] is None
    assert result.metadata["cpu_wavefront_runtime_sec"] >= 0.0
    assert result.metadata["final_wavefront_backend"] == "cpu_reference_incremental"
    assert result.metadata["stdp_parent_trace_runtime_sec"] >= 0.0
    assert result.metadata["path_reconstruction_runtime_sec"] >= 0.0
    assert result.metadata["stdp_path_backtrace_runtime_sec"] >= 0.0
    assert result.metadata["closed_neuron_count"] == 1
    assert result.metadata["closed_synapse_count"] == 1
    assert result.metadata["algorithm_benchmarks"]["dijkstra"]["path_nodes"] == [0, 2, 3]
    assert result.metadata["algorithm_benchmarks"]["astar"]["path_nodes"] == [0, 2, 3]


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
    assert result.metadata["brian2loihi_simulator_runtime_sec"] is not None
    assert result.metadata["cpu_wavefront_runtime_sec"] is not None
    assert result.metadata["final_wavefront_backend"] == "cpu_reference"
    assert result.metadata["stdp_path_backtrace_runtime_sec"] >= 0.0


def test_navigation_strict_loihi_does_not_fall_back_to_cpu(monkeypatch):
    calls: list[bool] = []

    def fake_run_wavefront(_graph, _start_node, _goal_node, *, use_loihi, **_kwargs):
        calls.append(bool(use_loihi))
        return {
            "backend": "unavailable",
            "success": False,
            "error": "backend missing",
            "spike_times_by_neuron": {},
        }

    monkeypatch.setattr("navigation.planner.run_wavefront", fake_run_wavefront)

    result = run_navigation(_toy_graph(), 0, 2, use_loihi=True, allow_cpu_fallback=False)

    assert calls == [True]
    assert result.path_nodes == []
    assert result.metadata["success"] is False
    assert result.metadata["loihi_error"] == "backend missing"
    assert result.metadata["cpu_wavefront_runtime_sec"] is None
    assert result.metadata["final_wavefront_backend"] == "unavailable"


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
