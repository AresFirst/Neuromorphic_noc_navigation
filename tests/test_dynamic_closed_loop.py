"""Integration test for the dynamic closed-loop demo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nmn.dynamic import closed_loop as closed_loop_module
from nmn.dynamic.closed_loop import generate_congestion_events_on_route, run_dynamic_navigation_loop
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from loihi_planner.wavefront_reference import event_driven_wavefront


def _build_graph():
    import networkx as nx

    graph = nx.DiGraph()
    for node in range(6):
        graph.add_node(node, x=float(node), y=float(node % 2), region=0)

    edges = [
        (0, 1, 1),
        (1, 2, 1),
        (2, 5, 1),
        (0, 3, 5),
        (3, 4, 1),
        (4, 5, 1),
        (1, 3, 1),
    ]
    for source, target, delay in edges:
        graph.add_edge(source, target, delay_ms=delay, original_delay_ms=delay, state="normal")
    return graph


def _fake_run_loihi_wavefront(G, start, target, delay_attr="delay_ms", **_kwargs):
    reference = event_driven_wavefront(G, start, target, delay_attr=delay_attr)
    if reference["target_arrival_time"] is None:
        return {
            "backend": "fake",
            "start": start,
            "target": target,
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "num_spikes": 0,
            "active_neurons": 0,
            "sim_time_ms": 0,
            "success": False,
            "error": "unreachable",
        }
    return {
        "backend": "fake",
        "start": start,
        "target": target,
        "spike_times_by_neuron": reference["arrival_times"],
        "target_arrival_time_ms": reference["target_arrival_time"],
        "num_spikes": len(reference["arrival_times"]),
        "active_neurons": len(reference["arrival_times"]),
        "sim_time_ms": int(reference["target_arrival_time"]) + 5,
        "success": True,
        "error": None,
    }


def test_dynamic_closed_loop_replans_around_blocked_edge(tmp_path, monkeypatch):
    monkeypatch.setattr(closed_loop_module, "run_loihi_wavefront", _fake_run_loihi_wavefront)

    graph = _build_graph()
    reference = event_driven_wavefront(graph, 0, 5, delay_attr="delay_ms")
    parent_trace = infer_parent_trace_from_spikes(graph, reference["arrival_times"], 0, delay_attr="delay_ms")
    initial_route = reconstruct_path_from_parent(parent_trace, 0, 5)
    assert initial_route == [0, 1, 2, 5]

    congestion_events = generate_congestion_events_on_route(
        route=initial_route,
        start_step=1,
        duration_steps=3,
        delay_factor=5.0,
        mode="blocked",
        num_events=1,
        seed=0,
    )
    assert len(congestion_events) == 1
    assert (congestion_events[0].edge_u, congestion_events[0].edge_v) == (1, 2)

    output_dir = tmp_path / "dynamic"
    result = run_dynamic_navigation_loop(
        G=graph,
        start=0,
        target=5,
        congestion_events=congestion_events,
        max_steps=10,
        replan_interval=5,
        loihi_config={"threshold": 1.0, "weight": 1.1, "refractory_ms": 1000, "seed": 0},
        output_dir=str(output_dir),
        visualize=False,
        save_frames=False,
        seed=0,
    )

    summary = result["summary"]
    step_logs = result["step_logs"]
    assert summary["arrived"] is True
    assert any(log["replanned"] for log in step_logs)
    assert any(log["replan_reason"] == "blocked_edge_on_route" for log in step_logs)
    assert summary["final_route"]
    assert (1, 2) not in set(zip(summary["final_route"], summary["final_route"][1:]))

    assert (output_dir / "dynamic_step_logs.csv").exists()
    assert (output_dir / "dynamic_summary.json").exists()
    assert json.loads((output_dir / "dynamic_summary.json").read_text(encoding="utf-8"))["arrived"] is True
