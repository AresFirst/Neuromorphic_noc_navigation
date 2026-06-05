"""Run the dynamic closed-loop city navigation demo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import dijkstra_delay_path, sample_start_target_pairs
from graph.graph_io import load_graph_json
from loihi_planner.backend_check import check_brian2loihi_available
from nmn.dynamic.closed_loop import (
    generate_congestion_events_on_route,
    run_dynamic_navigation_loop,
)
from nmn.dynamic.visualization import draw_dynamic_state
from nmn.loihi.parent_trace import infer_parent_trace_from_spikes
from nmn.loihi.path_compare import compute_path_cost
from nmn.loihi.path_reconstruction import reconstruct_path_from_parent
from nmn.loihi.wavefront import run_loihi_wavefront
from nmn.dynamic.snn_cost_adapter import prepare_graph_for_snn_planning


def _resolve_path(value, config_dir: Path, *, for_output: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"path value must be a string or null, got {type(value).__name__}")
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
        if cwd_candidate.exists():
            path = cwd_candidate
        elif repo_candidate.exists():
            path = repo_candidate
        else:
            path = cwd_candidate
    if not path.exists():
        raise FileNotFoundError(f"dynamic navigation config not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("dynamic navigation config must be a mapping")
    for section in ["graph", "vehicle", "dynamic", "loihi", "visualization", "output"]:
        if section not in raw:
            raise ValueError(f"dynamic navigation config missing section: {section}")

    config_dir = path.parent
    config = dict(raw)
    config["graph"] = dict(raw["graph"])
    config["vehicle"] = dict(raw["vehicle"])
    config["dynamic"] = dict(raw["dynamic"])
    config["loihi"] = dict(raw["loihi"])
    config["visualization"] = dict(raw["visualization"])
    config["output"] = dict(raw["output"])

    config["graph"]["graph_json"] = _resolve_path(config["graph"].get("graph_json"), config_dir)
    config["loihi"]["config_path"] = _resolve_path(config["loihi"].get("config_path"), config_dir)
    config["output"]["output_dir"] = _resolve_path(
        config["output"].get("output_dir"), config_dir, for_output=True
    )
    return config


def _select_demo_pair(G, seed: int) -> tuple[int, int]:
    candidates = sample_start_target_pairs(G, num_pairs=min(32, max(1, G.number_of_nodes() * 2)), seed=seed)
    best: tuple[int, int, list[int], float] | None = None
    best_score: tuple[float, int] | None = None
    for start, target in candidates:
        try:
            path, cost = dijkstra_delay_path(G, start, target, delay_attr="delay_ms")
        except Exception:
            continue
        if len(path) < 2:
            continue
        score = (float(cost), len(path))
        if best is None or score > best_score:
            best = (int(start), int(target), list(path), float(cost))
            best_score = score
    if best is None:
        raise ValueError("unable to find a valid start/target pair on the graph")
    return best[0], best[1]


def _plan_initial_route(G, start: int, target: int, loihi_config: dict, seed: int) -> tuple[list[int], dict]:
    G_snn = prepare_graph_for_snn_planning(G)
    wavefront = run_loihi_wavefront(
        G_snn,
        start,
        target,
        delay_attr="delay_ms",
        threshold=float(loihi_config.get("threshold", 1.0)),
        weight=float(loihi_config.get("weight", 1.1)),
        refractory_ms=int(loihi_config.get("refractory_ms", 1000)),
        seed=int(loihi_config.get("seed", seed)),
    )
    if not wavefront.get("success"):
        raise RuntimeError(f"Initial Brian2Loihi planning failed: {wavefront.get('error')}")

    parent_trace = infer_parent_trace_from_spikes(
        G_snn,
        wavefront["spike_times_by_neuron"],
        start,
        delay_attr="delay_ms",
    )
    route = reconstruct_path_from_parent(parent_trace, start, target)
    return route, wavefront


def _route_events_from_config(
    G,
    route: list[int],
    dynamic_cfg: dict,
    seed: int,
) -> list:
    total_events = int(dynamic_cfg.get("num_random_congestion_events", 3))
    congestion_on_initial_route = bool(dynamic_cfg.get("congestion_on_initial_route", True))
    congestion_mode = str(dynamic_cfg.get("congestion_mode", "delay"))
    duration_steps = int(dynamic_cfg.get("congestion_duration_steps", 20))
    delay_factor = float(dynamic_cfg.get("default_delay_factor", 5.0))

    route_events: list = []
    random_events: list = []

    if congestion_on_initial_route:
        total_events = max(1, total_events)
        route_event_count = 1
        route_events = generate_congestion_events_on_route(
            route=route,
            start_step=1,
            duration_steps=duration_steps,
            delay_factor=delay_factor,
            mode=congestion_mode,
            num_events=route_event_count,
            seed=seed,
        )
        if not route_events:
            raise ValueError("initial route is too short to place a congestion event")
        random_count = max(0, total_events - route_event_count)
    else:
        random_count = max(0, total_events)

    if random_count > 0:
        random_events = []
        all_edges = set((event.edge_u, event.edge_v) for event in route_events)
        candidates = [edge for edge in G.edges() if tuple(edge) not in all_edges]
        if candidates:
            from random import Random

            rng = Random(seed)
            if random_count <= len(candidates):
                selected = rng.sample(candidates, random_count)
            else:
                selected = [rng.choice(candidates) for _ in range(random_count)]
            for edge_u, edge_v in selected:
                threshold_penalty = 0.0
                event_delay_factor = delay_factor
                event_mode = congestion_mode
                if event_mode == "threshold":
                    threshold_penalty = delay_factor
                    event_delay_factor = 1.0
                from nmn.dynamic.congestion import CongestionEvent

                random_events.append(
                    CongestionEvent(
                        edge_u=int(edge_u),
                        edge_v=int(edge_v),
                        start_step=1,
                        end_step=1 + duration_steps,
                        delay_factor=event_delay_factor,
                        threshold_penalty=threshold_penalty,
                        mode=event_mode,
                    )
                )

    return route_events + random_events


def _final_preview(
    graph,
    summary: dict,
    step_logs: list[dict],
    output_dir: Path,
) -> None:
    preview_path = output_dir / "preview_final.png"
    final_log = step_logs[-1] if step_logs else {}
    draw_dynamic_state(
        graph,
        vehicle_node=int(final_log.get("current_node", summary.get("start"))),
        target_node=int(summary["target"]),
        current_route=summary.get("final_route"),
        active_congested_edges=final_log.get("active_congested_edges", []),
        step=int(final_log.get("step", 0)),
        save_path=str(preview_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the dynamic city navigation demo.")
    parser.add_argument("--config", required=True, help="Path to configs/dynamic_city_navigation.yaml")
    args = parser.parse_args()

    config = _load_config(args.config)
    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        raise RuntimeError(
            "Brian2Loihi is required for the dynamic city navigation demo: "
            f"{backend_check['error']}"
        )

    output_dir = Path(config["output"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    graph_json = config["graph"].get("graph_json")
    fallback = bool(config["graph"].get("fallback_to_synthetic_if_missing", False))
    if graph_json and Path(graph_json).exists():
        graph = load_graph_json(graph_json)
        graph_source = "graph_json"
    elif fallback:
        graph = generate_complex_graph("community", 64, seed=int(config["vehicle"].get("seed", 0)))
        graph_source = "synthetic_fallback"
    else:
        raise FileNotFoundError(
            f"graph_json not found: {graph_json}. Run first: "
            "python experiments/run_most_import.py --config configs/most.yaml"
        )

    graph.graph["max_draw_edges"] = int(config["visualization"].get("max_draw_edges", 3000))

    vehicle_start = config["vehicle"].get("start")
    vehicle_target = config["vehicle"].get("target")
    seed = int(config["vehicle"].get("seed", 0))
    if vehicle_start is None or vehicle_target is None:
        vehicle_start, vehicle_target = _select_demo_pair(graph, seed=seed)
    else:
        vehicle_start = int(vehicle_start)
        vehicle_target = int(vehicle_target)

    dynamic_cfg = config["dynamic"]
    loihi_cfg = {}
    loihi_config_path = config["loihi"].get("config_path")
    if loihi_config_path:
        loihi_cfg = yaml.safe_load(Path(loihi_config_path).read_text(encoding="utf-8")) or {}

    initial_route: list[int] | None = None
    congestion_events = []
    if bool(dynamic_cfg.get("congestion_on_initial_route", True)):
        initial_route, _ = _plan_initial_route(graph, vehicle_start, vehicle_target, loihi_cfg, seed)
        congestion_events = _route_events_from_config(graph, initial_route, dynamic_cfg, seed=seed)
    else:
        total_events = int(dynamic_cfg.get("num_random_congestion_events", 3))
        if total_events > 0:
            from nmn.dynamic.congestion import CongestionEvent
            from random import Random

            duration_steps = int(dynamic_cfg.get("congestion_duration_steps", 20))
            delay_factor = float(dynamic_cfg.get("default_delay_factor", 5.0))
            congestion_mode = str(dynamic_cfg.get("congestion_mode", "delay"))
            rng = Random(seed)
            candidates = list(graph.edges())
            if candidates:
                if total_events <= len(candidates):
                    selected = rng.sample(candidates, total_events)
                else:
                    selected = [rng.choice(candidates) for _ in range(total_events)]
                for edge_u, edge_v in selected:
                    threshold_penalty = 0.0
                    event_delay_factor = delay_factor
                    event_mode = congestion_mode
                    if event_mode == "threshold":
                        threshold_penalty = delay_factor
                        event_delay_factor = 1.0
                    congestion_events.append(
                        CongestionEvent(
                            edge_u=int(edge_u),
                            edge_v=int(edge_v),
                            start_step=1,
                            end_step=1 + duration_steps,
                            delay_factor=event_delay_factor,
                            threshold_penalty=threshold_penalty,
                            mode=event_mode,
                        )
                    )

    if bool(dynamic_cfg.get("congestion_on_initial_route", True)) and not congestion_events:
        raise RuntimeError("No congestion events could be generated on the initial route")

    loop_result = run_dynamic_navigation_loop(
        G=graph,
        start=vehicle_start,
        target=vehicle_target,
        congestion_events=congestion_events,
        max_steps=int(dynamic_cfg.get("max_steps", 100)),
        replan_interval=int(dynamic_cfg.get("replan_interval", 5)),
        loihi_config=loihi_cfg,
        output_dir=str(output_dir),
        visualize=bool(config["visualization"].get("visualize", True)),
        save_frames=bool(config["visualization"].get("save_frames", True)),
        seed=seed,
    )

    summary = dict(loop_result["summary"])
    summary["graph_source"] = graph_source
    summary["backend_check"] = backend_check

    congestion_events_path = output_dir / "congestion_events.json"
    congestion_events_path.write_text(
        json.dumps([event.to_dict() for event in congestion_events], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    final_route_path = output_dir / "final_route.json"
    final_route_path.write_text(
        json.dumps(
            {
                "start": int(vehicle_start),
                "target": int(vehicle_target),
                "final_route": summary.get("final_route", []),
                "arrived": summary.get("arrived", False),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _final_preview(graph, summary, loop_result["step_logs"], output_dir)

    summary_path = output_dir / "dynamic_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
