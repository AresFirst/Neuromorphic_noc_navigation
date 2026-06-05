"""Route planning on MoST with final visualization on original SUMO geometry."""

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

from dataset_import.most_importer import find_most_netxml
from graph.graph_baseline import dijkstra_delay_path, sample_start_target_pairs
from graph.graph_io import save_graph_json
from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_config import load_brian2loihi_config
from nmn.loihi import compute_path_cost, run_loihi_wavefront
from nmn.sumo import (
    digraph_to_snn,
    draw_sumo_route_overlay,
    most_to_digraph,
    path_to_sumo_route,
    run_sumo_map_load_check,
    snn_output_to_path,
)


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
    for section in ["map", "planning", "loihi", "visualization", "output"]:
        if section not in raw:
            raise ValueError(f"config missing section: {section}")

    config_dir = path.parent
    config = {
        "map": dict(raw["map"]),
        "planning": dict(raw["planning"]),
        "loihi": dict(raw["loihi"]),
        "visualization": dict(raw["visualization"]),
        "output": dict(raw["output"]),
    }
    config["map"]["root_dir"] = _resolve_path(config["map"].get("root_dir"), config_dir)
    config["map"]["netxml_path"] = _resolve_path(config["map"].get("netxml_path"), config_dir)
    config["map"]["sumocfg_path"] = _resolve_path(config["map"].get("sumocfg_path"), config_dir)
    config["loihi"]["config_path"] = _resolve_path(config["loihi"].get("config_path"), config_dir)
    config["output"]["output_dir"] = _resolve_path(
        config["output"].get("output_dir"), config_dir, for_output=True
    )
    return config


def _select_demo_pair(G, seed: int) -> tuple[int, int, list[int], float]:
    candidates = sample_start_target_pairs(G, num_pairs=min(48, max(1, G.number_of_nodes() * 2)), seed=seed)
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MoST routing and draw route over original SUMO geometry.")
    parser.add_argument("--config", required=True, help="Path to configs/most_sumo_overlay.yaml")
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
        netxml_path = str(find_most_netxml(config["map"]["root_dir"]))

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

    start = _resolve_node_id(graph, planning_cfg.get("start"))
    target = _resolve_node_id(graph, planning_cfg.get("target"))
    dijkstra_hint = None
    if start is None or target is None:
        start, target, dijkstra_hint, dijkstra_cost = _select_demo_pair(graph, seed=seed)
    else:
        dijkstra_hint, dijkstra_cost = dijkstra_delay_path(graph, start, target, delay_attr="delay_ms")

    loihi_config = load_brian2loihi_config(config["loihi"]["config_path"])
    snn_graph = digraph_to_snn(graph)
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
    path = snn_output_to_path(snn_graph, wavefront, start, target, delay_attr="delay_ms")
    sumo_route = path_to_sumo_route(graph, path)
    path_cost = compute_path_cost(snn_graph, path, weight="delay_ms")

    route_json_path = output_dir / "sumo_route.json"
    route_json_path.write_text(json.dumps(sumo_route, indent=2, ensure_ascii=False), encoding="utf-8")

    graph_json_path = output_dir / "temporary_planning_graph.json"
    save_graph_json(graph, str(graph_json_path))

    overlay_png_path = output_dir / "route_overlay.png"
    draw_sumo_route_overlay(
        geometry,
        route_edge_ids=sumo_route["sumo_edge_ids"],
        route_segments=sumo_route["segments"],
        save_path=str(overlay_png_path),
        max_background_edges=config["visualization"].get("max_background_edges"),
        title="MoST / SUMO geometry route overlay",
    )

    summary = {
        "success": True,
        "netxml_path": str(netxml_path),
        "sumocfg_path": config["map"].get("sumocfg_path"),
        "sumo_load_check": sumo_load_check,
        "backend_check": backend_check,
        "start": int(start),
        "target": int(target),
        "start_sumo_node_id": graph.nodes[start].get("sumo_node_id"),
        "target_sumo_node_id": graph.nodes[target].get("sumo_node_id"),
        "num_graph_nodes": graph.number_of_nodes(),
        "num_graph_edges": graph.number_of_edges(),
        "graph_is_temporary": True,
        "visualization_source": "original_sumo_geometry",
        "path": path,
        "sumo_edge_ids": sumo_route["sumo_edge_ids"],
        "path_cost": float(path_cost),
        "dijkstra_hint_path": dijkstra_hint,
        "dijkstra_hint_cost": float(dijkstra_cost),
        "num_spikes": int(wavefront.get("num_spikes", 0) or 0),
        "target_arrival_time_ms": wavefront.get("target_arrival_time_ms"),
        "temporary_planning_graph_json": str(graph_json_path),
        "sumo_route_json": str(route_json_path),
        "route_overlay_png": str(overlay_png_path),
    }
    summary_path = output_dir / "planning_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
