"""Week5 实验: 动态起点定位与中继重规划。

测试 SNN 波前路由在动态场景下的鲁棒性:

1. 动态起点定位:
   从 5 个随机节点的精确坐标出发，验证 replan_from_position()
   能否正确将连续坐标定位到图节点并找到路径。

2. 边阻塞 (blocked edge) 重规划:
   - 找到一条基线路径
   - 阻塞路径中间的一条边
   - 验证重规划后的路径是否避开了被阻塞的边

3. 边惩罚 (penalized edge) 重规划:
   - 将路径中间边的延迟乘以 5 倍
   - 验证重规划是否找到了替代路径（或仍然使用但代价更高）

CLI:
    --graph, --config, --output: 同上
    --seed: 随机种子 (默认 0)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import dijkstra_delay_path, sample_start_target_pairs
from graph.graph_io import load_graph_json, save_results_json
from graph.visualization import plot_graph_with_path
from loihi_planner.dynamic_replanning import replan_from_position
from loihi_planner.loihi_config import load_brian2loihi_config
from loihi_planner.relay_controller import RelayController


def _load_graph(path: Path, seed: int):
    if path.exists():
        return load_graph_json(str(path)), "loaded"
    return generate_complex_graph("community", 100, seed=seed), "generated_default"


def _path_middle_edge(path: list[int]) -> tuple[int, int]:
    """返回路径中间的那条边 (用于阻塞/惩罚测试)。"""
    if len(path) < 2:
        raise ValueError("path must contain at least one edge")
    edge_index = max(0, (len(path) - 1) // 2)
    return path[edge_index], path[edge_index + 1]


def _find_baseline_case(G, seed: int) -> tuple[int, int, list[int], float]:
    """找一个至少有 3 个节点的基线路径用于阻塞/惩罚测试。"""
    for start, target in sample_start_target_pairs(G, 50, seed=seed):
        path, cost = dijkstra_delay_path(G, start, target)
        if len(path) >= 3:
            return start, target, path, cost
    start, target = next(iter(sample_start_target_pairs(G, 1, seed=seed)))
    path, cost = dijkstra_delay_path(G, start, target)
    return start, target, path, cost


def main() -> int:
    parser = argparse.ArgumentParser(description="Run dynamic start and relay gate experiments.")
    parser.add_argument("--graph", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    G, graph_source = _load_graph(Path(args.graph), seed=args.seed)
    config = load_brian2loihi_config(args.config)
    rng = random.Random(args.seed)

    # ========== 实验 1: 动态起点 ==========
    nodes = list(G.nodes())
    target = rng.choice(nodes)
    selected_nodes = rng.sample(nodes, min(5, len(nodes)))
    dynamic_rows: list[dict[str, object]] = []
    for idx, node in enumerate(selected_nodes):
        # 使用节点的精确坐标作为 Agent 位置
        x = float(G.nodes[node]["x"])
        y = float(G.nodes[node]["y"])
        result = replan_from_position(G, x, y, target, sigma=0.1, loihi_config=config)
        dynamic_rows.append({
            "position_id": idx, "x": x, "y": y, "target": target,
            "estimated_start": result["estimated_start"],
            "path": json.dumps(result["path"]) if result["path"] is not None else None,
            "path_cost": result["path_cost"],
            "target_arrival_time_ms": result["target_arrival_time_ms"],
            "num_spikes": result["num_spikes"],
            "success": result["success"], "error": result["error"],
        })
    pd.DataFrame(dynamic_rows).to_csv(output_dir / "dynamic_start_results.csv", index=False)

    # ========== 实验 2-3: 边阻塞 + 惩罚 ==========
    baseline_start, baseline_target, baseline_path, baseline_cost = _find_baseline_case(G, args.seed)
    # 取路径中间的边做实验
    edge_u, edge_v = _path_middle_edge(baseline_path)
    start_x = float(G.nodes[baseline_start]["x"])
    start_y = float(G.nodes[baseline_start]["y"])

    # 实验 2: 阻塞边
    blocked_controller = RelayController(G)
    blocked_controller.block_edge(edge_u, edge_v)
    blocked_graph = blocked_controller.get_graph()
    blocked_result = replan_from_position(
        blocked_graph, start_x, start_y, baseline_target, sigma=0.1, loihi_config=config
    )
    blocked_path = blocked_result.get("path") or []
    blocked_payload = {
        "baseline_start": baseline_start, "baseline_target": baseline_target,
        "baseline_path": baseline_path, "baseline_cost": baseline_cost,
        "blocked_edge": [edge_u, edge_v],
        "new_path": blocked_result.get("path"),
        "new_cost": blocked_result.get("path_cost"),
        # 检查新路径是否仍然包含被阻塞的边
        "blocked_edge_in_new_path": any(
            (a, b) == (edge_u, edge_v) for a, b in zip(blocked_path, blocked_path[1:])
        ),
        "success": bool(blocked_result.get("success")),
        "error": blocked_result.get("error"),
    }
    save_results_json(blocked_payload, str(output_dir / "blocked_edge_results.json"))

    # 实验 3: 惩罚边 (延迟 ×5)
    penalized_controller = RelayController(G)
    penalized_controller.penalize_edge(edge_u, edge_v, factor=5.0)
    penalized_graph = penalized_controller.get_graph()
    penalized_result = replan_from_position(
        penalized_graph, start_x, start_y, baseline_target, sigma=0.1, loihi_config=config
    )
    penalized_payload = {
        "baseline_start": baseline_start, "baseline_target": baseline_target,
        "baseline_path": baseline_path, "baseline_cost": baseline_cost,
        "penalized_edge": [edge_u, edge_v],
        "penalized_delay_ms": int(penalized_graph[edge_u][edge_v]["delay_ms"]),
        "new_path": penalized_result.get("path"),
        "new_cost": penalized_result.get("path_cost"),
        "success": bool(penalized_result.get("success")),
        "error": penalized_result.get("error"),
    }
    save_results_json(penalized_payload, str(output_dir / "penalized_edge_results.json"))

    # 可视化
    example_path = penalized_result.get("path") or blocked_result.get("path") or baseline_path
    try:
        plot_graph_with_path(G, example_path, str(output_dir / "dynamic_replanning_example.png"),
                             title="dynamic replanning")
        visualization_warning = None
    except Exception as exc:  # pragma: no cover - plotting backend dependent
        visualization_warning = str(exc)

    summary = {
        "graph_source": graph_source,
        "num_dynamic_positions": len(dynamic_rows),
        "dynamic_success_rate": (
            sum(1 for row in dynamic_rows if row["success"]) / len(dynamic_rows) if dynamic_rows else 0.0
        ),
        "blocked_edge_avoided": (
            not blocked_payload["blocked_edge_in_new_path"] if blocked_payload["success"] else None
        ),
        "blocked_success": blocked_payload["success"],
        "penalized_success": penalized_payload["success"],
        "visualization_warning": visualization_warning,
    }
    save_results_json(summary, str(output_dir / "summary.json"))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
