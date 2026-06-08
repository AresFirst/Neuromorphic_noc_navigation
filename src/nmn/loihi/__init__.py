"""Minimal Brian2Loihi wavefront API used by OSM navigation."""

from __future__ import annotations

# 这个包是兼容层：保留 nmn.loihi.* 导入路径，同时复用 loihi_planner 的实现。
from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_config import load_brian2loihi_config, normalize_wavefront_config
from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compute_path_cost
from loihi_planner.path_reconstruction import reconstruct_path_from_parent

# 对外导出的都是 Brian2Loihi wavefront 闭环所需的最小 API。
__all__ = [
    "check_brian2loihi_available",
    "compute_path_cost",
    "infer_parent_trace_from_spikes",
    "load_brian2loihi_config",
    "normalize_wavefront_config",
    "reconstruct_path_from_parent",
    "run_loihi_wavefront",
]
