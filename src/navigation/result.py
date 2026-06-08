"""Standard navigation result data structures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class WavefrontFrame:
    # t 是离散 timestep / 毫秒时间点；active_nodes 是该时间点之前已发放的 neuron/node。
    t: int
    # active_edges 表示 spike 已经沿该边完成传播，可用于 GUI 高亮 wavefront 边。
    active_nodes: list[int]
    active_edges: list[tuple[int, int]]

    def to_dict(self) -> dict[str, Any]:
        # Streamlit 调试面板和 JSON 输出需要普通 dict，而不是 dataclass 对象。
        return asdict(self)


@dataclass(slots=True)
class NavigationResult:
    # start_node/goal_node 是项目 DiGraph 节点 ID，同时也是当前实现中的 SNN neuron index。
    start_node: int
    goal_node: int
    # path_nodes/path_edges 是最终回溯出的路线，用于地图 overlay 和车辆位置 slider。
    path_nodes: list[int]
    path_edges: list[tuple[int, int]]
    # wavefront_frames 可为空；为空表示后端没有可视化事件，GUI 会自动隐藏相关控件。
    wavefront_frames: list[WavefrontFrame] = field(default_factory=list)
    # total_cost 使用 planner 指定的 cost_attr 计算，通常是 traffic 后的 cost。
    total_cost: float | None = None
    # metadata 存放调试和展示指标，如 backend、spike_times、路径长度、运行耗时等。
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # 统一序列化入口，避免 GUI/测试重复手写 dataclass 展开逻辑。
        return asdict(self)
