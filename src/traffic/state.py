"""Traffic state models used by the simulated dynamic routing loop."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TrafficEdgeState:
    # edge 使用项目 DiGraph 的 (u, v) 节点 ID，和 SNN neuron/synapse 映射保持同一编号空间。
    edge: tuple[int, int]
    # vehicle_count 只用于 GUI 展示和模拟压力，不代表真实 API 数据。
    vehicle_count: int
    # congestion 归一化到 0..1；越接近 1，delay_factor 越高，也越可能 blocked。
    congestion: float
    delay_factor: float
    blocked: bool = False


@dataclass(frozen=True, slots=True)
class TrafficSnapshot:
    # step 是离散交通帧编号；同一 seed + step 会生成可复现的拥堵状态。
    step: int
    # edge_states 保存本帧所有拥堵边；未出现的边视为 normal。
    edge_states: dict[tuple[int, int], TrafficEdgeState] = field(default_factory=dict)
    # inhibited_nodes 表示被拥堵影响的路口，对应进入该 node/neuron 的延迟惩罚。
    inhibited_nodes: dict[int, float] = field(default_factory=dict)
    # metadata 用于 GUI/调试展示，不参与规划。
    metadata: dict[str, float | int | str] = field(default_factory=dict)

    @property
    def congested_edges(self) -> set[tuple[int, int]]:
        # 便捷集合，供 GUI 统计和 overlay 绘制使用。
        return {edge for edge, state in self.edge_states.items() if state.congestion > 0.0}

    @property
    def blocked_edges(self) -> set[tuple[int, int]]:
        # blocked 边会在 wavefront 中被跳过，等价于 spike 无法沿该突触传播。
        return {edge for edge, state in self.edge_states.items() if state.blocked}
