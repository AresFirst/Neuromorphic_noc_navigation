"""Metrics and persistence helpers for dynamic navigation."""

from __future__ import annotations

import csv
import json
from pathlib import Path


_STEP_LOG_ORDER = [
    "step",
    "current_node",
    "target",
    "replanned",
    "replan_reason",
    "planning_success",
    "route",
    "next_edge",
    "active_congested_edges",
    "arrived",
    "num_spikes",
    "target_arrival_time_ms",
    "path_cost",
    "route_index",
    "remaining_route",
    "planning_time_sec",
]


def _jsonify(value):
    if isinstance(value, tuple):
        return [_jsonify(item) for item in value]
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    return value


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(_jsonify(value), ensure_ascii=False)
    return value


def save_step_logs(step_logs: list[dict], path: str) -> None:
    output = Path(path).expanduser()
    if output.suffix.lower() != ".csv":
        output.mkdir(parents=True, exist_ok=True)
        output = output / "dynamic_step_logs.csv"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(_STEP_LOG_ORDER)
    for log in step_logs:
        for key in log:
            if key not in fieldnames:
                fieldnames.append(key)

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for log in step_logs:
            row = {field: _csv_value(log.get(field)) for field in fieldnames}
            writer.writerow(row)


def summarize_dynamic_run(step_logs: list[dict], start: int, target: int) -> dict:
    num_steps = len(step_logs)
    arrived_step = None
    for log in step_logs:
        if bool(log.get("arrived")):
            arrived_step = int(log.get("step"))
            break

    replanned_logs = [log for log in step_logs if bool(log.get("replanned"))]
    successful_replans = [log for log in replanned_logs if bool(log.get("planning_success"))]
    failed_replans = [log for log in replanned_logs if not bool(log.get("planning_success"))]

    planning_times = [
        float(log["planning_time_sec"])
        for log in replanned_logs
        if log.get("planning_time_sec") not in (None, "")
    ]
    total_spikes = sum(int(log.get("num_spikes", 0) or 0) for log in step_logs)
    final_route = step_logs[-1].get("route", []) if step_logs else []

    active_edges = set()
    for log in step_logs:
        for edge in log.get("active_congested_edges", []) or []:
            if isinstance(edge, (list, tuple)) and len(edge) == 2:
                active_edges.add((int(edge[0]), int(edge[1])))

    return {
        "start": int(start),
        "target": int(target),
        "arrived": bool(step_logs[-1].get("arrived")) if step_logs else False,
        "arrival_step": arrived_step,
        "num_steps": int(num_steps),
        "num_replans": int(len(replanned_logs)),
        "num_successful_replans": int(len(successful_replans)),
        "num_failed_replans": int(len(failed_replans)),
        "num_congestion_events": int(len(active_edges)),
        "final_route": final_route,
        "total_spikes": int(total_spikes),
        "mean_planning_time_sec": (sum(planning_times) / len(planning_times)) if planning_times else None,
        "output_dir": None,
    }
