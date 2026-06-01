"""小图波前传播验证 Demo。

在一个固定的 5 节点图上验证波前传播是否找到正确的路径和到达时间。

图结构 (硬编码):
    节点: 0, 1, 2, 3, 4
    边 (delay):
        0 → 1 (delay=1)
        0 → 2 (delay=3)
        1 → 3 (delay=1)
        2 → 3 (delay=1)
        3 → 4 (delay=1)

起点 = 0, 目标 = 4。
最短路径: 0→1→3→4, 延迟 = 1+1+1 = 3ms。
预期: neuron 4 在 t ≈ 3ms 发放。

这是从"单神经元"到"网络波前"的中间步骤验证。
"""

from __future__ import annotations

import numpy as np

from ._brian2_runner import load_brian2loihi_backend
from .backend_check import check_brian2loihi_available


def run_loihi_small_wavefront_demo() -> dict:
    """在小固定图上运行波前传播验证。

    Returns:
        字典:
        - spike_times_by_neuron: {神经元ID: [发放时间列表]}
        - target_arrival_time_ms: 目标神经元首次发放时间 (ms)
        - success: 目标是否在预期时间附近发放 (误差 ≤ 1ms)
        - error: 错误消息或 None
    """
    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        return {
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "success": False,
            "error": backend_check["error"] or "Brian2Loihi is not available.",
        }

    backend, error = load_brian2loihi_backend()
    if error:
        return {
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "success": False,
            "error": error,
        }

    try:
        b2 = backend.brian2

        # ---- object_api 模式 ----
        if backend.mode == "object_api":
            loihi = backend.loihi_module
            b2.start_scope()

            # 输入: 在 t=0 注入到 neuron 0
            input_group = loihi.LoihiSpikeGeneratorGroup(
                1,
                np.array([0], dtype=int),
                np.array([0], dtype=int),
            )

            # 5 个 LIF 神经元，代表 5 个图节点
            neurons = loihi.LoihiNeuronGroup(
                5,
                refractory=20,
                threshold_v_mant=100,
                decay_v=0,
                decay_I=4096,
            )

            # 输入 → neuron0
            input_synapses = loihi.LoihiSynapses(input_group, neurons, delay=0)
            input_synapses.connect(i=np.array([0], dtype=int), j=np.array([0], dtype=int))
            input_synapses.w = np.array([120], dtype=int)

            # 图边: 按延迟分组
            synapse_objects = [input_synapses]
            edges_by_delay: dict[int, list[tuple[int, int]]] = {
                1: [(0, 1), (1, 3), (2, 3), (3, 4)],  # delay=1ms 的边
                3: [(0, 2)],                              # delay=3ms 的边
            }
            for delay_ms, edges in edges_by_delay.items():
                # 突触延迟 = delay_ms - 1 (补偿 1ms 轴突延迟)
                synapses = loihi.LoihiSynapses(neurons, neurons, delay=max(0, delay_ms - 1))
                synapses.connect(
                    i=np.array([source for source, _target in edges], dtype=int),
                    j=np.array([target for _source, target in edges], dtype=int),
                )
                synapses.w = np.array([120] * len(edges), dtype=int)
                synapse_objects.append(synapses)

            monitor = loihi.LoihiSpikeMonitor(neurons)
            network = loihi.LoihiNetwork(input_group, neurons, *synapse_objects, monitor)
            network.run(8)

            # 收集各神经元的首次发放时间
            spike_times_by_neuron: dict[int, list[float]] = {idx: [] for idx in range(5)}
            for index, time in zip(monitor.i, monitor.t):
                spike_times_by_neuron[int(index)].append(float(time))

            # 目标 neuron 4 应在 t ≈ 3ms (路径 0→1→3→4)
            target_spikes = spike_times_by_neuron[4]
            target_arrival_time_ms = target_spikes[0] if target_spikes else None
            success = target_arrival_time_ms is not None and abs(target_arrival_time_ms - 3.0) <= 1.0
            return {
                "spike_times_by_neuron": spike_times_by_neuron,
                "target_arrival_time_ms": target_arrival_time_ms,
                "success": success,
                "error": None if success else "Target spike did not arrive near the expected time.",
            }

        # ---- brian2_device 模式 ----
        device_name = backend.device_name
        b2.set_device(device_name)
        b2.start_scope()
        b2.defaultclock.dt = 1 * b2.ms

        # 5 个 LIF 神经元
        neurons = b2.NeuronGroup(
            5,
            model="dv/dt = -v / (10*ms) : 1",
            threshold="v > 1.0",
            reset="v = 0",
            method="euler",
        )
        neurons.v = 0.0
        # 直接设置 neuron0 初始电位 = 1.1，使其在 t=0 发放
        neurons.v[0] = 1.1

        # 图边: 5 条边，延迟分别为 [1, 3, 1, 1, 1] ms
        synapses = b2.Synapses(neurons, neurons, on_pre="v_post += 1.1")
        sources = np.array([0, 0, 1, 2, 3], dtype=int)
        targets = np.array([1, 2, 3, 3, 4], dtype=int)
        synapses.connect(i=sources, j=targets)
        # 为每条边分别设置延迟
        synapses.delay = np.array([1, 3, 1, 1, 1], dtype=float) * b2.ms

        monitor = b2.SpikeMonitor(neurons)
        network = b2.Network(neurons, synapses, monitor)
        network.run(8 * b2.ms)

        spike_times_by_neuron: dict[int, list[float]] = {idx: [] for idx in range(5)}
        for index, time in zip(monitor.i, monitor.t):
            spike_times_by_neuron[int(index)].append(float(time / b2.ms))

        target_spikes = spike_times_by_neuron[4]
        target_arrival_time_ms = target_spikes[0] if target_spikes else None
        success = target_arrival_time_ms is not None and abs(target_arrival_time_ms - 3.0) <= 1.0
        return {
            "spike_times_by_neuron": spike_times_by_neuron,
            "target_arrival_time_ms": target_arrival_time_ms,
            "success": success,
            "error": None if success else "Target spike did not arrive near the expected time.",
        }
    except Exception as exc:  # pragma: no cover - backend-dependent
        return {
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "success": False,
            "error": str(exc),
        }
