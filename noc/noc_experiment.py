"""完整 NoC 验证流水线编排。

run_single_noc_validation() 是 NoC 模块的最高级编排函数。
它将 mapper → SNN → 路径重建 → 包跟踪 → 代理指标 → Noxim 仿真的所有步骤
串联为一次完整的 NoC 验证流程。

流程 (成功路径):
    1. create_core_mapping()               # 神经元→Core 映射
    2. run_loihi_wavefront()               # SNN 波前路由
    3. infer_parent_trace_from_spikes()    # 父节点追踪
    4. reconstruct_path_from_parent()      # 路径重建
    5. compute_path_cost()                 # 路径代价
    6. build_stdp_trace_table()            # STDP 分析
    7. spike_trace_to_packet_trace()       # 脉冲→包跟踪
    8. compute_noc_proxy_metrics()         # 代理指标
    9. packet_trace_to_traffic_table()     # 流量表
    10. save_noxim_hardcoded_traffic()     # 写入流量文件
    11. run_noxim_with_hardcoded_traffic()  # 运行 Noxim
    12. 汇总所有结果 → JSON

错误路径: 波前失败时仍写入空包跟踪和流量文件，保持输出完整性。
"""

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
    """运行单次完整的 NoC 验证实验。

    从图 G 上的 (start→target) 路径开始，依次完成:
    SNN 波前路由 → 路径重建 → 包跟踪转换 → 代理指标 → Noxim 仿真。

    Args:
        G: 有向图。
        start: 起点节点 ID。
        target: 目标节点 ID。
        mesh_rows, mesh_cols: NoC Mesh 尺寸。
        mapping_strategy: Core 映射策略 ("random"/"topology"/"community")。
        output_dir: 输出目录。
        loihi_config: SNN 和 Noxim 参数字典。
        seed: 随机种子。

    Returns:
        大型结果字典，包含:
        - success, start, target, path, path_cost
        - mapping_strategy, mapping
        - packet_trace_path, traffic_table_path, hardcoded_traffic_path, stdp_trace_path
        - metrics (代理指标), noxim_result (Noxim 仿真结果)
        - wavefront (SNN 波前结果), error
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    config = loihi_config or {}

    # 读取 Noxim 相关配置
    noxim_config_path = config.get("noxim_config_path")
    noxim_power_path = config.get("noxim_power_path")
    noxim_packet_size = int(config.get("noxim_packet_size", 2))
    noxim_warmup_cycles = int(config.get("noxim_warmup_cycles", 0))
    noxim_simulation_margin_cycles = int(config.get("noxim_simulation_margin_cycles", 200))

    # 步骤 1: 创建 core 映射
    mapping = create_core_mapping(G, mesh_rows, mesh_cols, mapping_strategy, seed=seed)

    # 步骤 2: SNN 波前路由
    wavefront = run_loihi_wavefront(
        G, start, target, delay_attr="delay_ms",
        threshold=float(config.get("threshold", 1.0)),
        weight=float(config.get("weight", 1.1)),
        refractory_ms=int(config.get("refractory_ms", 1000)),
        seed=int(config.get("seed", seed)),
    )

    # ---- 失败路径: 波前路由失败 ----
    if not wavefront.get("success"):
        # 构造空包跟踪（保持输出格式一致）
        empty_trace = pd.DataFrame(
            columns=["cycle", "src_neuron", "dst_neuron", "src_core", "dst_core", "packet_type", "packet_size"]
        )
        metrics = compute_noc_proxy_metrics(empty_trace, mesh_rows, mesh_cols)
        traffic_table = packet_trace_to_traffic_table(empty_trace, mesh_rows * mesh_cols)
        packet_path = output_path / f"packet_trace_{mapping_strategy}.csv"
        traffic_path = output_path / f"traffic_table_{mapping_strategy}.txt"
        hardcoded_path = output_path / f"hardcoded_traffic_{mapping_strategy}.txt"

        # 写空文件
        empty_trace.to_csv(packet_path, index=False)
        save_noxim_traffic_table(traffic_table, str(traffic_path))
        save_noxim_hardcoded_traffic(empty_trace, str(hardcoded_path))

        # 仍然运行 Noxim (带空流量，做完整性检查)
        noxim_result = run_noxim_with_hardcoded_traffic(
            config.get("noxim_bin"), noxim_config_path, str(hardcoded_path), str(output_path),
            power_path=noxim_power_path, mesh_rows=mesh_rows, mesh_cols=mesh_cols,
            simulation_time=noxim_simulation_margin_cycles, warmup_time=noxim_warmup_cycles,
            seed=int(config.get("seed", seed)), packet_size=noxim_packet_size,
        )
        return {
            "success": False, "start": start, "target": target,
            "path": None, "path_cost": None,
            "mapping_strategy": mapping_strategy, "mapping": mapping,
            "packet_trace_path": str(packet_path), "traffic_table_path": str(traffic_path),
            "hardcoded_traffic_path": str(hardcoded_path),
            "metrics": metrics, "noxim_result": noxim_result,
            "wavefront": wavefront, "error": wavefront.get("error"),
        }

    # ---- 成功路径 ----
    try:
        # 步骤 3-5: 路径重建与分析
        parent_trace = infer_parent_trace_from_spikes(
            G, wavefront["spike_times_by_neuron"], start, delay_attr="delay_ms"
        )
        path = reconstruct_path_from_parent(parent_trace, start, target)
        path_cost = compute_path_cost(G, path, weight="delay_ms")

        # 步骤 6: STDP 分析
        stdp_trace = build_stdp_trace_table(
            G, parent_trace, wavefront["spike_times_by_neuron"], delay_attr="delay_ms"
        )

        # 步骤 7: 脉冲→包跟踪
        packet_trace = spike_trace_to_packet_trace(
            G, wavefront["spike_times_by_neuron"], mapping, delay_attr="delay_ms"
        )

        # 步骤 8: 代理指标
        metrics = compute_noc_proxy_metrics(packet_trace, mesh_rows, mesh_cols)

        # 步骤 9: 流量表
        traffic_table = packet_trace_to_traffic_table(packet_trace, mesh_rows * mesh_cols)

        # 计算仿真时长: 最后一个包注入时间 + max(余量, 最远跳数×包大小+20)
        traffic_end_cycle = int(packet_trace["cycle"].max()) if not packet_trace.empty else 0
        simulation_time = traffic_end_cycle + max(
            noxim_simulation_margin_cycles,
            int(metrics.get("max_hop", 0)) * max(1, noxim_packet_size) + 20,
        )

        # 步骤 10: 写文件
        packet_path = output_path / f"packet_trace_{mapping_strategy}.csv"
        traffic_path = output_path / f"traffic_table_{mapping_strategy}.txt"
        hardcoded_path = output_path / f"hardcoded_traffic_{mapping_strategy}.txt"
        stdp_path = output_path / f"stdp_trace_{mapping_strategy}.csv"
        packet_trace.to_csv(packet_path, index=False)
        stdp_trace.to_csv(stdp_path, index=False)
        save_noxim_traffic_table(traffic_table, str(traffic_path))
        save_noxim_hardcoded_traffic(packet_trace, str(hardcoded_path))

        # 步骤 11: 运行 Noxim
        noxim_result = run_noxim_with_hardcoded_traffic(
            config.get("noxim_bin"), noxim_config_path, str(hardcoded_path), str(output_path),
            power_path=noxim_power_path, mesh_rows=mesh_rows, mesh_cols=mesh_cols,
            simulation_time=simulation_time, warmup_time=noxim_warmup_cycles,
            seed=int(config.get("seed", seed)), packet_size=noxim_packet_size,
        )

        # 步骤 12: 汇总结果
        payload = {
            "success": True, "start": start, "target": target,
            "path": path, "path_cost": path_cost,
            "mapping_strategy": mapping_strategy, "mapping": mapping,
            "packet_trace_path": str(packet_path), "traffic_table_path": str(traffic_path),
            "hardcoded_traffic_path": str(hardcoded_path), "stdp_trace_path": str(stdp_path),
            "metrics": metrics, "noxim_result": noxim_result,
            "wavefront": wavefront, "error": None,
        }
        (output_path / f"single_noc_{mapping_strategy}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
        )
        return payload
    except Exception as exc:
        # 任何步骤失败: 返回部分结果
        return {
            "success": False, "start": start, "target": target,
            "path": None, "path_cost": None,
            "mapping_strategy": mapping_strategy, "mapping": mapping,
            "metrics": compute_noc_proxy_metrics(pd.DataFrame(), mesh_rows, mesh_cols),
            "noxim_result": {"status": "skipped", "reason": "not run after path reconstruction failure"},
            "wavefront": wavefront, "error": str(exc),
        }
