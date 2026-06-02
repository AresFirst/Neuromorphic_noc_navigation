"""MoST 软件闭环导航演示。

这个脚本把流程串成一条纯软件链路：
MoST Scenario -> NetworkX DiGraph -> Loihi 风格 SNN -> 波前路由 -> 路径重建 -> 全图可视化。

不依赖 Noxim。输出的是可复现的图、结果表和完整地图上的路径对比图。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dataset_import.dataset_loader import load_public_road_dataset_as_graph
from experiments.visualize_path_comparison import visualize_path_comparison
from graph.graph_baseline import dijkstra_delay_path, sample_start_target_pairs
from graph.graph_io import save_graph_json, save_results_json
from graph.graph_metrics import compute_graph_metrics
from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_config import load_brian2loihi_config
from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compare_snn_path_with_dijkstra
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from loihi_planner.wavefront_reference import event_driven_wavefront


def _select_demo_pair(G, seed: int, candidate_count: int = 24) -> tuple[int, int, list[int], float]:
    """挑选一条更适合做全图展示的路径。

    从若干随机候选里，选择 Dijkstra 代价最高且可达的 pair，
    这样路径更容易跨越城市地图的多个区域。
    """
    candidates = sample_start_target_pairs(G, num_pairs=candidate_count, seed=seed)
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
        raise ValueError("unable to find a valid demo pair on the imported road graph")
    return best


def _load_graph(graph_path: str | None, config_path: str):
    if graph_path:
        from graph.graph_io import load_graph_json

        return load_graph_json(graph_path), "loaded_graph_json"
    return load_public_road_dataset_as_graph(config_path), "imported_from_most"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a software-only MoST navigation loop.")
    parser.add_argument("--config", required=True, help="Path to configs/most.yaml.")
    parser.add_argument("--loihi-config", default="configs/brian2loihi.yaml", help="Brian2Loihi config.")
    parser.add_argument("--graph", default=None, help="Optional pre-imported graph.json.")
    parser.add_argument("--output", required=True, help="Output directory.")
    parser.add_argument("--num-pairs", type=int, default=3, help="Number of navigation pairs to evaluate.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed.")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        raise RuntimeError(f"Brian2Loihi is required for this navigation loop: {backend_check['error']}")

    config = load_brian2loihi_config(args.loihi_config)
    graph, graph_source = _load_graph(args.graph, args.config)

    graph_json_path = output_dir / "graph.json"
    graph_metrics_path = output_dir / "graph_metrics.json"
    navigation_csv_path = output_dir / "navigation_results.csv"
    comparison_png_path = output_dir / "navigation_path_compare.png"
    summary_path = output_dir / "summary.json"

    save_graph_json(graph, str(graph_json_path))
    metrics = compute_graph_metrics(graph)
    save_results_json(metrics, str(graph_metrics_path))

    demo_start, demo_target, demo_dijkstra_path, demo_dijkstra_cost = _select_demo_pair(graph, seed=args.seed)
    candidate_pairs = [(demo_start, demo_target)]
    if args.num_pairs > 1:
        for start, target in sample_start_target_pairs(graph, num_pairs=args.num_pairs - 1, seed=args.seed):
            if (start, target) != (demo_start, demo_target):
                candidate_pairs.append((start, target))

    rows: list[dict[str, object]] = []
    for pair_id, (start, target) in enumerate(candidate_pairs):
        reference = event_driven_wavefront(graph, start, target, delay_attr="delay_ms")
        loihi = run_loihi_wavefront(
            graph,
            start,
            target,
            delay_attr="delay_ms",
            sim_time_ms=None,
            threshold=float(config["threshold"]),
            weight=float(config["weight"]),
            refractory_ms=int(config["refractory_ms"]),
            seed=int(args.seed),
        )

        if not loihi.get("success"):
            rows.append(
                {
                    "pair_id": pair_id,
                    "start": start,
                    "target": target,
                    "reference_arrival_ms": reference.get("target_arrival_time"),
                    "loihi_arrival_ms": loihi.get("target_arrival_time_ms"),
                    "arrival_error_ms": None,
                    "snn_path": None,
                    "dijkstra_path": None,
                    "same_path": False,
                    "same_cost": False,
                    "optimality_ratio": None,
                    "num_spikes": int(loihi.get("num_spikes", 0)),
                    "success": False,
                    "error": loihi.get("error"),
                }
            )
            continue

        parent_trace = infer_parent_trace_from_spikes(
            graph, loihi["spike_times_by_neuron"], start, delay_attr="delay_ms"
        )
        snn_path = reconstruct_path_from_parent(parent_trace, start, target)
        dijkstra_path, dijkstra_cost = dijkstra_delay_path(graph, start, target, delay_attr="delay_ms")
        compare = compare_snn_path_with_dijkstra(graph, snn_path, dijkstra_path, weight="delay_ms")

        reference_arrival = reference.get("target_arrival_time")
        loihi_arrival = loihi.get("target_arrival_time_ms")
        arrival_error = None
        if reference_arrival is not None and loihi_arrival is not None:
            arrival_error = abs(float(reference_arrival) - float(loihi_arrival))

        rows.append(
            {
                "pair_id": pair_id,
                "start": start,
                "target": target,
                "reference_arrival_ms": reference_arrival,
                "loihi_arrival_ms": loihi_arrival,
                "arrival_error_ms": arrival_error,
                "snn_path": json.dumps(snn_path),
                "dijkstra_path": json.dumps(dijkstra_path),
                "same_path": compare["same_path"],
                "same_cost": compare["same_cost"],
                "optimality_ratio": compare["optimality_ratio"],
                "num_spikes": int(loihi.get("num_spikes", 0)),
                "success": bool(loihi.get("success")) and bool(compare["same_cost"]),
                "error": None,
            }
        )

    import pandas as pd

    results_df = pd.DataFrame.from_records(rows)
    results_df.to_csv(navigation_csv_path, index=False)

    # 让全图可视化直接用 pair_id=0 的结果，这条路径是最适合展示的 demo pair。
    visualize_path_comparison(
        graph_path=str(graph_json_path),
        results_csv=str(navigation_csv_path),
        pair_id=0,
        output_path=str(comparison_png_path),
    )

    success_rows = [row for row in rows if row["success"]]
    arrival_errors = [row["arrival_error_ms"] for row in success_rows if row["arrival_error_ms"] is not None]
    optimality_values = [row["optimality_ratio"] for row in success_rows if row["optimality_ratio"] is not None]

    summary = {
        "graph_source": graph_source,
        "dataset_name": graph.graph.get("dataset_name"),
        "dataset_type": graph.graph.get("dataset_type"),
        "netxml_path": graph.graph.get("netxml_path"),
        "demo_pair": {"start": demo_start, "target": demo_target, "dijkstra_cost": demo_dijkstra_cost},
        "num_pairs": len(rows),
        "num_success": len(success_rows),
        "success_rate": (len(success_rows) / len(rows)) if rows else 0.0,
        "mean_arrival_error_ms": float(sum(arrival_errors) / len(arrival_errors)) if arrival_errors else None,
        "max_arrival_error_ms": float(max(arrival_errors)) if arrival_errors else None,
        "mean_optimality_ratio": float(sum(optimality_values) / len(optimality_values)) if optimality_values else None,
        "graph_json": str(graph_json_path),
        "graph_metrics_json": str(graph_metrics_path),
        "navigation_results_csv": str(navigation_csv_path),
        "navigation_path_compare_png": str(comparison_png_path),
        "backend_check": backend_check,
    }
    save_results_json(summary, str(summary_path))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
