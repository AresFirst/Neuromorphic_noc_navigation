"""Loihi 风格 SNN 波前与回溯功能的标准入口。"""

from __future__ import annotations

import sys
from importlib import import_module

from loihi_planner.backend_check import check_brian2loihi_available
from loihi_planner.dynamic_replanning import replan_from_position
from loihi_planner.loihi_config import load_brian2loihi_config, normalize_wavefront_config
from loihi_planner.loihi_delay_demo import run_loihi_delay_demo
from loihi_planner.loihi_lif_demo import run_loihi_lif_demo
from loihi_planner.loihi_small_wavefront_demo import run_loihi_small_wavefront_demo
from loihi_planner.loihi_wavefront import run_loihi_wavefront
from loihi_planner.parent_trace import infer_parent_trace_from_spikes
from loihi_planner.path_compare import compare_snn_path_with_dijkstra, compute_path_cost
from loihi_planner.path_reconstruction import reconstruct_path_from_parent
from loihi_planner.relay_controller import RelayController
from loihi_planner.spike_trace import load_spike_trace, save_spike_trace, spike_trace_to_dataframe
from loihi_planner.stdp_trace import build_stdp_trace_table
from loihi_planner.wavefront_reference import event_driven_wavefront

_ALIASES = {
    "backend": "loihi_planner.backend_check",
    "config": "loihi_planner.loihi_config",
    "dynamic_replanning": "loihi_planner.dynamic_replanning",
    "path_compare": "loihi_planner.path_compare",
    "path_reconstruction": "loihi_planner.path_reconstruction",
    "parent_trace": "loihi_planner.parent_trace",
    "relay": "loihi_planner.relay_controller",
    "reference": "loihi_planner.wavefront_reference",
    "spike_trace": "loihi_planner.spike_trace",
    "stdp_trace": "loihi_planner.stdp_trace",
    "wavefront": "loihi_planner.loihi_wavefront",
}

for name, module_name in _ALIASES.items():
    sys.modules[f"{__name__}.{name}"] = import_module(module_name)

__all__ = [
    "build_stdp_trace_table",
    "check_brian2loihi_available",
    "compare_snn_path_with_dijkstra",
    "compute_path_cost",
    "event_driven_wavefront",
    "infer_parent_trace_from_spikes",
    "load_brian2loihi_config",
    "load_spike_trace",
    "normalize_wavefront_config",
    "reconstruct_path_from_parent",
    "replan_from_position",
    "RelayController",
    "run_loihi_delay_demo",
    "run_loihi_lif_demo",
    "run_loihi_small_wavefront_demo",
    "run_loihi_wavefront",
    "save_spike_trace",
    "spike_trace_to_dataframe",
]
