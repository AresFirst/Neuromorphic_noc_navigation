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
    G, graph_source = _load_graph(Path(args.graph), seed=args.seed)
    loihi_config = load_brian2loihi_config(args.loihi_config)
    noc_config = yaml.safe_load(Path(args.noc_config).read_text(encoding="utf-8")) or {}
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

    for strategy in strategies:
        mapping = create_core_mapping(G, mesh_rows, mesh_cols, strategy, seed=args.seed)
        save_results_json(mapping, str(output_dir / f"mapping_{strategy}.json"))

    rows: list[dict[str, object]] = []
    for strategy in strategies:
        for pair_id, (start, target) in enumerate(pairs):
            pair_output = output_dir / f"pair_{pair_id}_{strategy}"
            result = run_single_noc_validation(
                G,
                start,
                target,
                mesh_rows,
                mesh_cols,
                strategy,
                str(pair_output),
                loihi_config=loihi_config,
                seed=args.seed,
            )
            metrics = result["metrics"]
            noxim_result = result["noxim_result"]
            rows.append(
                {
                    "pair_id": pair_id,
                    "start": start,
                    "target": target,
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
                }
            )
            if pair_id == 0 and strategy == "topology":
                packet_src = Path(result.get("packet_trace_path", pair_output / "packet_trace_topology.csv"))
                traffic_src = Path(result.get("traffic_table_path", pair_output / "traffic_table_topology.txt"))
                if packet_src.exists():
                    (output_dir / "packet_trace_pair0_topology.csv").write_text(packet_src.read_text(encoding="utf-8"), encoding="utf-8")
                if traffic_src.exists():
                    (output_dir / "traffic_table_pair0_topology.txt").write_text(traffic_src.read_text(encoding="utf-8"), encoding="utf-8")

    df = pd.DataFrame.from_records(rows)
    df.to_csv(output_dir / "noc_results.csv", index=False)

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

    warnings = {
        "fig_average_hop_by_mapping": _plot_bar(
            df,
            "average_hop",
            output_dir / "fig_average_hop_by_mapping.png",
            "Average Hop by Mapping",
        ),
        "fig_energy_proxy_by_mapping": _plot_bar(
            df,
            "energy_proxy",
            output_dir / "fig_energy_proxy_by_mapping.png",
            "Energy Proxy by Mapping",
        ),
    }
    summary = {
        "graph_source": graph_source,
        "mesh_rows": mesh_rows,
        "mesh_cols": mesh_cols,
        "num_pairs": len(pairs),
        "strategies": strategies,
        "by_mapping_strategy": summary_by_strategy,
        "warnings": {key: value for key, value in warnings.items() if value},
    }
    save_results_json(summary, str(output_dir / "summary.json"))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
