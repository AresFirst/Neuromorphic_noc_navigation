"""Minimal Brian2Loihi wavefront API used by OSM navigation."""

from __future__ import annotations

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.loihi_config import load_brian2loihi_config, normalize_wavefront_config
from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compute_path_cost
from loihi_planner.path_reconstruction import reconstruct_path_from_parent

__all__ = [
    "check_brian2loihi_available",
    "compute_path_cost",
    "infer_parent_trace_from_spikes",
    "load_brian2loihi_config",
    "normalize_wavefront_config",
    "reconstruct_path_from_parent",
    "run_loihi_wavefront",
]
