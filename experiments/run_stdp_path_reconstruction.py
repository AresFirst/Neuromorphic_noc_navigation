"""Week4 实验: STDP 路径重建与最优性验证。

完整的端到端路径重建验证:
1. 运行 Loihi SNN 波前
2. 从脉冲时间推断父节点关系 (infer_parent_trace_from_spikes)
3. 构建 STDP 权重变化表 (build_stdp_trace_table)
4. 沿父链反向追踪重建路径 (reconstruct_path_from_parent)
5. 与 Dijkstra 最优路径对比 (compare_snn_path_with_dijkstra)

成功标准: SNN 重建路径与 Dijkstra 路径的代价相同 (same_cost=True)。

CLI:
    --graph, --config, --output: 同上
    --num-pairs: 测试对数 (默认 50，比 Week3 多，因为此处是最关键验证)
    --seed: 随机种子 (默认 0)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import dijkstra_delay_path, sample_start_target_pairs
from graph.graph_io import load_graph_json, save_results_json
from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_config import load_brian2loihi_config
from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compare_snn_path_with_dijkstra
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from loihi_planner.spike_trace import save_spike_trace
from loihi_planner.stdp_trace import build_stdp_trace_table
from loihi_planner.wavefront_reference import event_driven_wavefront


def _load_graph(graph_path: Path, seed: int):
    if graph_path.exists():
        return load_graph_json(str(graph_path)), "loaded"
    return generate_complex_graph("community", 100, seed=seed), "generated_default"


def _empty_stdp_dataframe() -> pd.DataFrame:
    """创建空的 STDP DataFrame（schema 不变）。"""
    return pd.DataFrame(
        columns=["pre", "post", "is_parent_edge", "pre_spike_time_ms",
                 "post_spike_time_ms", "delta_t_ms", "stdp_weight"]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run STDP path reconstruction experiments.")
    parser.add_argument("--graph", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--num-pairs", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = load_brian2loihi_config(args.config)
    graph, graph_source = _load_graph(Path(args.graph), seed=args.seed)
    pairs = sample_start_target_pairs(graph, num_pairs=int(args.num_pairs), seed=int(args.seed))
    backend_check = check_brian2loihi_available()

    rows: list[dict[str, object]] = []
    first_pair_trace_written = False
    first_pair_stdp_written = False

    for pair_id, (start, target) in enumerate(pairs):
        # 步骤 1+2: 参考波前 + Loihi SNN 波前
        reference = event_driven_wavefront(graph, start, target, delay_attr="delay_ms")
        loihi = run_loihi_wavefront(
            graph, start, target, delay_attr="delay_ms", sim_time_ms=None,
            threshold=float(config["threshold"]), weight=float(config["weight"]),
            refractory_ms=int(config["refractory_ms"]), seed=int(args.seed),
        )

        snn_path: list[int] | None = None
        dijkstra_path: list[int] | None = None
        dijkstra_cost_value: float | None = None
        compare: dict | None = None
        stdp_df = _empty_stdp_dataframe()
        error = loihi.get("error")
        success = False

        if loihi.get("success") and loihi.get("target_arrival_time_ms") is not None:
            try:
                # 步骤 3: 父节点追踪
                parent_trace = infer_parent_trace_from_spikes(
                    graph, loihi["spike_times_by_neuron"], start, delay_attr="delay_ms"
                )
                # 步骤 4: STDP 分析
                stdp_df = build_stdp_trace_table(
                    graph, parent_trace, loihi["spike_times_by_neuron"], delay_attr="delay_ms"
                )
                # 步骤 5: 路径重建
                snn_path = reconstruct_path_from_parent(parent_trace, start, target)
                # 步骤 6: Dijkstra 基线
                dijkstra_path, dijkstra_cost_value = dijkstra_delay_path(
                    graph, start, target, delay_attr="delay_ms"
                )
                # 步骤 7: 对比
                compare = compare_snn_path_with_dijkstra(graph, snn_path, dijkstra_path, weight="delay_ms")
                success = bool(compare["same_cost"]) and compare["optimality_ratio"] is not None
                error = None
            except Exception as exc:
                error = str(exc)
                success = False
        else:
            # 波前失败但仍尝试计算 Dijkstra 路径
            try:
                dijkstra_path, dijkstra_cost_value = dijkstra_delay_path(
                    graph, start, target, delay_attr="delay_ms"
                )
            except Exception as exc:
                error = f"{error}; {exc}" if error else str(exc)

        if compare is None:
            compare = {
                "snn_cost": None, "dijkstra_cost": dijkstra_cost_value,
                "optimality_ratio": None, "same_path": False, "same_cost": False,
                "snn_num_hops": None,
                "dijkstra_num_hops": max(0, len(dijkstra_path) - 1) if dijkstra_path is not None else None,
            }

        # 保存第一对的详细数据
        if not first_pair_trace_written:
            save_spike_trace(
                loihi.get("spike_times_by_neuron", {}) if loihi.get("success") else {},
                str(output_dir / "pair_0_spike_trace.csv")
            )
            first_pair_trace_written = True
        if not first_pair_stdp_written:
            stdp_df.to_csv(output_dir / "pair_0_stdp_trace.csv", index=False)
            first_pair_stdp_written = True

        path_compare_payload = {
            "pair_id": pair_id, "start": start, "target": target,
            "reference_arrival_ms": reference.get("target_arrival_time"),
            "loihi_arrival_ms": loihi.get("target_arrival_time_ms"),
            "snn_path": snn_path, "dijkstra_path": dijkstra_path,
            "compare": compare, "success": success, "error": error,
        }
        if pair_id == 0:
            save_results_json(path_compare_payload, str(output_dir / "pair_0_path_compare.json"))

        rows.append({
            "pair_id": pair_id, "start": start, "target": target,
            "success": success,
            "snn_path": json.dumps(snn_path) if snn_path is not None else None,
            "dijkstra_path": json.dumps(dijkstra_path) if dijkstra_path is not None else None,
            "snn_cost": compare["snn_cost"], "dijkstra_cost": compare["dijkstra_cost"],
            "optimality_ratio": compare["optimality_ratio"],
            "same_cost": compare["same_cost"],
            "num_spikes": int(loihi.get("num_spikes", 0)),
            "target_arrival_time_ms": loihi.get("target_arrival_time_ms"),
            "error": error,
        })

    results_df = pd.DataFrame.from_records(rows)
    results_df.to_csv(output_dir / "stdp_path_results.csv", index=False)

    success_rows = [row for row in rows if row["success"]]
    optimality_values = [row["optimality_ratio"] for row in success_rows if row["optimality_ratio"] is not None]
    same_cost_values = [row["same_cost"] for row in success_rows]
    summary = {
        "backend_check": backend_check, "graph_source": graph_source,
        "num_pairs": len(rows), "num_success": len(success_rows),
        "success_rate": (len(success_rows) / len(rows)) if rows else 0.0,
        "mean_optimality_ratio": float(sum(optimality_values) / len(optimality_values)) if optimality_values else None,
        "max_optimality_ratio": float(max(optimality_values)) if optimality_values else None,
        "same_cost_rate": (sum(1 for v in same_cost_values if v) / len(same_cost_values)) if same_cost_values else 0.0,
    }
    save_results_json(summary, str(output_dir / "summary.json"))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
