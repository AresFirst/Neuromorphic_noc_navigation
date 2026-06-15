"""Tests for GUI-side route status helpers."""

from __future__ import annotations

import inspect

import networkx as nx

import gui.app as gui_app
from maps import HANGZHOU_BBOX
from gui.app import (
    FOLIUM_TILE_NAME,
    ROUTE_COLORS,
    _add_comparison_route_overlays,
    _algorithm_comparison_rows,
    _coordinate_in_bbox,
    _ensure_playback_state,
    _finish_playback_state,
    _pause_playback_state,
    _runtime_metric_rows,
    _start_playback_state,
    _validate_hangzhou_coordinates,
    _wavefront_frame_at_time,
    _wavefront_inflight_edges_at_time,
    _wavefront_time_limit,
    _reachability_status,
)
from navigation import NavigationResult, WavefrontFrame


def test_reachability_status_detects_reverse_only_route():
    # 单行道场景：反向可达不等于当前 start->goal 可达，GUI 应给出明确提示。
    graph = nx.DiGraph()
    graph.add_edge(1, 0)
    graph.add_edge(0, 2)

    reachable, message = _reachability_status(graph, 0, 1)

    assert reachable is False
    assert "反方向可能可达" in message


def test_reachability_status_accepts_directed_route():
    # 正向路径存在时，GUI 可以继续运行 SNN navigation。
    graph = nx.DiGraph()
    graph.add_edge(0, 1)

    reachable, message = _reachability_status(graph, 0, 1)

    assert reachable is True
    assert "有向可达路径" in message


def test_hangzhou_coordinate_validation_uses_fixed_bbox():
    assert HANGZHOU_BBOX.north > HANGZHOU_BBOX.south
    assert HANGZHOU_BBOX.east > HANGZHOU_BBOX.west
    assert _coordinate_in_bbox(30.25, 120.16)
    assert not _coordinate_in_bbox(31.25, 121.16)

    errors = _validate_hangzhou_coordinates(31.25, 120.16, 30.25, 121.16)

    assert errors == [
        "起点坐标不在浙江省杭州市范围内，请输入杭州经纬度范围内的坐标。",
        "终点坐标不在浙江省杭州市范围内，请输入杭州经纬度范围内的坐标。",
    ]


def test_playback_state_transitions_are_explicit():
    state: dict[str, object] = {}

    _ensure_playback_state(state)
    assert state["vehicle_running"] is False
    assert state["simulation_started"] is False

    _start_playback_state(state, now=12.5)
    assert state["vehicle_running"] is True
    assert state["vehicle_paused"] is False
    assert state["simulation_started"] is True
    assert state["last_tick_time"] == 12.5

    _pause_playback_state(state)
    assert state["vehicle_running"] is False
    assert state["vehicle_paused"] is True
    assert state["navigation_status_message"] == "导航已暂停"

    _finish_playback_state(state, "导航已结束")
    assert state["vehicle_running"] is False
    assert state["vehicle_paused"] is False
    assert state["vehicle_finished"] is True
    assert state["navigation_status_message"] == "导航已结束"


def test_gui_main_no_longer_exposes_region_or_tile_selectors():
    source = inspect.getsource(gui_app.main)

    assert "Map input" not in source
    assert "Place name" not in source
    assert "Bounding box" not in source
    assert "Map tiles" not in source
    assert "Car position" not in source
    assert "Step Dynamic Traffic" not in source
    assert "道路网络类型" not in source
    assert "显示基础道路网络" not in source
    assert "波前节点绘制数量上限" not in source
    assert "使用 Brian2Loihi 后端" not in source
    assert "启用模拟交通" not in source
    assert "交通模式" not in source
    assert FOLIUM_TILE_NAME == "OpenStreetMap"
    assert "tiles=FOLIUM_TILE_NAME" in source


def test_gui_main_contains_required_chinese_labels():
    source = inspect.getsource(gui_app.main)

    for label in [
        "当前地图区域：",
        "加载杭州地图",
        "运行 SNN 导航",
        "起点纬度",
        "起点经度",
        "终点纬度",
        "终点经度",
        "道路网络：",
        "地图缩放/拖动已禁用",
        "车辆每行驶约",
        "增量发放脉冲",
        "模拟交通",
        "开始",
        "暂停",
        "结束",
        "仿真时间",
        "车辆数",
        "平均速度",
        "拥堵路段",
        "重规划次数",
        "地图节点数",
        "路线折线点数",
        "SNN算法耗时",
        "算法运行耗时对比",
        "详细耗时指标",
        "调试信息 / 元数据 / 日志",
    ]:
        assert label in source


def test_wavefront_frame_at_arbitrary_timestep():
    # GUI slider 可以停在任意整数时间点，因此需要从 spike times 重建中间帧。
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


def test_algorithm_comparison_rows_include_independent_benchmarks():
    result = NavigationResult(
        start_node=0,
        goal_node=2,
        path_nodes=[0, 1, 2],
        path_edges=[(0, 1), (1, 2)],
        total_cost=3.0,
        metadata={
            "success": True,
            "snn_runtime_sec": 0.12,
            "path_travel_time_s": 3.0,
            "algorithm_benchmarks": {
                "dijkstra": {
                    "label": "Dijkstra",
                    "success": True,
                    "runtime_sec": 0.01,
                    "path_nodes": [0, 1, 2],
                    "path_node_count": 3,
                    "total_cost": 3.0,
                    "path_travel_time_s": 3.0,
                },
                "astar": {
                    "label": "A*",
                    "success": True,
                    "runtime_sec": 0.008,
                    "path_nodes": [0, 1, 2],
                    "path_node_count": 3,
                    "total_cost": 3.0,
                    "path_travel_time_s": 3.0,
                },
            },
        },
    )

    rows = _algorithm_comparison_rows(result)

    assert [row["算法"] for row in rows] == ["SNN", "Dijkstra", "A*"]
    assert rows[0]["算法计算耗时（秒）"] == 0.12
    assert rows[1]["算法计算耗时（秒）"] == 0.01
    assert rows[2]["算法计算耗时（秒）"] == 0.008
    assert rows[0]["耗时口径"] == "SNN 规划核心"
    assert rows[1]["耗时口径"] == "隔离图快照完整重算"
    assert rows[1]["路线关系"] == "与 SNN 相同"
    assert rows[2]["路线关系"] == "与 SNN 相同"


def test_runtime_metric_rows_include_map_snn_stdp_loihi_and_classical_timings():
    result = NavigationResult(
        start_node=0,
        goal_node=2,
        path_nodes=[0, 1, 2],
        path_edges=[(0, 1), (1, 2)],
        total_cost=3.0,
        metadata={
            "success": True,
            "snn_runtime_sec": 0.12,
            "snn_runtime_scope": "SNN test scope",
            "brian2loihi_simulator_runtime_sec": 0.02,
            "cpu_wavefront_runtime_sec": None,
            "final_wavefront_backend": "brian2loihi",
            "stdp_parent_trace_runtime_sec": 0.003,
            "path_reconstruction_runtime_sec": 0.004,
            "stdp_path_backtrace_runtime_sec": 0.007,
            "algorithm_benchmarks": {
                "dijkstra": {
                    "label": "Dijkstra",
                    "success": True,
                    "runtime_sec": 0.011,
                    "runtime_scope": "Dijkstra isolated",
                },
                "astar": {
                    "label": "A*",
                    "success": True,
                    "runtime_sec": 0.009,
                    "runtime_scope": "A* isolated",
                },
            },
        },
    )

    rows = _runtime_metric_rows(
        result,
        {
            "total_runtime_sec": 1.2,
            "graph_runtime_sec": 0.8,
            "geometry_runtime_sec": 0.4,
        },
    )
    by_metric = {row["指标"]: row for row in rows}

    assert by_metric["地图 load 总用时"]["耗时（秒）"] == 1.2
    assert by_metric["地图图数据 load 用时"]["耗时（秒）"] == 0.8
    assert by_metric["地图道路几何缓存用时"]["耗时（秒）"] == 0.4
    assert by_metric["SNN 总规划用时"]["耗时（秒）"] == 0.12
    assert by_metric["Brian2Loihi 仿真器用时"]["耗时（秒）"] == 0.02
    assert by_metric["STDP parent trace 用时"]["耗时（秒）"] == 0.003
    assert by_metric["路径重建与成本计算用时"]["耗时（秒）"] == 0.004
    assert by_metric["STDP 路径回溯总用时"]["耗时（秒）"] == 0.007
    assert by_metric["Dijkstra 规划用时"]["耗时（秒）"] == 0.011
    assert by_metric["A* 规划用时"]["耗时（秒）"] == 0.009


def test_comparison_route_overlays_always_draw_astar_even_when_path_matches_snn():
    graph = nx.DiGraph()
    graph.add_node(0, lat=30.0, lon=120.0)
    graph.add_node(1, lat=30.1, lon=120.1)
    graph.add_node(2, lat=30.2, lon=120.2)
    graph.add_edge(0, 1)
    graph.add_edge(1, 2)
    result = NavigationResult(
        start_node=0,
        goal_node=2,
        path_nodes=[0, 1, 2],
        path_edges=[(0, 1), (1, 2)],
        metadata={
            "success": True,
            "algorithm_benchmarks": {
                "dijkstra": {"success": True, "path_nodes": [0, 1, 2]},
                "astar": {"success": True, "path_nodes": [0, 1, 2]},
            },
        },
    )
    calls: list[dict[str, object]] = []

    class FakePolyLine:
        def __init__(self, points, **kwargs):
            self.points = points
            self.kwargs = kwargs

        def add_to(self, _fmap):
            calls.append(self.kwargs)
            return self

    class FakeFolium:
        PolyLine = FakePolyLine

    _add_comparison_route_overlays(FakeFolium, object(), graph, result)

    assert [call["tooltip"] for call in calls] == ["Dijkstra 路线", "A* 路线"]
    assert [call["color"] for call in calls] == [ROUTE_COLORS["dijkstra"], ROUTE_COLORS["astar"]]
