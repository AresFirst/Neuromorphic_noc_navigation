"""Week2 实验: Dijkstra 基线实验。

生成复杂拓扑图，运行 Dijkstra 最短路径作为传统算法基线，
计算图结构指标，输出可视化。

这是后续 SNN 波前路由实验的"最优解"参考。

CLI 参数:
    --config: 图生成配置 YAML 路径 (如 configs/graph.yaml)
    --output: 结果输出目录

输出文件:
    graph.json: 生成的图
    graph_metrics.json: 图结构指标
    dijkstra_results.csv: 所有起止点对的 Dijkstra 结果
    example_path.png: 一条示例路径的可视化
    summary.json: 汇总指标
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import evaluate_dijkstra_pairs, sample_start_target_pairs, dijkstra_path
from graph.graph_io import save_graph_json, save_results_json
from graph.graph_metrics import compute_graph_metrics
from graph.visualization import plot_graph_with_path


def main() -> int:
    """运行 Week2 Dijkstra 基线实验。

    Returns:
        退出码 0。
    """
    parser = argparse.ArgumentParser(description="Run the graph baseline pipeline.")
    parser.add_argument("--config", required=True, help="Path to the YAML graph config.")
    parser.add_argument("--output", required=True, help="Output directory.")
    args = parser.parse_args()

    config_path = Path(args.config)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载配置
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    graph_type = config.get("graph_type", "community")
    num_nodes = int(config.get("num_nodes", 200))
    seed = int(config.get("seed", 0))
    num_pairs = int(config.get("num_pairs", 20))
    min_delay_ms = int(config.get("min_delay_ms", 1))
    max_delay_ms = int(config.get("max_delay_ms", 10))

    # 步骤 1: 生成图
    graph = generate_complex_graph(
        graph_type=graph_type, num_nodes=num_nodes, seed=seed,
        directed=True, ensure_strongly_connected=True,
        min_delay_ms=min_delay_ms, max_delay_ms=max_delay_ms,
    )

    # 步骤 2: 保存图和指标
    save_graph_json(graph, str(output_dir / "graph.json"))
    metrics = compute_graph_metrics(graph)
    save_results_json(metrics, str(output_dir / "graph_metrics.json"))

    # 步骤 3: 采样起止点对并运行 Dijkstra
    pairs = sample_start_target_pairs(graph, num_pairs=num_pairs, seed=seed)
    results = evaluate_dijkstra_pairs(graph, pairs, weight="base_cost")
    results.to_csv(output_dir / "dijkstra_results.csv", index=False)

    # 步骤 4: 找一条有效路径做可视化示例
    example_path = None
    example_pair = None
    for start, target in pairs:
        try:
            example_path, _cost = dijkstra_path(graph, start, target, weight="base_cost")
            example_pair = {"start": start, "target": target}
            break
        except Exception:
            continue

    if example_path:
        plot_graph_with_path(
            graph, example_path, str(output_dir / "example_path.png"),
            title=f"{graph_type} baseline",
        )
    else:
        # 无有效路径时仍输出空图
        plot_graph_with_path(graph, None, str(output_dir / "example_path.png"),
                             title=f"{graph_type} baseline")

    # 步骤 5: 汇总
    summary = {
        "config": config,
        "metrics": metrics,
        "num_pairs": len(pairs),
        "example_pair": example_pair,
        "output_files": {
            "graph_json": str(output_dir / "graph.json"),
            "graph_metrics_json": str(output_dir / "graph_metrics.json"),
            "dijkstra_results_csv": str(output_dir / "dijkstra_results.csv"),
            "example_path_png": str(output_dir / "example_path.png"),
        },
    }
    save_results_json(summary, str(output_dir / "summary.json"))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
