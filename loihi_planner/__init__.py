"""Minimal Brian2Loihi wavefront planner."""

from __future__ import annotations

# loihi_planner 是 SNN wavefront 的低层实现包，GUI 不直接依赖内部文件。
from .backend_check import check_brian2loihi_available
from .loihi_config import load_brian2loihi_config, normalize_wavefront_config
from .loihi_wavefront import run_loihi_wavefront
from .parent_trace import infer_parent_trace_from_spikes
from .path_compare import compute_path_cost
from .path_reconstruction import reconstruct_path_from_parent

# 这里集中导出后端检测、wavefront、parent trace 和路径重建工具。
__all__ = [
    "check_brian2loihi_available",
    "compute_path_cost",
    "infer_parent_trace_from_spikes",
    "load_brian2loihi_config",
    "normalize_wavefront_config",
    "reconstruct_path_from_parent",
    "run_loihi_wavefront",
]
