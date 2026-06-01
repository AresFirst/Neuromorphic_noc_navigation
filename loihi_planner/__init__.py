"""神经形态规划器 —— loihi_planner 包。

本包是项目的核心模块，提供基于 Loihi/Brian2 的脉冲神经网络 (SNN) 波前路由、
路径重建与分析、动态重规划等全部神经形态规划功能。

包的 __init__.py 实现懒加载机制：通过 __getattr__ 延迟导入子模块，
避免一次性加载所有模块的开销，同时保持简洁的 API (from loihi_planner import X)。

数据流摘要:
    输入图 G(start, target)
        → run_loihi_wavefront()           # SNN 波前传播
        → spike_times_by_neuron           # 脉冲时间表
        → infer_parent_trace_from_spikes() # 父节点推断
        → reconstruct_path_from_parent()   # 反向追踪路径
        → compare_snn_path_with_dijkstra() # 最优性对比
        → build_stdp_trace_table()         # STDP 权重分析
"""

from __future__ import annotations

# _EXPORTS: {公开函数名: (模块路径, 属性名)} 映射表
# __getattr__ 通过此表实现懒加载
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
    """懒加载机制：首次访问属性时才导入对应模块。

    这种设计避免了 import loihi_planner 时加载所有子模块
    （包括 brian2 等重量级依赖），显著加快包的导入速度。

    Args:
        name: 要访问的属性名（必须在 _EXPORTS 中注册）。

    Returns:
        导入的模块属性。

    Raises:
        AttributeError: 如果 name 不在 _EXPORTS 中。
    """
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    # 导入目标模块并获取属性
    value = getattr(import_module(module_name), attr_name)
    # 缓存到 globals()，后续访问不再触发 __getattr__
    globals()[name] = value
    return value
