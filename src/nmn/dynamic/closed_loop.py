"""Closed-loop dynamic city navigation demo."""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path

import networkx as nx

from nmn.loihi import (
    compute_path_cost,
    infer_parent_trace_from_spikes,
    reconstruct_path_from_parent,
    run_loihi_wavefront,
)

from .congestion import CongestionController, CongestionEvent
from .metrics import save_step_logs, summarize_dynamic_run
from .replanning_policy import ReplanningPolicy
from .snn_cost_adapter import prepare_graph_for_snn_planning
from .vehicle import EgoVehicle
from .visualization import draw_dynamic_state


logger = logging.getLogger(__name__)


def _event_to_dict(event: CongestionEvent | dict) -> dict:
    if isinstance(event, CongestionEvent):
        return event.to_dict()
    return dict(event)


def _event_from_any(event: CongestionEvent | dict) -> CongestionEvent:
    if isinstance(event, CongestionEvent):
        return event
    return CongestionEvent(**dict(event))


def _vehicle_state(vehicle: EgoVehicle) -> dict:
    return {
        "current_node": vehicle.current_node(),
        "target_node": vehicle.target_node,
        "route_index": vehicle.route_index,
        "remaining_route": vehicle.route[vehicle.route_index :] if vehicle.route else [],
        "arrived": vehicle.has_arrived(),
    }


def _plan_route(
    G_dynamic: nx.DiGraph,
    current_node: int,
    target_node: int,
    loihi_config: dict | None,
    seed: int,
) -> dict:
    config = loihi_config or {}
    G_snn = prepare_graph_for_snn_planning(G_dynamic)
    wavefront = run_loihi_wavefront(
        G_snn,
        current_node,
        target_node,
        delay_attr="delay_ms",
        threshold=float(config.get("threshold", 1.0)),
        weight=float(config.get("weight", 1.1)),
        refractory_ms=int(config.get("refractory_ms", 1000)),
        seed=int(config.get("seed", seed)),
    )
    if not wavefront.get("success"):
        return {
            "success": False,
            "error": wavefront.get("error"),
            "path": None,
            "path_cost": None,
            "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
            "num_spikes": int(wavefront.get("num_spikes", 0) or 0),
            "wavefront": wavefront,
        }

    parent_trace = infer_parent_trace_from_spikes(
        G_snn,
        wavefront["spike_times_by_neuron"],
        current_node,
        delay_attr="delay_ms",
    )
    path = reconstruct_path_from_parent(parent_trace, current_node, target_node)
    path_cost = compute_path_cost(G_snn, path, weight="delay_ms")
    return {
        "success": True,
        "error": None,
        "path": path,
        "path_cost": path_cost,
        "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
        "num_spikes": int(wavefront.get("num_spikes", 0) or 0),
        "wavefront": wavefront,
    }


def generate_congestion_events_on_route(
    route: list[int],
    start_step: int,
    duration_steps: int,
    delay_factor: float,
    mode: str = "delay",
    num_events: int = 1,
    seed: int = 0,
) -> list[CongestionEvent]:
    if int(duration_steps) <= 0:
        raise ValueError("duration_steps must be positive")
    edges = list(zip([int(node) for node in route], [int(node) for node in route[1:]]))
    if not edges or num_events <= 0:
        return []

    if len(edges) > 2:
        candidates = edges[1:-1]
    else:
        candidates = edges

    if not candidates:
        return []

    rng = random.Random(int(seed))
    if num_events <= len(candidates):
        selected = rng.sample(candidates, num_events)
    else:
        selected = [rng.choice(candidates) for _ in range(num_events)]

    events: list[CongestionEvent] = []
    for edge_u, edge_v in selected:
        threshold_penalty = 0.0
        event_delay_factor = float(delay_factor)
        event_mode = str(mode)
        if event_mode == "threshold":
            threshold_penalty = float(delay_factor)
            event_delay_factor = 1.0
        events.append(
            CongestionEvent(
                edge_u=edge_u,
                edge_v=edge_v,
                start_step=int(start_step),
                end_step=int(start_step) + int(duration_steps),
                delay_factor=event_delay_factor,
                threshold_penalty=threshold_penalty,
                mode=event_mode,
            )
        )
    return events


def _generate_random_congestion_events(
    G: nx.DiGraph,
    num_events: int,
    start_step: int,
    duration_steps: int,
    delay_factor: float,
    mode: str,
    seed: int,
    exclude_edges: set[tuple[int, int]] | None = None,
) -> list[CongestionEvent]:
    if int(duration_steps) <= 0:
        raise ValueError("duration_steps must be positive")
    if num_events <= 0 or G.number_of_edges() == 0:
        return []
    exclude = set(exclude_edges or set())
    candidates = [edge for edge in G.edges() if tuple(edge) not in exclude]
    if not candidates:
        return []
    rng = random.Random(int(seed))
    if num_events <= len(candidates):
        selected = rng.sample(candidates, num_events)
    else:
        selected = [rng.choice(candidates) for _ in range(num_events)]

    events: list[CongestionEvent] = []
    for edge_u, edge_v in selected:
        threshold_penalty = 0.0
        event_delay_factor = float(delay_factor)
        event_mode = str(mode)
        if event_mode == "threshold":
            threshold_penalty = float(delay_factor)
            event_delay_factor = 1.0
        events.append(
            CongestionEvent(
                edge_u=int(edge_u),
                edge_v=int(edge_v),
                start_step=int(start_step),
                end_step=int(start_step) + int(duration_steps),
                delay_factor=event_delay_factor,
                threshold_penalty=threshold_penalty,
                mode=event_mode,
            )
        )
    return events


def run_dynamic_navigation_loop(
    G: nx.DiGraph,
    start: int,
    target: int,
    congestion_events: list,
    max_steps: int = 100,
    replan_interval: int = 5,
    loihi_config: dict | None = None,
    output_dir: str | None = None,
    visualize: bool = False,
    save_frames: bool = False,
    seed: int = 0,
) -> dict:
    output_path = Path(output_dir).expanduser() if output_dir else None
    if output_path is not None:
        output_path.mkdir(parents=True, exist_ok=True)

    vehicle = EgoVehicle(start_node=int(start), target_node=int(target))
    controller = CongestionController(G)
    for event in congestion_events:
        controller.add_event(_event_from_any(event))

    policy = ReplanningPolicy(
        replan_interval=int(replan_interval),
        replan_on_congestion_on_route=True,
        replan_on_blocked_edge=True,
    )

    step_logs: list[dict] = []
    last_path_cost: float | None = None
    last_target_arrival_time_ms: float | None = None
    num_successful_replans = 0
    num_failed_replans = 0

    for step in range(int(max_steps)):
        congestion_update = controller.update(step)
        active_edges = congestion_update["active_edges"]

        vehicle_state = _vehicle_state(vehicle)
        should_replan, reason = policy.should_replan(
            step=step,
            vehicle_state=vehicle_state,
            current_route=vehicle.route,
            active_congested_edges=active_edges,
            graph=controller.get_graph(),
        )

        replanned = bool(should_replan)
        planning_success = None
        planning_time_sec = None
        num_spikes = 0
        path_cost = last_path_cost
        target_arrival_time_ms = last_target_arrival_time_ms

        if replanned:
            plan_start = time.perf_counter()
            plan_result = _plan_route(
                controller.get_graph(),
                vehicle.current_node(),
                vehicle.target_node,
                loihi_config=loihi_config,
                seed=seed,
            )
            planning_time_sec = float(time.perf_counter() - plan_start)
            planning_success = bool(plan_result["success"])
            num_spikes = int(plan_result["num_spikes"])
            target_arrival_time_ms = plan_result["target_arrival_time_ms"]
            if planning_success:
                last_path_cost = float(plan_result["path_cost"])
                last_target_arrival_time_ms = target_arrival_time_ms
                vehicle.set_route(list(plan_result["path"]))
                num_successful_replans += 1
            else:
                num_failed_replans += 1
                logger.warning("Planning failed at step %s: %s", step, plan_result.get("error"))
        else:
            planning_success = None

        next_edge = vehicle.next_edge()
        current_graph = controller.get_graph()
        moved = True
        if next_edge is not None:
            if not current_graph.has_edge(*next_edge):
                moved = False
            elif current_graph[next_edge[0]][next_edge[1]].get("state") == "blocked":
                moved = False
        if moved:
            vehicle_state_after = vehicle.step()
        else:
            vehicle_state_after = vehicle.snapshot()

        if visualize or save_frames:
            frame_path = None
            if save_frames and output_path is not None:
                frames_dir = output_path / "frames"
                frames_dir.mkdir(parents=True, exist_ok=True)
                frame_path = frames_dir / f"step_{step:03d}.png"
            draw_dynamic_state(
                controller.get_graph(),
                vehicle_node=vehicle.current_node(),
                target_node=vehicle.target_node,
                current_route=vehicle.route,
                active_congested_edges=active_edges,
                step=step,
                save_path=str(frame_path) if frame_path is not None else None,
            )

        step_log = {
            "step": int(step),
            "current_node": int(vehicle_state_after["current_node"]),
            "target": int(vehicle.target_node),
            "replanned": replanned,
            "replan_reason": reason,
            "planning_success": planning_success,
            "route": vehicle.route,
            "next_edge": vehicle.next_edge(),
            "active_congested_edges": active_edges,
            "arrived": vehicle.has_arrived(),
            "num_spikes": int(num_spikes),
            "target_arrival_time_ms": target_arrival_time_ms,
            "path_cost": path_cost,
            "route_index": int(vehicle_state_after["route_index"]),
            "remaining_route": vehicle_state_after["remaining_route"],
            "planning_time_sec": planning_time_sec,
        }
        step_logs.append(step_log)

        if vehicle.has_arrived():
            break

    summary = summarize_dynamic_run(step_logs, start=start, target=target)
    summary["num_congestion_events"] = len(congestion_events)
    summary["output_dir"] = str(output_path) if output_path is not None else None
    summary["final_route"] = step_logs[-1]["route"] if step_logs else vehicle.route
    summary["total_spikes"] = int(sum(int(log.get("num_spikes", 0) or 0) for log in step_logs))
    summary["num_successful_replans"] = int(num_successful_replans)
    summary["num_failed_replans"] = int(num_failed_replans)
    planning_times = [
        float(log["planning_time_sec"])
        for log in step_logs
        if log.get("planning_time_sec") not in (None, "")
    ]
    summary["mean_planning_time_sec"] = (
        sum(planning_times) / len(planning_times) if planning_times else None
    )

    if output_path is not None:
        save_step_logs(step_logs, str(output_path / "dynamic_step_logs.csv"))
        (output_path / "dynamic_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return {
        "summary": summary,
        "step_logs": step_logs,
        "vehicle": vehicle,
        "controller": controller,
        "output_dir": str(output_path) if output_path is not None else None,
        "final_route": summary["final_route"],
    }
