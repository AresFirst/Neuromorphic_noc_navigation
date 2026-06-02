"""NoC 映射与 Noxim 验证入口。"""

from __future__ import annotations

import sys
from importlib import import_module

from noc.mapping import create_core_mapping
from noc.noc_experiment import run_single_noc_validation
from noc.noc_proxy_metrics import compute_noc_proxy_metrics, core_id_to_xy, manhattan_hop
from noc.noxim_wrapper import run_noxim, run_noxim_with_hardcoded_traffic, run_noxim_with_traffic_table
from noc.packet_trace import relay_events_to_packet_trace, spike_trace_to_packet_trace
from noc.parse_noxim_output import parse_noxim_output, parse_noxim_stats_file, parse_noxim_stats_payload
from noc.traffic_table import (
    packet_trace_to_hardcoded_traffic_lines,
    packet_trace_to_traffic_table,
    save_noxim_hardcoded_traffic,
    save_noxim_traffic_table,
    save_sample_noxim_traffic_table,
)

_ALIASES = {
    "experiment": "noc.noc_experiment",
    "mapping": "noc.mapping",
    "packet_trace": "noc.packet_trace",
    "proxy_metrics": "noc.noc_proxy_metrics",
    "traffic_table": "noc.traffic_table",
    "noxim": "noc.noxim_wrapper",
    "parse_noxim": "noc.parse_noxim_output",
}

for name, module_name in _ALIASES.items():
    sys.modules[f"{__name__}.{name}"] = import_module(module_name)

__all__ = [
    "compute_noc_proxy_metrics",
    "core_id_to_xy",
    "create_core_mapping",
    "manhattan_hop",
    "packet_trace_to_hardcoded_traffic_lines",
    "packet_trace_to_traffic_table",
    "parse_noxim_output",
    "parse_noxim_stats_file",
    "parse_noxim_stats_payload",
    "relay_events_to_packet_trace",
    "run_noxim",
    "run_noxim_with_hardcoded_traffic",
    "run_noxim_with_traffic_table",
    "run_single_noc_validation",
    "save_noxim_hardcoded_traffic",
    "save_noxim_traffic_table",
    "save_sample_noxim_traffic_table",
    "spike_trace_to_packet_trace",
]
