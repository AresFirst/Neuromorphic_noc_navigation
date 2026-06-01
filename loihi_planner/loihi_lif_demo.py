"""单神经元 LIF 验证 Demo。

验证最基本的 Loihi LIF 神经元是否能接收输入脉冲并成功发放。
这是整个项目的最底层验证——如果这个 demo 失败，
更深层的波前路由也不可能工作。

测试设置:
- 1 个输入 → 1 个 LIF 神经元
- 输入在 t=0 时刻发放 1 个脉冲
- 突触权重 = 120 (远大于阈值 threshold_v_mant=100)
- 预期: 神经元应在 t=0 或 t=1 时刻发放 1 个脉冲

支持两种后端模式: object_api (LoihiNeuronGroup) 和 brian2_device (NeuronGroup)。
"""

from __future__ import annotations

import numpy as np

from ._brian2_runner import load_brian2loihi_backend
from .backend_check import check_brian2loihi_available


def run_loihi_lif_demo() -> dict:
    """运行单神经元 LIF 发放验证。

    Returns:
        字典:
        - backend: 后端名称 ("unavailable" 如果不可用)
        - num_spikes: 发放的脉冲数
        - spike_times_ms: 脉冲发放时间列表 (ms)
        - success: 是否成功 (至少 1 个脉冲)
        - error: 错误消息或 None
    """
    # 快速检查: 后端是否可用
    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        return {
            "backend": "unavailable",
            "num_spikes": 0,
            "spike_times_ms": [],
            "success": False,
            "error": backend_check["error"] or "Brian2Loihi is not available.",
        }

    # 加载后端
    backend, error = load_brian2loihi_backend()
    if error:
        return {
            "backend": "unavailable",
            "num_spikes": 0,
            "spike_times_ms": [],
            "success": False,
            "error": error,
        }

    try:
        b2 = backend.brian2

        # ---- object_api 模式: 使用 LoihiNeuronGroup 等直接 API ----
        if backend.mode == "object_api":
            loihi = backend.loihi_module
            b2.start_scope()

            # 输入: 1 个脉冲生成器，在 t=0 时刻发放
            input_group = loihi.LoihiSpikeGeneratorGroup(
                1,
                np.array([0], dtype=int),  # 神经元编号 = 0
                np.array([0], dtype=int),  # 发放时间 = 0
            )

            # LIF 神经元: 1 个神经元
            # threshold_v_mant=100: 阈值的 mantissa 部分 (Loihi 整数表示)
            # decay_v=0: 膜电位不泄漏 (纯积分)
            # decay_I=4096: 电流衰减极慢
            neurons = loihi.LoihiNeuronGroup(
                1,
                refractory=10,       # 不应期 = 10 steps
                threshold_v_mant=100, # 阈值 (整数), 100 < 突触权重 120 → 保证发放
                decay_v=0,           # 无泄漏
                decay_I=4096,        # 慢速电流衰减
            )

            # 兴奋性突触: input → neuron, delay=0 (立即传导)
            synapses = loihi.LoihiSynapses(input_group, neurons, delay=0)
            synapses.connect(i=np.array([0], dtype=int), j=np.array([0], dtype=int))
            synapses.w = np.array([120], dtype=int)  # 权重 120 > 阈值 100

            # 脉冲监控
            monitor = loihi.LoihiSpikeMonitor(neurons)
            network = loihi.LoihiNetwork(input_group, neurons, synapses, monitor)
            network.run(5)  # 运行 5 个 time steps

            spike_times_ms = [float(time) for time in monitor.t]
            return {
                "backend": backend.name,
                "num_spikes": len(spike_times_ms),
                "spike_times_ms": spike_times_ms,
                "success": len(spike_times_ms) >= 1,
                "error": None if spike_times_ms else "The neuron did not spike.",
            }

        # ---- brian2_device 模式: 使用 Brian2 标准 API ----
        device_name = backend.device_name
        b2.set_device(device_name)
        b2.start_scope()
        b2.defaultclock.dt = 1 * b2.ms  # 1ms 时间步

        # 输入: SpikeGeneratorGroup, t=0ms
        input_group = b2.SpikeGeneratorGroup(1, np.array([0], dtype=int), np.array([0.0]) * b2.ms)

        # 标准 LIF 神经元: dv/dt = -v/τ, threshold=1.0
        neurons = b2.NeuronGroup(
            1,
            model="dv/dt = -v / (10*ms) : 1",
            threshold="v > 1.0",
            reset="v = 0",
            method="euler",
        )
        neurons.v = 0.0

        # 突触: pre 脉冲时 v_post += 1.1 (> threshold 1.0)
        synapses = b2.Synapses(input_group, neurons, on_pre="v_post += 1.1")
        synapses.connect()
        monitor = b2.SpikeMonitor(neurons)

        network = b2.Network(input_group, neurons, synapses, monitor)
        network.run(5 * b2.ms)

        # 转换 Brian2 时间单位到毫秒
        spike_times_ms = [float(time / b2.ms) for time in monitor.t]
        return {
            "backend": device_name,
            "num_spikes": len(spike_times_ms),
            "spike_times_ms": spike_times_ms,
            "success": len(spike_times_ms) >= 1,
            "error": None if spike_times_ms else "The neuron did not spike.",
        }
    except Exception as exc:  # pragma: no cover - backend-dependent
        return {
            "backend": backend.name,
            "num_spikes": 0,
            "spike_times_ms": [],
            "success": False,
            "error": str(exc),
        }
