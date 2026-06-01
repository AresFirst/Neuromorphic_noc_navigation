"""NoC (Network-on-Chip) 接口模块。

本包提供 SNN 仿真结果到 NoC 周期精确模拟器的完整桥接:

1. mapping.py: 神经元 → 物理 NoC core 的映射策略
2. packet_trace.py: SNN 脉冲时间 → NoC 数据包跟踪的转换
3. traffic_table.py: 数据包跟踪 → Noxim 可读的流量文件格式
4. noc_proxy_metrics.py: 无需 Noxim 的快速 NoC 代理指标估算
5. noc_experiment.py: 完整 NoC 验证流水线的编排器
6. noxim_wrapper.py: Noxim 模拟器的子进程调用封装
7. parse_noxim_output.py: Noxim 输出文本的解析（stdout 和 JSON stats）
"""

from .mapping import create_core_mapping
from .noc_experiment import run_single_noc_validation
from .noc_proxy_metrics import compute_noc_proxy_metrics, core_id_to_xy, manhattan_hop
from .noxim_wrapper import run_noxim, run_noxim_with_hardcoded_traffic, run_noxim_with_traffic_table
from .packet_trace import relay_events_to_packet_trace, spike_trace_to_packet_trace
from .parse_noxim_output import parse_noxim_output, parse_noxim_stats_file, parse_noxim_stats_payload
from .traffic_table import (
    packet_trace_to_hardcoded_traffic_lines,
    packet_trace_to_traffic_table,
    save_noxim_hardcoded_traffic,
    save_noxim_traffic_table,
    save_sample_noxim_traffic_table,
)

__all__ = [
    "create_core_mapping",
    "run_single_noc_validation",
    "compute_noc_proxy_metrics",
    "core_id_to_xy",
    "manhattan_hop",
    "run_noxim",
    "run_noxim_with_hardcoded_traffic",
    "run_noxim_with_traffic_table",
    "relay_events_to_packet_trace",
    "spike_trace_to_packet_trace",
    "parse_noxim_output",
    "parse_noxim_stats_file",
    "parse_noxim_stats_payload",
    "packet_trace_to_hardcoded_traffic_lines",
    "packet_trace_to_traffic_table",
    "save_noxim_hardcoded_traffic",
    "save_noxim_traffic_table",
    "save_sample_noxim_traffic_table",
]
