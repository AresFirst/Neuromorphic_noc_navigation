"""Simulated traffic congestion for dynamic SNN navigation."""

from __future__ import annotations

# traffic 包只提供模拟交通层：生成 TrafficSnapshot，并把它叠加到 DiGraph 上。
from .simulator import TrafficConfig, apply_traffic_to_graph, generate_traffic_snapshot
from .state import TrafficEdgeState, TrafficSnapshot

# 这些对象构成 GUI 动态重规划使用的稳定接口。
__all__ = [
    "TrafficConfig",
    "TrafficEdgeState",
    "TrafficSnapshot",
    "apply_traffic_to_graph",
    "generate_traffic_snapshot",
]
