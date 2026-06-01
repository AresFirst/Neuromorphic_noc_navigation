"""Week3 实验: Loihi SNN 波前传播验证。

对比 SNN 波前路由与 CPU 参考算法 (event_driven_wavefront) 的到达时间精度。
验证 SNN 是否正确地找到了最短延迟路径。

流程:
    对每个 (start, target) 对:
    1. 运行 CPU 参考波前 → reference_arrival_time (真值)
    2. 运行 Loihi SNN 波前 → loihi_arrival_time
    3. 计算到达时间误差 = |loihi - reference|
    4. 成功条件: 误差 ≤ 1.0 ms

CLI:
    --graph: 图 JSON 路径
    --config: Brian2Loihi YAML 配置
    --output: 输出目录
    --num-pairs: 测试对数 (默认 10)
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
from graph.graph_baseline import sample_start_target_pairs
from graph.graph_io import load_graph_json, save_results_json
from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_config import load_brian2loihi_config
from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.spike_trace import save_spike_trace
from loihi_planner.wavefront_reference import event_driven_wavefront


def _load_graph(graph_path: Path, seed: int) -> tuple[object, str]:
    """加载图或生成默认图 (100 节点 community)。"""
    if graph_path.exists():
        return load_graph_json(str(graph_path)), "loaded"
    return generate_complex_graph("community", 100, seed=seed), "generated_default"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Brian2Loihi wavefront experiments.")
    parser.add_argument("--graph", required=True, help="Path to a graph JSON file.")
    parser.add_argument("--config", required=True, help="Path to Brian2Loihi YAML config.")
    parser.add_argument("--output", required=True, help="Output directory.")
    parser.add_argument("--num-pairs", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_brian2loihi_config(args.config)
    graph, graph_source = _load_graph(Path(args.graph), seed=args.seed)

    # 采样测试对
    pairs = sample_start_target_pairs(graph, num_pairs=int(args.num_pairs), seed=int(args.seed))
    backend_check = check_brian2loihi_available()

    rows: list[dict[str, object]] = []
    first_pair_trace_written = False

    for pair_id, (start, target) in enumerate(pairs):
        # 1. CPU 参考波前 (真值)
        reference = event_driven_wavefront(graph, start, target, delay_attr="delay_ms")
        # 2. Loihi SNN 波前
        loihi = run_loihi_wavefront(
            graph, start, target, delay_attr="delay_ms", sim_time_ms=None,
            threshold=float(config["threshold"]), weight=float(config["weight"]),
            refractory_ms=int(config["refractory_ms"]), seed=int(args.seed),
        )

        # 3. 计算到达时间误差
        loihi_arrival = loihi.get("target_arrival_time_ms")
        reference_arrival = reference.get("target_arrival_time")
        arrival_error = None
        if loihi_arrival is not None and reference_arrival is not None:
            arrival_error = abs(float(loihi_arrival) - float(reference_arrival))

        # 4. 成功条件: 误差 ≤ 1.0 ms
        success = bool(loihi.get("success")) and arrival_error is not None and arrival_error <= 1.0
        row = {
            "pair_id": pair_id, "start": start, "target": target,
            "reference_arrival_ms": reference_arrival,
            "loihi_arrival_ms": loihi_arrival,
            "arrival_error_ms": arrival_error, "success": success,
            "num_spikes": int(loihi.get("num_spikes", 0)),
            "active_neurons": int(loihi.get("active_neurons", 0)),
            "error": loihi.get("error"),
        }
        rows.append(row)

        # 保存第一对的数据供详细检查
        if not first_pair_trace_written:
            spike_trace_path = output_dir / "spike_trace_pair_0.csv"
            save_spike_trace(
                loihi.get("spike_times_by_neuron", {}) if loihi.get("success") else {},
                str(spike_trace_path)
            )
            reference_trace_path = output_dir / "pair_0_reference_spike_trace.csv"
            save_spike_trace(reference.get("arrival_times", {}), str(reference_trace_path))
            first_pair_trace_written = True

    # 写出结果
    results_df = pd.DataFrame.from_records(
        rows,
        columns=["pair_id", "start", "target", "reference_arrival_ms",
                 "loihi_arrival_ms", "arrival_error_ms", "success",
                 "num_spikes", "active_neurons", "error"],
    )
    results_df.to_csv(output_dir / "wavefront_results.csv", index=False)

    # 汇总统计
    successes = [row for row in rows if row["success"]]
    arrival_errors = [row["arrival_error_ms"] for row in successes if row["arrival_error_ms"] is not None]
    summary = {
        "backend_check": backend_check,
        "graph_source": graph_source,
        "num_pairs": len(rows),
        "num_success": len(successes),
        "success_rate": (len(successes) / len(rows)) if rows else 0.0,
        "mean_arrival_error_ms": float(sum(arrival_errors) / len(arrival_errors)) if arrival_errors else None,
        "max_arrival_error_ms": float(max(arrival_errors)) if arrival_errors else None,
        "backend_error": backend_check.get("error"),
    }
    save_results_json(summary, str(output_dir / "summary.json"))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
