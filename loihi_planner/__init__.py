from __future__ import annotations

_EXPORTS = {
    "check_brian2loihi_available": ("loihi_planner.backend_check", "check_brian2loihi_available"),
    "load_brian2loihi_config": ("loihi_planner.loihi_config", "load_brian2loihi_config"),
    "normalize_wavefront_config": ("loihi_planner.loihi_config", "normalize_wavefront_config"),
    "run_loihi_delay_demo": ("loihi_planner.loihi_delay_demo", "run_loihi_delay_demo"),
    "run_loihi_lif_demo": ("loihi_planner.loihi_lif_demo", "run_loihi_lif_demo"),
    "run_loihi_wavefront": ("loihi_planner.loihi_wavefront", "run_loihi_wavefront"),
    "run_loihi_small_wavefront_demo": ("loihi_planner.loihi_small_wavefront_demo", "run_loihi_small_wavefront_demo"),
    "RelayController": ("loihi_planner.relay_controller", "RelayController"),
    "replan_from_position": ("loihi_planner.dynamic_replanning", "replan_from_position"),
    "compare_snn_path_with_dijkstra": ("loihi_planner.path_compare", "compare_snn_path_with_dijkstra"),
    "compute_path_cost": ("loihi_planner.path_compare", "compute_path_cost"),
    "reconstruct_path_from_parent": ("loihi_planner.path_reconstruction", "reconstruct_path_from_parent"),
    "infer_parent_trace_from_spikes": ("loihi_planner.parent_trace", "infer_parent_trace_from_spikes"),
    "load_spike_trace": ("loihi_planner.spike_trace", "load_spike_trace"),
    "save_spike_trace": ("loihi_planner.spike_trace", "save_spike_trace"),
    "spike_trace_to_dataframe": ("loihi_planner.spike_trace", "spike_trace_to_dataframe"),
    "build_stdp_trace_table": ("loihi_planner.stdp_trace", "build_stdp_trace_table"),
    "event_driven_wavefront": ("loihi_planner.wavefront_reference", "event_driven_wavefront"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
