from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compute_path_cost
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from loihi_planner.stdp_trace import build_stdp_trace_table

from .mapping import create_core_mapping
from .noc_proxy_metrics import compute_noc_proxy_metrics
from .noxim_wrapper import run_noxim_with_hardcoded_traffic
from .packet_trace import spike_trace_to_packet_trace
from .traffic_table import (
    packet_trace_to_traffic_table,
    save_noxim_hardcoded_traffic,
    save_noxim_traffic_table,
)


def run_single_noc_validation(
    G,
    start: int,
    target: int,
    mesh_rows: int,
    mesh_cols: int,
    mapping_strategy: str,
    output_dir: str,
    loihi_config: dict | None = None,
    seed: int = 0,
) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    config = loihi_config or {}
    noxim_config_path = config.get("noxim_config_path")
    noxim_power_path = config.get("noxim_power_path")
    noxim_packet_size = int(config.get("noxim_packet_size", 2))
    noxim_warmup_cycles = int(config.get("noxim_warmup_cycles", 0))
    noxim_simulation_margin_cycles = int(config.get("noxim_simulation_margin_cycles", 200))

    mapping = create_core_mapping(G, mesh_rows, mesh_cols, mapping_strategy, seed=seed)
    wavefront = run_loihi_wavefront(
        G,
        start,
        target,
        delay_attr="delay_ms",
        threshold=float(config.get("threshold", 1.0)),
        weight=float(config.get("weight", 1.1)),
        refractory_ms=int(config.get("refractory_ms", 1000)),
        seed=int(config.get("seed", seed)),
    )
    if not wavefront.get("success"):
        empty_trace = pd.DataFrame(
            columns=["cycle", "src_neuron", "dst_neuron", "src_core", "dst_core", "packet_type", "packet_size"]
        )
        metrics = compute_noc_proxy_metrics(empty_trace, mesh_rows, mesh_cols)
        traffic_table = packet_trace_to_traffic_table(empty_trace, mesh_rows * mesh_cols)
        packet_path = output_path / f"packet_trace_{mapping_strategy}.csv"
        traffic_path = output_path / f"traffic_table_{mapping_strategy}.txt"
        hardcoded_path = output_path / f"hardcoded_traffic_{mapping_strategy}.txt"
        empty_trace.to_csv(packet_path, index=False)
        save_noxim_traffic_table(traffic_table, str(traffic_path))
        save_noxim_hardcoded_traffic(empty_trace, str(hardcoded_path))
        noxim_result = run_noxim_with_hardcoded_traffic(
            config.get("noxim_bin"),
            noxim_config_path,
            str(hardcoded_path),
            str(output_path),
            power_path=noxim_power_path,
            mesh_rows=mesh_rows,
            mesh_cols=mesh_cols,
            simulation_time=noxim_simulation_margin_cycles,
            warmup_time=noxim_warmup_cycles,
            seed=int(config.get("seed", seed)),
            packet_size=noxim_packet_size,
        )
        return {
            "success": False,
            "start": start,
            "target": target,
            "path": None,
            "path_cost": None,
            "mapping_strategy": mapping_strategy,
            "mapping": mapping,
            "packet_trace_path": str(packet_path),
            "traffic_table_path": str(traffic_path),
            "hardcoded_traffic_path": str(hardcoded_path),
            "metrics": metrics,
            "noxim_result": noxim_result,
            "wavefront": wavefront,
            "error": wavefront.get("error"),
        }

    try:
        parent_trace = infer_parent_trace_from_spikes(G, wavefront["spike_times_by_neuron"], start, delay_attr="delay_ms")
        path = reconstruct_path_from_parent(parent_trace, start, target)
        path_cost = compute_path_cost(G, path, weight="delay_ms")
        stdp_trace = build_stdp_trace_table(G, parent_trace, wavefront["spike_times_by_neuron"], delay_attr="delay_ms")
        packet_trace = spike_trace_to_packet_trace(G, wavefront["spike_times_by_neuron"], mapping, delay_attr="delay_ms")
        metrics = compute_noc_proxy_metrics(packet_trace, mesh_rows, mesh_cols)
        traffic_table = packet_trace_to_traffic_table(packet_trace, mesh_rows * mesh_cols)
        traffic_end_cycle = int(packet_trace["cycle"].max()) if not packet_trace.empty else 0
        simulation_time = traffic_end_cycle + max(
            noxim_simulation_margin_cycles,
            int(metrics.get("max_hop", 0)) * max(1, noxim_packet_size) + 20,
        )

        packet_path = output_path / f"packet_trace_{mapping_strategy}.csv"
        traffic_path = output_path / f"traffic_table_{mapping_strategy}.txt"
        hardcoded_path = output_path / f"hardcoded_traffic_{mapping_strategy}.txt"
        stdp_path = output_path / f"stdp_trace_{mapping_strategy}.csv"
        packet_trace.to_csv(packet_path, index=False)
        stdp_trace.to_csv(stdp_path, index=False)
        save_noxim_traffic_table(traffic_table, str(traffic_path))
        save_noxim_hardcoded_traffic(packet_trace, str(hardcoded_path))

        noxim_result = run_noxim_with_hardcoded_traffic(
            config.get("noxim_bin"),
            noxim_config_path,
            str(hardcoded_path),
            str(output_path),
            power_path=noxim_power_path,
            mesh_rows=mesh_rows,
            mesh_cols=mesh_cols,
            simulation_time=simulation_time,
            warmup_time=noxim_warmup_cycles,
            seed=int(config.get("seed", seed)),
            packet_size=noxim_packet_size,
        )
        payload = {
            "success": True,
            "start": start,
            "target": target,
            "path": path,
            "path_cost": path_cost,
            "mapping_strategy": mapping_strategy,
            "mapping": mapping,
            "packet_trace_path": str(packet_path),
            "traffic_table_path": str(traffic_path),
            "hardcoded_traffic_path": str(hardcoded_path),
            "stdp_trace_path": str(stdp_path),
            "metrics": metrics,
            "noxim_result": noxim_result,
            "wavefront": wavefront,
            "error": None,
        }
        (output_path / f"single_noc_{mapping_strategy}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return payload
    except Exception as exc:
        return {
            "success": False,
            "start": start,
            "target": target,
            "path": None,
            "path_cost": None,
            "mapping_strategy": mapping_strategy,
            "mapping": mapping,
            "metrics": compute_noc_proxy_metrics(pd.DataFrame(), mesh_rows, mesh_cols),
            "noxim_result": {"status": "skipped", "reason": "not run after path reconstruction failure"},
            "wavefront": wavefront,
            "error": str(exc),
        }
