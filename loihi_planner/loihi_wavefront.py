"""核心：Loihi SNN 波前路由。

将 NetworkX 有向图转换为 SNN 并运行波前传播，
找到从起点到目标的最短路径（按累积延迟最小）。

图 → SNN 映射规则:
    - 图节点 v ∈ V → LIF 神经元
    - 有向边 (u→v) ∈ E → 兴奋性突触 u→v，延迟 = edge.delay_ms
    - 起点 start → 输入脉冲注入
    - 目标 target → 监控该神经元的首次发放时间

核心算法:
    1. 将图节点映射到连续的神经元索引
    2. 在起点注入初始脉冲（t=0 时刻）
    3. 所有边转为带延迟的突触:
       - object_api 模式: delay = edge_delay - 1 (补偿 1ms 轴突延迟)
       - brian2_device 模式: delay = edge_delay (ms)
    4. 相同延迟的边合并为一个 LoihiSynapses / Synapses 对象
    5. 运行仿真，记录每个神经元的首次发放时间
    6. 跳过 state="blocked" 的边和自环

关键参数 (Brian2LoihiRuntimeConfig):
    - threshold=1.0: 神经元发放阈值
    - weight=1.1: 突触权重 (必须 > threshold 以保证传播)
    - refractory_ms=1000: 不应期 >> 最大路径延迟 (每个神经元只发放一次)
"""

from __future__ import annotations

import networkx as nx
import numpy as np

from ._brian2_runner import load_brian2loihi_backend
from .backend_check import check_brian2loihi_available
from .wavefront_reference import event_driven_wavefront


def _build_sim_time_ms(G: nx.DiGraph, reference_arrival: float | None, delay_attr: str) -> int:
    """根据图的最大延迟和参考到达时间计算安全的仿真时长。

    仿真时长必须足够长，让波前能到达所有可达节点。
    公式: max(5, reference_arrival + max_delay + 5)。

    Args:
        G: 有向图。
        reference_arrival: CPU 参考算法得到的目标到达时间（None 如果不可达）。
        delay_attr: 边延迟属性名。

    Returns:
        安全仿真时长 (ms)，至少为 5ms。
    """
    # 收集所有非阻塞边的延迟
    delays = [int(attrs.get(delay_attr, 1)) for _, _, attrs in G.edges(data=True) if attrs.get("state") != "blocked"]
    max_delay = max(delays) if delays else 1
    # 参考到达时间 + 最大单跳延迟 + 5ms 余量
    path_bound = int((reference_arrival or 0.0) + max_delay + 5)
    return max(5, path_bound)


def _format_error(
    prefix: str,
    error: str,
    start: int | None = None,
    target: int | None = None,
    sim_time_ms: int | None = None,
    backend: str = "unavailable",
) -> dict:
    """生成统一的错误结果字典。

    Args:
        prefix: 错误类型前缀（如 "Brian2Loihi unavailable"）。
        error: 详细错误信息。
        start, target, sim_time_ms, backend: 上下文信息。

    Returns:
        标准错误字典（success=False）。
    """
    return {
        "backend": backend,
        "start": start,
        "target": target,
        "spike_times_by_neuron": {},
        "target_arrival_time_ms": None,
        "num_spikes": 0,
        "active_neurons": 0,
        "sim_time_ms": sim_time_ms,
        "success": False,
        "error": f"{prefix}: {error}",
    }


def run_loihi_wavefront(
    G: nx.DiGraph,
    start: int,
    target: int,
    delay_attr: str = "delay_ms",
    sim_time_ms: int | None = None,
    threshold: float = 1.0,
    weight: float = 1.1,
    refractory_ms: int = 1000,
    seed: int = 0,
) -> dict:
    """在图 G 上运行 Loihi SNN 波前路由。

    这是项目的核心函数。将图转为 SNN，在起点注入脉冲，
    观察波前通过带延迟突触传播，记录每个节点的首次发放时间。

    Args:
        G: NetworkX 有向图。边必须有 delay_attr 属性。
           节点可以是任意 hashable 类型（内部会映射到整数索引）。
        start: 起点节点 ID。
        target: 目标节点 ID。
        delay_attr: 边延迟属性名（默认 "delay_ms"）。
        sim_time_ms: 仿真时长 (ms)。None 时自动计算。
        threshold: 神经元发放阈值。必须 < weight。
        weight: 突触权重。必须 > threshold (默认 1.1 > 1.0)。
        refractory_ms: 不应期 (ms)。必须 >> 最大路径延迟 (默认 1000)。
        seed: 随机种子。

    Returns:
        字典:
        - backend: 后端名称
        - start, target: 起止节点
        - spike_times_by_neuron: {原始节点ID: 首次发放时间(ms)}
        - target_arrival_time_ms: 目标到达时间 (None = 不可达)
        - num_spikes: 仿真期间总脉冲数
        - active_neurons: 至少发放一次的神经元数
        - sim_time_ms: 实际仿真时长
        - success: 目标是否可达
        - error: 错误消息或 None
    """
    # 步骤 0: 后端检查
    backend_check = check_brian2loihi_available()
    if not backend_check["available"]:
        return _format_error(
            "Brian2Loihi unavailable",
            backend_check["error"] or "unknown backend error",
            start=start,
            target=target,
        )

    backend, error = load_brian2loihi_backend()
    if error:
        return _format_error(
            "Brian2Loihi backend load failed",
            error,
            start=start,
            target=target,
        )

    # 步骤 1: 验证输入
    if start not in G:
        return _format_error("Invalid start node", f"start node {start} not found", start=start, target=target)
    if target not in G:
        return _format_error("Invalid target node", f"target node {target} not found", start=start, target=target)

    # 步骤 2: 运行 CPU 参考算法（用于自动计算仿真时长和后续验证）
    try:
        reference = event_driven_wavefront(G, start, target, delay_attr=delay_attr)
    except Exception as exc:
        return _format_error("Reference wavefront failed", str(exc), start=start, target=target)

    try:
        b2 = backend.brian2

        # 步骤 3: 确定仿真时长
        computed_sim_time_ms = int(sim_time_ms) if sim_time_ms is not None else _build_sim_time_ms(
            G, reference.get("target_arrival_time"), delay_attr
        )

        # ================================================================
        # object_api 模式: 使用 LoihiNeuronGroup / LoihiSynapses
        # ================================================================
        if backend.mode == "object_api":
            loihi = backend.loihi_module
            b2.start_scope()

            # 步骤 4a: 建立节点→神经元索引映射
            # 图节点可能是不连续的 ID (如 0, 5, 12)，需要映射到连续索引
            nodes = list(G.nodes())
            node_index = {node: idx for idx, node in enumerate(nodes)}

            # 步骤 5a: 创建 Loihi 神经元组
            # refractory_steps: 钳制到 [1, 64] 范围 (Loihi 硬件限制)
            refractory_steps = max(1, min(64, int(refractory_ms)))
            # threshold_v_mant: Loihi 使用整数阈值 = round(threshold * 64)
            # 乘以 64 是因为 Loihi 采用 Q6.6 定点数格式
            neurons = loihi.LoihiNeuronGroup(
                len(nodes),
                refractory=refractory_steps,
                threshold_v_mant=max(1, int(round(float(threshold) * 64))),
                decay_v=0,     # 膜电位不泄漏 (纯积分模式)
                decay_I=4096,  # 电流衰减极慢 (4096 表示接近不衰减)
            )

            # 步骤 6a: 创建输入脉冲 (注入到起点神经元)
            input_group = loihi.LoihiSpikeGeneratorGroup(
                1,
                np.array([0], dtype=int),           # 仅 1 个神经元
                np.array([0], dtype=int),           # 在 t=0 发放
            )
            input_synapses = loihi.LoihiSynapses(input_group, neurons, delay=0)
            input_synapses.connect(
                i=np.array([0], dtype=int),
                j=np.array([node_index[start]], dtype=int)
            )
            input_synapses.w = np.array([120], dtype=int)

            # 步骤 7a: 将图边转为 Loihi 突触，按调整后的延迟分组
            # 每组相同延迟的边共享一个 LoihiSynapses 对象 (效率更高)
            # adjusted_delay = delay - 1: 补偿 1ms 的轴突延迟
            delay_groups: dict[int, list[tuple[int, int]]] = {}
            for source, target_node, attrs in G.edges(data=True):
                if attrs.get("state") == "blocked":
                    continue          # 跳过阻塞边
                if source == target_node:
                    continue          # 跳过自环
                delay = int(attrs.get(delay_attr, 0))
                if delay <= 0:
                    continue
                adjusted_delay = max(0, delay - 1)  # 补偿轴突延迟
                delay_groups.setdefault(adjusted_delay, []).append(
                    (node_index[source], node_index[target_node])
                )

            synapse_objects = [input_synapses]
            for adjusted_delay, edges in sorted(delay_groups.items()):
                synapses = loihi.LoihiSynapses(neurons, neurons, delay=adjusted_delay)
                synapses.connect(
                    i=np.array([source for source, _ in edges], dtype=int),
                    j=np.array([target for _, target in edges], dtype=int),
                )
                synapses.w = np.array([120] * len(edges), dtype=int)
                synapse_objects.append(synapses)

            # 步骤 8a: 构建网络并运行仿真
            spike_monitor = loihi.LoihiSpikeMonitor(neurons)
            network = loihi.LoihiNetwork(*([input_group, neurons] + synapse_objects + [spike_monitor]))
            network.run(computed_sim_time_ms)

            # 步骤 9a: 收集各节点的首次发放时间
            spike_times_by_neuron: dict[int, float] = {}
            for neuron_index, spike_time in zip(spike_monitor.i, spike_monitor.t):
                node = nodes[int(neuron_index)]
                # 只记录首次发放时间（由于 refractory >> sim_time, 每个神经元最多发一次）
                if node not in spike_times_by_neuron:
                    spike_times_by_neuron[node] = float(spike_time)

            target_arrival_time_ms = spike_times_by_neuron.get(target)
            success = target_arrival_time_ms is not None
            return {
                "backend": backend.name,
                "start": int(start),
                "target": int(target),
                "spike_times_by_neuron": spike_times_by_neuron,
                "target_arrival_time_ms": target_arrival_time_ms,
                "num_spikes": int(len(spike_monitor.t)),
                "active_neurons": int(len(spike_times_by_neuron)),
                "sim_time_ms": int(computed_sim_time_ms),
                "success": success,
                "error": None if success else f"Target neuron {target} did not spike.",
            }

        # ================================================================
        # brian2_device 模式: 使用标准 Brian2 API
        # ================================================================
        device_name = backend.device_name
        b2.set_device(device_name)
        b2.start_scope()

        # 设置随机种子（如果 Brian2 版本支持）
        if hasattr(b2, "seed"):
            try:
                b2.seed(seed)
            except Exception:
                pass
        b2.defaultclock.dt = 1 * b2.ms

        nodes = list(G.nodes())
        node_index = {node: idx for idx, node in enumerate(nodes)}

        # 步骤 5b: 创建 Brian2 神经元组
        # 指数衰减 LIF: dv/dt = -v / (10ms)
        neurons = b2.NeuronGroup(
            len(nodes),
            model="dv/dt = -v / (10*ms) : 1",
            threshold=f"v > {float(threshold)}",     # 动态阈值
            reset="v = 0",
            refractory=f"{int(refractory_ms)}*ms",   # 长不应期 = 单次发放
            method="euler",
        )
        neurons.v = 0.0

        # 步骤 6b: 输入脉冲
        input_group = b2.SpikeGeneratorGroup(
            1,
            np.array([0], dtype=int),
            np.array([0.0]) * b2.ms,
        )
        input_synapses = b2.Synapses(input_group, neurons, on_pre=f"v_post += {float(weight)}")
        input_synapses.connect(i=np.array([0], dtype=int), j=np.array([node_index[start]], dtype=int))

        # 步骤 7b: 图边 → Brian2 Synapses
        sources: list[int] = []
        targets: list[int] = []
        delays: list[int] = []
        for source, target_node, attrs in G.edges(data=True):
            if attrs.get("state") == "blocked":
                continue
            if source == target_node:
                continue
            delay = int(attrs.get(delay_attr, 0))
            if delay <= 0:
                continue
            sources.append(node_index[source])
            targets.append(node_index[target_node])
            delays.append(delay)

        graph_synapses = b2.Synapses(neurons, neurons, on_pre=f"v_post += {float(weight)}")
        if sources:
            graph_synapses.connect(i=np.array(sources, dtype=int), j=np.array(targets, dtype=int))
            # 为每条边分别设置延迟（支持异构延迟）
            graph_synapses.delay = np.array(delays, dtype=float) * b2.ms

        # 步骤 8b: 运行仿真
        spike_monitor = b2.SpikeMonitor(neurons)
        network = b2.Network(input_group, neurons, input_synapses, graph_synapses, spike_monitor)
        network.run(float(computed_sim_time_ms) * b2.ms)

        # 步骤 9b: 收集首次发放时间
        spike_times_by_neuron: dict[int, float] = {}
        for neuron_index, spike_time in zip(spike_monitor.i, spike_monitor.t):
            node = nodes[int(neuron_index)]
            if node not in spike_times_by_neuron:
                # Brian2 时间单位转换: time / ms → 毫秒
                spike_times_by_neuron[node] = float(spike_time / b2.ms)

        target_arrival_time_ms = spike_times_by_neuron.get(target)
        success = target_arrival_time_ms is not None
        return {
            "backend": backend.name,
            "start": int(start),
            "target": int(target),
            "spike_times_by_neuron": spike_times_by_neuron,
            "target_arrival_time_ms": target_arrival_time_ms,
            "num_spikes": int(len(spike_monitor.t)),
            "active_neurons": int(len(spike_times_by_neuron)),
            "sim_time_ms": int(computed_sim_time_ms),
            "success": success,
            "error": None if success else f"Target neuron {target} did not spike.",
        }
    except Exception as exc:  # pragma: no cover - backend-dependent
        return {
            "backend": backend.name,
            "start": int(start),
            "target": int(target),
            "spike_times_by_neuron": {},
            "target_arrival_time_ms": None,
            "num_spikes": 0,
            "active_neurons": 0,
            "sim_time_ms": int(sim_time_ms) if sim_time_ms is not None else None,
            "success": False,
            "error": str(exc),
        }
