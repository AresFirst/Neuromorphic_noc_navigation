"""Dynamic SUMO-geometry navigation driven by Brian2Loihi wavefront replanning."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import networkx as nx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_config import load_brian2loihi_config
from nmn.loihi import compute_path_cost, run_loihi_wavefront
from nmn.sumo import (
    advance_traffic_vehicles,
    apply_traffic_congestion,
    digraph_to_snn,
    draw_sumo_dynamic_frame,
    find_sumo_netxml,
    most_to_digraph,
    path_to_sumo_route,
    run_sumo_map_load_check,
    snn_output_to_path,
    spawn_random_traffic_vehicles,
    traffic_vehicle_positions,
    wavefront_frame_times,
    write_gif,
    write_json,
)


def _edge_delay(_source, _target, attrs: dict) -> float:
    if attrs.get("state") == "blocked":
        return float("inf")
    return float(attrs.get("delay_ms", attrs.get("base_cost", 1.0)))


def _dijkstra_delay_path(G: nx.DiGraph, start: int, target: int) -> tuple[list[int], float]:
    path = nx.shortest_path(G, start, target, weight=_edge_delay)
    cost = 0.0
    for source, target_node in zip(path, path[1:]):
        cost += float(G[source][target_node].get("delay_ms", 1))
    return [int(node) for node in path], float(cost)


def _sample_start_target_pairs(G: nx.DiGraph, *, num_pairs: int, seed: int) -> list[tuple[int, int]]:
    nodes = list(G.nodes())
    rng = __import__("random").Random(seed)
    pairs: list[tuple[int, int]] = []
    if len(nodes) < 2:
        return pairs
    attempts = max(num_pairs * 8, 32)
    for _ in range(attempts):
        start, target = rng.sample(nodes, 2)
        if start == target:
            continue
        pairs.append((int(start), int(target)))
        if len(pairs) >= num_pairs:
            break
    return pairs


def _save_graph_json(G: nx.DiGraph, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "directed": True,
        "graph": dict(G.graph),
        "nodes": [{"id": node, **dict(attrs)} for node, attrs in G.nodes(data=True)],
        "edges": [
            {"source": source, "target": target, **dict(attrs)}
            for source, target, attrs in G.edges(data=True)
        ],
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve_path(value, config_dir: Path, *, for_output: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"path value must be string or null, got {type(value).__name__}")
    path = Path(value).expanduser()
    if path.is_absolute():
        return str(path)
    config_relative = config_dir / path
    repo_relative = REPO_ROOT / path
    if for_output:
        return str(repo_relative)
    if config_relative.exists():
        return str(config_relative)
    return str(repo_relative)


def _load_config(config_path: str) -> dict:
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        cwd_candidate = Path.cwd() / path
        repo_candidate = REPO_ROOT / path
        path = cwd_candidate if cwd_candidate.exists() else repo_candidate
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config must be a mapping")
    for section in ["map", "planning", "traffic", "congestion", "loihi", "visualization", "output"]:
        if section not in raw:
            raise ValueError(f"config missing section: {section}")

    config_dir = path.parent
    config = {key: dict(raw[key]) for key in raw}
    config["map"]["root_dir"] = _resolve_path(config["map"].get("root_dir"), config_dir)
    config["map"]["netxml_path"] = _resolve_path(config["map"].get("netxml_path"), config_dir)
    config["map"]["sumocfg_path"] = _resolve_path(config["map"].get("sumocfg_path"), config_dir)
    config["loihi"]["config_path"] = _resolve_path(config["loihi"].get("config_path"), config_dir)
    config["output"]["output_dir"] = _resolve_path(
        config["output"].get("output_dir"), config_dir, for_output=True
    )
    return config


def _select_demo_pair(G, seed: int) -> tuple[int, int, list[int], float]:
    candidates = _sample_start_target_pairs(G, num_pairs=min(64, max(1, G.number_of_nodes() * 2)), seed=seed)
    best: tuple[int, int, list[int], float] | None = None
    best_score: tuple[float, int] | None = None
    for start, target in candidates:
        try:
            path, cost = _dijkstra_delay_path(G, start, target)
        except Exception:
            continue
        if len(path) < 2:
            continue
        score = (float(cost), len(path))
        if best is None or score > best_score:
            best = (int(start), int(target), list(path), float(cost))
            best_score = score
    if best is None:
        raise ValueError("unable to find a reachable demo pair")
    return best


def _resolve_node_id(G, value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        if value not in G:
            raise ValueError(f"configured node {value} not found in planning graph")
        return int(value)
    text = str(value)
    sumo_to_int = G.graph.get("sumo_node_id_to_node_id", {})
    if text in sumo_to_int:
        return int(sumo_to_int[text])
    try:
        node_id = int(text)
    except ValueError as exc:
        raise ValueError(f"configured node {value!r} is neither graph node id nor SUMO junction id") from exc
    if node_id not in G:
        raise ValueError(f"configured node {node_id} not found in planning graph")
    return int(node_id)


def _plan_route(G, start: int, target: int, loihi_config: dict, seed: int) -> dict:
    snn_graph = digraph_to_snn(G)
    wavefront = run_loihi_wavefront(
        snn_graph,
        start,
        target,
        delay_attr="delay_ms",
        threshold=float(loihi_config.get("threshold", 1.0)),
        weight=float(loihi_config.get("weight", 1.1)),
        refractory_ms=int(loihi_config.get("refractory_ms", 1000)),
        seed=int(loihi_config.get("seed", seed)),
    )
    if not wavefront.get("success"):
        return {
            "success": False,
            "error": wavefront.get("error"),
            "wavefront": wavefront,
            "path": None,
            "sumo_route": None,
            "path_cost": None,
        }
    path = snn_output_to_path(snn_graph, wavefront, start, target, delay_attr="delay_ms")
    sumo_route = path_to_sumo_route(G, path)
    return {
        "success": True,
        "error": None,
        "wavefront": wavefront,
        "path": path,
        "sumo_route": sumo_route,
        "path_cost": float(compute_path_cost(snn_graph, path, weight="delay_ms")),
    }


def _route_edges(route: list[int] | None) -> list[tuple[int, int]]:
    if not route:
        return []
    return [(int(source), int(target)) for source, target in zip(route, route[1:])]


def _has_route_conflict(G, route: list[int] | None, congested_edges, blocked_edges) -> bool:
    route_edge_set = set(_route_edges(route))
    if not route_edge_set:
        return True
    blocked = set(blocked_edges or [])
    congested = set(congested_edges or [])
    if route_edge_set & blocked:
        return True
    if route_edge_set & congested:
        return True
    for source, target in route_edge_set:
        if not G.has_edge(source, target) or G[source][target].get("state") == "blocked":
            return True
    return False


def _jsonable_edges(edges) -> list[list]:
    return [[source, target] for source, target in edges or []]


def _draw_wavefront_frames(
    *,
    geometry,
    graph,
    output_dir: Path,
    step: int,
    plan_result: dict,
    current_node: int,
    target_node: int,
    vehicle_positions: list[dict],
    congestion_state: dict,
    max_background_edges,
    num_frames: int,
    max_plans: int,
    plan_index: int,
) -> list[str]:
    if num_frames <= 0 or plan_index >= max_plans or not plan_result.get("success"):
        return []
    frames_dir = output_dir / "wavefront_frames" / f"step_{step:03d}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[str] = []
    route_segments = plan_result["sumo_route"]["segments"]
    for frame_idx, wave_time in enumerate(wavefront_frame_times(plan_result["wavefront"], num_frames)):
        frame_path = frames_dir / f"wave_{frame_idx:03d}.png"
        draw_sumo_dynamic_frame(
            geometry,
            graph,
            save_path=str(frame_path),
            route_segments=route_segments,
            wavefront_result=plan_result["wavefront"],
            wavefront_time_ms=wave_time,
            vehicle_positions=vehicle_positions,
            congested_edges=congestion_state["congested_edges"],
            blocked_edges=congestion_state["blocked_edges"],
            current_node=current_node,
            target_node=target_node,
            title=f"step {step} Brian2Loihi wavefront t={wave_time:.1f} ms",
            max_background_edges=max_background_edges,
            zoom_to_route=True,
        )
        frame_paths.append(str(frame_path))
    write_gif(frame_paths, output_dir / "wavefront_gifs" / f"step_{step:03d}.gif")
    return frame_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Run dynamic MoST routing over original SUMO geometry.")
    parser.add_argument("--config", required=True, help="Path to configs/dynamic_sumo_overlay.yaml")
    parser.add_argument(
        "--skip-sumo-load-check",
        action="store_true",
        help="Skip headless SUMO map loading. Use only when debugging the software pipeline without a working SUMO binary.",
    )
    args = parser.parse_args()

    config = _load_config(args.config)
    output_dir = Path(config["output"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    netxml_path = config["map"].get("netxml_path")
    if netxml_path is None:
        netxml_path = str(find_sumo_netxml(config["map"]["root_dir"]))

    sumo_load_check = None
    if bool(config["map"].get("require_sumo_load_check", True)) and not args.skip_sumo_load_check:
        sumo_load_check = run_sumo_map_load_check(
            netxml_path=netxml_path,
            sumocfg_path=config["map"].get("sumocfg_path"),
        )
        if not sumo_load_check["success"]:
            raise RuntimeError(f"SUMO map load check failed: {sumo_load_check['stderr']}")

    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        raise RuntimeError(f"Brian2Loihi is required: {backend_check['error']}")

    planning_cfg = config["planning"]
    traffic_cfg = config["traffic"]
    congestion_cfg = config["congestion"]
    visualization_cfg = config["visualization"]
    seed = int(planning_cfg.get("seed", 0))

    graph, geometry = most_to_digraph(
        netxml_path,
        min_delay_ms=int(planning_cfg.get("min_delay_ms", 1)),
        max_delay_ms=int(planning_cfg.get("max_delay_ms", 10)),
        max_nodes=planning_cfg.get("max_nodes"),
        seed=seed,
        use_travel_time_if_speed_available=bool(
            planning_cfg.get("use_travel_time_if_speed_available", True)
        ),
    )
    _save_graph_json(graph, output_dir / "initial_temporary_planning_graph.json")

    start = _resolve_node_id(graph, planning_cfg.get("start"))
    target = _resolve_node_id(graph, planning_cfg.get("target"))
    dijkstra_hint = None
    dijkstra_cost = None
    if start is None or target is None:
        start, target, dijkstra_hint, dijkstra_cost = _select_demo_pair(graph, seed=seed)
    else:
        dijkstra_hint, dijkstra_cost = _dijkstra_delay_path(graph, start, target)

    vehicles = spawn_random_traffic_vehicles(
        graph,
        num_vehicles=int(traffic_cfg.get("num_vehicles", 160)),
        seed=int(traffic_cfg.get("seed", seed)),
        min_speed=float(traffic_cfg.get("min_speed", 0.18)),
        max_speed=float(traffic_cfg.get("max_speed", 0.42)),
        num_hotspots=int(traffic_cfg.get("num_hotspots", 6)),
        hotspot_vehicle_fraction=float(traffic_cfg.get("hotspot_vehicle_fraction", 0.45)),
    )
    loihi_config = load_brian2loihi_config(config["loihi"]["config_path"])

    current_node = int(start)
    target_node = int(target)
    route: list[int] | None = None
    route_index = 0
    last_plan_result: dict | None = None
    step_logs: list[dict] = []
    dynamic_frame_paths: list[str] = []
    wavefront_frame_paths: list[str] = []
    num_successful_replans = 0
    num_failed_replans = 0
    wavefront_plan_index = 0

    max_steps = int(planning_cfg.get("max_steps", 18))
    replan_interval = int(planning_cfg.get("replan_interval", 3))

    for step in range(max_steps):
        if step > 0:
            advance_traffic_vehicles(graph, vehicles, seed=seed + step)

        congestion_state = apply_traffic_congestion(
            graph,
            vehicles,
            congested_density=float(congestion_cfg.get("congested_density", 0.55)),
            blocked_density=float(congestion_cfg.get("blocked_density", 1.0)),
            delay_factor=float(congestion_cfg.get("delay_factor", 3.0)),
            vehicles_per_lane_capacity=float(congestion_cfg.get("vehicles_per_lane_capacity", 3.0)),
            threshold_penalty_ms=float(congestion_cfg.get("threshold_penalty_ms", 2.0)),
        )
        vehicle_positions = traffic_vehicle_positions(graph, vehicles)

        should_replan = (
            route is None
            or step == 0
            or (replan_interval > 0 and step % replan_interval == 0)
            or _has_route_conflict(
                graph,
                route[route_index:] if route else None,
                congestion_state["congested_edges"],
                congestion_state["blocked_edges"],
            )
        )
        replan_reason = "interval_or_congestion" if should_replan else "keep_route"

        planning_time_sec = None
        if should_replan:
            plan_start = time.perf_counter()
            plan_result = _plan_route(graph, current_node, target_node, loihi_config, seed=seed + step)
            planning_time_sec = time.perf_counter() - plan_start
            last_plan_result = plan_result
            if plan_result["success"]:
                route = [int(node) for node in plan_result["path"]]
                route_index = 0
                num_successful_replans += 1
                wavefront_frame_paths.extend(
                    _draw_wavefront_frames(
                        geometry=geometry,
                        graph=graph,
                        output_dir=output_dir,
                        step=step,
                        plan_result=plan_result,
                        current_node=current_node,
                        target_node=target_node,
                        vehicle_positions=vehicle_positions,
                        congestion_state=congestion_state,
                        max_background_edges=visualization_cfg.get("max_background_edges"),
                        num_frames=int(visualization_cfg.get("wavefront_frames_per_replan", 5)),
                        max_plans=int(visualization_cfg.get("max_wavefront_replans", 3)),
                        plan_index=wavefront_plan_index,
                    )
                )
                wavefront_plan_index += 1
            else:
                num_failed_replans += 1

        sumo_route = None
        route_segments = None
        if route:
            try:
                sumo_route = path_to_sumo_route(graph, route[route_index:])
                route_segments = sumo_route["segments"]
            except Exception:
                sumo_route = None
                route_segments = None

        if bool(visualization_cfg.get("save_frames", True)):
            frames_dir = output_dir / "dynamic_frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            frame_path = frames_dir / f"step_{step:03d}.png"
            draw_sumo_dynamic_frame(
                geometry,
                graph,
                save_path=str(frame_path),
                route_segments=route_segments,
                wavefront_result=last_plan_result.get("wavefront") if last_plan_result else None,
                wavefront_time_ms=(
                    last_plan_result.get("wavefront", {}).get("target_arrival_time_ms")
                    if last_plan_result
                    else None
                ),
                vehicle_positions=vehicle_positions,
                congested_edges=congestion_state["congested_edges"],
                blocked_edges=congestion_state["blocked_edges"],
                current_node=current_node,
                target_node=target_node,
                title=f"dynamic SUMO navigation step {step}",
                max_background_edges=visualization_cfg.get("max_background_edges"),
                zoom_to_route=bool(visualization_cfg.get("zoom_to_route", True)),
            )
            dynamic_frame_paths.append(str(frame_path))

        next_edge = None
        moved = False
        if route and route_index < len(route) - 1:
            next_edge = (int(route[route_index]), int(route[route_index + 1]))
            if graph.has_edge(*next_edge) and graph[next_edge[0]][next_edge[1]].get("state") != "blocked":
                route_index += 1
                current_node = int(route[route_index])
                moved = True

        step_logs.append(
            {
                "step": int(step),
                "current_node": int(current_node),
                "target_node": int(target_node),
                "current_sumo_node_id": graph.nodes[current_node].get("sumo_node_id"),
                "target_sumo_node_id": graph.nodes[target_node].get("sumo_node_id"),
                "replanned": bool(should_replan),
                "replan_reason": replan_reason,
                "planning_success": None if not should_replan else bool(last_plan_result and last_plan_result["success"]),
                "planning_time_sec": planning_time_sec,
                "moved": moved,
                "next_edge": list(next_edge) if next_edge else None,
                "route": route,
                "remaining_route": route[route_index:] if route else None,
                "sumo_edge_ids": sumo_route["sumo_edge_ids"] if sumo_route else [],
                "num_congested_edges": int(congestion_state["num_congested_edges"]),
                "num_blocked_edges": int(congestion_state["num_blocked_edges"]),
                "congested_edges": _jsonable_edges(congestion_state["congested_edges"]),
                "blocked_edges": _jsonable_edges(congestion_state["blocked_edges"]),
                "num_vehicles": len(vehicles),
                "num_spikes": int(
                    last_plan_result.get("wavefront", {}).get("num_spikes", 0) if last_plan_result else 0
                ),
                "target_arrival_time_ms": (
                    last_plan_result.get("wavefront", {}).get("target_arrival_time_ms")
                    if last_plan_result
                    else None
                ),
                "path_cost": last_plan_result.get("path_cost") if last_plan_result else None,
                "arrived": current_node == target_node,
            }
        )
        if current_node == target_node:
            break

    if dynamic_frame_paths:
        write_gif(dynamic_frame_paths, output_dir / "dynamic_navigation.gif")
    if wavefront_frame_paths:
        write_gif(wavefront_frame_paths, output_dir / "wavefront_all.gif")

    write_json([vehicle.to_dict() for vehicle in vehicles], output_dir / "final_background_vehicles.json")
    write_json(step_logs, output_dir / "dynamic_step_logs.json")
    if last_plan_result and last_plan_result.get("sumo_route"):
        write_json(last_plan_result["sumo_route"], output_dir / "latest_sumo_route.json")

    summary = {
        "success": bool(step_logs),
        "arrived": bool(step_logs[-1]["arrived"]) if step_logs else False,
        "netxml_path": str(netxml_path),
        "sumocfg_path": config["map"].get("sumocfg_path"),
        "sumo_load_check": sumo_load_check,
        "backend_check": backend_check,
        "start": int(start),
        "target": int(target),
        "start_sumo_node_id": graph.nodes[int(start)].get("sumo_node_id"),
        "target_sumo_node_id": graph.nodes[int(target)].get("sumo_node_id"),
        "dijkstra_hint_path": dijkstra_hint,
        "dijkstra_hint_cost": float(dijkstra_cost) if dijkstra_cost is not None else None,
        "num_graph_nodes": graph.number_of_nodes(),
        "num_graph_edges": graph.number_of_edges(),
        "num_vehicles": len(vehicles),
        "num_steps": len(step_logs),
        "num_successful_replans": int(num_successful_replans),
        "num_failed_replans": int(num_failed_replans),
        "total_spikes": int(sum(int(log.get("num_spikes", 0) or 0) for log in step_logs)),
        "graph_is_temporary": True,
        "visualization_source": "original_sumo_geometry",
        "dynamic_frames_dir": str(output_dir / "dynamic_frames"),
        "wavefront_frames_dir": str(output_dir / "wavefront_frames"),
        "dynamic_navigation_gif": str(output_dir / "dynamic_navigation.gif"),
        "wavefront_all_gif": str(output_dir / "wavefront_all.gif"),
        "dynamic_step_logs_json": str(output_dir / "dynamic_step_logs.json"),
        "latest_sumo_route_json": str(output_dir / "latest_sumo_route.json"),
    }
    write_json(summary, output_dir / "dynamic_summary.json")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
