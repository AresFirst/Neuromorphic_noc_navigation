"""Week6 实验: NoC 验证 —— 多映射策略性能对比。

对每种 core 映射策略 (random / community / topology)，
运行完整的 NoC 验证流水线并对比性能指标。

实验矩阵:
    mapping_strategies × (start, target) pairs

每个 cell 运行:
    1. run_single_noc_validation()
       → SNN 波前 → 路径重建 → 包跟踪 → Noxim 仿真
    2. 收集: average_hop, total_hop, energy_proxy, hotspot_core, Noxim 延迟/吞吐

输出:
    - noc_results.csv: 所有组合的结果
    - mapping_{strategy}.json: 每种策略的 core 映射
    - packet_trace_pair0_topology.csv: 示例包跟踪
    - fig_average_hop_by_mapping.png / fig_energy_proxy_by_mapping.png: 柱状图对比
    - summary.json: 按策略汇总的均值/成功率

CLI:
    --graph, --loihi-config, --noc-config (YAML), --output
    --num-pairs (默认 20), --seed (默认 0)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from graph.complex_graph_generator import generate_complex_graph
from graph.graph_baseline import sample_start_target_pairs
from graph.graph_io import load_graph_json, save_results_json
from loihi_planner.loihi_config import load_brian2loihi_config
from noc.mapping import create_core_mapping
from noc.noc_experiment import run_single_noc_validation


def _load_graph(path: Path, seed: int):
    if path.exists():
        return load_graph_json(str(path)), "loaded"
    return generate_complex_graph("community", 100, seed=seed), "generated_default"


def _plot_bar(df: pd.DataFrame, value_col: str, save_path: Path, title: str) -> str | None:
    """绘制按 mapping_strategy 分组的柱状图。

    Args:
        df: 包含 mapping_strategy 和 value_col 的 DataFrame。
        value_col: 要绘制的列名。
        save_path: 输出 PNG 路径。
        title: 图表标题。

    Returns:
        错误消息或 None。
    """
    try:
        os.environ.setdefault("MPLCONFIGDIR", str(REPO_ROOT / ".matplotlib-cache"))
        import matplotlib
        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(6, 4), dpi=160)
        grouped = df.groupby("mapping_strategy")[value_col].mean()
        grouped.plot(kind="bar", ax=ax, color=["#4e79a7", "#59a14f", "#f28e2b"][: len(grouped)])
        ax.set_title(title)
        ax.set_xlabel("mapping strategy")
        ax.set_ylabel(value_col)
        fig.tight_layout()
        fig.savefig(save_path)
        plt.close(fig)
        return None
    except Exception as exc:  # pragma: no cover - plotting backend dependent
        return str(exc)


def _parsed_metric(noxim_result: dict, metric: str):
    """安全地从 Noxim 结果中提取指标。"""
    parsed = noxim_result.get("parsed") or {}
    return parsed.get(metric)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NoC validation experiments.")
    parser.add_argument("--graph", required=True)
    parser.add_argument("--loihi-config", required=True)
    parser.add_argument("--noc-config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--num-pairs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 加载配置
    G, graph_source = _load_graph(Path(args.graph), seed=args.seed)
    loihi_config = load_brian2loihi_config(args.loihi_config)
    noc_config = yaml.safe_load(Path(args.noc_config).read_text(encoding="utf-8")) or {}
    # 合并 Loihi 和 NoC 配置
    loihi_config = {
        **loihi_config,
        "noxim_bin": noc_config.get("noxim_bin"),
        "noxim_config_path": noc_config.get("noxim_config_path"),
        "noxim_power_path": noc_config.get("noxim_power_path"),
        "noxim_packet_size": noc_config.get("noxim_packet_size", 2),
        "noxim_warmup_cycles": noc_config.get("noxim_warmup_cycles", 0),
        "noxim_simulation_margin_cycles": noc_config.get("noxim_simulation_margin_cycles", 200),
    }

    mesh_rows = int(noc_config.get("mesh_rows", 8))
    mesh_cols = int(noc_config.get("mesh_cols", 8))
    strategies = list(noc_config.get("mapping_strategies", ["random", "community", "topology"]))
    pairs = sample_start_target_pairs(G, args.num_pairs, seed=args.seed)

    # 保存每种策略的 core 映射（保存结果，便于检查）
    for strategy in strategies:
        mapping = create_core_mapping(G, mesh_rows, mesh_cols, strategy, seed=args.seed)
        save_results_json(mapping, str(output_dir / f"mapping_{strategy}.json"))

    # 运行完整矩阵: strategies × pairs
    rows: list[dict[str, object]] = []
    for strategy in strategies:
        for pair_id, (start, target) in enumerate(pairs):
            pair_output = output_dir / f"pair_{pair_id}_{strategy}"
            result = run_single_noc_validation(
                G, start, target, mesh_rows, mesh_cols, strategy,
                str(pair_output), loihi_config=loihi_config, seed=args.seed,
            )
            metrics = result["metrics"]
            noxim_result = result["noxim_result"]
            rows.append({
                "pair_id": pair_id, "start": start, "target": target,
                "mapping_strategy": strategy,
                "success": result["success"],
                "path_cost": result.get("path_cost"),
                "num_packets": metrics["num_packets"],
                "average_hop": metrics["average_hop"],
                "max_hop": metrics["max_hop"],
                "total_hop": metrics["total_hop"],
                "energy_proxy": metrics["energy_proxy"],
                "hotspot_core": metrics["hotspot_core"],
                "hotspot_packet_count": metrics["hotspot_packet_count"],
                "noxim_status": noxim_result.get("status"),
                "noxim_average_latency": _parsed_metric(noxim_result, "average_latency"),
                "noxim_throughput": _parsed_metric(noxim_result, "throughput"),
                "error": result.get("error"),
            })

            # 复制第一对 topology 策略的示例数据
            if pair_id == 0 and strategy == "topology":
                packet_src = Path(result.get("packet_trace_path", pair_output / "packet_trace_topology.csv"))
                traffic_src = Path(result.get("traffic_table_path", pair_output / "traffic_table_topology.txt"))
                if packet_src.exists():
                    (output_dir / "packet_trace_pair0_topology.csv").write_text(
                        packet_src.read_text(encoding="utf-8"), encoding="utf-8")
                if traffic_src.exists():
                    (output_dir / "traffic_table_pair0_topology.txt").write_text(
                        traffic_src.read_text(encoding="utf-8"), encoding="utf-8")

    df = pd.DataFrame.from_records(rows)
    df.to_csv(output_dir / "noc_results.csv", index=False)

    # 按策略汇总
    summary_by_strategy: dict[str, dict[str, object]] = {}
    for strategy, group in df.groupby("mapping_strategy"):
        success_group = group[group["success"] == True]
        summary_by_strategy[str(strategy)] = {
            "mean_num_packets": float(group["num_packets"].mean()) if len(group) else 0.0,
            "mean_average_hop": float(group["average_hop"].mean()) if len(group) else 0.0,
            "mean_total_hop": float(group["total_hop"].mean()) if len(group) else 0.0,
            "mean_energy_proxy": float(group["energy_proxy"].mean()) if len(group) else 0.0,
            "mean_hotspot_packet_count": float(group["hotspot_packet_count"].mean()) if len(group) else 0.0,
            "num_success": int(len(success_group)),
            "success_rate": float(len(success_group) / len(group)) if len(group) else 0.0,
        }

    # 生成对比柱状图
    warnings = {
        "fig_average_hop_by_mapping": _plot_bar(
            df, "average_hop", output_dir / "fig_average_hop_by_mapping.png",
            "Average Hop by Mapping"),
        "fig_energy_proxy_by_mapping": _plot_bar(
            df, "energy_proxy", output_dir / "fig_energy_proxy_by_mapping.png",
            "Energy Proxy by Mapping"),
    }
    summary = {
        "graph_source": graph_source, "mesh_rows": mesh_rows, "mesh_cols": mesh_cols,
        "num_pairs": len(pairs), "strategies": strategies,
        "by_mapping_strategy": summary_by_strategy,
        "warnings": {key: value for key, value in warnings.items() if value},
    }
    save_results_json(summary, str(output_dir / "summary.json"))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
